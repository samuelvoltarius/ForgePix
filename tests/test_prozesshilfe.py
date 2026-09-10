"""Warum Tests ihre Unterprozesse ueber `prozesshilfe.lauf` starten.

Der eigentliche Beleg steht im zweiten Test: `capture_output=True` OHNE `stdin=` faellt unter
pytest mit `OSError: [WinError 6]` um, weil pytest `sys.stdin` durch ein Objekt ohne Handle
ersetzt und `capture_output` nur stdout und stderr umleitet. Ausserhalb von pytest laeuft
derselbe Aufruf. Das erklaert auch, warum es „zufaellig" wirkte: es haengt davon ab, welche
Abfangart gerade aktiv ist, also davon, was vorher lief.
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prozesshilfe


class Prozessstart(unittest.TestCase):
    def test_lauf_startet_und_reicht_argumente_durch(self):
        r = prozesshilfe.lauf([sys.executable, "-c", "print('hallo')"],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("hallo", r.stdout)

    def test_der_nackte_aufruf_ist_es_wirklich(self):
        """Die Gegenprobe: OHNE stdin scheitert derselbe Aufruf unter pytest.

        Faellt dieser Test eines Tages nicht mehr um, ist die Ursache verschwunden (andere
        pytest-Fassung, andere Abfangart) — dann darf `prozesshilfe` weg. Bis dahin belegt er,
        dass es die Datei nicht ohne Grund gibt.
        """
        try:
            subprocess.run([sys.executable, "-c", "print(1)"],
                           capture_output=True, text=True, encoding="utf-8")
        except OSError as fehler:
            self.assertIn("6", str(getattr(fehler, "winerror", "") or fehler.errno or ""))
            return
        self.skipTest("Der nackte Aufruf laeuft hier durch — die Ursache ist nicht aktiv.")

    def test_ein_eigenes_stdin_wird_nicht_ueberschrieben(self):
        r = prozesshilfe.lauf([sys.executable, "-c", "import sys; print(sys.stdin.read())"],
                              input="hereingereicht", capture_output=True, text=True,
                              encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("hereingereicht", r.stdout)

    def test_ein_fehlercode_schlaegt_durch(self):
        r = prozesshilfe.lauf([sys.executable, "-c", "raise SystemExit(3)"],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 3)


if __name__ == "__main__":
    unittest.main()
