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
import shutil
import tempfile
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


class TestFokusLueckenBewertung(unittest.TestCase):
    """F6 — der Punktabzug für eine Fokuslücke muss mit der fehlenden Abdeckung wachsen.

    Vorher pauschal −8. Folge (gemessen, nicht geschätzt): eine Serie aus 3 Aufnahmen mit
    Lücken (70 % Abdeckung, nur 45 % der Originalschärfe gerettet) bekam 92/100, eine
    lückenlose Serie aus 9 Aufnahmen (144 % Schärfe) nur 85/100 — die Note war der
    tatsächlichen Qualität entgegengesetzt."""

    def test_f6_lueckenlos_kostet_nichts(self):
        import focus_analysis as fa
        self.assertEqual(fa.focus_gap_penalty(1.0), 0)
        self.assertEqual(fa.focus_gap_penalty(fa.FOKUS_ABDECKUNG_OK), 0)

    def test_f6_abzug_waechst_monoton_mit_der_luecke(self):
        import focus_analysis as fa
        werte = [fa.focus_gap_penalty(c) for c in (0.90, 0.80, 0.70, 0.60, 0.50)]
        self.assertEqual(werte, sorted(werte), f"nicht monoton: {werte}")
        self.assertLess(werte[0], werte[-1], "eine groessere Luecke muss mehr kosten")

    def test_f6_luecke_wiegt_schwerer_als_ghosting_und_halo(self):
        """Ghosting kostet 15, Halos 12 — beides ist nachtraeglich behebbar. Eine deutliche
        Fokusluecke ist es nicht und muss darum schwerer wiegen."""
        import focus_analysis as fa
        self.assertGreater(fa.focus_gap_penalty(0.70), 15,
                           "eine 70-%-Abdeckung muss mehr kosten als der Ghosting-Abzug")

    def test_f6_abzug_ist_gedeckelt_und_nie_negativ(self):
        import focus_analysis as fa
        for c in (-1.0, 0.0, 0.3, 0.5, 1.0, 2.0):
            p = fa.focus_gap_penalty(c)
            self.assertGreaterEqual(p, 0)
            self.assertLessEqual(p, 45, f"Abzug ausser Rand und Band bei coverage={c}")

    def test_f6_note_ordnet_lueckenlos_ueber_lueckenhaft(self):
        """Der konkrete gemessene Fall: 100−Abzug muss die lueckenhafte Serie unter die
        lueckenlose (dort 85 durch die Ghosting-Heuristik) schieben."""
        import focus_analysis as fa
        lueckenhaft = 100 - fa.focus_gap_penalty(0.70)
        self.assertLess(lueckenhaft, 85, f"lueckenhafte Serie bekaeme {lueckenhaft}/100")


class TestGhostingStaffelung(unittest.TestCase):
    """F7 — die Ghosting-Heuristik darf statische Serien nicht als bewegt verurteilen.

    Gemessen: eine Serie MIT echter Bewegung liegt bei ~2.7 % Geisterfläche, eine VÖLLIG
    statische Fokusreihe je nach Motiv und Unschärfegrad zwischen 0.0 % und 0.8 % — die
    Frames sind bei starker Defokussierung konstruktionsbedingt uneins. Die alte einstufige
    Schwelle (0.2 %) verurteilte solche Serien als „Ghosting erkannt" und zog 15 Punkte ab."""

    def _reihe(self, n=9, blur=6.0, bewegung=False):
        h, w = 200, 260
        rng = np.random.RandomState(17)
        base = cv2.GaussianBlur((rng.rand(h, w, 3) * 255).astype(np.uint8), (0, 0), 0.7)
        for i in range(8):                       # harte Kanten -> der kritische Fall
            x, y = int(rng.randint(20, w - 40)), int(rng.randint(20, h - 40))
            cv2.rectangle(base, (x, y), (x + 26, y + 26),
                          tuple(int(v) for v in rng.randint(0, 255, 3)), -1)
        tiefe = np.tile(np.linspace(0, 1, w, dtype=np.float32), (h, 1))
        frames = []
        for i in range(n):
            d = np.abs(tiefe - i / (n - 1)) * blur
            f = np.zeros_like(base, np.float32)
            stufen = np.linspace(0, blur, 8)
            for s_ in stufen:
                b = base.astype(np.float32) if s_ < 0.05 else cv2.GaussianBlur(base.astype(np.float32), (0, 0), s_)
                halb = (stufen[1] - stufen[0]) / 2
                f += b * ((d >= s_ - halb) & (d < s_ + halb)).astype(np.float32)[..., None]
            f = np.clip(f, 0, 255).astype(np.uint8)
            if bewegung:
                cv2.circle(f, (30 + i * 22, 60), 14, (255, 40, 40), -1)
            frames.append(f)
        return frames

    def test_f7_befund_wird_nicht_als_tatsache_behauptet(self):
        """Die Heuristik KANN statisch und bewegt nicht trennen (gemessene Bereiche
        ueberlappen: statisch 0.00-0.81 %, bewegt 0.56-2.67 %). Darum darf der Befund nur
        eine Moeglichkeit benennen und den Nutzer auf die Geister-Karte verweisen —
        nicht behaupten, es sei Ghosting."""
        import focus_analysis as fa
        frames = self._reihe(bewegung=False)
        res = stacker.focus_stack_pyramid_consistent([f.copy() for f in frames], log=lambda *a: None)
        q = fa.stack_quality(np.asarray(res, np.uint8), frames)
        text = " ".join(q["findings"])
        self.assertNotIn("Ghosting/Bewegungszonen erkannt", text,
                         "Heuristik behauptet Ghosting als Tatsache")
        if "Geisterbilder" in text:
            self.assertIn("Geister-Karte", text, "Hinweis ohne Handlungsmoeglichkeit")

    def test_f7_empfindlichkeit_bleibt_erhalten(self):
        """Gegenprobe: die Umformulierung darf den Detektor NICHT unempfindlicher machen.
        Ein Versuch mit hoeherer Warnschwelle machte ihn fuer kleine Geister blind —
        deshalb wird hier festgehalten, dass bewegte Serien weiter ansprechen."""
        import focus_analysis as fa
        statisch = self._reihe(bewegung=False)
        bewegt = self._reihe(bewegung=True)
        def flaeche(fr):
            res = stacker.focus_stack_pyramid_consistent([f.copy() for f in fr], log=lambda *a: None)
            return fa.stack_quality(np.asarray(res, np.uint8), fr)["ghost_area_pct"]
        self.assertGreater(flaeche(bewegt), flaeche(statisch),
                           "bewegte Serie muss mehr Streuung zeigen als die statische")
        self.assertGreater(flaeche(bewegt), fa.GHOST_HINWEIS * 100,
                           "echte Bewegung spricht nicht mehr an — Detektor blind geworden")

    def test_f7_abzug_ist_massvoll(self):
        """Bei einer Heuristik mit ueberlappenden Bereichen waeren 15 Punkte Abzug
        ueberheblich — eine Fokusluecke (nicht behebbar) muss schwerer wiegen."""
        import focus_analysis as fa
        frames = self._reihe(bewegung=True)
        res = stacker.focus_stack_pyramid_consistent([f.copy() for f in frames], log=lambda *a: None)
        q = fa.stack_quality(np.asarray(res, np.uint8), frames)
        self.assertGreaterEqual(q["score"], 75,
                                "unsichere Heuristik wertet zu hart ab")
        self.assertGreater(fa.focus_gap_penalty(0.70), 8,
                           "die nicht behebbare Fokusluecke muss schwerer wiegen als der Ghosting-Verdacht")

    def test_f7_schwelle_vorhanden(self):
        import focus_analysis as fa
        self.assertGreater(fa.GHOST_HINWEIS, 0)


class TestZweiteVerschmelzung(unittest.TestCase):
    """F8 — `--alt-merge`: zweite Verschmelzung mit dem GEGENTEILIGEN Verfahren als
    Pinselquelle für die Retusche.

    Der Standardgriff bei Zerene/Helicon: die Tiefenkarten-Variante hält Farben und glatte
    Flächen sauber, die Pyramide holt Detail an Haaren/Borsten — eine als Basis nehmen, die
    Stärken der anderen hineinpinseln. Bewusst WÄHREND des Stacks gerechnet: bei 24 MP × 16
    Frames dauert eine Verschmelzung gemessen ~30 s, im Retusche-Dialog nachgerechnet würde
    das die Oberfläche einfrieren."""

    def _serie(self, n=4, h=120, w=160):
        rng = np.random.RandomState(23)
        base = cv2.GaussianBlur((rng.rand(h, w, 3) * 255).astype(np.uint8), (0, 0), 0.6)
        tiefe = np.tile(np.linspace(0, 1, w, dtype=np.float32), (h, 1))
        out = []
        for i in range(n):
            d = np.abs(tiefe - i / (n - 1)) * 4.0
            f = np.zeros_like(base, np.float32)
            stufen = np.linspace(0, 4.0, 6)
            for s_ in stufen:
                b = base.astype(np.float32) if s_ < 0.05 else cv2.GaussianBlur(base.astype(np.float32), (0, 0), s_)
                halb = (stufen[1] - stufen[0]) / 2
                f += b * ((d >= s_ - halb) & (d < s_ + halb)).astype(np.float32)[..., None]
            out.append(np.clip(f, 0, 255).astype(np.uint8))
        return out

    def test_f8_alt_merge_erzeugt_datei_mit_gegenteiligem_verfahren(self):
        """Echter Pipeline-Lauf: --alt-merge muss altmerge_<verfahren>.tif ablegen, und zwar
        mit dem KOMPLEMENTAEREN Verfahren zum gewaehlten."""
        import subprocess
        import glob
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = tempfile.mkdtemp(prefix="fp_alt_")
        try:
            ein = os.path.join(d, "in"); os.makedirs(ein)
            for i, f in enumerate(self._serie()):
                cv2.imencode(".jpg", f)[1].tofile(os.path.join(ein, "f_%02d.jpg" % i))
            wd = os.path.join(d, "work")
            r = subprocess.run([sys.executable, "-u", os.path.join(root, "core", "focus_cull_stack.py"),
                                "--input", ein, "--work", wd, "--alt-merge"],
                               capture_output=True, cwd=root, timeout=600)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-500:])
            treffer = glob.glob(os.path.join(wd, "altmerge_*.tif"))
            self.assertTrue(treffer, "keine zweite Verschmelzung abgelegt")
            # Standardverfahren ist die Pyramide -> die Alternative muss die Tiefenkarte sein
            self.assertIn("depthmap", os.path.basename(treffer[0]))
            bild = cv2.imdecode(np.fromfile(treffer[0], np.uint8), cv2.IMREAD_UNCHANGED)
            self.assertIsNotNone(bild, "abgelegte Verschmelzung ist nicht lesbar")
            self.assertEqual(bild.shape[:2], (120, 160))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_f8_ohne_schalter_keine_zweite_datei(self):
        """Gegenprobe: ohne --alt-merge darf der zweite Durchgang nicht laufen (er kostet Zeit)."""
        import subprocess
        import glob
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = tempfile.mkdtemp(prefix="fp_alt2_")
        try:
            ein = os.path.join(d, "in"); os.makedirs(ein)
            for i, f in enumerate(self._serie()):
                cv2.imencode(".jpg", f)[1].tofile(os.path.join(ein, "f_%02d.jpg" % i))
            wd = os.path.join(d, "work")
            r = subprocess.run([sys.executable, "-u", os.path.join(root, "core", "focus_cull_stack.py"),
                                "--input", ein, "--work", wd],
                               capture_output=True, cwd=root, timeout=600)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(glob.glob(os.path.join(wd, "altmerge_*.tif")), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
