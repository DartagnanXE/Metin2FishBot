"""Single source of truth for the inventory recognition engine.

Pure Python (no numpy/cv2/PIL) so this module is ALWAYS importable and
``unittest``-testable headless -- exactly like :mod:`geometry`/:mod:`constants`
in the rest of the project. Every geometric and colour constant the engine
needs lives here, plus the calibration default dict (a STARTING GUESS only --
the real grid drifts per session, so :func:`inventory.grid.auto_align`
re-locks it each scan).

Image convention (matches :mod:`detection`/:mod:`windowcapture`): a captured
image has shape ``(H, W, 3)``, indexed ``img[y, x]``. Captured pixels are BGR
(``WindowCapture.get_screenshot`` drops alpha via ``img[..., :3]``); icons load
as RGBA. The engine standardises internally on RGB float32 -- the slot
extractor converts BGR->RGB once at the capture boundary.
"""

# -- Slot / grid geometry --------------------------------------------------

# A single inventory slot is SLOT_PX x SLOT_PX pixels.
SLOT_PX = 32

# Inventory grid: 5 columns x 9 rows = 45 slots per page, pitch ~32px.
COLS = 5
ROWS = 9
SLOTS_PER_PAGE = COLS * ROWS  # 45

# The four inventory tab pages, left to right.
PAGES = ('I', 'II', 'III', 'IV')


# -- Colour references (RGB, 0..255) ---------------------------------------

# Empty-slot background: uniform dark. Used as the composite background for
# every reference and as the "is this slot empty?" yardstick.
EMPTY_REF = (5, 7, 3)

# GLOW: a freshly caught item recolours the slot BACKGROUND bright lavender.
# The item icon stays drawn on top, unchanged -- which is why masked matching
# (only the icon's opaque pixels) is glow-proof. Documented for tests/tools;
# the matcher never compares the background so it does not depend on this value.
GLOW_REF = (176, 177, 203)


# -- Stack-number band -----------------------------------------------------

# White stack-count digits occupy the lower-centre band of a slot: rows 14..24
# inclusive (0-indexed within the 32px slot). The reference weight mask zeroes
# these rows so digits can never corrupt the match score. The top ~13 rows are
# number-free and are used for the cheap "empty" probe.
NUMBER_BAND_ROWS = range(14, 25)

# The number-free upper region (rows 0..UPPER_REGION_END-1) used for the empty
# probe and the unknown-item signature. 14 == first number-band row.
UPPER_REGION_END = 14

# -- Per-slot STACK-NUMBER detector (selects the FULL vs BAND match mask) ----
#
# At classify time each slot is probed for a printed stack number so the matcher
# can pick the right reference mask (see reference.build_reference: every
# reference carries BOTH a FULL mask -- alpha-opaque, number rows KEPT -- and a
# BAND mask -- the same with NUMBER_BAND_ROWS zeroed). The printed digits are
# bright near-white glyphs sitting in the LOWER half of the slot; we count the
# near-white pixels in the digit rows and call the slot "numbered" once enough of
# them are present:
#
#   * NUMBER_DETECT_ROWS -- the slot rows scanned (16..31 inclusive, i.e. the
#     lower half where the two digit font sizes both land; measured on real
#     captures the glyphs sit there, never in the top half).
#   * NUMBER_DETECT_WHITE -- a pixel counts as a digit pixel when min(R,G,B) is
#     STRICTLY above this (a near-white glyph stroke; a coloured icon pixel has
#     at least one low channel, so it does not count).
#   * NUMBER_DETECT_MIN_PX -- the slot is "numbered" once at least this many such
#     near-white pixels are found in the scanned rows.
#
# The detector is intentionally SAFE-by-design (it can never lose an item):
#   - false POSITIVE (flags a number where there is none) -> the slot uses the
#     BAND mask instead of FULL = it merely forgoes the FULL-mask margin BONUS,
#     no harm (the BAND result is exactly today's behaviour);
#   - false NEGATIVE (misses a real number) -> practically impossible: a real
#     stack number paints 35..140 near-white px in these rows, a bare item paints
#     ~0, so the gap to the threshold is enormous.
# Measured on FischOhneLeuchten: every numbered slot trips it (BAND, unchanged),
# every number-free item stays under it (FULL, margin up), 0 items lost.
NUMBER_DETECT_ROWS = range(16, 32)
NUMBER_DETECT_WHITE = 190
NUMBER_DETECT_MIN_PX = 8

# Minimum alpha (0..1) for a pixel to count in the match weight mask. Anti-
# aliased icon EDGES are semi-transparent (0 < alpha < 1); on a GLOWING slot the
# lavender background bleeds THROUGH those partial-alpha pixels (the composite
# there is part icon, part glow), inflating a true item's masked distance. We
# therefore match only SOLIDLY-OPAQUE interior pixels (alpha >= this), which are
# genuinely glow-proof. Measured effect: worst synthetic glow distance drops
# from ~46 to ~5 and confident glow recovery returns to 100%, while DARK stays
# 100% and close-family margins are unchanged/slightly better (so no
# overfitting). 0.9 keeps every icon's mask comfortably non-empty (min ~25 px).
ALPHA_OPAQUE_MIN = 0.9


# -- Matcher tuning --------------------------------------------------------

# Masked mean-abs-diff distance is reported in 0..255 (per-channel) units. A
# correct match sits low (synthetic dark ~3, glow+number+shift+noise <= ~12);
# a wrong item -- or a correct item whose icon art differs from the on-screen
# rendering -- lands far higher (~30+). The threshold sits in that gap so a
# confident 'item' really is a confident match and ambiguous slots fall through
# to 'unknown' rather than producing a false positive. Empirically derived from
# the synthetic accuracy sweep (worst true glow match ~11.4).
MATCH_THRESHOLD = 22.0

# Minimum confidence margin (2nd-best distance - best distance) for a confident
# item classification. A confident ITEM must clear MATCH_THRESHOLD AND beat the
# runner-up by at least this margin; otherwise a near-tie between two
# close-family references (e.g. two hair dyes, Fischpuzzlebox vs its Deluxe) is
# demoted to 'unknown' rather than reported as a confident WRONG name. The
# measured gap on real/synthetic data is large (>= 12), so this 3.0 guard only
# trips on a genuine ambiguity, never on a clean match.
MARGIN_MIN = 3.0

# A slot with no confident item match AND a per-channel colour std no greater
# than this is treated as EMPTY (glow-aware fallback): a glowing-but-empty slot
# is a flat lavender field (tiny std), whereas a real item -- even on a glow
# background -- has a high-contrast silhouette (std well above this). Without
# this, a glow-empty slot would fall through to 'unknown' and churn signatures
# during glow fade-out / when an item leaves a still-glowing slot.
EMPTY_FALLBACK_STD = 6.0

# Rounded shift search radius for the matcher: try dy,dx in [-S..S]^2 and keep
# the best (lowest-distance) shift. Absorbs sub-pixel / small session offset.
SHIFT_RADIUS = 2

# DEFAULT page-vectorised matcher (inventory.itemdb.ItemDB.match_page_distances):
# instead of looping the masked-MAD matcher 45x per page (one Python call + one
# numpy broadcast over the N references each), the vectorised primitive scores
# ALL of a page's slots against ALL references in ONE batched numpy reduction
# (slots on a new leading axis, references chunked to stay cache-resident). It is
# NUMERICALLY IDENTICAL to the per-slot loop (bit-exact masked MAD + min over the
# same [-S..S]^2 shifts -> same stable argsort -> same names/margins), it just
# removes the 45x Python per-slot dispatch and reuses one big GIL-free numpy op.
# This is the *factor* the matcher chunks references into: the giant
# (slots, N, 32*32*3) intermediate is memory-bandwidth bound and slower than the
# per-slot loop if materialised whole, so references are processed VECTOR_REF_CHUNK
# at a time -- each chunk's (slots, chunk, P) diff stays in cache. ~8 measured
# fastest on the build box (45 refs); the result is identical for any chunk >= 1.
VECTOR_REF_CHUNK = 8

# Auto-grid-alignment search radius (pixels) around the calibration origin
# guess. The DENSE 1px search MUST stay strictly below the half-pitch (16px)
# bound: at exactly +-pitch/2 the objective becomes ambiguous (the grid shifted
# by one whole cell aligns each slot onto a DIFFERENT but equally-valid item, a
# spurious global-tie alias). 10px reaches the observed per-session drift from
# the (re-centred) calibration guess on the real 800x600 / 801x602 captures
# while leaving a safe margin below 16px. The grid origin guess itself is kept
# close to reality (see DEFAULT_CALIBRATION) so this small radius always
# brackets the truth without admitting a one-cell alias.
#
# The search is DENSE (every integer offset) on purpose: the matched-count well
# can be a single pixel wide on a SPARSE page (few items), so a coarse step-2
# sweep demonstrably misses it (~19% of drifts on a 9-item page). The downsample
# below keeps the dense sweep cheap.
AUTO_ALIGN_RADIUS = 10

# SESSION-CACHE refine radius (px) for auto_align. The inventory window is FIXED
# for a whole session, so once the grid is locked the NEXT scan's true origin is
# the cached one (at most a sub-pixel jitter away). auto_align therefore first
# probes the cached origin with a tiny DENSE +-this sweep (full-res, the sharp
# arbiter) instead of the full ~441-candidate cold sweep: if that still locks a
# grid with adequate item count it is reused in <<1s; if the count collapsed (the
# window genuinely moved beyond this refine) it falls back to the full cold sweep.
# 3px comfortably covers real per-scan jitter while staying far below the
# half-pitch alias bound, and (being centred on the previous lock) reproduces the
# cold-sweep winner exactly whenever the window is unmoved (the session invariant).
AUTO_ALIGN_CACHE_REFINE = 3

# Number of WHOLE-ROW shifts auto_align probes on each side of the calibration
# row to bridge a whole-row calibration drift (an inventory that sits one slot-row
# higher/lower than the bundled default -- observed on foreign clients, where the
# +-radius window alone locks one row off, silently dropping the off-grid row and
# inventing a phantom one). For each k in [-this..+this] a separate DENSE +-radius
# sweep runs around (calib_x, calib_y + k*pitch_y); the per-band winners are then
# re-ranked at FULL resolution (most items, then lowest mean, then nearest to the
# calibration origin). No coarse step and no separate refine pass -- each band
# representative is already its dense-sweep peak. Set to 0 for pure +-radius.
AUTO_ALIGN_ROW_REACH = 1

# The auto-align origin sweep matches DOWNSAMPLED references/slots (block-mean
# pooled by this factor) instead of the full 32x32. Alignment only needs to
# LOCATE the lattice, not name items, so 16x16 (factor 2) is plenty precise and
# ~4x cheaper per candidate. Measured on the build machine (real 800x600 capture)
# the dense 21x21 sweep is ~1-1.5 s/page and the full-res 45-slot recognise is
# ~0.9 s/page, so a live 4-page scan is ~10 s of CPU + ~1.2 s of settle pauses
# (~10-11 s total). That runs on the worker thread (UI stays responsive) and is
# fine for a MANUAL button; a future "auto-scan after fishing" should budget for
# it (or coarse-then-refine / skip re-align when the prior lock is still valid)
# rather than assume sub-second pages. Final classification always uses full-res
# refs. SLOT_PX must be divisible by this.
ALIGN_DOWNSCALE = 2

# Half-size of the square window (in px) averaged around each tab sample point in
# grid.active_page. 0 = a single pixel (fragile: a lone sample can land on tab
# text/border and leave only ~20 brightness units between the open and a closed
# tab). 1 -> a 3x3 mean, which widens the active/inactive gap to ~90-120 units on
# the real captures, so the brightest-of-4 open-tab decision is robust across
# theme/resolution/glow. The window is clamped to the image and always contains
# the centre point, so it is never empty.
ACTIVE_TAB_SAMPLE = 1

# Default tolerance (per-channel, 0..255) for "this region is ~empty_ref".
DEFAULT_TOLERANCE = 18


# -- Margin-primary acceptance (glow recovery WITHOUT hovering) ------------
#
# The hover-clear pre-pass (see inventory/hover.py) is the PRIMARY glow defence
# -- it removes the lavender glow so the page recognises at the no-glow ~100%.
# Margin-primary is a small ADDITIVE safety net: it accepts an item that sits
# slightly OVER MATCH_THRESHOLD when the runner-up reference is VERY far away
# (huge margin), which recovers easy glow cases even if a slot's glow lingered.
#
# It is a pure OR-branch on the existing decision, GUARDED so it can never
# introduce a false positive:
#
#   * MARGIN_PRIMARY_MAX_DIST is a hard ceiling just above the no-glow 22
#     threshold: a truly-unmatched slot (dist ~38-40+ on the real shots) can
#     NEVER be accepted, so it does not change the no-glow result (measured: the
#     no-glow FischOhneLeuchten shot stays 26/26 -- the nearest non-item slot is
#     at dist ~29 with margin ~8, below the min).
#   * MARGIN_PRIMARY_MIN is chosen ABOVE the largest CLOSE-FAMILY margin so
#     margin_primary can never fire BETWEEN two close relatives. Measured close-
#     family margins (distance from one family member to its NEAREST sibling):
#     hair dyes 12.65..21.1, Fischpuzzlebox vs _Deluxe ~40. The smallest
#     close-family gap (hair dyes) is ~12.65, while a TRUE item vs a RANDOM
#     wrong item is much larger (>= ~22 on the glow shot, e.g. Sage_King_Symbol
#     margin ~22). 12.0 therefore sits below the smallest real recovery margin
#     yet at/just-below the close-family floor: in practice a close-family
#     near-tie has a tiny best-vs-runner-up margin (well under 12) so it is
#     demoted to UNKNOWN exactly as MARGIN_MIN already does, while a clean
#     true-vs-random recovery (margin >> 12) is admitted.
MARGIN_PRIMARY_MIN = 12.0
MARGIN_PRIMARY_MAX_DIST = 30.0


# -- Live hover / scan timing (seconds; pure + importable headless) --------
#
# Kept here (not in the win32 runner) so they are tunable and importable in
# headless tests. All small. The hover SWEEP itself runs at pydirectinput
# PAUSE=0 (set+restored by the runner), so 45 cursor moves cost a few ms; these
# are only the single SETTLE pauses around the fast actions.

# Single settle AFTER the full 45-slot hover sweep, so the last glow finishes
# fading before the re-capture. NOT per-slot (a per-slot sleep would make the
# sweep slow + jittery).
HOVER_SETTLE_S = 0.05

# Settle after clicking an inventory tab, before verifying / capturing it.
TAB_SETTLE_S = 0.10

# Settle after pressing the inventory open hotkey, before the page loop.
OPEN_SETTLE_S = 0.15


# -- Tracked key items (the default 'remember + report' set) ---------------
#
# These four names equal real icon basenames in inventory_icons/ (verified:
# Fischpuzzlebox.png, Fischpuzzlebox_Deluxe.png, Lagerfeuer.png, Worm.png), so a
# SlotResult.name matches them exactly. The inventory report + a future item
# handler track these by default (locate now; move/use/delete is a later phase).
KEY_ITEMS = ('Fischpuzzlebox', 'Fischpuzzlebox_Deluxe', 'Lagerfeuer', 'Worm')


# -- Calibration default (a STARTING GUESS; auto_align re-locks per scan) ---

DEFAULT_CALIBRATION = {
    'client': [799, 602],
    'tabs': {
        'I': [654, 231],
        'II': [693, 232],
        'III': [732, 232],
        'IV': [770, 232],
    },
    'tab_active': {
        'offset': [15, 6],
        'rule': 'brightest of the 4 sample points = open page',
    },
    # Grid top-left / bottom-right slot centres-of-origin (px in the captured
    # CLIENT image). This is only a STARTING GUESS -- auto_align re-locks it per
    # scan within +-AUTO_ALIGN_RADIUS. It is centred on the EMPIRICAL grid
    # origin measured on the real captures (FischOhneLeuchten -> (633,275),
    # FischLeuchten -> (632,274)); the original (649,263) guess sat ~16px off
    # (a full half-pitch), which no small alias-safe search radius could recover.
    # br = tl + ((COLS-1)*32, (ROWS-1)*32) so lattice_from_calibration derives a
    # clean 32px pitch on both axes.
    'grid': {
        'tl': [633, 275],
        'br': [761, 531],
        'cols': COLS,
        'rows': ROWS,
    },
    'empty_ref': list(EMPTY_REF),
    'tolerance': DEFAULT_TOLERANCE,
}


def slot_indices():
    """Row-major ``(row, col)`` enumeration of all 45 slots.

    Pure Python so it is testable without numpy. Order matches the row-major
    layout used everywhere in the engine (page result lists, overlay labels).
    """
    return [(row, col) for row in range(ROWS) for col in range(COLS)]
