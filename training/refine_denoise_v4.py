"""Conservative own-denoiser refinement with replay and a mean-anchored residual.

The parent remains frozen. A small correction has zero mean within each 256px
network input. This preserves the parent's per-tile mean, not the mean after a
weighted full-image overlap. No full-image photometric guarantee is implied.
"""
import argparse
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


class MeanAnchoredDenoiser(torch.nn.Module):
    def __init__(self, parent_state, alpha=ALPHA):
        super().__init__()
        self.parent = NAFNet(**CONFIG)
        self.student = NAFNet(**CONFIG)
        self.parent.load_state_dict(parent_state)
        self.student.load_state_dict(parent_state)
        self.parent.requires_grad_(False)
        self.alpha = float(alpha)

    def forward(self, image, return_reference=False):
        with torch.no_grad():
            reference = self.parent(image)
        correction = self.student(image)-reference
        correction = correction-correction.mean((-2,-1), keepdim=True)
        prediction = reference+self.alpha*correction
        return (prediction, reference) if return_reference else prediction


def preservation_loss(prediction, target, reference, replay=False):
    error = prediction-target
    mse = error.square().mean()
    gradients = (error[:,:,:,1:]-error[:,:,:,:-1]).square().mean()
    gradients += (error[:,:,1:,:]-error[:,:,:-1,:]).square().mean()
    local = F.avg_pool2d(error, 8, 8).square().mean()
    local += F.avg_pool2d(error, 32, 32).square().mean()
    # A training-only weak-signal proxy, not the independent analytic nebula mask.
    limits = torch.quantile(target.detach().flatten(1),
        torch.tensor([.01,.99], device=target.device), dim=1)
    low = limits[0,:,None,None,None]
    width = (limits[1]-limits[0]).clamp_min(1e-6)[:,None,None,None]
    fraction = (target.detach()-low)/width
    weak = (fraction > .01) & (fraction < .30)
    weak_error = (error.square()*weak).sum()/weak.sum().clamp_min(1)
    # Preserve the incumbent's learned solution during original-distribution replay.
    anchoring = (prediction-reference).square().mean() if replay else error.new_zeros(())
    return mse + .5*gradients + 4*local + 2*weak_error + .25*anchoring


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
    return dict(kind="mean_anchored_nafnet_v4", config=CONFIG, contract=CONTRACT,
        alpha=model.alpha, parent=model.parent.state_dict(), student=model.student.state_dict(),
        report=dict(task="denoise", step=step, validation=validation, release_approved=False))


def load_candidate(path, device="cpu"):
    state = torch.load(path, map_location="cpu", weights_only=True)
    if state.get("kind") != "mean_anchored_nafnet_v4" or state["config"] != CONFIG or state["contract"] != CONTRACT:
        raise ValueError("Expected the explicit v4 anchored architecture and mono contract")
    model = MeanAnchoredDenoiser(state["parent"], state["alpha"])
    model.student.load_state_dict(state["student"])
    return model.to(device).eval()


def run(args):
    if not 1 <= args.steps <= 6000:
        raise ValueError("This preregistered run is bounded to at most 6000 steps")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA training device is required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(args.output.parent).free < 80*1024**3:
        raise RuntimeError("80 GiB free-disk reserve required")
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
    bank, observed_banks, provenance = load_banks(args.scenes)
    free_cuda, total_cuda = torch.cuda.mem_get_info()
    meminfo = dict(line.split(":",1) for line in Path("/proc/meminfo").read_text().splitlines())
    plan = dict(schema_version=1, task="denoise", status="experimental", release_approved=False,
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
    save_json(args.output/"plan.json",plan)
    model = MeanAnchoredDenoiser(parent_state["model"]).cuda()
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
    with (args.output/"metrics.jsonl").open("x") as stream:
        for step in range(1,args.steps+1):
            optimization_start = time.perf_counter()
            model.train()
            model.parent.eval()
            group = SCHEDULE[(step-1)%len(SCHEDULE)]
            if group == "original_replay":
                inp,target = sample(4,"cuda",generator,"denoise",bank)
            else:
                target = clean_batch(4,generator,bank)
                inp = add_noise(target,generator,group)
            x,y,_,_ = normalize(inp,target)
            optimizer.zero_grad(set_to_none=True)
            prediction,reference = model(x,return_reference=True)
            loss = preservation_loss(prediction,y,reference,replay=group=="original_replay")
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.student.parameters(),.25)
            optimizer.step()
            scheduler.step()
            torch.cuda.synchronize()
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
