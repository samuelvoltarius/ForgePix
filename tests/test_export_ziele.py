#!/usr/bin/env python3
"""
ForgePix — die Export-Ziele und der Astro-Modus.

    python3 tests/test_export_ziele.py

`--export instagram,whatsapp,web,4k,print` und `--web-jpg` wurden im **Astro-Modus** — dem
Hauptmodus des Programms — vollständig ignoriert. Die Optionen standen in der Hilfe, wurden
angenommen und taten nichts; es kam nicht einmal eine Meldung. `run_lucky` und `run_hdr` riefen
`export_web_jpg` auf, aber nicht `export_targets`.

Dazu die zweite Hälfte: exportiert werden darf nur das **fertige** Bild. Im Astro-Ergebnisordner
liegen daneben die linearen Zwischenstände (16- und 32-bit-TIFF) und die Abdeckungsmaske. Ein
Instagram-JPG davon ist praktisch schwarz und sieht aus wie ein misslungener Export.
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import focus_cull_stack as F  # noqa: E402
from constants import imwrite  # noqa: E402


class TestExportZiele(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_exp_")
        self.stack = os.path.join(self.d, "stack")
        self.aus = os.path.join(self.d, "export")
        os.makedirs(self.stack)
        rng = np.random.default_rng(3)
        hell = np.clip(rng.normal(0.45, 0.1, (200, 300, 3)), 0, 1).astype(np.float32)
        dunkel = (hell * 0.004).astype(np.float32)          # so sieht ein lineares Bild aus
        imwrite(os.path.join(self.stack, "x_astro.jpg"),
                np.clip(hell * 255, 0, 255).astype(np.uint8))
        imwrite(os.path.join(self.stack, "x_astro_linear.tif"),
                np.clip(dunkel * 65535, 0, 65535).astype(np.uint16))
        imwrite(os.path.join(self.stack, "coverage.tif"),
                np.full((200, 300), 255, np.uint8))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_only_nimmt_nur_die_eine_datei(self):
        # So ruft die Pipeline auf: argparse zerlegt --export schon in eine Liste.
        F.export_targets(self.stack, self.aus, ["instagram", "web"], only="x_astro.jpg")
        namen = sorted(os.listdir(self.aus))
        self.assertTrue(namen)
        self.assertTrue(all(n.startswith("x_astro_") or n == "x_astro.jpg" for n in namen),
                        namen)
        self.assertFalse([n for n in namen if "linear" in n or "coverage" in n],
                         "aus einem linearen Zwischenstand wurde exportiert: %s" % namen)

    def test_eine_zeichenkette_wird_auch_verstanden(self):
        """Wird versehentlich "instagram,web" statt einer Liste uebergeben, iterierte die
        Schleife ueber BUCHSTABEN, faende kein bekanntes Ziel und schriebe wortlos nichts."""
        F.export_targets(self.stack, self.aus, "instagram,web", only="x_astro.jpg")
        self.assertTrue(os.listdir(self.aus), "eine Zeichenkette ergab ein stilles Nichts")

    def test_web_jpg_nimmt_nur_die_eine_datei(self):
        F.export_web_jpg(self.stack, self.aus, only="x_astro.jpg")
        self.assertEqual(sorted(os.listdir(self.aus)), ["x_astro.jpg"])

    def test_ohne_only_kommt_alles(self):
        """Die Gegenprobe — sonst waere nicht zu unterscheiden, ob `only` wirkt oder ob
        ueberhaupt nichts exportiert wird."""
        F.export_web_jpg(self.stack, self.aus)
        self.assertGreater(len(os.listdir(self.aus)), 1)

    def test_exportiertes_bild_ist_nicht_schwarz(self):
        """Der eigentliche Punkt: ein Export aus dem linearen Zwischenstand waere praktisch
        schwarz und saehe aus wie ein misslungener Export."""
        import cv2
        F.export_targets(self.stack, self.aus, ["instagram"], only="x_astro.jpg")
        gefunden = [n for n in os.listdir(self.aus) if n.endswith(".jpg")]
        self.assertTrue(gefunden)
        p = os.path.join(self.aus, gefunden[0])
        bild = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_UNCHANGED)
        self.assertGreater(float(bild.mean()), 20.0,
                           "das Exportbild ist fast schwarz (Mittel %.1f)" % bild.mean())


class TestAlleModiExportieren(unittest.TestCase):
    """Jede Betriebsart, die ein Ergebnis schreibt, muss die Export-Optionen auch bedienen."""

    def _quelle(self, name):
        import ast
        import io
        pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core",
                            "focus_cull_stack.py")
        src = io.open(pfad, encoding="utf-8").read()
        baum = ast.parse(src)
        for n in ast.walk(baum):
            if isinstance(n, ast.FunctionDef) and n.name == name:
                return "\n".join(src.split("\n")[n.lineno - 1:n.end_lineno])
        raise AssertionError("Funktion %s nicht gefunden" % name)

    def test_jede_betriebsart_ruft_beide_exporte(self):
        """run_astro rief KEINEN von beiden, run_lucky und run_hdr nur export_web_jpg."""
        fehlend = []
        for name in ("run_astro", "run_own_engine", "run_longexp", "run_mosaic",
                     "run_lucky", "run_hdr"):
            q = self._quelle(name)
            if "export_targets(" not in q:
                fehlend.append("%s: --export" % name)
            if "export_web_jpg(" not in q:
                fehlend.append("%s: --web-jpg" % name)
        self.assertEqual(fehlend, [], "Optionen werden stillschweigend ignoriert: %s" % fehlend)

    def test_astro_exportiert_nur_das_fertige_bild(self):
        q = self._quelle("run_astro")
        self.assertIn("only=", q,
                      "im Astro-Ordner liegen lineare Zwischenstaende — ohne `only` werden "
                      "auch die exportiert")


if __name__ == "__main__":
    unittest.main(verbosity=2)
