"""Reine Bilderkennung des Angel-Minispiels als Mixin (kein eigener Zustand).

Beherbergt die drei Erkennungs-Methoden des FishingBot, die ausschliesslich aus
dem Capture lesen (Fisch-Position, Uhr/Minispiel, Tagesbelohnung) und dabei nur
auf bereits in :class:`fishingbot.FishingBot` definierte Klassen-/Instanz-Attribute
(``needle_img``, ``FISH_RANGE``, ``fish_pos_x`` ...) zugreifen.

Als Mixin herausgezogen, damit der zustandsbehaftete Cast-/State-Machine-Teil in
:mod:`fishingbot` schlank bleibt. ``FishingBot`` erbt von
:class:`FishingDetectMixin`; die Methodenaufloesung (``self.detect`` etc.) und
jeder ``self.``-Zugriff bleiben damit byte-identisch zur fruheren Single-Class.
"""

import math
import cv2 as cv
from time import time

from fishing_match import _match_template_max


class FishingDetectMixin:
    """Pure Erkennungs-Methoden (Fisch / Minispiel / Tagesbelohnung).

    Enthaelt KEINE eigenen Attribute und KEIN ``__init__`` -- saemtlicher
    Zustand (``needle_img``, ``FISH_RANGE``, ``fish_pos_x`` ...) lebt weiterhin
    auf :class:`fishingbot.FishingBot`. Reines Verhalten, per MRO eingemischt.
    """

    def detect(self, haystack_img):

        # match the needle_image with the hasytack image (robust: ein abweichendes
        # Capture darf KEINEN cv2-Crash ausloesen -> dann "kein Fisch" (None)).
        ok, max_val, max_loc = _match_template_max(haystack_img, self.needle_img)
        if not ok:
            return None

        # needle_image's dimensions
        needle_w = self.needle_img.shape[1]
        needle_h = self.needle_img.shape[0]

        # get the position of the match image
        top_left = max_loc
        bottom_right = (top_left[0] + needle_w, top_left[1] + needle_h)

        # Draw the circle of the fish limits
        cv.circle(haystack_img,
                (int(haystack_img.shape[1] / 2), int(haystack_img.shape[0] / 2)),
                self.FISH_RANGE, color=(0, 0, 255), thickness=1)

        # Only the max level of match is greater than 0.5
        if max_val > 0.5:
            pos_x = (top_left[0] + bottom_right[0])/2
            pos_y = (top_left[1] + bottom_right[1])/2

            if self.fish_last_time:
                dist = math.sqrt((pos_x - self.fish_pos_x)**2 + (self.fish_pos_y - pos_y)**2)
                cv.rectangle(haystack_img, top_left, bottom_right,
                            color=(0, 255, 0), thickness=2, lineType=cv.LINE_4)

                # Calculate the fish velocity
                velo = dist/(time() - self.fish_last_time)

                if velo == 0.0:
                    return (pos_x, pos_y, True)
                elif velo >= 150:

                    # With this velocity the fish position will be predict

                    pro = self.FISH_VELO_PREDICT / dist
                    destiny_x = int(pos_x + (pos_x - self.fish_pos_x) * pro)
                    destiny_y = int(pos_y + (pos_y - self.fish_pos_y) * pro)

                    # Draw the predict line

                    cv.line(haystack_img, (int(pos_x), int(pos_y)),
                            (destiny_x, destiny_y), (0, 255, 0),  thickness=3)

                    return (destiny_x, destiny_y, False)

            # get the fish position and the time

            self.fish_pos_x = pos_x
            self.fish_pos_y = pos_y
            self.fish_last_time = time()

        return None

    def detect_minigame(self, haystack_img):
        # Robust gegen Form-/Typ-Abweichungen des Captures (kein Crash mehr).
        ok, max_val, _ = _match_template_max(haystack_img, self.needle_img_clock)
        if ok and max_val > self._best_minigame_conf:
            self._best_minigame_conf = max_val
        return ok and max_val > 0.9

    def detect_daily_reward(self, image):

        for i in range(0, 5):
            for j in range(0, 5):
                if int(image[10 + i,10 +  j, 0]) + int(image[10 + i,10 +  j, 1]) + int(image[10 + i,10 +  j, 2]) > 0:
                    return False

        return True
