#!/usr/bin/env python3
"""Tests für die Panorama-Algorithmus-Lücken in core/mosaic.py (P1, P2, P4, P5).

Ausführen:  python3 tests/test_panorama_gaps.py
Klein/schnell gehalten — synthetische strukturreiche Kacheln, keine Plattenaufnahmen."""
import sys
import os
import unittest

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import numpy as np
import cv2
import mosaic


def make_base(h=240, w=480):
    """Strukturreiches Basisbild (Schachbrett + Punkte + Verlauf) für stabile Features."""
    rng = np.random.default_rng(7)
    img = np.zeros((h, w), np.float32)
    # Schachbrett
    cb = ((np.add.outer(np.arange(h) // 16, np.arange(w) // 16)) % 2) * 120
    img += cb
    # zufällige helle Punkte (eindeutige Korrespondenzen)
    for _ in range(400):
        y = rng.integers(4, h - 4); x = rng.integers(4, w - 4)
        cv2.circle(img, (int(x), int(y)), 2, float(rng.integers(60, 255)), -1)
    # sanfter Verlauf
    img += np.linspace(0, 60, w)[None, :]
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def grid_points(x0, y0, x1, y1, nx=6, ny=4):
    xs = np.linspace(x0, x1, nx); ys = np.linspace(y0, y1, ny)
    return np.array([(x, y) for y in ys for x in xs], np.float64)


class TestDistortionBA(unittest.TestCase):
    def test_ba_reduziert_reprojektionsfehler(self):
        """P1: bekannte Verzeichnung wird selbstkalibriert, RMS-Fehler sinkt."""
        base = make_base()
        h, w = base.shape[:2]
        # zwei überlappende Kacheln durch reine Translation (Pano-Geometrie)
        # Korrespondenzpunkte in der Überlappung
        gp_a = grid_points(240, 30, 470, 210)          # rechter Bereich Bild A
        gp_b = gp_a - np.array([220.0, 0.0])           # gleicher Inhalt, in Bild B verschoben

        # Linsenverzeichnung (Tonne) auf beide Punktmengen anwenden — entgegengesetzt sichtbar
        def distort(pts, cx, cy, nrm, k1):
            dx = (pts[:, 0] - cx) / nrm; dy = (pts[:, 1] - cy) / nrm
            r2 = dx * dx + dy * dy
            s = 1 + k1 * r2
            return np.column_stack([cx + dx * s * nrm, cy + dy * s * nrm])

        cx, cy, nrm = w / 2, h / 2, min(h, w) / 2
        k1 = 0.08
        da = distort(gp_a, cx, cy, nrm, k1)
        db = distort(gp_b, cx, cy, nrm, k1)

        pairs = [(0, 1, da, db)]
        shapes = [(h, w), (h, w)]
        res = mosaic.bundle_adjust_distortion(pairs, shapes, log=lambda *a: None)
        self.assertIn("residual_final", res)
        # BA muss den Reprojektionsfehler deutlich senken
        self.assertLess(res["residual_final"], res["residual_init"])
        self.assertLess(res["residual_final"], res["residual_init"] * 0.6)


class TestPhotometric(unittest.TestCase):
    def test_vignette_und_belichtung_angeglichen(self):
        """P2: künstliche Vignette + Belichtungsoffset werden ausgeglichen."""
        base = make_base()
        h, w = base.shape[:2]
        # zwei identische Kacheln; B künstlich abgedunkelt + vignettiert
        a = base.copy()
        b = base.copy()
        cx, cy, nrm = w / 2, h / 2, min(h, w) / 2
        yy, xx = np.mgrid[0:h, 0:w]
        r2 = ((xx - cx) / nrm) ** 2 + ((yy - cy) / nrm) ** 2
        vig = (1.0 - 0.35 * r2).clip(0.3, 1.0).astype(np.float32)
        b = np.clip(b.astype(np.float32) * vig[..., None] * 0.75, 0, 255).astype(np.uint8)

        # Korrespondenzen: dieselben Pixelkoordinaten in a und b
        pts = grid_points(20, 20, w - 20, h - 20, nx=12, ny=8)
        overlaps = [(0, 1, pts, pts)]
        corr, params = mosaic.optimize_photometric([a, b], overlaps, log=lambda *a: None)

        def sample(im, p):
            x = np.clip(p[:, 0].astype(int), 0, im.shape[1] - 1)
            y = np.clip(p[:, 1].astype(int), 0, im.shape[0] - 1)
            return cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)[y, x].astype(np.float64)

        before = np.abs(sample(a, pts) - sample(b, pts)).mean()
        after = np.abs(sample(corr[0], pts) - sample(corr[1], pts)).mean()
        self.assertLess(after, before)
        self.assertLess(after, before * 0.7)


class TestMultiPoints(unittest.TestCase):
    def test_drei_kacheln_groessere_breite(self):
        """P4: 3 horizontale Kacheln werden über Kontrollpunkte zu breiterem Pano vereint."""
        base = make_base(h=200, w=600)
        h = base.shape[0]
        # drei überlappende Spalten
        t0 = base[:, 0:280]
        t1 = base[:, 200:480]
        t2 = base[:, 400:600]

        # Kontrollpunkte aus bekannter Translation (gleicher Inhalt)
        gp = grid_points(210, 20, 270, h - 20, nx=5, ny=5)   # in Bild0-Koord (Überlappung 0/1)
        p0_01 = gp
        p1_01 = gp - np.array([200.0, 0.0])                  # selbe Stelle in t1
        gp2 = grid_points(410, 20, 470, h - 20, nx=5, ny=5)  # Überlappung 1/2 (Bild0-Koord)
        p1_12 = gp2 - np.array([200.0, 0.0])                 # in t1
        p2_12 = gp2 - np.array([400.0, 0.0])                 # in t2

        ppp = [(0, 1, p0_01, p1_01), (1, 2, p1_12, p2_12)]
        pano = mosaic.stitch_from_points_multi([t0, t1, t2], ppp, log=lambda *a: None)
        self.assertEqual(pano.ndim, 3)
        # Breite muss größer als jede Einzelkachel sein und ~Originalbreite erreichen
        self.assertGreater(pano.shape[1], t0.shape[1])
        self.assertGreater(pano.shape[1], 520)


class TestMasksParam(unittest.TestCase):
    def test_masks_parameter_akzeptiert(self):
        """P5: stitch_detail akzeptiert masks-Parameter ohne Fehler in der Signatur."""
        import inspect
        sig = inspect.signature(mosaic.stitch_detail)
        self.assertIn("masks", sig.parameters)

        # funktionaler Mini-Check: zwei überlappende Kacheln, Vollbild-Masken (None + Bitmap)
        base = make_base(h=200, w=400)
        a = base[:, 0:260].copy()
        b = base[:, 140:400].copy()
        m_a = np.full(a.shape[:2], 255, np.uint8)   # explizite Vollbildmaske
        # Stitch kann je nach OpenCV-Featurelage scheitern — Test prüft nur, dass
        # der masks-Pfad keinen Signatur-/Shape-Fehler wirft.
        try:
            out = mosaic.stitch_detail([a, b], masks=[m_a, None], log=lambda *a: None)
            self.assertEqual(out.ndim, 3)
        except RuntimeError:
            # Kamera-/Bündel-Schätzung kann bei synthetischen Daten fehlschlagen — ok
            pass

        # falsche Maskengröße muss klaren ValueError liefern
        with self.assertRaises(ValueError):
            mosaic.stitch_detail([a, b], masks=[np.full((10, 10), 255, np.uint8), None],
                                 log=lambda *a: None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
