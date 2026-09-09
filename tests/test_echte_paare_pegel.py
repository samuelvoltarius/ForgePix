"""Der Himmelspegel-Angleich der echten Rauschig/Sauber-Paare.

Warum es diesen Test gibt: die erste Fassung der Bank hatte ihn nicht, und **80 % des
Unterschieds zwischen rauschig und sauber war reiner Helligkeitsversatz** — der Himmel
schwankt von Aufnahme zu Aufnahme, das Leave-one-out-Mittel mittelt darueber hinweg. Ein
Entrauscher kann diesen Sockel nicht erraten; darauf zu trainieren heisst, dem Modell das
Wuerfeln der Helligkeit beizubringen. Und jede Messung an solchen Paaren misst zu 80 % den
Sockel: derselbe Entrauscher kam so auf Faktor 1,03, ohne Sockel auf 1,35.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "training"))
from prepare_paare_echt import pegel_angleichen


class HimmelspegelAngleichen(unittest.TestCase):
    def test_sockel_verschwindet_und_das_rauschen_bleibt(self):
        rng = np.random.default_rng(7)
        wahr = rng.random((64, 64, 3)).astype(np.float32) * 0.01 + 0.02
        rauschig = wahr + rng.normal(0, 0.002, wahr.shape).astype(np.float32)
        sauber = wahr + np.array([0.004, -0.003, 0.007], np.float32)  # je Kanal anderer Sockel

        aus = pegel_angleichen(rauschig, sauber)
        vorher = float(np.mean((rauschig - sauber) ** 2))
        nachher = float(np.mean((rauschig - aus) ** 2))
        rein_rauschen = float(np.mean((rauschig - wahr) ** 2))

        # Uebrig bleiben darf nur das Rauschen — nicht null. Genau das ist der Sinn: der
        # Sockel geht, die zu lernende Aufgabe bleibt.
        self.assertLess(nachher, vorher / 5)
        self.assertAlmostEqual(nachher, rein_rauschen, delta=0.1 * rein_rauschen)
        for kanal in range(3):
            self.assertAlmostEqual(
                float(np.median(rauschig[..., kanal]) - np.median(aus[..., kanal])),
                0.0, places=6)

    def test_ein_stern_im_eingang_verzieht_den_angleich_nicht(self):
        # Der Mittelwert laege hier um Groessenordnungen daneben, der Median nicht. In echten
        # Kacheln stehen immer Sterne, und sie stehen in beiden Bildern verschieden hell da.
        himmel = np.full((64, 64, 3), 0.02, np.float32)
        rauschig = himmel.copy()
        rauschig[30:34, 30:34] = 5.0
        aus = pegel_angleichen(rauschig, himmel.copy())
        self.assertAlmostEqual(float(np.median(aus)), 0.02, places=5)

    def test_mono_kachel_ohne_kanalachse(self):
        rauschig = np.full((16, 16), 0.05, np.float32)
        sauber = np.full((16, 16), 0.01, np.float32)
        self.assertAlmostEqual(
            float(np.median(pegel_angleichen(rauschig, sauber))), 0.05, places=6)


if __name__ == "__main__":
    unittest.main()
