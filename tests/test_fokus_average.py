"""Fokus-Stacking „average“ (Helicon Method A) muss scharf werden, nicht nur weich.

Gemessen am 24.11.2026 (docs/vergleich/fokus_vergleich.py, Schärfe je Kachel ÷ schärfstes
Einzelbild an derselben Stelle): mit linearer Gewichtung lag die Methode bei 0,29 (Platine) bzw.
0,15 (zweite Reihe) und verpasste an 100 % der Stellen den Fokus — sie war ein Weichzeichner.
Grund: ist ein Bild dreimal so scharf wie sechs andere, bekommt es linear nur ein Drittel Gewicht.
"""
import os
import sys
import unittest

import cv2
import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, "..", "core"))

import stacker  # noqa: E402


def _reihe(n=7, h=160, w=240, seed=2):
    """Textur; Bild 0 links scharf, Bild 1 rechts scharf, die übrigen LEICHT unscharf (σ 1), alle
    mit etwas Rauschen — wie eine echte Reihe. Erste Fassung nahm σ 3 ohne Rauschen: da reichte
    schon die lineare Gewichtung (0,80), die Gegenprobe fiel nicht. So trifft es die echte
    Messung: linear 0,26 (Platine echt 0,29)."""
    rng = np.random.default_rng(seed)
    textur = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 0.7)
    textur = (textur - textur.min()) / (textur.max() - textur.min())
    unscharf = cv2.GaussianBlur(textur, (0, 0), 1.0)
    bilder = []
    for i in range(n):
        b = unscharf.copy()
        if i == 0:
            b[:, : w // 2] = textur[:, : w // 2]
        elif i == 1:
            b[:, w // 2:] = textur[:, w // 2:]
        b = b + rng.normal(0, 0.01, b.shape).astype(np.float32)
        bilder.append(cv2.cvtColor((np.clip(b, 0, 1) * 255 + 0.5).astype(np.uint8), cv2.COLOR_GRAY2BGR))
    return bilder, textur


def _schaerfe(g):
    return float(cv2.Laplacian(g.astype(np.float32), cv2.CV_32F).var())


class TestAverageWirdScharf(unittest.TestCase):
    def _ausbeute(self, **kw):
        bilder, textur = _reihe()
        out = stacker.focus_stack_average(bilder, log=lambda *a: None, **kw)
        g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        w = g.shape[1]
        ideal = textur
        return [(_schaerfe(g[10:-10, a + 10:b - 10]) / _schaerfe(ideal[10:-10, a + 10:b - 10]))
                for a, b in ((0, w // 2), (w // 2, w))]

    def test_beide_haelften_scharf(self):
        for q in self._ausbeute():
            self.assertGreater(q, 0.8, q)
            self.assertLess(q, 1.3, q)                        # keine Überzeichnung

    def test_gegenprobe_linear_bleibt_unscharf(self):
        """Mit der alten linearen Gewichtung muss der Test fallen."""
        for q in self._ausbeute(steilheit=1):
            self.assertLess(q, 0.5, q)

    def test_steilheit_ausserhalb_wird_gemeldet(self):
        bilder, _ = _reihe(n=3)
        with self.assertRaises(ValueError):
            stacker.focus_stack_average(bilder, steilheit=0, log=lambda *a: None)

    def test_16bit_wie_8bit(self):
        bilder, _ = _reihe()
        a = stacker.focus_stack_average(bilder, log=lambda *a: None).astype(np.float32) / 255
        b16 = [(b.astype(np.uint16) * 257) for b in bilder]
        b = stacker.focus_stack_average(b16, log=lambda *a: None).astype(np.float32) / 65535
        self.assertLess(float(np.abs(a - b).max()), 2 / 255)


if __name__ == "__main__":
    unittest.main()
