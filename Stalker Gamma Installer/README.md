# G.A.M.M.A. Linux Launcher

Linux-native installer, updater and launcher for S.T.A.L.K.E.R. G.A.M.M.A.
It builds the same Mod Organizer 2 setup the official Windows launcher makes, then runs it
through `umu-run` + Proton (the same approach as your SPT install).

## Requirements
`python3` (with tkinter), `git`, `7z`, `umu-run`, and a Proton build (GE-Proton10-34 is preselected).
All of these are already on this machine. No pip packages are needed.

## Usage
```
./gamma-launcher            # GUI
./gamma-launcher install    # install / update / retry failed mods (CLI)
./gamma-launcher repair     # re-download and rebuild every mod that comes from an archive
./gamma-launcher play       # start the game (through MO2)
./gamma-launcher mo2        # open Mod Organizer 2 to toggle mods
./gamma-launcher prefix     # (re)install prefix dependencies
./gamma-launcher config gamma_dir=/path jobs=6   # change settings
```

1. Set **Anomaly 1.5.3 folder** to your extracted Anomaly. If you only have the archive, choose an
   empty folder and pick the archive under *Anomaly archive*; it will be extracted for you.
2. Choose the **G.A.M.M.A. folder** (Mod Organizer instance) and the **Wine prefix folder**.
   Keep everything on a Linux filesystem (btrfs/ext4) if you can. A full install needs about 100 GiB.
3. **Install / Update**. Takes a while the first time. Run it again any time to update.
   Only changed mods are re-downloaded, and failed ones are retried.
4. **▶ Play**. The first launch sets up the prefix (vcrun2022, d3dx9/10/11, d3dcompiler).
5. **Create shortcuts** adds "S.T.A.L.K.E.R. G.A.M.M.A." and the launcher to the desktop and menu.

## What it does
- Shallow-clones GAMMA's GitHub repos (`Stalker_GAMMA`, `gamma_large_files_v2`,
  `teivaz_anomaly_gunslinger`, `gamma_setup`) and pins every other GitHub mod to a commit.
- Downloads each mod from the GAMMA mod list (ModDB / GitHub) in parallel, with resume, retries,
  ModDB mirror fallback and MD5 checks. It then installs only the folders GAMMA specifies, merging
  folders whose names differ only by case (a common cause of broken Linux installs).
- Builds each mod in a staging folder and swaps it in, so an interrupted run never leaves half a mod.
- Patches Anomaly with GAMMA's files. On updates your `user.ltx` (settings and keybinds) is kept.
- Writes the `G.A.M.M.A` MO2 profile. On updates, mods you enabled or disabled yourself keep
  your choice, and mods you added yourself stay.

## When a download fails
The summary at the end lists every failed mod with its page and a folder, for example
`…/GAMMA/downloads/moddb-123456/`. Download the file in your browser, drop it into that
folder, and run Install / Update again.

## Files
- Settings: `~/.config/gamma-linux/config.json`
- Launcher data (state, repos, logs): `<GAMMA folder>/.gamma-linux/`
- Install log (last run): `<GAMMA folder>/.gamma-linux/logs/install.log`
- Game launch log: `<GAMMA folder>/.gamma-linux/logs/launch.log`
- Game crash log: `<Anomaly folder>/appdata/logs/xray_*.log`

## Mods updated on ModDB
Some ModDB authors replace their file after GAMMA wrote its install rules, so the folder GAMMA
names is no longer in the archive. Like the official launcher, the installer then uses only
GAMMA's bundled files for that mod and never guesses which folder to take. These mods are listed
at the end of every install run.
