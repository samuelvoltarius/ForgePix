#!/usr/bin/env python3
"""
Arbeitsplatz: Werkzeuge über mehrere Bilder, Kurven, MaskedStretch, externe Programme.

Jedes gegen eine bekannte Wahrheit:
* Kontinuum: Schmalband = Linie + k·Breitband mit k = 0,37 gebaut — die Schätzung muss k treffen
  und die Sterne verschwinden lassen.
* Kanal ersetzen / LRGB / PixelMath: Ergebnis gegen die Formel von Hand.
* Kurven: die Gerade y = x ändert nichts; Werte außerhalb 0…1 bleiben unangetastet.
* MaskedStretch: Hintergrund landet am Ziel, Sterne bleiben kleiner als bei einem gleich
  hellen MTF-Stretch.
* Ein zweites Bild anderer Größe ist ein Fehler, kein stilles Skalieren.
* GraXpert läuft echt, wenn es installiert ist (sonst übersprungen, mit Grund).
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prozesse  # noqa: E402
from test_prozesse import sternfeld  # noqa: E402

STILL = lambda *a, **k: None  # noqa: E731


class TestMehrbild(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _fits(self, name, bild):
        from astropy.io import fits
        pfad = os.path.join(self.d, name)
        daten = np.ascontiguousarray(bild[..., ::-1].transpose(2, 0, 1)) if bild.ndim == 3 else bild
        fits.writeto(pfad, np.asarray(daten, np.float32))
        return pfad

    def test_kontinuum_trifft_k(self):
        breit = sternfeld(seed=3)[..., 2]                          # Sterne + Hintergrund
        h, w = breit.shape
        yy, xx = np.mgrid[:h, :w]
        linie = (0.05 * np.exp(-((xx - 64) ** 2 + (yy - 48) ** 2) / (2 * 15.0 ** 2))).astype(np.float32)
        schmal = linie + 0.37 * (breit - np.median(breit)) + 0.01
        zeilen = []
        r = prozesse.anwenden(np.dstack([schmal] * 3), "kontinuum",
                              {"breitband": self._fits("rot.fits", breit)}, log=zeilen.append)
        k = float(zeilen[0].split("k = ")[1].split()[0])
        self.assertAlmostEqual(k, 0.37, delta=0.02)
        rest = r[..., 0] - np.median(r[..., 0])
        stern = (breit - np.median(breit)) > np.percentile(breit - np.median(breit), 99.5)
        self.assertLess(float(np.abs(rest[stern] - (linie[stern] - np.median(linie))).max()), 0.02,
                        "Sterne müssen bis auf die Linie verschwinden")

    def test_kanal_ersetzen(self):
        bild = sternfeld()
        mono = np.full(bild.shape[:2], 0.5, np.float32)
        r = prozesse.anwenden(bild, "kanal", {"kanal": "Rot", "quelle": self._fits("ha.fits", mono)})
        np.testing.assert_array_equal(r[..., 2], mono)
        np.testing.assert_array_equal(r[..., :2], bild[..., :2])

    def test_lrgb_setzt_helligkeit(self):
        bild = np.clip(sternfeld() + 0.1, 0, 1)
        L = np.full(bild.shape[:2], 0.4, np.float32)
        r = prozesse.anwenden(bild, "lrgb", {"L": self._fits("l.fits", L)})
        np.testing.assert_allclose(r.mean(axis=2), 0.4, atol=1e-5)
        # Farbverhältnisse bleiben
        np.testing.assert_allclose(r[..., 2] / r[..., 0], bild[..., 2] / bild[..., 0], rtol=1e-4)

    def test_pixelmath_mit_zwei_bildern(self):
        a = sternfeld(seed=1); b = sternfeld(seed=2)
        r = prozesse.anwenden(a, "pixelmath", {"formel": "0.25*A + 0.75*B", "B": self._fits("b.fits", b)})
        np.testing.assert_allclose(r, 0.25 * a + 0.75 * b, atol=1e-6)

    def test_falsche_groesse_ist_fehler(self):
        a = sternfeld()
        klein = self._fits("klein.fits", np.zeros((10, 10), np.float32))
        with self.assertRaises(ValueError) as e:
            prozesse.anwenden(a, "kanal", {"kanal": "Rot", "quelle": klein})
        self.assertIn("ausrichten", str(e.exception))

    def test_fehlende_datei_und_pflichtbild(self):
        with self.assertRaises(ValueError):
            prozesse.anwenden(sternfeld(), "lrgb", {"L": os.path.join(self.d, "gibtsnicht.fits")})
        with self.assertRaises(ValueError):
            prozesse.anwenden(sternfeld(), "lrgb")

    def test_kurven_gerade_aendert_nichts(self):
        bild = sternfeld(hintergrund=-0.01)
        r = prozesse.anwenden(bild, "kurven", {"punkte": "0,0; 1,1", "kanal": "RGB"})
        np.testing.assert_allclose(r, bild, atol=1e-6)

    def test_kurven_ausserhalb_unangetastet(self):
        bild = sternfeld(hintergrund=-0.01)
        r = prozesse.anwenden(bild, "kurven", {"punkte": "0,0.2; 1,1", "kanal": "RGB"})
        aussen = bild < 0
        self.assertTrue(aussen.any())
        np.testing.assert_array_equal(r[aussen], bild[aussen])
        innen = (bild > 0) & (bild < 0.01)
        self.assertTrue((r[innen] > 0.19).all(), "innen hebt die Kurve den Schwarzpunkt")

    def test_kurven_punkte_pruefen(self):
        for falsch in ("0,0", "0,0; 0,1", "0,0; 1,1.5", "a,b; 1,1"):
            with self.subTest(falsch), self.assertRaises(ValueError):
                prozesse.kurven_punkte(falsch)

    def test_masked_stretch_ziel_und_kleine_sterne(self):
        bild = sternfeld(hintergrund=0.01)
        r = prozesse.anwenden(bild, "masked_stretch", {"ziel": 0.15, "durchgaenge": 40}, log=STILL)
        self.assertAlmostEqual(float(np.median(r.mean(axis=2))), 0.15, delta=0.01)
        m = prozesse.anwenden(bild, "mtf", {"target_bg": float(np.median(r.mean(axis=2))), "shadow": -6.0})
        # Sternfläche: Pixel über halbem Weg zwischen Hintergrund und Weiß
        def flaeche(x):
            l = x.mean(axis=2)
            return int((l > (np.median(l) + 1.0) / 2).sum())
        self.assertLess(flaeche(r), flaeche(m), "MaskedStretch muss Sterne kleiner halten als MTF")

    def test_extern_nicht_installiert_sagt_es(self):
        p = prozesse.NACH_ID["cosmic"]
        alt = p.extern
        p.extern = lambda: None
        try:
            with self.assertRaises(ValueError) as e:
                prozesse.anwenden(sternfeld(), "cosmic")
            self.assertIn("nicht installiert", str(e.exception))
        finally:
            p.extern = alt

    @unittest.skipUnless(prozesse.NACH_ID["graxpert"].verfuegbar()[0], "GraXpert ist hier nicht installiert")
    def test_graxpert_echt(self):
        bild = sternfeld(h=128, w=128)
        yy, xx = np.mgrid[:128, :128]
        bild = bild + (0.05 * xx / 128.0)[..., None].astype(np.float32)    # Verlauf von links nach rechts
        zeilen = []
        r = prozesse.anwenden(bild, "graxpert", {"art": "Hintergrund"}, log=zeilen.append)
        self.assertEqual(r.shape, bild.shape)
        vorher = float(np.median(bild[:, -16:]) - np.median(bild[:, :16]))
        nachher = float(np.median(r[:, -16:]) - np.median(r[:, :16]))
        self.assertLess(abs(nachher), abs(vorher) / 2, "GraXpert soll den Verlauf deutlich verringern")


if __name__ == "__main__":
    unittest.main()
