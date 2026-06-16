# 🎣 Metin2 Fishing Bot

A visual automation bot for the Metin2 fishing mini-games. It re-baits and casts
the rod automatically while fishing, and can solve the jigsaw puzzle mini-game.
Modern single-window UI — and every "smart" upgrade is **optional**: the original
behaviour is fully preserved as the default.

> ⚠️ **Disclaimer.** For educational purposes only. Automating gameplay typically
> violates the game's Terms of Service and may get your account banned. Use at
> your own risk. See [`LICENSE.txt`](LICENSE.txt).

## 🆕 What's new in 1.2.12

- **Energiesplitter: NPC recognition now works across all camera angles.** The
  NPC name was never recognised (`ncc=0.0`) despite being clearly visible. Fixed,
  validated against **all 17 provided NPC images** (8 Alchemist + 9 weapon
  dealer): (1) the name template was never loaded (a doubled `npc_` key →
  `npc/npc_alchemist.png` instead of `npc/alchemist.png`), (2) the search region
  cropped NPCs pushed to the screen edge by the camera (recalibrated to the full
  measured span), (3) a new CI test asserts the NPC is found in every provided
  perspective (NCC 0.87–0.99).

## 🆕 What's new in 1.2.11

- **Energiesplitter: the game window is now focused during a run.** Keystrokes
  (like the bird's-eye `g`) only reach the **focused** window — without focus they
  went to the bot window and did nothing in-game, so the camera never switched and
  the NPC stayed "not recognisable" (`ncc=0.0`, endless retries). The bot now
  brings the game to the foreground at run start and before every keystroke (plain
  `SetForegroundWindow`, no process access). Applies to both NPCs (Alchemist +
  weapon dealer).

## 🆕 What's new in 1.2.10

- **Energiesplitter: first sharp run.** Fixed a crash when addressing the NPC
  (`t() got multiple values for argument 'key'` — a latent bug that could only
  surface now that v1.2.9 lets the bot actually reach the flow). And the
  **bird's-eye view** is now used properly when the NPC isn't recognised: the bot
  toggles bird's-eye (key `g`), **gives the camera time to switch** (~0.8 s) and
  **retries several times** (alternating normal/bird's-eye, up to 4 attempts)
  before cleanly stopping with "NPC not recognisable". F6 stops anytime.

## 🆕 What's new in 1.2.9

- **Energiesplitter fixes: it stood idle, kept "running" and couldn't be stopped.**
  Three root causes fixed: (1) the hammer/dagger/NPC **templates were not bundled
  into the EXE**, so the Phase-0 gate was always red ("item:hammer / npc:alchemist
  not found") and the bot never acted; (2) the start/stop button stayed red on
  "Stop" after the bot self-stopped, so clicking it **restarted** instead of
  stopping (endless restart loop) — the buttons now always mirror the real run
  state; (3) the debug log now states **in plain language what is missing**
  ("Alchemist not recognisable", "window not 800x600", "inventory grid not
  calibrated") and cleanly separates "not ready" from "simulation (flip
  Sharp/Live)". Errors always auto-stop, and F6 always stops.

## 🆕 What's new in 1.2.8

- **Energiesplitter simplified + settings cleaned up.** Yang no longer matters
  (price/balance/spend tracking and the Yang reader were removed entirely; the
  bot just buys and processes, with action caps and detect-before-action as the
  safety net). Hammers are always bought as **200-stacks** (you only enter how
  many stacks); daggers are processed **one after another**. The settings panel
  is now fully German, grouped and scrollable, with the risky timing knobs under
  an "Advanced" group. Default stays simulation; you consciously flip "Scharf/
  Live" for real purchases.

## 🆕 What's new in 1.2.6

- **Energiesplitter module: now calibrated and armable.** Inventory grid, hammer/
  dagger recognition, NPC detection and the **Yang reader** are calibrated from
  real game frames, so the module can buy and process for real. It still starts
  **safe**: the default is simulation — you consciously flip "Scharf/Live" before
  any real Yang is spent (recommended first run: small hammer count, supervised).
  Detect-before-action means a miscalibration cleanly stops instead of mis-
  clicking; Yang reserve / spend / action caps guard every purchase. New
  **"Yang check"** toggle (default on): off = the bot won't abort if the Yang
  balance is briefly unreadable (spend/action caps still bound it).

## 🆕 What's new in 1.2.5

- **New "Energiesplitter" module (preview).** Own tab with a split start button
  (buy hammers / buy + process daggers), a hammer-count input with a Yang cost
  calculator, dedicated settings and extensive logs. **Not yet armed:** a
  Phase-0 safety GATE blocks every mouse action until the remaining detection
  assets and calibration are in place, with several gold-protection backstops
  built in. The live buy/process logic ships in a follow-up update, with the
  first real run supervised and a high gold reserve.

## 🆕 What's new in 1.2.4

- **Jigsaw puzzle: smarter end-game + safety layer.** Fixed a case where the
  "finish" fallback could wreck a nearly-solved board — it would force an
  ill-fitting piece into a hole that a single right piece would have completed,
  then get stuck discarding. The solver now waits patiently for the completing
  piece (capped, so it never waits forever).
- **Background safety net (no change to normal play).** After each placement the
  bot now checks that the piece actually landed where planned and logs any
  mismatch; an ambiguous piece colour is discarded rather than risked; an
  obviously garbled board read is re-read; and a long run of discards stops the
  bot cleanly instead of burning boxes. The proven-optimal solver maths is
  untouched.

## 🆕 What's new in 1.2.3

- **Duel of the Seers: speed & reliability overhaul (major fix).** The bot no
  longer clicks on a fixed timer (which made every other round land _during_
  the previous round's animation and get ignored — wasting ~half the rounds and
  10s timeouts each). It now waits until the board is **actually settled**
  (animation finished), plays instantly, and confirms the move by detecting that
  **your card is now crossed out** — then reads the result from the score. Much
  faster and one clean game per game (no more phantom "extra rounds").

## 🆕 What's new in 1.2.2

- **Correct click target in the event overview (bugfix):** the auto-player now
  clicks the **"Seherwettstreit" name field** to open the event — not the
  "Ansehen" (view) button next to it. Rock-solid detection (match ≥0.99 even
  under noise / brightness / window shift) and a safety guard that never clicks
  unless the event overview is actually open.

## 🆕 What's new in 1.2.1

- **Seherwettstreit start flow hardened (bugfix):** the auto-player now
  retries each menu click (Ansehen / Start / Ja) if the game swallows a
  click, and uses a more robust Ctrl+E. Fixes a stop where the Start button
  was never pressed.
- **Full self-diagnosis in the console:** if any step doesn't look as
  expected, the bot now prints the raw match scores of every UI element it
  looks for (not just a saved image) — so problems can be pinpointed from
  the log alone.

## 🆕 What's new in 1.2.0

- 🔮 **New tab: "Duel of the Seers" (Seherwettstreit) auto-player** _(beta)_ —
  fully automates the card mini-game event: opens the event window (Ctrl+E),
  starts the game, plays all 9 rounds, collects the reward and repeats — until
  you press Stop, a configurable run limit is reached, or you run out of tarot
  sets (then it can optionally **switch character** or **close the client**).
- **Visible move timer** (4 s cadence between card plays) and a 0.75 s render
  floor between menu steps; everything else continues as soon as the next
  screen state is actually detected.
- **Honest error handling:** every step has an expected screen state. If the
  screen doesn't look as expected, the bot saves a debug frame
  (`seher_debug_*.png` next to the config), logs the failing step and stops —
  it never clicks blindly.
- Every round (own card, opponent colour, result, timings) is logged to the
  live console and appended to `seherwettstreit_results.jsonl` for later
  analysis.
- Fun fact, mathematically proven: against the game's random computer the card
  order **cannot** matter — the bot therefore simply plays a configurable
  fixed order and instead focuses on speed and robust detection.

## 🆕 What's new in 1.0.7

- **Leaderboard identity fix (important):** your install now keeps a **stable
  identity across restarts**, so your score stays on **one** entry. Previously a
  Portable EXE could lose its config on relaunch (the file was looked up relative
  to the working directory, not next to the EXE) — which silently **re-showed the
  name dialog**, **re-asked you to rate on GitHub**, and could create a **second
  leaderboard row** (e.g. two "FishLover"). The config now lives **next to the
  EXE** (Portable; `%APPDATA%` fallback) and the install id + your choices are
  saved **immediately**.
- **Unique names:** a self-chosen name now belongs to the **first** install that
  picks it. A later install choosing the same name falls back to its anonymous
  name instead of a confusing duplicate, and the first-run dialog **warns you up
  front** if a name is already taken.
- The name dialog and the GitHub rating prompt now **never reappear** once you
  have decided them.

## 🆕 What's new in 1.0.6

- **Puzzle fix (important):** the solver no longer **stops after every placed
  piece**. "Game over" is now decided by the board being **full** (the reward
  chest only appears then) instead of a single flickery preview pixel that read
  dark right after each placement.
- **Inventory stack reading:** the scan now reads the printed **stack numbers**
  (font-independent — both in-game number fonts) and **sums quantities per
  item**, so baits, boxes, dyes, bleach and keys count by amount, not by slot.
- **Scan-confidence warning:** an unreliable scan (nothing recognised / a number
  unreadable / far more unknown than known slots) is now flagged in the debug
  console instead of being silently trusted.
- **Update check every 30 minutes** (not only at startup).
- Inventory section moved **directly under Puzzle**; a one-time rating prompt
  after the 10th solved puzzle.
- **Experimental: auto-refill** — drag a bait into the quick-slot / a puzzle box
  onto the board straight from the inventory. **Off by default.**

> 🚨 **Danger — read this before enabling auto-refill.** Auto-refill performs
> **automated mouse drags inside your inventory**, moving **real items**. If the
> window position, resolution or calibration is even slightly off, it can drag
> the **wrong item** somewhere you did not intend. Only enable it on a
> calibrated **800×600** window, **watch the first few drags**, and use it
> entirely at your own risk. The bait quick-slot is fixed to keys **1–4 / F1–F4**
> (the only 8 quick-slots).

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

**Duel of the Seers (Seherwettstreit) event** _(new in 1.2.0, beta)_:

- Auto-plays the card mini-game in a loop: start via event overview, play,
  collect reward, repeat — with run limit and an optional after-action
  (switch character / close client).
- Template-based screen-state detection with hard stop + debug frame on any
  unexpected screen.

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

## 📊 Anonymous usage stats & leaderboard / Anonyme Nutzungs-Statistik & Rangliste

**English.** The app includes a small, always-on **anonymous** usage counter that
powers an online **leaderboard**.

- **What is collected:** a **random per-install id** (a `uuid4` generated once and
  stored locally — _not_ a device fingerprint) plus a few **counters** (catches,
  solved puzzles, fishing / puzzle runtime) and the **app version**. **No personal
  data.**
- **Everyone appears anonymously** under a generated funny name derived from the
  random id (same id → same name, e.g. `BraveTuna#4711`).
- **Opting in = your chosen name.** Typing a name in onboarding or
  _Settings → Ranking_ only **reveals that name** on the leaderboard. Clearing it
  returns you to the anonymous name. The chosen name is the _only_ potentially
  identifying datum and is strictly optional.
- **Anti-cheat moderation:** an install id can be **blocked** from the board and a
  chosen name can be **hidden** (it then shows the anonymous name). Neither is a
  durable person-ban — the random id is rotatable by editing this open-source
  client, so this is mass-protection only.
- **No raw IP is stored** (only a salted hash, then discarded).
- **Removal:** ask via the project page to be erased by install id or by name.

**Deutsch.** Die App enthält einen kleinen, immer aktiven **anonymen** Nutzungs-
Zähler für eine Online-**Rangliste**.

- **Was erfasst wird:** eine **zufällige Pro-Installation-ID** (einmalig erzeugte
  `uuid4`, lokal gespeichert — _kein_ Geräte-Fingerabdruck) sowie **Zähler**
  (Fänge, gelöste Puzzles, Angel- / Puzzle-Laufzeit) und die **App-Version**.
  **Keine personenbezogenen Daten.**
- **Alle erscheinen anonym** unter einem generierten lustigen Namen, der aus der
  zufälligen ID abgeleitet wird (gleiche ID → gleicher Name).
- **Opt-in = dein gewählter Name.** Ein Name im Onboarding oder unter
  _Einstellungen → Rangliste_ macht **nur diesen Namen** sichtbar; leeren →
  zurück zum anonymen Namen. Der gewählte Name ist das _einzige_ potenziell
  identifizierende Datum und strikt optional.
- **Anti-Cheat-Moderation:** eine Installations-ID kann von der Rangliste
  **gesperrt** und ein gewählter Name **ausgeblendet** werden (zeigt dann den
  anonymen Namen). Keines ist eine dauerhafte Personen-Sperre — die zufällige ID
  ist durch Editieren dieses Open-Source-Clients austauschbar (nur Massenschutz).
- **Keine rohe IP** wird gespeichert (nur ein gesalzener Hash, dann verworfen).
- **Löschung:** über die Projektseite anfragen (nach Installations-ID oder Name).

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
