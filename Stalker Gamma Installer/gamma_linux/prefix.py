"""Wine prefix setup and launching through umu-run + Proton (same approach as SPT on Linux)."""

import os
import shutil
import subprocess
from pathlib import Path

from .common import events, log
from .config import Config

WINETRICKS_VERBS = ["vcrun2022", "d3dx9", "d3dx10_43", "d3dx11_43", "d3dcompiler_43", "d3dcompiler_47"]
MARKER = ".gamma-linux-prefix"


class LaunchError(Exception):
    pass


def umu_env(cfg: Config) -> dict:
    proton = cfg.get("proton_path", "")
    if not proton or not (Path(os.path.expanduser(proton)) / "proton").is_file():
        raise LaunchError(f"Proton not found at '{proton}'. Pick a Proton build (e.g. GE-Proton10-34) in settings.")
    if not shutil.which("umu-run"):
        raise LaunchError("umu-run is not installed (package: umu-launcher).")
    env = os.environ.copy()
    env.update({
        "WINEPREFIX": str(cfg.prefix_dir),
        "PROTONPATH": os.path.expanduser(proton),
        "PROTON_VERB": "waitforexitandrun",
    })
    return env


def prefix_ready(cfg: Config) -> bool:
    m = cfg.prefix_dir / MARKER
    return m.is_file() and m.read_text().split() == WINETRICKS_VERBS


def setup_prefix(cfg: Config) -> None:
    env = umu_env(cfg)
    cfg.prefix_dir.mkdir(parents=True, exist_ok=True)
    log(f"[+] Setting up Wine prefix {cfg.prefix_dir}")
    log(f"    Proton: {env['PROTONPATH']}")
    log(f"    Installing: {' '.join(WINETRICKS_VERBS)} (a few minutes, ignore wine warnings)")
    p = subprocess.Popen(["umu-run", "winetricks", "-q", *WINETRICKS_VERBS], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    for line in p.stdout:
        if events.cancel.is_set():
            p.kill()
            events.check_cancel()
        line = line.rstrip()
        if line.startswith(("Executing", "------", "Using winetricks", "winetricks")) or "error" in line.lower():
            log(f"    {line[:200]}")
    if p.wait() != 0:
        raise LaunchError("winetricks failed, see the log above. You can retry with 'Setup prefix'.")
    (cfg.prefix_dir / MARKER).write_text(" ".join(WINETRICKS_VERBS))
    log("[+] Prefix ready")


def launch(cfg: Config, shortcut: str = None) -> subprocess.Popen:
    """Start Mod Organizer 2. With `shortcut`, MO2 starts that executable directly (the game)."""
    mo2 = cfg.gamma_dir / "ModOrganizer.exe"
    if not mo2.is_file():
        raise LaunchError("Mod Organizer is not installed yet, run Install / Update first.")
    if not prefix_ready(cfg):
        setup_prefix(cfg)
    env = umu_env(cfg)
    logs = cfg.data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    args = ["umu-run", str(mo2)] + ([f"moshortcut://:{shortcut}"] if shortcut else [])
    log(f"[+] Starting {'G.A.M.M.A. (' + shortcut + ')' if shortcut else 'Mod Organizer 2'}  "
        f"(log: {logs / 'launch.log'})")
    out = open(logs / "launch.log", "w")
    return subprocess.Popen(args, cwd=cfg.gamma_dir, env=env, stdout=out, stderr=subprocess.STDOUT,
                            start_new_session=True)
