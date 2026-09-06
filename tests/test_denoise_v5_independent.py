"""Independent numerical checks for the single-variable V5 experiment.

The CUDA check runs real V4 sampling and real NAFNet forwards, without training,
downloads, final/development scenes, or checkpoint selection. Run on the Spark
before the one bounded training run; a local Torch/CUDA skip is not GPU evidence.
"""
import hashlib
import importlib.util
import json
import random
import unittest
from copy import deepcopy

import numpy as np
from training import evaluate_denoise_v5 as selector

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None
if TORCH_AVAILABLE:
    import torch
    from training import refine_denoise_v4 as v4
    from training import refine_denoise_v5 as v5
else:
    torch = v4 = v5 = None


def independently_digest_batch(inp, target):
    sha = hashlib.sha256()
    for tensor in (inp, target):
        array = np.ascontiguousarray(tensor.detach().cpu().numpy())
        sha.update(str(array.dtype).encode("ascii"))
        sha.update(json.dumps(list(array.shape), separators=(",", ":")).encode("ascii"))
        sha.update(array.tobytes(order="C"))
    return sha.hexdigest()


class PreservationGateIndependentTests(unittest.TestCase):
    @staticmethod
    def metrics(error):
        error = np.asarray(error, np.float64)
        local = error.reshape(2, 16, 2, 16).mean((1, 3))
        return dict(mse=float(np.square(error).mean()), mae=float(np.abs(error).mean()),
                    absolute_image_bias=float(abs(error.mean())),
                    local_mean_rms=float(np.sqrt(np.square(local).mean())), scenes=16)

    def test_reduced_mse_cannot_hide_larger_pixel_mae_in_one_actual_group(self):
        sparse_error = np.zeros((32, 32))
        sparse_error.flat[::64] = .4
        diffuse_error = np.tile([-.01, .01], (32, 16))
        baseline, candidate = self.metrics(sparse_error), self.metrics(diffuse_error)
        self.assertLess(candidate["mse"], baseline["mse"])
        self.assertGreater(candidate["mae"], baseline["mae"])
        names = [f"{domain}/{noise}" for domain in ("synthetic", "M13", "M16")
                 for noise in ("identity", "low_noise", "read_dominated", "shot_dominated",
                               "correlated_small", "correlated_medium", "correlated_large",
                               "row_noise", "original_replay")]
        report = dict(development_selected_step=1000, development_group_count=27,
                      development_scenes_per_group=16,
                      parent_validation={name: dict(baseline) for name in names},
                      eligible_validation={name: dict(baseline) for name in names})
        self.assertTrue(selector.development_eligible(report))
        report["eligible_validation"]["M16/correlated_large"] = candidate
        with self.assertRaises(ValueError):
            selector.development_eligible(report)

    def test_lower_pixel_noise_cannot_hide_opposing_aperture_flux_biases(self):
        # Equal-area star-aperture errors have opposite signs: the global mean
        # cancels exactly while each independent aperture is photometrically bad.
        parent_error = np.tile([-.1, .1], (32, 16))
        candidate_error = np.full((32, 32), .02)
        candidate_error[16:] *= -1
        self.assertEqual(float(candidate_error.mean()), 0.)
        self.assertLess(float(np.square(candidate_error).mean()), float(np.square(parent_error).mean()))

        def measured(error):
            aperture_errors = [float(error[:16].sum()) / 100., float(error[16:].sum()) / 100.]
            return {"mse": {"mean": float(np.square(error).mean())},
                    "mean_bias": {"mean": float(error.mean()), "mean_absolute": float(abs(error.mean()))},
                    "faint_structure_mse": {"mean": float(np.square(error).mean())},
                    "stellar_aperture_flux_absolute_error_fraction": {"mean": float(np.abs(aperture_errors).mean())}}

        models = dict(parent=measured(parent_error), candidate=measured(candidate_error))
        evaluation = dict(overall=models, by_group={"noise_class": {
            name: {"models": deepcopy(models)} for name in
            ("low_noise", "read_dominated", "shot_dominated", "correlated")}})
        failures = selector.final_failures(evaluation)
        self.assertEqual([row["metric"] for row in failures], ["stellar_aperture_flux_absolute_error_fraction"])


@unittest.skipUnless(TORCH_AVAILABLE, "Training-only PyTorch dependency is absent")
class LossIndependentTests(unittest.TestCase):
    def test_added_mae_value_and_gradient_with_signed_hdr_errors(self):
        # Distinct signs, zeros and HDR levels exercise the actual derivative,
        # rather than only a metadata assertion about the name of a loss term.
        target = torch.linspace(-.4, 2.7, 2 * 32 * 32).reshape(2, 1, 32, 32)
        perturbation = torch.tensor([-.3, 0., .1, .45]).repeat(512).reshape_as(target)
        reference = target + .02
        coefficient = .037
        for replay in (False, True):
            with self.subTest(replay=replay):
                predicted = (target + perturbation).requires_grad_()
                base = v4.preservation_loss(predicted, target, reference, replay=replay)
                actual = v5.loss_v5(predicted, target, reference, coefficient, replay=replay)
                expected_increment = coefficient * perturbation.abs().mean()
                torch.testing.assert_close(actual - base, expected_increment, rtol=1e-5, atol=1e-7)
                gradient = torch.autograd.grad(actual - base, predicted)[0]
                expected_gradient = coefficient * perturbation.sign() / perturbation.numel()
                torch.testing.assert_close(gradient, expected_gradient, rtol=1e-5, atol=1e-9)

    def test_zero_coefficient_is_exactly_v4_and_perfect_target_has_zero_loss(self):
        target = torch.linspace(-1., 3., 32 * 32).reshape(1, 1, 32, 32)
        predicted = target + .01 * target.square()
        reference = target - .03
        for replay in (False, True):
            with self.subTest(replay=replay):
                self.assertTrue(torch.equal(
                    v5.loss_v5(predicted, target, reference, 0., replay=replay),
                    v4.preservation_loss(predicted, target, reference, replay=replay)))
                self.assertEqual(float(v5.loss_v5(target, target, target, .037, replay=replay)), 0.)


@unittest.skipUnless(TORCH_AVAILABLE and torch.cuda.is_available(), "Real CUDA generator/model check requires Spark")
class CalibrationIndependentTests(unittest.TestCase):
    def test_real_96_batches_preserve_rng_model_and_original_v4_sequence(self):
        torch.set_num_threads(4)
        torch.manual_seed(v4.TRAIN_SEED)
        generator = torch.Generator(device="cuda").manual_seed(v4.TRAIN_SEED)
        initial = v4.NAFNet(**v4.CONFIG)
        model = v4.MeanAnchoredDenoiser(initial.state_dict()).cuda()
        del initial
        model.train()
        model.parent.eval()
        # Analytic, finite training-bank fixture: no observed data or holdout is
        # needed to prove that bank sampling consumes the same original RNG.
        axis = torch.linspace(-1., 1., 256, device="cuda")
        yy, xx = torch.meshgrid(axis, axis, indexing="ij")
        bank = torch.stack([.03 * (xx + .1 * i).square() + .012 * torch.cos(yy * (i + 1))
                            for i in range(8)])[:, None]
        bank_before = bank.clone()
        generator_before = generator.get_state().clone()
        cpu_before = torch.get_rng_state().clone()
        cuda_before = [state.clone() for state in torch.cuda.get_rng_state_all()]
        numpy_before = np.random.get_state()
        python_before = random.getstate()
        weights_before = {name: value.detach().clone() for name, value in model.state_dict().items()}
        modes_before = {name: module.training for name, module in model.named_modules()}

        calibrated = v5.calibrate_mae(model, generator, bank)

        self.assertTrue(torch.equal(generator.get_state(), generator_before))
        self.assertTrue(torch.equal(torch.get_rng_state(), cpu_before))
        self.assertEqual(len(torch.cuda.get_rng_state_all()), len(cuda_before))
        for actual, expected in zip(torch.cuda.get_rng_state_all(), cuda_before):
            self.assertTrue(torch.equal(actual, expected))
        numpy_after = np.random.get_state()
        self.assertEqual(numpy_after[0], numpy_before[0])
        np.testing.assert_array_equal(numpy_after[1], numpy_before[1])
        self.assertEqual(numpy_after[2:], numpy_before[2:])
        self.assertEqual(random.getstate(), python_before)
        self.assertEqual({name: module.training for name, module in model.named_modules()}, modes_before)
        for name, value in model.state_dict().items():
            self.assertTrue(torch.equal(value, weights_before[name]), name)
        self.assertTrue(torch.equal(bank, bank_before))
        self.assertTrue(all(parameter.grad is None for parameter in model.parameters()))

        # Reconstruct the V4 loop INLINE, independently of V5.training_batch.
        # Measure losses again, so lambda cannot be justified by self-reported
        # medians or by matching only the batch-count metadata.
        measured_l4, measured_mae, expected_hashes, expected_groups = [], [], [], []
        with torch.no_grad():
            for step in range(1, 97):
                group = v4.SCHEDULE[(step - 1) % len(v4.SCHEDULE)]
                if group == "original_replay":
                    inp, target = v4.sample(4, "cuda", generator, "denoise", bank)
                else:
                    target = v4.clean_batch(4, generator, bank)
                    inp = v4.add_noise(target, generator, group)
                expected_groups.append(group)
                expected_hashes.append(independently_digest_batch(inp, target))
                x, y, _, _ = v4.normalize(inp, target)
                prediction, reference = model(x, return_reference=True)
                measured_l4.append(float(v4.preservation_loss(prediction, y, reference, replay=group == "original_replay")))
                measured_mae.append(float((prediction - y).abs().mean()))

        self.assertEqual(calibrated["calibration_batches"], 96)
        self.assertEqual(calibrated["batch_groups"], expected_groups)
        self.assertEqual(calibrated["batch_hashes"], expected_hashes)
        self.assertEqual(expected_groups.count("original_replay"), 48)
        self.assertGreater(len(set(expected_hashes)), 90)
        median_l4 = float(np.median(measured_l4))
        median_mae = float(np.median(measured_mae))
        self.assertGreater(median_l4, 0.)
        self.assertGreater(median_mae, 0.)
        self.assertAlmostEqual(calibrated["median_l4"], median_l4, delta=1e-12)
        self.assertAlmostEqual(calibrated["median_pixel_mae"], median_mae, delta=1e-12)
        self.assertAlmostEqual(calibrated["lambda_mae"], .1 * median_l4 / median_mae, delta=1e-12)

        # V5's actual batch helper must reproduce every batch as well; testing
        # calibration against only itself would miss a changed training loop.
        generator.set_state(generator_before)
        for step, expected in enumerate(expected_hashes, 1):
            group, inp, target = v5.training_batch(step, generator, bank)
            self.assertEqual(group, expected_groups[step - 1])
            self.assertEqual(independently_digest_batch(inp, target), expected, f"Original batch {step} changed")

    def test_forward_failure_restores_all_random_streams_and_modes(self):
        torch.manual_seed(v4.TRAIN_SEED)
        original = v4.NAFNet(**v4.CONFIG)
        model = v4.MeanAnchoredDenoiser(original.state_dict()).cuda()
        del original
        model.train()
        model.parent.eval()
        generator = torch.Generator(device="cuda").manual_seed(v4.TRAIN_SEED)
        before = (generator.get_state().clone(), torch.get_rng_state().clone(),
                  [x.clone() for x in torch.cuda.get_rng_state_all()],
                  np.random.get_state(), random.getstate(),
                  [module.training for module in model.modules()])

        def fail_after_real_forward(module, args, result):
            torch.rand(3)
            torch.rand(3, device="cuda")
            np.random.random(3)
            random.random()
            raise RuntimeError("Injected failure after real NAFNet forward")

        hook = model.register_forward_hook(fail_after_real_forward)
        try:
            with self.assertRaisesRegex(RuntimeError, "Injected failure"):
                v5.calibrate_mae(model, generator, None)
        finally:
            hook.remove()
        self.assertTrue(torch.equal(generator.get_state(), before[0]))
        self.assertTrue(torch.equal(torch.get_rng_state(), before[1]))
        for actual, expected in zip(torch.cuda.get_rng_state_all(), before[2]):
            self.assertTrue(torch.equal(actual, expected))
        after_numpy = np.random.get_state()
        self.assertEqual(after_numpy[0], before[3][0])
        np.testing.assert_array_equal(after_numpy[1], before[3][1])
        self.assertEqual(after_numpy[2:], before[3][2:])
        self.assertEqual(random.getstate(), before[4])
        self.assertEqual([module.training for module in model.modules()], before[5])


if __name__ == "__main__":
    unittest.main()
