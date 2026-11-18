"""Install / update S.T.A.L.K.E.R. G.A.M.M.A. into a Mod Organizer 2 instance.

Every folder in mods/ is a "target" built from one or more sources, in order:
  1. the archive from the GAMMA mod list (ModDB / GitHub), using its install directives
  2. gamma_large_files_v2 / teivaz_anomaly_gunslinger repo folders
  3. gamma_setup's modpack_addons (old base files), then Stalker_GAMMA's modpack_addons
Each target has a fingerprint of its sources. Running the installer again only
rebuilds targets whose fingerprint changed, so the same command installs,
updates, and retries anything that failed last time.
"""

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from . import archive, gitops, moddb, net
from .common import (Cancelled, atomic_write, ci_child, ci_resolve, disk_name, events, expand,
                     free_bytes, human, is_no_space, log, merge_tree, rmtree)
from .config import Config
from .modpack import match_entries, parse_maker_list, parse_modlist

PROFILE = "G.A.M.M.A"
GAME_FOLDERS = ("appdata", "db", "gamedata")
PLACEHOLDER = "/start/222467"          # GAMMA's "provided elsewhere" URL (the main menu theme)
PLACEHOLDER_REAL_TITLE = "Main Menu Theme - Deathcard Cabin"
SKIP_NAMES = {"164- Hunger Thirst Sleep UI 0.71 - xcvb"}
SKIP_TITLES = {"FDDA Redone Fixes"}
GUNSLINGER_PREFIX = "312- Gunslinger Guns for Anomaly"
EXECUTABLES = [
    ("Anomaly (DX11-AVX)", "bin/AnomalyDX11AVX.exe"),
    ("Anomaly (DX11)", "bin/AnomalyDX11.exe"),
    ("Anomaly (DX9-AVX)", "bin/AnomalyDX9AVX.exe"),
    ("Anomaly (DX9)", "bin/AnomalyDX9.exe"),
    ("Anomaly Launcher", "AnomalyLauncher.exe"),
]
GITHUB_ARCHIVE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/archive/(?:refs/(heads|tags)/)?(.+)\.zip$")
MIN_FREE = 60 * 1024 ** 3


class InstallError(Exception):
    pass


@dataclass
class Target:
    name: str
    state: str = ""                                 # '+', '-' or '' (not in modlist)
    separator: bool = False
    entry: object = None                            # MakerEntry to download, if any
    version: str = ""                               # resolved version of a mutable GitHub ref
    parts: list = field(default_factory=list)       # [(kind, path, sha)] repo sources
    fp: str = ""

    def fingerprint(self) -> str:
        e = self.entry
        data = [self.name, self.separator,
                [e.url, e.directives, self.version] if e else None,
                [(k, s) for k, _, s in self.parts]]
        return hashlib.sha1(json.dumps(data).encode()).hexdigest()


def win_path(p: Path) -> str:
    return "Z:" + str(p).replace("/", "\\")


class Installer:
    def __init__(self, cfg: Config, repair: bool = False):
        self.cfg = cfg
        self.repair = repair        # rebuild every mod that comes from an archive
        self.gamma = cfg.gamma_dir
        self.anomaly = cfg.anomaly_dir
        self.data = cfg.data_dir
        self.repos = self.data / "repos"
        self.mods = self.gamma / "mods"
        self.downloads = self.gamma / "downloads"
        self.tmp = self.data / "tmp"
        self.state_file = self.data / "state.json"
        self.state = {}
        self.failures = []
        self._lock = threading.Lock()
        self._bytes = 0

    # ------------------------------------------------------------------ state
    def load_state(self):
        try:
            self.state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.state = {}
        self.state.setdefault("targets", {})

    def save_state(self):
        with self._lock:
            atomic_write(self.state_file, json.dumps(self.state, indent=1))

    def _warn(self, name, msg):
        with self._lock:
            self.state.setdefault("warnings", {})[disk_name(name)] = msg

    # ------------------------------------------------------------------ main
    def run(self) -> bool:
        """Install / update. Everything logged is also written to .gamma-linux/logs/install.log."""
        logs = self.data / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        logfile = open(logs / "install.log", "w", encoding="utf-8")
        screen = events.log_cb

        def tee(msg):
            screen(msg)
            logfile.write(msg + "\n")
            logfile.flush()
        events.log_cb = tee
        try:
            return self._run()
        except Exception as exc:
            logfile.write(f"[!] ERROR: {exc}\n")
            raise
        finally:
            events.log_cb = screen
            logfile.close()

    def _run(self) -> bool:
        started = time.monotonic()
        events.cancel.clear()
        self.preflight()
        self.load_state()
        self.ensure_anomaly()
        revs = self.sync_repos()
        self.ensure_mo2()
        self.patch_anomaly()
        targets = self.build_plan()
        self.remove_obsolete(targets)
        self.apply(targets)
        self.write_profile()
        rmtree(self.tmp)
        self.state["definition"] = revs["definition"]
        self.save_state()
        mins = (time.monotonic() - started) / 60
        warnings = {n: m for n, m in self.state.get("warnings", {}).items() if n in {t.name for t in targets}}
        if warnings:
            log(f"\n[i] {len(warnings)} mod(s) did not match GAMMA's install rules (same as the official launcher):")
            for name, msg in sorted(warnings.items()):
                log(f"   - {name}: {msg}")
        if self.failures:
            log(f"\n[!] Finished in {mins:.0f} min with {len(self.failures)} problem(s):")
            for name, msg in self.failures:
                log(f"   - {name}: {msg}")
            log("\nRun Install / Update again to retry only the failed mods.")
            return False
        log(f"\n[+] G.A.M.M.A. is installed and up to date ({mins:.0f} min). Good hunting, stalker.")
        return True

    # ------------------------------------------------------------------ steps
    def preflight(self):
        missing = [t for t in ("git",) if not shutil.which(t)]
        if not shutil.which("umu-run"):
            log("[!] umu-run not found: installing works, but you need umu-launcher to play.")
        if not archive.find_7z():
            missing.append("7z (p7zip / 7zip)")
        if missing:
            raise InstallError("Missing required programs: " + ", ".join(missing))
        for p in (self.gamma, self.mods, self.downloads, self.data, self.tmp):
            p.mkdir(parents=True, exist_ok=True)
        free = free_bytes(self.gamma)
        log(f"[+] GAMMA folder: {self.gamma}  ({human(free)} free)")
        if free < MIN_FREE and not (self.mods / "G.A.M.M.A. Large Files").is_dir():
            log(f"[!] WARNING: a full install needs roughly 100+ GiB, only {human(free)} free here.")
        rmtree(self.tmp)
        self.tmp.mkdir(parents=True)

    def ensure_anomaly(self):
        exe = self.anomaly / "bin" / "AnomalyDX11AVX.exe"
        if exe.is_file():
            log(f"[+] Anomaly found: {self.anomaly}")
            return
        archives = [expand(a) for a in self.cfg.get("anomaly_archive", "").split(";") if a.strip()]
        if not archives:
            raise InstallError(
                f"Anomaly 1.5.3 not found in {self.anomaly} (no bin/AnomalyDX11AVX.exe).\n"
                "Set the Anomaly folder to your extracted Anomaly 1.5.3, or pick the Anomaly archive to extract.")
        self.anomaly.mkdir(parents=True, exist_ok=True)
        for a in archives:
            log(f"[+] Extracting {a.name} into {self.anomaly} (this takes a while)...")
            archive.extract(a, self.anomaly)
        # archives sometimes contain a single top folder
        if not exe.is_file():
            inner = [p for p in self.anomaly.iterdir() if (p / "bin" / "AnomalyDX11AVX.exe").is_file()]
            if len(inner) == 1:
                for child in list(inner[0].iterdir()):
                    os.replace(child, self.anomaly / child.name)
                inner[0].rmdir()
        if not exe.is_file():
            raise InstallError("Extracted the Anomaly archive but bin/AnomalyDX11AVX.exe is still missing.")

    def repo_specs(self) -> dict:
        return {
            "definition": (f"https://github.com/{self.cfg['gamma_repo']}", self.cfg["gamma_branch"]),
            "setup": ("https://github.com/Grokitach/gamma_setup", "main"),
            "large": ("https://github.com/Grokitach/gamma_large_files_v2", "main"),
            "gunslinger": ("https://github.com/Grokitach/teivaz_anomaly_gunslinger", "main"),
        }

    def sync_repos(self) -> dict:
        revs = {}
        for key, (url, branch) in self.repo_specs().items():
            log(f"[+] Syncing {url.split('github.com/')[1]} ...")
            sha, changed = net.with_retries(key, lambda: gitops.sync(url, self.repos / key, branch))
            revs[key] = sha
            log(f"    {'updated to' if changed else 'up to date at'} {sha[:10]}")
        defdir = self.repos / "definition"
        ver = defdir / "G.A.M.M.A_definition_version.txt"
        if ver.is_file():
            log(f"[+] G.A.M.M.A. definition version {ver.read_text().strip()}")
        return revs

    def ensure_mo2(self):
        exe = self.gamma / "ModOrganizer.exe"
        if not exe.is_file():
            v = self.cfg["mo2_version"]
            url = f"https://github.com/ModOrganizer2/modorganizer/releases/download/{v}/Mod.Organizer-{v.lstrip('v')}.7z"
            log(f"[+] Downloading Mod Organizer 2 {v}")
            f = net.with_retries("MO2", lambda: net.download(url, self.downloads / "_mo2"))
            work = self.tmp / "mo2"
            archive.extract(f, work)
            found = next(iter(sorted(work.rglob("ModOrganizer.exe"), key=lambda p: len(p.parts))), None)
            if not found:
                raise InstallError("Mod Organizer archive did not contain ModOrganizer.exe")
            merge_tree(found.parent, self.gamma, link=False)
            rmtree(work)
        (self.gamma / "portable.txt").touch()
        for d in ("overwrite", f"profiles/{PROFILE}"):
            (self.gamma / d).mkdir(parents=True, exist_ok=True)
        self.write_mo2_ini()
        icon = self.repos / "definition" / "G.A.M.M.A" / "modpack_data" / "modpack_icon.ico"
        if icon.is_file():
            shutil.copy2(icon, self.data / "gamma.ico")

    def write_mo2_ini(self):
        ini = self.gamma / "ModOrganizer.ini"
        game = win_path(self.anomaly).replace("\\", "\\\\")
        if ini.is_file():
            text = ini.read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"(?m)^gamePath=.*$", lambda _: f"gamePath=@ByteArray({game})", text)
            atomic_write(ini, text)
            return
        lines = [
            "[General]",
            "gameName=STALKER Anomaly",
            f"gamePath=@ByteArray({game})",
            f"selected_profile=@ByteArray({PROFILE})",
            "first_start=false",
            "",
            "[Settings]",
            "check_for_updates=false",
            "language=en",
            "",
            "[customExecutables]",
            f"size={len(EXECUTABLES)}",
        ]
        anomaly_fwd = "Z:" + str(self.anomaly)
        for i, (title, rel) in enumerate(EXECUTABLES, 1):
            lines += [
                f"{i}\\arguments=",
                f"{i}\\binary={anomaly_fwd}/{rel}",
                f"{i}\\hide=false",
                f"{i}\\ownicon=true",
                f"{i}\\steamAppID=",
                f"{i}\\title={title}",
                f"{i}\\toolbar={'true' if i == 1 else 'false'}",
                f"{i}\\workingDirectory={anomaly_fwd}",
            ]
        atomic_write(ini, "\r\n".join(lines) + "\r\n")

    def patch_anomaly(self):
        """GAMMA replaces some Anomaly files (modded exes, configs, shaders)."""
        sources = [(self.repos / "setup", "modpack_patches"),
                   (self.repos / "definition", "G.A.M.M.A/modpack_patches")]
        key = "|".join(gitops.tree_sha(repo, sub) or "-" for repo, sub in sources)
        key += "|" + str(self.anomaly)
        if self.state.get("patches") == key:
            log("[+] Anomaly patches already applied")
            return
        log("[+] Applying G.A.M.M.A. patches to Anomaly")
        first = "patches" not in self.state
        user_ltx = ci_resolve(self.anomaly, "appdata/user.ltx")
        saved = user_ltx.read_bytes() if (user_ltx and not first) else None
        for repo, sub in sources:
            src = repo / sub
            if src.is_dir():
                merge_tree(src, self.anomaly, link=False)
        user_ltx = ci_resolve(self.anomaly, "appdata/user.ltx")
        if saved is not None:
            (user_ltx or self.anomaly / "appdata" / "user.ltx").write_bytes(saved)
            log("    kept your existing user.ltx (settings / keybinds)")
        elif user_ltx:
            text = user_ltx.read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"(?m)^rs_screenmode\s+\S+", "rs_screenmode borderless", text)
            user_ltx.write_text(text, encoding="utf-8")
        cache = ci_resolve(self.anomaly, "appdata/shaders_cache")
        if cache:
            rmtree(cache)
        self.state["patches"] = key
        self.save_state()

    # ------------------------------------------------------------------ plan
    def build_plan(self) -> list:
        defdir = self.repos / "definition" / "G.A.M.M.A"
        modlist = parse_modlist((defdir / "modpack_data" / "modlist.txt").read_text(encoding="utf-8", errors="replace"))
        entries = parse_maker_list((defdir / "modpack_data" / "modpack_maker_list.txt").read_text(encoding="utf-8", errors="replace"))
        names = [n for _, n in modlist]
        states = {disk_name(n): s for s, n in modlist}
        matched, unmatched = match_entries(names, entries)
        for e in unmatched:
            log(f"    note: '{e.title}' has no folder in modlist.txt, skipped")

        targets = {}

        def target(name) -> Target:
            name = disk_name(name)
            if name not in targets:
                targets[name] = Target(name=name, state=states.get(name, ""))
            return targets[name]

        for _, n in modlist:
            if n.endswith("_separator"):
                target(n).separator = True

        large = gitops.subtrees(self.repos / "large")
        gun_sha = gitops.head(self.repos / "gunslinger")
        gun_name = next((n for n in names if n.startswith(GUNSLINGER_PREFIX)),
                        f"{GUNSLINGER_PREFIX} - Teivazcz & Gunslinger Team")
        provided = {disk_name(n) for n in large} | {disk_name(gun_name)}

        for name, e in matched.items():
            dn = disk_name(name)
            if name in SKIP_NAMES or e.title in SKIP_TITLES:
                continue
            if dn in provided:
                continue
            if self.cfg.get("skip_disabled") and states.get(dn) == "-":
                continue
            target(name).entry = e

        for n, sha in large.items():
            target(n).parts.append(("dir", self.repos / "large" / n, sha))
        target(gun_name).parts.append(("gamedata", self.repos / "gunslinger", gun_sha))
        for repo, sub in ((self.repos / "setup", "modpack_addons"),
                          (self.repos / "definition", "G.A.M.M.A/modpack_addons")):
            for n, sha in gitops.subtrees(repo, sub).items():
                target(n).parts.append(("dir", repo / sub / n, sha))

        # The placeholder URL means "files come from GAMMA's repos"; only download it
        # when nothing else provides the folder (same result as the official installer).
        for t in targets.values():
            if t.entry and PLACEHOLDER in t.entry.url and t.parts and t.entry.title != PLACEHOLDER_REAL_TITLE:
                t.entry = None

        self.resolve_versions([t for t in targets.values() if t.entry])
        for t in targets.values():
            t.fp = t.fingerprint()
        return list(targets.values())

    def resolve_versions(self, targets):
        """Branch/tag archives on GitHub change without the URL changing: pin them to a commit."""
        cache = {}
        for t in targets:
            m = GITHUB_ARCHIVE.match(t.entry.url)
            if not m or (m.group(3) is None and re.fullmatch(r"[0-9a-f]{40}", m.group(4))):
                continue
            user, repo, kind, ref = m.groups()
            key = (user, repo, kind or "heads", ref)
            if key not in cache:
                cache[key] = gitops.ls_remote(f"https://github.com/{user}/{repo}", f"refs/{kind or 'heads'}/{ref}") or ""
            t.version = cache[key]

    # ------------------------------------------------------------------ apply
    def remove_obsolete(self, targets):
        wanted = {t.name for t in targets}
        for name in list(self.state["targets"]):
            if name not in wanted:
                log(f"[-] Removing mod no longer in G.A.M.M.A.: {name}")
                rmtree(self.mods / name)
                del self.state["targets"][name]
        self.save_state()

    def apply(self, targets):
        done = self.state["targets"]
        dirty = [t for t in targets if done.get(t.name) != t.fp or not (self.mods / t.name).is_dir()
                 or (self.repair and t.entry)]
        groups = defaultdict(list)
        local = []
        for t in dirty:
            (groups[(t.entry.url, t.version)] if t.entry else local).append(t)
        total = len(dirty)
        log(f"[+] {len(targets)} mods in G.A.M.M.A., {total} to install/update "
            f"({len(groups)} downloads)")
        if not total:
            return
        self._done = 0
        self._total = total

        for t in local:
            events.check_cancel()
            self._build_guarded(t, None)

        jobs = max(1, int(self.cfg.get("jobs", 4)))
        pool = ThreadPoolExecutor(max_workers=jobs)
        try:
            futures = {pool.submit(self._process_group, key, ts): ts for key, ts in groups.items()}
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Cancelled:
                    raise
                except Exception as exc:
                    if is_no_space(exc):
                        events.cancel.set()
                        raise InstallError("The disk is full. Free some space (or move the GAMMA folder) "
                                           "and run Install / Update again; finished mods are kept.")
                    for t in futures[fut]:
                        self.failures.append((t.name, self._describe(t, exc)))
                        self._tick(t.name, failed=True)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def _tick(self, name, failed=False):
        with self._lock:
            self._done += 1
            done = self._done
        events.progress(done, self._total, name)
        log(f"[{done}/{self._total}] {'FAILED' if failed else 'OK'}  {name}")

    def _describe(self, t, exc) -> str:
        e = t.entry
        msg = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        where = self.downloads / self.cache_key(e)
        hint = (f"\n       manual fix: download it from {e.info_url or e.url}\n"
                f"       and put the file into: {where}/") if e else ""
        return msg + hint

    def _build_guarded(self, t, extracted):
        try:
            self.build_target(t, extracted)
            self._tick(t.name)
        except Cancelled:
            raise
        except Exception as exc:
            if is_no_space(exc):
                raise
            self.failures.append((t.name, str(exc)))
            self._tick(t.name, failed=True)

    def _process_group(self, key, targets):
        e = targets[0].entry
        f = self.fetch(e, targets[0].version)
        work = self.tmp / uuid.uuid4().hex
        try:
            archive.extract(f, work)
            for t in targets:
                events.check_cancel()
                self._build_guarded(t, work)
        finally:
            rmtree(work)
        if not self.cfg.get("keep_archives"):
            rmtree(f.parent)

    # ------------------------------------------------------------------ download
    @staticmethod
    def cache_key(e) -> str:
        fid = moddb.file_id(e.url) if "moddb.com" in e.url else None
        if fid:
            return f"moddb-{fid}"
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", "-".join(e.url.split("/")[3:5]))[:60]
        return f"gh-{slug}-{hashlib.sha1(e.url.encode()).hexdigest()[:8]}"

    def fetch(self, e, version: str) -> Path:
        d = self.downloads / self.cache_key(e)
        d.mkdir(parents=True, exist_ok=True)
        marker = d / ".version"
        if version and marker.is_file() and marker.read_text().strip() != version:
            for f in d.iterdir():
                rmtree(f)
        have = [f for f in d.iterdir() if f.is_file() and not f.name.startswith(".")]
        is_moddb = "moddb.com" in e.url
        info = {}
        if is_moddb and e.info_url and "moddb.com" in e.info_url:
            try:
                info = moddb.addon_info(e.info_url)
            except Exception:
                info = {}
        md5 = info.get("md5") or (None if is_moddb else e.md5)

        for f in have:          # cached, or dropped in manually by the user
            if archive.sniff(f) and (not md5 or self._md5(f) == md5.lower() or not is_moddb):
                return f
            f.unlink()

        if is_moddb:
            f = self._fetch_moddb(e, d, md5)
        else:
            f = net.with_retries(e.title, lambda: net.download(e.url, d, on_bytes=self._count))
            if not archive.sniff(f):
                f.unlink()
                raise InstallError("download is not an archive")
            if md5 and self._md5(f) != md5:
                log(f"    note: {e.title}: checksum differs from the mod list (GitHub file was updated), using it anyway")
        if version:
            marker.write_text(version)
        return f

    def _fetch_moddb(self, e, d: Path, md5) -> Path:
        links = net.with_retries(f"{e.title} (ModDB page)", lambda: moddb.mirror_links(e.url))
        if not links:
            raise InstallError("ModDB page has no download mirror (blocked or file removed)")
        last = None
        for link in links:
            try:
                url = net.with_retries(f"{e.title} (mirror)", lambda: moddb.resolve_mirror(link))
                f = net.with_retries(e.title, lambda: net.download(url, d, on_bytes=self._count))
                if not archive.sniff(f):
                    f.unlink()
                    raise InstallError("mirror returned a web page instead of the file")
                if md5 and self._md5(f) != md5.lower():
                    f.unlink()
                    raise InstallError("MD5 checksum mismatch")
                return f
            except Cancelled:
                raise
            except Exception as exc:
                if is_no_space(exc):
                    raise
                last = exc
                log(f"    {e.title}: mirror failed ({exc}), trying next")
        raise last

    def _count(self, n):
        with self._lock:
            self._bytes += n

    @staticmethod
    def _md5(path: Path) -> str:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    # ------------------------------------------------------------------ build
    def build_target(self, t: Target, extracted):
        staging = self.mods / f".staging-{uuid.uuid4().hex[:12]}"
        try:
            staging.mkdir()
            if t.separator:
                (staging / "meta.ini").write_text(SEPARATOR_META)
            if t.entry and extracted is not None:
                with self._lock:
                    self.state.setdefault("warnings", {}).pop(t.name, None)
                self.install_entry(t.entry, extracted, staging, has_other_sources=bool(t.parts))
            for kind, src, _ in t.parts:
                if kind == "dir":
                    merge_tree(src, staging)
                else:
                    for gd in sorted(src.rglob("gamedata")):
                        if gd.is_dir() and ".git" not in gd.parts:
                            merge_tree(gd, staging / "gamedata")
            if not (staging / "meta.ini").exists():
                (staging / "meta.ini").write_text(self.meta_ini(t))
            dest = self.mods / t.name
            rmtree(dest)
            os.replace(staging, dest)
        finally:
            rmtree(staging)
        with self._lock:
            self.state["targets"][t.name] = t.fp
        self.save_state()

    def install_entry(self, e, root: Path, dest: Path, has_other_sources: bool = False):
        roots = [root]
        missing = []
        for d in e.directives:
            p = ci_resolve(root, d)
            if p is None or not p.is_dir():
                missing.append(d)
            else:
                roots.append(p)
        if missing:
            top = ", ".join(sorted(p.name for p in root.iterdir() if p.is_dir())[:4])
            msg = (f"folder(s) {', '.join(repr(m) for m in missing)} named by GAMMA are not in the archive "
                   f"(it contains: {top}). The mod was probably updated on ModDB")
            log(f"    warning: {e.title}: {msg}")
            self._warn(e.name or e.title, msg)
        fomod = self._fomod_map(root)
        placed = 0
        for r in roots:
            dest_sub = fomod.get(str(r.relative_to(root)).lower()) if r != root else None
            if dest_sub is not None:
                placed += merge_tree(r, dest / dest_sub if dest_sub else dest)
                continue
            if r.name.lower() in GAME_FOLDERS and r != root:
                placed += merge_tree(r, dest / r.name.lower())
                continue
            for gf in GAME_FOLDERS:
                c = ci_child(r, gf)
                if c and c.is_dir():
                    placed += merge_tree(c, dest / gf)
        if placed == 0 and not e.directives:
            # '0' means "the archive root", but some archives wrap everything in one folder.
            # Only follow that when it is unambiguous; never guess between several folders
            # (that would pull optional patches or a newer, incompatible version).
            found = sorted((p for p in root.rglob("*") if p.is_dir() and p.name.lower() == "gamedata"),
                           key=lambda p: len(p.parts))
            shallowest = [p for p in found if len(p.parts) == len(found[0].parts)] if found else []
            if len(shallowest) == 1:
                for gf in GAME_FOLDERS:
                    c = ci_child(shallowest[0].parent, gf)
                    if c and c.is_dir():
                        placed += merge_tree(c, dest / gf)
                log(f"    note: {e.title}: installed from '{shallowest[0].parent.relative_to(root)}'")
        if placed == 0 and not has_other_sources:
            raise InstallError("nothing to install: the archive layout does not match GAMMA's install "
                               "rules (the mod was probably updated on ModDB)")
        if placed == 0:
            log(f"    note: {e.title}: using G.A.M.M.A.'s bundled files for this mod only")

    @staticmethod
    def _fomod_map(root: Path) -> dict:
        cfg = ci_resolve(root, "fomod/ModuleConfig.xml")
        if not cfg:
            return {}
        try:
            tree = ET.parse(cfg)
        except ET.ParseError:
            return {}
        result = {}
        for el in tree.iter():
            if el.tag.split("}")[-1] == "folder" and "source" in el.attrib:
                src = el.attrib["source"].replace("\\", "/").strip("/").lower()
                result[src] = el.attrib.get("destination", "").replace("\\", "/").strip("/")
        return result

    def meta_ini(self, t: Target) -> str:
        e = t.entry
        url = (e.info_url or e.url) if e else ""
        return (
            "[General]\n"
            "gameName=stalkeranomaly\n"
            "modid=0\n"
            "version=\n"
            "newestVersion=\n"
            "category=\"-1,\"\n"
            "installationFile=\n"
            "repository=\n"
            f"url={url}\n"
            f"hasCustomURL={'true' if url else 'false'}\n"
            "\n[installedFiles]\nsize=0\n"
        )

    # ------------------------------------------------------------------ profile
    def write_profile(self):
        """Write the G.A.M.M.A profile, keeping mods you enabled/disabled yourself."""
        prof = self.gamma / "profiles" / PROFILE
        prof.mkdir(parents=True, exist_ok=True)
        new_text = (self.repos / "definition" / "G.A.M.M.A" / "modpack_data" / "modlist.txt").read_text(
            encoding="utf-8", errors="replace")
        new_def = parse_modlist(new_text)
        old_def_file = self.data / "modlist.definition.txt"
        old_def = dict((n, s) for s, n in parse_modlist(old_def_file.read_text(encoding="utf-8"))) \
            if old_def_file.is_file() else {}
        cur_file = prof / "modlist.txt"
        current = parse_modlist(cur_file.read_text(encoding="utf-8", errors="replace")) if cur_file.is_file() else []
        cur = dict((n, s) for s, n in current)
        known = {n for _, n in new_def} | set(old_def)

        out = ["# This file was automatically generated by Mod Organizer."]
        # mods you added yourself stay on top (highest priority)
        out += [f"{s}{n}" for s, n in current if n not in known]
        kept = 0
        for s, n in new_def:
            dn = disk_name(n)
            if n in cur and n in old_def and cur[n] != old_def[n]:
                s = cur[n]
                kept += 1
            out.append(f"{s}{dn}")
        if cur_file.is_file():
            shutil.copy2(cur_file, prof / "modlist.txt.bak")
        atomic_write(cur_file, "\r\n".join(out) + "\r\n")
        atomic_write(old_def_file, new_text)
        settings = prof / "settings.txt"
        if not settings.is_file():
            settings.write_text("[General]\r\nLocalSaves=false\r\nLocalSettings=true\r\n"
                                "AutomaticArchiveInvalidation=false\r\n")
        for f in ("archives.txt", "plugins.txt", "loadorder.txt"):
            (prof / f).touch()
        log(f"[+] Profile '{PROFILE}' written" + (f" (kept {kept} of your own mod toggles)" if kept else ""))


SEPARATOR_META = ("[General]\nmodid=0\nversion=\nnewestVersion=\ncategory=0\ninstallationFile=\n"
                  "\n[installedFiles]\nsize=0\n")
