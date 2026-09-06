"""Native integration/export contracts for actual contributors and science hints."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from astropy.io import fits
import tifffile

sys.path[:0] = [str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parents[1] / "core")]
import astro
import focus_cull_stack as pipeline
from project_store import Project
from ui.astrometry_dialog import header_hints


class StackObservationExport(unittest.TestCase):
    def test_actual_contributors_reference_time_coverage_and_project_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = root / "inputs"
            inputs.mkdir()
            original = {}
            image = np.linspace(-.02, 1.3, 24 * 32, dtype=np.float32).reshape(24, 32)
            for index in range(3):
                header = fits.Header({"FPLINEAR": True, "IMAGETYP": "LIGHT",
                    "OBJECT": "test" if index < 2 else "different", "FILTER": "L",
                    "EXPTIME": 100 if index < 2 else 1000, "GAIN": 131, "EGAIN": .88,
                    "SATURATE": 65535, "BUNIT": "adu", "RA": 101. + index, "DEC": 20.,
                    "FOCALLEN": 1000., "XPIXSZ": 5., "YPIXSZ": 5.,
                    "XBINNING": 1, "YBINNING": 1, "DATE-BEG": f"2025-01-01T00:00:{10 * index:02d}",
                    "CRPIX1": 16., "CRVAL1": 999., "CTYPE1": "RA---TAN"})
                path = inputs / f"light{index}.fit"
                fits.writeto(path, image, header)
                original[path] = path.read_bytes()
            args = SimpleNamespace(prefix="", fits_out=True, astro_stretch=False,
                astro_method="average", astro_kappa=2.5, no_register=True,
                no_astro_qc=True, no_auto_calib=True, astro_bin=2)

            def register(paths, reg_dir, *args, **kwargs):
                Path(reg_dir).mkdir(parents=True)
                aligned = []
                for index in (0, 1):  # Third frame failed registration.
                    path = str(Path(reg_dir) / f"reg_{index:04d}.tif")
                    astro._warp_and_save(astro._read_float(paths[index]), None, (32, 24), path, 1)
                    mask = np.ones((24, 32), np.uint8)
                    mask[0, 0] = 0
                    tifffile.imwrite(path + ".coverage.tif", mask, metadata=None)
                    aligned.append(path)
                return aligned

            with patch.object(astro, "register_and_cache", side_effect=register):
                output = Path(pipeline.run_astro(str(inputs), str(root / "work"), args))
            source = next(output.glob("*_astro_linear.fits"))
            header = fits.getheader(source)
            self.assertEqual(header["NCOMBINE"], 2)
            self.assertEqual(header["FPTOTEXP"], 200)
            self.assertEqual(header["EXPTIME"], 100)
            self.assertEqual(header["FILTER"], "L")
            self.assertEqual(header["OBJECT"], "test")
            self.assertEqual(header["RA"], 102.)  # Actual middle-frame reference.
            self.assertTrue(header["DATE-AVG"].startswith("2025-01-01T00:00:55"))
            self.assertFalse(header["FPETEXAC"])
            self.assertTrue(header["FPLINEAR"])
            for absent in ("DATE-OBS", "GAIN", "EGAIN", "SATURATE", "BUNIT", "CRPIX1", "CTYPE1", "XBINNING", "XPIXSZ"):
                self.assertNotIn(absent, header)
            hints = header_hints(source)
            self.assertEqual(hints["ra"], 102.)
            self.assertAlmostEqual(hints["pixelscale_arcsec"], np.degrees(np.arctan(5 / 1e6)) * 3600 * 2)
            coverage = tifffile.imread(output / header["FPCOV"])
            self.assertEqual(coverage.shape, (12, 16))
            self.assertFalse(coverage[0, 0])  # A partly sampled binned pixel is excluded.
            self.assertEqual(np.count_nonzero(~coverage.astype(bool)), 1)
            tiff = next(output.glob("*_astro_linear_32bit.tif"))
            np.testing.assert_array_equal(tifffile.imread(tiff), np.moveaxis(fits.getdata(source), 0, -1))
            with tifffile.TiffFile(tiff) as file:
                tiff_header = fits.Header.fromstring(json.loads(file.pages[0].description)["fits_header"], sep="\n")
            for key in ("DATE-AVG", "MJD-AVG", "FPMHASH", "PIXSCALE", "FPCOV"):
                self.assertEqual(header[key], tiff_header[key])
            observation = json.loads((output / "observation_report.json").read_text(encoding="utf-8"))
            self.assertEqual(len(observation["sources"]), 2)
            self.assertEqual(observation["reference"]["path"], str(inputs / "light1.fit"))
            self.assertFalse(observation["pixel_gain_saturation_variance_qualified"])
            self.assertFalse(observation["timing"]["per_pixel_weighting_verified"])
            project = Project.create(root / "Stack.forgepix", "Stack", {})
            step = project.add_result(source, inputs / "light0.fit")
            export = Path(project.export_step(step, root / "Export"))
            for path in (source, output / "coverage.tif", output / "observation_report.json"):
                self.assertEqual((export / path.name).read_bytes(), path.read_bytes())
            for path, content in original.items():
                self.assertEqual(path.read_bytes(), content)

    def test_unknown_inputs_do_not_invent_linearity_or_time(self):
        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(prefix="", fits_out=True, astro_stretch=False)
            image = np.ones((12, 12, 3), np.float32)
            output = Path(pipeline._astro_write(image, folder, ["unknown.fit"], args, astro))
            header = fits.getheader(next(output.glob("*.fits")))
            for key in ("DATE-AVG", "DATE-OBS", "RA", "PIXSCALE", "FPLINEAR", "FPCOV", "GAIN"):
                self.assertNotIn(key, header)
            self.assertTrue((output / "observation_report.json").is_file())


if __name__ == "__main__":
    unittest.main()
