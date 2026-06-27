#!/usr/bin/env python3
"""Tests für die offenen Astro-Stacking-Lücken in core/astro.py (A3–A6).

Synthetische Sternfelder (mit Rotation/Spiegelung für A3), verrauschter Hintergrund (A4),
verschwommenes Bild (A5) und Sterne+Nebel (A6). Reine OpenCV/NumPy/scipy-Pfade.

Ausführen:  python3 tests/test_astro_gaps.py
"""
import os
import sys
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
# auch wenn aus dem Repo-Root oder aus tests/ gestartet
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import astro  # noqa: E402


def _make_star_field(n_stars=40, size=256, seed=0, fluxes=None):
    """Zufälliges Sternfeld: Punktquellen mit Gauss-Profil. Gibt (bild_gray, sternpositionen)."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size), np.float32)
    pts = rng.uniform(30, size - 30, size=(n_stars, 2)).astype(np.float32)
    for k, (x, y) in enumerate(pts):
        flux = fluxes[k] if fluxes is not None else rng.uniform(0.4, 1.0)
        xi, yi = int(x), int(y)
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                yy, xx = yi + dy, xi + dx
                if 0 <= yy < size and 0 <= xx < size:
                    img[yy, xx] += flux * np.exp(-(dx * dx + dy * dy) / 3.0)
    return np.clip(img, 0, 1), pts


def _to_bgr(g):
    return cv2.cvtColor((np.clip(g, 0, 1)).astype(np.float32), cv2.COLOR_GRAY2BGR)


class TestA3Triangles(unittest.TestCase):
    def test_match_under_rotation(self):
        """Dreiecks-Matching findet Korrespondenzen trotz großer Feldrotation."""
        g, pts = _make_star_field(n_stars=35, seed=1)
        # 35° drehen um die Bildmitte
        ang = np.deg2rad(35.0)
        c = 128.0
        rot = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]], np.float32)
        rpts = (pts - c) @ rot.T + c
        src, dst = astro.match_stars_triangles(pts, rpts)
        self.assertIsNotNone(src, "kein Match unter Rotation")
        self.assertGreaterEqual(len(src), 6)
        # Validieren: geschätzte Affine bildet src→dst klein-residual ab
        M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC)
        self.assertIsNotNone(M)
        self.assertGreaterEqual(int(inl.sum()), 6)

    def test_match_under_mirror(self):
        """Spiegelung (negative Skalierung) bricht das invariante Matching nicht."""
        g, pts = _make_star_field(n_stars=35, seed=2)
        mpts = pts.copy()
        mpts[:, 0] = 256 - mpts[:, 0]            # horizontal spiegeln
        src, dst = astro.match_stars_triangles(pts, mpts)
        self.assertIsNotNone(src, "kein Match unter Spiegelung")
        self.assertGreaterEqual(len(src), 6)

    def test_robust_transform_rotation(self):
        """_estimate_star_transform_robust richtet ein rotiertes Feld aus (translationsfrei)."""
        g, pts = _make_star_field(n_stars=45, seed=3)
        ang = np.deg2rad(25.0)
        c = 128.0
        M_true = cv2.getRotationMatrix2D((c, c), -np.rad2deg(ang), 1.0).astype(np.float32)
        gr = cv2.warpAffine(g, M_true, (256, 256))
        M = astro._estimate_star_transform_robust(g, gr)
        self.assertIsNotNone(M, "robuste Transform lieferte None")
        # gr mit M zurück ausrichten → sollte g ähneln (Sterne überlappen)
        back = cv2.warpAffine(gr, M, (256, 256))
        # Korrelation der hellen Bereiche soll hoch sein
        a, b = g.ravel(), back.ravel()
        corr = float(np.corrcoef(a, b)[0, 1])
        self.assertGreater(corr, 0.5, f"Ausrichtung schlecht (corr={corr:.2f})")


class TestA4Weighting(unittest.TestCase):
    def _write_frames(self, tmp, base, noises, seed=10):
        """Frames = base + gaußsches Rauschen je Frame; manche stark verrauscht (schlechte
        Transparenz simuliert)."""
        rng = np.random.default_rng(seed)
        paths = []
        for i, nz in enumerate(noises):
            f = base + rng.normal(0, nz, base.shape).astype(np.float32)
            f = np.clip(f, 0, 1)
            bgr = _to_bgr(f)
            p = os.path.join(tmp, f"f_{i:03d}.tif")
            cv2.imwrite(p, (bgr * 65535).astype(np.uint16))
            paths.append(p)
        return paths

    def test_weighting_improves_snr(self):
        """Gewichtetes Mittel (1/σ²) hat besseres SNR als ungewichtetes bei gemischter Transparenz."""
        size = 128
        base = np.full((size, size), 0.3, np.float32)
        base[40:88, 40:88] = 0.6                 # konstantes "Nebel"-Signal
        # Mischung: einige sehr saubere, einige sehr verrauschte Frames
        noises = [0.01, 0.01, 0.01, 0.01, 0.20, 0.20, 0.20, 0.20]
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_frames(tmp, base, noises)
            unw = astro.stack(paths, method="average", normalize=False, weight=False, log=lambda *a: None)
            wt = astro.stack(paths, method="average", normalize=False, weight=True, log=lambda *a: None)

        def _bg_noise(img):
            g = astro._gray(img)
            return float(np.std(g[:30, :30]))    # Ecke = Hintergrund

        self.assertLess(_bg_noise(wt), _bg_noise(unw) * 0.95,
                        "Gewichtung senkte das Hintergrundrauschen nicht")
        # Signal (Nebelregion) bleibt erhalten (Helligkeit ~unverändert)
        sig_w = float(astro._gray(wt)[50:78, 50:78].mean())
        self.assertGreater(sig_w, 0.5)

    def test_sigma_iters_default_safe(self):
        """sigma_iters>1 läuft durch und gibt ein plausibles Ergebnis (kein Crash, im Range)."""
        size = 96
        base = np.full((size, size), 0.4, np.float32)
        noises = [0.03] * 6
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_frames(tmp, base, noises, seed=20)
            r1 = astro.stack(paths, method="sigma", sigma_iters=1, normalize=False, log=lambda *a: None)
            r2 = astro.stack(paths, method="sigma", sigma_iters=2, normalize=False, log=lambda *a: None)
        self.assertEqual(r1.shape, r2.shape)
        self.assertTrue(np.all(np.isfinite(r2)))
        self.assertGreater(float(astro._gray(r2).mean()), 0.3)


class TestA5Deconv(unittest.TestCase):
    def test_deconv_sharpens_without_overshoot(self):
        """Regularisierte Deconv schärft eine verschwommene Kante, ohne starkes Overshoot."""
        size = 128
        g = np.zeros((size, size), np.float32)
        g[:, 64:] = 0.7                          # Kante
        # ein paar Sterne, damit estimate_psf eine PSF findet
        _, pts = _make_star_field(n_stars=30, size=size, seed=5)
        for x, y in pts:
            xi, yi = int(x), int(y)
            if 4 < xi < size - 4 and 4 < yi < size - 4:
                g[yi, xi] = 0.9
        blurred = cv2.GaussianBlur(g, (0, 0), 1.6)
        bgr = _to_bgr(blurred)
        out = astro.deconvolve(bgr, iterations=12, regularize=0.1, deringing=True,
                               star_protect=1.0, log=lambda *a: None)
        og = astro._gray(out)
        bg = astro._gray(bgr)
        # Schärfe (Gradientenenergie an der Kante) soll steigen
        gx_out = float(np.abs(np.diff(og[:, 60:70], axis=1)).sum())
        gx_blur = float(np.abs(np.diff(bg[:, 60:70], axis=1)).sum())
        self.assertGreater(gx_out, gx_blur, "Deconv schärfte die Kante nicht")
        # kein massives Overshoot: Wertebereich bleibt im Rahmen
        self.assertLessEqual(float(og.max()), 1.0 + 1e-5)
        self.assertGreaterEqual(float(og.min()), -1e-5)
        # Overshoot direkt an der Kante moderat (nicht > deutlich über Plateau)
        self.assertLess(float(og[:, 70:].max()), 1.0 + 1e-5)

    def test_deconv_tiled_runs(self):
        """tiled_psf-Pfad läuft durch und liefert gültiges Bild."""
        size = 96
        _, pts = _make_star_field(n_stars=40, size=size, seed=6)
        g, _ = _make_star_field(n_stars=40, size=size, seed=6)
        blurred = cv2.GaussianBlur(g, (0, 0), 1.4)
        out = astro.deconvolve(_to_bgr(blurred), iterations=6, tiled_psf=True, tiles=2,
                               star_protect=1.0, log=lambda *a: None)
        self.assertEqual(out.shape, (size, size, 3))
        self.assertTrue(np.all(np.isfinite(out)))


class TestA6StarRemoval(unittest.TestCase):
    def test_removes_star_energy_keeps_nebula(self):
        """Star-Removal senkt die Sternenergie deutlich und erhält den Nebel weitgehend."""
        size = 160
        # ausgedehnter "Nebel": glatter heller Fleck
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        neb = 0.45 * np.exp(-((xx - 80) ** 2 + (yy - 80) ** 2) / (2 * 35.0 ** 2))
        # kleine/mittlere Sterne drauf
        stars, pts = _make_star_field(n_stars=30, size=size, seed=7,
                                      fluxes=np.full(30, 0.9, np.float32))
        scene = np.clip(neb + stars, 0, 1)
        bgr = _to_bgr(scene)

        starless, mask = astro.remove_stars(bgr, log=lambda *a: None)
        self.assertEqual(starless.shape, bgr.shape)
        self.assertIsNotNone(mask)

        # Sternenergie an den Sternorten sinkt deutlich
        sg = astro._gray(scene)
        rg = astro._gray(starless)
        star_before, star_after, cnt = 0.0, 0.0, 0
        for x, y in pts:
            xi, yi = int(x), int(y)
            if 2 <= xi < size - 2 and 2 <= yi < size - 2:
                star_before += float(sg[yi, xi]); star_after += float(rg[yi, xi]); cnt += 1
        self.assertGreater(cnt, 0)
        self.assertLess(star_after, star_before * 0.85,
                        "Sternenergie nicht ausreichend gesenkt")

        # Nebel-Hintergrund (sternfreie Region nahe Zentrum) bleibt weitgehend erhalten
        # eine Region wählen, in der kein Stern liegt
        def _star_near(px, py, rad=6):
            return any(abs(px - x) < rad and abs(py - y) < rad for x, y in pts)
        ref_val, kept_val, k = 0.0, 0.0, 0
        for (px, py) in [(80, 80), (70, 90), (90, 70), (60, 80), (80, 60)]:
            if not _star_near(px, py):
                ref_val += float(sg[py, px]); kept_val += float(rg[py, px]); k += 1
        if k > 0:
            ratio = kept_val / max(ref_val, 1e-6)
            self.assertGreater(ratio, 0.7, f"Nebel zu stark beschädigt (ratio={ratio:.2f})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
