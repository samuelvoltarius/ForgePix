"""Explicit, opt-in GUI acceptance run against a real FITS series.

This is not part of unittest discovery. It keeps settings and all results in a
new output folder and starts the same QProcess as the beginner's primary button.
Example: python tests/gui_real_fits.py --input X:/Lights --output X:/QA/run-001
Use --layout-only to inspect the current UI without processing the images.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--filter", default="sv220_sii_oiii_7")
    for kind in ("dark", "flat", "bias"):
        parser.add_argument("--" + kind, type=Path, help="Explicit calibration FITS master")
    parser.add_argument("--layout-only", action="store_true")
    parser.add_argument("--timeout", type=int, default=2400)
    options = parser.parse_args()
    source = options.input.resolve(strict=True)
    output = options.output.resolve()
    if not source.is_dir() or output == source or source in output.parents:
        raise SystemExit("Choose a new output folder outside the original series.")
    output.mkdir(parents=True, exist_ok=False)
    os.environ["FORGEPIX_SETTINGS_FILE"] = str(output / "settings.ini")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "core")]

    import numpy as np
    from astropy.io import fits
    from PySide6.QtCore import QProcess, QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    from ui.equipment_dialog import EquipmentDialog
    from ui.main_window import MainWindow
    from ui.settings_io import app_settings
    from ui.theme import THEME
    from astro_input import light_paths
    import focus_cull_stack as pipeline

    sources = sorted(p for p in source.iterdir()
                     if p.is_file() and p.suffix.lower() in {".fit", ".fits", ".fts"})
    if len(sources) < 2:
        raise SystemExit("At least two FITS files are required.")
    selected = sorted(Path(p).resolve() for p in light_paths(str(source), pipeline.list_images))
    if selected != sources:
        raise SystemExit("The pipeline did not select exactly the FITS inputs.")
    source_records = []
    for path in sources:
        header = fits.getheader(path)
        stat = path.stat()
        source_records.append({"path": str(path), "size": stat.st_size,
                               "mtime_ns": stat.st_mtime_ns,
                               "sha256": sha256(path) if not options.layout_only else None,
                               "header": {key: header.get(key) for key in
                                          ("INSTRUME", "FILTER", "EXPTIME", "BAYERPAT",
                                           "FOCALLEN", "XPIXSZ", "NAXIS1", "NAXIS2")}})
    calibration_records = {}
    for kind in ("dark", "flat", "bias"):
        path = getattr(options, kind)
        if path is None:
            continue
        path = path.resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in {".fit", ".fits", ".fts"}:
            raise SystemExit("Calibration acceptance requires a FITS master: " + str(path))
        stat = path.stat()
        calibration_records[kind] = {"path": str(path), "sha256": sha256(path),
                                     "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    report = {
        "source": str(source), "output": str(output), "layout_only": options.layout_only,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "git_worktree": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "input_count": len(sources), "inputs": source_records,
        "calibrations": calibration_records,
        "selected_filter": options.filter,
        "filter_source": "User-selected equipment profile; original FITS headers preserved.",
        "run_exit_code": None, "result_markers": [], "outputs": [], "errors": [],
    }

    def save_report():
        (output / "gui-report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "seguiemj.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setStyleSheet(THEME)
    settings = app_settings()
    for key, value in {"check_updates": "0", "language": "de",
                       "astro_filter_key": options.filter,
                       "equipment/filter": options.filter,
                       "equipment/camera": "asi294mc", "equipment/pitch": 4.63,
                       "equipment/telescope": "rc8", "equipment/aperture": 203,
                       "equipment/focal": 1624, "equipment/corrector": "red_064",
                       "equipment/factor": .64, "equipment/binning": 1}.items():
        settings.setValue(key, value)
    settings.sync()
    window = MainWindow()
    window._choose_module(1)
    window.resize(1280, 800)
    window.in_edit.setText(str(source))
    window.work_edit.setText(str(output / "processing"))
    for kind, record in calibration_records.items():
        getattr(window, "astro_" + kind).setText(record["path"])
    window.show()
    app.processEvents()

    def capture(name):
        app.processEvents()
        window.grab().save(str(output / (name + ".png")))
        report[name + "_size"] = [window.width(), window.height()]
        scroll = window.wizard.currentWidget()
        report[name + "_horizontal_overflow"] = scroll.horizontalScrollBar().maximum()

    window.mode_box.setCurrentIndex(0)
    capture("beginner")
    window.mode_box.setCurrentIndex(1)
    capture("professional")
    equipment = EquipmentDialog(window, initial_filter=options.filter)
    equipment.show()
    app.processEvents()
    equipment.grab().save(str(output / "equipment.png"))
    equipment.reject()
    window.mode_box.setCurrentIndex(0)
    save_report()
    if options.layout_only:
        window.close()
        print(output / "gui-report.json", flush=True)
        return 0

    expected_args = window._build_args(auto=True)
    report["expected_arguments"] = expected_args
    if ("--filter" not in expected_args or
            expected_args[expected_args.index("--filter") + 1] != options.filter):
        report["errors"].append("The beginner action does not forward the selected filter.")
        save_report()
        window.close()
        return 1
    started = time.monotonic()
    finished = False

    def complete(code, _status):
        nonlocal finished
        if finished:
            return
        finished = True
        try:
            report["run_exit_code"] = code
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            log = window.log.toPlainText()
            (output / "processing.log").write_text(log, encoding="utf-8")
            markers = [line.removeprefix("RESULT:").strip() for line in log.splitlines()
                       if line.startswith("RESULT:")]
            report["result_markers"] = markers
            report["gui_result_path"] = window.result_path
            if not markers:
                report["errors"].append("The process emitted no RESULT marker.")
            for marker in markers:
                result = Path(marker).resolve(strict=True)
                if output not in result.parents:
                    raise ValueError("RESULT escaped the isolated output folder.")
                directory = result if result.is_dir() else result.parent
                for path in sorted(directory.iterdir()):
                    if not path.is_file():
                        continue
                    record = {"path": str(path), "size": path.stat().st_size,
                              "sha256": sha256(path)}
                    if path.suffix.lower() in {".fits", ".fit", ".fts"}:
                        with fits.open(path, memmap=False) as hdus:
                            data = hdus[0].data
                            record.update(shape=list(data.shape), dtype=str(data.dtype),
                                          finite=bool(np.isfinite(data).all()),
                                          minimum=float(data.min()), maximum=float(data.max()))
                    elif path.suffix.lower() in {".tif", ".tiff"}:
                        import tifffile
                        data = tifffile.imread(path)
                        record.update(shape=list(data.shape), dtype=str(data.dtype),
                                      finite=bool(np.isfinite(data).all()),
                                      minimum=float(data.min()), maximum=float(data.max()))
                    if record.get("finite") is False:
                        report["errors"].append("Nonfinite output pixels: " + str(path))
                    report["outputs"].append(record)
            report["originals_unchanged"] = all(
                Path(record["path"]).stat().st_size == record["size"] and
                Path(record["path"]).stat().st_mtime_ns == record["mtime_ns"] and
                sha256(Path(record["path"])) == record["sha256"]
                for record in [*source_records, *calibration_records.values()])
            if not report["originals_unchanged"]:
                report["errors"].append("An original FITS changed during the run.")
            capture("completed")
        except Exception as exc:
            report["errors"].append(type(exc).__name__ + ": " + str(exc))
        save_report()
        window.close()
        app.quit()

    def start():
        # Actual primary GUI action; no direct pipeline invocation or mock.
        window.auto_btn.click()
        if window.proc is None:
            report["errors"].append("The GUI action did not create its QProcess.")
            complete(-1, None)
            return
        report["process_program"] = window.proc.program()
        report["process_arguments"] = window.proc.arguments()
        window.proc.finished.connect(complete)
        save_report()

    def timeout():
        if not finished:
            report["errors"].append("GUI processing exceeded the timeout.")
            if window.proc and window.proc.state() != QProcess.NotRunning:
                window.proc.kill()
            else:
                complete(-1, None)

    QTimer.singleShot(0, start)
    QTimer.singleShot(options.timeout * 1000, timeout)
    app.exec()
    print(output / "gui-report.json", flush=True)
    return 0 if report["run_exit_code"] == 0 and not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
