#!/usr/bin/env python3
"""
INDI-Anschluss gegen einen nachgebauten indiserver.

Der Nachbau folgt der INDI-Protokollbeschreibung 1.7 und den Eigenschaftsnamen der
Standardtreiber (CONNECTION, CCD_EXPOSURE, CCD1-BLOB, FILTER_SLOT/FILTER_NAME,
EQUATORIAL_EOD_COORD). Ein echter indiserver lief in dieser Sitzung nicht (Windows-Rechner);
bis zu einem Lauf gegen `indiserver indi_simulator_ccd …` gilt der Anschluss als ungeprüft.

Festgehalten sind die Fallen:
* Das Bild kommt in vielen TCP-Stücken — der Leser darf erst am Elementende auswerten.
* INDI zählt Filterfächer ab 1, ForgePix (wie Alpaca) ab 0.
* Ein Gerät, das schneller antwortet als der Client „Busy“ setzt, darf nicht hängen bleiben.
* RA kommt sexagesimal ("20:30:00").
"""
import base64
import io
import os
import re
import shutil
import socketserver
import sys
import tempfile
import threading
import time
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))

import aufnahme  # noqa: E402
import indi  # noqa: E402

BILD = (np.arange(4 * 6, dtype=np.uint16).reshape(4, 6) * 100)


def _fits_bytes():
    from astropy.io import fits
    puffer = io.BytesIO()
    fits.PrimaryHDU(BILD).writeto(puffer)
    return puffer.getvalue()


DEFS = """
<defTextVector device="CCD Simulator" name="DRIVER_INFO" state="Idle" perm="ro">
  <defText name="DRIVER_INTERFACE">6</defText></defTextVector>
<defSwitchVector device="CCD Simulator" name="CONNECTION" state="Idle" perm="rw" rule="OneOfMany">
  <defSwitch name="CONNECT">Off</defSwitch><defSwitch name="DISCONNECT">On</defSwitch></defSwitchVector>
<defNumberVector device="CCD Simulator" name="CCD_EXPOSURE" state="Idle" perm="rw">
  <defNumber name="CCD_EXPOSURE_VALUE">1</defNumber></defNumberVector>
<defNumberVector device="CCD Simulator" name="CCD_INFO" state="Idle" perm="ro">
  <defNumber name="CCD_MAX_X">6</defNumber><defNumber name="CCD_MAX_Y">4</defNumber>
  <defNumber name="CCD_PIXEL_SIZE">3.76</defNumber></defNumberVector>
<defNumberVector device="CCD Simulator" name="CCD_TEMPERATURE" state="Ok" perm="rw">
  <defNumber name="CCD_TEMPERATURE_VALUE">-10</defNumber></defNumberVector>
<defTextVector device="CCD Simulator" name="CCD_CFA" state="Idle" perm="ro">
  <defText name="CFA_TYPE">RGGB</defText></defTextVector>
<defSwitchVector device="CCD Simulator" name="CCD_FRAME_TYPE" state="Idle" perm="rw" rule="OneOfMany">
  <defSwitch name="FRAME_LIGHT">On</defSwitch><defSwitch name="FRAME_BIAS">Off</defSwitch>
  <defSwitch name="FRAME_DARK">Off</defSwitch><defSwitch name="FRAME_FLAT">Off</defSwitch></defSwitchVector>
<defBLOBVector device="CCD Simulator" name="CCD1" state="Idle" perm="ro">
  <defBLOB name="CCD1"/></defBLOBVector>
<defSwitchVector device="CCD Simulator" name="CCD_ABORT_EXPOSURE" state="Idle" perm="rw" rule="AtMostOne">
  <defSwitch name="ABORT">Off</defSwitch></defSwitchVector>
<defSwitchVector device="Filter Simulator" name="CONNECTION" state="Idle" perm="rw" rule="OneOfMany">
  <defSwitch name="CONNECT">Off</defSwitch><defSwitch name="DISCONNECT">On</defSwitch></defSwitchVector>
<defNumberVector device="Filter Simulator" name="FILTER_SLOT" state="Idle" perm="rw">
  <defNumber name="FILTER_SLOT_VALUE">1</defNumber></defNumberVector>
<defTextVector device="Filter Simulator" name="FILTER_NAME" state="Idle" perm="rw">
  <defText name="FILTER_SLOT_NAME_1">L</defText><defText name="FILTER_SLOT_NAME_2">R</defText>
  <defText name="FILTER_SLOT_NAME_10">Ha</defText></defTextVector>
<defSwitchVector device="Telescope Simulator" name="CONNECTION" state="Idle" perm="rw" rule="OneOfMany">
  <defSwitch name="CONNECT">Off</defSwitch><defSwitch name="DISCONNECT">On</defSwitch></defSwitchVector>
<defNumberVector device="Telescope Simulator" name="EQUATORIAL_EOD_COORD" state="Idle" perm="rw">
  <defNumber name="RA">20:30:00</defNumber><defNumber name="DEC">-5:30:00</defNumber></defNumberVector>
"""


class _Handler(socketserver.StreamRequestHandler):
    belichtungen = []

    def schicken(self, text, stueck=None):
        daten = text.encode()
        if stueck is None:
            self.wfile.write(daten)
        else:                                   # in Stücken, wie ein langsames Netz
            for i in range(0, len(daten), stueck):
                self.wfile.write(daten[i:i + stueck]); self.wfile.flush(); time.sleep(0.001)
        self.wfile.flush()

    def handle(self):
        for zeile in self.rfile:
            zeile = zeile.decode().strip()
            if zeile.startswith("<getProperties"):
                self.schicken(DEFS)
            elif 'name="CONNECTION"' in zeile:
                geraet = re.search(r'device="([^"]+)"', zeile).group(1)
                an = '<oneSwitch name="CONNECT">On' in zeile
                self.schicken('<setSwitchVector device="%s" name="CONNECTION" state="Ok">'
                              '<oneSwitch name="CONNECT">%s</oneSwitch><oneSwitch name="DISCONNECT">%s</oneSwitch>'
                              '</setSwitchVector>' % (geraet, "On" if an else "Off", "Off" if an else "On"))
            elif 'name="CCD_FRAME_TYPE"' in zeile:
                self.belichtungen.append(re.search(r'name="(FRAME_\w+)">On', zeile).group(1))
                self.schicken('<setSwitchVector device="CCD Simulator" name="CCD_FRAME_TYPE" state="Ok"/>')
            elif 'name="CCD_EXPOSURE"' in zeile:
                daten = base64.b64encode(_fits_bytes()).decode()
                self.schicken('<setNumberVector device="CCD Simulator" name="CCD_EXPOSURE" state="Busy">'
                              '<oneNumber name="CCD_EXPOSURE_VALUE">0</oneNumber></setNumberVector>'
                              '<setBLOBVector device="CCD Simulator" name="CCD1" state="Ok">'
                              '<oneBLOB name="CCD1" size="%d" format=".fits">%s</oneBLOB></setBLOBVector>'
                              '<setNumberVector device="CCD Simulator" name="CCD_EXPOSURE" state="Ok"/>'
                              % (len(daten), daten), stueck=97)
            elif 'name="FILTER_SLOT"' in zeile:
                wert = re.search(r'>([\d.]+)</oneNumber>', zeile).group(1)
                self.schicken('<setNumberVector device="Filter Simulator" name="FILTER_SLOT" state="Ok">'
                              '<oneNumber name="FILTER_SLOT_VALUE">%s</oneNumber></setNumberVector>' % wert)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TestIndi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tcp = _Server(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.tcp.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.tcp.shutdown()
        cls.tcp.server_close()

    def setUp(self):
        _Handler.belichtungen = []
        self.s = indi.Server("127.0.0.1", self.tcp.server_address[1], timeout=5)
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        self.s.schliessen()
        shutil.rmtree(self.d, ignore_errors=True)

    def test_geraete_mit_typ(self):
        liste = self.s.geraete(warten=0.5)
        paare = {(g["name"], g["typ"]) for g in liste}
        self.assertIn(("CCD Simulator", "camera"), paare)
        self.assertIn(("Filter Simulator", "filterwheel"), paare)
        self.assertIn(("Telescope Simulator", "telescope"), paare)

    def test_kamera_bild_in_stuecken(self):
        k = indi.Kamera(self.s, "CCD Simulator")
        self.assertTrue(k.verbinden(sekunden=5))
        bild = k.belichten(0.0, max_warten=10)
        np.testing.assert_array_equal(bild, BILD)
        self.assertEqual(k.info()["bayer"], "RGGB")
        self.assertEqual(k.temperatur(), -10)

    def test_filter_ab_null_und_sortiert(self):
        f = indi.Filterrad(self.s, "Filter Simulator")
        self.assertEqual(f.namen(), ["L", "R", "Ha"], "Fach 10 gehört ans Ende, nicht hinter Fach 1")
        self.assertEqual(f.wechseln("Ha"), 2)
        self.assertEqual(f.position(), 2)

    def test_ra_sexagesimal(self):
        ra, dec = indi.Montierung(self.s, "Telescope Simulator").position()
        self.assertAlmostEqual(ra, 20.5)
        self.assertAlmostEqual(dec, -5.5)

    def test_ablaufplan_ueber_indi_mit_bildtyp(self):
        from astropy.io import fits
        k = indi.Kamera(self.s, "CCD Simulator"); k.verbinden(sekunden=5)
        plan = [aufnahme.Schritt(1, 0, "Light", "R"), aufnahme.Schritt(1, 0, "Bias")]
        dateien = aufnahme.Lauf(k, plan, self.d, filterrad=indi.Filterrad(self.s, "Filter Simulator"),
                                log=lambda *a: None).ausfuehren()
        self.assertEqual(len(dateien), 2)
        self.assertEqual(_Handler.belichtungen, ["FRAME_LIGHT", "FRAME_BIAS"],
                         "INDI kennt Bias/Flat — der Typ muss beim Treiber ankommen")
        with fits.open(dateien[0]) as h:
            self.assertEqual((h[0].header["FILTER"], h[0].header["BAYERPAT"]), ("R", "RGGB"))

    def test_sofortige_antwort_bleibt_nicht_haengen(self):
        """Über TCP ist der Nachbau nie schneller als der Client — der Wettlauf zeigt sich dort
        nicht (Gegenprobe am 22.11.: Test blieb grün). Darum hier die Antwort im Senden selbst."""
        import xml.etree.ElementTree as ET
        self.s.vektor("CCD Simulator", "CONNECTION")
        echt = self.s._senden

        def senden_und_sofort_antworten(xml):
            if "CONNECTION" not in xml:
                return echt(xml)
            # nicht an den Nachbau senden: sonst rettet dessen spätere Antwort den Fehler
            if "CONNECTION" in xml:
                self.s._verarbeiten(ET.fromstring(
                    '<setSwitchVector device="CCD Simulator" name="CONNECTION" state="Ok">'
                    '<oneSwitch name="CONNECT">On</oneSwitch></setSwitchVector>'))
        self.s._senden = senden_und_sofort_antworten
        self.s.neu("CCD Simulator", "CONNECTION", {"CONNECT": True})
        v = self.s.fertig("CCD Simulator", "CONNECTION", 2, "verbinden")
        self.assertEqual(v.zustand, "Ok")

    def test_nicht_erreichbar(self):
        with self.assertRaises(indi.IndiFehler) as e:
            indi.Server("127.0.0.1", 1, timeout=1).geraete(warten=0.1)
        self.assertIn("indiserver", str(e.exception))

    def test_zahlen(self):
        self.assertAlmostEqual(indi._zahl("-0:30:00"), -0.5)
        self.assertAlmostEqual(indi._zahl("12.25"), 12.25)


if __name__ == "__main__":
    unittest.main()
