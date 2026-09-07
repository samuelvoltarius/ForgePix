#!/usr/bin/env python3
"""
ForgePix — Tests für die Kamera-Erkennung aus dem FITS-Header.

    python3 tests/test_kamera_erkennung.py

Ohne erkannte Kamera gibt es im Messbericht kein Farburteil — und im DAU-Modus trägt niemand
eine Kamera von Hand ein. Deshalb wird der Schlüssel aus `INSTRUME` abgeleitet.

Der wichtigste Test ist hier NICHT, dass die Erkennung trifft, sondern dass sie **schweigt,
wenn sie sich nicht sicher ist**. `ASI294MC` (IMX294, 4,63 µm) und `ASI294MM` (IMX492,
2,315 µm) unterscheiden sich um einen Buchstaben und um den Faktor zwei in der Pixelgröße. Ein
falsch erkannter Sensor führt zu einem Farburteil über die falsche Kamera und zu einer
Abbildungsskala, die um 100 % danebenliegt — also zu einem erfundenen Befund, der sich wie eine
Messung liest. Nichts zu sagen ist in dem Fall die richtige Antwort.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import equipment  # noqa: E402
import messbericht  # noqa: E402


class TestKameraAusName(unittest.TestCase):

    def test_treffer_mit_und_ohne_hersteller(self):
        """ASIAIR schreibt "ZWO ASI294MC Pro", N.I.N.A. an derselben Kamera oft nur
        "ASI294MC Pro". Beides muss auf denselben Schluessel fuehren."""
        self.assertEqual(equipment.kamera_aus_name("ZWO ASI294MC Pro"), "asi294mc")
        self.assertEqual(equipment.kamera_aus_name("ASI294MC Pro"), "asi294mc")

    def test_mc_und_mm_werden_nicht_verwechselt(self):
        self.assertEqual(equipment.kamera_aus_name("ZWO ASI294MM Pro"), "asi294mm")
        self.assertEqual(equipment.kamera_aus_name("ZWO ASI2600MC Pro"), "asi2600mc")
        self.assertEqual(equipment.kamera_aus_name("ZWO ASI2600MM Pro"), "asi2600mm")

    def test_mehrdeutig_gibt_None(self):
        """Der eigentliche Punkt. "ASI294" passt auf MC UND MM — dann lieber nichts."""
        self.assertIsNone(equipment.kamera_aus_name("ASI294"))

    def test_unbekannt_und_leer_geben_None(self):
        for n in ("Canon EOS 6D", "", None, "   ", "Kamera"):
            self.assertIsNone(equipment.kamera_aus_name(n), "%r wurde erkannt" % (n,))

    def test_seestar(self):
        self.assertEqual(equipment.kamera_aus_name("Seestar S30"), "seestar_s30_cam")

    def test_jeder_schluessel_findet_sich_selbst(self):
        """Wer in KAMERAS steht, muss auch ueber seine eigene Bezeichnung auffindbar sein —
        sonst waere ein Eintrag tot, ohne dass es jemand merkt."""
        for schluessel, bezeichnung, _px in equipment.KAMERAS:
            if schluessel == "manuell":
                continue
            self.assertEqual(equipment.kamera_aus_name(bezeichnung.split("(")[0].strip()),
                             schluessel, "%s findet sich nicht selbst" % bezeichnung)


class TestBerichtNutztDieErkennung(unittest.TestCase):

    def _bild(self):
        rng = np.random.default_rng(1)
        return np.clip(rng.normal(0.02, 0.002, (60, 80, 3)), 0, 1).astype(np.float32)

    def test_ohne_pfad_bleibt_die_kamera_leer(self):
        b = messbericht.erstellen(self._bild(), log=lambda *a, **k: None)
        self.assertIsNone(b["ausruestung"]["kamera_schluessel"])
        self.assertIsNone(b["ausruestung"]["kamera_herkunft"])

    def test_vorgegebene_kamera_wird_nicht_ueberschrieben(self):
        b = messbericht.erstellen(self._bild(), kamera="asi294mc", log=lambda *a, **k: None)
        self.assertEqual(b["ausruestung"]["kamera_schluessel"], "asi294mc")
        self.assertEqual(b["ausruestung"]["kamera_herkunft"], "vorgegeben")

    def test_herkunft_steht_im_bericht(self):
        """Woher der Schluessel stammt, gehoert in den Bericht: eine Erkennung ist etwas
        anderes als eine Angabe des Benutzers, und der Leser muss das unterscheiden koennen."""
        import shutil
        import tempfile
        from astropy.io import fits
        d = tempfile.mkdtemp(prefix="fp_kam_")
        try:
            p = os.path.join(d, "a.fit")
            fits.writeto(p, np.full((60, 80), 0.02, np.float32),
                         fits.Header({"INSTRUME": "ZWO ASI294MC Pro", "EXPTIME": 300.0,
                                      "XPIXSZ": 4.63, "FOCALLEN": 1151.0}))
            b = messbericht.erstellen(self._bild(), pfad=p, log=lambda *a, **k: None)
            self.assertEqual(b["ausruestung"]["kamera_schluessel"], "asi294mc")
            self.assertEqual(b["ausruestung"]["kamera_herkunft"], "aus dem Header erkannt")
            self.assertIn(b["farbe"]["passt"], (True, False),
                          "mit erkannter Kamera muss ein Farburteil moeglich sein")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
