# 🎣 Metin2 Fishing Bot

A visual automation bot for the Metin2 fishing mini-games. It re-baits and casts
the rod automatically while fishing, and can solve the jigsaw puzzle mini-game.
Modern single-window UI — and every "smart" upgrade is **optional**: the original
behaviour is fully preserved as the default.

> ⚠️ **Disclaimer.** For educational purposes only. Automating gameplay typically
> violates the game's Terms of Service and may get your account banned. Use at
> your own risk. See [`LICENSE.txt`](LICENSE.txt).

## ✨ Features

**Fishing** — the original core, unchanged:

- Auto re-bait, cast, and play the catch mini-game.
- Adjustable delays (0.1–20 s) for bait / cast / mini-game start.
- Optional "stop after X minutes".

**Puzzle mini-game** — original solver kept as default, improvements opt-in:

- **Solver method:** _Default_ (the original greedy + opening book) or
  _AI-optimized_ (a provably optimal strategy via exact MDP value iteration).
- **Board detection:** _Default_ (fixed position) / _Auto_ (image match) /
  _Mark_ (calibrate once with a draggable grid overlay).
- **Colour sampling:** _Single_ pixel (default) or _Multi_ pixel (more robust).

**UI & quality of life:**

- One window, one big **START / STOP** button, a **Fishing | Puzzle** switch
  (mutually exclusive), a built-in **live log**, and all settings persisted.

## ⬇️ Download & Run

Grab the latest build from the **Releases** page:

| File                         | What it is                                                        |
| ---------------------------- | ----------------------------------------------------------------- |
| `Metin2FishBot-Portable.exe` | **Portable** — a single file, just double-click. No installation. |

> It is **unsigned**. Windows SmartScreen / Defender may show a generic warning
> for any new unsigned app — see [the note below](#-why-does-defender-sometimes-flag-it).

## 🎮 In-game setup

- Run the game in **800×600**, **windowed** (not fullscreen).
- Keep the game window **fully visible** (not minimized). This is a _visual_ bot —
  it moves your real mouse, so you can't use the PC while it runs.
- Put the **fishing skill on hotkey `1`** and the **bait on hotkey `2`**, and equip
  the rod.
- Start the app **as administrator**.
- For the puzzle: open the mini-game and don't move its window.

If your game window is not named `Metin2`, change it in `constants.py` and rebuild.

## 🛠️ Build from source

Requires **Python 3.11–3.13 (64-bit)** on Windows.

```bat
pip install -r requirements.txt
build.bat            :: -> dist_onefile\Metin2FishBot.exe (the portable single file)
```

- **Portable single file (what `build.bat` does):** `pyinstaller --noconfirm --distpath dist_onefile Metin2FishBot_onefile.spec`
- **Headless tests:** `python -m unittest discover -s tests`

## 🦠 Why does Defender sometimes flag it?

Freshly built, **unsigned** PyInstaller executables often trigger _generic
heuristic_ false-positives (e.g. `Wacatac`). This build is hardened against that
(no UPX, real PE metadata), but only a **code-signing certificate** removes it
for certain. If you run into a warning, you can verify the build on
[VirusTotal](https://www.virustotal.com) and report a false positive to Microsoft.

## 📁 Project layout

```
interface/         new CustomTkinter UI          tools/        HTML companion tools
images/            template images               tests/        headless test suite
assets/icon/       app icon (svg / ico / png)    *.spec        PyInstaller build specs
trained_solver.py  AI puzzle solver (MDP)        version.py    single version source
fishingbot.py      fishing core (original)       puzzle.py     puzzle core (original base)
```

## 🙏 Credits

This project is a reworked fork of
**[vncsms/Metin2FishBot](https://github.com/vncsms/Metin2FishBot)** (and
contributors), which itself builds on
**[learncodebygaming/opencv_tutorials](https://github.com/learncodebygaming/opencv_tutorials)**.
The original **fishing mechanic** and the **puzzle-detection base** are preserved
as the **default** behaviour; this version adds a new UI and optional
improvements on top. Full, file-level breakdown in **[`NOTICE`](NOTICE)**.

## 📄 License

The original project ships **without a license**, so rights to the inherited
parts remain with their original authors (see [`NOTICE`](NOTICE)). New and
reworked parts are © **Musketier Software**. Provided **as-is**, without warranty.
See [`LICENSE.txt`](LICENSE.txt).
