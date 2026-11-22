#!/usr/bin/env python3
"""
N.I.N.A.-Brücke über die Advanced API — gegen einen nachgebauten Server.

Die Antwortform (Hülle mit Response/Error/Success) ist am 22.11.2026 gegen ein laufendes
N.I.N.A. 3.2.0.9001 mit Advanced API 2.2.15.2 abgefragt worden; die Testaufnahme mit der
N.I.N.A.-Simulatorkamera lief dort echt (640×480-PNG). Nicht live geprüft ist das Abholen
von Rohdaten aus dem Bildverlauf: dafür braucht es einen Ablaufplan, der Bilder speichert.
Darum prüft dieser Test, dass ein falsches Format LAUT scheitert und nie als .fits landet.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))

import nina  # noqa: E402

FITS = b"SIMPLE  =                    T" + b" " * 50


def _huelle(antwort, ok=True, fehler=""):
    return json.dumps({"Response": antwort, "Error": fehler, "StatusCode": 200 if ok else 400,
                       "Success": ok, "Type": "API"}).encode()


class _Handler(BaseHTTPRequestHandler):
    bilder = [{"ImageType": "LIGHT", "Filter": "L", "ExposureTime": 60}]
    bild_daten = FITS

    def log_message(self, *a):
        pass

    def do_GET(self):
        pfad = urlparse(self.path).path.replace("/v2/api/", "")
        art, daten = "application/json", None
        if pfad == "version":
            daten = _huelle("2.2.15.2")
        elif pfad == "version/nina":
            daten = _huelle("3.2.0.9001")
        elif pfad == "equipment/info":
            daten = _huelle({"Camera": {"Connected": True, "DisplayName": "Sim"},
                             "Mount": {"Connected": False}})
        elif pfad == "equipment/camera/rescan":
            daten = _huelle([{"Id": "No_Device", "Name": "No camera"},
                             {"Id": "SIM", "Name": "Sim", "DisplayName": "Sim"}])
        elif pfad == "equipment/mount/connect":
            daten = _huelle(None, ok=False, fehler="Mount not available")
        elif pfad == "image-history":
            daten = _huelle(self.bilder)
        elif pfad.startswith("image/"):
            art, daten = "application/octet-stream", self.bild_daten
        elif pfad == "sequence/state":
            daten = _huelle([{"GlobalTriggers": []},
                             {"Name": "Targets_Container", "Status": "RUNNING", "Items": [1, 2]}])
        if daten is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", art)
        self.end_headers()
        self.wfile.write(daten)


class TestNina(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.n = nina.Nina("127.0.0.1", cls.server.server_address[1], timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.d = tempfile.mkdtemp()
        _Handler.bild_daten = FITS

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_version(self):
        self.assertEqual(self.n.version(), {"api": "2.2.15.2", "nina": "3.2.0.9001"})

    def test_geraete_ohne_name_ist_none(self):
        g = self.n.geraete()
        self.assertTrue(g["Camera"]["verbunden"])
        self.assertFalse(g["Mount"]["verbunden"])
        self.assertIsNone(g["Mount"]["name"], "fehlender Name ist None, nicht ''")

    def test_suche_ohne_platzhalter(self):
        self.assertEqual(self.n.geraete_suchen("Camera"), [{"id": "SIM", "name": "Sim"}])

    def test_abgelehnt_mit_fehlertext(self):
        with self.assertRaises(nina.NinaFehler) as e:
            self.n.verbinden("Mount")
        self.assertIn("Mount not available", str(e.exception))

    def test_bilder_holen_einmal(self):
        neu = self.n.neue_bilder_holen(self.d)
        self.assertEqual(len(neu), 1)
        self.assertTrue(os.path.basename(neu[0]).startswith("nina_00000_LIGHT_L_60"))
        with open(neu[0], "rb") as fh:
            self.assertTrue(fh.read().startswith(b"SIMPLE"))
        self.assertEqual(self.n.neue_bilder_holen(self.d), [], "zweites Holen lädt nichts doppelt")
        self.assertFalse([f for f in os.listdir(self.d) if f.endswith(".teil")])

    def test_kein_fits_scheitert_laut(self):
        """Gegenprobe: ein PNG darf nie als .fits im Live-Ordner landen."""
        _Handler.bild_daten = b"\x89PNG\r\n\x1a\n" + b"x" * 40
        with self.assertRaises(nina.NinaFehler):
            self.n.neue_bilder_holen(self.d)
        self.assertEqual([f for f in os.listdir(self.d) if f.endswith(".fits")], [])

    def test_sequenz_zusammenfassung(self):
        text = nina.sequenz_zusammenfassung(self.n.sequenz_status())
        self.assertIn("Targets: RUNNING (2 Schritte)", text)

    def test_nicht_erreichbar_sagt_was_zu_tun_ist(self):
        tot = nina.Nina("127.0.0.1", 1, timeout=1)
        with self.assertRaises(nina.NinaFehler) as e:
            tot.version()
        self.assertIn("Advanced API", str(e.exception))

    def test_unbekanntes_geraet(self):
        with self.assertRaises(ValueError):
            self.n.trennen("Toaster")


if __name__ == "__main__":
    unittest.main()
