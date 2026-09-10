"""Zwei Drizzle-Meldungen, die an M51 in die Irre fuehrten.

1. „Nur 100.00 % vollstaendig farbig belegt": 0,9999998 der Pixel waren belegt, die Warnung
   feuert bei JEDER Luecke, und auf zwei Stellen gerundet sind das 100,00. Eine Meldung, die
   sich selbst widerspricht, liest niemand zu Ende.
2. Drizzle ohne Zuschnitt plus Hintergrundkorrektur: abgelehnt wird das erst NACH dem Drizzle,
   an M51 nach rund zwei Stunden und ohne eine geschriebene Datei. Jetzt gibt es vorher eine
   Warnung.
"""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
import astro
import focus_cull_stack as fcs


class Lueckenmeldung(unittest.TestCase):
    def test_nennt_die_zahl_und_nie_hundert_prozent(self):
        abdeckung = np.ones((1000, 1000), bool)
        abdeckung[0, :3] = False                      # drei Luecken unter einer Million
        text = astro.abdeckung_meldung(abdeckung)
        self.assertIn("3 von 1000000", text)
        self.assertNotIn("100.00", text)
        self.assertNotIn("100,00", text)

    def test_der_gemessene_m51_fall(self):
        # 0,9999998 belegt — genau der Wert, der als „Nur 100.00 %" erschien.
        n = 5644 * 8288
        abdeckung = np.ones(n, bool)
        fehlend = round(n * (1 - 0.9999997862218805))
        abdeckung[:fehlend] = False
        text = astro.abdeckung_meldung(abdeckung)
        self.assertIn("%d von %d" % (fehlend, n), text)
        self.assertNotIn("100.00", text)


class Vorabwarnung(unittest.TestCase):
    def _args(self, **kw):
        basis = dict(autocrop=True, bg_extract=False, astro_deconv=False,
                     astro_synthstar=False, astro_denoise=0.0)
        basis.update(kw)
        return types.SimpleNamespace(**basis)

    def test_ohne_zuschnitt_mit_hintergrund_wird_gewarnt(self):
        self.assertEqual(fcs.drizzle_ohne_zuschnitt_gesperrt(
            self._args(autocrop=False, bg_extract=True)), ["Hintergrundkorrektur"])

    def test_alle_vier_werden_genannt(self):
        self.assertEqual(fcs.drizzle_ohne_zuschnitt_gesperrt(self._args(
            autocrop=False, bg_extract=True, astro_deconv=True, astro_synthstar=True,
            astro_denoise=0.5)),
            ["Hintergrundkorrektur", "Dekonvolution", "Sternkorrektur", "Entrauschen"])

    def test_mit_zuschnitt_nichts_zu_befuerchten(self):
        # Gegenprobe: der Normalfall darf keine Warnung ausloesen.
        self.assertEqual(fcs.drizzle_ohne_zuschnitt_gesperrt(
            self._args(autocrop=True, bg_extract=True, astro_denoise=0.5)), [])

    def test_ohne_zuschnitt_aber_ohne_nachbearbeitung_auch_nicht(self):
        # Genau der Aufruf, mit dem die ungeschnittene Gewichtskarte geholt wird.
        self.assertEqual(fcs.drizzle_ohne_zuschnitt_gesperrt(self._args(autocrop=False)), [])


if __name__ == "__main__":
    unittest.main()
