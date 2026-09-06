"""Execute shipped weights, not a mocked ONNX session, in the normal CI suite."""
import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"core"))
import ai_restore
from constants import ForgePixFehler


class BundledAITests(unittest.TestCase):
    def test_all_four_shipped_models_are_usable_and_explicitly_experimental(self):
        entries=ai_restore.list_models()
        by_task={item.get("task"):item for item in entries}
        self.assertEqual(set(by_task),set(ai_restore.TASKS))
        y,x=np.mgrid[:61,:73]
        mono=(.05+1.4*np.exp(-((x-33)**2+(y-29)**2)/12)).astype(np.float32)
        mono[0,0]=-.03
        for task in ai_restore.TASKS:
            with self.subTest(task=task):
                model=by_task[task]
                self.assertTrue(model["available"],model.get("reason"))
                self.assertFalse(model["release_approved"])
                with self.assertRaises(ForgePixFehler):
                    ai_restore.restore(mono,model["id"],log=lambda _:None)
                restored=ai_restore.restore(mono,model["id"],allow_experimental=True,log=lambda _:None)
                self.assertEqual(restored.shape,mono.shape)
                self.assertEqual(restored.dtype,np.float32)
                self.assertTrue(np.isfinite(restored).all())
                identity=ai_restore.restore(mono,model["id"],allow_experimental=True,strength=0,log=lambda _:None)
                np.testing.assert_array_equal(identity,mono)

    def test_actual_mono_model_does_not_swap_or_mix_color_channels(self):
        rng=np.random.default_rng(62945)
        rgb=rng.normal(.04,.006,(41,67,3)).astype(np.float32)
        rgb[...,0]+=.12
        rgb[...,1]+=.03
        first=ai_restore.restore(rgb,"forgepix-denoise-mono-v2",allow_experimental=True,log=lambda _:None)
        reversed_=ai_restore.restore(rgb[...,::-1],"forgepix-denoise-mono-v2",allow_experimental=True,log=lambda _:None)
        np.testing.assert_array_equal(first,reversed_[...,::-1])


if __name__=="__main__":
    unittest.main()
