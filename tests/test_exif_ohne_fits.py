#!/usr/bin/env python3
"""
ForgePix — FITS-Dateien werden nicht nach EXIF gefragt.

    python3 tests/test_exif_ohne_fits.py

EXIF gibt es nur in Kamera-Dateiformaten. FITS hat einen eigenen Header und kein EXIF.
`exifread` beantwortet die Frage darum mit „File format not recognized." — direkt auf die
Konsole, nicht als Rückgabewert. Beim Stapeln von fünf Subs stand diese Zeile fünfmal im
Protokoll und las sich wie ein Fehler, obwohl nur eine sinnlose Frage gestellt worden war.

Das ist keine Kosmetik: ein Protokoll, in dem Meldungen stehen, die nichts bedeuten, wird
nicht mehr gelesen — und dann fällt auch die Meldung nicht auf, die etwas bedeutet.
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import focus_analysis  # noqa: E402


class TestKeinExifBeiFits(unittest.TestCase):

    def test_astro_formate_werden_uebersprungen(self):
        for e in (".fit", ".fits", ".fts", ".FITS", ".xisf", ".ser", ".npy"):
            self.assertFalse(focus_analysis._hat_vielleicht_exif("a" + e), e)

    def test_kameraformate_werden_gefragt(self):
        for e in (".jpg", ".JPG", ".jpeg", ".tif", ".tiff", ".arw", ".nef", ".cr2", ".dng"):
            self.assertTrue(focus_analysis._hat_vielleicht_exif("a" + e), e)

    def test_leere_und_endungslose_pfade_stuerzen_nicht(self):
        for p in (None, "", "ohne_endung"):
            focus_analysis._hat_vielleicht_exif(p)

    def test_ein_fits_erzeugt_keine_ausgabe(self):
        """Der eigentliche Test: die Zeile darf nicht mehr erscheinen."""
        try:
            import exifread  # noqa: F401
        except ImportError:
            self.skipTest("exifread nicht installiert — die Meldung kann gar nicht entstehen")
        import contextlib
        import io as _io
        from astropy.io import fits
        d = tempfile.mkdtemp(prefix="fp_exif_")
        try:
            p = os.path.join(d, "a.fit")
            fits.writeto(p, np.zeros((8, 8), np.float32))
            aus, err = _io.StringIO(), _io.StringIO()
            with contextlib.redirect_stdout(aus), contextlib.redirect_stderr(err):
                self.assertIsNone(focus_analysis._optics_via_exifread(p))
            self.assertNotIn("not recognized", aus.getvalue() + err.getvalue())
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
