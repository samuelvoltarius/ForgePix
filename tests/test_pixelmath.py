import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from pixelmath import evaluate


class PixelMathTests(unittest.TestCase):
    def test_narrowband_mix_preserves_inputs_and_range(self):
        ha = np.full((8, 9), 2, np.float32)
        oxygen = np.full_like(ha, .4)
        result = evaluate("0.8 * Ha + 0.2 * OIII", {"Ha": ha, "OIII": oxygen})
        np.testing.assert_allclose(result, 1.68)
        np.testing.assert_array_equal(ha, 2)
        self.assertFalse(np.shares_memory(result, ha))

    def test_mask_and_constant(self):
        image = np.array([[.1, .8]], np.float32)
        np.testing.assert_allclose(evaluate("where(A > 0.5, A, 0)", {"A": image}), [[0, .8]])
        np.testing.assert_allclose(evaluate("0.25", {"A": image}), [[.25, .25]])

    def test_rejects_python_execution_and_nonfinite_math(self):
        for expression in ["__import__('os')", "A.__class__", "A[0]", "A / 0", "sqrt(-1)", "unknown(A)"]:
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                evaluate(expression, {"A": np.ones((2, 2))})

    def test_rejects_mismatched_images(self):
        with self.assertRaises(ValueError):
            evaluate("A+B", {"A": np.ones((2, 2)), "B": np.ones((3, 2))})
