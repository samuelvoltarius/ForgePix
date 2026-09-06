"""Opt-in native CLI acceptance with full-size original FITS copies, never JPEGs."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np
import tifffile
from astropy.io import fits


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--scale", type=int, choices=(1, 2), default=2)
    parser.add_argument("--align", choices=("shift", "rotate"), default="rotate",
                        help="Match the GUI rotation default, including meridian flips; shift is an explicit diagnostic")
    parser.add_argument("--no-quality-selection", action="store_true",
                        help="Explicit diagnostic only: skip the app's normal frame quality selection")
    options = parser.parse_args()
    sources = sorted(path for path in options.input.iterdir() if path.suffix.lower() in (".fits", ".fit", ".fts"))
    if options.count < 2 or len(sources) < options.count:
        raise ValueError("At least two FITS originals are required")
    selected = [sources[int(index)] for index in np.linspace(0, len(sources) - 1, options.count)]
    destination = options.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    staging = destination / "input-fits"
    staging.mkdir()
    repo = Path(__file__).resolve().parents[1]
    records = []
    for source in selected:
        header = fits.getheader(source)
        record = {"path": str(source.resolve()), "sha256": digest(source), "bytes": source.stat().st_size,
                  "mtime_ns": source.stat().st_mtime_ns,
                  "shape": [header.get("NAXIS2"), header.get("NAXIS1")],
                  "header": {key: header.get(key) for key in ("BAYERPAT", "INSTRUME", "EXPTIME", "FILTER")}}
        copy = staging / source.name
        shutil.copy2(source, copy)
        if digest(copy) != record["sha256"]:
            raise ValueError("FITS copy differs from original")
        records.append(record)
    command = [sys.executable, str(repo / "focus_stack_gui.py"), "--cli", "--astro", "--input", str(staging),
               "--work", str(destination / "processing"), "--astro-drizzle", str(options.scale), "--astro-drizzle-true",
               "--astro-pixfrac", ".7", "--astro-align", options.align, "--no-auto-calib",
               "--fits-out", "--astro-color", "0"]
    if options.no_quality_selection:
        command.append("--no-astro-qc")
    report = {"sources": records, "command": command, "python": sys.version,
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
              "worktree": subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True).splitlines(),
              "passed": False, "scale": options.scale, "align": options.align,
              "limitations": "The selected originals test execution and measured coverage, not scientific image quality or recovered resolution; no calibration frames."}
    start = time.monotonic()
    peak_working_set = 0
    try:
        with (destination / "pipeline.log").open("w", encoding="utf-8") as logfile:
            process = subprocess.Popen(command, cwd=repo, stdout=logfile, stderr=subprocess.STDOUT)
            class MemoryCounters(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                    (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
            while process.poll() is None:
                if sys.platform == "win32":
                    counters = MemoryCounters()
                    counters.cb = ctypes.sizeof(counters)
                    if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(int(process._handle)),
                                                               ctypes.byref(counters), counters.cb):
                        peak_working_set = max(peak_working_set, counters.PeakWorkingSetSize)
                time.sleep(.25)
            report["returncode"] = process.returncode
        if process.returncode:
            raise RuntimeError("Native CLI failed; see pipeline.log")
        stack = destination / "processing" / "stack"
        info = json.loads((stack / "drizzle_report.json").read_text(encoding="utf-8"))
        processing = json.loads((stack / "processing_report.json").read_text(encoding="utf-8"))
        science_path = next(stack.glob("*_astro_linear.fits"))
        with fits.open(science_path, memmap=True) as hdus:
            header = hdus[0].header
            science = np.moveaxis(hdus[0].data, 0, -1)
            coverage = tifffile.imread(stack / header["FPCOV"])
            channels = tifffile.imread(stack / header["FPDRZCOV"])
            weights = tifffile.memmap(stack / header["FPDRZWGT"])
            tiff = tifffile.memmap(next(stack.glob("*_astro_linear_32bit.tif")))
            if science.shape != (records[0]["shape"][0] * options.scale, records[0]["shape"][1] * options.scale, 3):
                raise ValueError("Output does not preserve full original resolution at the requested scale")
            if not np.isfinite(science).all() or not np.isfinite(weights).all():
                raise ValueError("Nonfinite output")
            np.testing.assert_array_equal(tiff, science)
            np.testing.assert_array_equal(science[channels == 0], 0)
            np.testing.assert_array_equal(weights > 0, channels.astype(bool))
            np.testing.assert_array_equal(coverage, channels.all(axis=2))
            report["output"] = {"shape": list(science.shape), "fits_tiff_equal": True, "finite": True,
                "range": [float(science.min()), float(science.max())], "coverage_fraction": float(coverage.mean()),
                "channel_coverage_fraction": channels.mean(axis=(0, 1)).tolist(), "output_pixel_area": header["FPPIXARE"]}
        if processing["registered_frames"] != len(info["source_files"]) or processing["method"] != "drizzle_weighted_mean":
            raise ValueError("Processing report overstates registration or rejection")
        report.update(drizzle=info, processing=processing)
        report["passed"] = True
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - start, 3)
        # On Windows a venv python.exe is a launcher: its handle can measure only
        # that tiny process, not the actual child interpreter. Never call it the
        # reconstruction's peak memory without process-tree accounting.
        report["peak_working_set_bytes"] = None
        report["launcher_peak_working_set_bytes"] = peak_working_set or None
        report["memory_measurement"] = "Reconstruction peak unknown; launcher handle is not a process-tree measurement."
        report["originals_unchanged"] = all(digest(Path(record["path"])) == record["sha256"]
            and Path(record["path"]).stat().st_mtime_ns == record["mtime_ns"] for record in records)
        report["passed"] &= report["originals_unchanged"]
        (destination / "drizzle-e2e-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in ("passed", "elapsed_seconds", "peak_working_set_bytes", "error", "originals_unchanged")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
