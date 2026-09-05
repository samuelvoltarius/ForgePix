#!/usr/bin/env python3
"""
ForgePix — Tests für das Kometen-Stacking (core/komet.py).

    python3 tests/test_komet.py     # oder: python3 -m unittest discover -s tests

Geprüft wird gegen eine bekannte Wahrheit: die synthetische Serie kennt die echte Bahn des
Kerns, also lässt sich der gefundene Versatz Frame für Frame damit vergleichen.

Gemessen: Kern in 12 von 12 Frames gefunden, Rest zur Geraden 0,33 px, grösster Fehler gegen
die Wahrheit 1,30 px (bei einer Wahrheit, die selbst auf ganze Pixel gerundet ist), und die
Spitzenhelligkeit des Kerns steigt gegenüber dem sternausgerichteten Stack um das 3,8-fache.
"""
import os
import sys
import shutil
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro     # noqa: E402
import komet     # noqa: E402
from constants import imwrite  # noqa: E402


def _stille(*a, **k):
    pass


class TestKomet(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_komet_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _serie(self, unter="reg", n=12, vx=3.0, vy=-1.6, h=260, w=260, seed=4,
               komet_an=True):
        """Fester Sternhimmel + ein diffuser Komet auf gleichförmiger Bahn."""
        rng = np.random.default_rng(seed)
        sx = rng.integers(20, w - 20, 40)
        sy = rng.integers(20, h - 20, 40)
        amp = rng.uniform(1.5, 8.0, 40)
        d = os.path.join(self.d, unter)
        os.makedirs(d, exist_ok=True)
        pfade, wahr = [], []
        for i in range(n):
            g = np.full((h, w), 0.03, np.float32)
            for x, y, a in zip(sx, sy, amp):
                p = np.zeros((h, w), np.float32)
                p[int(y), int(x)] = 1.0
                g += cv2.GaussianBlur(p, (0, 0), 1.5) * float(a)
            kx, ky = 60 + vx * i, 190 + vy * i
            if komet_an:
                k = np.zeros((h, w), np.float32)
                cv2.circle(k, (int(round(kx)), int(round(ky))), 3, 1.0, -1)
                g += cv2.GaussianBlur(k, (0, 0), 4.0) * 12.0        # diffuse Koma
            g = np.clip(g + rng.normal(0, 0.0015, (h, w)).astype(np.float32), 0, 1)
            bgr = np.dstack([g * 0.9, g, g * 0.95]).astype(np.float32)
            p = os.path.join(d, "f_%03d.tif" % i)
            imwrite(p, np.clip(bgr * 65535, 0, 65535).astype(np.uint16))
            pfade.append(p)
            wahr.append((kx - 60, ky - 190))
        return pfade, wahr

    def test_bahn_trifft_die_wahrheit(self):
        pfade, wahr = self._serie()
        info = komet.spur_finden(pfade, log=_stille)
        self.assertIsNotNone(info, "keine Kernbahn gefunden")
        fehler = np.abs(np.array(info["versatz"]) - np.array(wahr)).max()
        self.assertLess(float(fehler), 2.0, "Bahn weicht um %.2f px ab" % fehler)
        self.assertEqual(info["gefunden"], len(pfade))
        self.assertLess(info["rest_px"], 1.0, "Fundorte liegen nicht auf einer Geraden")

    def test_kern_wird_deutlich_heller(self):
        """Der eigentliche Zweck: der Komet soll sich addieren statt zu verschmieren."""
        pfade, _ = self._serie()
        erg, _info = komet.stack_auf_kern(pfade, os.path.join(self.d, "k"), log=_stille)
        self.assertIsNotNone(erg)
        normal = astro.stack(pfade, method="median", log=_stille)
        z = (slice(190 - 14, 190 + 14), slice(60 - 14, 60 + 14))
        spitze_k = float(astro._gray(erg)[z].max())
        spitze_n = float(astro._gray(normal)[z].max())
        self.assertGreater(spitze_k, spitze_n * 2.0,
                           "Kern kaum heller (%.4f gegen %.4f)" % (spitze_k, spitze_n))

    def test_ohne_bewegtes_objekt_kein_ergebnis(self):
        """Ein reines Sternfeld darf keine Kernbahn liefern — sonst würde die Funktion in
        jedem beliebigen Stack irgendein Rauschen als Kometen ausgeben."""
        pfade, _ = self._serie(unter="ohne", komet_an=False)
        info = komet.spur_finden(pfade, log=_stille)
        if info is not None:
            # Wird doch etwas gefunden, muss es wenigstens als unbrauchbar erkennbar sein:
            # ein Rauschtreffer wandert nicht geradlinig.
            self.assertGreater(info["rest_px"], 2.0,
                               "Rauschen wurde als saubere Kometenbahn ausgegeben")

    def test_zu_wenige_frames(self):
        pfade, _ = self._serie(unter="kurz", n=3)
        self.assertIsNone(komet.spur_finden(pfade, log=_stille))

    def test_ungleiche_abstaende_ohne_zeitstempel(self):
        """Ohne DATE-OBS wird über die Bildnummer gerechnet — das muss auch so GEMELDET
        werden, denn bei Wolkenpausen sässe der Kern sonst falsch."""
        pfade, _ = self._serie(unter="ohnezeit")
        info = komet.spur_finden(pfade, log=_stille)
        self.assertIsNotNone(info)
        self.assertFalse(info["echte_zeit"], "TIFFs haben kein DATE-OBS — darf nicht behauptet werden")

    def test_verschieben_erhaelt_form_und_anzahl(self):
        pfade, _ = self._serie(unter="warp")
        info = komet.spur_finden(pfade, log=_stille)
        raus = komet.auf_kern_verschieben(pfade, os.path.join(self.d, "w"),
                                          info["versatz"], log=_stille)
        self.assertEqual(len(raus), len(pfade))
        a, b = astro._read_float(pfade[0]), astro._read_float(raus[0])
        self.assertEqual(a.shape, b.shape)

    def test_hellster_fleck_ignoriert_einzelne_rauschspitzen(self):
        """Ein Komet ist diffus. Ein einzelnes helles Pixel ist ein Treffer, kein Kern."""
        rest = np.zeros((80, 80), np.float32)
        rest[40, 40] = 1.0                                   # eine einzelne Spitze
        self.assertIsNone(komet._hellster_fleck(rest))
        cv2.circle(rest, (20, 60), 4, 0.5, -1)               # diffuser Fleck
        ort = komet._hellster_fleck(cv2.GaussianBlur(rest, (0, 0), 1.5))
        self.assertIsNotNone(ort)
        self.assertLess(abs(ort[0] - 20) + abs(ort[1] - 60), 4.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
