"""Scientific degradation and non-regression gates for optional CUDA training."""
import unittest

try:
    import torch
    from training.refine_noise_groups import add_noise, gate_comparison, GROUPS, METRICS
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "PyTorch is optional; this test runs in the Spark training environment")
class NoiseGroupTraining(unittest.TestCase):
    def test_identity_preserves_signed_hdr_values_without_aliasing(self):
        clean = torch.linspace(-.1, 1.8, 256*256).reshape(1, 1, 256, 256)
        actual = add_noise(clean, torch.Generator().manual_seed(8), "identity")
        self.assertTrue(torch.equal(actual, clean))
        self.assertNotEqual(actual.data_ptr(), clean.data_ptr())

    def test_noise_is_seeded_finite_and_spatial_scale_changes_correlation(self):
        clean = torch.full((4, 1, 256, 256), .03)
        correlations = {}
        for group in GROUPS:
            first = add_noise(clean, torch.Generator().manual_seed(17), group)
            second = add_noise(clean, torch.Generator().manual_seed(17), group)
            self.assertTrue(torch.equal(first, second), group)
            self.assertTrue(torch.isfinite(first).all(), group)
            residual = first-clean
            if group.startswith("correlated_"):
                correlations[group] = float((residual[:,:,:,:-1]*residual[:,:,:,1:]).mean()/residual.square().mean())
        self.assertGreater(correlations["correlated_large"], correlations["correlated_small"])

    def test_a_better_mean_cannot_hide_a_single_group_regression(self):
        parent = {group: dict.fromkeys(METRICS, .01) for group in GROUPS}
        candidate = {group: dict.fromkeys(METRICS, .001) for group in GROUPS}
        candidate["identity"]["absolute_image_bias"] = .011
        decision = gate_comparison(candidate, parent)
        self.assertLess(decision["geometric_group_mse_ratio"], 1)
        self.assertFalse(decision["passes_all_groups"])
        self.assertEqual([(row["group"], row["metric"]) for row in decision["failures"]],
                         [("identity", "absolute_image_bias")])
        self.assertTrue(gate_comparison(parent, parent)["passes_all_groups"])


if __name__ == "__main__":
    unittest.main()
