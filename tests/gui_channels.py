"""Opt-in real-image acceptance of the native channel menu and worker.

Copies a supplied linear RGB FITS to an isolated new folder, exercises the actual
dialog buttons, then validates a SII/OIII composition. Original acquisition-filter
identity is not inferred: --filter is the user's explicit profile for this test.
Only the file-manager reveal is suppressed; image processing is not mocked.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--filter", default="sv220_sii_oiii_7")
    args = parser.parse_args()
    source = args.input.resolve(strict=True)
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    original = digest(source)
    local = destination / "input.fits"
    shutil.copy2(source, local)
    os.environ["FORGEPIX_SETTINGS_FILE"] = str(destination / "settings.ini")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "core")]
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtCore import QTimer
    from ui.main_window import MainWindow
    from ui.channels_dialog import ChannelsDialog
    from ui.settings_io import app_settings
    from ui.theme import THEME
    import numpy as np
    import tifffile
    from astropy.io import fits
    import channels

    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "seguiemj.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setStyleSheet(THEME)
    settings = app_settings()
    settings.setValue("check_updates", "0")
    settings.setValue("language", "de")
    settings.sync()
    window = MainWindow()
    window._choose_module(1)
    window.astro_filter.setCurrentIndex(window.astro_filter.findData(args.filter))
    window.resize(1280, 800)
    window.result_path = str(local)
    window.show()
    app.processEvents()
    report = {"source": str(source), "original_sha256": original,
              "filter": args.filter, "filter_basis": "explicit user profile, not verified capture metadata",
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              "worktree": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
              "errors": []}
    revealed = []
    start = time.monotonic()

    def close_error_boxes():
        modal = app.activeModalWidget()
        if isinstance(modal, QMessageBox):
            report["errors"].append(modal.text())
            modal.accept()

    errors = QTimer()
    errors.timeout.connect(close_error_boxes)
    errors.start(100)

    def edit(mode, paths=None):
        dialog = app.activeModalWidget()
        if not isinstance(dialog, ChannelsDialog):
            report["errors"].append("Channel dialog did not open")
            return
        dialog.mode.setCurrentIndex(dialog.mode.findData(mode))
        for key, path in (paths or {}).items():
            dialog.fields[key].setText(str(path))
        app.processEvents()
        dialog.grab().save(str(destination / (mode + ".png")))
        report[mode + "_size"] = [dialog.width(), dialog.height()]
        if not dialog.run_button.isEnabled():
            report["errors"].append("Required inputs were not accepted: " + mode)
            dialog.reject()
        else:
            dialog.run_button.click()

    try:
        action = next(a for a in window.tools_btn.menu().actions()
                      if a.text() == "Kanäle trennen und kombinieren")
        with patch("ui.main_window.reveal_in_files", side_effect=lambda p: revealed.append(p)):
            QTimer.singleShot(0, lambda: edit("split_dual"))
            action.trigger()
        if not revealed:
            raise RuntimeError("The split produced no result directory")
        split = Path(revealed[-1])
        paths = {key: split / (key + ".fits") for key in ("SII", "OIII")}
        for path in paths.values():
            if not path.is_file():
                raise RuntimeError("Missing extracted channel: " + str(path))
        QTimer.singleShot(0, lambda: edit("SOO", paths))
        action.trigger()
        output = Path(window.result_path).parent
        if not (output / "combined_32bit.fits").is_file():
            raise RuntimeError("The composition produced no linear FITS")
        rgb = tifffile.imread(output / "combined_32bit.tif")
        np.testing.assert_array_equal(fits.getdata(output / "combined_32bit.fits"), np.moveaxis(rgb, -1, 0))
        coverage = tifffile.imread(output / "coverage.tif").astype(bool)
        np.testing.assert_array_equal(rgb[~coverage], 0)
        np.testing.assert_array_equal(rgb[..., 1], rgb[..., 2])
        read = channels.read(local)[0]
        np.testing.assert_array_equal(fits.getdata(paths["SII"]), read[..., 2])
        np.testing.assert_allclose(fits.getdata(paths["OIII"]), (2 * read[..., 1] + read[..., 0]) / 3,
                                   rtol=2e-7, atol=1e-8)
        report.update(output=str(output), shape=list(rgb.shape), finite=bool(np.isfinite(rgb).all()),
                      composition=json.loads((output / "channels.json").read_text()),
                      originals_unchanged=(digest(source) == original and digest(local) == original))
        app.processEvents()
        window.grab().save(str(destination / "completed.png"))
        if not report["finite"] or not report["originals_unchanged"]:
            raise RuntimeError("Invalid result or modified source")
    except Exception as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc))
    finally:
        errors.stop()
        report["elapsed_seconds"] = round(time.monotonic() - start, 3)
        (destination / "processing.log").write_text(window.log.toPlainText(), encoding="utf-8")
        (destination / "gui-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if getattr(window, "_tool_worker", None):
            window._tool_worker.wait(5000)
        window.close()
    print(destination / "gui-report.json")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
