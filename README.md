# Gamma Launcher for Linux! 
So i just vibecoded it to hell with claude but it work so well i am deciding to share it. anyone that is actually good in programming feel free to fork it if you want to deslopfiy it.

# BEFORE YOU START! 
If you encounter a problem please check if its the launchers fault before reporting anything to the GAMMA Discord. 
## Requirements
| What | Why |
|---|---|
| Python 3.10+ with **tkinter** | runs the launcher (not needed for the standalone binary) |
| **git** | G.A.M.M.A.'s definition and large-file repositories |
| **7z** (7-Zip or p7zip, with RAR support) | extracting mods |
| **umu-run** (umu-launcher) | running Mod Organizer / the game with Proton |
| A **Proton** build, e.g. GE-Proton | GE-Proton10-34 is known to work |
| ~100 GiB free disk space | Anomaly + G.A.M.M.A. (ideally on a Linux filesystem, not NTFS) |


Optional: `unrar` (fallback for some RAR archives) and `xdg-utils` (the "open folder" buttons).

**Fedora / Nobara**
```
sudo dnf install python3 python3-tkinter git 7zip umu-launcher
```
**Arch / CachyOS / EndeavourOS**
```
sudo pacman -S python tk git 7zip umu-launcher
```
**Debian / Ubuntu / Mint**
```
sudo apt install python3 python3-tk git 7zip
```

For Proton Use Either ProtonUp-Qt Or ProtonPlus as it uses it from steam. (I recommend Proton GE-10-34)

## Usage
Run `./gamma-launcher` (or the packaged `dist/gamma-launcher`) to open the GUI.

1. **Settings**: set the Anomaly 1.5.3 folder. If you only have the archive, pick an empty folder
   and select the archive, and it will be extracted for you. Choose where G.A.M.M.A. and the Wine
   prefix go, and pick a Proton build.
2. **INSTALL**: the first run takes a while. Afterwards the same button updates.
3. **PLAY**: the first launch prepares the Wine prefix.

Command line:
```
gamma-launcher install    # install / update / retry failed mods
gamma-launcher repair     # re-download and rebuild every mod that comes from an archive
gamma-launcher play       # start the game through Mod Organizer
gamma-launcher mo2        # open Mod Organizer 2 to toggle mods
gamma-launcher prefix     # (re)install prefix dependencies
gamma-launcher shortcuts  # desktop + menu entries
gamma-launcher config gamma_dir=/path jobs=6   # change settings
```

## Building an executable
```
./build.sh                # dist/gamma-launcher: single file (~40 KB), needs system python3 + tkinter
./build.sh --standalone   # dist/gamma-launcher-standalone: bundles Python + Tk (~18 MB), via PyInstaller
```
The standalone build downloads PyInstaller into `build/venv` the first time. Both still need git,
7z and umu-run on the system.

## When a download fails
The summary at the end of an install lists every failed mod with its page and a folder, for example
`…/GAMMA/downloads/moddb-123456/`. Download the file in your browser, drop it into that folder,
and press Install / Update again.

## Mods updated on ModDB
Some ModDB authors replace their file after G.A.M.M.A. wrote its install rules, so the folder
G.A.M.M.A. names is no longer in the archive. Like the official launcher, the installer then uses
only G.A.M.M.A.'s bundled files for that mod and never guesses which folder to take. These mods are
listed at the end of every install and counted under *Notices* on the ZONE tab.

## Files
- Settings: `~/.config/gamma-linux/config.json`
- Launcher data (state, repos, logs): `<GAMMA folder>/.gamma-linux/`
- Install log (last run): `<GAMMA folder>/.gamma-linux/logs/install.log`
- Game launch log: `<GAMMA folder>/.gamma-linux/logs/launch.log`
- Game crash log: `<Anomaly folder>/appdata/logs/xray_*.log`

## Troubleshooting
- **Crash with a Lua error at load**: check the crash log for the script name, then look at which
  folders in `mods/` provide that script. A file left over from a different version of a mod is the
  usual cause.
- **"pure virtual function call"** and similar random engine crashes also happen on Windows. Save often.
- To save outside campfires: in-game MCM → *Yet Another Campfire Saving* → untick campfire saving.

## Credits
G.A.M.M.A. by Grokitach and the G.A.M.M.A. team, and every mod author in the pack.
S.T.A.L.K.E.R. Anomaly by the Anomaly team. Mod Organizer 2 by its contributors.


## Performence

As for performence it rans really well. my Specs are as follows 
AMD Ryzen 5 5600x 
32GB ddr4 3200MT/s
5070 TI 16gb VRAM 
Some Samsung Mvme (1600mb/s i think)
OS: Nobara Linux 44 (Fedora based) 

and it ran really well i was seeing like 80 fps? i ran so smooth i didn't even look at fps. i encountered Crashes but mostly it was Just unlucky ones.

## Issue Reporting

If you see a issue that is tied to the launcher please report it! 
