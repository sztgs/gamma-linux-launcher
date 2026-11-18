"""Shared helpers: event sink (log/progress/cancel) and filesystem utilities."""

import errno
import os
import re
import shutil
import stat
import sys
import threading
from pathlib import Path


class Cancelled(Exception):
    pass


class Events:
    """Where long-running code reports to. The GUI swaps the callbacks."""

    def __init__(self):
        self.log_cb = lambda msg: print(msg, flush=True)
        self.progress_cb = lambda done, total, label: None
        self.cancel = threading.Event()
        self._lock = threading.Lock()

    def log(self, msg: str) -> None:
        with self._lock:
            self.log_cb(msg)

    def progress(self, done: int, total: int, label: str = "") -> None:
        with self._lock:
            self.progress_cb(done, total, label)

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


events = Events()
log = events.log


def expand(p) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(p)))).absolute()


def disk_name(name: str) -> str:
    """Windows (and therefore Wine/MO2) drops trailing spaces and dots."""
    return name.strip().rstrip(" .")


def free_bytes(path: Path) -> int:
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def is_no_space(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and exc.errno == errno.ENOSPC


def _force_writable(func, path, *_):
    try:
        parent = os.path.dirname(path)
        os.chmod(parent, os.stat(parent).st_mode | stat.S_IWUSR | stat.S_IXUSR)
        os.chmod(path, os.lstat(path).st_mode | stat.S_IWUSR)
    except OSError:
        pass
    func(path)


def rmtree(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if os.path.isfile(path) or os.path.islink(path):
        os.unlink(path)
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force_writable)
    else:
        shutil.rmtree(path, onerror=_force_writable)


def ci_child(parent: Path, name: str):
    """Find `name` inside `parent` ignoring case (and trailing spaces/dots)."""
    p = parent / name
    if os.path.lexists(p):
        return p
    try:
        entries = os.listdir(parent)
    except (FileNotFoundError, NotADirectoryError):
        return None
    low = name.lower()
    for e in entries:
        if e.lower() == low:
            return parent / e
    low = disk_name(low)
    for e in entries:
        if disk_name(e.lower()) == low:
            return parent / e
    return None


def ci_resolve(root: Path, rel: str):
    cur = root
    for part in (p for p in re.split(r"[\\/]+", rel) if p):
        cur = ci_child(cur, part)
        if cur is None:
            return None
    return cur


def place_file(src: Path, dst: Path, link: bool) -> None:
    if link:
        try:
            os.link(src, dst)
            return
        except OSError:
            pass
    shutil.copy2(src, dst)


def merge_tree(src: Path, dst: Path, link: bool = True) -> int:
    """Copy `src` into `dst`, overwriting files and merging folders whose names
    differ only by case (Windows mods are not case-consistent, Linux is).
    Files are hard-linked when possible (instant, no extra disk space).
    Returns the number of files placed."""
    dst.mkdir(parents=True, exist_ok=True)
    existing = {n.lower(): n for n in os.listdir(dst)}
    count = 0
    with os.scandir(src) as it:
        for e in it:
            name = existing.get(e.name.lower(), e.name)
            target = dst / name
            if e.is_dir(follow_symlinks=False):
                if os.path.lexists(target) and not target.is_dir():
                    os.unlink(target)
                count += merge_tree(Path(e.path), target, link)
            else:
                if os.path.lexists(target):
                    if target.is_dir() and not target.is_symlink():
                        rmtree(target)
                    else:
                        os.unlink(target)
                place_file(Path(e.path), target, link)
                count += 1
            existing[e.name.lower()] = name
    return count


def make_writable(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            p = os.path.join(dirpath, d)
            m = os.lstat(p).st_mode
            if not stat.S_ISLNK(m) and (m & 0o700) != 0o700:
                os.chmod(p, m | 0o700)
        for f in filenames:
            p = os.path.join(dirpath, f)
            m = os.lstat(p).st_mode
            if not stat.S_ISLNK(m) and not m & stat.S_IWUSR:
                os.chmod(p, m | stat.S_IWUSR | stat.S_IRUSR)


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"
