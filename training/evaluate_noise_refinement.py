"""Evaluate a preregistered run using the unchanged independent scene generator.

Both compared models use the mono-v2 affine adapter. The older evaluator CLI
expects an RGB-v1 parent, so this wrapper reuses its public evaluator and passes
two mono adapters, without changing any test scenes or scientific metrics.
"""
import argparse
import json
import math
from pathlib import Path

from training import evaluate_models as independent


def selection(training, evaluation):
    if evaluation["holdout_seed"] != training["reserved_final_seed"]:
        raise ValueError("Final seed differs from the pre-training plan")
    if evaluation["scene_count"] != training["reserved_final_scenes"]:
        raise ValueError("Final scene count differs from the pre-training plan")
    if evaluation["evaluator_sha256"] != training["final_evaluator_source_sha256"]:
        raise ValueError("Independent evaluator changed since the run was planned")
    if evaluation["models"]["parent"]["sha256"] != training["parent_checkpoint_sha256"]:
        raise ValueError("Parent checkpoint differs from the pre-training plan")
    if evaluation["models"]["candidate"]["sha256"] != training["best_research_candidate_sha256"]:
        raise ValueError("Candidate checkpoint differs from the training report")
    failures = []
    def compare(group, models, metric, statistic="mean"):
        candidate = models["candidate"][metric][statistic]
        parent = models["parent"][metric][statistic]
        if candidate is None or parent is None or not math.isfinite(candidate) or not math.isfinite(parent):
            failures.append(dict(group=group, metric=metric, reason="Missing/non-finite metric"))
        elif candidate > parent:
            failures.append(dict(group=group, metric=metric, statistic=statistic,
                                 candidate=candidate, parent=parent, ratio=candidate/parent if parent else None))
    compare("overall", evaluation["overall"], "mse")
    for noise, group in evaluation["by_group"]["noise_class"].items():
        compare(noise, group["models"], "mse")
    compare("overall", evaluation["overall"], "stellar_aperture_flux_absolute_error_fraction")
    compare("overall", evaluation["overall"], "faint_structure_mse")
    compare("overall", evaluation["overall"], "mean_bias", "mean_absolute")
    eligible = training["candidate_gates"]["passes_all_groups"] and not failures
    return dict(schema_version=1, decision="research_candidate_passes_limited_gates" if eligible else "reject_refinement",
        release_approved=False, bundled_weights_changed=False,
        development_pass=training["candidate_gates"]["passes_all_groups"], final_pass=not failures,
        development_failed_metrics=len(training["candidate_gates"]["failures"]),
        final_failures=failures, final_comparison=evaluation["comparison"],
        device=training["device"], seed=evaluation["holdout_seed"], scenes=evaluation["scene_count"],
        suite_sha256=evaluation["suite_sha256"], models=evaluation["models"],
        source_hashes=dict(training=training["training_source_sha256"],
                           scene_generator=training["scene_generator_source_sha256"],
                           independent_evaluator=evaluation["evaluator_sha256"]),
        split_provenance=training["provenance"],
        reason="All declared development and final gates are required. A lower aggregate MSE cannot hide a noise-class, object or preservation regression. Even a pass remains research-only.",
        limitations=training["limitations"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    args = parser.parse_args()
    training = json.loads((args.run/"report.json").read_text())
    plan = json.loads((args.run/"plan.json").read_text())
    for field in ("reserved_final_seed", "reserved_final_scenes", "parent_checkpoint_sha256",
                  "final_evaluator_source_sha256", "training_source_sha256"):
        if training[field] != plan[field]:
            raise ValueError("Training report changed a pre-training plan field")
    if independent.sha256(Path(independent.__file__)) != plan["final_evaluator_source_sha256"]:
        raise ValueError("Evaluator source changed; preserve the original independent evaluator")
    report_path = args.run/"independent_evaluation.json"
    selection_path = args.run/"selection.json"
    if report_path.exists() or selection_path.exists():
        raise FileExistsError("Final evaluation already exists; do not inspect and reroll")
    independent.HOLDOUT_SEED = plan["reserved_final_seed"]
    candidate = independent.Predictor(args.run/"candidate.pt", "candidate", "denoise", "cuda")
    parent = independent.Predictor(args.parent, "candidate", "denoise", "cuda")
    parent.details["comparison_role"] = "unchanged_mono_v2_parent"
    candidate.details["comparison_role"] = "noise_group_refinement_candidate"
    report = independent.evaluate(candidate, parent, "denoise", plan["reserved_final_scenes"])
    report["evaluator_sha256"] = independent.sha256(Path(independent.__file__))
    report["comparison_adapter"] = "Both models use the unchanged candidate/mono affine adapter; same generator, scenes and scientific measurements"
    decision = selection(training, report)
    with report_path.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    with selection_path.open("x") as stream:
        json.dump(decision, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(selection=str(selection_path), decision=decision["decision"],
        comparison=report["comparison"], failed_metrics=len(decision["final_failures"]))), flush=True)


if __name__ == "__main__":
    main()
