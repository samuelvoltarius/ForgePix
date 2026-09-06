"""Observed-scene preprocessing must retain real dynamic range and split safety."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from astropy.io import fits
from training.prepare_scenes import prepare


class ScenePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def source(self, group, split, image, digest=None):
        folder=self.root/"sources"/group
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/"example_drc.fits"
        fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(image,name="SCI"),
                      fits.ImageHDU(np.ones_like(image),name="WHT")]).writeto(path)
        record=dict(group=group,split=split,rights="PUBLIC",uri="mast:HST/product/example_drc.fits",
                    policy="https://archive.stsci.edu/publishing/data-use",
                    sha256=digest or hashlib.sha256(path.read_bytes()).hexdigest())
        Path(str(path)+".json").write_text(json.dumps(record))
        return path

    def run_prepare(self):
        with contextlib.redirect_stdout(io.StringIO()):
            prepare(self.root/"sources",self.root/"output",per_file=1)

    def test_dark_background_and_bright_cores_survive(self):
        values=np.linspace(-2,3,256*256,dtype=np.float32).reshape(256,256)
        values[100,100]=40
        self.source("train-object","train",values)
        self.source("validation-object","validation",values+1)
        self.run_prepare()
        train=np.load(self.root/"output/train.npy")
        self.assertEqual(train.shape,(1,256,256))
        self.assertLess(float(train.min()),0)
        self.assertGreater(float(train.max()),1)
        report=json.loads((self.root/"output/manifest.json").read_text())
        self.assertEqual(report["counts"],dict(train=1,validation=1,test=0))
        self.assertFalse(report["ground_truth"])

    def test_modified_source_hash_fails_before_training(self):
        self.source("train-object","train",np.ones((256,256),np.float32),digest="0"*64)
        with self.assertRaisesRegex(ValueError,"checksum"):
            self.run_prepare()

    def test_identical_fits_cannot_cross_splits(self):
        values=np.arange(256*256,dtype=np.float32).reshape(256,256)
        self.source("first-object","train",values)
        self.source("other-object","validation",values)
        with self.assertRaisesRegex(ValueError,"crosses splits"):
            self.run_prepare()


if __name__ == "__main__":
    unittest.main()
