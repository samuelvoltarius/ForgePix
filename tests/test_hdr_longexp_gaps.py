#!/usr/bin/env python3
"""Tests für die neuen HDR/Langzeit-Algorithmus-Lücken (H1 Punkt-Stern-Stacking mit Feldrotation,
H2 lokales Durand-Tonemapping, H3 Gradient/Flow-Deghosting, H4 Sky-Maske mit räumlichem Constraint).
Eigenständig lauffähig: python3 tests/test_hdr_longexp_gaps.py"""
import os
import sys
import tempfile
import shutil
import unittest

import numpy as np
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))


def _rng():
    return np.random.RandomState(7)


class TestHDRLongexpGaps(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    # --- H2: lokales Tonemapping (Durand): globale Dynamik komprimieren, FEINES Detail erhalten ---
    def test_tonemap_local_komprimiert_aber_haelt_detail(self):
        import hdr
        r = _rng()
        H, W = 120, 160
        # HDR-artig: Helligkeits-Rampe dunkel→hell + feine Textur überall
        ramp = np.linspace(10, 245, W)[None, :].repeat(H, 0).astype(np.float32)
        tex = (r.rand(H, W) - 0.5) * 30
        g = np.clip(ramp + tex, 0, 255).astype(np.uint8)
        img = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        out = hdr.tonemap_local(img, strength=1.0)
        self.assertEqual(out.shape, img.shape)
        self.assertEqual(out.dtype, np.uint8)
        go = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32)

        def base_range(x):                                 # globale Dynamik (große Skala)
            b = cv2.GaussianBlur(x.astype(np.float32), (0, 0), 20)
            return float(b.max() - b.min())

        def fine(x):                                       # feines Detail (kleine Skala)
            return float((x.astype(np.float32) - cv2.GaussianBlur(x.astype(np.float32), (0, 0), 2)).std())
        self.assertLess(base_range(go), base_range(g) * 0.98)      # globale Dynamik komprimiert
        self.assertGreater(fine(go), fine(g) * 0.5)               # feines Detail erhalten

    # --- H3: Deghosting (Gradient/adaptiv + Flow-Pfad) ---
    def test_merge_exposures_flow_deghost(self):
        import hdr
        r = _rng()
        base = (r.rand(90, 110, 3) * 180 + 30).astype(np.uint8)
        imgs = [np.clip(base * f, 0, 255).astype(np.uint8) for f in (0.4, 1.0, 1.9)]
        out = hdr.merge_exposures(imgs, align=False, deghost="auto", flow=True, log=lambda *a: None)
        self.assertEqual(out.shape[:2], base.shape[:2])
        self.assertEqual(out.dtype, np.uint8)

    # --- H1: Punkt-Stern-Stacking mit Feldrotation ---
    def test_stack_stars_point_mittelt_und_richtet_aus(self):
        import longexp
        r = _rng()
        H, W = 140, 180
        fg = np.zeros((H, W, 3), np.float32)
        for _ in range(40):
            cv2.circle(fg, (r.randint(0, W), r.randint(int(H * 0.6), H)), 2, (0.2, 0.25, 0.2), -1)
        stars = [(r.randint(10, W - 10), r.randint(10, int(H * 0.5))) for _ in range(45)]
        paths = []
        for i in range(8):
            f = fg.copy()
            for (x, y) in stars:                            # leichte Rotation um die Bildmitte (Feldrotation)
                M = cv2.getRotationMatrix2D((W / 2, H / 2), i * 0.4, 1.0)
                p = (M @ np.array([x, y, 1.0]))
                cv2.circle(f, (int(p[0]), int(p[1])), 1, (0.9, 0.9, 0.95), -1)
            f = np.clip(f + r.normal(0, 0.05, f.shape), 0, 1)   # Rauschen
            pth = os.path.join(self.d, f"n{i:02d}.tif")
            cv2.imwrite(pth, (f * 65535).astype(np.uint16), [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
            paths.append(pth)
        out = longexp.stack_stars_point(paths, work_dir=self.d, align="auto", log=lambda *a: None)
        self.assertEqual(out.shape, (H, W, 3))
        self.assertTrue(0.0 <= float(out.min()) and float(out.max()) <= 1.0)
        # Average-Stacking senkt das Rauschen im (sternfreien) Himmel-Hintergrund
        bg = out[:int(H * 0.4), :, :]
        single = cv2.imread(paths[0], cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0
        self.assertLess(float(bg.std()), float(single[:int(H * 0.4)].std()) + 1e-3)

    # --- H4: Auto-Sky-Maske mit räumlichem Constraint ---
    def test_auto_sky_mask_raeumlich(self):
        import longexp
        r = _rng()
        H, W = 150, 200
        fg = np.zeros((H, W, 3), np.float32)
        for _ in range(60):
            cv2.circle(fg, (r.randint(0, W), r.randint(int(H * 0.6), H)), 2, (0.2, 0.2, 0.2), -1)
        stars = [(r.randint(0, W), r.randint(0, int(H * 0.5))) for _ in range(50)]
        paths = []
        for i in range(10):
            f = fg.copy()
            for (x, y) in stars:
                cv2.circle(f, (min(W - 1, x + i * 2), y), 1, (0.9, 0.9, 0.9), -1)
            f = np.clip(f + r.normal(0, 0.01, f.shape), 0, 1)
            pth = os.path.join(self.d, f"s{i:02d}.tif")
            cv2.imwrite(pth, (f * 65535).astype(np.uint16), [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
            paths.append(pth)
        m = longexp._auto_sky_mask(paths, (H, W), log=lambda *a: None)
        self.assertIsNotNone(m)
        m = m[..., 0]
        self.assertGreater(float(m[int(H * 0.65):].mean()), 0.6)   # Vordergrund eingefroren
        self.assertLess(float(m[:int(H * 0.4)].mean()), 0.6)       # Himmel langzeitbelichtet


if __name__ == "__main__":
    unittest.main(verbosity=2)
