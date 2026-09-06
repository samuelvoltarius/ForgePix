"""One preregistered V5 run: V4 plus a training-calibrated direct pixel MAE.

The parent remains frozen. A small correction has zero mean within each 256px
network input. This preserves the parent's per-tile mean, not the mean after a
weighted full-image overlap. No full-image photometric guarantee is implied.
"""
import argparse
import copy
import hashlib
import pickle
import random
import json
import os
from pathlib import Path
import shutil
import time

import numpy as np
import torch
import torch.nn.functional as F

from training.train_restoration import CONFIG, CONTRACT, sample, normalize
from training.refine_noise_groups import (
    GROUPS, GATE_FLOORS, METRICS, add_noise, clean_batch, digest,
    evaluate_groups, gate_comparison, load_banks, save_json,
)
from training.vendor.nafnet_upstream import NAFNet


TRAIN_SEED = 609064
DEVELOPMENT_SEED = 830125
FINAL_SEED = 9671507
ALPHA = .25
SCHEDULE = ("original_replay",)*12 + ("identity",)*2 + ("low_noise",)*2 + \
    ("read_dominated",)*2 + ("shot_dominated",)*2 + \
    ("correlated_small", "correlated_medium", "correlated_large", "row_noise")


from training.refine_denoise_v4 import MeanAnchoredDenoiser, preservation_loss

CALIBRATION_BATCHES = 96
EXPECTED_PARENT_SHA256 = "e2c5b901b8761908edb9cd23d3d49ee4302b8b357a5dfad4a57eca446857e417"
RUN_ID = "denoise-anchored-v5-mae-001"
# Measured separately, without an optimizer: 4 x forward/backward peak plus all
# banks, all development tensors and AdamW moments = 6,056,589,704 bytes.
# Round up to 6 GiB. GB10 CUDA free tracks free unified pages, while host
# MemAvailable also includes reclaimable cache. No other job/cache is changed.
MIN_CUDA_FREE_BYTES = 6*1024**3


def verify_frozen_sources():
    """Refuse to reinterpret V5 if any reused V4 numerical source has changed."""
    root = Path(__file__).parent
    frozen = json.loads((root/"reports/denoise-anchored-v4-001-plan.json").read_text())
    decision = json.loads((root/"reports/denoise-anchored-v4-001-decision.json").read_text())
    expected = {
        "refine_denoise_v4.py": frozen["training_source_sha256"],
        "train_restoration.py": frozen["original_generator_source_sha256"],
        "refine_noise_groups.py": frozen["noise_groups_source_sha256"],
        "evaluate_models.py": frozen["final_evaluator_source_sha256"],
        "evaluate_denoise_v4.py": decision["selector_source_sha256"],
    }
    for filename, reference in expected.items():
        if digest(root/filename) != reference:
            raise ValueError("Frozen V4 numerical source changed: " + filename)
    return frozen, expected


def training_batch(step, generator, bank):
    """The original V4 schedule and generator calls, in their original order."""
    group = SCHEDULE[(step-1) % len(SCHEDULE)]
    if group == "original_replay":
        inp, target = sample(4, "cuda", generator, "denoise", bank)
    else:
        target = clean_batch(4, generator, bank)
        inp = add_noise(target, generator, group)
    return group, inp, target


def batch_digest(*tensors):
    sha = hashlib.sha256()
    for tensor in tensors:
        array = tensor.detach().cpu().contiguous().numpy()
        sha.update(str(array.dtype).encode("ascii"))
        sha.update(json.dumps(list(array.shape), separators=(",", ":")).encode("ascii"))
        sha.update(array.tobytes(order="C"))
    return sha.hexdigest()


def _state_digest(model):
    sha = hashlib.sha256()
    for key, value in sorted(model.state_dict().items()):
        sha.update(key.encode("utf-8"))
        sha.update(batch_digest(value).encode("ascii"))
    return sha.hexdigest()


def loss_v5(prediction, target, reference, lambda_mae, replay=False):
    return preservation_loss(prediction, target, reference, replay=replay) + lambda_mae * (prediction-target).abs().mean()


def calibrate_mae(model, generator, bank):
    """Fix one weight on training batches without advancing any training RNG.

    No validation access, optimizer, architecture change or parameter update.
    Raw input/target hashes must later match actual optimization batches 1..96.
    """
    started = time.perf_counter()
    generator_state = generator.get_state().clone()
    cpu_state = torch.get_rng_state().clone()
    cuda_states = [value.clone() for value in torch.cuda.get_rng_state_all()]
    numpy_state = copy.deepcopy(np.random.get_state())
    python_state = random.getstate()
    modules = list(model.modules())
    modes = [module.training for module in modules]
    state_hash = _state_digest(model)
    clone = torch.Generator(device=generator.device)
    clone.set_state(generator_state)
    l4_values, mae_values, hashes, groups = [], [], [], []
    try:
        model.eval()
        with torch.no_grad():
            for step in range(1, CALIBRATION_BATCHES + 1):
                group, inp, target = training_batch(step, clone, bank)
                hashes.append(batch_digest(inp, target))
                groups.append(group)
                x, y, _, _ = normalize(inp, target)
                prediction, reference = model(x, return_reference=True)
                l4 = preservation_loss(prediction, y, reference, replay=group == "original_replay")
                mae = (prediction-y).abs().mean()
                l4_values.append(float(l4))
                mae_values.append(float(mae))
    finally:
        generator.set_state(generator_state)
        torch.set_rng_state(cpu_state)
        torch.cuda.set_rng_state_all(cuda_states)
        np.random.set_state(numpy_state)
        random.setstate(python_state)
        for module, mode in zip(modules, modes):
            module.training = mode
    restored = dict(
        generator=torch.equal(generator.get_state(), generator_state),
        cpu_rng=torch.equal(torch.get_rng_state(), cpu_state),
        cuda_rng=all(torch.equal(a, b) for a, b in zip(torch.cuda.get_rng_state_all(), cuda_states)),
        numpy_rng=pickle.dumps(np.random.get_state()) == pickle.dumps(numpy_state),
        python_rng=random.getstate() == python_state,
        module_modes=[module.training for module in modules] == modes,
        model_state=_state_digest(model) == state_hash)
    if not all(restored.values()):
        raise RuntimeError("MAE calibration changed model state, mode or training RNG")
    median_l4, median_mae = float(np.median(l4_values)), float(np.median(mae_values))
    if not np.isfinite(l4_values).all() or not np.isfinite(mae_values).all() or not (
            np.isfinite([median_l4, median_mae]).all() and median_l4 > 0 and median_mae > 0):
        raise RuntimeError("Non-finite/non-positive training-only calibration; no fallback weight")
    weight = .10 * median_l4 / median_mae
    if not np.isfinite(weight) or weight <= 0:
        raise RuntimeError("Invalid fixed MAE weight; no fallback")
    return dict(lambda_mae=weight, median_l4=median_l4, median_pixel_mae=median_mae,
        calibration_batches=CALIBRATION_BATCHES, batch=4, batch_hashes=hashes,
        batch_groups=groups, batch_l4=l4_values, batch_pixel_mae=mae_values,
        rule="0.10 * median(L4) / median(Pixel-MAE); training only; fixed before optimizer step 1",
        initial_model_state_sha256=state_hash,
        generator_state_sha256=batch_digest(generator_state),
        cpu_rng_state_sha256=batch_digest(cpu_state),
        cuda_rng_state_sha256=[batch_digest(value) for value in cuda_states],
        restored=restored, seconds=time.perf_counter()-started)


def development_cases(observed_banks):
    generator = torch.Generator(device="cuda").manual_seed(DEVELOPMENT_SEED)
    cases = {}
    for domain, bank in [("synthetic", None), *sorted(observed_banks.items())]:
        for group in GROUPS:
            clean = clean_batch(16, generator, bank, force_observed=bank is not None)
            cases[f"{domain}/{group}"] = (add_noise(clean, generator, group), clean)
        # Original replay retains its original 25% observed-scene mixture. The
        # eight separate observed groups above use only the named observed object.
        inputs, targets = zip(*(sample(4,"cuda",generator,"denoise",bank) for _ in range(4)))
        cases[f"{domain}/original_replay"] = (torch.cat(inputs),torch.cat(targets))
    return cases


def checkpoint(model, step, validation):
    return dict(kind="mean_anchored_nafnet_v5_mae", config=CONFIG, contract=CONTRACT,
        alpha=model.alpha, parent=model.parent.state_dict(), student=model.student.state_dict(),
        report=dict(task="denoise", step=step, validation=validation, release_approved=False, lambda_mae=model.lambda_mae))


def load_candidate(path, device="cpu"):
    state = torch.load(path, map_location="cpu", weights_only=True)
    if state.get("kind") != "mean_anchored_nafnet_v5_mae" or state["config"] != CONFIG or state["contract"] != CONTRACT:
        raise ValueError("Expected the explicit v5 MAE anchored architecture and mono contract")
    model = MeanAnchoredDenoiser(state["parent"], state["alpha"])
    model.student.load_state_dict(state["student"])
    return model.to(device).eval()


def run(args):
    if args.steps != 6000:
        raise ValueError("This preregistered run requires exactly 6000 steps")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA training device is required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(args.output.parent).free < 80*1024**3:
        raise RuntimeError("80 GiB free-disk reserve required")
    if args.output.name != RUN_ID:
        raise ValueError("Use the one preregistered new V5 run directory")
    if args.output.exists():
        raise FileExistsError("The V5 run directory already exists; no rerun")
    free_cuda, _ = torch.cuda.mem_get_info()
    meminfo = dict(line.split(":",1) for line in Path("/proc/meminfo").read_text().splitlines())
    available = int(meminfo["MemAvailable"].strip().split()[0]) * 1024
    if free_cuda < MIN_CUDA_FREE_BYTES or available < 8*1024**3:
        raise RuntimeError("Measured 6 GiB CUDA reserve and 8 GiB host available RAM required")
    lock = args.output.parent/"restoration-training.lock"
    with lock.open("x") as stream:
        json.dump(dict(pid=os.getpid(), output=str(args.output), started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())), stream)
    try:
        train(args)
    finally:
        lock.unlink(missing_ok=True)


def train(args):
    args.output.mkdir(exist_ok=False)
    torch.set_num_threads(4)
    torch.manual_seed(TRAIN_SEED)
    generator = torch.Generator(device="cuda").manual_seed(TRAIN_SEED)
    parent_state = torch.load(args.parent, map_location="cpu", weights_only=True)
    if parent_state.get("config") != CONFIG or parent_state.get("contract") != CONTRACT:
        raise ValueError("Only the original mono-v2 parent is accepted")
    if digest(args.parent) != EXPECTED_PARENT_SHA256:
        raise ValueError("Original mono-v2 parent hash changed")
    frozen_v4, frozen_sources = verify_frozen_sources()
    bank, observed_banks, provenance = load_banks(args.scenes)
    if provenance != frozen_v4["provenance"]:
        raise ValueError("The V4 scene bank/split/source provenance changed")
    free_cuda, total_cuda = torch.cuda.mem_get_info()
    meminfo = dict(line.split(":",1) for line in Path("/proc/meminfo").read_text().splitlines())
    plan = dict(schema_version=1, run_id=RUN_ID, task="denoise", status="experimental", release_approved=False,
        planned_steps=args.steps, batch=4, learning_rate=1e-5, final_learning_rate=1e-6,
        training_seed=TRAIN_SEED, development_seed=DEVELOPMENT_SEED,
        reserved_final_seed=FINAL_SEED, reserved_final_scenes=128,
        previous_consumed_final_seeds=[9237401,9374209,9518063],
        final_evaluation_rule="Do not consume the reserved final seed unless a changed checkpoint passes every development gate. A failed development candidate cannot be selected by final-test results.",
        device=dict(type="cuda", name=torch.cuda.get_device_name(), cuda_version=torch.version.cuda,
                    torch_version=str(torch.__version__), cudnn_version=torch.backends.cudnn.version()),
        resources=dict(free_disk_bytes=shutil.disk_usage(args.output.parent).free,
                       cuda_free_bytes=free_cuda,cuda_total_bytes=total_cuda,
                       mem_available_kib=int(meminfo["MemAvailable"].strip().split()[0]),
                       unrelated_jobs_modified=False),
        parent_checkpoint_sha256=digest(args.parent), training_source_sha256=digest(__file__),
        original_generator_source_sha256=digest(Path(__file__).with_name("train_restoration.py")),
        noise_groups_source_sha256=digest(Path(__file__).with_name("refine_noise_groups.py")),
        final_evaluator_source_sha256=digest(Path(__file__).with_name("evaluate_models.py")),
        provenance=provenance, schedule=list(SCHEDULE), alpha=ALPHA,
        architecture="Frozen original NAFNet plus quarter-strength trainable NAFNet difference with its per-input spatial mean removed",
        development_group_count=27, development_scenes_per_group=16,
        gates=dict(rule="Every development group must be no worse than unchanged mono parent on every metric; original v3 numerical floors unchanged",
                   metrics=list(METRICS), absolute_numerical_floors=GATE_FLOORS, maximum_ratio=1.,
                   final_rule="Overall and each noise-class MSE, overall stellar flux absolute error, faint-structure MSE and absolute image bias must not regress against original mono parent",
                   full_image_rule="Before adoption separately require large-field overlap/tile-phase and scientific preservation gates; per-tile mean anchoring does not guarantee bias-free weighted full-image output"),
        limitations="HST targets retain observational noise; no real independent noise pairs or held-out camera qualification. The architecture approximately doubles network inference work. Per-input mean anchoring preserves the parent's mean, not true absolute sky or the mean after full-image weighted overlap. No automatic activation.")
    plan.update(
        experiment_change="V4 loss plus fixed training-calibrated direct Pixel-MAE only",
        verified_frozen_v4_source_hashes=frozen_sources,
        memory_probe=json.loads((args.output.parent/(RUN_ID+"-memory-probe.json")).read_text()),
        memory_probe_sha256=digest(args.output.parent/(RUN_ID+"-memory-probe.json")),
        minimum_cuda_free_bytes=MIN_CUDA_FREE_BYTES,
        preflight_note="An initial supervisor refused before launching training at 7.58 GiB CUDA free against an unmeasured 8 GiB rule. A separate zero-optimizer-step memory probe justified a rounded-up 6 GiB operational reserve, with 8 GiB host available RAM and 80 GiB disk still required. Scientific experiment unchanged.",
        preregistration_sha256=digest(Path(__file__).with_name("DENOISE_V5_PLAN.md")),
        v4_training_source_sha256=digest(Path(__file__).with_name("refine_denoise_v4.py")),
        v4_selector_source_sha256=digest(Path(__file__).with_name("evaluate_denoise_v4.py")),
        selector_source_sha256=digest(Path(__file__).with_name("evaluate_denoise_v5.py")),
        precision="Original V4 Float32; no autocast or changed backend precision settings",
        optimizer=dict(name="AdamW", lr=1e-5, weight_decay=0., gradient_clip=.25,
                       scheduler="CosineAnnealingLR", eta_min=1e-6, steps=6000),
        calibration_rule="96 original training batches; lambda=0.10*median(L4)/median(pixel MAE); no sweep")
    save_json(args.output/"plan.json",plan)
    model = MeanAnchoredDenoiser(parent_state["model"]).cuda()
    calibration = calibrate_mae(model, generator, bank)
    model.lambda_mae = calibration["lambda_mae"]
    save_json(args.output/"mae_calibration.json", calibration)
    plan["mae_calibration"] = calibration
    save_json(args.output/"plan.json", plan)
    print(json.dumps(dict(calibration="complete_before_step_1", lambda_mae=model.lambda_mae,
        median_l4=calibration["median_l4"], median_pixel_mae=calibration["median_pixel_mae"],
        rng_restored=all(calibration["restored"].values()))), flush=True)
    cases = development_cases(observed_banks)
    validation_started = time.perf_counter()
    parent_scores = evaluate_groups(model.parent, cases)
    validation_seconds = time.perf_counter()-validation_started
    save_json(args.output/"parent_development.json",parent_scores)
    shutil.copyfile(args.parent,args.output/"selected_parent.pt")
    optimizer = torch.optim.AdamW(model.student.parameters(),lr=1e-5,weight_decay=0.)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,args.steps,eta_min=1e-6)
    started = time.perf_counter()
    best_score, best_step, accepted_score, accepted_step = float("inf"),0,1.,0
    best_validation = accepted_validation = None
    validations = []
    optimization_seconds = 0.
    optimization_cuda_seconds = 0.
    cuda_start, cuda_end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    reproduced_hashes = []
    with (args.output/"metrics.jsonl").open("x") as stream:
        for step in range(1,args.steps+1):
            optimization_start = time.perf_counter()
            model.train()
            model.parent.eval()
            cuda_start.record()
            group, inp, target = training_batch(step, generator, bank)
            if step <= CALIBRATION_BATCHES:
                actual_hash = batch_digest(inp, target)
                if actual_hash != calibration["batch_hashes"][step-1]:
                    raise RuntimeError("Actual training batch differs from the cloned calibration sequence")
                reproduced_hashes.append(actual_hash)
                if step == CALIBRATION_BATCHES:
                    save_json(args.output/"batch_reproduction.json", dict(
                        matched=True, actual_optimization_batch_hashes=reproduced_hashes,
                        calibration_batches=CALIBRATION_BATCHES,
                        calibration_sha256=digest(args.output/"mae_calibration.json")))
            x,y,_,_ = normalize(inp,target)
            optimizer.zero_grad(set_to_none=True)
            prediction,reference = model(x,return_reference=True)
            loss = loss_v5(prediction,y,reference,model.lambda_mae,replay=group=="original_replay")
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.student.parameters(),.25)
            optimizer.step()
            scheduler.step()
            cuda_end.record()
            torch.cuda.synchronize()
            optimization_cuda_seconds += cuda_start.elapsed_time(cuda_end)/1000.
            optimization_seconds += time.perf_counter()-optimization_start
            if step == 1 or step%100 == 0:
                row=dict(step=step,group=group,loss=float(loss.detach()),seconds=time.perf_counter()-started)
                stream.write(json.dumps(row)+"\n");stream.flush()
                print(json.dumps(row),flush=True)
            if step%1000 == 0 or step==args.steps:
                began=time.perf_counter()
                scores=evaluate_groups(model,cases)
                validation_seconds+=time.perf_counter()-began
                gate=gate_comparison(scores,parent_scores)
                validations.append(dict(step=step,gate=gate))
                save_json(args.output/f"development-{step:05d}.json",dict(step=step,gate=gate,validation=scores))
                score=gate["geometric_group_mse_ratio"]
                if score<best_score:
                    best_score,best_step,best_validation=score,step,scores
                    torch.save(checkpoint(model,step,scores),args.output/"research_candidate.pt")
                if gate["passes_all_groups"] and score<accepted_score:
                    accepted_score,accepted_step,accepted_validation=score,step,scores
                    torch.save(checkpoint(model,step,scores),args.output/"eligible_candidate.pt")
                print(json.dumps(dict(step=step,score=score,gate_pass=gate["passes_all_groups"],
                    failed_metrics=len(gate["failures"]),accepted_step=accepted_step)),flush=True)
    report=dict(plan,completed_steps=step,seconds=time.perf_counter()-started,
        optimization_seconds=optimization_seconds,validation_seconds=validation_seconds,
        optimization_cuda_event_seconds=optimization_cuda_seconds,
        cuda_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
        calibration_seconds=calibration["seconds"],
        optimization_first_96_batches_match_calibration=len(reproduced_hashes) == CALIBRATION_BATCHES,
        optimization_first_96_batch_hashes=reproduced_hashes,
        best_research_step=best_step,best_research_candidate_sha256=digest(args.output/"research_candidate.pt"),
        development_selected_step=accepted_step,
        development_selected_sha256=digest(args.output/"eligible_candidate.pt") if accepted_step else plan["parent_checkpoint_sha256"],
        development_decision="candidate_requires_independent_evaluation" if accepted_step else "reject_refinement_retain_original_parent",
        final_seed_consumed=False,validation=best_validation,parent_validation=parent_scores,
        candidate_gates=gate_comparison(best_validation,parent_scores),
        eligible_validation=accepted_validation,validation_checkpoints=validations)
    save_json(args.output/"report.json",report)
    print(json.dumps(dict(report=str(args.output/"report.json"),seconds=report["seconds"],
        best_research_step=best_step,development_selected_step=accepted_step,
        final_seed_consumed=False)),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent",type=Path,required=True)
    parser.add_argument("--scenes",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--steps",type=int,default=6000)
    run(parser.parse_args())
