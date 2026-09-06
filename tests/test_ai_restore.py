"""Numerical and file-safety regressions for local monochrome ONNX inference."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
import tifffile
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import ai_restore
from constants import ForgePixFehler


class _Session:
    def __init__(self, transform=lambda x: x):
        self.transform = transform
        self.inputs = []

    def run(self, names, inputs):
        value = inputs["input"]
        if value.dtype != np.float32 or value.shape != (1, 1, 256, 256):
            raise AssertionError("invalid model input contract")
        self.inputs.append((float(value.min()), float(value.max())))
        return [self.transform(value)]


class AIRestoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.models = self.root / "models"
        self.folder = self.models / "test-mono"
        self.folder.mkdir(parents=True)
        content = b"test graph; execution is replaced by a numerical model fixture"
        (self.folder / "model.onnx").write_bytes(content)
        self.manifest = {"schema_version": 1, "id": "test-mono", "task": "denoise",
                         "model_file": "model.onnx", "sha256": hashlib.sha256(content).hexdigest(),
                         "channels": 1, "tile_size": 256, "halo": 32,
                         "normalization": "affine_percentile_v1",
                         "output": "complete_target",
                         "status": "experimental", "release_approved": False}
        self._save_manifest()

    def _save_manifest(self):
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def _restore(self, image, **kwargs):
        return ai_restore.restore(image, "test-mono", model_dir=self.models,
                                  allow_experimental=True, log=lambda *a: None, **kwargs)

    def _file(self, source, **kwargs):
        return Path(ai_restore.run_file(source, "test-mono", model_dir=self.models,
                                       allow_experimental=True, log=lambda *a: None, **kwargs))

    def test_identity_preserves_mono_rgb_and_small_reflected_images(self):
        rng = np.random.default_rng(52)
        for shape in ((1, 1), (1, 9), (11, 1), (7, 13), (385, 601), (225, 413, 3)):
            image = rng.normal(.3, .2, shape).astype(np.float32)
            original = image.copy()
            session = _Session()
            with patch.object(ai_restore, "_create_session", return_value=(session, "input", "output")):
                result = self._restore(image, strength=1)
            self.assertEqual((result.shape, result.dtype), (image.shape, np.float32))
            np.testing.assert_allclose(result, image, atol=3e-7, rtol=2e-6)
            np.testing.assert_array_equal(image, original)

    def test_shared_unclipped_normalization_and_channel_independence(self):
        rng = np.random.default_rng(19)
        image = rng.uniform(.1, 2, (300, 431, 3)).astype(np.float32)
        image[..., 1] *= .2
        image[..., 2] *= 4
        image[0, 0] = [-10, 40, 1]
        session = _Session(lambda x: np.float32(.8) * x + np.float32(.1))
        progress = []
        with patch.object(ai_restore, "_create_session", return_value=(session, "input", "output")):
            result = self._restore(image, strength=.7, progress=lambda done, total: progress.append((done, total)))
        low, high = np.percentile(image, [.1, 99.9])
        scale = max(float(high) - float(low), 1e-6)
        expected = image + .7 * (.8 * (image - low) + .1 * scale + low - image)
        np.testing.assert_allclose(result, expected, atol=1e-5, rtol=2e-6)
        self.assertLess(min(pair[0] for pair in session.inputs), 0)
        self.assertGreater(max(pair[1] for pair in session.inputs), 1)
        self.assertEqual(progress[0], (0, 18))
        self.assertEqual(progress[-1], (18, 18))
        self.assertEqual([done for done, total in progress], list(range(19)))
        with patch.object(ai_restore, "_create_session", return_value=(_Session(lambda x: .8 * x + .1), "input", "output")):
            permuted = self._restore(image[..., ::-1], strength=.7)
        np.testing.assert_array_equal(permuted[..., ::-1], result)

    def test_zero_strength_is_exact_and_does_not_load_runtime(self):
        image = np.array([[-.2, 5], [12, .001]], np.float32)
        with patch.object(ai_restore, "_create_session", side_effect=AssertionError("runtime loaded")):
            result = self._restore(image, strength=0)
        np.testing.assert_array_equal(result, image)
        self.assertFalse(np.shares_memory(result, image))

    def test_background_subtracts_global_smooth_gradient_without_resampling_stars(self):
        self.manifest["task"] = "background"
        self._save_manifest()
        h, w = 512, 768
        y, x = np.mgrid[:h, :w]
        image = (.2 + .3 * x / w + .1 * y / h).astype(np.float32)
        image[250, 310], image[251, 311], image[270, 390] = 1.7, -.1, 1.9
        wy, wx = np.mgrid[:256, :256]
        known_residual = (.08 * (wx + .5) / 256 + .03 * (wy + .5) / 256 - .02).astype(np.float32)
        session = _Session(lambda tile: tile - known_residual[None, None])
        original = image.copy()
        with patch.object(ai_restore, "_create_session", return_value=(session, "input", "output")):
            result = self._restore(image, strength=.8)
        self.assertEqual(len(session.inputs), 1)
        low, high = np.percentile(image, [.1, 99.9])
        # A linear gradient is unchanged by symmetric smoothing away from the
        # image edge. This analytic expectation includes the original point stars.
        full_gradient = .08 * (x + .5) / w + .03 * (y + .5) / h - .02
        expected = image - .8 * (high - low) * full_gradient
        np.testing.assert_allclose(result[160:352, 240:528], expected[160:352, 240:528], atol=2e-5)
        self.assertGreater(result[250, 310], 1.6)
        self.assertLess(result[251, 311], 0)
        np.testing.assert_array_equal(image, original)

    def test_background_known_constant_residual_preserves_single_pixel_detail(self):
        self.manifest["task"] = "background"
        self._save_manifest()
        rng = np.random.default_rng(74)
        image = rng.uniform(.1, .2, (431, 589)).astype(np.float32)
        image[99, 101], image[100, 101] = 8, -.4
        with patch.object(ai_restore, "_create_session", return_value=(_Session(lambda tile: tile - .125), "input", "output")):
            result = self._restore(image, strength=1)
        low, high = np.percentile(image, [.1, 99.9])
        expected = image - .125 * (high - low)
        np.testing.assert_allclose(result, expected, atol=1e-6)
        self.assertAlmostEqual(float(result[99, 101] - result[100, 101]),
                               float(image[99, 101] - image[100, 101]), places=5)

    def test_background_uses_one_global_prediction_per_channel_and_keeps_offset(self):
        self.manifest["task"] = "background"
        self._save_manifest()
        image = np.full((401, 601, 3), [-.2, .7, 2.1], np.float32)
        session = _Session(lambda tile: .8 * tile + .05)
        progress = []
        with patch.object(ai_restore, "_create_session", return_value=(session, "input", "output")):
            result = self._restore(image, strength=.5, progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(len(session.inputs), 3)
        self.assertEqual(progress, [(0, 3), (1, 3), (2, 3), (3, 3)])
        low, high = np.percentile(image, [.1, 99.9])
        expected = image - .5 * (.2 * (image - low) - .05 * (high - low))
        np.testing.assert_allclose(result, expected, atol=2e-7)
        # There is deliberately no median recentering of the predicted residual.
        self.assertNotEqual(float(result.mean()), float(image.mean()))

    def test_background_invalid_prediction_cancel_and_zero_strength(self):
        self.manifest["task"] = "background"
        self._save_manifest()
        image = np.array([[-.2, 2.3]], np.float32)
        with patch.object(ai_restore, "_create_session", side_effect=AssertionError("runtime loaded")):
            np.testing.assert_array_equal(self._restore(image, strength=0), image)
        with patch.object(ai_restore, "_create_session", return_value=(_Session(lambda tile: tile[..., :100, :100]), "input", "output")):
            with self.assertRaisesRegex(ForgePixFehler, "ungültige Pixel"):
                self._restore(image)
        with patch.object(ai_restore, "_create_session", return_value=(_Session(lambda tile: np.full_like(tile, np.nan)), "input", "output")):
            with self.assertRaisesRegex(ForgePixFehler, "ungültige Pixel"):
                self._restore(image)
        cancel = threading.Event()
        session = _Session()
        with patch.object(ai_restore, "_create_session", return_value=(session, "input", "output")):
            with self.assertRaisesRegex(ForgePixFehler, "abgebrochen"):
                self._restore(np.ones((401, 601, 3), np.float32), cancel=cancel,
                              progress=lambda done, total: cancel.set() if done == 1 else None)
        self.assertEqual(len(session.inputs), 1)

    def test_background_report_describes_whole_field_residual_instead_of_tiling(self):
        self.manifest["task"] = "background"
        self._save_manifest()
        source = self.root / "background-source.fits"
        fits.writeto(source, np.full((312, 511), .2, np.float32))
        with patch.object(ai_restore, "_create_session", return_value=(_Session(), "input", "output")):
            output = self._file(source)
        report = json.loads((output.parent / "ai_report.json").read_text())
        self.assertEqual(report["strategy"], "global_background_residual")
        self.assertNotIn("tiling", report)
        self.assertEqual(report["inference"]["working_shape"], [256, 256])
        self.assertEqual(report["inference"]["residual_smoothing_sigma"], 16)
        self.assertEqual(report["inference"]["input_interpolation"], "area")
        self.assertEqual(report["inference"]["residual_interpolation"], "cubic")
        self.assertTrue(report["inference"]["applied"])
        self.assertFalse(report["release_approved"])

    def test_invalid_images_and_strength_are_rejected(self):
        for image in (np.zeros((0, 3)), np.zeros((2, 2, 4)), np.full((2, 2), np.nan),
                      np.full((2, 2), np.inf), np.full((2, 2), 1e100), np.ones((2, 2), complex)):
            with self.assertRaises(ForgePixFehler):
                self._restore(image)
        for strength in (-.1, 1.1, np.nan, "invalid"):
            with self.assertRaisesRegex(ForgePixFehler, "Stärke"):
                self._restore(np.ones((2, 2)), strength=strength)

    def test_explicit_experimental_opt_in_and_hash_are_required(self):
        with self.assertRaisesRegex(ForgePixFehler, "experimentell"):
            ai_restore.restore(np.ones((2, 2)), "test-mono", model_dir=self.models)
        self.assertTrue(ai_restore.list_models(self.models)[0]["available"])
        (self.folder / "model.onnx").write_bytes(b"changed graph")
        entry = ai_restore.list_models(self.models)[0]
        self.assertFalse(entry["available"])
        self.assertIn("SHA256", entry["reason"])
        with self.assertRaisesRegex(ForgePixFehler, "SHA256"):
            self._restore(np.ones((2, 2)), strength=0)

    def test_manifest_rejects_path_traversal_and_incompatible_contract(self):
        for value in ("../model.onnx", "..\\model.onnx", "C:\\model.onnx", "/tmp/model.onnx"):
            self.manifest["model_file"] = value
            self._save_manifest()
            with self.assertRaisesRegex(ForgePixFehler, "neben dem Manifest"):
                self._restore(np.ones((2, 2)), strength=0)
        self.manifest["model_file"] = "model.onnx"
        self.manifest["channels"] = 3
        self._save_manifest()
        with self.assertRaisesRegex(ForgePixFehler, "channels"):
            self._restore(np.ones((2, 2)), strength=0)

    def test_unknown_or_missing_model_output_contract_is_rejected(self):
        for value in (None, "residual", "noise"):
            self.manifest["output"] = value
            self._save_manifest()
            with self.assertRaisesRegex(ForgePixFehler, "complete_target"):
                self._restore(np.ones((2, 2)), strength=0)

    def test_scientific_header_and_coverage_survive_fits_and_tiff_roundtrip(self):
        source = self.root / "science.fits"
        image = np.arange(240, dtype=np.float32).reshape(12, 20) / 20 - .2
        fields = {"OBJECT": "M27", "FILTER": "SII", "FPLINE": "SII", "FPCOORD": "registered-grid-123",
                  "INSTRUME": "ASI294MC Pro", "TELESCOP": "RC203", "EXPTIME": 300., "BUNIT": "electron / s",
                  "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CRPIX1": 10., "CRPIX2": 6.,
                  "CRVAL1": 299.901, "CRVAL2": 22.721, "CDELT1": -.000255, "CDELT2": .000255}
        header = fits.Header(dict(fields, FPCOV="input-coverage.tif"))
        header.add_history("Original calibrated science product")
        fits.writeto(source, image, header, checksum=True)
        mask = np.ones(image.shape, np.uint8)
        tifffile.imwrite(source.parent / "input-coverage.tif", mask)
        original = source.read_bytes()
        output = self._file(source, strength=0)
        result_header = fits.getheader(output.with_suffix(".fits"))
        for key, value in fields.items():
            self.assertEqual(result_header[key], value, key)
        self.assertEqual(result_header["BITPIX"], -32)
        self.assertNotIn("CHECKSUM", result_header)
        self.assertNotIn("DATASUM", result_header)
        self.assertIn("Original calibrated science product", str(result_header["HISTORY"]))
        self.assertEqual(result_header["FPCOV"], "coverage.tif")
        np.testing.assert_array_equal(tifffile.imread(output.parent / "coverage.tif"), mask)
        self.assertEqual(source.read_bytes(), original)
        with tifffile.TiffFile(output) as file:
            metadata = json.loads(file.pages[0].description)
        self.assertEqual(metadata["FPLINE"], "SII")
        self.assertEqual(metadata["FPCOV"], "coverage.tif")
        self.assertEqual(metadata["BUNIT"], "electron / s")
        # Reading a ForgePix TIFF must preserve its embedded WCS in another FITS.
        second = self._file(output, strength=0)
        second_header = fits.getheader(second.with_suffix(".fits"))
        for key, value in fields.items():
            self.assertEqual(second_header[key], value, key)
        np.testing.assert_array_equal(tifffile.imread(second.parent / "coverage.tif"), mask)
        np.testing.assert_array_equal(ai_restore.read_source(second), image)

    def test_partial_missing_or_unsafe_coverage_is_rejected_before_inference(self):
        source = self.root / "coverage-source.fits"
        fits.writeto(source, np.ones((10, 10), np.float32), fits.Header({"FPCOV": "mask.tif"}))
        with self.assertRaisesRegex(ForgePixFehler, "Bildabdeckung fehlt"):
            self._file(source, strength=0)
        mask = np.ones((10, 10), np.uint8)
        mask[0, 0] = 0
        tifffile.imwrite(self.root / "mask.tif", mask)
        with self.assertRaisesRegex(ForgePixFehler, "vollständig abgedeckten Bereich"):
            self._file(source, strength=0)
        fits.setval(source, "FPCOV", value="../mask.tif")
        with self.assertRaisesRegex(ForgePixFehler, "Ungültiger Verweis"):
            self._file(source, strength=0)
        self.assertEqual(list(self.root.glob("ai-*")), [])

    def test_runtime_is_optional_and_prediction_failures_are_clear(self):
        with patch.dict(sys.modules, {"onnxruntime": None}):
            with self.assertRaisesRegex(ForgePixFehler, "ONNX Runtime fehlt"):
                ai_restore._create_session(b"unused")
        for transform in (lambda x: np.full_like(x, np.nan), lambda x: x[..., :128, :128]):
            with patch.object(ai_restore, "_create_session", return_value=(_Session(transform), "input", "output")):
                with self.assertRaisesRegex(ForgePixFehler, "ungültige Pixel"):
                    self._restore(np.ones((2, 2)))

    def test_cancellation_stops_between_tiles_without_outputs(self):
        source = self.root / "source.fits"
        fits.writeto(source, np.full((400, 400), .2, np.float32))
        original = source.read_bytes()
        cancel, session = threading.Event(), _Session()
        def progress(done, total):
            if done == 1:
                cancel.set()
        with patch.object(ai_restore, "_create_session", return_value=(session, "input", "output")):
            with self.assertRaisesRegex(ForgePixFehler, "abgebrochen"):
                self._file(source, cancel=cancel, progress=progress)
        self.assertEqual(len(session.inputs), 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(list(self.root.glob("ai-*")), [])
        with self.assertRaisesRegex(ForgePixFehler, "abgebrochen"):
            self._restore(np.ones((2, 2)), cancel=lambda: True)

    def test_file_outputs_keep_signed_stars_residual_and_original(self):
        self.manifest["task"] = "starless"
        self._save_manifest()
        source = self.root / "source.fits"
        # FITS axis order is RGB x H x W; no 0..1 scaling may be inferred.
        image = np.stack([np.full((15, 21), value, np.float32) for value in (-.2, 1.5, 7)], axis=-1)
        fits.writeto(source, np.moveaxis(image, -1, 0), fits.Header({"BAYERPAT": "RGGB", "XBAYROFF": 1}))
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        with patch.object(ai_restore, "_create_session", return_value=(_Session(lambda x: x + .05), "input", "output")):
            output = self._file(source, strength=1)
            prior = output.read_bytes()
            second = self._file(source, strength=1)
        self.assertNotEqual(output.parent, second.parent)
        self.assertEqual(output.read_bytes(), prior)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
        result = tifffile.imread(output)
        residual = tifffile.imread(output.parent / "stars_residual_32bit.tif")
        self.assertTrue(np.all(residual < 0))
        self.assertGreater(result.max(), 1)
        np.testing.assert_allclose(result + residual, image, atol=1e-6)
        np.testing.assert_array_equal(np.moveaxis(fits.getdata(output.with_suffix(".fits")), 0, -1), result)
        self.assertTrue(fits.getheader(output.with_suffix(".fits"))["FPLINEAR"])
        self.assertEqual(fits.getheader(output.with_suffix(".fits"))["FPQUAL"], "EXPERIMENTAL")
        self.assertNotIn("BAYERPAT", fits.getheader(output.with_suffix(".fits")))
        self.assertEqual(fits.getheader(output.parent / "stars_residual_32bit.fits")["FPAIROLE"], "stars_residual")
        report = json.loads((output.parent / "ai_report.json").read_text())
        self.assertFalse(report["release_approved"])
        self.assertFalse(report["photometry_validated"])
        self.assertEqual(report["source"]["sha256"], source_hash)
        self.assertLess(report["reconstruction_max_error"], 1e-6)

    def test_mono_export_matches_existing_integer_reader_scale(self):
        source = self.root / "mono.fits"
        image = np.array([[1200, 1700], [500, 65535]], np.uint16)
        fits.writeto(source, image, fits.Header({"BUNIT": "ADU"}))
        output = self._file(source, strength=0)
        result = tifffile.imread(output)
        self.assertEqual(result.ndim, 2)
        np.testing.assert_array_equal(result, image.astype(np.float32) / 65535)
        import astro
        np.testing.assert_array_equal(result, astro._read_float(str(source))[..., 0])
        np.testing.assert_array_equal(fits.getdata(output.with_suffix(".fits")), result)
        header = fits.getheader(output.with_suffix(".fits"))
        self.assertEqual((header["BUNIT"], header["FPOUNIT"], header["FPISCALE"]), ("relative", "ADU", 65535))
        self.assertNotIn("BZERO", header)
        self.assertNotIn("BSCALE", header)

    def test_raw_cfa_jpeg_display_tiff_and_nonlinear_fits_are_rejected(self):
        cfa = self.root / "raw.fits"
        fits.writeto(cfa, np.ones((12, 12), np.uint16), fits.Header({"BAYERPAT": "RGGB"}))
        display = self.root / "display.tif"
        tifffile.imwrite(display, np.ones((12, 12), np.float32), description=json.dumps({"forgepix": True, "linear": False}))
        eight_bit = self.root / "display8.tif"
        tifffile.imwrite(eight_bit, np.ones((12, 12), np.uint8))
        nonlinear = self.root / "stretched.fits"
        fits.writeto(nonlinear, np.ones((12, 12), np.float32), fits.Header({"FPLINEAR": False}))
        for source in (cfa, display, eight_bit, nonlinear, self.root / "preview.jpg"):
            with self.assertRaises(ForgePixFehler):
                self._file(source, strength=0)
        self.assertEqual(list(self.root.glob("ai-*")), [])

    def test_cancel_during_export_removes_only_new_partial_files(self):
        source = self.root / "source.fits"
        fits.writeto(source, np.ones((12, 12), np.float32))
        first = self._file(source, strength=0)
        prior = first.read_bytes()
        cancel = threading.Event()
        real_write = tifffile.imwrite
        def cancel_after_write(*args, **kwargs):
            real_write(*args, **kwargs)
            cancel.set()
        with patch.object(ai_restore.tifffile, "imwrite", side_effect=cancel_after_write):
            with self.assertRaisesRegex(ForgePixFehler, "abgebrochen"):
                self._file(source, strength=0, cancel=cancel)
        self.assertEqual(first.read_bytes(), prior)
        self.assertEqual([path.resolve() for path in self.root.glob("ai-*")], [first.parent.resolve()])

    def test_output_integrity_covers_science_layers_and_coverage(self):
        self.manifest["task"] = "starless"
        self._save_manifest()
        source = self.root / "integrity-source.fits"
        fits.writeto(source, np.ones((12, 12), np.float32), fits.Header({"FPCOV": "mask.tif"}))
        tifffile.imwrite(self.root / "mask.tif", np.ones((12, 12), np.uint8))
        output = self._file(source, strength=0)
        report = json.loads((output.parent / "ai_report.json").read_text())
        expected = {"result_32bit.tif", "result_32bit.fits", "stars_residual_32bit.tif",
                    "stars_residual_32bit.fits", "coverage.tif"}
        self.assertEqual({record["name"] for record in report["output_integrity"]}, expected)
        self.assertEqual(set(report["outputs"]), expected)
        for record in report["output_integrity"]:
            actual = (output.parent / record["name"]).read_bytes()
            self.assertEqual(record["bytes"], len(actual))
            self.assertEqual(record["sha256"], hashlib.sha256(actual).hexdigest())
        # The original report exposes an edited TIFF even if its filename stays.
        prior_record = next(record for record in report["output_integrity"] if record["name"] == output.name)
        tifffile.imwrite(output, np.full((12, 12), .7, np.float32))
        self.assertNotEqual(prior_record["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())

    def test_cancellation_during_integrity_check_removes_new_export(self):
        source = self.root / "integrity-cancel.fits"
        fits.writeto(source, np.ones((12, 12), np.float32))
        prior = source.read_bytes()
        cancel = threading.Event()
        real_integrity = ai_restore._file_integrity
        def stop_hashing(path, cancel=None):
            cancel.set()
            return real_integrity(path, cancel)
        with patch.object(ai_restore, "_file_integrity", side_effect=stop_hashing):
            with self.assertRaisesRegex(ForgePixFehler, "abgebrochen"):
                self._file(source, strength=0, cancel=cancel)
        self.assertEqual(source.read_bytes(), prior)
        self.assertEqual(list(self.root.glob("ai-*")), [])

    def test_packaged_denoiser_executes_actual_onnx_graph_when_available(self):
        folder = ai_restore.default_model_dir() / "forgepix-denoise-mono-v2"
        if not (folder / "manifest.json").is_file():
            self.skipTest("packaged denoiser not present")
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest("optional ONNX Runtime not present")
        image = np.linspace(-.01, 1.4, 61 * 93, dtype=np.float32).reshape(61, 93)
        result = ai_restore.restore(image, "forgepix-denoise-mono-v2", allow_experimental=True,
                                    strength=.5, log=lambda *a: None)
        self.assertEqual((result.shape, result.dtype), (image.shape, np.float32))
        self.assertTrue(np.isfinite(result).all())
        self.assertGreater(result.max(), 1.)


if __name__ == "__main__":
    unittest.main()
