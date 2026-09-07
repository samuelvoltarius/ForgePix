#!/usr/bin/env python3
"""
ForgePix — eine abgeschnittene FITS-Datei darf keinen Stapellauf killen.

    python3 tests/test_kaputte_fits.py

In Alfreds Archiv liegt eine unvollstaendig gesicherte Aufnahme (IC5070). `astro._read_float`
stuerzte daran ab, und zwar so:

    TypeError: buffer is too small for requested array
      File ".../astropy/io/fits/file.py", line 439, in readarray
        return np.ndarray(shape=shape, dtype=dtype, offset=offset, buffer=self._mmap)

Eine Meldung aus dem Innersten von numpy, die **den Dateinamen nicht nennt**. Wer sie sieht,
weiss nicht, welche von 300 Aufnahmen gemeint ist — und der ganze Lauf ist beendet, unter
Umstaenden nach zwei Stunden Rechenzeit.

Der Fehler entsteht erst beim ZUGRIFF auf `hdu.data`, nicht beim Oeffnen: astropy liest den
Header, meldet hoechstens eine Warnung ("File may have been truncated") und faellt erst um,
wenn die Bilddaten wirklich gebraucht werden. Ein `try` um `fits.open` allein haette also nicht
geholfen.

`astro_quality.select_subs` faengt unlesbare Aufnahmen laengst ab und nennt sie einzeln
("-> 5/8 Subs behalten (3 davon nicht lesbar)"). Damit das auch hier greift, muss der Fehler
als `ForgePixFehler` MIT Dateiname herauskommen.
"""
import os
import sys
import shutil
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro  # noqa: E402
from constants import ForgePixFehler  # noqa: E402


class TestAbgeschnittenesFits(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_trunc_")
        self.addCleanup(shutil.rmtree, self.d, True)

    def _schreiben(self, name, anteil=1.0):
        """Ein FITS schreiben und danach auf `anteil` seiner Laenge kuerzen."""
        from astropy.io import fits
        pfad = os.path.join(self.d, name)
        daten = np.arange(256 * 256, dtype=np.uint16).reshape(256, 256)
        fits.PrimaryHDU(daten).writeto(pfad)
        if anteil < 1.0:
            voll = os.path.getsize(pfad)
            with open(pfad, "r+b") as fh:
                fh.truncate(int(voll * anteil))
        return pfad

    def test_eine_heile_datei_laesst_sich_lesen(self):
        """Die Gegenprobe zuerst — sonst wuerde ein Lesen, das IMMER scheitert, den Test
        unten ebenfalls bestehen."""
        bild = astro._read_float(self._schreiben("heil.fits"))
        self.assertIsNotNone(bild)
        self.assertGreater(bild.size, 0)

    def test_eine_abgeschnittene_datei_nennt_ihren_namen(self):
        pfad = self._schreiben("abgeschnitten.fits", anteil=0.55)
        with self.assertRaises(ForgePixFehler) as fall:
            astro._read_float(pfad)
        text = str(fall.exception)
        self.assertIn("abgeschnitten.fits", text,
                      "die Meldung nennt die Datei nicht: %s" % text)
        self.assertIn("unlesbar", text)

    def test_es_ist_kein_roher_TypeError_mehr(self):
        """Der Punkt der Aenderung: der Aufrufer soll einen ForgePixFehler abfangen koennen,
        keinen TypeError aus numpy."""
        pfad = self._schreiben("abgeschnitten2.fits", anteil=0.55)
        try:
            astro._read_float(pfad)
        except ForgePixFehler:
            pass
        except TypeError as e:
            self.fail("immer noch ein roher TypeError: %s" % e)

    def test_die_sub_bewertung_ueberspringt_sie(self):
        """Das eigentliche Ziel: eine kaputte Datei unter vielen kostet nicht den Lauf."""
        import astro_quality
        from constants import imwrite
        gut = []
        rng = np.random.default_rng(3)
        for i in range(4):
            g = np.clip(rng.normal(0.05, 0.004, (200, 200)), 0, 1).astype(np.float32)
            for _ in range(30):
                y, x = int(rng.integers(10, 190)), int(rng.integers(10, 190))
                g[y - 1:y + 2, x - 1:x + 2] += 0.5
            p = os.path.join(self.d, "gut_%d.tif" % i)
            imwrite(p, np.clip(np.dstack([g] * 3) * 65535, 0, 65535).astype(np.uint16))
            gut.append(p)
        kaputt = self._schreiben("mittendrin.fits", anteil=0.55)
        zeilen = []
        frames, behalten = astro_quality.select_subs(gut + [kaputt], log=zeilen.append)
        self.assertEqual(len(frames), 5, "die kaputte Datei verschwindet spurlos")
        self.assertNotIn(kaputt, behalten)
        self.assertTrue(any("mittendrin" in z for z in zeilen),
                        "die kaputte Datei wird nicht genannt: %s" % zeilen)


if __name__ == "__main__":
    unittest.main(verbosity=2)
