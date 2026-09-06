"""Real HST scene adaptation with added noise; targets retain observational noise."""
import json
from pathlib import Path
import time
import numpy as np
from astropy.io import fits
import torch
from training.vendor.nafnet_upstream import NAFNet


def prepare(root):
    rng = np.random.default_rng(6291)
    patches = {"train": [], "validation": []}
    provenance = []
    for group in sorted(root.iterdir()):
        if not group.is_dir():
            continue
        for metadata in sorted(group.glob("*.fits.json"))[:2]:
            record = json.loads(metadata.read_text())
            split = record["split"]
            if split not in patches:
                continue
            path = Path(str(metadata)[:-5])
            with fits.open(path, memmap=False) as hdus:
                image = np.asarray(hdus["SCI"].data, np.float32)
                valid = np.isfinite(image)
                if "WHT" in hdus:
                    valid &= np.isfinite(hdus["WHT"].data) & (hdus["WHT"].data > 0)
                if "DQ" in hdus:
                    valid &= hdus["DQ"].data == 0
                values = image[valid]
                if not values.size:
                    continue
                low, high = np.percentile(values, [1, 99.8])
                if high <= low:
                    continue
                accepted = []
                for attempt in range(1500):
                    y = int(rng.integers(0, image.shape[0] - 127))
                    x = int(rng.integers(0, image.shape[1] - 127))
                    if not valid[y:y+128, x:x+128].all():
                        continue
                    patch = (image[y:y+128, x:x+128] - low) / (high-low)
                    if patch.max() > 1 or patch.min() < 0 or patch.std() < .001:
                        continue
                    patches[split].append(patch.astype(np.float32))
                    accepted.append([x, y])
                    if len(accepted) >= 24:
                        break
            provenance.append(dict(file=path.name, sha256=record["sha256"], group=group.name,
                                   split=split, patches_xy=accepted, low=float(low), high=float(high)))
            print(group.name, split, len(accepted), "valid patches", flush=True)
    if not all(patches.values()):
        raise RuntimeError("Both independent object groups need usable patches")
    return {key: torch.from_numpy(np.stack(value))[:, None].repeat(1, 3, 1, 1)
            for key, value in patches.items()}, provenance


def main():
    root = Path.home() / "forgepix-training"
    output = root / ("runs/fits-adaptation-" + time.strftime("%Y%m%d-%H%M%S"))
    output.mkdir(exist_ok=False)
    datasets, provenance = prepare(root / "datasets/hst-diverse-001")
    (output / "patch_manifest.json").write_text(json.dumps(provenance, indent=2))
    torch.manual_seed(6291)
    source = root / "runs/multi-task-001/denoise/checkpoint.pt"
    checkpoint = torch.load(source, map_location="cpu", weights_only=False)
    model = NAFNet(**checkpoint["config"]).cuda()
    model.load_state_dict(checkpoint["model"])
    validation = datasets["validation"].cuda()
    generator = torch.Generator(device="cuda").manual_seed(771234)
    noisy_validation = validation + torch.randn(validation.shape, device="cuda", generator=generator) * .015

    def evaluate():
        model.eval()
        predictions = []
        with torch.no_grad():
            for batch in noisy_validation.split(8):
                predictions.append(model(batch))
        prediction = torch.cat(predictions)
        return dict(mse=(prediction-validation).square().mean().item(),
                    mean_bias=(prediction-validation).mean().item())

    before = evaluate()
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5)
    training = datasets["train"].cuda()
    start = time.perf_counter()
    for step in range(1500):
        target = training[torch.randint(len(training), (4,), device="cuda")]
        noise_sigma = torch.rand(4, 1, 1, 1, device="cuda") * .025 + .002
        noisy = target + torch.randn_like(target) * noise_sigma
        optimizer.zero_grad(set_to_none=True)
        loss = (model(noisy)-target).square().mean()
        if not torch.isfinite(loss):
            raise RuntimeError("Non-finite loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1)
        optimizer.step()
        if step % 100 == 0:
            print(step, loss.item(), flush=True)
    after = evaluate()
    report = dict(status="experimental_real_scenes_added_gaussian_noise", steps=1500,
        seconds=time.perf_counter()-start, patch_counts={k: len(v) for k,v in datasets.items()},
        identity_mse=(noisy_validation-validation).square().mean().item(), before=before, after=after,
        improved_over_parent=after["mse"] < before["mse"], release_approved=False,
        limitations="Original HST noise remains in targets. Monochrome repeated into RGB. No real independent noise-pair or camera-general evaluation.")
    torch.save(dict(model=model.state_dict(), config=checkpoint["config"], report=report), output / "checkpoint.pt")
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
