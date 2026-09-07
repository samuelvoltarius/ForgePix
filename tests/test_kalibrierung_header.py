#!/usr/bin/env python3
"""
ForgePix — Kalibrierbilder über den FITS-Header finden, aber nur die passenden.

    python3 tests/test_kalibrierung_header.py

Die Suche nach Kalibrierbildern über die Kopfdaten löst ein echtes Problem: wer seine Darks
lose zwischen den Lights liegen hat oder den Ordner „Kalibrierung 2026-09" nennt, bekam
stillschweigend eine unkalibrierte Verrechnung.

Sie durchsucht dafür den **übergeordneten** Ordner, und zwar rekursiv. Wer `D:\\astro\\M31`
wählt, durchsucht damit `D:\\astro` mit allen anderen Objekten, Kameras und Belichtungszeiten.
Ohne Auswahl landeten fremde Darks in der Liste, und der Lauf starb anschliessend an
`calibration_metadata.validate` mit „Kalibrierung/Aufnahmeserie passt nicht" — **statt einfach
ohne Kalibrierung weiterzurechnen**. Genau das ist in dieser Sitzung versehentlich passiert:
Testdateien im übergeordneten Ordner haben einen fremden Test zum Absturz gebracht.

Ein Dark der falschen Länge ist dabei die tückischste Sorte: es zieht den falschen Dunkelstrom
ab, und im fertigen Bild sieht man das nicht.
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro_input  # noqa: E402


def _stille(*a, **k):
    pass


class TestPassendeKalibrierung(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_kal_")
        self._schreiben("light1.fit")
        self._schreiben("light2.fit")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _schreiben(self, name, hoehe=8, breite=8, **felder):
        from astropy.io import fits
        kopf = {"IMAGETYP": "Light", "INSTRUME": "ZWO ASI294MC Pro", "EXPTIME": 300.0,
                "FILTER": "L"}
        kopf.update(felder)
        fits.writeto(os.path.join(self.d, name), np.zeros((hoehe, breite), np.float32),
                     fits.Header(kopf))
        return os.path.join(self.d, name)

    def _suchen(self):
        return astro_input.kalibrierung_nach_header(
            [self.d], log=_stille,
            passend_zu=[os.path.join(self.d, "light1.fit")])

    def _namen(self, art):
        return sorted(os.path.basename(p) for p in self._suchen()[art])

    def test_passendes_dark_wird_genommen(self):
        self._schreiben("dark_passt.fit", IMAGETYP="Dark", EXPTIME=300.0)
        self.assertEqual(self._namen("dark"), ["dark_passt.fit"])

    def test_dark_falscher_laenge_faellt_raus(self):
        """Die tueckischste Sorte: es zieht den falschen Dunkelstrom ab, und man sieht es
        im fertigen Bild nicht."""
        self._schreiben("dark_60s.fit", IMAGETYP="Dark", EXPTIME=60.0)
        self.assertEqual(self._namen("dark"), [])

    def test_dark_fremder_kamera_faellt_raus(self):
        self._schreiben("dark_fremd.fit", IMAGETYP="Dark", EXPTIME=300.0,
                        INSTRUME="Seestar S30")
        self.assertEqual(self._namen("dark"), [])

    def test_dark_anderer_sensorgroesse_faellt_raus(self):
        self._schreiben("dark_gross.fit", IMAGETYP="Dark", EXPTIME=300.0, hoehe=16, breite=16)
        self.assertEqual(self._namen("dark"), [])

    def test_flat_mit_falschem_filter_faellt_raus(self):
        self._schreiben("flat_L.fit", IMAGETYP="Flat", FILTER="L", EXPTIME=1.0)
        self._schreiben("flat_Ha.fit", IMAGETYP="Flat", FILTER="Ha", EXPTIME=1.0)
        self.assertEqual(self._namen("flat"), ["flat_L.fit"])

    def test_flat_darf_eine_andere_belichtung_haben(self):
        """Ein Flat wird kurz belichtet — die Zeit darf und muss abweichen."""
        self._schreiben("flat_L.fit", IMAGETYP="Flat", FILTER="L", EXPTIME=0.5)
        self.assertEqual(self._namen("flat"), ["flat_L.fit"])

    def test_alles_zusammen(self):
        self._schreiben("dark_passt.fit", IMAGETYP="Dark", EXPTIME=300.0)
        self._schreiben("dark_60s.fit", IMAGETYP="Dark", EXPTIME=60.0)
        self._schreiben("dark_fremd.fit", IMAGETYP="Dark", EXPTIME=300.0,
                        INSTRUME="Seestar S30")
        self._schreiben("flat_L.fit", IMAGETYP="Flat", FILTER="L", EXPTIME=1.0)
        self._schreiben("flat_Ha.fit", IMAGETYP="Flat", FILTER="Ha", EXPTIME=1.0)
        g = self._suchen()
        self.assertEqual([os.path.basename(p) for p in g["dark"]], ["dark_passt.fit"])
        self.assertEqual([os.path.basename(p) for p in g["flat"]], ["flat_L.fit"])

    def test_ohne_vorgabe_bleibt_alles_drin(self):
        """Ohne `passend_zu` bleibt das alte Verhalten — sonst braeche ein anderer Aufrufer."""
        self._schreiben("dark_60s.fit", IMAGETYP="Dark", EXPTIME=60.0)
        g = astro_input.kalibrierung_nach_header([self.d], log=_stille)
        self.assertEqual(len(g["dark"]), 1)


class TestVergleich(unittest.TestCase):
    """`_passt_dazu` einzeln — fehlende Angaben duerfen nicht ausschliessen."""

    L = {"kamera": "ZWO ASI294MC Pro", "breite": 100, "hoehe": 80, "belichtung": 300.0,
         "filter": "L"}

    def test_gleiches_passt(self):
        self.assertTrue(astro_input._passt_dazu(dict(self.L), self.L, "dark"))

    def test_unbekannte_felder_schliessen_nicht_aus(self):
        """Ein Kalibrierbild ohne INSTRUME ist nicht automatisch das falsche. Wer aus einer
        Nicht-Angabe einen Ausschluss macht, verwirft brauchbare Bilder."""
        k = {"kamera": "", "breite": 100, "hoehe": 80, "belichtung": 300.0, "filter": ""}
        self.assertTrue(astro_input._passt_dazu(k, self.L, "dark"))

    def test_leere_eingabe(self):
        self.assertFalse(astro_input._passt_dazu({}, self.L, "dark"))
        self.assertFalse(astro_input._passt_dazu(dict(self.L), {}, "dark"))

    def test_halbe_sekunde_toleranz_bei_darks(self):
        """ASIAIR schreibt 300.0, N.I.N.A. manchmal 299.98 — das ist dieselbe Aufnahme."""
        k = dict(self.L); k["belichtung"] = 299.98
        self.assertTrue(astro_input._passt_dazu(k, self.L, "dark"))
        k["belichtung"] = 240.0
        self.assertFalse(astro_input._passt_dazu(k, self.L, "dark"))

    def test_bias_braucht_keine_belichtung(self):
        k = dict(self.L); k["belichtung"] = 0.0
        self.assertTrue(astro_input._passt_dazu(k, self.L, "bias"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
