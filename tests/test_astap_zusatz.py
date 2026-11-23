#!/usr/bin/env python3
"""
ASTAP-Anschluss (blind und mit Hinweis) und die Übersicht der Zusatzprogramme.

ASTAP ist auf dem Testrechner nicht installiert. Der Nachbau hier ist ein kleines Python-Skript,
das die Kommandozeile mitschreibt und — wie ASTAP — die Lösung als `<Bild>.wcs` ablegt. Geprüft
wird also: richtige Argumente (blind = `-fov 0 -r 180`), richtige Ergebnisdatei, klare Fehler.
Ob echtes ASTAP so antwortet, ist damit NICHT bewiesen.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astap  # noqa: E402
import zusatzprogramme  # noqa: E402

NACHBAU = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_ASTAP_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
if os.environ.get("FAKE_ASTAP_FAIL"):
    print("No solution found!"); sys.exit(1)
bild = args[args.index("-f") + 1]
from astropy.io import fits
kopf = fits.Header()
for k, v in json.load(open(os.environ["FAKE_ASTAP_WCS"], encoding="utf-8")).items():
    kopf[k] = v
kopf.tofile(os.path.splitext(bild)[0] + ".wcs", overwrite=True)
print("Solution found")
'''


class TestAstap(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.skript = os.path.join(self.d, "fake_astap.py")
        with open(self.skript, "w", encoding="utf-8") as fh:
            fh.write(NACHBAU)
        self.log = os.path.join(self.d, "aufrufe.jsonl")
        wcs = {"WCSAXES": 2, "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CRVAL1": 83.8, "CRVAL2": -5.39,
               "CRPIX1": 64.5, "CRPIX2": 48.5, "CD1_1": -0.001, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": 0.001}
        self.wcs_json = os.path.join(self.d, "wcs.json")
        with open(self.wcs_json, "w", encoding="utf-8") as fh:
            json.dump(wcs, fh)
        os.environ.update(FAKE_ASTAP_LOG=self.log, FAKE_ASTAP_WCS=self.wcs_json)
        os.environ.pop("FAKE_ASTAP_FAIL", None)
        self.befehl = [sys.executable, self.skript]
        self.bild = np.random.default_rng(0).normal(0.1, 0.01, (96, 128, 3)).astype(np.float32)

    def tearDown(self):
        os.environ.pop("FAKE_ASTAP_FAIL", None)
        shutil.rmtree(self.d, ignore_errors=True)

    def _aufrufe(self):
        with open(self.log, encoding="utf-8") as fh:
            return [json.loads(z) for z in fh]

    def test_blind_ruft_ganzen_himmel(self):
        wcs = astap.loesen(self.bild, befehl=self.befehl, log=lambda *a: None)
        ra, dec = wcs.pixel_to_world_values(63.5, 47.5)
        self.assertAlmostEqual(float(ra), 83.8, places=6)
        self.assertAlmostEqual(float(dec), -5.39, places=6)
        a = self._aufrufe()[0]
        self.assertEqual(a[a.index("-fov") + 1], "0")
        self.assertEqual(a[a.index("-r") + 1], "180")
        self.assertIn("-wcs", a)
        self.assertNotIn("-ra", a)

    def test_mit_hinweis(self):
        astap.loesen(self.bild, {"ra": 83.8, "dec": -5.4, "pixelscale_arcsec": 3.6}, befehl=self.befehl,
                     log=lambda *a: None)
        a = self._aufrufe()[0]
        self.assertAlmostEqual(float(a[a.index("-ra") + 1]), 83.8 / 15, places=5)
        self.assertAlmostEqual(float(a[a.index("-spd") + 1]), 84.6, places=5)
        self.assertAlmostEqual(float(a[a.index("-fov") + 1]), 96 * 3.6 / 3600, places=4)

    def test_ohne_loesung_klarer_fehler(self):
        os.environ["FAKE_ASTAP_FAIL"] = "1"
        with self.assertRaises(astap.AstapFehler) as e:
            astap.loesen(self.bild, befehl=self.befehl, log=lambda *a: None)
        self.assertIn("Sterndatenbank", str(e.exception))

    def test_nicht_installiert_nennt_download(self):
        import photometric
        alt = photometric._find_solver
        photometric._find_solver = lambda: (None, None)
        try:
            with self.assertRaises(astap.AstapFehler) as e:
                astap.loesen(self.bild, log=lambda *a: None)
            self.assertIn(astap.DOWNLOAD, str(e.exception))
        finally:
            photometric._find_solver = alt

    def test_zentrieren_faellt_auf_astap_zurueck(self):
        import zentrieren
        from gaia_lokal import Katalog
        leer = Katalog([83.8], [-5.39], [9.0], [0.7])      # eigener Solver findet damit nichts
        ra, dec, _ = zentrieren.bildmitte(self.bild, leer, 83.8, -5.39, 3.6, log=lambda *a: None,
                                          astap_befehl=self.befehl)
        self.assertAlmostEqual(ra, 83.8, places=4)
        self.assertEqual(len(self._aufrufe()), 1)

    def test_datenbank_empfehlung(self):
        self.assertEqual(astap.datenbank_fuer(1.2)[:2], ["D80", "D50"])     # Seestar
        self.assertEqual(astap.datenbank_fuer(30), ["W08"])
        self.assertEqual(astap.datenbank_fuer(0.1), [])


class TestZusatzprogramme(unittest.TestCase):
    def test_alle_mit_https_link(self):
        stand = zusatzprogramme.stand()
        self.assertGreaterEqual(len(stand), 10)
        for s in stand:
            self.assertTrue(s["url"].startswith("https://"), s["name"])
        self.assertEqual(zusatzprogramme.link("astap"), astap.DOWNLOAD)

    def test_fehlendes_programm_nennt_link_im_arbeitsplatz(self):
        import prozesse
        p = prozesse.NACH_ID["starnet"]
        alt, p.extern = p.extern, (lambda: None)
        try:
            da, hinweis = p.verfuegbar()
            self.assertFalse(da)
            self.assertIn("https://starnetastro.com/", hinweis)
        finally:
            p.extern = alt


class TestZusatzDialog(unittest.TestCase):
    def test_knopf_oeffnet_offizielle_seite(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from ui.zusatzprogramme_dialog import ZusatzprogrammeDialog
        geoeffnet = []
        sys.path.insert(0, ROOT)
        d = ZusatzprogrammeDialog(None, oeffnen=geoeffnet.append)
        try:
            zeile = [i for i, s in enumerate(d.stand) if s["id"] == "astap"][0]
            d.tabelle.cellWidget(zeile, 4).click()
            self.assertEqual(geoeffnet, ["https://www.hnsky.org/astap.htm"])
        finally:
            d.deleteLater(); app.processEvents()


if __name__ == "__main__":
    unittest.main()
