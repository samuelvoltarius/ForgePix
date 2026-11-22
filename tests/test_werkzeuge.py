#!/usr/bin/env python3
"""
Die Werkzeuge, die in die Oberfläche geholt wurden (core/werkzeuge.py).

Am wichtigsten ist die Umrechnung der Himmelsposition fürs Beschriften: ForgePix schreibt WCS
als PC + CDELT, `annotation` rechnet mit CD und nullbasierten Pixeln. Ein vergessenes „-1" bei
CRPIX verschiebt jede Beschriftung um ein Pixel, ohne dass etwas meldet — darum wird gegen
astropy selbst geprüft, nicht gegen die eigene Rechnung.
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))

import annotation  # noqa: E402
import werkzeuge  # noqa: E402


class TestWerkzeuge(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _wcs_fits(self):
        from astropy.io import fits
        from astropy.wcs import WCS
        w = WCS(naxis=2)
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        w.wcs.crval = [300.0, 22.7]
        w.wcs.crpix = [101.5, 81.0]
        w.wcs.cdelt = [-0.0003, 0.0003]
        winkel = np.radians(23.0)
        w.wcs.pc = [[np.cos(winkel), -np.sin(winkel)], [np.sin(winkel), np.cos(winkel)]]
        pfad = os.path.join(self.d, "geloest.fits")
        fits.writeto(pfad, np.zeros((160, 200), np.float32), w.to_header())
        return pfad, w

    def test_beschriftung_trifft_astropy(self):
        pfad, w = self._wcs_fits()
        loesung = werkzeuge.loesung_aus_fits(pfad)
        wcs = annotation._wcs_aus_loesung(loesung)
        ra = np.array([300.0, 300.02, 299.97]); dec = np.array([22.7, 22.69, 22.72])
        x, y = annotation.himmel_zu_pixel(ra, dec, wcs)
        ax, ay = w.world_to_pixel_values(ra, dec)           # astropy: nullbasiert
        self.assertLess(float(np.max(np.hypot(x - ax, y - ay))), 0.01)

    def test_ohne_wcs_klare_meldung(self):
        from astropy.io import fits
        pfad = os.path.join(self.d, "roh.fits")
        fits.writeto(pfad, np.zeros((10, 10), np.float32))
        with self.assertRaises(ValueError) as e:
            werkzeuge.loesung_aus_fits(pfad)
        self.assertIn("Himmelsposition", str(e.exception))

    def test_superbias_datei_ist_roh_und_markiert(self):
        from astropy.io import fits
        rng = np.random.default_rng(2)
        pfade = []
        for i in range(3):
            kopf = fits.Header(); kopf["BAYERPAT"] = "RGGB"
            p = os.path.join(self.d, "bias%d.fits" % i)
            fits.writeto(p, (1000 + rng.normal(0, 10, (24, 32))).astype(np.uint16), kopf)
            pfade.append(p)
        ziel = werkzeuge.superbias(pfade, os.path.join(self.d, "superbias.fits"), log=lambda *a: None)
        with fits.open(ziel) as h:
            self.assertEqual(h[0].data.shape, (24, 32))
            self.assertEqual(h[0].header["IMAGETYP"], "Bias")
            self.assertEqual(h[0].header["BAYERPAT"], "RGGB")
        zweit = werkzeuge.superbias(pfade, os.path.join(self.d, "superbias.fits"), log=lambda *a: None)
        self.assertNotEqual(ziel, zweit, "nie überschreiben")

    def test_superbias_verschiedene_groessen_abgelehnt(self):
        from astropy.io import fits
        pfade = []
        for i, form in enumerate(((8, 8), (8, 8), (8, 9))):
            p = os.path.join(self.d, "b%d.fits" % i)
            fits.writeto(p, np.full(form, 100, np.uint16))
            pfade.append(p)
        with self.assertRaises(ValueError):
            werkzeuge.superbias(pfade, os.path.join(self.d, "x.fits"), log=lambda *a: None)

    def test_ausserhalb_wird_gemeldet(self):
        zeilen = []
        anteil = werkzeuge._ausserhalb_melden(np.array([-0.1, 0.5, 1.2, 0.3]), zeilen.append)
        self.assertAlmostEqual(anteil, 0.5)
        self.assertTrue(zeilen and "begrenzt" in zeilen[0])


if __name__ == "__main__":
    unittest.main()
