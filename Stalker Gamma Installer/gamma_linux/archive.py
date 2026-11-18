"""Archive extraction through the 7z CLI (zip / 7z / rar), with Windows-path cleanup."""

import os
import shutil
import subprocess
from pathlib import Path

from .common import make_writable, merge_tree, rmtree

MAGIC = (
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
)


class ArchiveError(Exception):
    pass


def sniff(path: Path):
    with open(path, "rb") as f:
        head = f.read(8)
    for magic, kind in MAGIC:
        if head.startswith(magic):
            return kind
    return None


def find_7z():
    for name in ("7z", "7zz", "7za"):
        if shutil.which(name):
            return name
    return None


def extract(archive: Path, dest: Path) -> None:
    kind = sniff(archive)
    if kind is None:
        raise ArchiveError(f"{archive.name} is not a zip/7z/rar archive "
                           "(the server probably sent an error page instead of the file)")
    dest.mkdir(parents=True, exist_ok=True)
    tool = find_7z()
    ok, output = False, "7z not found"
    if tool:
        r = subprocess.run([tool, "x", "-y", "-bd", f"-o{dest}", str(archive)],
                           capture_output=True, text=True, errors="replace")
        ok, output = r.returncode in (0, 1), (r.stdout + r.stderr)
    if not ok and kind == "rar" and shutil.which("unrar"):
        r = subprocess.run(["unrar", "x", "-o+", "-idq", str(archive), str(dest) + os.sep],
                           capture_output=True, text=True, errors="replace")
        ok, output = r.returncode == 0, (r.stdout + r.stderr)
    if not ok:
        tail = "\n".join(output.strip().splitlines()[-6:])
        raise ArchiveError(f"failed to extract {archive.name}:\n{tail}")
    make_writable(dest)
    fix_backslash_names(dest)


def fix_backslash_names(root: Path) -> None:
    """Some Windows-made archives store 'gamedata\\scripts\\x.script' as one file name."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames + dirnames:
            if "\\" not in name:
                continue
            src = Path(dirpath) / name
            dst = Path(dirpath).joinpath(*[p for p in name.split("\\") if p])
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                merge_tree(src, dst, link=False)
                rmtree(src)
            else:
                os.replace(src, dst)
