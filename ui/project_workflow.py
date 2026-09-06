"""Project menu, asynchronous file verification, and saved-result adoption."""
import os
import json
import uuid
from pathlib import Path

from PySide6.QtCore import QProcess, QThread, Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout)

from i18n import tr
from project_store import Project, ProjectError, resolve


class _ProjectWorker(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation, self.value, self.error = operation, None, None

    def run(self):
        try:
            self.value = self.operation()
        except Exception as exc:
            self.error = str(exc)


class _ProjectWait(QDialog):
    def __init__(self, title, worker, parent):
        super().__init__(parent)
        self.worker = worker
        self.setWindowTitle(title)
        self.resize(440, 110)
        layout = QVBoxLayout(self)
        label = QLabel(tr("Dateien werden geprüft und das Projekt sicher gespeichert …"))
        label.setWordWrap(True)
        layout.addWidget(label)
        progress = QProgressBar()
        progress.setRange(0, 0)
        layout.addWidget(progress)

    def reject(self):
        if not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)


class ProjectMixin:
    def _setup_projects(self):
        self._project = None
        self._project_worker = None
        self._project_loading = False
        self._project_standalone_preview = None
        menu = self.menuBar().addMenu(tr("Projekt"))
        self.project_actions = {}
        for key, title, shortcut, method in (
            ("new", "Neues Projekt …", "Ctrl+N", self.new_project),
            ("open", "Projekt öffnen …", "Ctrl+Shift+O", self.open_project),
            ("save", "Projekt speichern", "Ctrl+S", self.save_project),
            ("add", "Ergebnis hinzufügen …", "Ctrl+Shift+I", self.add_project_result),
            ("history", "Ergebnisverlauf …", "Ctrl+H", self.open_project_history),
            ("export", "Gesicherten Stand exportieren …", "Ctrl+Shift+E", self.export_project_result),
        ):
            action = QAction(tr(title), self)
            action.setShortcut(shortcut)
            action.triggered.connect(method)
            menu.addAction(action)
            self.project_actions[key] = action

    def _project_export_current(self):
        project = getattr(self, "_project", None)
        selected = project.data.get("selected_step") if project else None
        if (not selected or not self.result_path or os.path.realpath(self.result_path)
                != str(resolve(project.step(selected)["result"]["path"], project.path.parent))):
            return False
        # Once this is a saved project result, failed integrity verification
        # must never fall through to the generic lossy image exporter.
        self.export_project_result()
        return True

    def export_project_result(self):
        if not self._project_ready():
            return
        if self._project is None or not self._project.data.get("selected_step"):
            QMessageBox.information(self, tr("Projekt"), tr("Zuerst einen gesicherten Ergebnisstand wählen."))
            return
        project, identifier = self._project, self._project.data["selected_step"]
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Gesicherten Stand exportieren"))
        dialog.resize(560, 230)
        layout = QVBoxLayout(dialog)
        info = QLabel(tr("Ergebnisdatei und Begleitdateien werden mit geprüften Prüfsummen unverändert kopiert. "
                         "FITS-Pixel, Header und Abdeckungsmasken bleiben erhalten. Es entsteht keine JPG- oder 16-bit-Konvertierung."))
        info.setWordWrap(True)
        layout.addWidget(info)
        destination_label = QLabel()
        destination_label.setWordWrap(True)
        destination_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(destination_label)
        layout.addStretch()
        row = QHBoxLayout()
        folder = QPushButton(tr("Exportordner öffnen"))
        folder.setEnabled(False)
        row.addWidget(folder)
        row.addStretch()
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(dialog.reject)
        row.addWidget(close)
        save = QPushButton(tr("Speicherort wählen und kopieren"))
        save.setObjectName("primary")
        row.addWidget(save)
        layout.addLayout(row)
        self._project_export_dialog = dialog
        self._last_project_export = None

        def execute():
            parent = QFileDialog.getExistingDirectory(dialog, tr("Speicherort wählen"), str(project.path.parent))
            if not parent:
                return
            try:
                destination = Path(parent) / ("stack-export-project-" + uuid.uuid4().hex[:8])
                exported = self._project_job(tr("Ergebnisdateien kopieren"),
                    lambda: project.export_step(identifier, destination))
                self._last_project_export = exported
                destination_label.setText(tr("Unverändert exportiert: {path}").format(path=exported))
                self._append(tr("Unverändert exportiert: {path}").format(path=exported) + "\n")
                folder.setEnabled(True)
            except (ProjectError, OSError, ValueError) as exc:
                QMessageBox.warning(dialog, tr("Exportieren"), str(exc))

        def open_folder():
            from ui.components import reveal_in_files
            if self._last_project_export:
                reveal_in_files(self._last_project_export)
        save.clicked.connect(execute)
        folder.clicked.connect(open_folder)
        dialog.copy_button, dialog.close_button = save, close
        dialog.exec()
        dialog.deleteLater()
        self._project_export_dialog = None

    def add_project_result(self):
        if not self._project_ready():
            return
        if self._project is None:
            QMessageBox.information(self, tr("Projekt"), tr("Zuerst ein Projekt anlegen oder öffnen."))
            return
        before = self.result_path
        self.reimport_result()
        selected = self._project.data.get("selected_step")
        if selected and self.result_path != before:
            try:
                self._open_project_step(selected)
            except (ProjectError, OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("Projekt"), str(exc))

    def _project_workspace(self):
        return {"input_directory": self.in_edit.text().strip(), "work_directory": self.work_edit.text().strip(),
                "module": self.task_box.currentIndex()}

    def _project_ready(self):
        active = getattr(self, "_tool_worker", None)
        ai = getattr(self, "_ai_restore_dialog", None)
        recipe = getattr(self, "_recipe_dialog", None)
        catalogue_busy = any(dialog is not None and dialog.is_running() for dialog in
                             (getattr(self, "_astrometry_dialog", None), getattr(self, "_catalogue_dialog", None)))
        if (getattr(self, "_project_worker", None) is not None
                or (self.proc and self.proc.state() != QProcess.NotRunning)
                or (active is not None and active.isRunning()) or (ai is not None and ai.is_running())
                or (recipe is not None and recipe.is_running()) or catalogue_busy):
            QMessageBox.information(self, tr("Projekt"), tr("Bitte zuerst die laufende Verarbeitung abschließen."))
            return False
        return True

    def _project_job(self, title, operation):
        worker = _ProjectWorker(operation, self)
        self._project_worker = worker
        dialog = _ProjectWait(title, worker, self)
        worker.finished.connect(dialog.accept)
        worker.start()
        dialog.exec()
        # finished is queued after run() returns. Never destroy a live QThread.
        worker.wait()
        self._project_worker = None
        value, error = worker.value, worker.error
        worker.deleteLater()
        dialog.deleteLater()
        if error:
            raise ProjectError(error)
        return value

    def _project_title(self):
        base = tr("ForgePix — Astrofotos einfach entwickeln")
        self.setWindowTitle(base + (" · " + self._project.data["name"] if self._project else ""))

    def new_project(self):
        if not self._project_ready():
            return
        filename, _ = QFileDialog.getSaveFileName(self, tr("Neues Projekt"),
                                                 os.path.join(self._work_dir(), "Astroprojekt.forgepix"),
                                                 "ForgePix-Projekt (*.forgepix)")
        if not filename:
            return
        if not filename.lower().endswith(".forgepix"):
            filename += ".forgepix"
        workspace = self._project_workspace()
        try:
            self._project = self._project_job(tr("Projekt anlegen"),
                lambda: Project.create(filename, Path(filename).stem, workspace))
            self._project_title()
            self._append(tr("Projekt angelegt: {path}").format(path=filename) + "\n")
            self._record_project_result(tr("Ausgangsergebnis"))
        except ProjectError as exc:
            QMessageBox.warning(self, tr("Projekt"), str(exc))

    def save_project(self):
        if not self._project_ready():
            return False
        if self._project is None:
            self.new_project()
            return self._project is not None
        workspace = self._project_workspace()
        try:
            self._project_job(tr("Projekt speichern"), lambda: self._project.save(workspace))
            self._append(tr("Projekt gespeichert: {path}").format(path=self._project.path) + "\n")
            return True
        except ProjectError as exc:
            QMessageBox.warning(self, tr("Projekt"), str(exc))
            return False

    def open_project(self):
        if not self._project_ready():
            return
        filename, _ = QFileDialog.getOpenFileName(self, tr("Projekt öffnen"), self._work_dir(),
                                                 "ForgePix-Projekt (*.forgepix)")
        if not filename:
            return
        try:
            project, checks = self._project_job(tr("Projekt prüfen"), lambda: _load_checked(filename))
            self._project = project
            self._project_title()
            workspace = project.data["workspace"]
            self._choose_module(workspace["module"])
            warnings = []
            for key, widget in (("input_directory", self.in_edit), ("work_directory", self.work_edit)):
                ref = workspace.get(key)
                path = resolve(ref, project.path.parent) if ref else None
                widget.setText(str(path) if path else "")
                if path and not path.is_dir():
                    warnings.append(tr("Ordner fehlt: {path}").format(path=path))
            self._project_clear_result()
            selected = project.data.get("selected_step")
            if selected:
                status = checks[selected]
                if status["result"]["status"] == "ok" and all(x["status"] == "ok" for x in status["artifacts"]):
                    self._open_project_step(selected)
                else:
                    warnings.append(tr("Der zuletzt gewählte Ergebnisstand fehlt oder wurde verändert. Bitte den Projektverlauf öffnen."))
            affected = sum(any(item["status"] != "ok" for key, item in value.items() if key != "artifacts")
                           or any(item["status"] != "ok" for item in value["artifacts"]) for value in checks.values())
            if affected:
                warnings.append(tr("Bei {count} Ergebnisständen fehlen oder unterscheiden sich Dateien. Details stehen im Projektverlauf.").format(count=affected))
            self._append(tr("Projekt geöffnet: {path}").format(path=filename) + "\n")
            if warnings:
                QMessageBox.warning(self, tr("Projektdateien prüfen"), "\n".join(warnings))
        except (ProjectError, OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Projekt"), str(exc))

    def _project_clear_result(self):
        self.result_path = self.before_path = None
        self._ai_result_path = self._ai_display = self._ai_report = None
        self._project_standalone_preview = None
        self._preview_pix = self._preview_src = None
        self.preview.setPixmap(QPixmap())
        self.preview.setText(tr("Projekt geöffnet. Einen gespeicherten Ergebnisstand im Verlauf wählen oder neue Bilder verarbeiten."))
        self._clear_filmstrip()
        self.decision.setText(tr("Projektverlauf öffnen, um gespeicherte Ergebnisstände zu prüfen."))
        for widget in (self.cmp_btn, self.export_btn, self.open_btn, self.openfolder_btn, self.enhance_btn,
                       self.starless_btn, self.graxpert_btn, self.starnet_btn, self.retouch_btn,
                       self.send_btn, self.reimport_btn, self.ghost_btn, *self.export_chips):
            widget.setEnabled(False)

    def _record_project_result(self, label="Ergebnis übernommen"):
        if (getattr(self, "_project", None) is None or getattr(self, "_project_loading", False)
                or getattr(self, "_project_worker", None) is not None or not self.result_path
                or (self.proc and self.proc.state() != QProcess.NotRunning)):
            return
        source, comparison, workspace = self.result_path, self.before_path, self._project_workspace()
        try:
            identifier = self._project_job(tr("Ergebnisstand sichern"),
                lambda: self._project.add_result(source, comparison, str(label), workspace))
            self._append(tr("Projekt: Ergebnisstand gesichert — {name}").format(name=self._project.step(identifier)["label"]) + "\n")
        except ProjectError as exc:
            self._append(tr("Projektstand konnte nicht gesichert werden: {reason}").format(reason=exc) + "\n")
            QMessageBox.warning(self, tr("Projektstand nicht gesichert"), str(exc))

    def open_project_history(self):
        if not self._project_ready():
            return
        if self._project is None:
            QMessageBox.information(self, tr("Projektverlauf"), tr("Zuerst ein Projekt anlegen oder öffnen."))
            return
        from ui.project_dialog import ProjectHistoryDialog
        try:
            checks = self._project_job(tr("Ergebnisstände prüfen"), self._project.check)
            dialog = ProjectHistoryDialog(self._project, checks, self)
            self._project_history_dialog = dialog
            if dialog.exec() == QDialog.Accepted:
                if dialog.relocate_requested:
                    path, _ = QFileDialog.getOpenFileName(self, tr("Identische Ergebnisdatei wählen"),
                                                         str(self._project.path.parent), "Bilder (*.fits *.fit *.fts *.tif *.tiff *.png *.jpg *.jpeg)")
                    if path:
                        self._project_job(tr("Datei prüfen und zuordnen"),
                            lambda: self._project.relocate(dialog.selected_step, path))
                        self.open_project_history()
                else:
                    self._open_project_step(dialog.selected_step)
            dialog.deleteLater()
        except (ProjectError, OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Projektverlauf"), str(exc))
        finally:
            self._project_history_dialog = None

    def _open_project_step(self, identifier):
        result, comparison = self._project_job(tr("Ergebnisstand öffnen"), lambda: self._project.select(identifier))
        self._project_loading = True
        self._project_standalone_preview = None
        try:
            self._ai_result_path = self._ai_display = self._ai_report = None
            is_ai = self._restore_ai_result_context(result)
            if is_ai:
                if comparison and self._ai_report.get("source", {}).get("sha256") == self._project.step(identifier)["comparison"]["sha256"]:
                    from ui.ai_preview import create_previews
                    try:
                        self._ai_display = create_previews(comparison, result)
                    except Exception:
                        self._ai_display = None
                comparison = self._ai_display["source"] if self._ai_display else None
            # A standalone linear preview remains usable if the original
            # comparison was lost; it is never presented as a linked pair.
            if not is_ai or self._ai_display is None:
                self._project_standalone_preview = self._project_job(tr("Ergebnisvorschau laden"),
                                                                    lambda: _standalone_preview(result))
            self._adopt_result(result, comparison)
            self.cmp_btn.setEnabled(bool(comparison))
            self.export_btn.setEnabled(True)
            self.tools_btn.setEnabled(True)
            self.reimport_btn.setEnabled(True)
            self.send_btn.setEnabled(True)
            sky = bool(getattr(self, "is_astro", False) or getattr(self, "is_longexp", False)
                       or getattr(self, "is_hybrid", False))
            for widget in (self.enhance_btn, self.starless_btn, self.graxpert_btn, self.starnet_btn):
                widget.setEnabled(sky)
            self.ghost_btn.setEnabled(False)
            self.view_focusmap.setEnabled(False)
            self.view_ghost.setEnabled(False)
            for widget in self.export_chips:
                widget.setEnabled(True)
            self.view_result.setChecked(True)
            self.view_result.setEnabled(True)
            self._clear_filmstrip()
            self._append(tr("Gespeicherten Ergebnisstand geöffnet: {name}").format(name=self._project.step(identifier)["label"]) + "\n")
        finally:
            self._project_loading = False

    def _project_preview_for(self, path):
        entry = getattr(self, "_project_standalone_preview", None)
        if entry and os.path.realpath(path) == entry["source"]:
            stat = Path(path).stat()
            if stat.st_mtime_ns == entry["mtime_ns"] and stat.st_size == entry["bytes"]:
                return entry["preview"]
        return None


def _load_checked(filename):
    project = Project.open(filename)
    return project, project.check()


def _standalone_preview(source):
    if Path(source).suffix.lower() not in {".fits", ".fit", ".fts", ".tif", ".tiff"}:
        return None
    import cv2
    import numpy as np
    import tifffile
    from astropy.io import fits
    from ui.ai_preview import display_parameters, display_pixels, write_display
    from ui.appinfo import _cache_path
    try:
        path = Path(source)
        if path.suffix.lower() in {".fits", ".fit", ".fts"}:
            with fits.open(path, memmap=False) as hdus:
                pixels, metadata = hdus[0].data, dict(hdus[0].header)
                if pixels is None:
                    return None
                if pixels.ndim == 3 and pixels.shape[0] == 3:
                    pixels = np.moveaxis(pixels, 0, -1)
        else:
            with tifffile.TiffFile(path) as image:
                pixels = image.asarray()
                try:
                    metadata = json.loads(image.pages[0].description or "{}")
                except ValueError:
                    metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            if isinstance(metadata.get("fits_header"), str):
                embedded = dict(fits.Header.fromstring(metadata["fits_header"], sep="\n"))
                metadata = dict(embedded, **metadata)
        if pixels.ndim not in (2, 3) or (pixels.ndim == 3 and pixels.shape[-1] != 3):
            return None
        pixels = np.asarray(pixels, np.float64)
        valid = np.isfinite(pixels)
        mask_name = metadata.get("FPDRZCOV") or metadata.get("FPCOV")
        if mask_name:
            if not isinstance(mask_name, str) or Path(mask_name).name != mask_name or "/" in mask_name or "\\" in mask_name:
                return None
            mask = tifffile.imread(path.parent / mask_name)
            if not np.isin(mask, [0, 1]).all():
                return None
            if mask.shape == pixels.shape[:2] and pixels.ndim == 3:
                mask = np.broadcast_to(mask[..., None], pixels.shape)
            if mask.shape != pixels.shape:
                return None
            valid &= mask.astype(bool)
        if not valid.any():
            return None
        shown = display_pixels(np.where(valid, pixels, 0), display_parameters(pixels[valid]))
        shown[~valid] = 0  # Display only. Scientific pixels are never changed.
        if max(shown.shape[:2]) > 1400:
            factor = 1400 / max(shown.shape[:2])
            shown = cv2.resize(shown, (max(1, round(shown.shape[1] * factor)),
                                       max(1, round(shown.shape[0] * factor))), interpolation=cv2.INTER_AREA)
        preview = _cache_path("fp_project_linear_", source)
        write_display(preview, shown)
        stat = Path(source).stat()
        return {"source": os.path.realpath(source), "preview": preview,
                "mtime_ns": stat.st_mtime_ns, "bytes": stat.st_size}
    except Exception:
        return None
