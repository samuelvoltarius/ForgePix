#!/usr/bin/env python3
"""
ForgePix — Tests für gemischte Belichtungszeiten beim Stacken (`astro.stack(belichtungen=…)`).

    python3 tests/test_belichtungen.py     # oder: python3 -m unittest discover -s tests

Die Serie besteht aus 4 Subs zu 300 s und 8 zu 60 s, mit einem Satelliten in einem der kurzen.
Signal wächst mit der Zeit, Rauschen mit ihrer Wurzel — wie in der Wirklichkeit.

Der eigentliche Grund für die Skalierung ist NICHT der Rauschabstand, sondern die Ausreisser-
Erkennung: ohne sie vergleicht das Sigma-Clipping ein 60-s-Sub mit einem 300-s-Sub und hält das
kurze für einen Ausreisser. Gemessen:

    sigma ohne Zeiten          SNR 87.0   Satellitenrest 0.0423
    sigma mit Zeiten           SNR 66.4   Satellitenrest 0.0161
    sigma mit Zeiten + Gewicht SNR 85.8   Satellitenrest 0.0161

Skalieren allein kostet also Rauschabstand (die hochgerechneten kurzen Subs bringen ihr Rauschen
mit); erst zusammen mit der SNR-Gewichtung gibt es beides. Genau deshalb schaltet die Pipeline
die Gewichtung bei gemischten Zeiten selbst mit.

NICHT eingebaut: DeepSkyStackers „Entropy Weighted Average". Gebaut, gemessen, verworfen — eine
Satellitenspur trägt die höchste örtliche Streuung und bekommt damit das höchste Gewicht. Sie
stand danach bei 0,845 gegen einen Himmel von 0,036 (Sigma+Zeiten: 0,013 gegen 0,010), und die
Himmelsstreuung stieg auf das 414-fache.
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

import astro  # noqa: E402
from constants import imwrite  # noqa: E402


def _stille(*a, **k):
    pass


class TestGemischteBelichtungen(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_bel_")
        h = w = 160
        rng = np.random.default_rng(9)
        wahr = np.full((h, w), 0.05, np.float32)
        neb = np.zeros((h, w), np.float32)
        cv2.circle(neb, (w // 2, h // 2), 36, 1.0, -1)
        self.wahr = np.clip(wahr + cv2.GaussianBlur(neb, (0, 0), 10) * 0.04, 0, 1)
        self.pfade, self.zeiten = [], []
        for i in range(12):
            t = 300.0 if i < 4 else 60.0
            f = np.clip(self.wahr * (t / 300.0)
                        + rng.normal(0, 0.004 * np.sqrt(t / 300.0), (h, w)).astype(np.float32),
                        0, 1)
            if i == 6:                                   # Satellit in EINEM kurzen Sub
                cv2.line(f, (8, 24), (w - 8, h - 24), 0.9, 2)
            p = os.path.join(self.d, "f_%02d.tif" % i)
            imwrite(p, np.clip(np.dstack([f] * 3) * 65535, 0, 65535).astype(np.uint16))
            self.pfade.append(p)
            self.zeiten.append(t)
        self.spur = np.zeros((h, w), np.uint8)
        cv2.line(self.spur, (8, 24), (w - 8, h - 24), 1, 2)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _sat_rest(self, erg):
        """Wie viel vom Satelliten steht noch, bezogen auf den Himmel daneben?"""
        a = astro._gray(erg)
        return float(a[self.spur > 0].mean() - a[self.spur == 0].mean())

    def _snr(self, erg):
        a = astro._gray(erg)
        himmel = a[5:30, 5:30]
        return float(a[74:86, 74:86].mean() - himmel.mean()) / max(float(himmel.std()), 1e-9)

    def test_satellit_wird_mit_zeiten_deutlich_besser_verworfen(self):
        """Der eigentliche Grund für die Skalierung."""
        ohne = self._sat_rest(astro.stack(self.pfade, method="sigma", log=_stille))
        mit = self._sat_rest(astro.stack(self.pfade, method="sigma",
                                         belichtungen=self.zeiten, log=_stille))
        self.assertLess(mit, ohne * 0.6,
                        "Satellitenrest kaum besser (%.4f gegen %.4f)" % (mit, ohne))

    def test_zeiten_plus_gewicht_halten_den_rauschabstand(self):
        """Skalieren ALLEIN kostet SNR — das ist kein Nebeneffekt, sondern der Grund, warum die
        Pipeline die Gewichtung bei gemischten Zeiten selbst mitschaltet."""
        ohne = self._snr(astro.stack(self.pfade, method="sigma", log=_stille))
        nur_zeit = self._snr(astro.stack(self.pfade, method="sigma",
                                         belichtungen=self.zeiten, log=_stille))
        beides = self._snr(astro.stack(self.pfade, method="sigma", belichtungen=self.zeiten,
                                       weight=True, log=_stille))
        self.assertLess(nur_zeit, ohne, "Skalieren allein muesste SNR kosten — Testszene pruefen")
        self.assertGreater(beides, nur_zeit * 1.15,
                           "Gewichtung holt den Rauschabstand nicht zurueck (%.1f -> %.1f)"
                           % (nur_zeit, beides))

    def test_median_profitiert_klar(self):
        """Der Median über gemischte Pegel ist schlicht bedeutungslos."""
        ohne = self._snr(astro.stack(self.pfade, method="median", log=_stille))
        mit = self._snr(astro.stack(self.pfade, method="median",
                                    belichtungen=self.zeiten, log=_stille))
        self.assertGreater(mit, ohne * 1.2, "median %.1f -> %.1f" % (ohne, mit))

    def test_gleiche_zeiten_aendern_nichts(self):
        """Sicherung gegen stille Nebenwirkungen: bei einheitlicher Belichtung muss das
        Ergebnis Bit für Bit dem bisherigen entsprechen."""
        a = astro.stack(self.pfade, method="sigma", log=_stille)
        b = astro.stack(self.pfade, method="sigma", belichtungen=[300.0] * 12, log=_stille)
        self.assertTrue(np.array_equal(a, b), "einheitliche Zeiten haben das Ergebnis veraendert")

    def test_unbrauchbare_angaben_werden_ignoriert(self):
        a = astro.stack(self.pfade, method="sigma", log=_stille)
        for schlecht in ([0.0] * 12, [None] * 12, [300.0] * 5, None):
            with self.subTest(zeiten=schlecht):
                b = astro.stack(self.pfade, method="sigma", belichtungen=schlecht, log=_stille)
                self.assertTrue(np.array_equal(a, b))

    def test_keine_entropie_methode(self):
        """Festgehalten, damit sie nicht versehentlich zurueckkommt: das Verfahren belaedt
        genau die Stoerungen, die weggerechnet werden sollen (Satellit 0,845 gegen Himmel
        0,036; Himmelsstreuung 414-fach)."""
        with self.assertRaises(Exception):
            astro.stack(self.pfade, method="entropy", log=_stille)


if __name__ == "__main__":
    unittest.main(verbosity=2)
