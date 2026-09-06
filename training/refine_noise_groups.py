"""Bounded denoiser research with separate noise/object gates; never promotes.

The final evaluator is a different, unchanged generator. Its seed is committed
to the run plan before optimization; results may only reject this experiment.
Observed HST targets retain their original noise and are not clean truth.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time

import numpy as np
import torch
import torch.nn.functional as F

from training.train_restoration import CONFIG, CONTRACT, sample, normalize, loss_function
from training.vendor.nafnet_upstream import NAFNet


TRAIN_SEED = 609063
DEVELOPMENT_SEED = 830124
FINAL_SEED = 9518063
GROUPS = ("identity", "low_noise", "read_dominated", "shot_dominated",
          "correlated_small", "correlated_medium", "correlated_large", "row_noise")
METRICS = ("mse", "mae", "absolute_image_bias", "local_mean_rms")
GATE_FLOORS = dict(mse=1e-12, mae=1e-8, absolute_image_bias=1e-8, local_mean_rms=1e-8)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def add_noise(clean, generator, group):
    """Independent read/shot/correlated amplitudes, not a fixed fraction of read.

    Gaussian correlation sigma ranges from 0.35 to 5 pixels. Kernels have unit
    sum, then their realized noise is standardized per image before amplitude.
    Row/column components vary independently; signed clean values are retained.
    """
    if group not in GROUPS:
        raise ValueError("Unknown noise group")
    if group == "identity":
        return clean.clone()
    batch, _, height, width = clean.shape
    shape = (batch, 1, 1, 1)
    def uniform(low, high):
        return torch.rand(shape, device=clean.device, generator=generator) * (high-low) + low
    def log_uniform(low, high):
        return 10 ** uniform(math.log10(low), math.log10(high))
    def white(shape):
        return torch.randn(shape, device=clean.device, generator=generator)
    electrons = log_uniform(2000, 100000)
    read_sigma = log_uniform(.0003, .003)
    if group == "low_noise":
        electrons, read_sigma = log_uniform(15000, 150000), log_uniform(.0001, .001)
    elif group == "read_dominated":
        electrons, read_sigma = log_uniform(15000, 150000), log_uniform(.002, .012)
    elif group == "shot_dominated":
        electrons, read_sigma = log_uniform(300, 2000), log_uniform(.0001, .002)
    positive = clean.clamp_min(0)
    noisy = clean + torch.poisson(positive*electrons, generator=generator)/electrons-positive
    noisy += white(clean.shape)*read_sigma
    if group.startswith("correlated_"):
        bounds = {"correlated_small": (.35, 1.0), "correlated_medium": (1.0, 2.5),
                  "correlated_large": (2.5, 5.0)}[group]
        sigma = float(uniform(*bounds)[0].item())
        radius = math.ceil(4*sigma)
        axis = torch.arange(-radius, radius+1, device=clean.device)
        kernel = torch.exp(-.5*(axis/sigma).square())
        kernel /= kernel.sum()
        noise = white(clean.shape)
        noise = F.conv2d(F.pad(noise, (radius, radius, 0, 0), mode="reflect"), kernel[None,None,None,:])
        noise = F.conv2d(F.pad(noise, (0, 0, radius, radius), mode="reflect"), kernel[None,None,:,None])
        noise -= noise.mean((-2,-1), keepdim=True)
        noise /= noise.std((-2,-1), keepdim=True).clamp_min(1e-6)
        noisy += noise*log_uniform(.0004, .012)
    if group == "row_noise":
        noisy += white((batch,1,height,1))*log_uniform(.0004, .008)
        noisy += white((batch,1,1,width))*log_uniform(.0001, .003)
    return noisy


def clean_batch(batch, generator, bank=None, force_observed=False):
    _, clean = sample(batch, "cuda", generator, "denoise", None)
    if bank is not None:
        indices = torch.randint(len(bank), (batch,), device="cuda", generator=generator)
        observed = bank[indices]
        if torch.rand((), device="cuda", generator=generator) < .5:
            observed = observed.flip(-1)
        if torch.rand((), device="cuda", generator=generator) < .5:
            observed = observed.transpose(-1,-2)
        shape = (batch,1,1,1)
        observed = observed*(torch.rand(shape, device="cuda", generator=generator)*.5+.05)
        observed += (torch.rand(shape, device="cuda", generator=generator)-.5)*.025
        use = torch.rand(shape, device="cuda", generator=generator) < .25
        clean = observed if force_observed else torch.where(use, observed, clean)
    return clean


def development_cases(observed_banks):
    generator = torch.Generator(device="cuda").manual_seed(DEVELOPMENT_SEED)
    cases = {}
    for domain, bank in [("synthetic", None), *sorted(observed_banks.items())]:
        for group in GROUPS:
            clean = clean_batch(16, generator, bank, force_observed=bank is not None)
            cases[f"{domain}/{group}"] = (add_noise(clean, generator, group), clean)
    return cases


@torch.no_grad()
def evaluate_groups(model, cases):
    model.eval()
    result = {}
    for name, (inputs, targets) in cases.items():
        rows = []
        for inp, target in zip(inputs.split(4), targets.split(4)):
            x, _, offset, scale = normalize(inp, target)
            error = model(x)*scale+offset-target
            flat = error.flatten(1)
            local = F.avg_pool2d(error, 16, 16).flatten(1)
            rows.append(torch.stack((flat.square().mean(1), flat.abs().mean(1),
                flat.mean(1).abs(), local.square().mean(1).sqrt()), dim=1).cpu().numpy())
        result[name] = dict(zip(METRICS, np.concatenate(rows).mean(0).tolist()), scenes=len(inputs))
    return result


def gate_comparison(candidate, parent):
    failures = []
    ratios = []
    for group, baseline in parent.items():
        ratios.append(candidate[group]["mse"]/max(baseline["mse"], 1e-12))
        for metric in METRICS:
            limit = baseline[metric] + GATE_FLOORS[metric]
            if candidate[group][metric] > limit:
                failures.append(dict(group=group, metric=metric, candidate=candidate[group][metric],
                                     parent=baseline[metric], limit=limit))
    score = float(np.exp(np.log(np.maximum(ratios, 1e-12)).mean()))
    return dict(passes_all_groups=not failures, geometric_group_mse_ratio=score, failures=failures)


def load_banks(root):
    manifest_path = root/"manifest.json"
    manifest = json.loads(manifest_path.read_text())
    splits, seen_hashes, groups = {}, {}, {}
    cursor = 0
    val_indices = {}
    for record in manifest["records"]:
        group, split, sha = record["group"], record["split"], record["sha256"]
        if record["rights"] != "PUBLIC":
            raise ValueError("Unreviewed source rights")
        if group in splits and splits[group] != split or sha in seen_hashes and seen_hashes[sha] != split:
            raise ValueError("Object or source hash crosses splits")
        splits[group], seen_hashes[sha] = split, split
        groups.setdefault(split, set()).add(group)
        if split == "validation":
            count = len(record["patches_xy"])
            val_indices.setdefault(group, []).extend(range(cursor, cursor+count))
            cursor += count
    train = np.load(root/"train.npy")
    validation = np.load(root/"validation.npy")
    if len(train) != manifest["counts"]["train"] or cursor != len(validation):
        raise ValueError("Scene bank/manifest count mismatch")
    if not np.isfinite(train).all() or not np.isfinite(validation).all():
        raise ValueError("Scene bank has non-finite pixels")
    provenance = dict(manifest_sha256=digest(manifest_path), train_sha256=digest(root/"train.npy"),
        validation_sha256=digest(root/"validation.npy"), counts=manifest["counts"],
        objects={key: sorted(value) for key,value in groups.items()},
        source_noise_retained=True, independent_exposure_pairs=False,
        source_files=[dict(uri=row["uri"], sha256=row["sha256"], split=row["split"],
                           group=row["group"], rights=row["rights"], policy=row["policy"]) for row in manifest["records"]])
    banks = {group: torch.from_numpy(validation[indices])[:,None].cuda() for group,indices in val_indices.items()}
    return torch.from_numpy(train)[:,None].cuda(), banks, provenance


def run(args):
    if not 1 <= args.steps <= 8000:
        raise ValueError("Bounded run requires 1..8000 steps")
    if not torch.cuda.is_available():
        raise RuntimeError("This training run requires a CUDA GPU")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(args.output.parent).free < 80*1024**3:
        raise RuntimeError("80 GiB free-disk reserve required")
    lock = args.output.parent/"restoration-training.lock"
    with lock.open("x") as stream:
        json.dump(dict(pid=os.getpid(), output=str(args.output), started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), stream)
    try:
        train(args)
    finally:
        lock.unlink(missing_ok=True)


def train(args):
    args.output.mkdir(exist_ok=False)
    torch.set_num_threads(4)
    torch.manual_seed(TRAIN_SEED)
    generator = torch.Generator(device="cuda").manual_seed(TRAIN_SEED)
    checkpoint = torch.load(args.parent, map_location="cpu", weights_only=False)
    if checkpoint["config"] != CONFIG or checkpoint.get("contract") != CONTRACT:
        raise ValueError("Only the unchanged mono-v2 parent contract is accepted")
    train_bank, observed_banks, provenance = load_banks(args.scenes)
    plan = dict(schema_version=1, task="denoise", status="experimental", release_approved=False,
        steps=args.steps, batch=4, training_seed=TRAIN_SEED, development_seed=DEVELOPMENT_SEED,
        reserved_final_seed=FINAL_SEED, reserved_final_scenes=128,
        device=dict(type="cuda", name=torch.cuda.get_device_name(), cuda_version=torch.version.cuda,
                    torch_version=str(torch.__version__), cudnn_version=torch.backends.cudnn.version()),
        parent_checkpoint_sha256=digest(args.parent), training_source_sha256=digest(__file__),
        scene_generator_source_sha256=digest(Path(__file__).with_name("train_restoration.py")),
        final_evaluator_source_sha256=digest(Path(__file__).with_name("evaluate_models.py")),
        provenance=provenance, group_names=list(GROUPS),
        gates=dict(rule="Every development group must be no worse than unchanged mono parent on every metric; floors are numerical only",
                   metrics=list(METRICS), absolute_numerical_floors=GATE_FLOORS, maximum_ratio=1.0,
                   final_rule="Independent final overall and each noise-class MSE must not regress; overall absolute stellar flux error, faint-structure MSE and absolute image bias must not regress. No automatic deployment."),
        limitations="Observed HST scene targets retain their noise; no independent clean/noisy exposures, real-camera qualification, full-image tiling qualification or automatic promotion.")
    save_json(args.output/"plan.json", plan)
    model = NAFNet(**CONFIG).cuda()
    model.load_state_dict(checkpoint["model"])
    cases = development_cases(observed_banks)
    parent_scores = evaluate_groups(model, cases)
    save_json(args.output/"parent_development.json", parent_scores)
    shutil.copyfile(args.parent, args.output/"checkpoint.pt")
    optimizer = torch.optim.AdamW(model.parameters(), lr=4e-5)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, args.steps, eta_min=4e-6)
    started = time.perf_counter()
    best_score, best_step, accepted_step = float("inf"), 0, 0
    best_validation = None
    accepted_score = 1.0
    validations = []
    with (args.output/"metrics.jsonl").open("x") as stream:
        for step in range(1, args.steps+1):
            model.train()
            group = GROUPS[(step-1) % len(GROUPS)]
            target = clean_batch(4, generator, train_bank)
            inp = add_noise(target, generator, group)
            x, y, _, _ = normalize(inp, target)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(x), y)
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
            optimizer.step()
            scheduler.step()
            if step == 1 or step % 100 == 0:
                row = dict(step=step, group=group, loss=float(loss.detach()), seconds=time.perf_counter()-started)
                stream.write(json.dumps(row)+"\n"); stream.flush()
                print(json.dumps(row), flush=True)
            if step % 1000 == 0 or step == args.steps:
                validation = evaluate_groups(model, cases)
                gate = gate_comparison(validation, parent_scores)
                result = dict(step=step, gate=gate, validation=validation)
                validations.append(result)
                save_json(args.output/f"development-{step:05d}.json", result)
                score = gate["geometric_group_mse_ratio"]
                state = dict(model=model.state_dict(), config=CONFIG, contract=CONTRACT,
                             report=dict(task="denoise", step=step, validation=validation, release_approved=False))
                if score < best_score:
                    best_score, best_step, best_validation = score, step, validation
                    torch.save(state, args.output/"candidate.pt")
                if gate["passes_all_groups"] and score < accepted_score:
                    accepted_step, accepted_score = step, score
                    torch.save(state, args.output/"checkpoint.pt")
                print(json.dumps(dict(step=step, score=score, gate_pass=gate["passes_all_groups"],
                                      failed_metrics=len(gate["failures"]), accepted_step=accepted_step)), flush=True)
    report = dict(plan, seconds=time.perf_counter()-started, best_step=best_step,
        best_research_candidate_sha256=digest(args.output/"candidate.pt"),
        development_selected_step=accepted_step, development_selected_sha256=digest(args.output/"checkpoint.pt"),
        development_decision="research_candidate_only" if accepted_step else "retain_unchanged_parent",
        validation=best_validation, parent_validation=parent_scores,
        candidate_gates=gate_comparison(best_validation, parent_scores),
        validation_checkpoints=[dict(step=row["step"], gate=row["gate"]) for row in validations])
    save_json(args.output/"report.json", report)
    print(json.dumps(dict(report=str(args.output/"report.json"), best_step=best_step,
                         development_selected_step=accepted_step, seconds=report["seconds"])), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--scenes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=6000)
    run(parser.parse_args())
