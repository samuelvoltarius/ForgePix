#!/usr/bin/env python3
"""
Eigene Gerätesteuerung über ASCOM Alpaca und der Ablaufplan — gegen ein nachgebautes Gerät.

Der Nachbau folgt der veröffentlichten Alpaca-Beschreibung: GET mit ClientID/
ClientTransactionID in der Adresse, PUT als Formular, Antworthülle mit Value/ErrorNumber,
ImageArray als [x][y]. Die zwei Fallen, die hier festgehalten sind:

* ImageArray ist spaltenweise. Ohne Drehen kämen Bilder um 90° gekippt und gespiegelt an —
  bei quadratischem Sensor ohne jede Fehlermeldung.
* Ein Filter im Plan ohne verbundenes Filterrad muss VOR der ersten Belichtung scheitern,
  nicht stumm ungefiltert aufnehmen.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))

import alpaca  # noqa: E402
import aufnahme  # noqa: E402

BREITE, HOEHE = 6, 4
# Bild mit eindeutigen Werten: Zeile y, Spalte x -> 100*y + x
BILD = np.array([[100 * y + x for x in range(BREITE)] for y in range(HOEHE)])


class _Geraet(BaseHTTPRequestHandler):
    zustand = {}

    def log_message(self, *a):
        pass

    def _antwort(self, wert=None, fehler=0, text=""):
        daten = json.dumps({"Value": wert, "ClientTransactionID": 1, "ServerTransactionID": 1,
                            "ErrorNumber": fehler, "ErrorMessage": text}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(daten)

    def do_GET(self):
        z = self.zustand
        teile = urlparse(self.path).path.strip("/").split("/")
        if teile[:3] == ["management", "v1", "configureddevices"]:
            return self._antwort([{"DeviceName": "Sim-Kamera", "DeviceType": "Camera",
                                   "DeviceNumber": 0, "UniqueID": "k1"}]
                                 + ([{"DeviceName": "Sim-Montierung", "DeviceType": "Telescope",
                                      "DeviceNumber": 0, "UniqueID": "t1"}] if self.zustand.get("mit_montierung") else []))
        typ, methode = teile[2], teile[4]
        werte = {
            ("camera", "connected"): z.get("kamera_an", False), ("camera", "name"): "Sim-Kamera",
            ("camera", "cameraxsize"): BREITE, ("camera", "cameraysize"): HOEHE,
            ("camera", "pixelsizex"): 3.76, ("camera", "sensortype"): 2,
            ("camera", "bayeroffsetx"): 1, ("camera", "bayeroffsety"): 0,
            ("camera", "ccdtemperature"): -10.0, ("camera", "binx"): 1,
            ("camera", "imageready"): z.get("bereit", False),
            ("camera", "imagearray"): BILD.T.tolist(),          # Alpaca: [x][y]
            ("filterwheel", "names"): ["L", "R", "Ha"],
            ("filterwheel", "position"): z.get("filter", 0),
            ("filterwheel", "connected"): True,
            ("telescope", "rightascension"): z.get("ra", 20.5), ("telescope", "declination"): z.get("dec", 40.0),
            ("telescope", "slewing"): False, ("telescope", "tracking"): z.get("tracking", False),
            ("telescope", "connected"): True,
        }
        if (typ, methode) in (("camera", "gain"), ("camera", "offset")):
            return self._antwort(None, alpaca.NICHT_UMGESETZT, "Gain not implemented")
        if (typ, methode) not in werte:
            return self._antwort(None, 0x400, "unbekannt")
        return self._antwort(werte[(typ, methode)])

    def do_PUT(self):
        laenge = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(laenge).decode()).items()}
        teile = urlparse(self.path).path.strip("/").split("/")
        typ, methode = teile[2], teile[4]
        self.zustand.setdefault("puts", []).append((typ, methode, form))
        if "ClientTransactionID" not in form:
            return self._antwort(None, 0x401, "ClientTransactionID fehlt")
        if (typ, methode) == ("camera", "connected"):
            self.zustand["kamera_an"] = form["Connected"] == "True"
        elif (typ, methode) == ("camera", "startexposure"):
            self.zustand["bereit"] = True
        elif (typ, methode) == ("filterwheel", "position"):
            self.zustand["filter"] = int(form["Position"])
        elif (typ, methode) == ("telescope", "slewtocoordinatesasync"):
            self.zustand["ra"], self.zustand["dec"] = float(form["RightAscension"]), float(form["Declination"])
        elif (typ, methode) == ("telescope", "tracking"):
            self.zustand["tracking"] = form["Tracking"] == "True"
        elif (typ, methode) == ("telescope", "park"):
            self.zustand["geparkt"] = True
        return self._antwort()


class TestAlpaca(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Geraet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.alpaca = alpaca.Server("127.0.0.1", cls.server.server_address[1], timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Geraet.zustand = {}
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_geraeteliste(self):
        self.assertEqual(self.alpaca.geraete(),
                         [{"name": "Sim-Kamera", "typ": "camera", "nummer": 0, "id": "k1"}])

    def test_verbinden_per_formular(self):
        kamera = alpaca.Kamera(self.alpaca)
        self.assertTrue(kamera.verbinden())
        typ, methode, form = _Geraet.zustand["puts"][0]
        self.assertEqual(form["Connected"], "True")

    def test_bild_wird_gedreht(self):
        bild = alpaca.Kamera(self.alpaca).belichten(0.0)
        self.assertEqual(bild.shape, (HOEHE, BREITE))
        np.testing.assert_array_equal(bild, BILD)
        self.assertEqual(bild.dtype, np.uint16)

    def test_info_ohne_gain_ist_none(self):
        info = alpaca.Kamera(self.alpaca).info()
        self.assertIsNone(info["gain"], "nicht umgesetzt -> None, keine erfundene 0")
        self.assertEqual(info["bayer"], "GRBG", "Versatz x=1 verschiebt RGGB zu GRBG")

    def test_filter_nach_name(self):
        self.assertEqual(alpaca.Filterrad(self.alpaca).wechseln("Ha"), 2)
        with self.assertRaises(alpaca.AlpacaFehler):
            alpaca.Filterrad(self.alpaca).wechseln("OIII")

    def test_ablaufplan_schreibt_fits_mit_kopf(self):
        from astropy.io import fits
        plan = [aufnahme.Schritt(2, 0.0, "Light", "R"), aufnahme.Schritt(1, 0.0, "Dark")]
        zeilen = []
        lauf = aufnahme.Lauf(alpaca.Kamera(self.alpaca), plan, self.d,
                             filterrad=alpaca.Filterrad(self.alpaca),
                             montierung=alpaca.Montierung(self.alpaca), objekt="M 27",
                             log=zeilen.append)
        dateien = lauf.ausfuehren()
        self.assertEqual(len(dateien), 3)
        self.assertEqual(sum(z.startswith("AUFNAHME:") for z in zeilen), 3)
        with fits.open(dateien[0]) as h:
            k = h[0].header
            np.testing.assert_array_equal(h[0].data, BILD)
            self.assertEqual((k["IMAGETYP"], k["FILTER"], k["BAYERPAT"], k["OBJECT"]),
                             ("Light", "R", "GRBG", "M 27"))
            self.assertAlmostEqual(k["RA"], 20.5 * 15)
            self.assertNotIn("GAIN", k, "unbekannter Gain fehlt, statt 0 zu behaupten")
        with fits.open(dateien[2]) as h:
            self.assertEqual(h[0].header["IMAGETYP"], "Dark")
            self.assertNotIn("RA", h[0].header, "Darks bekommen keine Himmelsposition")
        dark_puts = [f for t, m, f in _Geraet.zustand["puts"] if m == "startexposure"]
        self.assertEqual([f["Light"] for f in dark_puts], ["True", "True", "False"])

    def test_filter_ohne_rad_scheitert_vorher(self):
        lauf = aufnahme.Lauf(alpaca.Kamera(self.alpaca), [aufnahme.Schritt(1, 0, "Light", "R")],
                             self.d, log=lambda *a: None)
        with self.assertRaises(ValueError):
            lauf.ausfuehren()
        self.assertNotIn("puts", _Geraet.zustand, "keine Belichtung gestartet")

    def test_abbruch(self):
        lauf = aufnahme.Lauf(alpaca.Kamera(self.alpaca), [aufnahme.Schritt(5, 0, "Light")],
                             self.d, log=lambda *a: None)
        lauf.abbrechen()
        self.assertEqual(lauf.ausfuehren(), [])

    def test_falsche_schritte(self):
        for args in ((0, 1), (1, -1), (1, 1, "Foto")):
            with self.assertRaises(ValueError):
                aufnahme.Schritt(*args)

    def test_nicht_erreichbar(self):
        with self.assertRaises(alpaca.AlpacaFehler):
            alpaca.Server("127.0.0.1", 1, timeout=1).geraete()


if __name__ == "__main__":
    unittest.main()
