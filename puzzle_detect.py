"""Reines Brett-/Stein-Lesen + Klassifikation des Puzzles als Mixin.

Beherbergt die selbst-staendigen Vision-Bausteine des PuzzleBot, die aus dem
Bildausschnitt lesen und klassifizieren -- OHNE Klick-/State-Machine-Logik:

  * :meth:`_sample_cell_bgr`     -- Zellfarbe lesen ('single' 1 Pixel / 'multi' Patch).
  * :meth:`_classify_piece`      -- BGR -> Steintyp 1..6 (oder None).
  * :meth:`_is_valid_piece_color`-- Toleranzpruefung gegen die 6 echten Steinfarben.
  * :meth:`_diagnose_board`      -- {valid, empty, garbage}-Zaehlung ueber die 24 Zellen.
  * :meth:`detect_end_game`      -- "neuer Stein da?" am getpiece-Sample.

Als Mixin herausgezogen, damit die zustandsbehaftete Solver-Glue-/State-Machine
in :mod:`puzzle` schlank bleibt. ``PuzzleBot`` erbt von :class:`PuzzleDetectMixin`;
saemtlicher Zustand (``PIECE_REF_BGR``, ``color_mode``, ``board_size``,
``key_points`` ...) lebt weiter auf ``PuzzleBot``. Methodenaufloesung und jeder
``self.``-Zugriff bleiben damit byte-identisch zur fruheren Single-Class.
"""

import geometry


class PuzzleDetectMixin:
    """Pure Lese-/Klassifikations-Methoden (kein eigener Zustand, kein __init__)."""

    def _sample_cell_bgr(self, crop_img, x, y):
        """Liest die Farbe an ``(x, y)`` als ``(b, g, r)``-Int-Tupel.

        'single' (Default): exakt ``crop_img[y, x]`` -- bit-identisch zum
        bisherigen Verhalten (1 Pixel).
        'multi' : Mittelwert ueber ein ``color_patch`` x ``color_patch``
        grosses Fenster, zentriert auf ``(x, y)`` und an den Bildraendern
        geklemmt. Mittelung pro Kanal, auf Int abgerundet.
        """
        if self.color_mode != 'multi':
            px = crop_img[y, x]
            return (int(px[0]), int(px[1]), int(px[2]))

        # -- Multi-Patch-Mittelwert ---------------------------------------
        try:
            patch = int(self.color_patch)
        except (TypeError, ValueError):
            patch = 3
        if patch < 1:
            patch = 1
        half = patch // 2

        # Bildgrenzen defensiv bestimmen (numpy-Shape: (Hoehe, Breite, ...)).
        height = int(crop_img.shape[0])
        width = int(crop_img.shape[1])

        x0 = max(0, x - half)
        x1 = min(width, x + half + 1)
        y0 = max(0, y - half)
        y1 = min(height, y + half + 1)

        region = crop_img[y0:y1, x0:x1]
        # Mittelwert ueber die ersten zwei Achsen (alle Pixel des Patches) je
        # Kanal. region hat Form (h, w, 3); mean(axis=(0,1)) -> (3,).
        mean = region.mean(axis=(0, 1))
        return (int(mean[0]), int(mean[1]), int(mean[2]))

    def _classify_piece(self, bgr):
        """Ordnet eine ``(b, g, r)``-Farbe einem Steintyp 1..6 zu (oder None).

        'single' (Default): die sechs bestehenden engen BGR-Fenster, bit-
        identisch zu get_new_piece_color (kein Treffer -> None).
        'multi' : naechste Referenzfarbe (kleinste quadratische euklidische
        Distanz zu den PIECE_REF_BGR-Zentroiden) -- nie None bei gueltiger
        Farbe, ausser das Brett-/Garbage-Schwarz (alle Kanaele < 50) wird vom
        Aufrufer separat behandelt.
        """
        b, g, r = bgr

        if self.color_mode != 'multi':
            # Exakt die Verzweigung aus get_new_piece_color (Reihenfolge und
            # Grenzen unveraendert) -> garantierte Byte-Stabilitaet.
            if b > 35 and b < 40 and g > 60 and g < 70 and r > 240 and r < 260:
                return 4
            elif b > 20 and b < 30 and g > 150 and g < 170 and r > 240 and r < 260:
                return 1
            elif b > 35 and b < 50 and g > 240 and g < 260 and r > 35 and r < 50:
                return 5
            elif b > 240 and b < 260 and g > 240 and g < 260 and r > 20 and r < 30:
                return 3
            elif b > 240 and b < 260 and g > 100 and g < 115 and r > -10 and r < 10:
                return 2
            elif b > 50 and b < 60 and g > 235 and g < 255 and r > 250 and r < 260:
                return 6
            return None

        # -- Multi: naechste Referenzfarbe --------------------------------
        best_type = None
        best_dist = None
        for piece_type, ref in self.PIECE_REF_BGR.items():
            db = b - ref[0]
            dg = g - ref[1]
            dr = r - ref[2]
            dist = db * db + dg * dg + dr * dr
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_type = piece_type
        return best_type

    def _is_valid_piece_color(self, b, g, r, tol=45):
        """True, wenn (b,g,r) nahe einer der 6 ECHTEN Steinfarben liegt.

        Mode-unabhaengig (PIECE_REF_BGR + Toleranz) -- fuer die Board-Diagnose:
        belegte Zelle MIT gueltiger Steinfarbe vs. Garbage (belegt, aber keine
        echte Steinfarbe = kein echtes Puzzle)."""
        for ref in self.PIECE_REF_BGR.values():
            if (abs(b - ref[0]) <= tol and abs(g - ref[1]) <= tol
                    and abs(r - ref[2]) <= tol):
                return True
        return False

    def _diagnose_board(self, crop_image):
        """Klassifiziert die 24 Zellen fuer eine KLARE Stop-Diagnose.

        Liefert ``{'valid', 'empty', 'garbage'}``:
          * empty   -- dunkel (alle Kanaele < 50)    -> leere Zelle
          * valid   -- belegt UND echte Steinfarbe    -> echtes Puzzlestueck
          * garbage -- belegt ABER keine Steinfarbe   -> kein echtes Board
        So lassen sich 'leeres Brett' / 'volles Brett' / 'gar kein echtes Puzzle
        (Garbage, z.B. Fake-Fenster/falsche Position)' sauber trennen. Wirft nie.
        """
        valid = empty = garbage = 0
        try:
            for i in range(4):
                for j in range(6):
                    cx, cy = geometry.cell_point(i, j, self.board_size)
                    b, g, r = self._sample_cell_bgr(crop_image, cx, cy)
                    if b < 50 and g < 50 and r < 50:
                        empty += 1
                    elif self._is_valid_piece_color(b, g, r):
                        valid += 1
                    else:
                        garbage += 1
        except Exception:
            pass
        return {'valid': valid, 'empty': empty, 'garbage': garbage}

    def detect_end_game(self, crop_img):

        x, y = geometry.get_piece_point(self.board_size, self.key_points.get('getpiece'))


        if crop_img[y, x, 0] > 100 and crop_img[y, x, 1] > 150 and crop_img[y, x, 2] > 150:
            return False
        else:
            return True
