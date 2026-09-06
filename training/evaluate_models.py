"""Independent fixed-scene evaluation of experimental ForgePix restoration models.

This module deliberately does not import the training scene generator. Its seed
and scenes are a holdout: do not train on them or repeatedly tune against their
results. Passing this synthetic evaluation never approves a production model.

Example (from the repository root)::

    python -m training.evaluate_models --candidate runs/new/checkpoint.pt \
        --parent runs/old/checkpoint.pt --task denoise --output evaluation.json

The candidate uses input-derived affine normalization v1 (p0.1, p99.9, scalar
scale >= 1e-6). The original three-channel parent receives the same physical mono
input in all three channels, including exactly the same noise realization.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np


HOLDOUT_SEED = 9237401
SCENE_SIZE = 256
MIN_SCENES = 64
TASKS = ("denoise", "background", "deblur", "starless")
NORMALIZATION = {
    "version": 1,
    "kind": "input_percentile_affine",
    "percentiles": [0.1, 99.9],
    "minimum_scale": 1e-6,
    "clip": False,
    "statistics_scope": "entire 256x256 input scene, scalar shared by all channels",
}
MODEL_CONTRACT = {"channels": 1, "tile_size": 256, "halo": 32,
                  "normalization": "affine_percentile_v1", "output": "complete_target"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_v1(image):
    """Return an affine-normalized input and the exact inverse parameters."""
    image = np.asarray(image, dtype=np.float32)
    if image.shape != (SCENE_SIZE, SCENE_SIZE) or not np.isfinite(image).all():
        raise ValueError("Evaluation input must be finite 256x256 mono data")
    low, high = np.percentile(image.astype(np.float64), [0.1, 99.9])
    scale = max(float(high - low), 1e-6)
    return ((image.astype(np.float64) - low) / scale).astype(np.float32), float(low), scale


def _gaussian_blur(image, sigma):
    """Separable Gaussian convolution; only NumPy is required by the generator."""
    radius = max(1, int(math.ceil(4 * sigma)))
    axis = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (axis / sigma) ** 2)
    kernel /= kernel.sum()
    height, width = image.shape
    padded = np.pad(image, ((radius, radius), (0, 0)), mode="reflect")
    vertical = np.zeros((height, width), np.float64)
    for offset, value in enumerate(kernel):
        vertical += value * padded[offset:offset + height, :]
    padded = np.pad(vertical, ((0, 0), (radius, radius)), mode="reflect")
    result = np.zeros((height, width), np.float64)
    for offset, value in enumerate(kernel):
        result += value * padded[:, offset:offset + width]
    return result.astype(np.float32)


def make_scene(index, task):
    """Analytic stars, extended emission and filaments, independent of training.

    Non-denoising tasks include both noiseless and noisy stress cases. Background
    removal and star separation targets retain the *same* additive observation
    noise; they are not silently assessed as simultaneous denoisers. Deblurring
    uses a noiseless known target and reports the noisy cases separately.
    """
    if task not in TASKS or index < 0:
        raise ValueError("Invalid task or scene index")
    rng = np.random.default_rng(np.random.SeedSequence([HOLDOUT_SEED, int(index)]))
    size = SCENE_SIZE
    yy, xx = np.mgrid[:size, :size].astype(np.float64)
    xn, yn = (xx - size / 2) / size, (yy - size / 2) / size
    brightness = (0.25, 0.65, 1.0, 1.6)[(index // 4) % 4]
    morphology = "dense_moffat" if (index // 2) % 2 else "sparse_gaussian"
    background = float(rng.uniform(0.008, 0.025) * brightness)
    structure = np.zeros((size, size), np.float64)
    for _ in range(2):
        cx, cy = rng.uniform(60, 196, 2)
        angle = rng.uniform(0, np.pi)
        major, minor = rng.uniform(25, 65), rng.uniform(10, 28)
        dx, dy = xx - cx, yy - cy
        u, v = dx * np.cos(angle) + dy * np.sin(angle), -dx * np.sin(angle) + dy * np.cos(angle)
        structure += rng.uniform(0.008, 0.03) * np.exp(-0.5 * ((u / major) ** 2 + (v / minor) ** 2))
    for _ in range(2):
        centre = rng.uniform(65, 190)
        line = centre + rng.uniform(8, 25) * np.sin(xx / rng.uniform(20, 55) + rng.uniform(0, 6))
        filament = np.exp(-0.5 * ((yy - line) / rng.uniform(1.3, 3.5)) ** 2)
        envelope = np.exp(-0.5 * ((xx - rng.uniform(80, 180)) / rng.uniform(35, 65)) ** 2)
        structure += rng.uniform(0.002, 0.009) * filament * envelope
    structure *= brightness
    nebula = background + structure
    stars = np.zeros_like(structure)
    star_parameters = []
    for _ in range(42 if morphology == "dense_moffat" else 16):
        cx, cy = rng.uniform(16, size - 16, 2)
        fwhm = float(rng.uniform(1.9, 4.7))
        radius2 = (xx - cx) ** 2 + (yy - cy) ** 2
        if morphology == "dense_moffat":
            beta = rng.uniform(2.3, 4.2)
            alpha = fwhm / (2 * np.sqrt(2 ** (1 / beta) - 1))
            profile = (1 + radius2 / alpha ** 2) ** (-beta)
        else:
            profile = np.exp(-radius2 / (2 * (fwhm / 2.354820045) ** 2))
        amplitude = float(10 ** rng.uniform(-1.65, -0.12) * brightness)
        stars += profile * amplitude
        star_parameters.append((float(cx), float(cy), fwhm))
    clean = (nebula + stars).astype(np.float32)
    nebula = nebula.astype(np.float32)
    stars = stars.astype(np.float32)

    noise_class = ("low_noise", "read_dominated", "shot_dominated", "correlated")[(index // 16) % 4]
    electrons, read_sigma = {
        "low_noise": (16000.0, 0.0007),
        "read_dominated": (10000.0, 0.006),
        "shot_dominated": (600.0, 0.001),
        "correlated": (5000.0, 0.003),
    }[noise_class]
    shot = rng.poisson(np.maximum(clean, 0) * electrons) / electrons - clean
    read = rng.normal(0, read_sigma, clean.shape)
    if noise_class == "correlated":
        correlated = _gaussian_blur(rng.normal(size=clean.shape), 0.75)
        correlated /= max(float(correlated.std()), 1e-12)
        read += correlated * 0.004
    noise = (shot + read).astype(np.float32)
    noise_condition = "observational_noise"
    if task != "denoise" and index % 2 == 0:
        noise = np.zeros_like(noise)
        noise_condition = "noiseless"
    gradient_kind = ("plane", "curved", "off_axis_glow", "vignette_like")[index % 4]
    psf_sigma = float((0.65, 1.05, 1.5, 2.1)[index % 4])
    if task == "denoise":
        observed, target = clean + noise, clean
    elif task == "background":
        a, b = rng.uniform(-0.1, 0.1, 2)
        gradient = a * xn + b * yn
        if gradient_kind == "curved":
            gradient += rng.uniform(-0.08, 0.08) * (xn ** 2 - yn ** 2) + 0.045 * xn * yn
        elif gradient_kind == "off_axis_glow":
            gradient += 0.13 * np.exp(-((xn - 0.7) ** 2 + (yn + 0.35) ** 2) / 0.12)
        elif gradient_kind == "vignette_like":
            gradient += 0.1 * ((xn + 0.15) ** 2 + (yn - 0.2) ** 2)
        # Absolute additive pedestal is underdetermined; holdout defines zero-
        # mean gradient so that legitimate constant sky remains in the target.
        gradient = (gradient - gradient.mean()).astype(np.float32)
        observed, target = clean + noise + gradient, clean + noise
    elif task == "deblur":
        observed, target = _gaussian_blur(clean, psf_sigma) + noise, clean
    else:
        observed, target = clean + noise, nebula + noise
    star_mask = np.zeros((size, size), bool)
    apertures = []
    for cx, cy, fwhm in star_parameters:
        radius = max(5.0, 2.0 * fwhm)
        star_mask |= (xx - cx) ** 2 + (yy - cy) ** 2 <= radius ** 2
        isolated = all((cx - other_x) ** 2 + (cy - other_y) ** 2 > (radius + max(5, 2 * other_w)) ** 2
                       for other_x, other_y, other_w in star_parameters if (other_x, other_y) != (cx, cy))
        if isolated:
            apertures.append((cx, cy, radius))
    peak = max(float(structure.max()), 1e-12)
    faint = (~star_mask) & (structure > peak * 0.035) & (structure < peak * 0.35)
    blank = (~star_mask) & (structure < peak * 0.02) & (stars < 1e-4 * brightness)
    return {
        "input": observed.astype(np.float32), "target": target.astype(np.float32),
        "nebula": nebula, "stars": stars, "star_mask": star_mask,
        "faint_mask": faint, "nebula_mask": structure > peak * 0.035,
        "blank_mask": blank, "apertures": apertures,
        "group": {"noise_class": noise_class, "noise_condition": noise_condition,
                  "morphology": morphology, "brightness": str(brightness),
                  "gradient_kind": gradient_kind if task == "background" else "not_applicable",
                  "psf_sigma": str(psf_sigma) if task == "deblur" else "not_applicable"},
        "parameters": {"index": int(index), "size": size, "electrons_per_unit": electrons,
                       "read_sigma": read_sigma, "stellar_apertures": len(apertures),
                       "faint_pixels": int(faint.sum()), "blank_pixels": int(blank.sum())},
    }


def measure(prediction, scene, task):
    prediction = np.asarray(prediction, dtype=np.float64)
    target = np.asarray(scene["target"], dtype=np.float64)
    if prediction.shape != target.shape or not np.isfinite(prediction).all():
        raise ValueError("Model returned invalid shape or non-finite pixels")
    error = prediction - target

    def masked_mse(mask):
        return float(np.mean(error[mask] ** 2)) if np.any(mask) else None

    blank_mse = masked_mse(scene["blank_mask"])
    metrics = {"mse": float(np.mean(error ** 2)), "mae": float(np.mean(np.abs(error))),
               "mean_bias": float(np.mean(error)),
               "faint_structure_mse": masked_mse(scene["faint_mask"]),
               "blank_region_false_rms": math.sqrt(blank_mse) if blank_mse is not None else None,
               "star_region_mse": masked_mse(scene["star_mask"])}
    yy, xx = np.mgrid[:target.shape[0], :target.shape[1]]
    fractions = []
    for cx, cy, radius in scene["apertures"]:
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius ** 2
        flux = float(np.sum(scene["stars"][mask], dtype=np.float64))
        if flux > 1e-12:
            fractions.append(float(error[mask].sum() / flux))
    if task == "starless":
        metrics["remaining_star_flux_fraction"] = float(np.mean(fractions)) if fractions else None
        metrics["remaining_star_flux_absolute_fraction"] = float(np.mean(np.abs(fractions))) if fractions else None
        metrics["nebula_mse"] = masked_mse(scene["nebula_mask"])
    else:
        metrics["stellar_aperture_flux_bias_fraction"] = float(np.mean(fractions)) if fractions else None
        metrics["stellar_aperture_flux_absolute_error_fraction"] = float(np.mean(np.abs(fractions))) if fractions else None
    return metrics


class Predictor:
    """Strict local model adapter; no downloads, training or promotion."""

    def __init__(self, path, role, task, device="auto"):
        self.path = Path(path)
        self.role = role
        self.details = {"path": str(self.path.resolve()), "sha256": sha256(self.path), "role": role}
        if self.path.suffix.lower() == ".onnx":
            import onnxruntime as ort
            if role == "candidate":
                manifest = json.loads((self.path.parent / "manifest.json").read_text(encoding="utf-8"))
                if (any(manifest.get(key) != value for key, value in MODEL_CONTRACT.items())
                        or manifest.get("task") != task or manifest.get("sha256") != self.details["sha256"]
                        or manifest.get("model_file") != self.path.name):
                    raise ValueError("ONNX manifest task, hash or preprocessing contract does not match")
                self.details["contract"] = MODEL_CONTRACT
            available = ort.get_available_providers()
            providers = ["CPUExecutionProvider"]
            if device != "cpu" and "CUDAExecutionProvider" in available:
                providers.insert(0, "CUDAExecutionProvider")
            elif device == "cuda":
                raise RuntimeError("ONNX CUDA provider is unavailable")
            self.session = ort.InferenceSession(str(self.path), providers=providers)
            inputs = self.session.get_inputs()
            if len(inputs) != 1 or len(inputs[0].shape) != 4:
                raise ValueError("Expected one NCHW ONNX input")
            if inputs[0].type != "tensor(float)":
                raise ValueError("Expected float32 ONNX input")
            if any(isinstance(d, int) and d != expected for d, expected in
                   zip((inputs[0].shape[0], *inputs[0].shape[2:]), (1, SCENE_SIZE, SCENE_SIZE))):
                raise ValueError("Expected ONNX input accepting one 256x256 scene")
            self.channels = inputs[0].shape[1]
            self.input_name = inputs[0].name
            self.format = "onnx"
            self.details.update(format=self.format, providers=self.session.get_providers())
        else:
            import torch
            from training.vendor.nafnet_upstream import NAFNet
            selected = "cuda" if device == "auto" and torch.cuda.is_available() else device
            self.device = "cpu" if selected == "auto" else selected
            if self.device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("PyTorch CUDA is unavailable")
            # Early own checkpoints stored torch.__version__ as TorchVersion.
            # Allow this string subclass without enabling arbitrary pickle code.
            from torch.torch_version import TorchVersion
            with torch.serialization.safe_globals([TorchVersion]):
                checkpoint = torch.load(str(self.path), map_location="cpu", weights_only=True)
            if not isinstance(checkpoint, dict) or "config" not in checkpoint or "model" not in checkpoint:
                raise ValueError("Checkpoint requires config and model state")
            if role == "candidate" and checkpoint.get("contract") != MODEL_CONTRACT:
                raise ValueError("Candidate preprocessing contract is missing or incompatible")
            recorded_task = checkpoint.get("report", {}).get("task")
            if recorded_task is not None and recorded_task != task:
                raise ValueError("Checkpoint task differs from requested evaluation task")
            self.channels = checkpoint["config"].get("img_channel", 3)
            self.model = NAFNet(**checkpoint["config"]).to(self.device).eval()
            self.model.load_state_dict(checkpoint["model"], strict=True)
            self.format = "torch"
            self.details.update(format=self.format, device=self.device, config=checkpoint["config"],
                                torch_version=str(torch.__version__), checkpoint_task=recorded_task,
                                contract=checkpoint.get("contract"))
        if self.channels != (1 if role == "candidate" else 3):
            raise ValueError("Candidate must have one input channel; v1 parent must have three")
        self.details["input_contract"] = (NORMALIZATION if role == "candidate"
                                           else "Physical mono input repeated unchanged into RGB, identical noise")
        self.details["output_contract"] = ("Inverse input affine transformation, no clipping" if role == "candidate"
                                            else "Mean of three output channels in original physical units")

    def predict(self, image):
        if self.role == "candidate":
            data, low, scale = normalize_v1(image)
        else:
            data, low, scale = np.asarray(image, dtype=np.float32), 0.0, 1.0
        tensor = np.repeat(data[None, None], self.channels, axis=1)
        if self.format == "onnx":
            result = self.session.run(None, {self.input_name: tensor})[0]
        else:
            import torch
            with torch.inference_mode():
                result = self.model(torch.from_numpy(tensor).to(self.device)).cpu().numpy()
        if result.shape != tensor.shape or not np.isfinite(result).all():
            raise ValueError("Unexpected model output shape or non-finite values")
        mono = np.mean(result[0].astype(np.float64), axis=0)
        return (mono * scale + low).astype(np.float32)


def summarize(rows):
    """Equal scene weighting, with valid-ROI counts for every reported metric."""
    names = sorted({name for row in rows for name in row})
    summary = {}
    for name in names:
        values = [row[name] for row in rows if row.get(name) is not None]
        summary[name] = {
            "mean": float(np.mean(values)) if values else None,
            "p95": float(np.percentile(values, 95)) if values else None,
            "maximum": float(np.max(values)) if values else None,
            "mean_absolute": float(np.mean(np.abs(values))) if values else None,
            "p95_absolute": float(np.percentile(np.abs(values), 95)) if values else None,
            "scenes": len(values),
        }
    return summary


def evaluate(candidate, parent, task, scenes=MIN_SCENES):
    if scenes < MIN_SCENES:
        raise ValueError("At least 64 independent scenes are required")
    records = []
    started = time.perf_counter()
    suite_digest = hashlib.sha256()
    for index in range(scenes):
        scene = make_scene(index, task)
        suite_digest.update(scene["input"].astype("<f4").tobytes())
        suite_digest.update(scene["target"].astype("<f4").tobytes())
        _, low, scale = normalize_v1(scene["input"])
        normalized_target = (scene["target"].astype(np.float64) - low) / scale
        outcomes = {}
        timings = {}
        for name, predictor in (("input", None), ("parent", parent), ("candidate", candidate)):
            began = time.perf_counter()
            prediction = scene["input"] if predictor is None else predictor.predict(scene["input"])
            timings[name] = time.perf_counter() - began
            outcomes[name] = measure(prediction, scene, task)
            # Target uses the input's affine parameters; never target-derived ones.
            normalized_prediction = (np.asarray(prediction, np.float64) - low) / scale
            outcomes[name]["input_affine_mse"] = float(np.mean((normalized_prediction - normalized_target) ** 2))
        records.append({"scene": scene["parameters"], "groups": scene["group"],
                        "normalization": {"low": low, "scale": scale},
                        "metrics": outcomes, "inference_seconds": timings})
        if index == 0 or (index + 1) % 8 == 0:
            print(json.dumps({"evaluated_scenes": index + 1, "total": scenes,
                              "elapsed_seconds": time.perf_counter() - started}), flush=True)
    overall = {model: summarize([row["metrics"][model] for row in records])
               for model in ("input", "parent", "candidate")}
    grouped = {}
    for group in records[0]["groups"]:
        grouped[group] = {}
        for value in sorted({row["groups"][group] for row in records}):
            selected = [row for row in records if row["groups"][group] == value]
            grouped[group][value] = {"scene_count": len(selected), "models": {
                model: summarize([row["metrics"][model] for row in selected])
                for model in overall}}
    comparisons = {}
    for baseline in ("input", "parent"):
        candidate_mse = overall["candidate"]["mse"]["mean"]
        baseline_mse = overall[baseline]["mse"]["mean"]
        comparisons[baseline] = {
            "candidate_mse_lower": candidate_mse < baseline_mse,
            "candidate_to_baseline_mse_ratio": candidate_mse / baseline_mse if baseline_mse > 0 else None,
            "scenes_with_lower_mse": sum(row["metrics"]["candidate"]["mse"] < row["metrics"][baseline]["mse"]
                                          for row in records),
            "scene_count": scenes,
        }
    return {
        "status": "experimental_independent_synthetic_evaluation",
        "release_approved": False, "production_approved": False,
        "task": task, "holdout_seed": HOLDOUT_SEED, "scene_count": scenes, "scene_size": SCENE_SIZE,
        "suite_sha256": suite_digest.hexdigest(), "normalization": NORMALIZATION,
        "models": {"candidate": candidate.details, "parent": parent.details},
        "seconds": time.perf_counter() - started, "numpy_version": np.__version__,
        "overall": overall, "by_group": grouped, "comparison": comparisons, "scenes": records,
        "metric_definitions": {
            "mse_mae_bias": "Measured in original linear physical units after inverse affine transformation.",
            "stellar_flux": "Aperture sum of prediction minus target, divided by known original star flux; isolated analytic stars only.",
            "remaining_star_flux_fraction": "Signed aperture residual relative to original star flux; target retains the same observation noise. Negative values mean over-removal, not improvement.",
            "faint_structure_mse": "Residual over known weak extended/filamentary emission outside stellar apertures.",
            "blank_region_false_rms": "Residual RMS in analytic blank regions; includes remaining noise/gradient and is not alone proof of hallucinated structure.",
            "aggregation": "Equal weighting per scene; per-metric scene counts disclose empty regions/aperture sets.",
        },
        "limitations": [
            "Synthetic holdout only; no real camera, readout, filter, observing-session or telescope generalization claim.",
            "Mono evaluation does not measure RGB color preservation or Bayer interpolation/noise artifacts.",
            "Once used for tuning, these scenes cease to be an untouched final test; reserve another suite before release.",
            "Fixed 256px inference does not establish full-image tiled inference, offset invariance or seam/edge fidelity.",
            "Known analytic scenes omit many real halos, diffraction spikes, saturation effects, optical aberrations and extended objects.",
            "Mean bias can cancel locally; inspect grouped and per-scene flux, faint-structure and blank-region residuals.",
            "No automatic checkpoint promotion or production activation is performed.",
        ],
    }


def main():
    global HOLDOUT_SEED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New report JSON file; never overwritten")
    parser.add_argument("--scenes", type=int, default=MIN_SCENES)
    parser.add_argument("--seed", type=int, default=HOLDOUT_SEED,
                        help="Reserve a fresh, recorded holdout seed before inspecting its results")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    if args.seed < 0:
        parser.error("--seed must be nonnegative")
    HOLDOUT_SEED = args.seed
    if args.scenes < MIN_SCENES:
        parser.error("--scenes must be at least 64")
    if args.output.exists():
        parser.error("Output already exists; choose a new report path")
    candidate = Predictor(args.candidate, "candidate", args.task, args.device)
    parent = Predictor(args.parent, "parent", args.task, args.device)
    report = evaluate(candidate, parent, args.task, args.scenes)
    report["evaluator_sha256"] = sha256(Path(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps({"report": str(args.output.resolve()), "comparison": report["comparison"],
                      "release_approved": False}), flush=True)


if __name__ == "__main__":
    main()
