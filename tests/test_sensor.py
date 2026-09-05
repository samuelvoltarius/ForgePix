#!/usr/bin/env python3
"""
ForgePix — Tests für die Sensor-/Optikdiagnose (core/sensor.py).

Eigenständig lauffähig:

    python3 tests/test_sensor.py     # oder: python3 -m unittest discover -s tests

Zwei Dinge, die Siril kann (`inspector`/`tilt` und `find_hot`/`cosme`) und die beide OHNE
Kalibrierframes auskommen — entscheidend, weil für viele Kameras schlicht keine passenden
Darks vorliegen.

An echten Daten gegengeprüft (ASI294MC Pro, 750 mm, 63 Subs NGC7380): das Feld war
gleichmäßig (3.38–4.02 px, Urteil „ok"), und aus 20 Lights kamen 2373 dauerhaft defekte
Pixel heraus (0.02 % des Sensors).
"""
import os
import sys
import shutil
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import sensor  # noqa: E402


def _sternfeld(h=300, w=300, fwhm_karte=None, seed=5, n=140):
    """Sternfeld, dessen Sternbreite ortsabhängig ist. `fwhm_karte(x, y) -> sigma`."""
    rng = np.random.default_rng(seed)
    g = np.full((h, w), 0.05, np.float32)
    for _ in range(n):
        x, y = int(rng.integers(12, w - 12)), int(rng.integers(12, h - 12))
        s = 1.0 if fwhm_karte is None else float(fwhm_karte(x / w, y / h))
        punkt = np.zeros((h, w), np.float32)
        cv2.circle(punkt, (x, y), 1, 1.0, -1)
        g += cv2.GaussianBlur(punkt, (0, 0), max(0.6, s)) * float(rng.uniform(0.5, 1.0))
    return np.clip(g, 0, 1)


class TestFeldkarte(unittest.TestCase):
    """Krümmung und Verkippung unterscheiden — die eine ist optisch, die andere mechanisch."""

    def test_gleichmaessiges_feld_ist_ok(self):
        g = _sternfeld()
        kennz, satz = sensor.feld_urteil(sensor.feldkarte(g, 3))
        self.assertIn(kennz, ("ok", "unbekannt"), satz)

    def test_bildfeldkruemmung_wird_erkannt(self):
        """Ecken rundum schlechter als die Mitte = Krümmung, ein Flattener hilft."""
        def karte(x, y):
            r = ((x - 0.5) ** 2 + (y - 0.5) ** 2) ** 0.5
            return 0.9 + 4.0 * r * r
        kennz, satz = sensor.feld_urteil(sensor.feldkarte(_sternfeld(fwhm_karte=karte), 3))
        self.assertEqual(kennz, "kruemmung", satz)
        self.assertIn("Flattener", satz)

    def test_verkippung_wird_als_mechanisch_gemeldet(self):
        """Eine SEITE schlechter als die andere = Sensor/Auszug schief. Das muss deutlich
        gesagt werden, denn keine Software behebt es."""
        def karte(x, y):
            return 0.8 + 4.0 * x           # nur nach rechts schlechter
        kennz, satz = sensor.feld_urteil(sensor.feldkarte(_sternfeld(fwhm_karte=karte), 3))
        self.assertEqual(kennz, "verkippung", satz)
        self.assertIn("mechanisch", satz)

    def test_ohne_sterne_kein_urteil(self):
        leer = np.full((200, 200), 0.05, np.float32)
        kennz, _ = sensor.feld_urteil(sensor.feldkarte(leer, 3))
        self.assertEqual(kennz, "unbekannt")


class TestDefektkarte(unittest.TestCase):
    """Dauerhaft defekte Pixel aus den Aufnahmen — ohne Darks."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_sens_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _serie(self, unterordner, n=10, hot=None, kosmisch_in=None, h=120, w=160):
        """n Aufnahmen mit wanderndem Himmel; `hot` sitzt IMMER an derselben Stelle."""
        d = os.path.join(self.d, unterordner)
        os.makedirs(d, exist_ok=True)
        rng = np.random.default_rng(9)
        sx = rng.integers(15, w - 15, 25); sy = rng.integers(15, h - 15, 25)
        pfade = []
        for i in range(n):
            f = np.full((h, w), 0.06, np.float32)
            dx, dy = int(rng.integers(-4, 5)), int(rng.integers(-4, 5))
            for x, y in zip(sx, sy):
                xi, yi = int(x) + dx, int(y) + dy
                if 3 <= xi < w - 3 and 3 <= yi < h - 3:
                    cv2.circle(f, (xi, yi), 2, 0.7, -1)
            f = cv2.GaussianBlur(f, (0, 0), 1.1) + rng.normal(0, 0.004, (h, w)).astype(np.float32)
            for (x, y) in (hot or []):
                f[y, x] = 0.95                       # ortsfester Defekt
            if kosmisch_in is not None and i == kosmisch_in:
                f[h // 2, w // 2] = 0.99             # EINMALIGER Treffer
            bgr = np.clip(np.dstack([f, f, f]), 0, 1)
            p = os.path.join(d, "l_%02d.tif" % i)
            cv2.imencode(".tif", (bgr * 65535).astype(np.uint16))[1].tofile(p)
            pfade.append(p)
        return pfade

    def test_ortsfeste_defekte_werden_gefunden(self):
        hot = [(20, 30), (100, 80), (140, 15)]
        pfade = self._serie("a", hot=hot)
        maske, n = sensor.defektkarte(pfade, log=lambda *a: None)
        self.assertIsNotNone(maske, "keine Defekte gefunden")
        for x, y in hot:
            self.assertTrue(maske[y, x], "Defekt bei (%d,%d) nicht erkannt" % (x, y))

    def test_einmaliger_kosmischer_treffer_zaehlt_nicht(self):
        """Genau das unterscheidet die Karte von einer Einzelbild-Kosmetik: ein Treffer, der
        nur in EINER Aufnahme steht, ist kein Sensordefekt."""
        pfade = self._serie("b", hot=[(20, 30)], kosmisch_in=4)
        maske, _ = sensor.defektkarte(pfade, log=lambda *a: None)
        self.assertIsNotNone(maske)
        self.assertFalse(maske[60, 80], "einmaliger Treffer wurde als Defekt gezaehlt")

    def test_quelle_darks_lehnt_ohne_darks_ab(self):
        pfade = self._serie("c", hot=[(20, 30)])
        maske, n = sensor.defektkarte(pfade, quelle="darks", log=lambda *a: None)
        self.assertIsNone(maske)
        self.assertEqual(n, 0)

    def test_darks_werden_bevorzugt_wenn_vorhanden(self):
        lights = self._serie("d_l", hot=[(20, 30)])
        darks = self._serie("d_d", hot=[(50, 50)])
        maske, _ = sensor.defektkarte(lights, darks=darks, log=lambda *a: None)
        self.assertIsNotNone(maske)
        self.assertTrue(maske[50, 50], "Defekt aus den DARKS fehlt — wurden sie benutzt?")

    def test_zu_wenige_aufnahmen(self):
        maske, n = sensor.defektkarte([], log=lambda *a: None)
        self.assertIsNone(maske)
        self.assertEqual(n, 0)

    def test_ersetzen_trifft_nur_die_markierten_pixel(self):
        """Echte Sterne muessen unangetastet bleiben — auch kleine, helle."""
        h, w = 60, 80
        f = np.full((h, w, 3), 0.2, np.float32)
        f[10, 10] = 0.9                              # markierter Defekt
        f[40, 60] = 0.9                              # echter Stern, NICHT markiert
        maske = np.zeros((h, w), bool); maske[10, 10] = True
        out = sensor.defekte_ersetzen(f, maske)
        self.assertLess(float(out[10, 10].mean()), 0.5, "Defekt nicht ersetzt")
        self.assertAlmostEqual(float(out[40, 60].mean()), 0.9, places=3,
                               msg="unmarkierter Stern wurde veraendert")

    def test_karte_speichern_und_laden(self):
        maske = np.zeros((40, 50), bool)
        maske[5, 7] = True; maske[30, 44] = True
        p = os.path.join(self.d, "defekte.txt")
        self.assertTrue(sensor.karte_speichern(maske, p))
        zurueck = sensor.karte_laden(p, (40, 50))
        self.assertIsNotNone(zurueck)
        self.assertTrue(zurueck[5, 7] and zurueck[30, 44])
        self.assertEqual(int(zurueck.sum()), 2)

    def test_laden_von_muell_gibt_none(self):
        p = os.path.join(self.d, "murks.txt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("# nur ein Kommentar\nkeine Zahlen\n")
        self.assertIsNone(sensor.karte_laden(p, (10, 10)))
        self.assertIsNone(sensor.karte_laden(os.path.join(self.d, "gibtsnicht.txt"), (10, 10)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
