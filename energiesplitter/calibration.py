# -*- coding: utf-8 -*-
"""Gemessene 800x600-Geometrie + Asset-Anker fuer den Energiesplitter.

Diese Datei ist die EINE Quelle der gemessenen Pixel-Konstanten (Phase-1,
2026-06-15). Alle Werte gelten im normierten 800x600-CLIENT (siehe
``geometry.to_client`` / ``CLIENT_X0=1``, ``CLIENT_Y0=31`` -- die echten
Fixtures sind 802x632 Vollfenster). Reine Daten + reine Funktionen; KEINE
Klick-/Eingabe-Logik, kein win32/IO. Wirft nie.

Mess-Grundlage (verifizierte echte Screenshots, beide 802x632):
  * ``tests/fixtures/energiesplitter/inventar_alchemist.png`` (yKo7rQ4BUz)
  * ``tests/fixtures/energiesplitter/inventar_waffenhaendler.png`` (VjWdxCoJqJ)
  * ``energiesplitter/Einkauf Hammer/Shopgeoeffnetalchemist.png``

Verifikation der Grid-Geometrie gegen die User-Grundwahrheit (de, 2026-06-15):
slot 18 = Hammer mit Stack ``2``; slot 19/20/23/24 = Dolch; slot 25/28/29 =
Hammer (leuchtend); slot 30 = leuchtender Dolch (im Waffenhaendler-Bild). Per
Crop + Template-NCC bestaetigt: Hammer-/Dolch-Templates klassifizieren diese
Slots korrekt (Gewinner-NCC >= 0.79, Verlierer <= 0.39 -- konfusionsfrei).

WICHTIG: Diese Werte wurden an FIXTURES gemessen und sind ``# KALIBRIER-BAR`` --
sie MUESSEN am echten Live-Client (Phase-0 P0.6) re-verifiziert werden, bevor
scharf geklickt/gekauft/gedraggt wird (Sicherheits-Invariante: Erkennung vor
Aktion; fehlt/abweicht ein Anker -> sauberer Stopp, nie Blind-Aktion).
"""

from . import geometry as _geo


# -- Inventar-Raster Seite I (5 Spalten) ------------------------------------
# Ursprung = MITTELPUNKT von Slot 1 (oben-links). Pitch in x UND y = 32px
# (per Autokorrelation der Zeilen-Helligkeit bestaetigt: Peak bei Lag 32).
# slot 1 Mittelpunkt (648,258) liegt exakt auf der ersten Potion (Stack "18").
GRID_COLS = 5                      # KALIBRIER-BAR
GRID_SLOT_CENTER_X0 = 648          # KALIBRIER-BAR (Slot 1, Spalten-Mitte)
GRID_SLOT_CENTER_Y0 = 258          # KALIBRIER-BAR (Slot 1, Zeilen-Mitte)
GRID_PITCH_X = 32                  # KALIBRIER-BAR
GRID_PITCH_Y = 32                  # KALIBRIER-BAR
# Abgeleitete Zell-Eckbox (oben-links Slot 1) -- nur informativ.
GRID_CELL_W = 32                   # KALIBRIER-BAR
GRID_CELL_H = 32                   # KALIBRIER-BAR
GRID_ORIGIN_TL = (632, 242)        # KALIBRIER-BAR (Slot 1 obere-linke Ecke)

# Tab-/Header-Struktur des Inventar-Panels (Seite I/II/III/IV).
INV_HEADER_BAND = (632, 152, 158, 37)   # KALIBRIER-BAR ("Inventar"-Titelbalken, x,y,w,h)
INV_TAB_BAND = (632, 222, 158, 18)      # KALIBRIER-BAR (Tab-Reihe I..IV)
INV_GRID_TOP_Y = 242                    # KALIBRIER-BAR (obere Kante Slot-Zeile 1)


def slot_center(slot):
    """Inventar-Slot (1..40, Seite I) -> Client-Pixel-Mittelpunkt ``(x, y)``.

    ``slot = (zeile-1)*5 + spalte`` (1-basiert, links->rechts, oben->unten).
    Gibt ``None`` bei nicht-positiver/nicht-ganzer Eingabe (defensiv; der GATE
    haelt scharfe Laeufe ohnehin zurueck). Reines Rechnen, wirft nie.
    """
    try:
        s = int(slot)
    except Exception:
        return None
    if s < 1:
        return None
    col = (s - 1) % GRID_COLS
    row = (s - 1) // GRID_COLS
    x = GRID_SLOT_CENTER_X0 + col * GRID_PITCH_X
    y = GRID_SLOT_CENTER_Y0 + row * GRID_PITCH_Y
    return x, y


def slot_cell(slot, size=32):
    """Slot-Mittelpunkt -> Zell-ROI ``(x, y, w, h)`` (zentriertes Quadrat).

    ``size`` = Kantenlaenge des Ausschnitts (Default 32 = volle Zelle). Fuer
    Template-NCC empfiehlt sich 32 (volle Zelle, gibt ``matchTemplate`` Spielraum).
    ``None`` bei ungueltigem Slot. Wirft nie.
    """
    c = slot_center(slot)
    if c is None:
        return None
    half = int(size) // 2
    return c[0] - half, c[1] - half, int(size), int(size)


# -- Glow-Erkennung ("frisch gekauft", noch nicht gehovert) -----------------
# Frisch gekaufte Items haben einen blau-weissen Glow-Halo. Gemessen am
# Slot-Rand-Ring (4px): nicht-leuchtend -> min-Kanal-Mittel ~11..21, Glow-Anteil
# <= 0.115; leuchtend -> min-Kanal-Mittel ~141, Glow-Anteil >= 0.65. Provably
# konfusionsfrei (Luecke 0.115..0.65). Schwelle 0.35 sitzt mittig.
# Projekt-GLOW_REF (Phase-1, RGB (176,177,203)) wird hier als BGR-Referenz
# wiederverwendet; die robustere Metrik ist aber der min-Kanal-Glow-Anteil.
GLOW_REF_BGR = (203, 177, 176)     # KALIBRIER-BAR (== Projekt-GLOW_REF, RGB->BGR)
GLOW_RING_PX = 4                   # Randring-Breite fuer die Glow-Stichprobe
GLOW_MINCH_THR = 80                # Pixel mit min(B,G,R) > das zaehlt als Glow
GLOW_FRACTION_THR = 0.35           # Glow-Anteil im Randring > das = leuchtend


# -- Shop-Item-Anker (Erkennung vor Aktion) ---------------------------------
# Hammer-Shop (Alchemist, "Shopgeoeffnetalchemist.png"): der Energiesplitter-
# Hammer (200er-Stack) sitzt im Laden-Panel; per Template-NCC (templates/
# hammer.png) lokalisiert bei Zell-Mittelpunkt (425,121). Stack-Groessen lt.
# Spec 1/50/200 -- in DIESEM Screenshot nur der 200er sichtbar; 1/50 = LUECKE
# (separater Screenshot noetig). Der Kauf-Knopf "Kaufen" sitzt unten im Panel.
SHOP_HAMMER_ANCHOR = (425, 121)    # KALIBRIER-BAR (Hammer-200-Zell-Mitte im Laden)
SHOP_HAMMER_CELL = 32              # Zellgroesse fuer die NCC-Verifikation
SHOP_BUY_BUTTON = (425, 273)       # KALIBRIER-BAR (ungefaehr "Kaufen"-Knopf, grob)
# Dolch-Shop (Waffenhaendler): GESCHLOSSEN (2026-06-15). Der markierte Dolch-Slot
# liegt in der OBEREN Shop-Reihe; per Template-NCC im SAUBEREN Shop-Screenshot
# ('Einkauf Dolche/Shopgeoeffnet.png', unannotiert) eindeutig bei Zell-Mitte
# (556,59) lokalisiert -- die Inventar-dolch.png matcht dort konfusionsfrei mit
# NCC 1.00 (einziger Treffer >= 0.6 im gesamten Client; Hammer-Template trifft
# diesen Slot NICHT). Sauberes Shop-Template: templates/shop_dolch.png (24x24,
# OHNE rote Markierung -- aus der unannotierten Vorlage gecroppt).
SHOP_DAGGER_ANCHOR = (556, 59)     # KALIBRIER-BAR (Dolch-Slot-Zell-Mitte im Laden)
SHOP_DAGGER_CELL = 32              # Zellgroesse fuer die NCC-Verifikation


# -- NPC-Suchregion + Detektions-Hinweise -----------------------------------
# Gruener NPC-Name ("Alchemist" / "Waffenhaendler") in der Spielszene. Gemessen:
# Alchemist-Label bei (339,228), Waffenhaendler bei (396,211) -- beide im
# oberen Szenen-Drittel. Suchregion bewusst grosszuegig (NPC-Position variiert).
ROI_NPC_SEARCH = (80, 90, 540, 380)   # KALIBRIER-BAR (== geometry.ROI_SCENE); an ALLEN 17 NPC-Bildern gemessen: Name liegt je nach Kamerawinkel bei x 126..565 / y 106..429 -> Suchfenster deckt die volle Spanne mit Rand ab (frueher 150/100/470/320 schnitt Rand-NPCs ab -> ncc=0.0)
# Anvisierter NPC: gelber Abwaerts-Pfeil ueber dem Kopf (gemessen im Alchemist-
# Bild: gesaettigtes Gelb R>180,G>160,B<120 im oberen Szenen-Bereich). Nach
# RECHTSKLICK zusaetzlich eine ROTE Auswahl-Markierung an den NPC-Fuessen.
# Detektions-Reihenfolge zum Ansprechen: ERST Rechtsklick (rote Markierung
# bestaetigt Ziel) DANN Linksklick. Pfeil + rote Markierung dienen als
# Ziel-Bestaetigung, NICHT als alleiniger Klick-Anker (Name-NCC ist primaer).
NPC_ARROW_YELLOW = dict(r_min=180, g_min=160, b_max=120)  # KALIBRIER-BAR
NPC_GREEN_NAME = dict(g_min=110, gr_delta=20, gb_delta=20)  # KALIBRIER-BAR


# -- Re-Export der Client-Normierung (Bequemlichkeit) -----------------------
to_client = _geo.to_client
crop = _geo.crop
CLIENT_X0 = _geo.CLIENT_X0
CLIENT_Y0 = _geo.CLIENT_Y0
GAME_W = _geo.GAME_W
GAME_H = _geo.GAME_H


__all__ = [
    'GRID_COLS', 'GRID_SLOT_CENTER_X0', 'GRID_SLOT_CENTER_Y0',
    'GRID_PITCH_X', 'GRID_PITCH_Y', 'GRID_CELL_W', 'GRID_CELL_H',
    'GRID_ORIGIN_TL', 'INV_HEADER_BAND', 'INV_TAB_BAND', 'INV_GRID_TOP_Y',
    'slot_center', 'slot_cell',
    'GLOW_REF_BGR', 'GLOW_RING_PX', 'GLOW_MINCH_THR', 'GLOW_FRACTION_THR',
    'SHOP_HAMMER_ANCHOR', 'SHOP_HAMMER_CELL', 'SHOP_BUY_BUTTON',
    'SHOP_DAGGER_ANCHOR', 'SHOP_DAGGER_CELL',
    'ROI_NPC_SEARCH', 'NPC_ARROW_YELLOW', 'NPC_GREEN_NAME',
    'to_client', 'crop', 'CLIENT_X0', 'CLIENT_Y0', 'GAME_W', 'GAME_H',
]
