#!/usr/bin/env python3
"""
ForgePix — Tests für das Maskensystem (core/masken.py).

    python3 tests/test_masken.py     # oder: python3 -m unittest discover -s tests

Masken sind der Grund, warum PixInsight so viel mehr kann als eine Kette fester Werkzeuge:
dort lässt sich jeder Schritt nur dort anwenden, wo er hingehört. Entrauschen in den
Hintergrund, lokaler Kontrast in den Nebel.

An echten Daten gemessen (10 Subs M27, ASI294MC Pro, registriert, gestapelt, gestreckt):
    Entrauschen ohne Maske : Himmelrauschen 0,0252 -> 0,0155, Sternspitze 0,948 -> 0,919
    Entrauschen mit Maske  : Himmelrauschen 0,0252 -> 0,0161, Sternspitze bleibt 0,938
    lokaler Kontrast ohne Maske: Himmelrauschen 0,0252 -> 0,0640
    lokaler Kontrast mit Maske : Himmelrauschen bleibt 0,0255
Die Maske kostet also fast nichts an Wirkung und verhindert den Schaden.

WARUM `masken.sterne()` NICHT `astro.remove_stars()` benutzt: dessen Erkennung ist auf LINEARE
Subs ausgelegt und nimmt jeden Blob ab einem einzigen Pixel mit. Auf dem gestreckten Stack kamen
so 94 % des Bildes als „Stern" heraus (die Streckung hebt das Rauschen mit an). Mit Mindestfläche
und einer Schwelle aus der vorzeichenbehafteten Streuung sind es 10,8 %.
"""
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro    # noqa: E402
import masken   # noqa: E402


def _szene(h=260, w=260, seed=3):
    """Himmel + ein heller Nebelfleck + Sterne — die drei Bereiche, die getrennt werden sollen."""
    rng = np.random.default_rng(seed)
    g = np.full((h, w), 0.12, np.float32)
    neb = np.zeros((h, w), np.float32)
    cv2.circle(neb, (w // 2, h // 2), 45, 1.0, -1)
    g += cv2.GaussianBlur(neb, (0, 0), 18) * 0.45
    for _ in range(35):
        x, y = int(rng.integers(15, w - 15)), int(rng.integers(15, h - 15))
        p = np.zeros((h, w), np.float32)
        cv2.circle(p, (x, y), 1, 1.0, -1)
        g += cv2.GaussianBlur(p, (0, 0), 1.6) * float(rng.uniform(4, 12))
    g = np.clip(g + rng.normal(0, 0.012, (h, w)).astype(np.float32), 0, 1)
    return np.dstack([g * 0.85, g * 0.95, g]).astype(np.float32)


class TestMaskenBauen(unittest.TestCase):

    def setUp(self):
        self.f = _szene()
        self.sm = masken.sterne(self.f)

    def test_sternmaske_bleibt_eine_sternmaske(self):
        """Der entscheidende Punkt: über ein paar Prozent hinaus ist es keine Sternmaske mehr,
        sondern eine Decke über dem halben Bild."""
        anteil = masken.anteil(self.sm)
        self.assertLess(anteil, 0.25, "Sternmaske deckt %.1f %% ab" % (100 * anteil))
        self.assertGreater(anteil, 0.001, "gar keine Sterne gefunden")

    def test_hintergrund_und_nebel_ueberschneiden_sich_kaum(self):
        mh = masken.hintergrund(self.f, stern_maske=self.sm)
        mn = masken.nebel(self.f, stern_maske=self.sm)
        ueberlapp = float(np.mean(np.minimum(mh, mn)))
        self.assertLess(ueberlapp, 0.05,
                        "Hintergrund und Nebel ueberlappen zu %.3f" % ueberlapp)

    def test_nebelmaske_sitzt_auf_dem_nebel(self):
        mn = masken.nebel(self.f, stern_maske=self.sm)
        h, w = self.f.shape[:2]
        mitte = float(mn[h // 2 - 20:h // 2 + 20, w // 2 - 20:w // 2 + 20].mean())
        ecke = float(mn[5:45, 5:45].mean())
        self.assertGreater(mitte, 0.5, "Nebelmitte nicht erfasst (%.2f)" % mitte)
        self.assertLess(ecke, 0.2, "leere Ecke faelschlich als Nebel (%.2f)" % ecke)

    def test_helligkeitsmaske_trifft_den_bereich(self):
        m = masken.helligkeit(self.f, 0.0, 0.2, weich=0.02)
        lum = astro._gray(self.f)
        self.assertGreater(float(m[lum < 0.15].mean()), 0.8)
        self.assertLess(float(m[lum > 0.30].mean()), 0.05)

    def test_stern_maske_durchreichen_aendert_nichts_am_ergebnis(self):
        """Die Abkuerzung darf nur schneller sein, nicht anders."""
        a = masken.hintergrund(self.f, stern_maske=self.sm)
        b = masken.hintergrund(self.f)
        self.assertTrue(np.allclose(a, b, atol=1e-5))


class TestMaskenAnwenden(unittest.TestCase):

    def setUp(self):
        self.f = _szene()

    def test_maske_null_und_eins_sind_die_grenzfaelle(self):
        bearbeitet = np.zeros_like(self.f)
        h, w = self.f.shape[:2]
        aus = masken.anwenden(self.f, np.zeros((h, w), np.float32), bearbeitet)
        an = masken.anwenden(self.f, np.ones((h, w), np.float32), bearbeitet)
        self.assertTrue(np.allclose(aus, self.f, atol=1e-6))
        self.assertTrue(np.allclose(an, bearbeitet, atol=1e-6))

    def test_entrauschen_durch_die_hintergrundmaske_schont_die_sterne(self):
        """Der Hauptzweck. Ohne Maske frisst das Entrauschen die Sternspitzen mit."""
        sm = masken.sterne(self.f)
        mh = masken.hintergrund(self.f, stern_maske=sm)
        ent = astro.tv_denoise(self.f, 0.6, 6)
        ent_m = masken.anwenden(self.f, mh, ent)

        def spitze(a):
            return float(astro._gray(a).max())

        def rauschen(a):
            g = astro._gray(a)[5:45, 5:45]
            return float(np.median(np.abs(g - np.median(g))) * 1.4826)

        self.assertLess(rauschen(ent_m), rauschen(self.f) * 0.85,
                        "maskiertes Entrauschen wirkt kaum")
        self.assertGreaterEqual(spitze(ent_m), spitze(ent),
                                "maskiert duerfen die Sterne nicht staerker leiden")

    def test_unpassende_groessen_werden_abgelehnt(self):
        """Eine verrutschte Maske sieht man dem Ergebnis nicht an — darum lieber ein Fehler
        als eine stille Skalierung."""
        h, w = self.f.shape[:2]
        with self.assertRaises(ValueError):
            masken.anwenden(self.f, np.ones((h // 2, w), np.float32), self.f.copy())
        with self.assertRaises(ValueError):
            masken.anwenden(self.f, np.ones((h, w), np.float32), self.f[:, :w // 2])

    def test_werkzeuge_an_der_maske(self):
        m = masken.helligkeit(self.f, 0.0, 0.2)
        self.assertTrue(np.allclose(masken.invertieren(masken.invertieren(m)), m, atol=1e-6))
        self.assertLessEqual(masken.anteil(masken.verstaerken(m, 2.0)), masken.anteil(m) + 1e-6)
        self.assertEqual(masken.weichzeichnen(m, 2.0).shape, m.shape)
        self.assertIs(masken.weichzeichnen(m, 0.0), m)


if __name__ == "__main__":
    unittest.main(verbosity=2)
