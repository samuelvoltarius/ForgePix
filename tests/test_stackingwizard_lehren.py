#!/usr/bin/env python3
"""
ForgePix — Tests für die drei Punkte, die der Vergleich mit StackingWizard aufgedeckt hat.

    python3 tests/test_stackingwizard_lehren.py

Alle drei sind derselbe Fehlertyp: **es schlägt nichts fehl.** Der Stapel läuft durch und sieht
normal aus, nur ist er falsch oder er kommt gar nicht erst zustande.

1. **Bildgrösse aus der Mehrheit, nicht aus der ersten Datei.** Lag ein Ausreisser an erster
   Stelle — eine Voransicht, ein anders gebinntes Sub, ein Frame aus einer anderen Nacht —
   scheiterte der GANZE Stapel. Nachgestellt: 10 Frames, einer davon abweichend an Position 0,
   Abbruch, neun gute Aufnahmen verloren.

2. **Jede Aufnahme genau einmal.** Siril und DeepSkyStacker legen konvertierte Kopien neben die
   Originale. Doppelt gestapelt gewichten sie die Nacht falsch und brechen die
   Ausreisser-Erkennung, weil derselbe Wert zweimal in derselben Verteilung steht.

3. **Kalibrierbilder über den FITS-Header.** Vorher wurden nur Ordner erkannt, die „dark",
   „flats" oder „bias" heissen. Wer die Kalibrierbilder lose zwischen den Lights liegen hat,
   bekam still eine unkalibrierte Verrechnung.
"""
import os
import sys
import shutil
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro          # noqa: E402
import astro_input    # noqa: E402
from constants import imwrite  # noqa: E402


def _stille(*a, **k):
    pass


class TestMehrheitsgroesse(unittest.TestCase):
    """Ein Ausreisser darf nicht die ganze Nacht kosten."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_gr_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _frames(self, formen, praefix="f"):
        pfade = []
        for i, (h, w) in enumerate(formen):
            f = np.clip(np.random.default_rng(i).random((h, w, 3)).astype(np.float32), 0, 1)
            p = os.path.join(self.d, "%s_%02d.tif" % (praefix, i))
            imwrite(p, (f * 65535).astype(np.uint16))
            pfade.append(p)
        return pfade

    def test_ausreisser_an_erster_stelle_kostet_nicht_den_stapel(self):
        pfade = self._frames([(100, 120)] + [(96, 128)] * 9)
        erg = astro.stack(pfade, method="average", log=_stille)
        self.assertEqual(erg.shape[:2], (96, 128),
                         "die Mehrheit haette 96x128 sein muessen")

    def test_die_mehrheit_entscheidet_wirklich(self):
        """Gegenprobe: steht die Mehrheit auf der anderen Seite, gewinnt sie auch."""
        pfade = self._frames([(96, 128)] * 2 + [(100, 120)] * 4, praefix="g")
        erg = astro.stack(pfade, method="average", log=_stille)
        self.assertEqual(erg.shape[:2], (100, 120))

    def test_einheitliche_serie_bleibt_unveraendert(self):
        """Sicherung gegen stille Nebenwirkungen: ohne Ausreisser darf sich nichts aendern."""
        pfade = self._frames([(64, 80)] * 5, praefix="h")
        erg = astro.stack(pfade, method="average", log=_stille)
        self.assertEqual(erg.shape[:2], (64, 80))
        von_hand = np.mean(np.stack([astro._read_float(p) for p in pfade]), axis=0)
        self.assertLess(float(np.abs(erg - von_hand).mean()), 0.02)

    def test_groesse_wird_ohne_vollen_lesevorgang_bestimmt(self):
        pfade = self._frames([(48, 64)], praefix="k")
        self.assertEqual(astro._bildgroesse(pfade[0]), (48, 64))
        self.assertIsNone(astro._bildgroesse(os.path.join(self.d, "gibtsnicht.tif")))


class TestDoppelte(unittest.TestCase):
    """Dieselbe Aufnahme darf nur einmal in den Stapel."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_dop_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _lights(self, n=4):
        from astropy.io import fits
        pfade = []
        for i in range(n):
            p = os.path.join(self.d, "Light_%02d.fit" % i)
            fits.writeto(p, np.full((8, 8), 0.1, np.float32),
                         fits.Header({"IMAGETYP": "Light",
                                      "DATE-OBS": "2026-09-06T22:%02d:00" % i,
                                      "EXPTIME": 300.0}))
            pfade.append(p)
        return pfade

    def test_kopien_werden_erkannt(self):
        """So sehen die Kopien aus, die Siril hinterlaesst: anderer Name, gleicher Inhalt."""
        pfade = self._lights()
        for i in (1, 2):
            kopie = os.path.join(self.d, "pp_Light_%02d.fit" % i)
            shutil.copy(pfade[i], kopie)
            pfade.append(kopie)
        behalten, verworfen = astro_input.doppelte_aussortieren(sorted(pfade), log=_stille)
        self.assertEqual(len(behalten), 4)
        self.assertEqual(len(verworfen), 2)

    def test_echte_serie_bleibt_vollstaendig(self):
        """Der teuerste Fehlgriff waere, echte Aufnahmen fuer Kopien zu halten."""
        pfade = self._lights(6)
        behalten, verworfen = astro_input.doppelte_aussortieren(pfade, log=_stille)
        self.assertEqual(len(behalten), 6)
        self.assertEqual(verworfen, [])

    def test_ohne_zeitstempel_wird_nichts_verworfen(self):
        """Ohne DATE-OBS wird nicht geraten — lieber eine Kopie zu viel als ein Original weg."""
        from astropy.io import fits
        pfade = []
        for i in range(3):
            p = os.path.join(self.d, "ohne_%02d.fit" % i)
            fits.writeto(p, np.full((8, 8), 0.1, np.float32), fits.Header({"IMAGETYP": "Light"}))
            pfade.append(p)
        behalten, verworfen = astro_input.doppelte_aussortieren(pfade, log=_stille)
        self.assertEqual(len(behalten), 3)
        self.assertEqual(verworfen, [])


class TestKalibrierungAusHeader(unittest.TestCase):
    """Der Header weiss es, der Ordnername ist nur eine Gewohnheit."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_kal_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _gemischt(self):
        from astropy.io import fits
        nacht = os.path.join(self.d, "Nacht 2026-09-06")
        os.makedirs(nacht)
        for i in range(3):
            fits.writeto(os.path.join(nacht, "a_%02d.fit" % i),
                         np.full((16, 16), 0.1, np.float32), fits.Header({"IMAGETYP": "Light"}))
        for i in range(2):
            fits.writeto(os.path.join(nacht, "b_%02d.fit" % i),
                         np.full((16, 16), 0.01, np.float32),
                         fits.Header({"IMAGETYP": "Dark Frame"}))
        fits.writeto(os.path.join(nacht, "c_00.fit"), np.full((16, 16), 0.5, np.float32),
                     fits.Header({"IMAGETYP": "Flat Field"}))
        fits.writeto(os.path.join(nacht, "d_00.fit"), np.full((16, 16), 0.002, np.float32),
                     fits.Header({"IMAGETYP": "Bias Frame"}))
        return nacht

    def test_gemischter_ordner_ohne_namenskonvention(self):
        nacht = self._gemischt()
        gefunden = astro_input.kalibrierung_nach_header([nacht], log=_stille)
        self.assertEqual(len(gefunden["dark"]), 2)
        self.assertEqual(len(gefunden["flat"]), 1)
        self.assertEqual(len(gefunden["bias"]), 1)

    def test_die_lights_bleiben_getrennt(self):
        nacht = self._gemischt()
        self.assertEqual(len(astro_input.fits_lights(nacht)), 3)

    def test_bildart_aus_dem_header(self):
        from astropy.io import fits
        p = os.path.join(self.d, "x.fit")
        for kopf, erwartet in (("Light", "light"), ("Dark Frame", "dark"),
                               ("Flat Field", "flat"), ("Bias Frame", "bias"),
                               ("Master Dark", None)):
            fits.writeto(p, np.zeros((4, 4), np.float32), fits.Header({"IMAGETYP": kopf}),
                         overwrite=True)
            self.assertEqual(astro_input._bildart(p), erwartet, "IMAGETYP=%r" % kopf)


if __name__ == "__main__":
    unittest.main(verbosity=2)
