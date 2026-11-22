#!/usr/bin/env python3
"""
`--superbias` muss die Kalibrierung tatsächlich verändern.

Bis 22.11.2026 wurde das Superbias-Modell erst NACH `_load_astro_calibration` gebaut und in
eine Variable geschrieben, die danach niemand mehr las. Das Protokoll meldete „Superbias:
Modell aus 3 Aufnahmen …", das Ergebnis war bitgleich mit einem Lauf ohne die Option —
gemessen an 8 echten Seestar-Aufnahmen (IC 5146): größte Abweichung genau 0,0. Außerdem
wurden die Bias-Aufnahmen debayert gelesen (H×B×3), alle anderen Master roh (H×B).

Mit der Korrektur: dieselben 8 Aufnahmen weichen um bis zu 0,006 ab (mittel 4,6e-5).
"""
import argparse
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))

import focus_cull_stack as F  # noqa: E402


class TestSuperbiasWirkt(unittest.TestCase):
    def setUp(self):
        from astropy.io import fits
        self.d = tempfile.mkdtemp()
        rng = np.random.default_rng(3)
        spalten = rng.normal(0, 30, 48)
        self.bias = []
        for i in range(4):
            kopf = fits.Header(); kopf["BAYERPAT"] = "RGGB"; kopf["IMAGETYP"] = "Bias"
            daten = (2000 + spalten[None, :] + rng.normal(0, 15, (32, 48))).astype(np.uint16)
            pfad = os.path.join(self.d, "b%d.fits" % i)
            fits.writeto(pfad, daten, kopf)
            self.bias.append(pfad)
        kopf = fits.Header(); kopf["BAYERPAT"] = "RGGB"; kopf["IMAGETYP"] = "Light"
        self.light = os.path.join(self.d, "light.fits")
        fits.writeto(self.light, np.full((32, 48), 5000, np.uint16), kopf)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _args(self, superbias):
        return argparse.Namespace(dark=None, flat=None, bias=None, no_auto_calib=True,
                                  superbias=superbias, dark_skalieren=False)

    def test_superbias_landet_in_der_kalibrierung(self):
        dark, flat, bias = F._load_astro_calibration(self.d, self._args(self.bias), [self.light])
        self.assertIsNotNone(bias, "Superbias wurde gebaut, aber nicht zurückgegeben")
        self.assertEqual(bias.ndim, 2, "Superbias muss roh (H×B) sein wie die anderen Master")
        # Ohne Dark wird der Bias direkt vom Licht abgezogen — also muss er im Dark stecken.
        self.assertIs(dark, bias)

    def test_gegenprobe_ohne_superbias_kein_bias(self):
        dark, flat, bias = F._load_astro_calibration(self.d, self._args(None), [self.light])
        self.assertIsNone(bias)
        self.assertIsNone(dark)

    def test_zu_wenige_aufnahmen_ist_fehler(self):
        with self.assertRaises(ValueError):
            F._load_astro_calibration(self.d, self._args(self.bias[:2]), [self.light])


if __name__ == "__main__":
    unittest.main()
