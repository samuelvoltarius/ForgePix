"""Pinned recipe execution, file contracts, cancellation and atomic journals."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import numpy as np
import tifffile
from astropy.io import fits
import ai_restore
import recipes


class _IdentitySession:
    def __init__(self, action=None):
        self.action = action

    def run(self, names, inputs):
        if self.action:
            self.action()
        value = inputs["input"]
        assert value.dtype == np.float32 and value.shape == (1, 1, 256, 256)
        return [value.copy()]


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.models = self.root / "models"
        self.models.mkdir()
        for task in recipes.TASKS:
            folder = self.models / task
            folder.mkdir()
            content = ("numeric identity fixture for " + task).encode("ascii")
            (folder / "model.onnx").write_bytes(content)
            manifest = {"schema_version": 1, "id": "test-" + task, "task": task,
                        "model_file": "model.onnx", "sha256": hashlib.sha256(content).hexdigest(),
                        "channels": 1, "tile_size": 256, "halo": 32,
                        "normalization": "affine_percentile_v1", "output": "complete_target",
                        "status": "experimental", "release_approved": False}
            (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.source = self.root / "M27.fits"
        self.pixels = np.linspace(-.02, 2.1, 42 * 48, dtype=np.float32).reshape(42, 48)
        self.header = fits.Header({"OBJECT": "M27", "FILTER": "SV220", "TELESCOP": "RC203",
                                  "BUNIT": "ADU", "FPLINEAR": True, "FPCOV": "coverage.tif",
                                  "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CRPIX1": 24., "CRPIX2": 21.})
        fits.writeto(self.source, self.pixels, self.header)
        tifffile.imwrite(self.root / "coverage.tif", np.ones(self.pixels.shape, np.uint8))
        self.original = self.source.read_bytes()
        self.recipe = {"format": "ForgePixRecipe", "schema_version": 1, "name": "Native test",
                       "steps": [recipes.pin_step("test-" + task, device="cpu", model_dir=self.models)
                                 for task in ("background", "denoise")]}

    def run_recipe(self, recipe=None, source=None, **kwargs):
        return recipes.run_recipe(recipe if recipe is not None else self.recipe, source or self.source,
                                  self.root, model_dir=self.models, allow_experimental=True,
                                  log=lambda *_: None, **kwargs)

    def test_saved_recipe_runs_on_two_inputs_with_independent_journals_and_preserved_metadata(self):
        path = recipes.save_recipe(self.root / "develop.forgepix-recipe.json", self.recipe)
        self.assertEqual(recipes.load_recipe(path), self.recipe)
        second = self.root / "M31.fits"
        fits.writeto(second, self.pixels + .13, fits.Header(dict(self.header, OBJECT="M31")))
        second_original = second.read_bytes()
        callbacks, progress = [], []
        def completed(index, result, record):
            journal = json.loads((Path(result).parent.parent / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(journal["completed_steps"], index)
            self.assertEqual(journal["steps"][index - 1]["status"], "completed")
            self.assertEqual(record["result_path"], result)
            callbacks.append(index)
        with patch.object(ai_restore, "_create_session", return_value=(_IdentitySession(), "input", "output")):
            first = self.run_recipe(path, on_step=completed, progress=lambda *values: progress.append(values))
            repeated = self.run_recipe(path, source=second)
        for report, expected, obj in ((first, self.pixels, "M27"), (repeated, self.pixels + .13, "M31")):
            self.assertEqual(report["status"], "completed", report["error"])
            self.assertEqual(report["completed_steps"], 2)
            self.assertEqual(json.loads(Path(report["journal_path"]).read_bytes()), report)
            self.assertEqual(hashlib.sha256(Path(report["recipe_path"]).read_bytes()).hexdigest(), report["recipe_sha256"])
            self.assertEqual(Path(report["result_path"]).suffix, ".fits")
            np.testing.assert_allclose(fits.getdata(report["result_path"]), expected, atol=5e-7, rtol=1e-6)
            output_header = fits.getheader(Path(report["result_path"]).with_suffix(".fits"))
            for key in ("FILTER", "TELESCOP", "BUNIT", "CTYPE1", "CTYPE2", "CRPIX1", "CRPIX2"):
                self.assertEqual(output_header[key], self.header[key])
            self.assertEqual(output_header["OBJECT"], obj)
            self.assertEqual(output_header["FPCOV"], "coverage.tif")
            self.assertFalse(report["release_approved"])
            self.assertEqual(report["steps"][1]["source_path"], report["steps"][0]["result_path"])
            self.assertEqual(report["steps"][0]["source_path"], report["input_snapshot"]["path"])
            for step in report["steps"]:
                self.assertEqual(step["files"][0]["path"], step["result_path"])
                for item in step["files"]:
                    self.assertEqual(hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest(), item["sha256"])
        self.assertNotEqual(first["run_dir"], repeated["run_dir"])
        self.assertNotEqual(first["input"]["sha256"], repeated["input"]["sha256"])
        self.assertEqual(callbacks, [1, 2])
        self.assertEqual({values[0] for values in progress}, {1, 2})
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(second.read_bytes(), second_original)

    def test_all_four_allowed_tasks_keep_signed_starless_companions(self):
        self.recipe["steps"] = [recipes.pin_step("test-" + task, device="cpu", model_dir=self.models)
                                for task in recipes.TASKS]
        with patch.object(ai_restore, "_create_session", return_value=(_IdentitySession(), "input", "output")):
            report = self.run_recipe()
        self.assertEqual(report["status"], "completed", report["error"])
        self.assertEqual(report["completed_steps"], 4)
        folder = Path(report["result_path"]).parent
        residual = tifffile.imread(folder / "stars_residual_32bit.tif")
        previous = fits.getdata(report["steps"][-1]["source_path"])
        np.testing.assert_allclose(fits.getdata(report["result_path"]).astype(np.float64) + residual,
                                   previous, atol=2e-7)
        self.assertEqual(fits.getheader(folder / "stars_residual_32bit.fits")["FPCHTYPE"], "RESIDUAL")
        self.assertEqual(len(report["steps"][-1]["files"]), 6)  # TIFF/FITS result + residual, mask, report.

    def test_invalid_recipe_model_hash_or_task_is_rejected_before_any_run_output(self):
        bad = []
        for patch_value in ({"model_sha256": "0" * 64}, {"task": "starless"}, {"strength": True},
                            {"strength": float("nan")}, {"strength": 10 ** 400}, {"device": "remote"},
                            {"task": "python"}, {"model_id": "../model"}, {"command": "run code"}):
            candidate = deepcopy(self.recipe)
            candidate["steps"][1].update(patch_value)
            bad.append(candidate)
        bad += [dict(self.recipe, script="print('unexpected')"), dict(self.recipe, schema_version=True),
                dict(self.recipe, steps=[])]
        with patch.object(ai_restore, "run_file", side_effect=AssertionError("Inference started")):
            for candidate in bad:
                with self.subTest(candidate=candidate), self.assertRaises(recipes.RecipeError):
                    self.run_recipe(candidate)
        self.assertEqual(list(self.root.glob("stack-recipe-*")), [])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_explicit_opt_in_and_linear_covered_input_are_required_before_outputs(self):
        with self.assertRaisesRegex(recipes.RecipeError, "experimentell"):
            recipes.run_recipe(self.recipe, self.source, self.root, model_dir=self.models)
        for update, partial in (({"BAYERPAT": "RGGB"}, False), ({"FPLINEAR": False}, False), ({}, True)):
            with self.subTest(update=update, partial=partial):
                fits.writeto(self.source, self.pixels, fits.Header(dict(self.header, **update)), overwrite=True)
                mask = np.ones(self.pixels.shape, np.uint8)
                if partial:
                    mask[0, 0] = 0
                tifffile.imwrite(self.root / "coverage.tif", mask)
                with self.assertRaises(recipes.RecipeError):
                    self.run_recipe()
        self.assertEqual(list(self.root.glob("stack-recipe-*")), [])

    def test_cancel_before_start_creates_no_run_or_outputs(self):
        cancel = threading.Event()
        cancel.set()
        report = self.run_recipe(cancel=cancel)
        self.assertEqual(report["status"], "cancelled")
        self.assertIsNone(report["journal_path"])
        self.assertIsNone(report["result_path"])
        self.assertEqual(list(self.root.glob("stack-recipe-*")), [])

    def test_cancellation_during_second_model_preserves_first_step_and_originals(self):
        cancel = threading.Event()
        sessions = iter([_IdentitySession(), _IdentitySession(cancel.set)])
        with patch.object(ai_restore, "_create_session", side_effect=lambda *a, **k: (next(sessions), "input", "output")):
            report = self.run_recipe(cancel=cancel)
        self.assertEqual(report["status"], "cancelled", report["error"])
        self.assertEqual(report["completed_steps"], 1)
        self.assertEqual([step["status"] for step in report["steps"]], ["completed", "cancelled"])
        self.assertEqual(report["result_path"], report["steps"][0]["result_path"])
        self.assertTrue(Path(report["result_path"]).is_file())
        self.assertEqual(json.loads(Path(report["journal_path"]).read_bytes()), report)
        self.assertEqual(len(list(Path(report["run_dir"]).glob("ai-*"))), 1)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_changed_model_between_steps_fails_without_losing_completed_result(self):
        def changed(index, result, record):
            if index == 1:
                (self.models / "denoise/model.onnx").write_bytes(b"changed local model")
        with patch.object(ai_restore, "_create_session", return_value=(_IdentitySession(), "input", "output")):
            report = self.run_recipe(on_step=changed)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["completed_steps"], 1)
        self.assertTrue(Path(report["result_path"]).is_file())
        self.assertIn("Prüfsumme", report["error"])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_snapshot_and_canonical_recipe_isolate_later_external_input_changes(self):
        recipe = deepcopy(self.recipe)
        canonical = recipes.validate_recipe(recipe)
        def changed(index, result, record):
            if index == 1:
                fits.writeto(self.source, self.pixels + 100, self.header, overwrite=True)
                recipe["steps"][1]["model_id"] = "changed-outside-run"
                record["status"] = "corrupted callback copy"
        with patch.object(ai_restore, "_create_session", return_value=(_IdentitySession(), "input", "output")):
            report = self.run_recipe(recipe, on_step=changed)
        self.assertEqual(report["status"], "completed", report["error"])
        self.assertEqual(Path(report["input_snapshot"]["path"]).read_bytes(), self.original)
        self.assertEqual(recipes.load_recipe(report["recipe_path"]), canonical)
        np.testing.assert_allclose(fits.getdata(report["result_path"]), self.pixels, atol=5e-7, rtol=1e-6)
        self.assertEqual(report["steps"][0]["status"], "completed")

    def test_project_callback_failure_is_reported_with_completed_scientific_files_retained(self):
        def fail(index, result, record):
            raise OSError("project archive unavailable")
        with patch.object(ai_restore, "_create_session", return_value=(_IdentitySession(), "input", "output")):
            report = self.run_recipe(on_step=fail)
        self.assertEqual(report["status"], "failed")
        self.assertIn("project archive unavailable", report["error"])
        self.assertEqual(report["steps"][0]["callback_status"], "failed")
        self.assertEqual(report["steps"][0]["status"], "completed")
        self.assertEqual(report["steps"][1]["status"], "pending")
        self.assertTrue(Path(report["result_path"]).is_file())
        self.assertEqual(json.loads(Path(report["journal_path"]).read_bytes()), report)

    def test_corrupted_new_companion_is_never_recorded_as_completed(self):
        original_run = ai_restore.run_file
        def corrupt(*args, **kwargs):
            result = original_run(*args, **kwargs)
            (Path(result).parent / "coverage.tif").write_bytes(b"modified mask")
            return result
        with patch.object(ai_restore, "_create_session", return_value=(_IdentitySession(), "input", "output")), \
                patch.object(ai_restore, "run_file", side_effect=corrupt):
            report = self.run_recipe()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["completed_steps"], 0)
        self.assertIsNone(report["result_path"])
        self.assertEqual(report["steps"][0]["status"], "failed")

    def test_failed_atomic_recipe_and_journal_write_retain_previous_bytes(self):
        path = recipes.save_recipe(self.root / "recipe.json", self.recipe)
        previous = path.read_bytes()
        with patch("recipes.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(recipes.RecipeError):
                recipes.save_recipe(path, dict(self.recipe, name="Changed"))
        self.assertEqual(path.read_bytes(), previous)
        journal = self.root / "run.json"
        recipes._atomic_json(journal, {"status": "running", "completed_steps": 1})
        original = journal.read_bytes()
        with patch("recipes.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                recipes._atomic_json(journal, {"status": "completed", "completed_steps": 2})
        self.assertEqual(journal.read_bytes(), original)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_duplicate_json_keys_are_rejected(self):
        path = self.root / "ambiguous.json"
        path.write_text('{"format":"ForgePixRecipe","format":"other"}', encoding="utf-8")
        with self.assertRaisesRegex(recipes.RecipeError, "doppelt"):
            recipes.load_recipe(path)

    def test_packaged_onnx_model_executes_a_real_recipe_when_runtime_is_available(self):
        if importlib.util.find_spec("onnxruntime") is None:
            self.skipTest("ONNX Runtime is unavailable")
        manifests = ai_restore.default_model_dir().glob("*/manifest.json")
        candidate = next((json.loads(path.read_text(encoding="utf-8")) for path in manifests
                          if path.parent.name == "forgepix-denoise-mono-v2"), None)
        if candidate is None:
            self.skipTest("Bundled denoise model is unavailable")
        recipe = dict(self.recipe, steps=[recipes.pin_step(candidate["id"], device="cpu")])
        report = recipes.run_recipe(recipe, self.source, self.root, allow_experimental=True, log=lambda *_: None)
        self.assertEqual(report["status"], "completed", report["error"])
        self.assertEqual(report["steps"][0]["execution"]["provider"], "CPUExecutionProvider")
        self.assertEqual(report["steps"][0]["execution"]["applied"], True)
        self.assertTrue(np.isfinite(fits.getdata(report["result_path"])).all())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(fits.getheader(Path(report["result_path"]).with_suffix(".fits"))["FILTER"], "SV220")


if __name__ == "__main__":
    unittest.main()
