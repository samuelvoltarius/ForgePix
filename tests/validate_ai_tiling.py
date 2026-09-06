"""Opt-in scientific smoke check of actual bundled ONNX restoration.

This is deliberately outside unittest discovery. It does not train, download,
promote or modify models. One independent 576x640 scene per task is processed
through the application's real ai_restore.restore path on CPU, at full strength.

Example::

    python tests/validate_ai_tiling.py --tasks denoise starless --output NEW.json

Add --phase-check for a second, circularly shifted view of each same scene. Its
pixel distribution and normalization are unchanged; the aligned interior output
is compared, with explicit limits on separating tile phase from boundary context.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
import ai_restore

SEED = 8803142
HEIGHT, WIDTH = 576, 640
TASKS = ("denoise", "background", "deblur", "starless")


def _hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _blur(image, sigma):
    radius = max(1, math.ceil(4 * sigma))
    axis = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (axis / sigma) ** 2)
    kernel /= kernel.sum()
    h, w = image.shape
    padded = np.pad(image, ((radius, radius), (0, 0)), mode="reflect")
    result = sum(value * padded[index:index + h] for index, value in enumerate(kernel))
    padded = np.pad(result, ((0, 0), (radius, radius)), mode="reflect")
    return sum(value * padded[:, index:index + w] for index, value in enumerate(kernel)).astype(np.float32)


def scene(task):
    """Known Gaussian/Moffat stars, faint filaments and nebula; no training imports."""
    if task not in TASKS:
        raise ValueError("Unknown task")
    rng = np.random.default_rng(SEED)
    yy, xx = np.mgrid[:HEIGHT, :WIDTH].astype(np.float64)
    structure = np.zeros((HEIGHT, WIDTH), np.float64)
    for cx, cy, sx, sy, amplitude in ((315, 295, 95, 52, .016), (205, 365, 53, 80, .009),
                                     (450, 245, 56, 45, .006)):
        structure += amplitude * np.exp(-.5 * (((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2))
    for shift, amplitude, width in ((0, .003, 2.2), (75, .0015, 1.5)):
        line = 245 + shift + 35 * np.sin(xx / 73 + .6)
        structure += amplitude * np.exp(-.5 * ((yy - line) / width) ** 2) * np.exp(-.5 * ((xx - 325) / 135) ** 2)
    nebula = (.018 + structure).astype(np.float32)
    stars = np.zeros_like(nebula)
    star_specs = []
    # Include bright stars close to overlap centres and well away from them.
    for row, cy in enumerate((110, 290, 470)):
        for column, cx in enumerate((110, 192, 280, 384, 470, 575)):
            cx, cy_star = cx + rng.uniform(-.4, .4), cy + rng.uniform(-7, 7)
            fwhm = float(rng.uniform(2.9, 5.2))
            distance2 = (xx - cx) ** 2 + (yy - cy_star) ** 2
            if (row + column) % 2:
                beta = float(rng.uniform(2.6, 3.6))
                alpha = fwhm / (2 * np.sqrt(2 ** (1 / beta) - 1))
                profile = (1 + distance2 / alpha ** 2) ** -beta
                kind = "moffat"
            else:
                profile = np.exp(-distance2 / (2 * (fwhm / 2.354820045) ** 2))
                kind = "gaussian"
            stars += (rng.uniform(.12, .65) * profile).astype(np.float32)
            star_specs.append({"x": float(cx), "y": float(cy_star), "fwhm": fwhm, "kind": kind})
    clean = nebula + stars
    read = rng.normal(0, .003, clean.shape)
    shot = rng.poisson(clean * 4000) / 4000 - clean
    correlated = _blur(rng.normal(size=clean.shape), .8)
    correlated *= .0015 / max(float(correlated.std()), 1e-12)
    if task == "denoise":
        observed, target = clean + read + shot + correlated, clean
        degradation = {"electrons_per_unit": 4000, "read_sigma": .003,
                       "correlated_sigma": .0015, "correlation_gaussian_sigma": .8}
    elif task == "background":
        xn, yn = (xx - WIDTH / 2) / WIDTH, (yy - HEIGHT / 2) / HEIGHT
        gradient = .07 * xn - .055 * yn + .055 * xn * yn
        gradient += .06 * np.exp(-((xn - .6) ** 2 + (yn + .3) ** 2) / .15)
        gradient -= gradient.mean()
        observed, target = clean + gradient, clean
        degradation = {"gradient": "zero-mean plane + cross term + off-axis glow", "noise": "none"}
    elif task == "deblur":
        observed, target = _blur(clean, 1.15) + read * .2, clean
        degradation = {"gaussian_psf_sigma": 1.15, "read_sigma": .0006}
    else:
        observed, target = clean, nebula
        degradation = {"stars": "known Gaussian/Moffat profiles", "noise": "none"}
    star_mask = np.zeros_like(clean, dtype=bool)
    for spec in star_specs:
        star_mask |= ((xx - spec["x"]) ** 2 + (yy - spec["y"]) ** 2 <= (2.5 * spec["fwhm"]) ** 2)
    faint = (structure > .0006) & (structure < .008) & ~star_mask
    blank = (structure < .00015) & (stars < .00001) & ~star_mask
    # Weighted overlap centres in physical image coordinates are multiples of
    # STRIDE; HALO=32 and overlap=64 put the midpoint at these coordinates.
    seam = np.zeros_like(clean, dtype=bool)
    x_centres = list(range(ai_restore.STRIDE, WIDTH, ai_restore.STRIDE))
    y_centres = list(range(ai_restore.STRIDE, HEIGHT, ai_restore.STRIDE))
    for centre in x_centres:
        seam |= np.abs(xx - centre) <= 8
    for centre in y_centres:
        seam |= np.abs(yy - centre) <= 8
    interior = np.zeros_like(clean, dtype=bool)
    interior[64:-64, 64:-64] = True
    return {"input": observed.astype(np.float32), "target": target.astype(np.float32),
            "nebula": nebula, "stars": stars, "star_specs": star_specs,
            "star_mask": star_mask, "faint": faint, "blank": blank,
            "seam": seam & interior, "away": ~seam & interior,
            "seam_x": x_centres, "seam_y": y_centres, "degradation": degradation}


def _stellar_measurements(image, spec):
    """Local-sky aperture flux and radial half-maximum diameter in pixels.

    FWHM is an estimator on sampled profiles, not a fitted optical PSF. Failure
    to find a significant central profile returns None and is counted explicitly.
    """
    radius = max(7, 2.5 * spec["fwhm"])
    outer = int(math.ceil(radius * 2))
    x, y = spec["x"], spec["y"]
    x0, x1 = max(0, int(x) - outer), min(image.shape[1], int(x) + outer + 1)
    y0, y1 = max(0, int(y) - outer), min(image.shape[0], int(y) + outer + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    distance = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    patch = image[y0:y1, x0:x1].astype(np.float64)
    ring = patch[(distance >= radius * 1.5) & (distance <= radius * 2)]
    sky = float(np.median(ring))
    noise = float(np.median(np.abs(ring - sky)) * 1.4826)
    residual = patch - sky
    flux = float(np.sum(residual[distance <= radius]))
    select = distance <= radius
    bins = np.floor(distance[select] / .5).astype(int)
    counts = np.bincount(bins)
    values = np.bincount(bins, weights=residual[select])
    indices = np.flatnonzero(counts)
    radial = indices * .5 + .25
    profile = values[indices] / counts[indices]
    peak_index = int(np.argmax(profile[:min(4, len(profile))]))
    peak = float(profile[peak_index])
    width = None
    if peak > max(3 * noise, 1e-7):
        crossings = np.flatnonzero(profile[peak_index + 1:] <= peak * .5)
        if crossings.size:
            right = int(crossings[0] + peak_index + 1)
            left = right - 1
            fraction = (profile[left] - peak * .5) / max(profile[left] - profile[right], 1e-12)
            width = float(2 * (radial[left] + fraction * (radial[right] - radial[left])))
    return {"aperture_flux": flux, "local_sky": sky, "fwhm_pixels": width}


def measure(image, reference, task):
    image = np.asarray(image, np.float64)
    error = image - reference["target"]
    if image.shape != (HEIGHT, WIDTH) or not np.isfinite(image).all():
        raise ValueError("Runtime returned a wrong shape or non-finite image")

    def mse(mask):
        return float(np.mean(error[mask] ** 2)) if np.any(mask) else None

    def rms(mask):
        value = mse(mask)
        return math.sqrt(value) if value is not None else None

    measures = {"mse": float(np.mean(error ** 2)), "mae": float(np.mean(np.abs(error))),
                "mean_bias": float(np.mean(error)), "faint_nebula_mse": mse(reference["faint"]),
                "blank_region_residual_rms": rms(reference["blank"]),
                "seam_region_mse": mse(reference["seam"]), "away_from_seam_mse": mse(reference["away"]),
                "seam_nonstellar_mse": mse(reference["seam"] & ~reference["star_mask"]),
                "away_nonstellar_mse": mse(reference["away"] & ~reference["star_mask"]),
                "seam_faint_nebula_mse": mse(reference["seam"] & reference["faint"]),
                "away_faint_nebula_mse": mse(reference["away"] & reference["faint"])}
    jump_values = []
    for x in reference["seam_x"]:
        if 64 < x < WIDTH - 64:
            jump_values.extend(np.abs(error[64:-64, x] - error[64:-64, x - 1]).tolist())
    for y in reference["seam_y"]:
        if 64 < y < HEIGHT - 64:
            jump_values.extend(np.abs(error[y, 64:-64] - error[y - 1, 64:-64]).tolist())
    measures["seam_residual_jump_mae"] = float(np.mean(jump_values)) if jump_values else None
    stellar = []
    flux_errors, width_changes = [], []
    for spec in reference["star_specs"]:
        measured = _stellar_measurements(image, spec)
        expected = _stellar_measurements(reference["target"], spec)
        # Normalize against the known star-only aperture flux, so a nebular
        # slope left by local-sky subtraction cannot dilute the relative error.
        original = _stellar_measurements(reference["stars"], spec)
        scale = original["aperture_flux"]
        fraction = ((measured["aperture_flux"] - expected["aperture_flux"]) / scale
                    if scale > 1e-10 else None)
        width_change = None
        if task != "starless" and measured["fwhm_pixels"] is not None and expected["fwhm_pixels"] is not None:
            width_change = measured["fwhm_pixels"] - expected["fwhm_pixels"]
            width_changes.append(width_change)
        if fraction is not None:
            flux_errors.append(fraction)
        stellar.append({**spec, "measured": measured, "target": expected,
                        "flux_error_fraction": fraction, "fwhm_change_pixels": width_change})
    measures["stellar_flux_relative_bias"] = float(np.mean(flux_errors)) if flux_errors else None
    measures["stellar_flux_mean_absolute_error_fraction"] = float(np.mean(np.abs(flux_errors))) if flux_errors else None
    measures["stellar_flux_p95_absolute_error_fraction"] = float(np.percentile(np.abs(flux_errors), 95)) if flux_errors else None
    measures["fwhm_mean_change_pixels"] = float(np.mean(width_changes)) if width_changes else None
    measures["fwhm_mean_absolute_change_pixels"] = float(np.mean(np.abs(width_changes))) if width_changes else None
    measures["fwhm_measured_stars"] = len(width_changes)
    if task == "starless":
        measures["remaining_star_flux_fraction"] = measures["stellar_flux_relative_bias"]
        measures["nebula_mse"] = float(np.mean(error ** 2))
    return {"metrics": measures, "stars": stellar}


def validate(task, model, model_dir=None, phase_check=False):
    reference = scene(task)
    original_hash = hashlib.sha256(reference["input"].tobytes()).hexdigest()
    start = time.perf_counter()
    progress = []
    output = ai_restore.restore(reference["input"], model["id"], model_dir=model_dir,
                                strength=1, allow_experimental=True, log=print,
                                progress=lambda done, total: progress.append((done, total)))
    if hashlib.sha256(reference["input"].tobytes()).hexdigest() != original_hash:
        raise RuntimeError("Runtime modified the original input array")
    results = {"input": measure(reference["input"], reference, task),
               "restored": measure(output, reference, task)}
    manifest_path = Path(model["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    item = {"model_id": model["id"], "manifest_sha256": _hash(manifest_path),
            "model_sha256": manifest["sha256"], "checkpoint_sha256": manifest.get("checkpoint_sha256"),
            "task": task, "input_sha256": original_hash,
            "target_sha256": hashlib.sha256(reference["target"].tobytes()).hexdigest(),
            "shape": [HEIGHT, WIDTH], "degradation": reference["degradation"],
            "strength": 1.0, "runtime": "ai_restore.restore, CPUExecutionProvider",
            "inference_strategy": manifest.get("inference",{}).get("strategy","overlapping_tiles"),
            "inference_calls": progress[-1][1] if progress else None,
            "seam_metrics_applicable": task != "background",
            "seam_centres": {"x": reference["seam_x"], "y": reference["seam_y"],
                             "half_width": 8, "edge_exclusion": 64},
            "roi_pixels": {name: int(reference[name].sum()) for name in ("faint", "blank", "seam", "away")},
            "results": results}
    if phase_check:
        shift = (37, 71)
        shifted = np.roll(reference["input"], shift, axis=(0, 1))
        np.testing.assert_array_equal(np.percentile(reference["input"], [.1, 99.9]),
                                      np.percentile(shifted, [.1, 99.9]))
        shifted_output = ai_restore.restore(shifted, model["id"], model_dir=model_dir,
                                            strength=1, allow_experimental=True, log=print)
        aligned = np.roll(shifted_output, (-shift[0], -shift[1]), axis=(0, 1))
        interior = np.s_[128:-128, 128:-128]
        difference = aligned[interior].astype(np.float64) - output[interior]
        target = reference["target"][interior]
        item["phase_check"] = {
            "shift_yx": list(shift), "same_pixel_distribution_and_percentiles": True,
            "interior_edge_exclusion": 128, "comparison_shape": list(difference.shape),
            "aligned_output_difference_rms": float(np.sqrt(np.mean(difference ** 2))),
            "aligned_output_difference_maximum": float(np.max(np.abs(difference))),
            "original_interior_mse": float(np.mean((output[interior] - target) ** 2)),
            "shifted_interior_mse": float(np.mean((aligned[interior] - target) ** 2)),
            "limitation": "Circular relocation also changes boundary context. Interior exclusion reduces but does not prove elimination of that influence with global channel attention.",
        }
    item["seconds"] = time.perf_counter() - start
    return item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", "--task", nargs="+", choices=("all", *TASKS), default=["all"])
    parser.add_argument("--output", type=Path, required=True, help="New JSON report; never overwritten")
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--phase-check", action="store_true", help="One extra rolled-view runtime inference per task")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; select a new report path")
    selected = list(TASKS) if "all" in args.tasks else list(dict.fromkeys(args.tasks))
    catalogue = ai_restore.list_models(args.model_dir)
    models = {}
    for task in selected:
        matches = [model for model in catalogue if model.get("available") and model.get("task") == task]
        if len(matches) != 1:
            parser.error("Expected exactly one available model for task %s; found %s" % (task, len(matches)))
        models[task] = matches[0]
    report = {
        "status": "experimental_actual_runtime_check", "release_approved": False,
        "production_approved": False, "seed": SEED, "scene_shape": [HEIGHT, WIDTH],
        "scenes_per_task": 1, "tasks": selected, "phase_check_enabled": args.phase_check,
        "script_sha256": _hash(Path(__file__)), "runtime_source_sha256": _hash(Path(ai_restore.__file__)),
        "numpy_version": np.__version__, "results": {},
        "limitations": [
            "One analytic scene per task is a scientific smoke check, not statistical qualification or real-camera validation.",
            "Seam and non-seam regions have different scene content. Their error ratio alone does not prove or exclude stitching artifacts.",
            "Global background inference has no tile seams; seam-labelled ROIs are just fixed spatial regions for that task, not a stitching assessment.",
            "FWHM is a sampled radial half-maximum estimator with local-sky subtraction, not a PSF fit. Starless FWHM changes are not meaningful and are not aggregated.",
            "Blank-region RMS includes residual noise/gradient; it cannot alone establish whether astronomical structure was invented.",
            "Known input/target pixels are linear floats. No JPEG, stretch, clipping or external application participates in inference.",
            "The script never promotes models. All outputs remain explicitly experimental, regardless of numerical improvement.",
        ],
    }
    for task in selected:
        print("Evaluating actual local runtime:", task, flush=True)
        item = validate(task, models[task], args.model_dir, args.phase_check)
        report["results"][task] = item
        print(json.dumps({"task": task, "input_mse": item["results"]["input"]["metrics"]["mse"],
                          "restored_mse": item["results"]["restored"]["metrics"]["mse"],
                          "seconds": item["seconds"]}), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps({"report": str(args.output.resolve()), "release_approved": False}), flush=True)


if __name__ == "__main__":
    main()
