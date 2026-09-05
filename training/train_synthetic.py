"""Reproducible NAFNet engineering baseline, not a production astronomy model.

Run from the repository root: python -m training.train_synthetic --output RUN_DIR
No pretrained weights, user images, or external applications are used.
"""
import argparse
import json
import time
from pathlib import Path

import torch
from training.vendor.nafnet_upstream import NAFNet


def sample(batch, size, device, generator, task="denoise"):
    """Linear scenes with stars, diffuse structure and varying shot/read noise.

    Parameters cover multiple synthetic observing conditions, not verified camera
    profiles. Background is part of the clean target and must be preserved.
    """
    def rand(*shape):
        return torch.rand(shape, device=device, generator=generator)
    grid = torch.linspace(-1, 1, size, device=device)
    yy, xx = torch.meshgrid(grid, grid, indexing="ij")
    clean = rand(batch, 3, 1, 1) * 0.02
    clean = clean.expand(batch, 3, size, size).clone()
    diffuse = clean.clone()
    for _ in range(20):
        cx, cy = rand(batch, 1, 1, 1) * 2 - 1, rand(batch, 1, 1, 1) * 2 - 1
        sigma = (rand(batch, 1, 1, 1) * 2.5 + 0.7) * 2 / size
        star = torch.exp(-((xx - cx).square() + (yy - cy).square()) / (2 * sigma.square()))
        clean += star * rand(batch, 3, 1, 1) * 0.7
    for _ in range(3):
        cx, cy = rand(batch, 1, 1, 1) * 2 - 1, rand(batch, 1, 1, 1) * 2 - 1
        sigma = rand(batch, 1, 1, 1) * 0.4 + 0.1
        nebula = torch.exp(-((xx - cx).square() + (yy - cy).square()) / (2 * sigma.square())) * rand(batch, 3, 1, 1) * 0.06
        clean += nebula
        diffuse += nebula
    clean = clean.clamp(0, 1)
    if task == "background":
        gradient = (xx + 1) * rand(batch, 3, 1, 1) * .04
        gradient += (yy + 1) * rand(batch, 3, 1, 1) * .04
        gradient += (xx.square() + yy.square()) * rand(batch, 3, 1, 1) * .03
        return clean + gradient, clean
    if task == "deblur":
        # A known isotropic PSF baseline; not a model of field-dependent aberrations.
        sigma = .5 + float(rand(1).item()) * 1.5
        axis = torch.arange(-6, 7, device=device)
        kernel = torch.exp(-axis.square() / (2 * sigma ** 2))
        kernel = kernel[:, None] * kernel[None, :]
        kernel = (kernel / kernel.sum()).expand(3, 1, 13, 13)
        blurred = torch.nn.functional.conv2d(
            torch.nn.functional.pad(clean, (6, 6, 6, 6), mode="reflect"), kernel, groups=3)
        return blurred, clean
    if task == "starless":
        return clean, diffuse
    if task != "denoise":
        raise ValueError("Unknown training task")
    electrons = 10 ** (rand(batch, 1, 1, 1) * 2 + 2.5)
    read_noise = rand(batch, 1, 1, 1) * 0.008 + 0.0005
    noisy = torch.poisson(clean * electrons, generator=generator) / electrons
    noisy += torch.randn(clean.shape, device=device, generator=generator) * read_noise
    return noisy, clean


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--task", choices=["denoise", "background", "deblur", "starless"], default="denoise")
    args = parser.parse_args()
    if args.steps < 1 or args.size < 16 or args.batch < 1:
        parser.error("steps/batch must be positive; size must be at least 16")
    args.output.mkdir(parents=True, exist_ok=False)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(20260905)
    generator = torch.Generator(device=device).manual_seed(20260905)
    validation_generator = torch.Generator(device=device).manual_seed(314159)
    config = dict(img_channel=3, width=16, middle_blk_num=2,
                  enc_blk_nums=[1, 1, 2], dec_blk_nums=[1, 1, 1])
    model = NAFNet(**config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.0002)
    start = time.perf_counter()
    with (args.output / "metrics.jsonl").open("w") as log:
        for step in range(1, args.steps + 1):
            noisy, clean = sample(args.batch, args.size, device, generator, args.task)
            optimizer.zero_grad(set_to_none=True)
            loss = (model(noisy) - clean).square().mean()
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            if step == 1 or step % 25 == 0 or step == args.steps:
                item = dict(step=step, mse=loss.item(), elapsed_seconds=time.perf_counter() - start)
                print(json.dumps(item), flush=True)
                log.write(json.dumps(item) + "\n")
                log.flush()
        model.eval()
        with torch.no_grad():
            measurements = []
            for _ in range(8):
                noisy, clean = sample(4, args.size, device, validation_generator, args.task)
                result = model(noisy)
                measurements.append(dict(input_mse=(noisy-clean).square().mean().item(),
                                         output_mse=(result-clean).square().mean().item(),
                                         mean_bias=(result-clean).mean().item()))
            validation = {key: sum(item[key] for item in measurements) / len(measurements)
                          for key in measurements[0]}
            validation["samples"] = 32
    report = dict(status="experimental_synthetic_only", config=config,
                  task=args.task, steps=args.steps, batch=args.batch, size=args.size,
                  seconds=time.perf_counter()-start, device=device,
                  torch_version=torch.__version__, validation=validation,
                  release_approved=False)
    torch.save(dict(model=model.state_dict(), config=config,
                    optimizer=optimizer.state_dict(), report=report), args.output / "checkpoint.pt")
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
