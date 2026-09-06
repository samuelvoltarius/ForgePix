"""Consume a reserved final test only after all fixed development gates pass.

No app model is ever installed. Even a successful final synthetic comparison
only permits a research export pending separate full-image/camera evaluation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import time


# Import the fixed comparisons; do not retune thresholds or aggregate groups.
from training.evaluate_denoise_v4 import NUMERICAL_FLOORS, digest, development_eligible, final_failures


def export_research(checkpoint_path,output,training,evaluation):
    import numpy as np
    import torch
    import onnx
    import onnxruntime as ort
    from training.refine_denoise_v5 import load_candidate,CONTRACT
    model=load_candidate(checkpoint_path).eval()
    torch.set_num_threads(4)
    output.mkdir(exist_ok=False)
    graph=output/"model.onnx"
    torch.onnx.export(model,torch.zeros(1,1,256,256),str(graph),input_names=["image"],
        output_names=["restored"],opset_version=17,dynamo=False,external_data=False)
    onnx.checker.check_model(onnx.load(graph))
    options=ort.SessionOptions();options.intra_op_num_threads=4
    session=ort.InferenceSession(str(graph),sess_options=options,providers=["CPUExecutionProvider"])
    rng=np.random.default_rng(790067)
    inputs=[np.zeros((1,1,256,256),np.float32),rng.normal(.08,.03,(1,1,256,256)).astype(np.float32),
            rng.uniform(-.2,2.,(1,1,256,256)).astype(np.float32)]
    errors=[]
    for image in inputs:
        with torch.no_grad():
            reference=model(torch.from_numpy(image)).numpy()
        actual=session.run(None,{"image":image})[0]
        np.testing.assert_allclose(actual,reference,atol=2e-5,rtol=2e-4)
        if not np.isfinite(actual).all():
            raise ValueError("Non-finite export")
        errors.append(float(np.abs(actual-reference).max()))
    manifest=dict(schema_version=1,id="forgepix-denoise-anchored-v5-mae",task="denoise",model_file="model.onnx",
        sha256=digest(graph),checkpoint_sha256=digest(checkpoint_path),**CONTRACT,
        status="experimental",release_approved=False,photometry_validated=False,license="MIT",
        architecture=training["architecture"],weights_origin="Own ForgePix parent and fine-tuned student; no external pretrained weights",
        onnx_opset=17,export_max_abs_errors=errors,exporter_source_sha256=digest(__file__),
        inference=dict(strategy="overlapping_tiles",stride=192,overlap=64,padding="reflect"),
        limitations=training["limitations"])
    for name,value in [("manifest.json",manifest),("training_report.json",training),("evaluation.json",evaluation)]:
        (output/name).write_text(json.dumps(value,indent=2,allow_nan=False))
    source=Path(__file__).resolve().parent.parent
    shutil.copyfile(source/"training/vendor/NAFNet-LICENSE.txt",output/"NAFNet-LICENSE.txt")
    shutil.copyfile(source/"LICENSE",output/"LICENSE")
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--parent",type=Path,required=True)
    args=parser.parse_args()
    training=json.loads((args.run/"report.json").read_text())
    plan=json.loads((args.run/"plan.json").read_text())
    for field in ("reserved_final_seed","reserved_final_scenes","parent_checkpoint_sha256",
                  "training_source_sha256","final_evaluator_source_sha256","gates",
                  "selector_source_sha256","v4_training_source_sha256","v4_selector_source_sha256",
                  "mae_calibration","preregistration_sha256","provenance","optimizer"):
        if training[field]!=plan[field]:
            raise ValueError("A pre-training plan field changed")
    if digest(args.parent)!=training["parent_checkpoint_sha256"]:
        raise ValueError("Original parent checkpoint changed")
    if training.get("run_id") != "denoise-anchored-v5-mae-001" or training.get("completed_steps") != 6000:
        raise ValueError("Expected the one fully completed preregistered V5 run")
    if not training.get("optimization_first_96_batches_match_calibration") or (
            training["optimization_first_96_batch_hashes"] != training["mae_calibration"]["batch_hashes"]):
        raise ValueError("The 96 real optimization batches did not reproduce calibration")
    root = Path(__file__).parent
    for name, field in (("refine_denoise_v5.py", "training_source_sha256"),
                        ("evaluate_denoise_v5.py", "selector_source_sha256"),
                        ("refine_denoise_v4.py", "v4_training_source_sha256"),
                        ("evaluate_denoise_v4.py", "v4_selector_source_sha256"),
                        ("DENOISE_V5_PLAN.md", "preregistration_sha256")):
        if digest(root/name) != training[field]:
            raise ValueError("Preregistered source changed: " + name)
    decision_path=args.run/"decision.json"
    evaluation_path=args.run/"independent_evaluation.json"
    final_marker = args.run/"final_seed_consumption.json"
    if decision_path.exists() or evaluation_path.exists() or final_marker.exists():
        raise FileExistsError("Decision or final evaluation already exists; do not reroll")
    decision=dict(schema_version=1,release_approved=False,bundled_weights_changed=False,
        parent_checkpoint_sha256=training["parent_checkpoint_sha256"],device=training["device"],
        reserved_final_seed=training["reserved_final_seed"],final_seed_consumed=False,
        decision="reject_development_candidate_retain_original_parent",final_evaluation_performed=False,
        development_failures=training["candidate_gates"]["failures"],
        limitations=training["limitations"],selector_source_sha256=digest(__file__))
    if not development_eligible(training):
        decision["reason"]="No changed checkpoint passed all fixed development gates. The final test seed remains untouched; no export or deployment is justified."
    else:
        # The V4 selector's group comparisons remain unchanged. Additionally
        # enforce the already preregistered strict geometric improvement and
        # reject malformed/nonfinite baselines instead of trusting NaN ordering.
        ratios = []
        for group, parent_scores in training["parent_validation"].items():
            candidate_scores = training["eligible_validation"][group]
            for metric in NUMERICAL_FLOORS:
                if not math.isfinite(parent_scores[metric]) or not math.isfinite(candidate_scores[metric]):
                    raise ValueError("Nonfinite development evidence")
            ratios.append(candidate_scores["mse"]/max(parent_scores["mse"], 1e-12))
        if not math.exp(sum(math.log(max(value, 1e-12)) for value in ratios)/len(ratios)) < 1.:
            raise ValueError("No strict geometric MSE improvement")
        import numpy as np
        import torch
        from training import evaluate_models as independent
        from training.refine_denoise_v5 import load_candidate,CONTRACT
        if digest(Path(independent.__file__))!=training["final_evaluator_source_sha256"]:
            raise ValueError("Independent scene generator or metrics changed")
        candidate_path=args.run/"eligible_candidate.pt"
        if digest(candidate_path)!=training["development_selected_sha256"]:
            raise ValueError("Selected candidate changed")
        torch.set_num_threads(4)
        class Candidate:
            def __init__(self):
                self.model=load_candidate(candidate_path,"cuda")
                self.details=dict(path=str(candidate_path),sha256=digest(candidate_path),role="candidate",
                    format="torch",device="cuda",contract=CONTRACT,architecture=training["architecture"])
            def predict(self,image):
                image,low,scale=independent.normalize_v1(image)
                with torch.no_grad():
                    actual=self.model(torch.from_numpy(image[None,None]).cuda()).cpu().numpy()[0,0]
                return (actual.astype(np.float64)*scale+low).astype(np.float32)
        if training["reserved_final_seed"] != 9671507 or training["reserved_final_scenes"] != 128:
            raise ValueError("The pre-reserved final seed or scene count changed")
        # Claim this seed before generating a single final scene, even if the
        # subsequent process fails. A crash is not permission for another try.
        with final_marker.open("x") as stream:
            json.dump(dict(seed=9671507, scenes=128, candidate_sha256=digest(candidate_path),
                claimed_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
                rule="One final evaluation only; do not reroll after failure"),stream,indent=2)
        independent.HOLDOUT_SEED=training["reserved_final_seed"]
        parent=independent.Predictor(args.parent,"candidate","denoise","cuda")
        parent.details["comparison_role"]="unchanged_mono_v2_parent"
        began=time.perf_counter()
        evaluation=independent.evaluate(Candidate(),parent,"denoise",training["reserved_final_scenes"])
        evaluation["evaluator_sha256"]=training["final_evaluator_source_sha256"]
        evaluation["comparison_adapter"]="Both receive the same input-derived mono affine transform; independent scenes and measurements unchanged"
        evaluation_path.write_text(json.dumps(evaluation,indent=2,allow_nan=False))
        failures=final_failures(evaluation)
        decision.update(final_seed_consumed=True,final_evaluation_performed=True,
            final_evaluation_seconds=time.perf_counter()-began,final_failures=failures,
            final_comparison=evaluation["comparison"],suite_sha256=evaluation["suite_sha256"],
            decision="reject_final_candidate_retain_original_parent" if failures else "research_candidate_requires_full_image_and_camera_gates")
        if not failures:
            decision["research_export"]=export_research(candidate_path,args.run/"research-export",training,evaluation)
    with decision_path.open("x") as stream:
        json.dump(decision,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(path=str(decision_path),decision=decision["decision"],
                         final_seed_consumed=decision["final_seed_consumed"])),flush=True)


if __name__=="__main__":
    main()
