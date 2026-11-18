"""User settings, stored in ~/.config/gamma-linux/config.json."""

import json
import os
from pathlib import Path

from .common import atomic_write, expand

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gamma-linux"
CONFIG_FILE = CONFIG_DIR / "config.json"

COMPAT_DIRS = [
    Path.home() / ".steam/steam/compatibilitytools.d",
    Path.home() / ".local/share/Steam/compatibilitytools.d",
    Path("/usr/share/steam/compatibilitytools.d"),
]
PREFERRED_PROTON = "GE-Proton10-34"


def find_protons() -> list:
    """Every Proton build found in Steam's compatibilitytools.d folders."""
    seen, result = set(), []
    for d in COMPAT_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            real = p.resolve()
            if (p / "proton").is_file() and real not in seen:
                seen.add(real)
                result.append(str(p))
    return result


def _default_proton() -> str:
    protons = find_protons()
    for p in protons:
        if Path(p).name == PREFERRED_PROTON:
            return p
    return protons[0] if protons else ""


DEFAULTS = {
    # Existing Anomaly 1.5.3 install folder (it will be created if an archive is given).
    "anomaly_dir": "~/Games/GAMMA/Anomaly",
    # Optional: Anomaly 1.5.3 archive(s) to extract into anomaly_dir, separated by ';'.
    "anomaly_archive": "",
    # Mod Organizer 2 instance: mods/, downloads/, profiles/, ModOrganizer.exe.
    "gamma_dir": "~/Games/GAMMA/GAMMA",
    "prefix_dir": "~/Games/GAMMA/Prefix",
    "proton_path": "",
    "mo2_version": "v2.5.2",
    "jobs": 4,
    "keep_archives": False,
    "skip_disabled": False,
    "gamma_repo": "Grokitach/Stalker_GAMMA",
    "gamma_branch": "main",
    "executable": "Anomaly (DX11-AVX)",
}


class Config(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        if CONFIG_FILE.is_file():
            try:
                self.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        if not self.get("proton_path"):
            self["proton_path"] = _default_proton()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write(CONFIG_FILE, json.dumps(self, indent=2) + "\n")

    def path(self, key: str) -> Path:
        return expand(self[key])

    @property
    def anomaly_dir(self) -> Path:
        return self.path("anomaly_dir")

    @property
    def gamma_dir(self) -> Path:
        return self.path("gamma_dir")

    @property
    def prefix_dir(self) -> Path:
        return self.path("prefix_dir")

    @property
    def data_dir(self) -> Path:
        """Launcher bookkeeping inside the GAMMA folder (state, git repos, temp, logs)."""
        return self.gamma_dir / ".gamma-linux"
