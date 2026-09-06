"""Regressionen: Farbtreue, Wiederaufnahme, vollständige Dateien und finaler Export."""
import os
import sys
import signal
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import livestack
import focus_cull_stack as pipeline


class LiveRegressions(unittest.TestCase):
    def test_resume_context_tracks_calibration_pixels_and_options(self):
        args = SimpleNamespace(astro_kappa=2.5, no_register=False, aufnahmefilter="dual7")
        dark = np.full((8, 8), .02, np.float32)
        fingerprint = pipeline._live_context_id(args, ".", dark, None)
        self.assertEqual(fingerprint, pipeline._live_context_id(args, ".", dark.copy(), None))
        changed = dark.copy()
        changed[0, 0] += .001
        self.assertNotEqual(fingerprint, pipeline._live_context_id(args, ".", changed, None))
        args.aufnahmefilter = "sv220_sii_oiii_7"
        self.assertNotEqual(fingerprint, pipeline._live_context_id(args, ".", dark, None))

    def test_incompatible_resume_preserves_checkpoint(self):
        from constants import ForgePixFehler
        with tempfile.TemporaryDirectory() as folder:
            state = livestack.LiveStack(registrieren=False)
            state.hinzufuegen(np.full((8, 8, 3), .2, np.float32))
            state.context_id = "different-settings"
            checkpoint = Path(folder) / "_live_zustand.npz"
            state.speichern(checkpoint)
            original = checkpoint.read_bytes()
            with patch("livestack.LiveStack.laden", return_value=state):
                with self.assertRaisesRegex(ForgePixFehler, "neuen Arbeitsordner"):
                    pipeline.live_loop(SimpleNamespace(no_auto_calib=True), folder, folder)
            self.assertEqual(checkpoint.read_bytes(), original)

    def test_channel_rejection_preserves_neutral_pixel(self):
        base = np.full((20, 20, 3), .2, np.float32)
        s = livestack.LiveStack(registrieren=False, gewichten=False)
        for _ in range(5):
            s.hinzufuegen(base.copy())
        noisy = base.copy()
        noisy[10, 10, 0] = .9
        s.hinzufuegen(noisy)
        np.testing.assert_allclose(s.ergebnis()[10, 10], [.2, .2, .2], atol=1e-6)

    def test_resume_preserves_settings_and_future_result(self):
        rng = np.random.default_rng(81)
        frames = [.2 + rng.normal(0, .005, (20, 20, 3)).astype(np.float32) for _ in range(15)]
        s = livestack.LiveStack(registrieren=False, gewichten=False, min_fuer_verwurf=12)
        for f in frames[:6]:
            s.hinzufuegen(f)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "state.npz")
            s.speichern(p)
            resumed = livestack.LiveStack.laden(p)
            self.assertEqual((resumed.registrieren, resumed.gewichten, resumed.min_fuer_verwurf),
                             (False, False, 12))
            for f in frames[6:]:
                s.hinzufuegen(f)
                resumed.hinzufuegen(f)
            np.testing.assert_array_equal(s.ergebnis(), resumed.ergebnis())

    def test_failed_save_preserves_previous_checkpoint(self):
        s = livestack.LiveStack(registrieren=False, gewichten=False)
        s.hinzufuegen(np.full((20, 20, 3), .2, np.float32))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.npz"
            s.speichern(p)
            original = p.read_bytes()
            with patch("livestack.np.savez_compressed", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    s.speichern(p)
            self.assertEqual(original, p.read_bytes())
            self.assertEqual([q.name for q in Path(d).iterdir()], ["state.npz"])

    def test_legacy_checkpoint_requires_rebuild(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.npz"
            np.savez(p, summe=np.zeros((2, 2, 3)))
            self.assertIsNone(livestack.LiveStack.laden(p, log=lambda *a: None))

    def test_growing_file_waits_for_stability(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "frame.fits"
            p.write_bytes(b"S")
            seen = {}
            def scan(t):
                return livestack.neue_dateien(d, set(), beobachtet=seen, jetzt=t, settle=2)
            self.assertEqual(scan(0), [])
            p.write_bytes(b"SIMPLE")
            self.assertEqual(scan(2), [])
            self.assertEqual(scan(3), [])
            self.assertEqual(scan(4), [str(p)])

    def test_retry_and_stop_export_real_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "frame.tif")
            from constants import imwrite
            base = np.full((32, 32, 3), .2, np.float32)
            imwrite(p, (base * 65535).astype(np.uint16))
            state = livestack.LiveStack(registrieren=False, gewichten=False)
            handlers, seen = {}, []
            def register(sig, handler):
                handlers[sig] = handler
                return signal.SIG_DFL
            def scan(folder, known, **kwargs):
                seen.append(set(known))
                return [] if p in known else [p]
            polls = []
            def poll(_):
                polls.append(1)
                if len(polls) == 3:
                    handlers[signal.SIGINT](None, None)
            args = SimpleNamespace(prefix="", astro_stretch=6.0, vlm_endpoint="", vlm_model="")
            with patch("livestack.LiveStack", return_value=state), \
                 patch("livestack.astro._read_float", side_effect=[OSError("file still being written"), base]), \
                 patch("livestack.neue_dateien", side_effect=scan), \
                 patch("signal.signal", side_effect=register), \
                 patch("time.sleep", side_effect=poll):
                pipeline.live_loop(args, d, str(Path(d) / "work"))
            self.assertEqual(seen, [set(), set(), {p}])
            self.assertEqual(state.n, 1)
            exported = list((Path(d) / "work" / "stack").glob("*linear_32bit.tif"))
            self.assertEqual(len(exported), 1)
            import tifffile
            np.testing.assert_allclose(tifffile.imread(exported[0]), base, atol=1e-6)
            self.assertEqual(handlers[signal.SIGINT], signal.SIG_DFL)

    def test_crop_without_scipy(self):
        import subprocess
        code = """
import sys
sys.path.insert(0, 'core')
sys.modules['scipy'] = None
import mosaic
import numpy as np
img = np.zeros((20,20,3), np.uint8)
img[3:17,3:17] = 100
assert mosaic._autocrop(img).shape == (14,14,3)
"""
        result = subprocess.run([sys.executable, "-c", code],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
