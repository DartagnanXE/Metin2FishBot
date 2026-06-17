# 🎣 Metin2 Fishing Bot

A visual automation bot for the Metin2 fishing mini-games. It re-baits and casts
the rod automatically while fishing, and can solve the jigsaw puzzle mini-game.
Modern single-window UI — and every "smart" upgrade is **optional**: the original
behaviour is fully preserved as the default.

> ⚠️ **Disclaimer.** For educational purposes only. Automating gameplay typically
> violates the game's Terms of Service and may get your account banned. Use at
> your own risk. See [`LICENSE.txt`](LICENSE.txt).

## 🆕 What's new in 1.2.31

- **Box refill: puzzle boxes are now reliably recognized in the inventory.** The
  refill scanned all 4 pages but recognized no box and stopped with "out of boxes",
  even though the boxes were on page IV. Two causes, both fixed: the auto grid
  alignment was ~10 px off (now uses the fixed calibrated grid), and the box carries
  a large stack count (57/104/200) on its lower half that broke full-icon matching
  (now only the upper icon half is matched, ignoring the number). Proven on the real
  screenshot: standard-box match distance ≈ 1.0, all non-box slots ≥ 39 — clean
  separation. A dedicated, client-robust box finder replaces the general inventory
  scan for refilling.

## 🆕 What's new in 1.2.30

- **Puzzle solver: optimal all the way to the end (finish mode removed).** A real
  logic bug (reported by a user): when only a single 1-move hole was left (e.g. an
  L of 3 cells), the bot would eventually place a fragmenting piece (e.g. a single
  cell), creating 2 single cells → one move/piece more than needed. Cause: a "finish
  mode" that forced a suboptimal placement after many discards. It's now removed —
  the bot always plays the provably optimal policy (place only if it strictly lowers
  the expected pieces-to-win, otherwise wait). **Minimal pieces at all times, no
  artificial limits.** Verified by Monte-Carlo (50,000 games): the policy hits the
  predicted optimum (15.58 ≈ V[empty]=15.57), 0 stuck games; the old approach used
  22% more pieces. The anti-hang backstop is calibrated to 120 consecutive discards
  so it never interferes with legitimate optimal waiting.

## 🆕 What's new in 1.2.29

- **Deluxe box: reactive detection instead of count-reading — now used reliably.**
  The old logic read a stack number printed on the box slot, which doesn't exist for
  an empty/normal box, so it always read 0 and never opened the Deluxe box. The bot
  no longer reads any count: when a free 2×3 hole exists it simply opens the Deluxe
  box (it's almost always loaded) and places the magenta 2×3 piece. Only if nothing
  comes (no magenta) does it treat the slot as empty and react — refill from the
  inventory (if enabled), or just disable Deluxe and keep playing normally (no stop).
  No per-move check = no speed penalty.

## 🆕 What's new in 1.2.28

- **Fix: "AI optimized" no longer freezes for ~19 s on first start.** The AI value
  function (over all 16.7M board states) used to be computed live on the very first
  "AI optimized" move (~19 s), during which the bot looked frozen — and the portable
  EXE didn't ship the precomputed file, so it happened on every fresh start. It's now
  precomputed and bundled compressed in the EXE (`trained_V.npz`, ~13 MB), loading in
  ~0.2 s, and preloaded at puzzle start. No more freeze.

## 🆕 What's new in 1.2.27

- **Force Deluxe now actually uses the Deluxe box (opportunistic).** The old
  strategy reserved a fixed 2×3 field and waited — it stalled whenever the box-count
  read 0, so the Deluxe box was never opened and the solver just filled the whole
  board and discarded forever. Now the bot works opportunistically: as soon as a
  **free 2×3 hole** exists on the board **and a Deluxe box is available**, it opens
  the Deluxe box and fills that hole with the magenta 2×3 piece (a deterministic
  6-cell fit). The log now shows `Deluxe check: free 2x3 hole at …, deluxe boxes
read=N` so it's finally visible whether a box is detected. A safety cap disables
  Deluxe for the run after 2 empty opens (no infinite clicking).

## 🆕 What's new in 1.2.26

- **Fix: puzzle box auto-refill now actually opens the inventory.** In 1.2.25 the
  refill logged _"inventory not verifiably open"_ and refilled nothing — the
  puzzle plays with mouse clicks only, so the game window had no keyboard focus
  and the inventory hotkey went nowhere. The bot now **focuses the game window
  before pressing the hotkey** (like the Energiesplitter), so the inventory opens
  reliably. Also triggers faster (after 2 empty draws instead of 3) and logs a
  clear diagnostic line (`auto-refill enabled=…, engine=…, streak=N/2`).

## 🆕 What's new in 1.2.25

- **Fish puzzle: auto-refill empty boxes from the inventory (opt-in).** New
  _"Auto-refill boxes"_ switch in the puzzle settings. When a puzzle box runs
  empty mid-game, the bot drags a fresh box from the inventory into the box slot
  (standard box → lower slot, Deluxe → upper slot). Always the **first** box
  found, scanning inventory pages I→IV, slots 1–45, and **only** a confidently
  recognized box — never another item. The inventory is opened automatically if
  needed; out of boxes → the bot stops with a clear message. F6 aborts instantly.
  **Default OFF** — dragging/recognition is only verifiable on the live game, so
  enable it and watch the first run.

## 🆕 What's new in 1.2.24

- **Campfire grilling: hard 35-second limit.** The placed campfire only lasts
  ~35 seconds — the bot no longer counts on it being there a second longer. A hard
  deadline starts at placement; once it's up, grilling stops (no more fish dragged
  onto a fire that's already gone).

## 🆕 What's new in 1.2.23

- **Energiesplitter dagger mode: the shop buys now + ALL daggers get processed.**
  At the weapon dealer the shop opened but then stopped with "bag_not_open" — an
  uncalibrated double bag-check that always failed; removed (the bag is already
  verified via open_probe). And the bot now hammers **every dagger in the
  inventory** (bought **and** pre-existing) — but **only slots safely recognized
  as a dagger** (NCC winner among all item templates), never any other item, with
  a second per-drag verification.

## 🆕 What's new in 1.2.22

- **Energiesplitter: the NPC dialog now gets time to appear.** A full tester run
  showed the NPC recognized + clicked, but then "open shop not found" (NCC 0.274)
  because the dialog search ran ~30 ms after the click — before the NPC dialog had
  opened. The bot now waits for the dialog and retries the "open shop" line search
  with a render pause (up to 5×). Also: the "ZUSTAND: Tick" log no longer spams
  identical lines during waits (looked frozen).

## 🆕 What's new in 1.2.21

- **Energiesplitter: shop-item search now retries while the shop renders.** The
  whole buy chain runs to the shop (bird's-eye → NPC → open shop). A tester saw
  "hammer not in shop" (NCC 0.547) because the shop was still fading in on the
  first look. The item search (hammer + dagger) now retries with a short render
  pause (up to 6×) before reporting "not in shop".

## 🆕 What's new in 1.2.20

- **Energiesplitter now defaults to Sharp/Live** (fresh installs) so testers can
  start right away without flipping a switch. The "Sharp/Live" toggle stays (you
  can switch back to simulation anytime). All safety backstops remain fully active:
  detect-before-action (only verified targets are bought/dragged), the Phase-0 gate
  (no click without recognized assets/800×600/calibration), the action cap, and F6.

## 🆕 What's new in 1.2.19

- **Energiesplitter: buy confirmation, real bird's-eye (drag), dagger processing.**
  Every shop purchase asks "do you want to buy…?" — the bot detects the dialog by
  its "Ja" button (calibrated from your screenshot; threshold 0.85 + only checked
  right after a buy click) and clicks **Ja** (hammer + dagger). Bird's-eye is now
  done via your method — **right-click-hold + drag the mouse down 25% of the
  height** for a true top-down view (once per run; the old "g" key maneuver and its
  setting are fully removed). Daggers: a hammer can only be dragged onto a dagger
  when the weapon-dealer shop is **closed**, so the bot now closes it (ESC) before
  dragging and re-opens it for the next round.

## 🆕 What's new in 1.2.18

- **Update helper hardened further (belt-and-suspenders to 1.2.17).** In addition
  to `CREATE_NO_WINDOW`, the helper is now also launched with `STARTUPINFO`/
  `SW_HIDE`, and a regression test guarantees the wait/copy loops stay hard-bounded
  forever. A full code scan confirmed the update helper was the only
  window/process-spawning path; `os.startfile`/`webbrowser.open` are user-initiated
  and harmless.

## 🆕 What's new in 1.2.17

- **CRITICAL: the update helper spawned dozens of CMD windows (unkillable).** On
  update, many black `ping`/`find` console windows popped up and the PC needed a
  hard reset. Cause: the self-replace `.bat` was launched with `DETACHED_PROCESS`
  (no console → every child command opened its own visible console). Fixed: it now
  runs with `CREATE_NO_WINDOW` (hidden console, inherited) — no windows at all —
  and the wait/copy loops are now hard-bounded. (If you're on an older build, replace
  the EXE manually once from the releases page; the old helper still has the bug.)

## 🆕 What's new in 1.2.16

- **Energiesplitter: opening the shop is now calibrated — the hammer purchase
  runs end-to-end.** The "Laden öffnen" (open shop) dialog line is detected via
  color-NCC in the centered options band (calibrated from your dialog
  screenshots; present ≥0.985, absent ≤0.36) and clicked, for both Alchemist and
  weapon dealer. Shop-open is verified by finding the item (the 200-stack hammer
  at the calibrated anchor, NCC 0.91) instead of a fragile fixed header. So:
  address NPC → open shop → right-click the 200-hammer → re-read verification.
  (Multi-page scan II/III/IV is the next step for buying more than page-I free
  slots.)

## 🆕 What's new in 1.2.15

- **Energiesplitter: auto-dismiss the AFK dialog + talk to NPCs via left-click.**
  The centered "you are AFK" dialog blocked all input → the bot never reached the
  NPC. It now detects it (OK-button NCC, bundled template) and clicks OK at the
  start of each tick. NPCs are now addressed via a **left-click centered on the
  name** (the correct way to talk to an NPC), using the detected green name
  center; bird's-eye runs first if the name isn't otherwise visible. The dialog
  step no longer hard-stops when its template isn't calibrated yet.

## 🆕 What's new in 1.2.14

- **Energiesplitter now detects whether the bag is open – and opens it.** It used
  to scan the inventory "blind" and read 0 free slots on a closed/wrong bag (false
  "no space" stop). It now reuses the fishing bot's proven open-state logic
  (`inventory.open_probe`: tab-template probe + toggle hotkey): it checks the bag
  is open before scanning and opens it itself (key I) if not, in both actions.

## 🆕 What's new in 1.2.13

- **Energiesplitter tab polish.** The two start/stop buttons no longer flicker
  on the Energie tab (they were reconfigured ~100×/s every bot tick; now only on
  real state changes). The Energie tab now sits **above** the ranking (with the
  bot modes). And the "inventory full" stop is now explicit: "inventory shows 0
  free slots (page I) – open the inventory AND free up space, then start again."

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
