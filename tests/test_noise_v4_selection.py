"""A development failure must not consume a final holdout or loosen its gates."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from training.evaluate_denoise_v4 import development_eligible,final_failures,main,NUMERICAL_FLOORS


class AnchoredNoiseSelection(unittest.TestCase):
    def test_failed_development_does_not_run_final_test_or_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            parent=root/"parent.pt";parent.write_bytes(b"unchanged parent fixture")
            report=dict(development_selected_step=0,reserved_final_seed=9671507,reserved_final_scenes=128,
                parent_checkpoint_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
                training_source_sha256="training",final_evaluator_source_sha256="evaluator",gates={},
                device={"type":"cuda"},candidate_gates={"failures":[{"group":"M13/read","metric":"mae"}]},
                limitations="No full-image proof")
            for name in ("plan.json","report.json"):
                (root/name).write_text(json.dumps(report))
            with patch.object(sys,"argv",["evaluate","--run",str(root),"--parent",str(parent)]):
                main()
            decision=json.loads((root/"decision.json").read_text())
            self.assertFalse(decision["final_seed_consumed"])
            self.assertFalse(decision["final_evaluation_performed"])
            self.assertFalse(decision["release_approved"])
            self.assertFalse((root/"independent_evaluation.json").exists())
            self.assertFalse((root/"research-export").exists())

    def test_claimed_eligible_candidate_must_really_pass_each_development_metric(self):
        groups={f"group-{index}":dict.fromkeys(NUMERICAL_FLOORS,.01) for index in range(27)}
        for metrics in groups.values():metrics["scenes"]=16
        report=dict(development_selected_step=1000,development_group_count=27,development_scenes_per_group=16,
                    parent_validation=deepcopy(groups),eligible_validation=deepcopy(groups))
        self.assertTrue(development_eligible(report))
        report["eligible_validation"]["group-5"]["local_mean_rms"]*=1.01
        with self.assertRaises(ValueError):development_eligible(report)

    def report(self):
        metrics={key:{"mean":.01,"mean_absolute":.01} for key in
            ("mse","mean_bias","stellar_aperture_flux_absolute_error_fraction","faint_structure_mse")}
        models={"parent":deepcopy(metrics),"candidate":deepcopy(metrics)}
        return dict(overall=deepcopy(models),by_group={"noise_class":{
            "read_dominated":{"models":deepcopy(models)},"correlated":{"models":deepcopy(models)}}})

    def test_group_regression_cannot_hide_behind_lower_overall_error(self):
        report=self.report()
        report["overall"]["candidate"]["mse"]["mean"]*=.5
        report["by_group"]["noise_class"]["read_dominated"]["models"]["candidate"]["mse"]["mean"]*=1.01
        self.assertEqual(final_failures(report)[0]["group"],"read_dominated")

    def test_absolute_bias_and_missing_faint_measurement_are_required(self):
        report=self.report()
        report["overall"]["candidate"]["mean_bias"]["mean"]=0
        report["overall"]["candidate"]["mean_bias"]["mean_absolute"]*=1.01
        report["overall"]["candidate"]["faint_structure_mse"]["mean"]=None
        self.assertEqual({row["metric"] for row in final_failures(report)},
                         {"mean_bias","faint_structure_mse"})


if __name__=="__main__":
    unittest.main()
