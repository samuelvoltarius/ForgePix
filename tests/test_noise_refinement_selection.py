"""Final decisions require unchanged provenance and every preregistered gate."""
from copy import deepcopy
import unittest

from training.evaluate_noise_refinement import selection


class NoiseRefinementSelection(unittest.TestCase):
    def fixtures(self):
        training = dict(reserved_final_seed=1234, reserved_final_scenes=128,
            final_evaluator_source_sha256="evaluator", parent_checkpoint_sha256="parent",
            best_research_candidate_sha256="candidate", training_source_sha256="training",
            scene_generator_source_sha256="generator", device={"type": "cuda"}, provenance={},
            candidate_gates={"passes_all_groups": True, "failures": []}, limitations="Research only")
        metrics = {name: {"mean": .01, "mean_absolute": .01} for name in
            ("mse", "mean_bias", "stellar_aperture_flux_absolute_error_fraction", "faint_structure_mse")}
        models = {"parent": deepcopy(metrics), "candidate": deepcopy(metrics)}
        report = dict(holdout_seed=1234, scene_count=128, evaluator_sha256="evaluator",
            models={"parent": {"sha256": "parent"}, "candidate": {"sha256": "candidate"}},
            overall=deepcopy(models), by_group={"noise_class": {"correlated": {"models": deepcopy(models)}}},
            comparison={}, suite_sha256="suite")
        return training, report

    def test_limited_pass_never_approves_or_deploys(self):
        training, report = self.fixtures()
        result = selection(training, report)
        self.assertTrue(result["final_pass"])
        self.assertFalse(result["release_approved"])
        self.assertFalse(result["bundled_weights_changed"])

    def test_group_regression_rejected_even_if_overall_error_improves(self):
        training, report = self.fixtures()
        report["overall"]["candidate"]["mse"]["mean"] = .001
        report["by_group"]["noise_class"]["correlated"]["models"]["candidate"]["mse"]["mean"] = .011
        result = selection(training, report)
        self.assertEqual(result["decision"], "reject_refinement")
        self.assertEqual(result["final_failures"][0]["group"], "correlated")

    def test_development_failure_cannot_be_overridden_by_final_pass(self):
        training, report = self.fixtures()
        training["candidate_gates"] = {"passes_all_groups": False, "failures": [{}]}
        self.assertEqual(selection(training, report)["decision"], "reject_refinement")

    def test_missing_preservation_measurement_cannot_pass(self):
        training, report = self.fixtures()
        report["overall"]["candidate"]["faint_structure_mse"]["mean"] = None
        self.assertEqual(selection(training, report)["decision"], "reject_refinement")

    def test_changed_seed_evaluator_or_checkpoint_rejected(self):
        training, report = self.fixtures()
        for field, value in [("holdout_seed", 12), ("scene_count", 64), ("evaluator_sha256", "other")]:
            altered = dict(report, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                selection(training, altered)
        report["models"]["parent"]["sha256"] = "different"
        with self.assertRaises(ValueError):
            selection(training, report)


if __name__ == "__main__":
    unittest.main()
