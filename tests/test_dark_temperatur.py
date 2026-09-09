"""`--dark-skalieren` konnte die TEMPERATUR nie umrechnen — zwei Sperren davor.

An echten Daten gefunden (NGC 7023, 09.09.2026): 215 Lights bei −20,2 °C, dazu ein passendes
Master-Dark, das in allem uebereinstimmt (ASI533MC Pro, 60 s, Gain 95, Offset 30, RGGB, 3008²)
ausser der Temperatur: −15,0 °C. Genau der Fall, fuer den es `--dark-skalieren` gibt.

Der Lauf brach ab: *„Kalibrierung/Aufnahmeserie passt nicht: Sensortemperatur −15,0 … statt
−20,2"*. Zwei unabhaengige Sperren:

1. `validate` nahm `scale_dark` nur fuer die BELICHTUNGSZEIT aus der Pruefung, nicht fuer die
   Temperatur. Der Abbruch kam also, bevor irgendetwas skaliert werden konnte.
2. Selbst ohne diese Sperre haette es nicht geholfen: `dark_skalieren` wurde nur aufgerufen,
   wenn die BELICHTUNGSZEITEN auseinanderlagen. Bei gleichen Zeiten und abweichender
   Temperatur — dem haeufigsten Fall einer Dark-Bibliothek — lief die Umrechnung nie an,
   obwohl die Funktion den Temperaturteil kann und ihre Beschreibung ihn ausdruecklich nennt.
"""
import os
import sys
import tempfile
import unittest

import numpy as np
from astropy.io import fits

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
import calibration_metadata
from constants import ForgePixFehler


def _schreiben(ordner, name, **karten):
    pfad = os.path.join(ordner, name)
    kopf = fits.Header()
    for k, v in dict(INSTRUME="ZWO ASI533MC Pro", GAIN=95, OFFSET=30, XBINNING=1,
                     YBINNING=1, BAYERPAT="RGGB", EXPTIME=60.0).items():
        kopf[k] = v
    for k, v in karten.items():
        kopf[k] = v
    fits.writeto(pfad, np.zeros((8, 8), np.uint16), kopf, overwrite=True)
    return pfad


class DarkTemperatur(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ordner = self._tmp.name
        self.light = _schreiben(self.ordner, "light.fits", **{"CCD-TEMP": -20.2})
        self.dark = _schreiben(self.ordner, "dark.fits", **{"CCD-TEMP": -15.0})
        self.addCleanup(self._tmp.cleanup)

    def test_ohne_skalieren_bleibt_der_abbruch(self):
        # 5,2 K sind rund 80 % mehr Dunkelstrom. Unkorrigiert abzuziehen waere falsch, und
        # stillschweigend waere es schlimmer als ein Abbruch.
        with self.assertRaisesRegex(ForgePixFehler, "Sensortemperatur"):
            calibration_metadata.validate([self.light], {"dark": [self.dark]},
                                          scale_dark=False)

    def test_mit_skalieren_laeuft_es_durch(self):
        bericht = calibration_metadata.validate([self.light], {"dark": [self.dark]},
                                                scale_dark=True)
        self.assertEqual(bericht["fits_calibration_checked"]["dark"], 1)

    def test_auch_mit_skalieren_bleibt_eine_endliche_grenze(self):
        # Das Modell 2^(dT/6) beschreibt den mittleren Dunkelstrom, nicht einzelne heisse
        # Pixel. Ein Dark 25 Grad daneben ist kein Skalierungsfall mehr.
        weit = _schreiben(self.ordner, "weit.fits", **{"CCD-TEMP": 5.0})
        with self.assertRaisesRegex(ForgePixFehler, "Sensortemperatur"):
            calibration_metadata.validate([self.light], {"dark": [weit]}, scale_dark=True)

    def test_darks_untereinander_bleiben_streng(self):
        # Ein Master aus Aufnahmen verschiedener Temperatur ist schon vor jeder Skalierung
        # falsch — daran aendert --dark-skalieren nichts.
        zweites = _schreiben(self.ordner, "dark2.fits", **{"CCD-TEMP": -9.0})
        with self.assertRaisesRegex(ForgePixFehler, "Sensortemperatur"):
            calibration_metadata.validate([self.light], {"dark": [self.dark, zweites]},
                                          scale_dark=True)

    def test_gleiche_belichtung_verschiedene_temperatur_loest_die_umrechnung_aus(self):
        """Die zweite Sperre: der Ausloeser sah nur die Belichtungszeit."""
        import astro
        dunkel = np.full((16, 16), 0.10, np.float32)
        # Lights kaelter als das Dark -> der Dunkelstromanteil muss KLEINER werden.
        kalt = astro.dark_skalieren(dunkel, 60.0, 60.0, bias=np.zeros((16, 16), np.float32),
                                    ziel_temp=-20.2, dark_temp=-15.0,
                                    log=lambda *a, **k: None)
        self.assertLess(float(np.mean(kalt)), float(np.mean(dunkel)))
        # 2^(-5,2/6) = 0,548
        self.assertAlmostEqual(float(np.mean(kalt)) / float(np.mean(dunkel)), 0.548, places=2)
        # Und andersherum: waermere Lights brauchen mehr.
        warm = astro.dark_skalieren(dunkel, 60.0, 60.0, bias=np.zeros((16, 16), np.float32),
                                    ziel_temp=-9.0, dark_temp=-15.0,
                                    log=lambda *a, **k: None)
        self.assertGreater(float(np.mean(warm)), float(np.mean(dunkel)))


if __name__ == "__main__":
    unittest.main()
