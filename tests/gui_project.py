"""Opt-in real project-menu/file-dialog/history round trip, without UI mocks.

Use --output NEW_FOLDER. Optional --input is a user's FITS to reference and
verify unchanged; otherwise create a small analytic FITS fixture. The second
fixture is deliberately offset to distinguish history states, not an advertised
processing algorithm. No AI model or remote service participates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    options = parser.parse_args()
    output = options.output.resolve()
    if output.exists() or not output.parent.is_dir():
        parser.error("--output must be a new directory under an existing parent")
    if options.input and options.input.suffix.lower() not in {".fit", ".fits", ".fts"}:
        parser.error("--input must be an existing FITS image")
    source = options.input.resolve(strict=True) if options.input else output / "source.fits"
    output.mkdir()
    os.environ["FORGEPIX_SETTINGS_FILE"] = str(output / "settings.ini")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "core")]
    import numpy as np
    from astropy.io import fits
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from ui.main_window import MainWindow
    from ui.project_dialog import ProjectHistoryDialog
    from ui.settings_io import app_settings
    from ui.theme import THEME
    if not options.input:
        yy, xx = np.mgrid[:192, :256]
        data = .02 + .10 * np.exp(-((xx - 135) ** 2 + (yy - 94) ** 2) / 1800)
        data += .50 * np.exp(-((xx - 70) ** 2 + (yy - 80) ** 2) / 7)
        fits.writeto(source, data.astype(np.float32), fits.Header({"OBJECT": "Project GUI fixture", "FPLINEAR": True}))
    original_hash, original_stat = digest(source), source.stat()
    second = output / "second_result.fits"
    fits.writeto(second, fits.getdata(source).astype(np.float32) + np.float32(.015),
                 fits.Header({"OBJECT": "Project history fixture B", "FPLINEAR": True}))
    second_hash = digest(second)
    project_path = output / "M27.forgepix"
    report = {"source": str(source), "source_sha256": original_hash, "second_fixture_sha256": second_hash,
              "project": str(project_path), "errors": [], "actions": [], "passed": False,
              "scope": "Real project menus, Qt file dialogs, snapshot archive, reopening and history selection; no processing quality claim."}
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "seguiemj.ttf"):
        QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / name))
    app.setStyleSheet(THEME)
    settings = app_settings()
    settings.setValue("check_updates", "0")
    settings.setValue("language", "de")
    settings.sync()

    def window():
        item = MainWindow()
        item._choose_module(1)
        item.in_edit.setText(str(source.parent))
        item.work_edit.setText(str(output))
        item.resize(1280, 800)
        item.show()
        app.processEvents()
        return item

    active_window = window()
    all_windows = [active_window]
    errors = QTimer()
    def dismiss_error():
        modal = app.activeModalWidget()
        if isinstance(modal, QMessageBox):
            report["errors"].append(modal.text())
            modal.reject()
    errors.timeout.connect(dismiss_error)
    errors.start(20)

    def file_action(action, path):
        chosen = []
        started = time.monotonic()
        timer = QTimer()
        def choose():
            modal = app.activeModalWidget()
            if isinstance(modal, QFileDialog):
                modal.setDirectory(str(path.parent))
                modal.selectFile(str(path))
                chosen.append(str(path))
                timer.stop()
                modal.accept()
            elif time.monotonic() - started > 15:
                timer.stop()
                report["errors"].append("File dialog did not appear")
                if modal:
                    modal.reject()
        timer.timeout.connect(choose)
        timer.start(10)
        action.trigger() if hasattr(action, "trigger") else action.click()
        timer.stop()
        if not chosen:
            raise RuntimeError("The real file dialog was not used")
        report["actions"].append({"menu": action.text(), "file_dialog_selected": chosen[-1]})
        app.processEvents()

    try:
        file_action(active_window.project_actions["new"], project_path)
        file_action(active_window.project_actions["add"], source)
        first = active_window._project.data["selected_step"]
        file_action(active_window.project_actions["add"], second)
        latest = active_window._project.data["selected_step"]
        active_window.project_actions["save"].trigger()
        if first == latest or len(active_window._project.data["steps"]) != 2:
            raise RuntimeError("Result import did not create two saved history entries")
        active_window.grab().save(str(output / "saved-project.png"))
        active_window.close()
        active_window = window()
        all_windows.append(active_window)
        file_action(active_window.project_actions["open"], project_path)
        if digest(active_window.result_path) != second_hash:
            raise RuntimeError("Reopening did not restore the last selected result")
        history_selected = []
        timer = QTimer()
        def choose_history():
            modal = app.activeModalWidget()
            if isinstance(modal, ProjectHistoryDialog):
                timer.stop()
                modal.grab().save(str(output / "history-latest.png"))
                item = modal.tree.topLevelItem(0)
                modal.tree.setCurrentItem(item)
                app.processEvents()
                modal.grab().save(str(output / "history.png"))
                if not modal.open_button.isEnabled():
                    raise RuntimeError("Verified historical result is disabled")
                history_selected.append(item.data(0, Qt.UserRole))
                modal.open_button.click()
        timer.timeout.connect(choose_history)
        timer.start(10)
        active_window.project_actions["history"].trigger()
        timer.stop()
        if history_selected != [first] or digest(active_window.result_path) != original_hash:
            raise RuntimeError("The history dialog did not restore the original saved result")
        if not active_window._preview_pix or active_window._preview_pix.isNull():
            raise RuntimeError("The historical FITS preview is empty")
        active_window.grab().save(str(output / "restored-first-result.png"))
        export_clicked = []
        export_timer = QTimer()
        def copy_scientific():
            modal = app.activeModalWidget()
            if modal is getattr(active_window, "_project_export_dialog", None) and modal is not None:
                if active_window._last_project_export:
                    modal.grab().save(str(output / "scientific-export.png"))
                    export_timer.stop()
                    modal.close_button.click()
                elif not export_clicked:
                    export_clicked.append(True)
                    modal.copy_button.click()
        export_timer.timeout.connect(copy_scientific)
        export_timer.start(10)
        file_action(active_window.export_btn, output)
        export_timer.stop()
        exported = Path(active_window._last_project_export)
        exported_image = exported / Path(active_window.result_path).name
        if digest(exported_image) != original_hash:
            raise RuntimeError("Scientific export changed the original FITS bytes")
        report["scientific_export"] = str(exported_image)
        report["scientific_export_sha256"] = digest(exported_image)
        report["scientific_export_report"] = json.loads((exported / "forgepix-export.json").read_text(encoding="utf-8"))
        report["historical_result"] = active_window.result_path
        report["project_data"] = active_window._project.data
        report["checks"] = active_window._project.check()
        report["history_selected"] = history_selected
        report["menu_count"] = len(active_window.project_actions)
        report["snapshot_count"] = len(active_window._project.data["steps"])
        report["preview_visible"] = True
        after = source.stat()
        report["original_unchanged"] = digest(source) == original_hash and (after.st_size, after.st_mtime_ns) == (original_stat.st_size, original_stat.st_mtime_ns)
        report["passed"] = not report["errors"] and report["original_unchanged"]
    except Exception as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc))
    finally:
        errors.stop()
        for item in all_windows:
            item.close()
        (output / "gui-project-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(output / "gui-project-report.json", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
