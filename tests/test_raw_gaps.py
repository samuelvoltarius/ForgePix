#!/usr/bin/env python3
"""test_raw_gaps.py — Tests für die neuen RAW-Entwicklungs-Lücken in core/develop.py
(R1 Farb-Management, R2 filmic Tonemapping, R4 Luma/Chroma-Denoise, R5 parametrische Masken).

Lauf:  python3 tests/test_raw_gaps.py
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import develop as D  # noqa: E402


def _bgr_to_hue(bgr):
    """Hue (0..1) aus einem BGR-Float-Bild (zum Prüfen von Farbton-Stabilität)."""
    import cv2
    hsv = cv2.cvtColor(np.clip(bgr, 0, 1).astype(np.float32), cv2.COLOR_BGR2HSV)
    return hsv[..., 0] / 360.0, hsv[..., 1]


class TestColorManagement(unittest.TestCase):
    """R1: camera_to_working → working_to_display Round-Trip."""

    def test_identity_camera_matrix_roundtrip(self):
        # Wenn die Kamera-Matrix == sRGB-XYZ-Matrix ist, ist Kamera-RGB == sRGB-linear.
        # Dann sollte working_to_display(camera_to_working(x)) ≈ Gamma(x) sein.
        cam_xyz = np.linalg.inv(D._RGB2XYZ["srgb"])  # XYZ->Kamera (rawpy-Konvention): Kamera==sRGB
        rng = np.random.default_rng(0)
        lin = rng.uniform(0, 1, size=(8, 8, 3)).astype(np.float64)
        work = D.camera_to_working(lin, cam_xyz, working="rec2020")
        disp = D.working_to_display(work, working="rec2020", gamma="linear")
        # gamma="linear" → disp sollte das ursprüngliche lineare sRGB sein
        self.assertTrue(np.allclose(disp, lin, atol=1e-6),
                        f"max err {np.abs(disp - lin).max()}")

    def test_roundtrip_prophoto_with_bradford(self):
        cam_xyz = np.linalg.inv(D._RGB2XYZ["srgb"])
        rng = np.random.default_rng(1)
        lin = rng.uniform(0.05, 0.95, size=(4, 4, 3)).astype(np.float64)
        work = D.camera_to_working(lin, cam_xyz, working="prophoto")
        disp = D.working_to_display(work, working="prophoto", gamma="linear")
        self.assertTrue(np.allclose(disp, lin, atol=1e-5),
                        f"prophoto roundtrip err {np.abs(disp - lin).max()}")

    def test_rawpy_4x3_matrix_accepted(self):
        cam = np.vstack([np.linalg.inv(D._RGB2XYZ["srgb"]), np.zeros((1, 3))])  # 4x3 wie rawpy
        lin = np.full((2, 2, 3), 0.5)
        work = D.camera_to_working(lin, cam, working="rec2020")
        self.assertEqual(work.shape, (2, 2, 3))

    def test_srgb_gamma_applied(self):
        cam_xyz = np.linalg.inv(D._RGB2XYZ["srgb"])
        lin = np.full((2, 2, 3), 0.5, dtype=np.float64)
        work = D.camera_to_working(lin, cam_xyz, working="srgb")
        disp = D.working_to_display(work, working="srgb", gamma="srgb")
        # sRGB-Gamma von 0.5 linear ≈ 0.735
        self.assertAlmostEqual(float(disp.mean()), 0.7353, places=2)

    def test_unknown_working_raises(self):
        with self.assertRaises(ValueError):
            D.camera_to_working(np.zeros((2, 2, 3)), D._RGB2XYZ["srgb"], working="foo")


class TestFilmicTonemap(unittest.TestCase):
    """R2: komprimiert Lichter (max sinkt), Hue stabil."""

    def test_compresses_highlights(self):
        # szenenbezogenes Bild mit hellem Bereich >1
        img = np.zeros((16, 16, 3), dtype=np.float32)
        img[:, :8] = 0.18                            # Mitte
        img[:, 8:] = 6.0                             # weit über Weiß
        out = D.filmic_tonemap(img, white=8.0)
        self.assertLessEqual(out.max(), 1.0 + 1e-6, "filmic muss auf <=1 mappen")
        self.assertGreater(out.max(), out.min(), "es muss Tonwertspreizung geben")
        # die hellen Pixel dürfen nicht mehr 6.0 sein → komprimiert
        self.assertLess(float(out[:, 8:].max()), 6.0)

    def test_hue_preserved(self):
        rng = np.random.default_rng(2)
        # bunte, szenenbezogene Werte
        img = rng.uniform(0.05, 4.0, size=(32, 32, 3)).astype(np.float32)
        h_in, _ = _bgr_to_hue(np.clip(img / img.max(), 0, 1))
        out = D.filmic_tonemap(img, sat_preserve=1.0)
        h_out, _ = _bgr_to_hue(out)
        # ratio-preserving: Farbton bleibt (zyklische Distanz klein)
        d = np.abs(h_in - h_out)
        d = np.minimum(d, 1.0 - d)
        # nur dort prüfen, wo Sättigung nennenswert ist (graue Pixel haben undef. Hue)
        _, sat = _bgr_to_hue(out)
        mask = sat > 0.05
        self.assertLess(float(d[mask].mean()), 0.02,
                        f"Hue driftet: mean {float(d[mask].mean())}")

    def test_monotonic_luminance(self):
        # höhere Szenen-Luminanz → nie geringere Display-Luminanz
        L = np.linspace(0.001, 10.0, 200)
        img = np.stack([L, L, L], axis=-1)[None].astype(np.float32)
        out = D.filmic_tonemap(img)
        y = 0.0722 * out[..., 0] + 0.7152 * out[..., 1] + 0.2126 * out[..., 2]
        y = y.ravel()
        self.assertTrue(np.all(np.diff(y) >= -1e-6), "Kurve muss monoton sein")

    def test_dtype_preserved_uint16(self):
        img = (np.full((4, 4, 3), 0.5) * 65535).astype(np.uint16)
        out = D.filmic_tonemap(img)
        self.assertEqual(out.dtype, np.uint16)


class TestDenoiseChromaLuma(unittest.TestCase):
    """R4: senkt Rauschen, erhält Kanten/Bit-Tiefe."""

    def _noisy(self, seed=3):
        rng = np.random.default_rng(seed)
        base = np.zeros((64, 64, 3), dtype=np.float32)
        base[:, :32] = 0.3
        base[:, 32:] = 0.7                           # harte Kante in der Mitte
        noisy = np.clip(base + rng.normal(0, 0.05, base.shape), 0, 1)
        return base, noisy.astype(np.float32)

    def test_reduces_noise(self):
        base, noisy = self._noisy()
        out = D.denoise_chroma_luma(noisy, luma=1.5, chroma=2.0)
        err_in = float(np.mean((noisy - base) ** 2))
        err_out = float(np.mean((out.astype(np.float32) - base) ** 2))
        self.assertLess(err_out, err_in, "Denoise muss Rauschen senken")

    def test_preserves_edge(self):
        base, noisy = self._noisy()
        out = D.denoise_chroma_luma(noisy, luma=1.0, chroma=1.0).astype(np.float32)
        # Kantenkontrast (links/rechts-Mittelwert) muss erhalten bleiben
        left = float(out[:, :28].mean())
        right = float(out[:, 36:].mean())
        self.assertGreater(right - left, 0.3, "Kante darf nicht verwaschen")

    def test_preserves_bitdepth_16(self):
        _, noisy = self._noisy()
        u16 = (noisy * 65535).astype(np.uint16)
        out = D.denoise_chroma_luma(u16, luma=1.0, chroma=1.0)
        self.assertEqual(out.dtype, np.uint16)
        # mehr als 256 distinkte Werte → echte 16-bit, kein uint8-Zwang
        self.assertGreater(len(np.unique(out)), 256)

    def test_iso_scales_strength(self):
        base, noisy = self._noisy()
        low = D.denoise_chroma_luma(noisy, luma=1.0, iso=100).astype(np.float32)
        high = D.denoise_chroma_luma(noisy, luma=1.0, iso=6400).astype(np.float32)
        # höheres ISO → stärkerer Threshold → glatter (geringere lokale Varianz)
        var_low = float(np.var(low[:, :28]))
        var_high = float(np.var(high[:, :28]))
        self.assertLessEqual(var_high, var_low + 1e-9)


class TestParametricMask(unittest.TestCase):
    """R5: 0..1-Maske, trifft die richtige Region."""

    def test_luminance_mask_range_and_region(self):
        img = np.zeros((10, 20, 3), dtype=np.float32)
        img[:, :10] = 0.1                            # dunkel links
        img[:, 10:] = 0.9                            # hell rechts
        m = D.parametric_mask(img, by="luminance", lo=0.6, hi=1.0, feather=0.05)
        self.assertGreaterEqual(m.min(), 0.0)
        self.assertLessEqual(m.max(), 1.0)
        self.assertLess(float(m[:, :10].mean()), 0.1, "dunkle Region nicht selektiert")
        self.assertGreater(float(m[:, 10:].mean()), 0.9, "helle Region selektiert")
        self.assertEqual(m.shape, img.shape[:2])

    def test_saturation_mask(self):
        img = np.zeros((8, 16, 3), dtype=np.float32)
        img[:, :8] = (0.5, 0.5, 0.5)                 # grau (sat=0)
        img[:, 8:] = (0.0, 0.0, 1.0)                 # gesättigtes Rot (BGR)
        m = D.parametric_mask(img, by="saturation", lo=0.5, hi=1.0, feather=0.05)
        self.assertLess(float(m[:, :8].mean()), 0.1)
        self.assertGreater(float(m[:, 8:].mean()), 0.9)

    def test_hue_mask_cyclic_red(self):
        img = np.zeros((8, 16, 3), dtype=np.float32)
        img[:, :8] = (1.0, 0.0, 0.0)                 # Blau (BGR) → Hue ~0.667
        img[:, 8:] = (0.0, 0.0, 1.0)                 # Rot (BGR) → Hue ~0.0
        # Bereich um Rot, der über die 1.0-Grenze wrappt (0.95..0.05)
        m = D.parametric_mask(img, by="hue", lo=0.95, hi=0.05, feather=0.02)
        self.assertGreater(float(m[:, 8:].mean()), 0.9, "Rot muss selektiert sein")
        self.assertLess(float(m[:, :8].mean()), 0.1, "Blau nicht selektiert")

    def test_mask_combines_with_geometric(self):
        img = np.full((20, 20, 3), 0.8, dtype=np.float32)
        pm = D.parametric_mask(img, by="luminance", lo=0.5, hi=1.0, feather=0.1)
        rm = D.radial_mask(img.shape, 10, 10, 6, 6, feather=0.3)
        combined = pm * rm                            # andockbar/kombinierbar
        self.assertEqual(combined.shape, (20, 20))
        self.assertGreaterEqual(combined.min(), 0.0)
        self.assertLessEqual(combined.max(), 1.0)

    def test_hue_needs_color(self):
        with self.assertRaises(ValueError):
            D.parametric_mask(np.zeros((4, 4), dtype=np.float32), by="hue")


if __name__ == "__main__":
    unittest.main(verbosity=2)
