import json
import sys
import tempfile
from pathlib import Path
import unittest
import numpy as np
import tifffile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import astro
import star_layers
from constants import ForgePixFehler


class StarLayers(unittest.TestCase):
    def test_float_background_kept_and_additive_roundtrip(self):
        yy, xx = np.mgrid[:80, :80]
        background = (.0012345 + xx * .0000017).astype(np.float32)
        source = np.repeat(background[..., None], 3, axis=-1)
        source += (.45 * np.exp(-((xx - 40)**2 + (yy - 40)**2)/5))[..., None].astype(np.float32)
        original = source.copy()
        nebula, stars, mask = star_layers.split(source, log=lambda *a: None)
        np.testing.assert_array_equal(source, original)
        np.testing.assert_allclose(star_layers.combine(nebula, stars), source, atol=3e-8)
        np.testing.assert_array_equal(nebula[mask == 0], source[mask == 0])
        self.assertLess(float(nebula[40, 40, 0]), float(source[40, 40, 0]) / 2)
        self.assertGreater(float(nebula[40, 40, 0]), .0005)

    def test_signed_layers_and_scaling(self):
        n = np.full((8, 8, 3), .03, np.float32)
        s = np.full_like(n, -.002)
        np.testing.assert_allclose(star_layers.combine(n, s), .028)
        np.testing.assert_array_equal(star_layers.combine(n, s, star_amt=0), n)
        with self.assertRaises(ForgePixFehler):
            star_layers.combine(n, s, star_amt=float('nan'))

    def test_native_files_and_repeated_mix_preserve_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.tif'
            data = np.full((32, 32, 3), .012345, np.float32)
            tifffile.imwrite(source, data, photometric='rgb')
            original = source.read_bytes()
            preview = Path(star_layers.run(source, log=lambda *a: None))
            work = preview.parent.parent
            self.assertLess(json.loads((work/'layers.json').read_text())['reconstruction_max_error'], 1e-7)
            second = Path(star_layers.recombine(work, star_amt=.5))
            self.assertNotEqual(preview, second)
            self.assertTrue(preview.exists())
            np.testing.assert_allclose(tifffile.imread(preview.parent/'combined_32bit.tif'), data, atol=1e-8)
            self.assertEqual(original, source.read_bytes())
