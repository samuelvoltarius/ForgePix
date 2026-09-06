"""Device selection and complete-image recovery, without requiring a GPU in CI."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import ai_restore
from constants import ForgePixFehler


CPU, CUDA, DML, COREML = (ai_restore._PROVIDERS[name] for name in ("cpu", "cuda", "directml", "coreml"))


class Session:
    def __init__(self, providers, transform=lambda image: image, fail_at=None, cancel=None):
        self.providers, self.transform, self.fail_at = providers, transform, fail_at
        self.cancel, self.calls, self.fallback_disabled = cancel, 0, False

    def disable_fallback(self):
        self.fallback_disabled = True

    def get_providers(self):
        return self.providers

    def get_inputs(self):
        return [SimpleNamespace(type="tensor(float)", shape=[1, 1, 256, 256], name="input")]

    def get_outputs(self):
        return [SimpleNamespace(type="tensor(float)", shape=[1, 1, 256, 256], name="output")]

    def run(self, outputs, inputs):
        self.calls += 1
        if self.calls == self.fail_at:
            if self.cancel is not None:
                self.cancel.set()
            raise RuntimeError("GPU allocation failed")
        return [self.transform(inputs["input"])]


class Runtime:
    __version__ = "test-runtime"
    ExecutionMode = SimpleNamespace(ORT_SEQUENTIAL="sequential")
    SessionOptions = SimpleNamespace

    def __init__(self, available, behaviors=None):
        self.available, self.behaviors = available, behaviors or {}
        self.created = []

    def get_available_providers(self):
        return self.available

    def InferenceSession(self, content, sess_options, providers):
        provider = providers[0][0]
        self.created.append({"content": content, "options": sess_options, "providers": providers})
        behavior = self.behaviors.get(provider)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior or Session([provider] + ([] if provider == CPU else [CPU]))


class AIDeviceTests(unittest.TestCase):
    def create(self, runtime, device="auto", platform="win32"):
        record, logs = ai_restore._execution_record(device), []
        with patch.dict(sys.modules, {"onnxruntime": runtime}), patch.object(ai_restore.sys, "platform", platform):
            session, _, _ = ai_restore._create_session(b"verified-model-bytes", device=device,
                                                      execution=record, log=logs.append)
        return session, record, logs

    def infer(self, runtime, image, task="denoise", device="auto", cancel=None, progress=None):
        with patch.dict(sys.modules, {"onnxruntime": runtime}), patch.object(ai_restore.sys, "platform", "win32"):
            return ai_restore._infer(image, b"verified-model-bytes", 1, progress, cancel,
                                     task=task, device=device, log=lambda text: None)

    def test_auto_prefers_cuda_and_disables_tf32(self):
        runtime = Runtime([CPU, DML, CUDA])
        session, record, _ = self.create(runtime)
        self.assertEqual(record["provider"], CUDA)
        self.assertEqual(record["provider_options"]["use_tf32"], "0")
        self.assertEqual(runtime.created[0]["content"], b"verified-model-bytes")
        self.assertTrue(session.fallback_disabled)
        self.assertFalse(record["gpu_execution_verified"])
        self.assertFalse(record["fallback_used"])

    def test_cpu_request_never_initializes_available_gpu(self):
        runtime = Runtime([CUDA, DML, CPU])
        _, record, _ = self.create(runtime, "cpu")
        self.assertEqual(record["provider"], CPU)
        self.assertEqual([item["providers"][0][0] for item in runtime.created], [CPU])
        self.assertFalse(record["fallback_used"])

    def test_directml_disables_memory_pattern_and_parallel_execution(self):
        runtime = Runtime([DML, CPU])
        _, record, _ = self.create(runtime)
        self.assertEqual(record["provider"], DML)
        self.assertIs(runtime.created[0]["options"].enable_mem_pattern, False)
        self.assertEqual(runtime.created[0]["options"].execution_mode, "sequential")
        self.assertEqual(record["registered_providers"], [DML, CPU])

    def test_coreml_uses_gpu_and_float32_accumulation_options(self):
        runtime = Runtime([COREML, CPU])
        _, record, _ = self.create(runtime, platform="darwin")
        self.assertEqual(record["provider"], COREML)
        self.assertEqual(record["provider_options"]["MLComputeUnits"], "CPUAndGPU")
        self.assertEqual(record["provider_options"]["AllowLowPrecisionAccumulationOnGPU"], "0")

    def test_missing_gpu_is_explicit_in_record_and_log(self):
        for device in ("auto", "gpu", "cuda", "directml", "coreml"):
            with self.subTest(device=device):
                _, record, logs = self.create(Runtime([CPU]), device)
                self.assertEqual(record["provider"], CPU)
                self.assertEqual(record["requested_device"], device)
                self.assertTrue(record["fallback_used"])
                self.assertEqual(len(record["fallback_reasons"]), 1)
                self.assertTrue(any("CPU" in line for line in logs))

    def test_cuda_initialization_failure_can_select_directml(self):
        runtime = Runtime([CUDA, DML, CPU], {CUDA: RuntimeError("cuDNN DLL missing")})
        _, record, _ = self.create(runtime)
        self.assertEqual(record["provider"], DML)
        self.assertTrue(record["fallback_used"])
        self.assertIn("cuDNN DLL missing", record["fallback_reasons"][0])
        self.assertEqual([item["status"] for item in record["attempts"]], ["initialization_failed", "ready"])

    def test_ort_silent_constructor_fallback_is_not_reported_as_gpu(self):
        runtime = Runtime([DML, CPU], {DML: Session([CPU])})
        _, record, _ = self.create(runtime)
        self.assertEqual(record["provider"], CPU)
        self.assertTrue(record["fallback_used"])
        self.assertEqual(record["attempts"][0]["status"], "initialization_failed")

    def test_failed_later_tile_restarts_all_channels_on_cpu(self):
        image = np.random.default_rng(604).normal(.4, .2, (208, 210, 3)).astype(np.float32)
        # Four tiles/channel: one full channel plus another tile have already
        # completed on GPU when the sixth call fails. They must all be discarded.
        gpu = Session([DML, CPU], lambda tile: tile + 1, fail_at=6)
        cpu = Session([CPU])
        runtime = Runtime([DML, CPU], {DML: gpu, CPU: cpu})
        progress = []
        result, info = self.infer(runtime, image, progress=lambda done, total: progress.append((done, total)))
        np.testing.assert_allclose(result, image, atol=3e-7, rtol=2e-6)
        self.assertEqual((gpu.calls, cpu.calls), (6, 12))
        record = info["execution"]
        self.assertEqual((record["provider"], record["whole_image_restarts"]), (CPU, 1))
        self.assertEqual(record["requested_device"], "auto")
        self.assertTrue(record["applied"])
        self.assertEqual([status["status"] for status in record["attempts"]], ["execution_failed", "ready"])
        self.assertEqual(progress.count((0, 12)), 2)
        self.assertEqual(progress[-1], (12, 12))

    def test_failed_background_channel_restarts_whole_field(self):
        image = np.random.default_rng(44).uniform(.1, 2, (280, 350, 3)).astype(np.float32)
        gpu = Session([DML, CPU], lambda tile: tile + 1, fail_at=2)
        cpu = Session([CPU])
        runtime = Runtime([DML, CPU], {DML: gpu, CPU: cpu})
        result, info = self.infer(runtime, image, task="background")
        np.testing.assert_array_equal(result, image)
        self.assertEqual(cpu.calls, 3)
        self.assertEqual(info["execution"]["whole_image_restarts"], 1)

    def test_cancel_during_provider_failure_never_restarts(self):
        cancel = threading.Event()
        runtime = Runtime([DML, CPU], {DML: Session([DML, CPU], fail_at=2, cancel=cancel)})
        with self.assertRaisesRegex(ForgePixFehler, "abgebrochen"):
            self.infer(runtime, np.ones((210, 220), np.float32), cancel=cancel)
        self.assertEqual(len(runtime.created), 1)

    def test_progress_cancellation_never_restarts(self):
        cancel = threading.Event()
        runtime = Runtime([DML, CPU])
        with self.assertRaisesRegex(ForgePixFehler, "abgebrochen"):
            self.infer(runtime, np.ones((210, 220), np.float32), cancel=cancel,
                       progress=lambda done, total: cancel.set() if done == 1 else None)
        self.assertEqual(len(runtime.created), 1)

    def test_cpu_failure_after_gpu_failure_stops_without_retry_loop(self):
        runtime = Runtime([DML, CPU], {DML: Session([DML, CPU], fail_at=1), CPU: Session([CPU], fail_at=1)})
        with self.assertRaisesRegex(ForgePixFehler, "KI-Inferenz fehlgeschlagen"):
            self.infer(runtime, np.ones((30, 30), np.float32))
        self.assertEqual(len(runtime.created), 2)

    def test_nonfinite_gpu_prediction_is_discarded_before_cpu_retry(self):
        runtime = Runtime([DML, CPU], {DML: Session([DML, CPU], lambda tile: np.full_like(tile, np.nan))})
        image = np.ones((30, 30), np.float32)
        result, info = self.infer(runtime, image)
        np.testing.assert_array_equal(result, image)
        self.assertEqual(info["execution"]["provider"], CPU)

    def test_zero_strength_records_no_inference_or_device_initialization(self):
        with patch.object(ai_restore, "_create_session", side_effect=AssertionError("runtime must stay unloaded")):
            image = np.full((5, 9), -.2, np.float32)
            result, info = ai_restore._infer(image, b"unused", 0, None, None, device="directml")
        np.testing.assert_array_equal(result, image)
        self.assertEqual(info["execution"]["requested_device"], "directml")
        self.assertIsNone(info["execution"]["provider"])
        self.assertFalse(info["execution"]["applied"])

    def test_invalid_device_is_rejected_even_at_zero_strength(self):
        for device in (None, "gpuu", 1, ""):
            with self.subTest(device=device), self.assertRaisesRegex(ForgePixFehler, "Unbekannte KI-Recheneinheit"):
                ai_restore._infer(np.ones((2, 2), np.float32), b"unused", 0, None, None, device=device)

    def test_scientific_file_report_records_actual_cpu_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = root / "models" / "test-model"
            model.mkdir(parents=True)
            content = b"verified-model-bytes"
            (model / "model.onnx").write_bytes(content)
            (model / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "id": "test-model", "task": "denoise", "model_file": "model.onnx",
                "sha256": hashlib.sha256(content).hexdigest(), "channels": 1, "tile_size": 256,
                "halo": 32, "normalization": ai_restore.NORMALIZATION, "output": "complete_target",
                "status": "experimental", "release_approved": False}), encoding="utf-8")
            source = root / "source.fits"
            fits.writeto(source, np.ones((30, 30), np.float32))
            before = source.read_bytes()
            runtime = Runtime([DML, CPU], {DML: Session([DML, CPU], fail_at=1)})
            with patch.dict(sys.modules, {"onnxruntime": runtime}):
                output = Path(ai_restore.run_file(source, "test-model", model_dir=root / "models",
                                                  allow_experimental=True, device="directml", log=lambda text: None))
            report = json.loads((output.parent / "ai_report.json").read_text())
            self.assertEqual(report["execution"]["requested_device"], "directml")
            self.assertEqual(report["execution"]["provider"], CPU)
            self.assertEqual(report["execution"]["whole_image_restarts"], 1)
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(all(item["sha256"] for item in report["output_integrity"]))


if __name__ == "__main__":
    unittest.main()
