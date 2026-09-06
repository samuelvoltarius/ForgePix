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


NUMERICAL_FLOORS={"mse":1e-12,"mae":1e-8,"absolute_image_bias":1e-8,"local_mean_rms":1e-8}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def development_eligible(training):
    if training["development_selected_step"] == 0:
        return False
    candidate,parent=training["eligible_validation"],training["parent_validation"]
    if set(candidate)!=set(parent) or len(parent)!=training["development_group_count"]:
        raise ValueError("Development group set changed")
    for group,baseline in parent.items():
        if candidate[group]["scenes"]!=training["development_scenes_per_group"]:
            raise ValueError("Development scene count changed")
        for metric,floor in NUMERICAL_FLOORS.items():
            value=candidate[group][metric]
            if not math.isfinite(value) or value>baseline[metric]+floor:
                raise ValueError("Claimed eligible candidate fails a fixed development gate")
    return True


def final_failures(evaluation):
    failures=[]
    def compare(group,models,metric,statistic="mean"):
        candidate,parent=models["candidate"][metric][statistic],models["parent"][metric][statistic]
        if candidate is None or parent is None or not math.isfinite(candidate) or not math.isfinite(parent):
            failures.append(dict(group=group,metric=metric,reason="Missing/non-finite scientific metric"))
        elif candidate>parent:
            failures.append(dict(group=group,metric=metric,statistic=statistic,candidate=candidate,parent=parent,
                ratio=candidate/parent if parent else None))
    compare("overall",evaluation["overall"],"mse")
    for name,group in evaluation["by_group"]["noise_class"].items():
        compare(name,group["models"],"mse")
    compare("overall",evaluation["overall"],"stellar_aperture_flux_absolute_error_fraction")
    compare("overall",evaluation["overall"],"faint_structure_mse")
    compare("overall",evaluation["overall"],"mean_bias","mean_absolute")
    return failures


def export_research(checkpoint_path,output,training,evaluation):
    import numpy as np
    import torch
    import onnx
    import onnxruntime as ort
    from training.refine_denoise_v4 import load_candidate,CONTRACT
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
    manifest=dict(schema_version=1,id="forgepix-denoise-anchored-v4",task="denoise",model_file="model.onnx",
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
                  "training_source_sha256","final_evaluator_source_sha256","gates"):
        if training[field]!=plan[field]:
            raise ValueError("A pre-training plan field changed")
    if digest(args.parent)!=training["parent_checkpoint_sha256"]:
        raise ValueError("Original parent checkpoint changed")
    decision_path=args.run/"decision.json"
    evaluation_path=args.run/"independent_evaluation.json"
    if decision_path.exists() or evaluation_path.exists():
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
        import numpy as np
        import torch
        from training import evaluate_models as independent
        from training.refine_denoise_v4 import load_candidate,CONTRACT
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
