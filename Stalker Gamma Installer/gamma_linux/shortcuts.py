"""Desktop / application-menu entries."""

import shutil
import subprocess
from pathlib import Path

from .common import log
from .config import Config

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "gamma-launcher"


def desktop_dir() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
        if out and Path(out).is_dir():
            return Path(out)
    except OSError:
        pass
    return Path.home() / "Desktop"


def create(cfg: Config) -> None:
    icon = cfg.data_dir / "gamma.ico"
    icon_line = f"Icon={icon}" if icon.is_file() else "Icon=applications-games"
    entries = {
        "gamma-launcher.desktop": ("G.A.M.M.A. Launcher", f'"{LAUNCHER}"'),
        "gamma-play.desktop": ("S.T.A.L.K.E.R. G.A.M.M.A.", f'"{LAUNCHER}" play'),
    }
    apps = Path.home() / ".local/share/applications"
    apps.mkdir(parents=True, exist_ok=True)
    desk = desktop_dir()
    for fname, (name, exe) in entries.items():
        text = (f"[Desktop Entry]\nType=Application\nName={name}\nExec={exe}\n"
                f"Path={ROOT}\n{icon_line}\nCategories=Game;ActionGame;\nTerminal=false\n")
        for d in (apps, desk):
            p = d / fname
            p.write_text(text)
            p.chmod(0o755)
        if shutil.which("gio"):
            subprocess.run(["gio", "set", str(desk / fname), "metadata::trusted", "true"],
                           capture_output=True)
    log(f"[+] Shortcuts created on {desk} and in the application menu")
