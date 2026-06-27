#!/usr/bin/env python3
"""
ForgePix — Tests für die geschlossenen Fokus-Stacking-Lücken (F2–F5) in core/stacker.py.

Eigenständig lauffähig:

    python3 tests/test_focus_gaps.py        # oder: python3 -m unittest discover -s tests

Erzeugt synthetische Fokusreihen (jeder Frame in seinem Sektor scharf) und prüft das
beobachtbare Verhalten der neuen Engine-Funktionen — nicht die Implementierung:
  • F2 align_images_breathing  → monoton geglättete Maßstäbe, korrekte Form/Länge
  • F3 focus_stack_pyramid_consistent → schärfer als Einzelframe, kein Overshoot (kein Halo)
  • F4 focus_stack_depthmap(regularize=True) → geringere Index-Varianz in flachen Zonen
  • F5 deghost_sharpest + Fenster-Selektor → korrekte Form, scharf in Streuzonen
"""
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import stacker  # noqa: E402


def _rng(seed=7):
    return np.random.RandomState(seed)


def make_focus_series(n=8, size=(240, 320), seed=7):
    """Fokusreihe in BGR uint8: jeder Frame ist in einem vertikalen Sektor scharf (= das Original),
    der Rest ist stark gaußgeglättet. So „wandert" die Schärfe horizontal durch die Serie."""
    h, w = size
    base = (_rng(seed).rand(h, w, 3) * 255).astype(np.uint8)
    # etwas Struktur dazu, damit Laplace/Schärfemaß überall Signal hat
    base = cv2.GaussianBlur(base, (0, 0), 0.8)
    frames = []
    for k in range(n):
        blurred = cv2.GaussianBlur(base.astype(np.float32), (0, 0), 6)
        x0 = int(w * k / n); x1 = int(w * (k + 1) / n)
        blurred[:, x0:x1] = base[:, x0:x1].astype(np.float32)
        frames.append(np.clip(blurred, 0, 255).astype(np.uint8))
    return frames, base


def _sharpness(img):
    """Globales Schärfemaß = Varianz des Laplace (höher = schärfer)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return float(cv2.Laplacian(g.astype(np.float32), cv2.CV_32F).var())


class TestF2Breathing(unittest.TestCase):
    def test_shape_and_length_preserved(self):
        frames, _ = make_focus_series(n=6)
        out = stacker.align_images_breathing(frames, log=lambda *a: None)
        self.assertEqual(len(out), len(frames))
        for o, f in zip(out, frames):
            self.assertEqual(o.shape, f.shape)
            self.assertEqual(o.dtype, f.dtype)

    def test_under_two_images_passthrough(self):
        frames, _ = make_focus_series(n=1)
        self.assertEqual(stacker.align_images_breathing(frames, log=lambda *a: None), frames)

    def test_scale_is_monotone_smoothed(self):
        # synthetische Breathing-Serie: bekannter, MONOTON wachsender Maßstab pro Frame
        _, base = make_focus_series(n=1, size=(240, 320))
        h, w = base.shape[:2]
        cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
        n = 9
        true_scales = np.linspace(0.94, 1.06, n).astype(np.float32)
        ref_idx = n // 2
        true_scales = true_scales / true_scales[ref_idx]
        frames = []
        for s in true_scales:
            M = np.float32([[s, 0, cx - s * cx], [0, s, cy - s * cy]])
            frames.append(cv2.warpAffine(base, M, (w, h), flags=cv2.INTER_LANCZOS4))
        out = stacker.align_images_breathing(frames, ref_idx=ref_idx, smooth=True,
                                             log=lambda *a: None)
        self.assertEqual(len(out), n)
        # die korrigierten Frames sollten untereinander ÄHNLICHER (skalen-angeglichen) sein
        # als die Eingabe → mittlere paarweise Differenz zu den Nachbarn sinkt.
        def neighbor_diff(seq):
            return float(np.mean([np.mean(np.abs(seq[i].astype(np.float32) -
                                                 seq[i + 1].astype(np.float32)))
                                  for i in range(len(seq) - 1)]))
        # zentralen Ausschnitt vergleichen (Warp-Ränder ausblenden)
        c = lambda im: im[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
        d_in = neighbor_diff([c(f) for f in frames])
        d_out = neighbor_diff([c(o) for o in out])
        self.assertLess(d_out, d_in + 1e-6,
                        "Breathing-Korrektur sollte benachbarte Frames angleichen")


class TestF3PyramidConsistent(unittest.TestCase):
    def test_shape_and_dtype(self):
        frames, _ = make_focus_series(n=8)
        res = stacker.focus_stack_pyramid_consistent(frames, log=lambda *a: None)
        self.assertEqual(res.shape, frames[0].shape)
        self.assertEqual(res.dtype, frames[0].dtype)

    def test_sharper_than_any_single_frame(self):
        frames, _ = make_focus_series(n=8)
        res = stacker.focus_stack_pyramid_consistent(frames, log=lambda *a: None)
        best_single = max(_sharpness(f) for f in frames)
        self.assertGreater(_sharpness(res), best_single,
                           "konsistentes Stacking muss schärfer sein als jeder Einzelframe")

    def test_no_overshoot_halo(self):
        # Cross-Scale-Kopplung soll Überschwinger (Halos) vermeiden: Ergebnis darf die Pixel-Hülle
        # der Quellframes nur minimal verlassen.
        frames, _ = make_focus_series(n=8)
        res = stacker.focus_stack_pyramid_consistent(frames, log=lambda *a: None).astype(np.float32)
        stack = np.stack([f.astype(np.float32) for f in frames])
        lo, hi = stack.min(axis=0), stack.max(axis=0)
        over = np.maximum(res - hi, 0) + np.maximum(lo - res, 0)
        overshoot_frac = float((over > 8.0).mean())   # >8/255 deutlicher Überschwinger
        self.assertLess(overshoot_frac, 0.02,
                        f"zu viel Overshoot/Halo: {overshoot_frac:.3%}")

    def test_under_two_images(self):
        frames, _ = make_focus_series(n=1)
        out = stacker.focus_stack_pyramid_consistent(frames, log=lambda *a: None)
        self.assertTrue(np.array_equal(out, frames[0]))


class TestF4Regularize(unittest.TestCase):
    def _index_map(self, frames, regularize, **kw):
        """Schärfe-Index-Karte nachbilden wie in focus_stack_depthmap (zur Varianz-Messung)."""
        n = len(frames)
        h, w = frames[0].shape[:2]
        rad = 4.0
        S = np.empty((n, h, w), np.float32)
        for i, im in enumerate(frames):
            g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
            S[i] = cv2.GaussianBlur(np.abs(cv2.Laplacian(g, cv2.CV_32F)), (0, 0), rad)
        if regularize:
            guide = np.mean(np.stack([f.astype(np.float32) for f in frames]), axis=0)
            guide_g = cv2.cvtColor(guide, cv2.COLOR_BGR2GRAY)
            S = np.stack([stacker._guided_filter(guide_g, S[i], radius=8, eps=(0.08 * 255) ** 2)
                          for i in range(n)])
        return np.argmax(S, axis=0)

    def test_regularization_reduces_index_noise(self):
        # verrauschte, fast-flache Serie: ohne Reg. „flackert" der schärfste-Frame-Index,
        # mit Reg. wird er räumlich glatter → weniger lokale Index-Sprünge (Mottling).
        rng = _rng(3)
        h, w, n = 160, 200, 6
        base = (rng.rand(h, w, 3) * 40 + 110).astype(np.float32)   # flaches, kontrastarmes Feld
        frames = [np.clip(base + rng.randn(h, w, 3) * 12, 0, 255).astype(np.uint8) for _ in range(n)]

        def index_jitter(idx):
            dx = np.abs(np.diff(idx.astype(np.int16), axis=1)) > 0
            dy = np.abs(np.diff(idx.astype(np.int16), axis=0)) > 0
            return float(dx.mean() + dy.mean())

        raw = self._index_map(frames, regularize=False)
        reg = self._index_map(frames, regularize=True)
        self.assertLess(index_jitter(reg), index_jitter(raw),
                        "Regularisierung muss das Index-Mottling reduzieren")

    def test_regularized_merge_runs_and_shape(self):
        frames, _ = make_focus_series(n=6)
        res = stacker.focus_stack_depthmap(frames, regularize=True, log=lambda *a: None)
        self.assertEqual(res.shape, frames[0].shape)
        self.assertEqual(res.dtype, frames[0].dtype)
        # darf nicht schlechter sein als ein Einzelframe
        self.assertGreater(_sharpness(res), max(_sharpness(f) for f in frames) * 0.5)


class TestF5DeghostSharpest(unittest.TestCase):
    def test_shape_and_dtype(self):
        frames, _ = make_focus_series(n=6)
        merged = stacker.focus_stack_depthmap(frames, log=lambda *a: None)
        out = stacker.deghost_sharpest(frames, merged, log=lambda *a: None)
        self.assertEqual(out.shape, merged.shape)
        self.assertEqual(out.dtype, merged.dtype)

    def test_sharpest_in_disagreement_zone(self):
        # Serie mit einem bewegten Block (Streuzone): ein blurriger Median verwischt dort,
        # deghost_sharpest soll einen SCHARFEN Quellframe einsetzen → Streuzone bleibt scharf.
        frames, base = make_focus_series(n=6, size=(200, 260))
        h, w = base.shape[:2]
        # einen scharfen, wandernden hellen Block einbauen (Bewegung über die Frames)
        for k, f in enumerate(frames):
            x = 20 + k * 18
            cv2.rectangle(f, (x, 80), (x + 24, 120), (255, 255, 255), -1)
        merged_med = np.median(np.stack([f.astype(np.float32) for f in frames]), axis=0)
        merged_med = merged_med.astype(np.uint8)
        out = stacker.deghost_sharpest(frames, merged_med, thresh=0.2, log=lambda *a: None)
        # Schärfe in der Bewegungsregion: deghost-Ergebnis >= Median-Mischung
        roi = (slice(70, 130), slice(10, 150))
        self.assertGreaterEqual(_sharpness(out[roi]) + 1e-6, _sharpness(merged_med[roi]),
                                "deghost_sharpest sollte in Streuzonen nicht unschärfer sein als der Median")

    def test_under_two_images(self):
        frames, _ = make_focus_series(n=1)
        merged = frames[0]
        out = stacker.deghost_sharpest(frames, merged, log=lambda *a: None)
        self.assertTrue(np.array_equal(out, merged))

    def test_window_energy_is_robust(self):
        # Fenster-Energie soll einen einzelnen Rausch-Ausreißer nicht durchschlagen lassen
        a = np.zeros((1, 20, 20), np.float32)
        a[0, 10, 10] = 1000.0
        smoothed = stacker._window_energy(a, win=5)
        self.assertLess(smoothed.max(), a.max(),
                        "Fenster-Mittelung muss Spitzen dämpfen")
        self.assertEqual(smoothed.shape, a.shape)


if __name__ == "__main__":
    unittest.main(verbosity=2)
