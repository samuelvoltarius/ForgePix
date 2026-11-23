#!/usr/bin/env python3
"""
Autofokus (HFR-Kurve) und PHD2-Dithern — gegen nachgebaute Geräte mit bekannter Wahrheit.

* Autofokus: eine Kamera, deren Sterne mit |Position − 5230| unscharf werden. Er muss 5230 auf
  einen halben Schritt genau finden — und darf NICHT anfahren, wenn das Minimum außerhalb der
  gefahrenen Spanne liegt (dann zurück an den Start).
* HFR: ein Bild ohne Sterne ist None, kein Platzhalterwert.
* PHD2: Dithern wartet auf SettleDone; Status ≠ 0 ist ein Fehler; Dithern ohne Guiding wird
  abgelehnt; der Ablaufplan dithert alle N Lights, aber nicht nach der letzten Aufnahme.
"""
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))

import aufnahme  # noqa: E402
import autofokus  # noqa: E402
import phd2  # noqa: E402

BESTER = 5230


class FakeFokus:
    def __init__(self, pos=5000):
        self.pos, self.wege = pos, []

    def position(self):
        return self.pos

    def fahren(self, ziel):
        self.wege.append(int(ziel))
        self.pos = int(ziel)
        return self.pos


class FakeKamera:
    """Sternfeld, Unschärfe sigma = 1,2 + |Fokus − BESTER| / 60."""

    def __init__(self, fokus, sterne=40, seed=0):
        self.fokus = fokus
        rng = np.random.default_rng(seed)
        self.orte = rng.uniform(25, 175, (sterne, 2))
        self.hell = rng.uniform(0.2, 0.9, sterne)
        self.rng = rng

    def belichten(self, dauer, **_):
        sigma = 1.2 + abs(self.fokus.pos - BESTER) / 60.0
        yy, xx = np.mgrid[:200, :200]
        b = np.full((200, 200), 0.02, np.float32)
        for (x, y), a in zip(self.orte, self.hell):
            b += (a * 2.0 / sigma ** 2 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))).astype(np.float32)
        return b + self.rng.normal(0, 0.002, b.shape).astype(np.float32)

    def info(self):
        return {"name": "Fake"}

    def temperatur(self):
        return None


class TestAutofokus(unittest.TestCase):
    def test_hfr_ohne_sterne_ist_none(self):
        self.assertIsNone(autofokus.hfr(np.random.default_rng(1).normal(0.1, 0.001, (100, 100))))

    def test_hfr_waechst_mit_unschaerfe(self):
        f = FakeFokus(BESTER)
        k = FakeKamera(f)
        scharf = autofokus.hfr(k.belichten(1))
        f.pos = BESTER + 150
        self.assertGreater(autofokus.hfr(k.belichten(1)), scharf * 1.5)

    def test_findet_den_fokus(self):
        f = FakeFokus(5150)
        ergebnis = autofokus.autofokus(FakeKamera(f), f, schritt=60, punkte=9, log=lambda *a: None)
        self.assertLess(abs(ergebnis["position"] - BESTER), 30)
        self.assertEqual(f.pos, ergebnis["position"])
        # Anlauf von unten: vor der Endposition steht eine kleinere
        self.assertLess(f.wege[-2], f.wege[-1])

    def test_minimum_ausserhalb_faehrt_zurueck(self):
        f = FakeFokus(4300)                         # Fokus liegt weit außerhalb der Spanne
        with self.assertRaises(RuntimeError):
            autofokus.autofokus(FakeKamera(f), f, schritt=50, punkte=7, log=lambda *a: None)
        self.assertEqual(f.pos, 4300, "nach dem Scheitern muss er auf dem Start stehen")


class _Phd2Handler(socketserver.StreamRequestHandler):
    zustand = "Guiding"
    settle_status = 0
    dithers = []

    def schicken(self, obj):
        self.wfile.write((json.dumps(obj) + "\r\n").encode()); self.wfile.flush()

    def handle(self):
        self.schicken({"Event": "Version", "PHDVersion": "2.6.13"})
        self.schicken({"Event": "AppState", "State": self.zustand})
        for zeile in self.rfile:
            n = json.loads(zeile.decode())
            m, i = n["method"], n["id"]
            if m == "get_app_state":
                self.schicken({"jsonrpc": "2.0", "result": self.zustand, "id": i})
            elif m == "dither":
                type(self).dithers.append(n["params"])
                self.schicken({"jsonrpc": "2.0", "result": 0, "id": i})
                self.schicken({"Event": "SettleBegin"})
                fertig = {"Event": "SettleDone", "Status": self.settle_status}
                if self.settle_status:
                    fertig["Error"] = "timed-out waiting for guider to settle"
                self.schicken(fertig)
            elif m == "guide":
                self.schicken({"jsonrpc": "2.0", "result": 0, "id": i})
                self.schicken({"Event": "SettleDone", "Status": 0})
            else:
                self.schicken({"jsonrpc": "2.0", "error": {"code": 1, "message": "unknown method"}, "id": i})


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TestPhd2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tcp = _Server(("127.0.0.1", 0), _Phd2Handler)
        threading.Thread(target=cls.tcp.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.tcp.shutdown(); cls.tcp.server_close()

    def setUp(self):
        _Phd2Handler.zustand, _Phd2Handler.settle_status, _Phd2Handler.dithers = "Guiding", 0, []
        self.p = phd2.Phd2("127.0.0.1", self.tcp.server_address[1], timeout=5)
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        self.p.schliessen()
        shutil.rmtree(self.d, ignore_errors=True)

    def test_dithern_wartet_auf_ruhe(self):
        e = self.p.dithern(betrag=4)
        self.assertEqual(e["Event"], "SettleDone")
        self.assertEqual(_Phd2Handler.dithers[0]["amount"], 4.0)

    def test_unruhe_ist_fehler(self):
        _Phd2Handler.settle_status = 1
        with self.assertRaises(phd2.Phd2Fehler) as e:
            self.p.dithern()
        self.assertIn("timed-out", str(e.exception))

    def test_ohne_guiding_kein_dithern(self):
        _Phd2Handler.zustand = "Stopped"
        with self.assertRaises(phd2.Phd2Fehler):
            self.p.dithern()
        self.assertEqual(_Phd2Handler.dithers, [])

    def test_guiding_starten(self):
        self.assertEqual(self.p.guiding_starten()["Status"], 0)

    def test_unbekannter_befehl(self):
        with self.assertRaises(phd2.Phd2Fehler):
            self.p.aufrufen("gibtsnicht")

    def test_ablaufplan_dithert_alle_zwei_aber_nicht_am_ende(self):
        f = FakeFokus(BESTER)
        lauf = aufnahme.Lauf(FakeKamera(f), [aufnahme.Schritt(5, 0, "Light")], self.d,
                             phd2=self.p, dither_alle=2, log=lambda *a: None)
        self.assertEqual(len(lauf.ausfuehren()), 5)
        self.assertEqual(len(_Phd2Handler.dithers), 2, "nach Light 2 und 4, nicht nach 5")

    def test_dithern_ohne_phd2_abgelehnt(self):
        with self.assertRaises(ValueError):
            aufnahme.Lauf(FakeKamera(FakeFokus()), [aufnahme.Schritt(1, 0)], self.d, dither_alle=3)

    def test_nicht_erreichbar(self):
        with self.assertRaises(phd2.Phd2Fehler) as e:
            phd2.Phd2("127.0.0.1", 1, timeout=1).zustand()
        self.assertIn("Server aktivieren", str(e.exception))


if __name__ == "__main__":
    unittest.main()
