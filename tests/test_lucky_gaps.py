#!/usr/bin/env python3
"""
test_lucky_gaps.py — Tests für die geschlossenen Lucky-Imaging-Lücken in core/lucky.py:

  L1  Drizzle/Super-Resolution  (lucky_stack_map(drizzle=...))
  L2  Iterative Referenz        (lucky_stack(ref_topn=...), lucky_stack_map(refine_passes=...))
  L4  Adaptive AP-Größe/-Dichte (lucky_stack_map(adaptive_ap=True))

Erzeugt ein kleines synthetisches Seeing-Video (procedurale Scheibe mit „Kratern" + lokale Warps
+ variabler Blur + Rauschen) per cv2.VideoWriter in einem Temp-Ordner. Klein gehalten (200 px,
40 Frames) für schnelle Tests.

Aufruf:  python3 tests/test_lucky_gaps.py
"""
import os
import sys
import tempfile
import shutil
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
# auch lauffähig, wenn aus dem tests/-Ordner gestartet
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import lucky  # noqa: E402


SIZE = 200
N_FRAMES = 40


def _base_disk(size=SIZE):
    """Helle Scheibe auf dunklem Grund mit ein paar dunklen „Kratern" als feste Struktur."""
    img = np.full((size, size), 12.0, np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    cx = cy = size / 2.0
    r = size * 0.36
    disk = ((xx - cx) ** 2 + (yy - cy) ** 2) <= r ** 2
    img[disk] = 200.0
    # leichter Helligkeitsverlauf
    img[disk] -= 0.12 * ((xx - cx)[disk])
    # Krater (dunkle Flecken) als wiedererkennbare lokale Struktur
    rng = np.random.default_rng(7)
    for _ in range(14):
        ang = rng.uniform(0, 2 * np.pi)
        rad = rng.uniform(0, r * 0.8)
        kx = cx + rad * np.cos(ang)
        ky = cy + rad * np.sin(ang)
        kr = rng.uniform(4, 9)
        spot = ((xx - kx) ** 2 + (yy - ky) ** 2) <= kr ** 2
        img[spot] *= rng.uniform(0.45, 0.7)
    return np.clip(img, 0, 255)


def _warp_local(img, strength, seed):
    """Lokale, ortsabhängige Verzeichnung (simuliert Seeing-Wellen)."""
    rng = np.random.default_rng(seed)
    size = img.shape[0]
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    fx = strength * np.sin(2 * np.pi * (yy / size) * rng.uniform(1.5, 3.0) + rng.uniform(0, 6))
    fy = strength * np.cos(2 * np.pi * (xx / size) * rng.uniform(1.5, 3.0) + rng.uniform(0, 6))
    mapx = (xx + fx).astype(np.float32)
    mapy = (yy + fy).astype(np.float32)
    return cv2.remap(img, mapx, mapy, interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


def make_seeing_video(path, n=N_FRAMES, size=SIZE):
    """Schreibt ein synthetisches Seeing-Video. Globaler Sub-Pixel-Jitter (für Drizzle nötig)
    + lokale Warps + variabler Blur + Rauschen. Einige wenige Frames sind „lucky" (kaum Blur)."""
    base = _base_disk(size)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(path, fourcc, 25.0, (size, size), isColor=True)
    if not vw.isOpened():
        raise RuntimeError("VideoWriter konnte nicht geöffnet werden (mp4v fehlt?)")
    rng = np.random.default_rng(123)
    for k in range(n):
        img = base.copy()
        # globaler Sub-Pixel-Jitter (statisches Stativ mit Restzittern → Drizzle-Voraussetzung)
        jx = rng.uniform(-2.5, 2.5)
        jy = rng.uniform(-2.5, 2.5)
        M = np.float32([[1, 0, jx], [0, 1, jy]])
        img = cv2.warpAffine(img, M, (size, size), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
        # lokale Seeing-Warps
        img = _warp_local(img, strength=rng.uniform(0.6, 2.2), seed=1000 + k)
        # variabler Blur — jedes 7. Frame ist „lucky" (scharf)
        sigma = 0.4 if (k % 7 == 0) else rng.uniform(1.2, 2.8)
        img = cv2.GaussianBlur(img, (0, 0), sigma)
        # Rauschen
        img = img + rng.normal(0, 4.0, img.shape).astype(np.float32)
        img8 = np.clip(img, 0, 255).astype(np.uint8)
        vw.write(cv2.cvtColor(img8, cv2.COLOR_GRAY2BGR))
    vw.release()
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise RuntimeError("Seeing-Video wurde nicht geschrieben")


def _silent(*a, **k):
    pass


class LuckyGapsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lucky_gaps_")
        cls.video = os.path.join(cls.tmp, "seeing.mp4")
        make_seeing_video(cls.video)
        # Sanity: Video ist lesbar
        cap = cv2.VideoCapture(cls.video)
        ok = cap.isOpened()
        cap.release()
        assert ok, "Test-Video nicht lesbar"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- L1 Drizzle -------------------------------------------------------
    def test_drizzle_enlarges_output(self):
        """Drizzle 1.5 muss eine um Faktor 1.5 größere, valide Ausgabe liefern."""
        base = lucky.lucky_stack_map(self.video, max_load=40, ap_step=40,
                                     sharpen=0.0, log=_silent)
        bh, bw = base.shape[:2]
        for dz in (1.5, 3.0):
            out = lucky.lucky_stack_map(self.video, max_load=40, ap_step=40,
                                        sharpen=0.0, drizzle=dz, log=_silent)
            oh, ow = out.shape[:2]
            self.assertAlmostEqual(oh / bh, dz, delta=0.06,
                                   msg=f"Drizzle {dz}: Höhe nicht skaliert ({oh} vs {bh})")
            self.assertAlmostEqual(ow / bw, dz, delta=0.06,
                                   msg=f"Drizzle {dz}: Breite nicht skaliert ({ow} vs {bw})")
            self.assertEqual(out.dtype, np.uint8)
            self.assertTrue(np.isfinite(out).all())
            # keine kompletten Löcher (Inpaint/Mittelbild-Fallback füllt)
            self.assertGreater(float(out.std()), 5.0, "Drizzle-Ausgabe wirkt leer/flach")

    def test_drizzle_not_worse(self):
        """Drizzle darf die Schärfe nicht VERSCHLECHTERN: auf gleiche Größe gebracht muss die
        Detail-/Kontrast-Energie (Laplace-Varianz) mindestens vergleichbar bleiben."""
        base = lucky.lucky_stack_map(self.video, max_load=40, ap_step=40,
                                     sharpen=0.0, log=_silent)
        dz = lucky.lucky_stack_map(self.video, max_load=40, ap_step=40,
                                   sharpen=0.0, drizzle=2.0, log=_silent)
        # Drizzle auf Eingaberaster zurückbringen, dann Schärfe vergleichen
        dz_small = cv2.resize(dz, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)

        def sharp(im):
            g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
            return float(cv2.Laplacian(g, cv2.CV_64F).var())

        self.assertGreaterEqual(sharp(dz_small), 0.55 * sharp(base),
                                "Drizzle-Ergebnis deutlich unschärfer als Basis")

    # ---- L2 Iterative Referenz -------------------------------------------
    def test_ref_topn_runs_and_valid(self):
        """lucky_stack mit ref_topn>1 (Mittel der Top-N) läuft und liefert valides Bild."""
        out1 = lucky.lucky_stack(self.video, keep_pct=0.4, max_frames=200,
                                 sharpen_amount=0, ref_topn=1, log=_silent)
        out8 = lucky.lucky_stack(self.video, keep_pct=0.4, max_frames=200,
                                 sharpen_amount=0, ref_topn=8, log=_silent)
        for o in (out1, out8):
            self.assertEqual(o.dtype, np.uint8)
            self.assertEqual(o.shape, (SIZE, SIZE, 3))
            self.assertTrue(np.isfinite(o).all())
            self.assertGreater(float(o.std()), 5.0)

    def test_refine_pass_runs_and_valid(self):
        """lucky_stack_map mit refine_passes=1 (2. Pass mit geschärftem Template) läuft + valide."""
        out = lucky.lucky_stack_map(self.video, max_load=40, ap_step=40,
                                    refine_passes=1, log=_silent)
        self.assertEqual(out.dtype, np.uint8)
        self.assertEqual(out.shape, (SIZE, SIZE, 3))
        self.assertTrue(np.isfinite(out).all())
        self.assertGreater(float(out.std()), 5.0)

    def test_refine_with_drizzle(self):
        """Kombination Drizzle + Refine-Pass darf nicht crashen und liefert vergrößerte Ausgabe."""
        out = lucky.lucky_stack_map(self.video, max_load=40, ap_step=40,
                                    drizzle=2.0, refine_passes=1, log=_silent)
        self.assertAlmostEqual(out.shape[0] / SIZE, 2.0, delta=0.06)
        self.assertTrue(np.isfinite(out).all())

    # ---- L4 Adaptive AP --------------------------------------------------
    def test_adaptive_ap_runs(self):
        """adaptive_ap=True läuft und liefert ein valides Bild gleicher Größe."""
        out = lucky.lucky_stack_map(self.video, max_load=40, ap_step=50,
                                    adaptive_ap=True, log=_silent)
        self.assertEqual(out.dtype, np.uint8)
        self.assertEqual(out.shape, (SIZE, SIZE, 3))
        self.assertTrue(np.isfinite(out).all())
        self.assertGreater(float(out.std()), 5.0)

    def test_default_behaviour_unchanged(self):
        """Defaults (drizzle=1.0, refine_passes=0, adaptive_ap=False) → unveränderte Größe."""
        out = lucky.lucky_stack_map(self.video, max_load=40, ap_step=40, log=_silent)
        self.assertEqual(out.shape, (SIZE, SIZE, 3))

    def test_all_features_combined(self):
        """Alle drei Lücken gleichzeitig — robuster End-to-End-Lauf."""
        out = lucky.lucky_stack_map(self.video, max_load=40, ap_step=45,
                                    drizzle=1.5, refine_passes=1, adaptive_ap=True,
                                    log=_silent)
        self.assertAlmostEqual(out.shape[0] / SIZE, 1.5, delta=0.06)
        self.assertTrue(np.isfinite(out).all())
        self.assertGreater(float(out.std()), 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
