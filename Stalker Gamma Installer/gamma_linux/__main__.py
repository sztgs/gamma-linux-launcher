"""Command line entry point. No arguments opens the GUI."""

import argparse
import sys

from . import VERSION
from .common import Cancelled
from .config import CONFIG_FILE, Config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gamma-launcher", description="S.T.A.L.K.E.R. G.A.M.M.A. for Linux")
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="open the launcher window (default)")
    sub.add_parser("install", help="install or update G.A.M.M.A. (also retries failed mods)")
    sub.add_parser("update", help="same as install")
    sub.add_parser("repair", help="re-download and rebuild every mod that comes from an archive")
    sub.add_parser("prefix", help="(re)create the Wine prefix dependencies")
    p = sub.add_parser("play", help="start the game through Mod Organizer")
    p.add_argument("--exe", help="MO2 executable title, e.g. 'Anomaly (DX11)'")
    sub.add_parser("mo2", help="open the Mod Organizer 2 window")
    sub.add_parser("shortcuts", help="create desktop and menu shortcuts")
    c = sub.add_parser("config", help="show or change settings: config key=value ...")
    c.add_argument("pairs", nargs="*")
    args = ap.parse_args(argv)

    if args.cmd in (None, "gui"):
        from .gui import main as gui_main
        return gui_main()

    cfg = Config()
    try:
        if args.cmd in ("install", "update", "repair"):
            from .installer import Installer
            return 0 if Installer(cfg, repair=args.cmd == "repair").run() else 1
        if args.cmd == "prefix":
            from .prefix import setup_prefix
            setup_prefix(cfg)
        elif args.cmd == "play":
            from .prefix import launch
            launch(cfg, args.exe or cfg.get("executable"))
        elif args.cmd == "mo2":
            from .prefix import launch
            launch(cfg)
        elif args.cmd == "shortcuts":
            from .shortcuts import create
            create(cfg)
        elif args.cmd == "config":
            for pair in args.pairs:
                key, _, value = pair.partition("=")
                if key not in cfg:
                    sys.exit(f"unknown setting '{key}'")
                old = cfg[key]
                cfg[key] = (value.lower() in ("1", "true", "yes")) if isinstance(old, bool) else \
                    int(value) if isinstance(old, int) else value
            if args.pairs:
                cfg.save()
            print(f"# {CONFIG_FILE}")
            for k, v in cfg.items():
                print(f"{k} = {v}")
    except Cancelled:
        print("Cancelled.")
        return 130
    except Exception as exc:
        print(f"[!] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
