"""Shallow git clones of GAMMA's GitHub repositories (fast updates, exact change detection)."""

import os
import subprocess
import time
from pathlib import Path

from .common import events, log, rmtree

GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


class GitError(Exception):
    pass


def git(*args, cwd=None, check=True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, errors="replace")
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed:\n{r.stderr.strip()[-800:]}")
    return r.stdout


def _git_progress(args, cwd=None) -> None:
    """Run a long git command, echoing its progress every few seconds."""
    p = subprocess.Popen(["git", *args], cwd=cwd, env=GIT_ENV, stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE, text=True, errors="replace", bufsize=1)
    last, tail, buf = 0.0, [], ""
    while True:
        if events.cancel.is_set():
            p.kill()
            p.wait()
            events.check_cancel()
        ch = p.stderr.read(1)
        if not ch:
            break
        if ch in "\r\n":
            line, buf = buf.strip(), ""
            if line:
                tail = (tail + [line])[-10:]
                if time.monotonic() - last > 5:
                    log(f"    {line}")
                    last = time.monotonic()
        else:
            buf += ch
    if p.wait() != 0:
        raise GitError(f"git {args[0]} failed:\n" + "\n".join(tail))


def head(repo: Path) -> str:
    return git("rev-parse", "HEAD", cwd=repo).strip()


def sync(url: str, dest: Path, branch: str = "main") -> tuple:
    """Clone (depth 1) or fast-forward `dest`. Returns (sha, changed)."""
    if (dest / ".git").is_dir():
        old = head(dest)
        git("remote", "set-url", "origin", url, cwd=dest)
        _git_progress(["fetch", "--depth", "1", "--progress", "origin", branch], cwd=dest)
        new = git("rev-parse", "FETCH_HEAD", cwd=dest).strip()
        if new == old and not git("status", "--porcelain", cwd=dest).strip():
            return old, False
        git("reset", "--hard", "-q", "FETCH_HEAD", cwd=dest)
        git("clean", "-fdq", cwd=dest)
        if new != old:
            # drop the previous snapshot so shallow repos don't keep growing
            git("reflog", "expire", "--expire=now", "--all", cwd=dest, check=False)
            git("gc", "--prune=now", "--quiet", cwd=dest, check=False)
        return new, new != old
    tmp = dest.with_name(dest.name + ".cloning")
    rmtree(tmp)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git_progress(["clone", "--depth", "1", "--single-branch", "--branch", branch, "--progress", url, str(tmp)])
    git("config", "core.fileMode", "false", cwd=tmp)
    os.replace(tmp, dest)
    return head(dest), True


def tree_sha(repo: Path, path: str):
    out = git("rev-parse", f"HEAD:{path}", cwd=repo, check=False).strip()
    return out or None


def subtrees(repo: Path, path: str = "") -> dict:
    """{folder name: tree sha} for the folders directly inside `path`."""
    out = git("ls-tree", "-z", f"HEAD:{path}" if path else "HEAD", cwd=repo, check=False)
    result = {}
    for item in out.split("\0"):
        if "\t" not in item:
            continue
        meta, name = item.split("\t", 1)
        mode, kind, sha = meta.split()
        if kind == "tree":
            result[name] = sha
    return result


def ls_remote(url: str, ref: str):
    try:
        out = git("ls-remote", url, ref, ref + "^{}")
    except GitError:
        return None
    lines = [l.split("\t") for l in out.splitlines() if "\t" in l]
    peeled = [sha for sha, r in lines if r.endswith("^{}")]
    return (peeled or [sha for sha, _ in lines] or [None])[0]
