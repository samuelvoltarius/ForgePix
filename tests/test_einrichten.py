#!/usr/bin/env python3
"""
Die Ersteinrichtung (einrichten.py) und die Start-Skripte.

Anlass: ForgePix lief auf einem anderen Rechner nicht. run.sh zeigte fest auf
`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` — das gibt es nur auf
einem bestimmten Mac —, und run.bat installierte nie ein Paket. Dieser Test hält fest, dass
kein Start-Skript wieder einen festen Python-Pfad bekommt und dass die Einrichtung erkennt,
wenn requirements.txt sich geändert hat.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

import einrichten  # noqa: E402


class TestEinrichten(unittest.TestCase):
    def test_versionen(self):
        self.assertFalse(einrichten.version_pruefen((3, 9))[0])
        self.assertTrue(einrichten.version_pruefen((3, 12))[0])
        ok, text = einrichten.version_pruefen((3, 15))
        self.assertTrue(ok)
        self.assertIn("neuer als getestet", text)

    def test_requirements_folgen_r(self):
        pakete = einrichten.pakete_aus("requirements.txt")
        namen = " ".join(pakete)
        for p in ("PySide6", "numpy", "astropy", "astroquery"):
            self.assertIn(p, namen)
        self.assertFalse([p for p in pakete if p.startswith(("-r", "#"))])

    def test_pflichtmodule_stehen_in_den_requirements(self):
        namen = " ".join(einrichten.pakete_aus("requirements.txt")).lower()
        for paket in einrichten.PFLICHT.values():
            self.assertIn(paket.lower(), namen)

    def test_marke_erkennt_geaenderte_requirements(self):
        d = tempfile.mkdtemp()
        try:
            python = einrichten.venv_python(d)
            os.makedirs(os.path.dirname(python))
            open(python, "w").close()
            self.assertFalse(einrichten.ist_eingerichtet(d), "ohne Marke nicht eingerichtet")
            with open(os.path.join(d, einrichten.MARKE), "w") as fh:
                fh.write(einrichten.anforderungen_hash())
            self.assertTrue(einrichten.ist_eingerichtet(d))
            with open(os.path.join(d, einrichten.MARKE), "w") as fh:
                fh.write("alt")
            self.assertFalse(einrichten.ist_eingerichtet(d), "geänderte requirements -> neu einrichten")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_kein_fester_python_pfad_in_startskripten(self):
        for datei in ("run.sh", "run.bat", os.path.join("ForgePix.app", "Contents", "MacOS", "ForgePix")):
            with open(os.path.join(ROOT, datei), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("Versions/3.13/bin/python3", text, datei)
            self.assertNotRegex(text, r"(?m)^exec\s+\"?/Library/Frameworks", datei)
            if datei != "run.bat":
                self.assertIn("run.sh" if datei.endswith("ForgePix") else "einrichten.py", text, datei)

    def test_run_bat_richtet_ein(self):
        with open(os.path.join(ROOT, "run.bat"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("einrichten.py", text)
        self.assertIn(".venv\\Scripts\\python.exe", text)


if __name__ == "__main__":
    unittest.main()
