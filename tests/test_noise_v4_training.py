"""Scientific and optimization contracts for the optional v4 CUDA experiment."""
import unittest

try:
    import torch
    from training.refine_denoise_v4 import MeanAnchoredDenoiser, preservation_loss, SCHEDULE, CONFIG
    from training.vendor.nafnet_upstream import NAFNet
except ImportError:
    torch=None


@unittest.skipIf(torch is None,"PyTorch is optional; run architecture tests in the Spark training environment")
class MeanAnchoredNoiseTraining(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(4)
        torch.manual_seed(5291)
        parent=NAFNet(**CONFIG)
        self.model=MeanAnchoredDenoiser(parent.state_dict())

    def test_initialization_is_exactly_parent_and_half_schedule_is_original_replay(self):
        image=torch.randn(2,1,64,64)*.4-.05
        with torch.no_grad():
            self.assertTrue(torch.equal(self.model(image),self.model.parent(image)))
        self.assertEqual(SCHEDULE.count("original_replay")*2,len(SCHEDULE))

    def test_changed_student_keeps_parent_spatial_mean_for_each_image(self):
        with torch.no_grad():
            self.model.student.ending.weight.add_(torch.randn_like(self.model.student.ending.weight)*.02)
            self.model.student.ending.bias.add_(.13)
        image=torch.randn(3,1,64,64)*.5-.2
        with torch.no_grad():
            candidate,parent=self.model(image,return_reference=True)
        self.assertGreater(float((candidate-parent).square().mean()),1e-8)
        torch.testing.assert_close(candidate.mean((-2,-1)),parent.mean((-2,-1)),atol=1e-7,rtol=1e-6)

    def test_only_student_gets_gradients_and_signed_targets_have_finite_loss(self):
        image=torch.randn(2,1,64,64)*.2-.1
        target=image+torch.randn_like(image)*.01
        candidate,parent=self.model(image,return_reference=True)
        loss=preservation_loss(candidate,target,parent,replay=True)
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        self.assertTrue(all(parameter.grad is None for parameter in self.model.parent.parameters()))
        self.assertTrue(any(parameter.grad is not None and parameter.grad.abs().sum()>0
                            for parameter in self.model.student.parameters()))


if __name__=="__main__":
    unittest.main()
