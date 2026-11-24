"""Langzeitbelichtung aus der Hand: Ausrichtung „perspective“ und keine stillen Fehler mehr.

Gemessen am 24.11.2026 an einem Freihand-Video eines Wasserfalls (90 Bilder, bis ~15 px Versatz,
docs/vergleich/langzeit_vergleich.py; Schärfe fester Felsen ÷ Einzelbild an zwei Stellen):
ohne Ausrichtung 0,26 / 0,24, die bisher vorgeschlagene Stern-Ausrichtung „shift“ 0,77 / 0,22,
„feature“ 0,67 / 0,34 in 143 s, „perspective“ (ECC, Homographie, grob nach fein) 0,61 / 0,60 in
36 s; über die Kommandozeile mit Vorschlag 0,62 / 0,63. Die Merkmale sitzen bei einem Wasserfall
fast alle im bewegten Wasser.

Außerdem: ein unbekannter Modus wurde still zu „smooth“, die Stärke still beschnitten, und
unlesbare Bilder fielen ohne Meldung heraus.
"""
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, "..", "core"))

import longexp  # noqa: E402

KASTEN = (10, 70, 10, 100)          # fester „Fels“ links oben (y0, y1, x0, x1)


def _serie(ordner, n=12, h=180, w=260, seed=4):
    """Feste Textur (Fels) + ein Band mit Rauschen, das sich jedes Bild ändert (Wasser), aus der
    Hand: jedes Bild mit einer kleinen, bekannten Perspektive versetzt."""
    rng = np.random.default_rng(seed)
    fels = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 1.0)
    fels = (fels - fels.min()) / (fels.max() - fels.min())
    pfade = []
    for i in range(n):
        b = fels.copy()
        b[:, 130:200] = cv2.GaussianBlur(rng.random((h, 70)).astype(np.float32), (0, 0), 0.8)  # Wasser
        q = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        z = q + rng.uniform(-4, 4, q.shape).astype(np.float32)
        H = cv2.getPerspectiveTransform(q, z)
        b = cv2.warpPerspective(b, H, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        p = os.path.join(ordner, "f_%02d.png" % i)
        cv2.imwrite(p, cv2.cvtColor((b * 255 + 0.5).astype(np.uint8), cv2.COLOR_GRAY2BGR))
        pfade.append(p)
    return pfade


def _schaerfe(b):
    g = cv2.cvtColor(np.asarray(b, np.float32), cv2.COLOR_BGR2GRAY)
    lap = np.abs(cv2.Laplacian(g, cv2.CV_32F))
    y0, y1, x0, x1 = KASTEN
    return float(lap[y0:y1, x0:x1].mean())


class TestPerspektive(unittest.TestCase):
    def _rel(self, align):
        with tempfile.TemporaryDirectory() as d:
            pfade = _serie(d)
            einzel = _schaerfe(cv2.imread(pfade[len(pfade) // 2]).astype(np.float32) / 255)
            r = longexp.combine(pfade, mode="smooth", align=align, work_dir=d, log=lambda *a: None)
        return _schaerfe(r) / einzel

    def test_perspektive_haelt_den_fels_scharf(self):
        # gemessen: perspective 0,83, feature 0,85, ohne Ausrichtung 0,32 (lineares Umrechnen
        # kostet etwas Schärfe; 1,0 ist nicht erreichbar)
        self.assertGreater(self._rel("perspective"), 0.75)

    def test_gegenprobe_ohne_ausrichtung_verwischt(self):
        self.assertLess(self._rel("none"), 0.6)

    def test_shift_ohne_sterne_sagt_warum(self):
        """„shift“ ist die Stern-Ausrichtung. An einer Tagesszene brach sie mit „keine Frames zum
        Stacken“ ab — ohne Hinweis, dass Sterne fehlen und was stattdessen hilft."""
        with self.assertRaises(RuntimeError) as k:
            self._rel("shift")
        self.assertIn("perspective", str(k.exception))

    def test_vorschlag_bei_verwackeln_ist_perspektive(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(longexp.suggest_mode(_serie(d))["align"], "perspective")


class TestKeineStillenFehler(unittest.TestCase):
    def test_unbekannter_modus(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                longexp.combine(_serie(d, n=3), mode="glatt", work_dir=d, log=lambda *a: None)

    def test_unbekannte_ausrichtung(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                longexp.combine(_serie(d, n=3), align="frei", work_dir=d, log=lambda *a: None)

    def test_staerke_ausserhalb(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                longexp.combine(_serie(d, n=3), strength=1.5, work_dir=d, log=lambda *a: None)

    def test_unlesbares_bild_wird_genannt(self):
        with tempfile.TemporaryDirectory() as d:
            pfade = _serie(d, n=4)
            kaputt = os.path.join(d, "kaputt.png")
            with open(kaputt, "wb") as f:
                f.write(b"kein bild")
            meldungen = []
            longexp.combine(pfade + [kaputt], align="perspective", work_dir=d, log=meldungen.append)
        self.assertTrue(any("kaputt.png" in m for m in meldungen), meldungen[-3:])


if __name__ == "__main__":
    unittest.main()
