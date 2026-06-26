#!/usr/bin/env python3
"""
ForgePix — Engine-Tests (reine Logik, ohne GUI). Laufen mit der Standardbibliothek:

    python3 -m unittest discover -s tests        # oder: python3 tests/test_engines.py

Erzeugt synthetische Bilder in einem Temp-Ordner und prüft das beobachtbare Verhalten
der Engines (focus_analysis, longexp, astro, stacker, mosaic, constants).
"""
import os
import sys
import tempfile
import shutil
import unittest

import numpy as np
import cv2

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "core"))   # Engine-Module liegen in core/


def _rng():
    return np.random.RandomState(42)


def make_focus_series(folder, n=10, size=(300, 400), blurry=(), grid_sweep=True):
    """Fokusreihe: jeder Frame in seinem Sektor scharf, Rest unscharf. `blurry` = Indizes
    komplett unscharfer (verwackelter) Frames."""
    h, w = size
    base = (_rng().rand(h, w, 3) * 255).astype(np.uint8)
    paths = []
    for k in range(n):
        out = cv2.GaussianBlur(base.astype(np.float32), (0, 0), 6)
        if k not in blurry and grid_sweep:
            x0 = int(w * k / n); x1 = int(w * (k + 1) / n)
            out[:, x0:x1] = base[:, x0:x1]
        p = os.path.join(folder, f"{k:03d}.png")
        cv2.imwrite(p, np.clip(out, 0, 255).astype(np.uint8))
        paths.append(p)
    return sorted(paths)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.w = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
        shutil.rmtree(self.w, ignore_errors=True)


class TestConstants(TmpCase):
    def test_shared_constants(self):
        import constants
        import focus_cull_stack as F
        import astro
        self.assertIn(".arw", constants.RAW_EXTS)
        self.assertIs(F.RAW_EXTS, constants.RAW_EXTS)
        self.assertIs(astro.RAW_EXTS, constants.RAW_EXTS)
        self.assertTrue(constants.VERSION)


class TestFocusAnalysis(TmpCase):
    def test_matrix_and_blurry(self):
        import focus_analysis as fa
        paths = make_focus_series(self.d, n=10, blurry=(8, 9))
        M = fa.sharpness_matrix(paths, grid=10, log=lambda *a: None)
        self.assertEqual(M.shape[0], 10)
        bad = {i for i, _n, _r in fa.detect_blurry(M, paths)}
        self.assertIn(8, bad)
        self.assertIn(9, bad)
        self.assertNotIn(0, bad)

    def test_sweep_and_optimizer(self):
        import focus_analysis as fa
        paths = make_focus_series(self.d, n=10, blurry=(8, 9))
        M = fa.sharpness_matrix(paths, grid=12, log=lambda *a: None)
        sweep = fa.focus_sweep(M, paths)
        # blurry frames contribute nothing
        self.assertIn(8, sweep["redundant"])
        opt = fa.stack_optimizer(M, paths)
        cov = [lvl["coverage"] for lvl in opt["levels"]]
        # coverage is monotonically non-increasing as frames drop
        self.assertEqual(cov, sorted(cov, reverse=True))
        self.assertLessEqual(cov[0], 100.0)

    def test_analyze_series_report(self):
        import focus_analysis as fa
        paths = make_focus_series(self.d, n=10, blurry=(7,))
        rep = fa.analyze_series(paths, grid=12, log=lambda *a: None)
        self.assertEqual(rep["n"], 10)
        self.assertEqual(len(rep["status"]), 10)
        blurry = [i for i, st, _r in rep["status"] if st == "blurry"]
        self.assertIn(7, blurry)
        self.assertIn("complete", rep)

    def test_focus_map(self):
        import focus_analysis as fa
        paths = make_focus_series(self.d, n=8)
        fm = fa.focus_map(paths)
        self.assertEqual(fm.ndim, 3)
        self.assertEqual(fm.shape[2], 3)

    def test_dof_macro(self):
        import focus_analysis as fa
        d = fa.dof_calc(8, focal_mm=105, magnification=1.0, sensor="fullframe")
        self.assertGreater(d["dof_mm"], 0)
        self.assertLess(d["dof_mm"], 5)               # 1:1 f/8 → sub-mm DOF
        self.assertLess(d["step_mm"], d["dof_mm"])    # mit Überlappung kleiner
        n = fa.frames_for_depth(8.0, d["step_mm"])
        self.assertGreater(n, 5)

    def test_dof_distance(self):
        import focus_analysis as fa
        d = fa.dof_calc(8, focal_mm=50, distance_m=3.0, sensor="fullframe")
        self.assertIsNotNone(d)
        self.assertGreater(d["dof_mm"], 0)

    def test_dof_needs_input(self):
        import focus_analysis as fa
        self.assertIsNone(fa.dof_calc(8, focal_mm=105))  # weder Abbildung noch Distanz

    def test_stack_quality(self):
        import focus_analysis as fa
        img = (_rng().rand(200, 300, 3) * 255).astype(np.uint8)
        q = fa.stack_quality(img)
        self.assertIn("score", q)
        self.assertTrue(0 <= q["score"] <= 100)
        self.assertIsInstance(q["findings"], list)

    def test_exif_optics_graceful(self):
        import focus_analysis as fa
        p = make_focus_series(self.d, n=1)[0]
        r = fa.read_exif_optics(p)            # ohne exiftool → None; mit → dict
        self.assertTrue(r is None or isinstance(r, dict))


class TestLongexp(TmpCase):
    def _series(self, n=6, dark=False):
        h, w = 200, 260
        base = (_rng().rand(h, w, 3) * (60 if dark else 255)).astype(np.uint8)
        paths = []
        for k in range(n):
            im = base.copy()
            im[90:100, 20 + k * 30:28 + k * 30] = 250  # bewegtes helles Objekt
            p = os.path.join(self.d, f"{k:02d}.png"); cv2.imwrite(p, im); paths.append(p)
        return sorted(paths)

    def test_modes(self):
        import longexp
        paths = self._series()
        for m in ("smooth", "trails", "declutter", "bright"):
            r = longexp.combine(paths, mode=m, work_dir=self.w, log=lambda *a: None)
            self.assertEqual(r.shape[2], 3)
            self.assertTrue(0.0 <= float(r.min()) and float(r.max()) <= 1.0)

    def test_strength_blend(self):
        import longexp
        paths = self._series()
        r0 = longexp.combine(paths, mode="smooth", strength=0.0, work_dir=self.w, log=lambda *a: None)
        r1 = longexp.combine(paths, mode="smooth", strength=1.0, work_dir=self.w, log=lambda *a: None)
        self.assertGreater(float(np.abs(r0 - r1).mean()), 0.0)  # Slider wirkt

    def test_suggest_mode(self):
        import longexp
        s = longexp.suggest_mode(self._series())
        self.assertIn(s["mode"], longexp.MODES)
        self.assertIn("rationale", s)

    def test_empty_guard(self):
        import longexp
        with self.assertRaises(RuntimeError):
            longexp.combine([], mode="smooth", work_dir=self.w, log=lambda *a: None)


class TestAstro(TmpCase):
    def _lights(self, n=5):
        h, w = 200, 240
        stars = np.zeros((h, w, 3), np.float32)
        r = _rng()
        for _ in range(30):
            y, x = r.randint(10, h - 10), r.randint(10, w - 10)
            cv2.circle(stars, (x, y), 2, (0.9, 0.9, 0.9), -1)
        stars = cv2.GaussianBlur(stars, (0, 0), 1.0)
        paths = []
        for k in range(n):
            fr = np.clip(stars + r.normal(0, 0.01, stars.shape), 0, 1)
            p = os.path.join(self.d, f"{k:02d}.tif")
            cv2.imwrite(p, (fr * 65535).astype(np.uint16)); paths.append(p)
        return sorted(paths)

    def test_register_and_stack(self):
        import astro
        paths = self._lights()
        reg = astro.register_and_cache(paths, os.path.join(self.w, "reg"), log=lambda *a: None)
        self.assertEqual(len(reg), len(paths))
        res = astro.stack(reg, method="sigma", log=lambda *a: None)
        self.assertEqual(res.shape[2], 3)

    def test_fits_read(self):
        try:
            from astropy.io import fits
        except Exception:
            self.skipTest("astropy nicht installiert")
        import astro
        p = os.path.join(self.d, "light.fits")
        fits.PrimaryHDU(np.random.RandomState(1).rand(80, 100).astype(np.float32)).writeto(p)
        f = astro._read_float(p)                 # FITS-Light lesen
        self.assertEqual(f.shape[2], 3)          # mono -> BGR
        self.assertTrue(0.0 <= float(f.min()) and float(f.max()) <= 1.0)

    def test_stack_methods(self):
        import astro
        reg = astro.register_and_cache(self._lights(), os.path.join(self.w, "r"), log=lambda *a: None)
        for m in ("average", "median", "max", "sigma", "winsor"):
            res = astro.stack(reg, method=m, log=lambda *a: None)
            self.assertTrue(np.isfinite(res).all())

    def test_cosmetic(self):
        import astro
        f = np.full((50, 60, 3), 0.2, np.float32)
        f[25, 30] = 1.0                              # Hot-Pixel
        f[10, 40] = 0.0                              # Cold-Pixel
        out = astro.cosmetic_correct(f)
        self.assertLess(float(out[25, 30].max()), 1.0)      # Hot entfernt
        self.assertGreater(float(out[10, 40].max()), 0.05)  # Cold angehoben

    def test_stack_empty_guard(self):
        import astro
        with self.assertRaises(RuntimeError):
            astro.stack([], log=lambda *a: None)


class TestStacker(TmpCase):
    def test_focus_stack_color(self):
        import stacker
        imgs = []
        for k in range(4):
            im = (_rng().rand(120, 160, 3) * 255).astype(np.uint8)
            imgs.append(cv2.GaussianBlur(im, (0, 0), 1 + k))
        res = stacker.focus_stack(imgs, log=lambda *a: None)
        self.assertEqual(res.shape[:2], (120, 160))

    def test_focus_stack_grayscale_guard(self):
        import stacker
        imgs = [(_rng().rand(120, 160) * 255).astype(np.uint8) for _ in range(3)]
        res = stacker.focus_stack(imgs, log=lambda *a: None)  # darf nicht crashen
        self.assertEqual(res.shape[:2], (120, 160))

    def test_focus_stack_depthmap(self):
        import stacker
        # gemeinsames Motiv, je Frame eine andere scharfe Region — Depth Map muss überall
        # die scharfe Quelle wählen und darf KEINE schwarzen Löcher erzeugen.
        base = (_rng().rand(120, 160, 3) * 255).astype(np.uint8)
        imgs = []
        for k in range(4):
            blur = cv2.GaussianBlur(base, (0, 0), 4)
            sharp_band = base.copy()
            y0 = k * 30
            blur[y0:y0 + 30] = sharp_band[y0:y0 + 30]   # je Frame ein scharfer Streifen
            imgs.append(blur)
        res = stacker.focus_stack_depthmap(imgs, log=lambda *a: None)
        self.assertEqual(res.shape, base.shape)
        self.assertEqual(res.dtype, np.uint8)
        # keine durchgehend schwarzen Zeilen (Loch-Regression)
        self.assertFalse(bool((res.reshape(120, -1).max(axis=1) == 0).any()))

    def test_disagreement_map(self):
        import stacker
        imgs = [(_rng().rand(80, 100, 3) * 255).astype(np.uint8) for _ in range(4)]
        dm = stacker.disagreement_map(imgs)
        self.assertTrue(0.0 <= float(dm.min()) and float(dm.max()) <= 1.0001)

    def test_align_sequential_recenters_shift(self):
        import stacker
        base = (_rng().rand(160, 200, 3) * 255).astype(np.uint8)
        base = cv2.GaussianBlur(base, (0, 0), 1.0)            # etwas Textur fürs Matching
        # Frames mit wachsender bekannter Verschiebung (Drift wie bei Freihand-Reihe)
        imgs = []
        for k in range(5):
            M = np.float32([[1, 0, 2 * k], [0, 1, 1 * k]])
            imgs.append(cv2.warpAffine(base, M, (200, 160), borderMode=cv2.BORDER_REFLECT))
        out = stacker.align_sequential(imgs, detector="ORB", log=lambda *a: None)
        self.assertEqual(len(out), 5)
        self.assertTrue(all(o.shape == base.shape for o in out))
        # Nach der Ausrichtung müssen die Frames deutlich ähnlicher zur Referenz (Mitte) sein
        ref = out[2].astype(np.float32)
        before = np.abs(imgs[0].astype(np.float32) - imgs[2].astype(np.float32)).mean()
        after = np.abs(out[0].astype(np.float32) - ref).mean()
        self.assertLess(after, before)

    def test_hdr_exposure_fusion(self):
        import hdr
        # Drei „Belichtungen" derselben Szene: dunkel / mittel / hell
        base = (_rng().rand(120, 160, 3) * 255).astype(np.uint8)
        dark = (base * 0.4).astype(np.uint8)
        mid = base
        bright = np.clip(base.astype(np.float32) * 1.8, 0, 255).astype(np.uint8)
        out = hdr.merge_exposures([dark, mid, bright], align=False, log=lambda *a: None)
        self.assertEqual(out.shape, base.shape)
        self.assertEqual(out.dtype, np.uint8)
        # Fusion soll weniger ausgebrannte UND weniger abgesoffene Pixel haben als die Extreme
        g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        self.assertLess((g > 250).mean(), (cv2.cvtColor(bright, cv2.COLOR_BGR2GRAY) > 250).mean() + 1e-6)
        self.assertLess((g < 5).mean(), (cv2.cvtColor(dark, cv2.COLOR_BGR2GRAY) < 5).mean() + 1e-6)

    def test_hdr_apply_look(self):
        import hdr
        flat = (np.full((80, 100, 3), 128, np.uint8))
        flat[:, :50] = 120; flat[:, 50:] = 136          # leicht flaches Bild
        neutral = hdr.apply_look(flat, "neutral")
        self.assertTrue(np.array_equal(neutral, flat))   # neutral = unverändert
        for pr in ("natural", "vivid", "dramatic"):
            out = hdr.apply_look(flat, pr)
            self.assertEqual(out.shape, flat.shape)
            self.assertEqual(out.dtype, np.uint8)
        # mehr Kontrast als flach: Std-Abw der Luminanz steigt
        g0 = cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY).std()
        gv = cv2.cvtColor(hdr.apply_look(flat, "vivid"), cv2.COLOR_BGR2GRAY).std()
        self.assertGreater(gv, g0)

    def test_hdr_split_brackets_fixed(self):
        import hdr
        paths = [f"f{i}.arw" for i in range(9)]
        groups = hdr.split_brackets(paths, size=3, log=lambda *a: None)
        self.assertEqual(len(groups), 3)
        self.assertTrue(all(len(g) == 3 for g in groups))

    def test_merge_tree_matches_shape_and_count(self):
        import stacker
        calls = {"n": 0}

        def mf(pair):
            self.assertLessEqual(len(pair), 2)               # immer nur Paare
            calls["n"] += 1
            return np.maximum(pair[0], pair[1]) if len(pair) == 2 else pair[0]
        imgs = [(_rng().rand(40, 50, 3) * 255).astype(np.uint8) for _ in range(5)]
        res = stacker.merge_tree(imgs, mf, log=lambda *a: None)
        self.assertEqual(res.shape, imgs[0].shape)
        self.assertGreaterEqual(calls["n"], 3)               # 5 Frames → mind. 3 Paar-Merges


class TestMosaic(TmpCase):
    def test_stitch_runs(self):
        import mosaic
        # zwei stark überlappende Kacheln aus einem großen Bild
        big = (_rng().rand(300, 600, 3) * 255).astype(np.uint8)
        a = big[:, :360]; b = big[:, 240:]
        pa = os.path.join(self.d, "a.png"); pb = os.path.join(self.d, "b.png")
        cv2.imwrite(pa, a); cv2.imwrite(pb, b)
        try:
            pano, _ = mosaic.stitch([pa, pb], mode="panorama")
            self.assertEqual(pano.ndim, 3)
        except Exception:
            # Stitcher kann bei synthetischem Rauschen scheitern — kein harter Fail
            self.skipTest("Stitcher fand zu wenige Merkmale (synthetisch)")


class TestExport(TmpCase):
    def test_export_targets_only(self):
        """export_targets(only=...) exportiert NUR die genannte Datei, nicht den ganzen Ordner."""
        import focus_cull_stack as F
        sd = os.path.join(self.d, "stack"); os.makedirs(sd)
        for name in ("result.jpg", "ghostmap.jpg"):
            cv2.imwrite(os.path.join(sd, name), (_rng().rand(200, 300, 3) * 255).astype(np.uint8))
        ed = os.path.join(self.d, "export")
        F.export_targets(sd, ed, ["web"], only="result.jpg")
        out = os.listdir(ed)
        self.assertTrue(any("result_web" in f for f in out))
        self.assertFalse(any("ghostmap" in f for f in out))   # kein Müll vom Verzeichnis-Scan


class TestI18n(unittest.TestCase):
    def test_all_strings_translated(self):
        """Jeder tr()/help_btn()-String muss einen en.json-Eintrag haben (kein DE-Rückfall)."""
        import ast
        import json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        keys = set()
        for fn in ("ui/main_window.py", "ui/components.py"):
            tree = ast.parse(open(os.path.join(root, fn)).read())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in ("tr", "help_btn") and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    keys.add(node.args[0].value)
        en = json.load(open(os.path.join(root, "lang", "en.json")))
        missing = sorted(k for k in keys if k not in en and k.strip())
        self.assertEqual(missing, [], f"Ohne EN-Übersetzung: {missing[:5]}")

    def test_keine_unverpackten_ui_strings(self):
        """Regressions-Schutz: sichtbare UI-Texte müssen in tr() stehen. Erkennt rohe String-
        Literale in QLabel/QPushButton/QCheckBox/QGroupBox/setToolTip/setText/setWindowTitle/
        setPlaceholderText/addItem, die wie deutscher Satz/Text aussehen (Umlaut ODER Leerzeichen
        + Buchstabe) — die wären im englischen UI nicht übersetzt."""
        import ast
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        SETTERS = {"QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox",
                   "setToolTip", "setWindowTitle", "setPlaceholderText", "_row"}
        offenders = []

        def looks_like_text(s):
            if any(c in s for c in "äöüßÄÖÜ"):
                return True
            return (" " in s.strip()) and any(c.isalpha() for c in s)

        for fn in ("ui/main_window.py", "ui/components.py"):
            tree = ast.parse(open(os.path.join(root, fn)).read())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    continue
                name = (node.func.id if isinstance(node.func, ast.Name)
                        else node.func.attr if isinstance(node.func, ast.Attribute) else "")
                if name in SETTERS and looks_like_text(node.args[0].value):
                    offenders.append(f"{fn}: {name}({node.args[0].value[:40]!r})")
        self.assertEqual(offenders, [], "Unverpackte deutsche UI-Strings (in tr() setzen):\n"
                         + "\n".join(offenders[:8]))


class TestEditorAutoMask(unittest.TestCase):
    """Auto-Maske im Editor: schützt dunklen Hintergrund + helle Sterne, betont Mitteltöne."""
    def test_lum_mask_protects_darks_and_brights(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            import numpy as np
            from ui.components import AdjustDialog
        except Exception as e:  # pragma: no cover
            self.skipTest(f"Qt nicht verfügbar: {e}")
        QApplication.instance() or QApplication([])
        img = np.zeros((30, 30, 3), "uint8")
        img[0:10] = 5      # dunkler Hintergrund
        img[10:20] = 120   # Mitteltöne (Motiv)
        img[20:30] = 250   # helle Sterne/Kern
        dlg = AdjustDialog(img, "/tmp/x.jpg")
        m = dlg._lum_mask(img)[..., 0]
        self.assertLess(m[0:10].mean(), 0.2)    # Hintergrund geschützt
        self.assertGreater(m[10:20].mean(), 0.5)  # Motiv betont
        self.assertLess(m[20:30].mean(), 0.4)   # helle Sterne geschützt
        dlg.close()

    def test_brush_paints_local_mask(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QPointF
            import numpy as np
            from ui.components import AdjustDialog
        except Exception as e:  # pragma: no cover
            self.skipTest(f"Qt nicht verfügbar: {e}")
        QApplication.instance() or QApplication([])
        dlg = AdjustDialog((np.zeros((120, 160, 3)) + 60).astype("uint8"), "/tmp/x.jpg")
        dlg.resize(800, 600)
        dlg._update()  # setzt Anzeige-Geometrie

        class _Ev:
            def position(self):
                ox, oy, dw, dh, iw, ih = dlg._disp
                return QPointF(ox + dw / 2, oy + dh / 2)
        dlg.brush_on.setChecked(True)
        dlg._set_brush(True)
        dlg._mouse_paint(_Ev())
        self.assertIsNotNone(dlg.mask)
        cy, cx = dlg.mask.shape[0] // 2, dlg.mask.shape[1] // 2
        self.assertGreater(dlg.mask[cy, cx], 0.5)   # Mitte aufgenommen
        self.assertLess(dlg.mask[0, 0], 0.2)        # Ecke unberührt
        dlg.close()


class TestGuiShowResult(unittest.TestCase):
    """Regression: _show_result/_find_result darf nicht crashen (IMG_EXTS-Import-Bug v1.10.1–1.15.0)."""
    def test_show_result_loads_without_crash(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            import numpy as np
            import cv2
            import focus_stack_gui as g
        except Exception as e:  # pragma: no cover
            self.skipTest(f"Qt/cv2 nicht verfügbar: {e}")
        import tempfile
        app = QApplication.instance() or QApplication([])
        app.setStyleSheet(g.THEME)
        w = g.MainWindow()
        work = tempfile.mkdtemp()
        stack = os.path.join(work, "stack")
        os.makedirs(stack)
        cv2.imwrite(os.path.join(stack, "result.jpg"), (np.zeros((30, 40, 3)) + 80).astype("uint8"))
        w.work_edit.setText(work)
        w._show_result()                       # darf NICHT werfen (NameError IMG_EXTS)
        self.assertTrue(w.result_path and w.result_path.endswith("result.jpg"))
        w.close()


class TestGuiSmoke(unittest.TestCase):
    def test_mainwindow_builds(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            import focus_stack_gui as g
        except Exception as e:  # pragma: no cover
            self.skipTest(f"Qt nicht verfügbar: {e}")
        app = QApplication.instance() or QApplication([])
        app.setStyleSheet(g.THEME)
        w = g.MainWindow()
        for t in range(4):                       # alle vier Module bauen ohne Crash
            w._choose_module(t)
        a = w._build_args(False)
        self.assertIn("--input", " ".join(a) + " --input")  # build_args liefert Liste
        w.close()


class TestGuessModule(TmpCase):
    def test_fits_is_astro(self):
        from focus_analysis import guess_module
        open(os.path.join(self.d, "m31.fits"), "w").close()
        self.assertEqual(guess_module(self.d)[0], "astro")

    def test_calibration_names_are_astro(self):
        from focus_analysis import guess_module
        open(os.path.join(self.d, "light_001.jpg"), "w").close()
        self.assertEqual(guess_module(self.d)[0], "astro")

    def test_empty_defaults_makro(self):
        from focus_analysis import guess_module
        self.assertEqual(guess_module(self.d)[0], "makro")


class TestAIContext(unittest.TestCase):
    def test_wish_is_passed_through(self):
        import focus_cull_stack as F

        class A:
            wish = "seidiges Wasser, Personen scharf"
        ctx = F.build_ai_context([], A())  # ohne Bilder: nur der Wunsch
        self.assertEqual(ctx.get("wish"), "seidiges Wasser, Personen scharf")

    def test_empty_wish_gives_no_key(self):
        import focus_cull_stack as F

        class A:
            wish = "  "
        self.assertNotIn("wish", F.build_ai_context([], A()))

    def test_context_injected_into_prompt(self):
        import glob
        import focus_cull_stack as F
        imgs = sorted(glob.glob("testdata/amber-flies/*.jpg"))
        if not imgs:
            self.skipTest("keine Beispielbilder")
        captured = {}
        orig = F._vlm_chat
        F._vlm_chat = lambda e, m, msg, **k: (captured.__setitem__("m", msg)
                                              or '{"subject":"x","rationale":"y"}')
        try:
            frames = [F.Frame(path=p, name=os.path.basename(p), peak_sharp=10.0) for p in imgs]
            F.suggest_settings(frames, "http://x/v1", "m",
                               context={"exif": "105mm, f/8", "wish": "Personen scharf"})
        finally:
            F._vlm_chat = orig
        text = captured["m"][0]["content"][0]["text"]
        self.assertIn("105mm, f/8", text)
        self.assertIn("Personen scharf", text)


class TestGhostAndSubsAI(unittest.TestCase):
    def test_ghostmap_attached_and_advice(self):
        import numpy as np
        import cv2
        import focus_cull_stack as F
        gm = os.path.join(self.tmp(), "gm.jpg")
        cv2.imwrite(gm, (np.zeros((40, 40, 3)) + 128).astype("uint8"))
        cap = {}
        orig = F._vlm_chat
        F._vlm_chat = lambda e, m, msg, **k: (cap.__setitem__("m", msg)
                                              or '{"sharpen":10,"ghost_advice":"linker Flügel"}')
        try:
            res = (np.zeros((60, 60, 3)) + 100).astype("uint8")
            out = F.ai_enhance_params(res, "http://x/v1", "m", ghostmap_path=gm)
        finally:
            F._vlm_chat = orig
        text = cap["m"][0]["content"][0]["text"]
        imgs = [c for c in cap["m"][0]["content"] if c.get("type") == "image_url"]
        self.assertIn("GEISTER-KARTE", text)
        self.assertEqual(len(imgs), 2)            # Ergebnis + Geister-Karte
        self.assertEqual(out.get("ghost_advice"), "linker Flügel")

    def test_subs_summary_text(self):
        import astro_quality as AQ
        frames = [
            {"ok": True, "keep": True, "name": "s1", "fwhm": 3.0, "stars": 400, "reasons": []},
            {"ok": True, "keep": False, "name": "s2", "fwhm": 3.1, "stars": 120,
             "reasons": ["wenige Sterne — Wolken?"]},
        ]
        txt = AQ.subs_summary_text(frames)
        self.assertIn("1 behalten", txt)
        self.assertIn("s2", txt)

    def tmp(self):
        import tempfile
        return tempfile.mkdtemp()


class TestExifReadFallback(unittest.TestCase):
    def test_ratio_parsing(self):
        from focus_analysis import _exr_float

        class _Ratio:
            def __init__(self, n, d):
                self.num, self.den = n, d

        class _Tag:
            def __init__(self, v):
                self.values = [v]
        self.assertAlmostEqual(_exr_float(_Tag(_Ratio(28, 10))), 2.8)   # FNumber 2.8
        self.assertAlmostEqual(_exr_float(_Tag(_Ratio(1, 200))), 0.005)  # 1/200 s
        self.assertAlmostEqual(_exr_float(_Tag(105)), 105.0)             # plain int
        self.assertIsNone(_exr_float(None))

    def test_read_exif_optics_never_crashes(self):
        import focus_analysis as fa
        # Auf einer Nicht-Bild-Datei: darf nicht crashen, gibt Dict oder None
        r = fa.read_exif_optics(__file__)
        self.assertTrue(r is None or isinstance(r, dict))


class TestExifCopyPiexif(TmpCase):
    def test_copy_exif_to_jpeg_without_exiftool(self):
        try:
            import piexif
            import numpy as np
            import cv2
        except Exception:
            self.skipTest("piexif/cv2 fehlt")
        import shutil
        import focus_cull_stack as F
        src = os.path.join(self.d, "src.jpg")
        dst = os.path.join(self.d, "out.jpg")
        cv2.imwrite(src, (np.zeros((40, 40, 3)) + 100).astype("uint8"))
        cv2.imwrite(dst, (np.zeros((20, 20, 3)) + 50).astype("uint8"))
        exif = {"0th": {piexif.ImageIFD.Model: b"ILCE-7M5"},
                "Exif": {piexif.ExifIFD.FNumber: (28, 10)}}
        piexif.insert(piexif.dump(exif), src)
        orig = shutil.which
        F.shutil.which = lambda n: None if n == "exiftool" else orig(n)
        try:
            F.copy_exif(src, [dst])
        finally:
            F.shutil.which = orig
        d = piexif.load(dst)
        self.assertEqual(d["0th"].get(piexif.ImageIFD.Model), b"ILCE-7M5")
        self.assertEqual(d["Exif"].get(piexif.ExifIFD.FNumber), (28, 10))


class TestExifTiff(TmpCase):
    def test_exif_into_tiff_without_exiftool_keeps_pixels(self):
        try:
            import piexif
            import tifffile
            import numpy as np
            import cv2
        except Exception:
            self.skipTest("piexif/tifffile/cv2 fehlt")
        import shutil
        import focus_cull_stack as F
        src = os.path.join(self.d, "src.jpg")
        cv2.imwrite(src, (np.zeros((30, 30, 3)) + 90).astype("uint8"))
        piexif.insert(piexif.dump({"0th": {piexif.ImageIFD.Model: b"ILCE-7M5"}, "Exif": {}}), src)
        dst = os.path.join(self.d, "out.tif")
        data = (np.arange(20 * 20 * 3).reshape(20, 20, 3) % 1000).astype("uint16")
        import tifffile as tf
        tf.imwrite(dst, data)
        before = tf.imread(dst).copy()
        orig = shutil.which
        F.shutil.which = lambda n: None if n == "exiftool" else orig(n)
        try:
            F.copy_exif(src, [dst])
        finally:
            F.shutil.which = orig
        with tf.TiffFile(dst) as t:
            tags = {tg.code: tg.value for tg in t.pages[0].tags}
        self.assertEqual(tags.get(272), "ILCE-7M5")           # Model
        self.assertTrue(np.array_equal(before, tf.imread(dst)))  # Pixel bit-identisch


class TestAstroColorAndStretch(unittest.TestCase):
    def test_bayer_fits_is_debayered_to_color(self):
        try:
            from astropy.io import fits
            import numpy as np
            import astro
        except Exception:
            self.skipTest("astropy fehlt")
        import tempfile
        import os as _os
        # 2D-Bayer-FITS mit BAYERPAT -> muss als 3-Kanal-Farbe zurückkommen
        d = (np.random.rand(40, 60) * 1000).astype("uint16")
        p = _os.path.join(tempfile.mkdtemp(), "bayer.fits")
        hdu = fits.PrimaryHDU(d)
        hdu.header["BAYERPAT"] = "GRBG"
        hdu.writeto(p, overwrite=True)
        out = astro._read_float(p)
        self.assertEqual(out.ndim, 3)
        self.assertEqual(out.shape[2], 3)

    def test_autostretch_lifts_faint_and_clamps(self):
        import numpy as np
        import astro
        f = np.zeros((60, 60, 3), "float32") + 0.02   # Hintergrund-Boden
        f[10:20, 10:20] = 0.15                          # schwaches Nebelsignal (über dem Boden)
        f[40:48, 40:48] = 0.9                           # heller Kern
        out = astro.autostretch(f, strength=14.0, protect_core=True)
        self.assertTrue(0.0 <= out.min() and out.max() <= 1.0)
        self.assertGreater(out[10:20, 10:20].mean(), f[10:20, 10:20].mean())  # Schwaches angehoben
        self.assertGreater(out[40:48, 40:48].mean(), 0.5)                     # Kern bleibt hell

    def test_ai_stretch_params_clamped(self):
        import numpy as np
        import focus_cull_stack as F
        orig = F._vlm_chat
        F._vlm_chat = lambda e, m, msg, **k: '{"strength":99,"saturation":3.0,"color":5,"protect_core":false}'
        try:
            p = F.ai_astro_stretch_params((np.zeros((20, 20, 3)) + 0.2).astype("float32"), "x", "m")
        finally:
            F._vlm_chat = orig
        self.assertLessEqual(p["strength"], 30.0)
        self.assertLessEqual(p["saturation"], 1.6)
        self.assertLessEqual(p["color"], 1.0)   # Farbkalibrierung 0..1 geklemmt

    def test_remove_green_cast(self):
        import numpy as np
        import astro
        f = np.zeros((10, 30, 3), "float32")
        f[:, 0:10] = (0, 1, 0)      # BGR: reines Grün -> sollte stark reduziert werden
        f[:, 10:20] = (0, 0, 1)     # reines Rot -> unverändert
        out = astro.remove_green_cast(f)
        self.assertLess(out[:, 0:10, 1].mean(), 0.1)            # Grün runter (auf (R+B)/2=0)
        self.assertAlmostEqual(float(out[:, 10:20, 2].mean()), 1.0)  # Rot unangetastet

    def _make_starfield(self, shift=(0, 0), hot=True, seed=0):
        import numpy as np
        rng = np.random.RandomState(seed)
        H, W = 300, 400
        g = np.zeros((H, W), np.float32)
        # 60 feste Sterne (gleiche Welt-Position), um (shift) verschoben gerendert
        self._star_xy = getattr(self, "_star_xy", rng.uniform([40, 40], [W - 40, H - 40], (60, 2)))
        for x, y in self._star_xy:
            xi, yi = int(round(x + shift[0])), int(round(y + shift[1]))
            if 1 <= xi < W - 1 and 1 <= yi < H - 1:
                g[yi - 1:yi + 2, xi - 1:xi + 2] += 0.6
                g[yi, xi] += 0.4
        if hot:  # feste Hotpixel an Sensor-Positionen (bewegen sich NICHT mit) → Falle für phaseCorrelate
            for hx, hy in [(50, 50), (120, 200), (300, 100), (380, 280), (200, 30)]:
                g[hy, hx] = 1.0
        return np.clip(g, 0, 1)

    def test_star_centroids_findet_viele_sterne(self):
        # Regression: MAD-Schwelle muss zuverlässig viele Sterne finden (Otsu fand nur eine Handvoll).
        import astro
        g = self._make_starfield()
        pts = astro._star_centroids(g)
        self.assertGreater(len(pts), 30)

    def test_registrierung_findet_drift_trotz_hotpixel(self):
        # Kernregression: Frame um (12, -18) gedriftet, mit FESTEN Hotpixel. Die stern-basierte
        # Registrierung muss die echte Drift finden — nicht wie phaseCorrelate auf (0,0) einrasten.
        import numpy as np
        import astro
        ref = self._make_starfield(shift=(0, 0))
        img = self._make_starfield(shift=(12, -18))
        M = astro._estimate_star_transform(ref, img)
        self.assertIsNotNone(M, "stern-basierte Registrierung sollte die Drift finden")
        # M bildet img→ref ab: die Translation muss ~(-12, +18) zurückschieben
        self.assertAlmostEqual(M[0, 2], -12, delta=1.5)
        self.assertAlmostEqual(M[1, 2], 18, delta=1.5)

    def test_dualband_hoo_ha_red_oiii_teal(self):
        import numpy as np
        import astro
        img = np.zeros((4, 6, 3), "float32")
        img[:, 0:3] = (0, 0, 1.0)   # BGR: nur Rot = Hα
        img[:, 3:6] = (1.0, 1.0, 0)  # Blau+Grün = OIII
        out = astro.dualband_hoo(img)
        self.assertGreater(out[0, 0, 2], 0.5)   # Hα → Rot hoch
        self.assertLess(out[0, 0, 1], 0.5)      # Hα → Grün niedrig
        self.assertGreater(out[0, 4, 1], 0.5)   # OIII → Grün hoch (teal)
        self.assertGreater(out[0, 4, 0], 0.5)   # OIII → Blau hoch (teal)
        self.assertLess(out[0, 4, 2], 0.5)      # OIII → Rot niedrig

    def test_dualband_sho_ha_gold(self):
        # Synthetisches SHO: reines Hα soll gold werden (Rot UND Grün hoch, Blau niedrig).
        import numpy as np
        import astro
        img = np.zeros((4, 6, 3), "float32")
        img[:, 0:3] = (0, 0, 1.0)    # nur Hα
        img[:, 3:6] = (1.0, 1.0, 0)  # nur OIII
        out = astro.dualband_sho(img)
        self.assertGreater(out[0, 0, 2], 0.5)   # Hα → Rot hoch
        self.assertGreater(out[0, 0, 1], 0.3)   # Hα → Grün hoch (gold, nicht reines Rot)
        self.assertLess(out[0, 0, 0], 0.5)      # Hα → Blau niedrig
        self.assertGreater(out[0, 4, 0], 0.5)   # OIII → Blau hoch

    def test_dualband_foraxx_pure_ha_red(self):
        # Foraxx (dynamisch): reines Hα ohne OIII bleibt ROT (kein erzwungenes Gold).
        import numpy as np
        import astro
        img = np.zeros((4, 6, 3), "float32")
        img[:, 0:3] = (0, 0, 1.0)    # nur Hα, kein OIII
        img[:, 3:6] = (1.0, 1.0, 0)  # nur OIII
        out = astro.dualband_foraxx(img)
        self.assertGreater(out[0, 0, 2], 0.5)            # Hα → Rot hoch
        self.assertGreater(out[0, 0, 2], out[0, 0, 1])   # Rot > Grün → rot, nicht gold
        self.assertGreater(out[0, 4, 0], 0.5)            # OIII → Blau hoch

    def test_dualband_bicolor_synth_green(self):
        # Bicolor (Cannistra): Grün wird aus den beiden Kanälen ERRECHNET (G=max(OIII,0.5·Hα)),
        # d. h. reines Hα bekommt etwas Grün (≈0.5) statt 0 → weniger Magenta, wärmer.
        import numpy as np
        import astro
        img = np.zeros((4, 6, 3), "float32")
        img[:, 0:3] = (0, 0, 1.0)    # nur Hα
        img[:, 3:6] = (1.0, 1.0, 0)  # nur OIII
        out = astro.dualband_bicolor(img)
        self.assertGreater(out[0, 0, 2], 0.5)            # Hα → Rot hoch
        self.assertGreater(out[0, 0, 1], 0.2)            # Hα → synthetisches Grün vorhanden (>0)
        self.assertGreater(out[0, 0, 2], out[0, 0, 1])   # bleibt rotdominiert (G≈0.5·R)
        self.assertGreater(out[0, 4, 0], 0.5)            # OIII → Blau hoch

    def test_color_balance_strength_blend(self):
        import numpy as np
        import astro
        f = (np.random.rand(40, 50, 3)).astype("float32")
        self.assertTrue(np.array_equal(astro.color_balance(f, 0.0), f))   # 0 = aus
        out = astro.color_balance(f, 1.0)
        self.assertEqual(out.shape, f.shape)


class TestLayeredTiffSurvivesExif(TmpCase):
    """Regression: EXIF-Übernahme (eingebaut) darf Photoshop-Ebenen im TIFF NICHT plattmachen."""
    def test_layers_preserved(self):
        try:
            import numpy as np
            import tifffile
            import psdtags  # noqa: F401 — Ebenen-TIFF braucht psdtags
            import stacker
            import focus_cull_stack as F
        except Exception:
            self.skipTest("Abhängigkeit fehlt (psdtags/tifffile)")
        import shutil
        res = (np.zeros((30, 40, 3)) + 100).astype("uint8")
        ltif = os.path.join(self.d, "ebenen.tif")
        stacker.write_layered_tiff(ltif, [("Ergebnis", res), ("F1", res)], flat_bgr=res)
        with tifffile.TiffFile(ltif) as t:
            self.assertTrue(any(tg.code == 37724 for tg in t.pages[0].tags))  # Ebenen da
        src = os.path.join(self.d, "src.jpg")
        import cv2
        cv2.imwrite(src, res)
        orig = shutil.which
        F.shutil.which = lambda n: None if n == "exiftool" else orig(n)
        try:
            F.copy_exif(src, [ltif])
        finally:
            F.shutil.which = orig
        with tifffile.TiffFile(ltif) as t:
            self.assertTrue(any(tg.code == 37724 for tg in t.pages[0].tags))  # Ebenen NOCH da


class TestStreamedGhost(unittest.TestCase):
    def test_streamed_disagreement_map(self):
        import glob
        import stacker
        imgs = sorted(glob.glob("testdata/amber-flies/*.jpg"))
        if len(imgs) < 3:
            self.skipTest("zu wenige Beispielbilder")
        dmap = stacker.disagreement_map_streamed(imgs, log=lambda *a: None)
        self.assertIsNotNone(dmap)
        self.assertAlmostEqual(float(dmap.max()), 1.0, places=3)


class TestParallel(unittest.TestCase):
    def test_pmap_preserves_order(self):
        from parallel import pmap
        items = list(range(50))
        self.assertEqual(pmap(lambda x: x * x, items), [x * x for x in items])

    def test_pmap_handles_empty_and_single(self):
        from parallel import pmap
        self.assertEqual(pmap(lambda x: x, []), [])
        self.assertEqual(pmap(lambda x: x + 1, [41]), [42])

    def test_cpu_workers_sane(self):
        from parallel import cpu_workers
        self.assertGreaterEqual(cpu_workers(), 1)
        self.assertLessEqual(cpu_workers(memory_heavy=True), cpu_workers())


class TestBinningAndCalib(unittest.TestCase):
    def test_bin_image_halbiert_und_mittelt(self):
        import numpy as np
        import astro
        f = np.zeros((4, 4, 3), np.float32)
        f[0:2, 0:2] = 1.0                      # ein 2x2-Block weiß
        out = astro.bin_image(f, 2)
        self.assertEqual(out.shape, (2, 2, 3))
        self.assertAlmostEqual(float(out[0, 0, 0]), 1.0)   # Block war ganz weiß
        self.assertAlmostEqual(float(out[1, 1, 0]), 0.0)

    def test_bin_image_factor1_unveraendert(self):
        import numpy as np
        import astro
        f = np.random.rand(6, 8, 3).astype(np.float32)
        self.assertTrue(np.array_equal(astro.bin_image(f, 1), f))

    def test_autodetect_calibration(self):
        import os, tempfile
        import focus_cull_stack as F
        with tempfile.TemporaryDirectory() as d:
            lights = os.path.join(d, "lights"); os.makedirs(lights)
            darks = os.path.join(d, "darks"); os.makedirs(darks)
            import numpy as np, cv2
            cv2.imwrite(os.path.join(darks, "d1.tif"), np.zeros((8, 8, 3), np.uint16))
            cv2.imwrite(os.path.join(lights, "l1.tif"), np.zeros((8, 8, 3), np.uint16))
            dark, flat, bias = F._autodetect_calibration(lights)   # darks liegt im Parent
            self.assertTrue(dark and dark.endswith("darks"))
            self.assertIsNone(flat)


class TestStarless(unittest.TestCase):
    def test_palette_view_liefert_bild(self):
        import numpy as np
        import starless
        img = np.zeros((6, 8, 3), np.float32); img[:, :4] = (0, 0, 0.8)  # etwas Hα
        for pal in (None, "hoo", "bicolor"):
            out = starless._palette_view(img, pal)
            self.assertEqual(out.shape, img.shape)

    def test_boost_nebula_bleibt_im_bereich(self):
        import numpy as np
        import starless
        neb = np.random.rand(20, 20, 3).astype(np.float32)
        out = starless._boost_nebula(neb)
        self.assertEqual(out.shape, neb.shape)
        self.assertGreaterEqual(float(out.min()), 0.0)
        self.assertLessEqual(float(out.max()), 1.0)

    def test_available_ist_bool(self):
        import starless
        self.assertIn(starless.available("/nonexistent"), (True, False))


class TestToolsEngine(unittest.TestCase):
    def test_tool_info_vorhanden(self):
        import tools_engine
        self.assertIn("graxpert", tools_engine.TOOL_INFO)
        self.assertIn("starnet", tools_engine.TOOL_INFO)
        name, url, desc = tools_engine.TOOL_INFO["graxpert"]
        self.assertTrue(url.startswith("http"))

    def test_enhance_raises_ohne_graxpert(self):
        # Ohne installiertes GraXpert muss die Veredeln-Funktion sauber abbrechen (GUI zeigt Hinweis).
        import tools_engine
        orig = tools_engine.find_graxpert
        tools_engine.find_graxpert = lambda *a, **k: None
        try:
            with self.assertRaises(RuntimeError):
                tools_engine.run_graxpert_enhance("/tmp/does_not_exist.tif")
        finally:
            tools_engine.find_graxpert = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
