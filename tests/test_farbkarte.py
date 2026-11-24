"""Farbkarte: Farbabstand messen, Karte finden, Farbprofil rechnen (core/farbkarte.py).

Gemessen am 24.11.2026 an einer Fuji-X-T4-Aufnahme mit ColorChecker Classic (raw.pixls.us,
CC0): ΔE 2000 nach Weißabgleich über Grau — Kamera-JPEG 7,9, ForgePix neutral 3,5; mit
Farbprofil 2,4 (eins ausgelassen 2,7). Die Karte findet ForgePix selbst; Abweichung zu den von
Hand gesetzten Feldmitten höchstens 6,8 px.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HIER, ".."), os.path.join(HIER, "..", "core")]

import farbkarte as FK  # noqa: E402

STICH = np.array([[1.10, 0.05, -0.02], [0.03, 0.92, 0.04], [-0.04, 0.08, 0.80]])   # linear, RGB


def _karte(drehung=1, stich=True, seed=3):
    """Karte aus den Sollwerten zeichnen (Standardlage 6x4, dann gedreht), auf Laubtextur."""
    rng = np.random.default_rng(seed)
    lin = FK.soll_srgb_linear()
    if stich:
        lin = np.clip(lin @ STICH.T, 0, 1)
    rgb = FK.linear_srgb(lin)
    f, rand = 60, 14
    karte = np.full((4 * f + 5 * rand, 6 * f + 7 * rand, 3), 0.08)
    for k in range(24):
        r, c = divmod(k, 6)
        y0 = rand + r * (f + rand); x0 = rand + c * (f + rand)
        karte[y0:y0 + f, x0:x0 + f] = rgb[k][::-1]                # BGR
    karte = np.rot90(karte, drehung)
    H, W = 700, 900
    bild = cv2.GaussianBlur(rng.random((H, W, 3)).astype(np.float32), (0, 0), 3) * 0.5
    bild[:, :, 1] += 0.15
    y, x = 120, 260
    bild[y:y + karte.shape[0], x:x + karte.shape[1]] = karte
    return (np.clip(bild, 0, 1) * 255 + 0.5).astype(np.uint8)


class TestDeltaE2000(unittest.TestCase):
    def test_paare_aus_sharma_2005(self):
        for a, b, soll in (((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
                           ((50, 0, 0), (50, -1, 2), 2.3669),
                           ((50, 2.5, 0), (73, 25, -18), 27.1492),
                           ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644)):
            self.assertAlmostEqual(float(FK.delta_e2000(np.array(a), np.array(b))), soll, places=4)

    def test_sollwerte_ergeben_null(self):
        """Feld 18 (Cyan) liegt außerhalb von sRGB (Rot linear −0,044) und kann in einem
        sRGB-Bild nicht exakt erscheinen: dort bleibt ΔE 3,37. Alle anderen Felder: 0."""
        rgb = np.clip(FK.linear_srgb(FK.soll_srgb_linear()), 0, 1)
        de = FK.bewerten(rgb, belichtung_angleichen=False)["je_feld"]
        self.assertLess(float(np.delete(de, 17).max()), 0.01)
        self.assertAlmostEqual(float(de[17]), 3.37, delta=0.05)


class TestKarteFinden(unittest.TestCase):
    def test_findet_in_jeder_lage(self):
        for drehung in (0, 1, 2, 3):
            bild = _karte(drehung)
            m, h = FK.finden(bild)
            rgb = FK.felder_messen(bild, m, h)
            # die richtige Lage: ohne Stich gemessen wäre es ~0; mit Stich hier deutlich > 0,
            # aber nach Profil wieder klein — falsche Lage gäbe beides groß
            M = FK.kalibrierung_berechnen(rgb)
            nach = FK.bewerten(FK.linear_srgb(np.clip(FK.srgb_linear(rgb) @ M.T, 0, 1)),
                               belichtung_angleichen=False)
            self.assertLess(nach["mittel"], 1.5, (drehung, nach["mittel"]))

    def test_ohne_karte_klare_meldung(self):
        rng = np.random.default_rng(0)
        bild = (cv2.GaussianBlur(rng.random((500, 700, 3)).astype(np.float32), (0, 0), 3) * 255).astype(np.uint8)
        with self.assertRaises(ValueError):
            FK.finden(bild)


class TestProfil(unittest.TestCase):
    def test_stich_wird_weggerechnet(self):
        bild = _karte()
        p = FK.profil_erstellen(bild)
        self.assertGreater(p["delta_e"]["vorher"], 3.0)
        self.assertLess(p["delta_e"]["nachher"], 1.0)
        self.assertLess(p["delta_e"]["eins_ausgelassen"], 1.5)
        korrigiert = FK.kalibrierung_anwenden(bild, np.asarray(p["matrix"]))
        m, h = FK.finden(korrigiert)
        self.assertLess(FK.bewerten(FK.felder_messen(korrigiert, m, h), belichtung_angleichen=False)["mittel"], 1.0)

    def test_einheitsmatrix_aendert_nichts(self):
        bild = _karte()
        self.assertLessEqual(int(np.abs(FK.kalibrierung_anwenden(bild, np.eye(3)).astype(int) - bild).max()), 1)

    def test_falsches_format_wird_abgelehnt(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"format": "etwas/1", "matrix": np.eye(3).tolist()}, f)
            with self.assertRaises(ValueError):
                FK.profil_laden(p)

    def test_kommandozeile_erstellt_profil(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "karte.png")
            cv2.imwrite(p, _karte())
            lauf = subprocess.run([sys.executable, os.path.join(HIER, "..", "core", "focus_cull_stack.py"),
                                   "--farbprofil-erstellen", p], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
            self.assertEqual(lauf.returncode, 0, lauf.stderr[-500:])
            self.assertIn("FARBPROFIL:", lauf.stdout)
            M = FK.profil_laden(os.path.join(d, "karte.farbprofil.json"))
        self.assertEqual(M.shape, (3, 3))


class TestOberflaeche(unittest.TestCase):
    def test_profil_geht_an_die_pipeline(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from ui.main_window import MainWindow
        w = MainWindow()
        w.raw_dev.setChecked(True)
        w.raw_farbprofil.setText(os.path.join(HIER, "p.farbprofil.json"))
        with contextlib.redirect_stdout(io.StringIO()):
            a = w._build_args(False)
        self.assertIn("--raw-farbprofil", a)
        w.close()


if __name__ == "__main__":
    unittest.main()
