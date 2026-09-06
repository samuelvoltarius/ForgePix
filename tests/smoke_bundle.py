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
        # Exercise the native scientific import -> CFA Drizzle -> export path
        # inside the package. Identical undithered inputs intentionally leave
        # incomplete per-color coverage; they must not be inpainted or debayered.
        raw_directory = Path(d) / "cfa"
        raw_directory.mkdir()
        yy, xx = np.mgrid[:40, :48]
        raw = (-.01 + .5 * np.exp(-((xx - 23)**2 + (yy - 19)**2) / 12)).astype(np.float32)
        raw[15, 20] = 1.4
        raw_hashes = {}
        for index in range(3):
            path = raw_directory / ("Light-%d.fits" % index)
            fits.writeto(path, raw, fits.Header({"BAYERPAT": "RGGB", "EXPTIME": 300,
                                                "IMAGETYP": "LIGHT", "FILTER": "SII/OIII"}))
            raw_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        drizzle_work = Path(d) / "drizzle-work"
        reconstructed = subprocess.run(command + ["--cli", "--input", str(raw_directory),
            "--work", str(drizzle_work), "--astro", "--astro-drizzle", "2", "--astro-drizzle-true",
            "--no-register", "--no-astro-stretch", "--fits-out"],
            env=env, capture_output=True, timeout=180, cwd=root)
        if reconstructed.returncode:
            raise RuntimeError("Packaged CFA Drizzle failed: " + reconstructed.stderr.decode(errors="replace"))
        records = list(drizzle_work.rglob("drizzle_report.json"))
        if len(records) != 1:
            raise RuntimeError("Packaged Drizzle did not export its scientific coverage report")
        record = json.loads(records[0].read_text(encoding="utf-8"))
        if not record.get("cfa_preserved"):
            raise RuntimeError("Packaged Drizzle lost native CFA measurements")
        science_path = next(records[0].parent.glob("*_astro_linear.fits"))
        cube = np.moveaxis(fits.getdata(science_path, memmap=False), 0, -1)
        header = fits.getheader(science_path)
        coverage = tifffile.imread(records[0].parent / header["FPDRZCOV"]).astype(bool)
        weights = tifffile.imread(records[0].parent / header["FPDRZWGT"])
        if (cube.shape != (80, 96, 3) or not np.isfinite(cube).all()
                or coverage.shape != cube.shape or not np.array_equal(coverage, weights > 0)
                or not np.all(cube[~coverage] == 0) or not np.any(~coverage)
                or not np.any(cube[coverage] < 0) or not np.any(cube[coverage] > 1)):
            raise RuntimeError("Packaged Drizzle violated float/CFA/coverage preservation")
        for path, expected in raw_hashes.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError("Drizzle changed its raw source FITS")
        print("Native CFA Drizzle smoke passed: signed/HDR FITS and explicit missing-color coverage")
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
        steps = []
        for task in ("background", "denoise"):
            model_id = "forgepix-" + task + "-mono-v2"
            manifest = json.loads((root / "assets/models" / model_id / "manifest.json").read_text(encoding="utf-8"))
            steps.append(dict(task=task, model_id=model_id, model_sha256=manifest["sha256"],
                              strength=.5, device=args.device))
        recipe = Path(d) / "Repeat.fprecipe"
        recipe.write_text(json.dumps(dict(format="ForgePixRecipe", schema_version=1,
                                          name="Package acceptance", steps=steps)), encoding="utf-8")
        repeated = subprocess.run(command + ["--recipe", "--file", str(recipe), "--input", str(scientific),
            "--output-root", str(Path(d)), "--experimental"], env=env, capture_output=True, timeout=120, cwd=root)
        if repeated.returncode:
            raise RuntimeError("Packaged recipe failed: " + repeated.stderr.decode(errors="replace"))
        journals = list(Path(d).glob("stack-recipe-*/run.json"))
        if len(journals) != 1:
            raise RuntimeError("Packaged recipe did not save a unique journal")
        journal = json.loads(journals[0].read_text(encoding="utf-8"))
        if (journal["status"] != "completed" or journal["completed_steps"] != 2 or
            hashlib.sha256(scientific.read_bytes()).hexdigest() != original):
            raise RuntimeError("Packaged recipe did not preserve its source and completed chain")
        if args.require_provider and any(step["execution"]["provider"] != args.require_provider for step in journal["steps"]):
            raise RuntimeError("Packaged recipe used an unexpected backend")
        print("Native recipe smoke passed: two pinned models, journal and preserved FITS")

        # The tested executable performs its own detection and catalogue solve.
        # The input fixture is generated independently with Astropy's WCS API.
        from test_astrometry import fixture
        points, _, shape, catalogue, hints, truth = fixture()
        catalogue_path = Path(d) / "catalogue.npz"
        catalogue.speichern(catalogue_path)
        yy, xx = np.indices(shape)
        field = np.full(shape, .01, np.float64)
        for index, (px, py) in enumerate(points):
            field += (.16 - index * .001) * np.exp(-((xx - px)**2 + (yy - py)**2) / 4.5)
        solve_input = Path(d) / "astrometry.fits"
        fits.writeto(solve_input, field, fits.Header({"FPLINEAR": True, "BUNIT": "electron"}))
        solved = subprocess.run(command + ["--solve", "--input", str(solve_input), "--catalogue", str(catalogue_path),
            "--ra", str(hints["ra"]), "--dec", str(hints["dec"]), "--scale", str(hints["pixelscale_arcsec"]),
            "--output-root", str(Path(d))], env=env, capture_output=True, timeout=90, cwd=root)
        if solved.returncode:
            raise RuntimeError("Packaged native solve failed: " + solved.stderr.decode(errors="replace"))
        solved_paths = list(Path(d).glob("stack-astrometry-*/solved.fits"))
        if len(solved_paths) != 1 or not np.array_equal(fits.getdata(solved_paths[0]), field):
            raise RuntimeError("Packaged native solver changed scientific pixel values")
        from astropy.wcs import WCS
        fitted = WCS(fits.getheader(solved_paths[0]))
        gx, gy = np.meshgrid(np.linspace(0, shape[1] - 1, 6), np.linspace(0, shape[0] - 1, 5))
        sky = truth.pixel_to_world(gx, gy)
        sx, sy = fitted.world_to_pixel(sky)
        if np.max(np.hypot(sx - gx, sy - gy)) > .2:
            raise RuntimeError("Packaged native WCS does not match the independent field")
        print("Native astrometry smoke passed: independent WCS field and exact float64 FITS")


if __name__ == "__main__":
    main()
