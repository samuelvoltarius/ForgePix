"""Run a synthetic focus stack through the packaged CLI and read its output."""
import os
import argparse
import subprocess
import sys
import tempfile
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from astropy.io import fits
import tifffile


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--source", action="store_true", help="Test the source entry point")
    mode.add_argument("--binary", type=Path, help="Test an extracted package executable")
    parser.add_argument("--device", choices=("auto", "cpu", "gpu", "cuda", "directml", "coreml"),
                        default="auto", help="AI compute request for this package check")
    parser.add_argument("--require-provider", help="Fail if an AI task silently falls back from this ORT backend")
    args = parser.parse_args()
    if args.source:
        command = [sys.executable, str(root / "focus_stack_gui.py")]
    elif args.binary:
        command = [str(args.binary.resolve(strict=True))]
    else:
        binary = {"win32": "dist/ForgePix/ForgePix.exe",
                  "darwin": "dist/ForgePix.app/Contents/MacOS/ForgePix"}.get(
                      sys.platform, "dist/ForgePix/ForgePix")
        command = [str(root / binary)]
    with tempfile.TemporaryDirectory(prefix="forgepix-smoke-") as d:
        source, work = Path(d) / "input", Path(d) / "work"
        source.mkdir()
        rng = np.random.default_rng(42)
        base = rng.integers(30, 230, size=(120, 160, 3), dtype=np.uint8)
        for i in range(4):
            frame = cv2.GaussianBlur(base, (0, 0), 2)
            frame[:, i * 40:(i + 1) * 40] = base[:, i * 40:(i + 1) * 40]
            cv2.imencode(".png", frame)[1].tofile(str(source / ("f%d.png" % i)))
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        gui = subprocess.run(command + ["--smoke-gui"], env=env,
                             capture_output=True, timeout=30, cwd=root)
        if gui.returncode:
            raise RuntimeError("Packaged GUI failed: " + gui.stderr.decode(errors="replace"))
        print("GUI smoke test passed: Astro workspace opened and closed")
        result = subprocess.run(command + ["--cli", "--input", str(source), "--work", str(work)],
                                env=env, capture_output=True, timeout=180, cwd=root)
        if result.returncode:
            raise RuntimeError("Packaged CLI failed: " + result.stderr.decode(errors="replace"))
        outputs = list((work / "stack").glob("*"))
        images = [cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_UNCHANGED) for p in outputs]
        if not any(im is not None and im.size and float(im.std()) > 1 for im in images):
            raise RuntimeError("No readable, nonconstant stack output")
        print("CLI smoke test passed: readable focus stack exported")
        # Run every shipped model through the packaged entry point, so an
        # omitted ONNX DLL or data file cannot pass a mere GUI startup check.
        y, x = np.mgrid[:71, :83]
        linear = (.006 + .3 * np.exp(-((x-42)**2+(y-35)**2)/12)).astype(np.float32)
        linear += rng.normal(0, .001, linear.shape).astype(np.float32)
        scientific = Path(d)/"linear.fits"
        fits.PrimaryHDU(linear).writeto(scientific)
        original = hashlib.sha256(scientific.read_bytes()).hexdigest()
        for task in ("denoise", "background", "deblur", "starless"):
            destination = Path(d)/("ai-"+task)
            restored = subprocess.run(command + ["--ai-restore", "--input", str(scientific),
                "--model", "forgepix-"+task+"-mono-v2", "--output-root", str(destination),
                "--experimental", "--device", args.device], env=env, capture_output=True, timeout=120, cwd=root)
            if restored.returncode:
                raise RuntimeError("Packaged AI failed ("+task+"): "+restored.stderr.decode(errors="replace"))
            outputs=list(destination.glob("*/result_32bit.tif"))
            if len(outputs) != 1:
                raise RuntimeError("Missing unique model export: "+task)
            pixels=tifffile.imread(outputs[0])
            if pixels.shape != linear.shape or pixels.dtype != np.float32 or not np.isfinite(pixels).all():
                raise RuntimeError("Invalid scientific model output: "+task)
            report = json.loads((outputs[0].parent / "ai_report.json").read_text(encoding="utf-8"))
            execution = report.get("execution", {})
            provider = execution.get("provider")
            if args.require_provider and provider != args.require_provider:
                raise RuntimeError("Wrong packaged AI backend ("+task+"): "+str(execution))
            print("AI backend ("+task+"): "+str(provider))
        if hashlib.sha256(scientific.read_bytes()).hexdigest() != original:
            raise RuntimeError("AI changed its source FITS")
        print("AI smoke test passed: all four bundled models export finite float32 from FITS")


if __name__ == "__main__":
    main()
