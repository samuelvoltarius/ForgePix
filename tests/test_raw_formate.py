#!/usr/bin/env python3
"""
RAW-Formate aller Hersteller: Erkennung und verständliche Fehler.

Am 23.11.2026 an 20 echten Dateien gemessen (18 Hersteller von raw.pixls.us, CC0, plus Sony
A7 V und A7 III): 19 entwickelt, darunter Hasselblad .fff und Phase One .iiq — die aber in
einem Ordner gar nicht als Bilder erkannt wurden, weil ihre Endungen fehlten. GoPro .gpr kann
die eingebaute LibRaw nicht lesen und meldete sich mit „Out of order call of libraw function“.

Die echten Dateien liegen nicht im Repository (testdata/, siehe docs/TESTDATEN.md); dieser Test
prüft mit Platzhalter-Dateien, dass Endungen erkannt werden und Fehler Namen und Ausweg nennen.
Mit vorhandenem testdata/raw läuft zusätzlich der echte Durchgang.
"""
import glob
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))

import constants  # noqa: E402
import focus_cull_stack as F  # noqa: E402

ECHT = os.path.join(ROOT, "testdata", "raw")


class TestRawFormate(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_hersteller_endungen_werden_erkannt(self):
        for endung in (".fff", ".3fr", ".iiq", ".rwl", ".nrw", ".cr3", ".raf", ".orf", ".gpr"):
            open(os.path.join(self.d, "bild" + endung), "wb").close()
        gefunden = {os.path.splitext(p)[1].lower() for p in F.list_images(self.d)}
        self.assertTrue({".fff", ".iiq", ".rwl", ".nrw", ".gpr"} <= gefunden, gefunden)

    def test_kaputte_raw_nennt_datei(self):
        pfad = os.path.join(self.d, "kaputt.nef")
        with open(pfad, "wb") as fh:
            fh.write(b"kein raw" * 100)
        with self.assertRaises(constants.ForgePixFehler) as e:
            F.develop_raw_to_bgr(pfad, half=True)
        self.assertIn("kaputt.nef", str(e.exception))

    def test_gpr_nennt_den_ausweg(self):
        pfad = os.path.join(self.d, "GOPR0001.GPR")
        with open(pfad, "wb") as fh:
            fh.write(b"\x00" * 512)
        with self.assertRaises(constants.ForgePixFehler) as e:
            F.develop_raw_to_bgr(pfad, half=True)
        self.assertIn(constants.GPR_WERKZEUG, str(e.exception))

    @unittest.skipUnless(glob.glob(os.path.join(ECHT, "*", "*.*")), "testdata/raw fehlt (docs/TESTDATEN.md)")
    def test_echte_dateien_aller_hersteller(self):
        dateien = [p for p in glob.glob(os.path.join(ECHT, "*", "*.*"))
                   if os.path.splitext(p)[1].lower() in constants.RAW_EXTS]
        entwickelt, gescheitert = [], []
        for p in dateien:
            try:
                b = F.develop_raw_to_bgr(p, half=True)
                self.assertEqual(b.ndim, 3)
                entwickelt.append(os.path.basename(p))
            except constants.ForgePixFehler as e:
                gescheitert.append(os.path.splitext(p)[1].lower())
                self.assertIn(os.path.basename(p), str(e))
        self.assertGreaterEqual(len(entwickelt), 15)
        self.assertLessEqual(set(gescheitert), {".gpr"}, "nur GoPro darf scheitern")


if __name__ == "__main__":
    unittest.main()
