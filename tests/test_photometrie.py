#!/usr/bin/env python3
"""
ForgePix — Tests für die Messphotometrie (core/photometrie.py).

    python3 tests/test_photometrie.py     # oder: python3 -m unittest discover -s tests

Gegen eine bekannte Wahrheit geprüft: die Serie enthält einen Stern mit einer vorgegebenen
Sinusschwankung (Periode 3 h, Amplitude 0,35 mag), dazu eine gemeinsame Durchsicht-Schwankung,
die ALLE Sterne trifft, und eine wandernde Bildlage.

Gemessen (40 Aufnahmen über 6 Stunden):
    Restabweichung zur Wahrheit  0,058 mag differentiell gegen 0,189 mag ohne Vergleichssterne
    Streuung der Vergleichssterne untereinander 0,041 mag (die ehrliche Untergrenze)
    Periode 2,95 h gegen 3,00 h wahr, Stärke des Maximums 0,96

Der Unterschied 0,058 gegen 0,189 IST der Grund für differentielle Photometrie: die
Durchsicht-Schwankung trifft alle Sterne gleich und fällt heraus.

Eine Falle, die der erste Durchgang aufgedeckt hat: die TIFFs trugen kein `DATE-OBS`, also fiel
die Zeit auf die Änderungszeit der Datei zurück — und weil die Serie in einem Rutsch geschrieben
wurde, hatten alle Aufnahmen dieselbe Sekunde. Die Lichtkurve sah völlig normal aus, die
Periodensuche lieferte 24,00 h statt 3,00 h. Seitdem wird eine tote Zeitachse erkannt, gemeldet
und der AAVSO-Export verweigert.
"""
import math
import os
import sys
import shutil
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import photometrie  # noqa: E402
from constants import imwrite  # noqa: E402


def _stille(*a, **k):
    pass


ZIEL = (100, 100)
VERGLEICH = [(40, 60), (150, 45), (60, 150)]


class TestPhotometrie(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_phot_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _serie(self, n=40, stunden=6.0, periode=3.0, amplitude=0.35, unter="a",
               zeitstempel=True, saettigen=False, seed=2):
        rng = np.random.default_rng(seed)
        d = os.path.join(self.d, unter)
        os.makedirs(d, exist_ok=True)
        h = w = 200
        pfade, wahr = [], []
        for i in range(n):
            t = i * (stunden / n)
            dmag = amplitude * math.sin(2 * math.pi * t / periode)
            f = np.full((h, w), 0.03, np.float32)
            # Durchsicht: trifft ALLE Sterne gleich, muss differentiell herausfallen
            durchsicht = 1.0 + 0.25 * math.sin(t * 1.7) + rng.normal(0, 0.03)
            for (x, y), basis in [(ZIEL, 40.0)] + list(zip(VERGLEICH, (55.0, 38.0, 47.0))):
                amp = basis * durchsicht
                if (x, y) == ZIEL:
                    amp *= 10 ** (-0.4 * dmag)
                if saettigen:
                    amp *= 40.0
                p = np.zeros((h, w), np.float32)
                p[y, x] = 1.0
                f += cv2.GaussianBlur(p, (0, 0), 2.0) * amp * 0.01
            dx, dy = int(round(2.5 * math.sin(t))), int(round(2.0 * math.cos(t)))
            M = np.array([[1, 0, dx], [0, 1, dy]], np.float32)
            f = cv2.warpAffine(f, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
            f = np.clip(f + rng.normal(0, 0.0015, (h, w)).astype(np.float32), 0, 1)
            q = os.path.join(d, "l_%03d.tif" % i)
            imwrite(q, np.clip(np.dstack([f] * 3) * 65535, 0, 65535).astype(np.uint16))
            if zeitstempel:
                ts = 1750000000 + t * 3600
                os.utime(q, (ts, ts))
            pfade.append(q)
            wahr.append(dmag)
        return pfade, np.asarray(wahr)

    def test_differentiell_schlaegt_roh_deutlich(self):
        """Der Kern der Sache: die Durchsicht-Schwankung faellt heraus."""
        pfade, wahr = self._serie()
        k = photometrie.lichtkurve(pfade, ZIEL, VERGLEICH, log=_stille)
        self.assertIsNotNone(k)
        gem = np.asarray([p["delta_mag"] for p in k["punkte"]])
        roh = -2.5 * np.log10(np.asarray([p["fluss"] for p in k["punkte"]]))
        w = wahr[:len(gem)]
        rest_diff = float(np.std((gem - gem.mean()) - (w - w.mean())))
        rest_roh = float(np.std((roh - roh.mean()) - (w - w.mean())))
        self.assertLess(rest_diff, rest_roh * 0.5,
                        "differentiell %.4f gegen roh %.4f mag" % (rest_diff, rest_roh))
        self.assertLess(rest_diff, 0.12, "Restabweichung %.4f mag zu gross" % rest_diff)

    def test_streuung_der_vergleichssterne_wird_gemeldet(self):
        """Die ehrliche Messgenauigkeit: was die Vergleichssterne UNTEREINANDER streuen, ist
        die Untergrenze fuer alles, was am Ziel gemessen wird."""
        pfade, _ = self._serie()
        k = photometrie.lichtkurve(pfade, ZIEL, VERGLEICH, log=_stille)
        self.assertIsNotNone(k["streuung_vergleich"])
        self.assertLess(k["streuung_vergleich"], 0.2)

    def test_periode_wird_getroffen(self):
        pfade, _ = self._serie(periode=3.0)
        k = photometrie.lichtkurve(pfade, ZIEL, VERGLEICH, log=_stille)
        per = photometrie.periode_schaetzen(k["punkte"])
        self.assertIsNotNone(per)
        self.assertGreater(per["staerke"], 0.5, "kein klares Maximum")
        self.assertLess(abs(per["periode_stunden"] - 3.0), 0.5,
                        "Periode %.2f h statt 3,00 h" % per["periode_stunden"])

    def test_tote_zeitachse_wird_erkannt(self):
        """Ohne DATE-OBS und mit gleicher Schreibzeit ist die Zeitachse unbrauchbar. Das sah
        im ersten Durchgang voellig normal aus und lieferte 24,00 h statt 3,00 h."""
        pfade, _ = self._serie(n=12, unter="ohnezeit", zeitstempel=False)
        for p in pfade:
            os.utime(p, (1750000000, 1750000000))       # alle exakt gleich
        k = photometrie.lichtkurve(pfade, ZIEL, VERGLEICH, log=_stille)
        self.assertFalse(k["zeit_brauchbar"])
        self.assertIsNone(photometrie.periode_schaetzen(k["punkte"]),
                          "Periodensuche haette eine Zahl geliefert, die wie ein Ergebnis aussieht")
        datei = os.path.join(self.d, "aavso_tot.txt")
        self.assertFalse(photometrie.aavso_export(k, datei, "X", log=_stille))
        self.assertFalse(os.path.exists(datei), "Meldedatei trotz toter Zeitachse geschrieben")

    def test_ausgefressener_stern_wird_erkannt(self):
        """Ein ausgefressener Stern liefert einen systematisch ZU KLEINEN Fluss — und zwar
        still, weil oben einfach Werte fehlen. Er muss darum als solcher gemeldet werden."""
        h = w = 120
        f = np.full((h, w), 0.02, np.float32)
        p = np.zeros((h, w), np.float32)
        cv2.circle(p, (60, 60), 3, 1.0, -1)
        f = np.clip(f + cv2.GaussianBlur(p, (0, 0), 2.0) * 60.0, 0, 1)     # laeuft in die Saettigung
        satt = photometrie.fluss_messen(f, 60, 60)
        self.assertTrue(satt["gesaettigt"], "Saettigung nicht erkannt")
        g = np.full((h, w), 0.02, np.float32)
        g = np.clip(g + cv2.GaussianBlur(p, (0, 0), 2.0) * 0.5, 0, 1)      # schwach, sauber
        self.assertLess(float(g.max()), 0.99, "Gegenprobe laeuft selbst in die Saettigung")
        self.assertFalse(photometrie.fluss_messen(g, 60, 60)["gesaettigt"])

    def test_ausgefressene_messungen_werden_nicht_gemeldet(self):
        """Sie sind als Messpunkt schlicht falsch — also raus aus der Meldedatei."""
        pfade, _ = self._serie(n=10, unter="satt")
        k = photometrie.lichtkurve(pfade, ZIEL, VERGLEICH, log=_stille)
        for q in k["punkte"]:
            q["gesaettigt"] = True
        datei = os.path.join(self.d, "aavso_satt.txt")
        self.assertFalse(photometrie.aavso_export(k, datei, "X", log=_stille))
        self.assertFalse(os.path.exists(datei))

    def test_aavso_kennzeichnet_instrumentelle_werte(self):
        """Instrumentelle Werte ohne Kennzeichnung in eine Datenbank zu geben waere der
        schlimmste denkbare Fehler dieses Moduls."""
        pfade, _ = self._serie(n=12, unter="aav")
        k = photometrie.lichtkurve(pfade, ZIEL, VERGLEICH, log=_stille)
        datei = os.path.join(self.d, "aavso.txt")
        self.assertTrue(photometrie.aavso_export(k, datei, "TESTSTERN",
                                                 beobachter="XYZ", log=_stille))
        text = open(datei, encoding="utf-8").read()
        self.assertIn("#TYPE=EXTENDED", text)
        self.assertIn("#OBSCODE=XYZ", text)
        self.assertIn("INSTRUMENTELLE", text)
        for zeile in [z for z in text.splitlines() if not z.startswith("#")][1:]:
            self.assertIn("instrumentell", zeile)

    def test_katalogbezug_macht_echte_helligkeiten(self):
        pfade, _ = self._serie(n=12, unter="kat")
        k = photometrie.lichtkurve(pfade, ZIEL, VERGLEICH, katalog_helligkeit=9.5, log=_stille)
        self.assertFalse(k["instrumentell"])
        werte = [p["mag"] for p in k["punkte"]]
        # Ziel ist schwaecher als die SUMME der drei Vergleichssterne, delta liegt also bei
        # etwa +1,2 mag: mit einer Vergleichssumme von 9,5 mag kommt das Ziel um 10,7 heraus.
        self.assertTrue(all(9.5 < m < 12.0 for m in werte),
                        "Helligkeiten liegen nicht um den Katalogwert: %.2f..%.2f"
                        % (min(werte), max(werte)))

    def test_position_wird_nachgefuehrt(self):
        """Das Feld wandert. Wer starr misst, misst nach einer Stunde den Himmel daneben."""
        pfade, _ = self._serie(n=12, unter="wander")
        k = photometrie.lichtkurve(pfade, ZIEL, VERGLEICH, log=_stille)
        xs = [p["x"] for p in k["punkte"]]
        self.assertGreater(max(xs) - min(xs), 1.0, "Nachfuehrung hat gar nicht gegriffen")
        self.assertLess(max(xs) - min(xs), 12.0, "Nachfuehrung ist weggelaufen")

    def test_fehlende_angaben(self):
        self.assertIsNone(photometrie.lichtkurve([], ZIEL, VERGLEICH, log=_stille))
        pfade, _ = self._serie(n=6, unter="leer")
        self.assertIsNone(photometrie.lichtkurve(pfade, ZIEL, [], log=_stille))
        self.assertIsNone(photometrie.instrumentelle_helligkeit(0.0))
        self.assertIsNone(photometrie.instrumentelle_helligkeit(-5.0))
        self.assertFalse(photometrie.aavso_export(None, os.path.join(self.d, "x.txt"),
                                                  "X", log=_stille))

    def test_julianisches_datum(self):
        """1970-01-01 00:00 UTC = JD 2440587,5 — der Bezugspunkt muss stimmen, sonst ist jede
        Meldung um Tage daneben."""
        from datetime import datetime, timezone
        jd = photometrie.julianisches_datum(datetime(1970, 1, 1, tzinfo=timezone.utc))
        self.assertAlmostEqual(jd, 2440587.5, places=6)
        self.assertIsNone(photometrie.julianisches_datum(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
