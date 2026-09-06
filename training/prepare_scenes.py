"""Verify public science FITS and extract object-separated scene patches.

These are observed scene bases, NOT noiseless restoration ground truth. Noise
already in the observation is retained in both input and target. No RGB copies
with independently added noise are produced. Original FITS are read only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from astropy.io import fits


def prepare(root, output, per_file=32, size=256):
    output.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(605193)
    banks = {"train": [], "validation": [], "test": []}
    seen_hash, seen_group, records = {}, {}, []
    for metadata in sorted(root.glob("*/*.fits.json")):
        record = json.loads(metadata.read_text())
        split, group = record["split"], record["group"]
        if split not in banks or record.get("rights") != "PUBLIC":
            raise ValueError(f"Unreviewed split/rights: {metadata}")
        if group in seen_group and seen_group[group] != split:
            raise ValueError(f"Object crosses dataset splits: {group}")
        seen_group[group] = split
        path = Path(str(metadata)[:-5])
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"Source checksum mismatch: {path}")
        if digest in seen_hash:
            if seen_hash[digest] != split:
                raise ValueError(f"Duplicate source crosses splits: {path}")
            continue
        seen_hash[digest] = split
        # Combined products only. Individual exposures may be constituents of
        # these products; never pretend they form independent noise pairs.
        if not path.name.endswith(("_drc.fits", "_drz.fits")):
            continue
        with fits.open(path, memmap=False) as hdus:
            data = np.asarray(hdus["SCI"].data, dtype=np.float32)
            if data.ndim != 2 or min(data.shape) < size:
                continue
            valid = np.isfinite(data)
            if "WHT" in hdus:
                weight = hdus["WHT"].data
                valid &= np.isfinite(weight) & (weight > 0)
            if "DQ" in hdus:
                valid &= hdus["DQ"].data == 0
            pixels = data[valid]
            if not pixels.size:
                continue
            low, high = np.percentile(pixels, [.1, 99.9])
            scale = max(float(high - low), 1e-6)
            accepted = []
            for _ in range(2000):
                y = int(rng.integers(0, data.shape[0] - size + 1))
                x = int(rng.integers(0, data.shape[1] - size + 1))
                if not valid[y:y+size, x:x+size].all():
                    continue
                patch = (data[y:y+size, x:x+size] - low) / scale
                # Keep signed shadows and bright cores. Only reject numerical
                # overflow; no all-pixels-within-percentiles selection bias.
                if not np.isfinite(patch).all():
                    continue
                banks[split].append(np.asarray(patch, dtype=np.float32))
                accepted.append([x, y])
                if len(accepted) == per_file:
                    break
        records.append(dict(source=str(path), uri=record["uri"], sha256=digest,
            split=split, group=group, filter=record.get("filter"),
            instrument=record.get("header", {}), patches_xy=accepted,
            normalization=dict(offset=float(low), scale=scale),
            rights=record["rights"], policy=record["policy"], ground_truth=False))
        print(f"{group} {path.name}: {split} {len(accepted)} patches", flush=True)
    if not banks["train"] or not banks["validation"]:
        raise ValueError("Independent train and validation objects required")
    for split, values in banks.items():
        if values:
            np.save(output / f"{split}.npy", np.stack(values))
    manifest = dict(schema_version=1, size=size, seed=605193,
        counts={k: len(v) for k, v in banks.items()}, records=records,
        use="Public observed scene bases with controlled added degradations",
        source_noise_retained=True, ground_truth=False,
        credit="NASA/ESA Hubble; observing programmes; STScI/MAST",
        limitations="HST optical mono scenes; no ground-camera or real clean/noisy pair qualification")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["counts"]), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--per-file", type=int, default=32)
    args = ap.parse_args()
    if args.per_file < 1:
        ap.error("per-file must be positive")
    prepare(args.input, args.output, args.per_file)
