"""Editable, repeatable local processing recipes with cooperative cancellation."""
from copy import deepcopy
from pathlib import Path
import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from i18n import tr
from ui.ai_restore_dialog import TASKS


class _RecipeWorker(QThread):
    progress = Signal(int, int, int, int)
    message = Signal(str)
    step_done = Signal(int)

    def __init__(self, request, project=None, workspace=None, parent=None):
        super().__init__(parent)
        self.request, self.project, self.workspace = request, project, workspace
        self.cancel_event = threading.Event()
        self.report = None
        self.error = None
        self.previews = None
        self.project_step = None

    def run(self):
        try:
            import recipes
            previous = self.request["source"]

            def finished(index, path, record):
                nonlocal previous
                if self.project is not None:
                    # A later archive failure must not leave the id of an older
                    # result masquerading as the chain's final output.
                    self.project_step = None
                    label = dict((key, tr(title)) for key, title, _ in TASKS).get(
                        self.request["recipe"]["steps"][index - 1]["task"], "KI")
                    self.project_step = self.project.add_result(
                        path, previous, tr("Rezept: ") + label, self.workspace)
                previous = path
                self.step_done.emit(index)

            self.report = recipes.run_recipe(
                **self.request, cancel=self.cancel_event,
                progress=self.progress.emit, on_step=finished,
                log=lambda *parts, **kw: self.message.emit(" ".join(map(str, parts))))
            if self.report.get("result_path") and not self.cancel_event.is_set():
                from ui.ai_preview import create_previews
                # Preview preparation is separate from the scientific run. A
                # cancelled chain may still have usable completed steps.
                try:
                    self.previews = create_previews(self.report["input_snapshot"]["path"],
                                                    self.report["result_path"])
                except Exception as exc:
                    self.message.emit(tr("Vorschau nicht verfügbar: ") + str(exc))
        except Exception as exc:
            self.error = str(exc)


class RecipeDialog(QDialog):
    """The recipe is portable; the input and output location belong to a run."""

    def __init__(self, parent=None, source=None, model_dir=None, project=None, workspace=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Bearbeitungsrezepte"))
        self.resize(950, 700)
        self.model_dir, self.project, self.workspace = model_dir, project, workspace
        self.worker = None
        self.report = None
        self.result_path = None
        self.source_path = None
        self.previews = None
        self.project_step = None
        self._close_when_finished = False
        self._editing = False
        self._steps = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel(tr("Wiederholbare Bearbeitung"))
        heading.setObjectName("sectionHeader")
        layout.addWidget(heading)
        intro = QLabel(tr("Stelle deinen Ablauf zusammen und wende ihn auf weitere lineare FITS an. "
                          "Jeder Schritt erzeugt ein eigenes Ergebnis mit Laufbericht."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.editor = QWidget()
        edit_layout = QVBoxLayout(self.editor)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(10)
        bar = QHBoxLayout()
        self.name = QLineEdit(tr("Mein Astro-Rezept"))
        self.name.setAccessibleName(tr("Rezeptname"))
        bar.addWidget(self.name, 1)
        self.load_button = QPushButton(tr("Öffnen …"))
        self.load_button.clicked.connect(self.load)
        bar.addWidget(self.load_button)
        self.save_button = QPushButton(tr("Speichern …"))
        self.save_button.clicked.connect(self.save)
        bar.addWidget(self.save_button)
        edit_layout.addLayout(bar)
        form = QFormLayout()
        self.source = QLineEdit(str(source or ""))
        source_button = QPushButton(tr("Wählen …"))
        source_button.clicked.connect(self.pick_source)
        form.addRow(tr("Lineares Bild"), self._row(self.source, source_button))
        self.destination = QLineEdit()
        self.destination.setPlaceholderText(tr("Leer = eigener Laufordner neben dem Eingabebild"))
        destination_button = QPushButton(tr("Wählen …"))
        destination_button.clicked.connect(self.pick_destination)
        form.addRow(tr("Ergebnisordner"), self._row(self.destination, destination_button))
        edit_layout.addLayout(form)
        split = QSplitter(Qt.Horizontal)
        list_panel = QWidget()
        left = QVBoxLayout(list_panel)
        left.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Schritt"), tr("Wirkung"), tr("Status")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setMinimumHeight(190)
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 72)
        self.tree.currentItemChanged.connect(self.selection_changed)
        left.addWidget(self.tree, 1)
        add_row = QHBoxLayout()
        self.task = QComboBox()
        for key, title, _ in TASKS:
            self.task.addItem(tr(title), key)
        add_row.addWidget(self.task, 1)
        self.add_button = QPushButton(tr("Hinzufügen"))
        self.add_button.clicked.connect(self.add_step)
        add_row.addWidget(self.add_button)
        left.addLayout(add_row)
        controls = QHBoxLayout()
        self.up_button = QPushButton(tr("Nach oben"))
        self.down_button = QPushButton(tr("Nach unten"))
        self.remove_button = QPushButton(tr("Entfernen"))
        self.up_button.clicked.connect(lambda: self.move_step(-1))
        self.down_button.clicked.connect(lambda: self.move_step(1))
        self.remove_button.clicked.connect(self.remove_step)
        for button in (self.up_button, self.down_button, self.remove_button):
            controls.addWidget(button)
        controls.addStretch()
        left.addLayout(controls)
        split.addWidget(list_panel)
        self.parameters = QWidget()
        right = QVBoxLayout(self.parameters)
        right.setContentsMargins(14, 0, 0, 0)
        self.step_title = QLabel(tr("Schritt auswählen"))
        self.step_title.setObjectName("sectionHeader")
        self.step_title.setWordWrap(True)
        right.addWidget(self.step_title)
        self.description = QLabel()
        self.description.setWordWrap(True)
        right.addWidget(self.description)
        params = QFormLayout()
        self.strength = QDoubleSpinBox()
        self.strength.setRange(0, 100)
        self.strength.setDecimals(0)
        self.strength.setSingleStep(5)
        self.strength.setSuffix(" %")
        self.strength.valueChanged.connect(self.change_parameters)
        params.addRow(tr("Wirkung"), self.strength)
        self.device = QComboBox()
        for title, key in (("Automatisch · GPU bevorzugt", "auto"), ("Prozessor", "cpu"),
                           ("GPU", "gpu"), ("CUDA", "cuda"), ("DirectML", "directml"),
                           ("CoreML", "coreml")):
            self.device.addItem(tr(title), key)
        self.device.currentIndexChanged.connect(self.change_parameters)
        params.addRow(tr("Berechnung"), self.device)
        right.addLayout(params)
        self.model_label = QLabel()
        self.model_label.setWordWrap(True)
        self.model_label.setObjectName("hint")
        right.addWidget(self.model_label)
        right.addStretch()
        split.addWidget(self.parameters)
        split.setSizes([550, 310])
        edit_layout.addWidget(split, 1)
        self.confirm = QCheckBox(tr("Experimentelle KI-Schritte auf einem linearen Stack ausführen"))
        edit_layout.addWidget(self.confirm)
        layout.addWidget(self.editor, 1)
        self.feedback = QLabel(tr("Füge den ersten Bearbeitungsschritt hinzu."))
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.output = QLineEdit()
        self.output.setReadOnly(True)
        self.output.hide()
        layout.addWidget(self.output)
        buttons = QHBoxLayout()
        self.result_button = QPushButton(tr("Ergebnis ansehen"))
        self.result_button.setEnabled(False)
        self.result_button.clicked.connect(self.accept_result)
        buttons.addWidget(self.result_button)
        self.folder_button = QPushButton(tr("Laufordner öffnen"))
        self.folder_button.setEnabled(False)
        self.folder_button.clicked.connect(self.open_run_folder)
        buttons.addWidget(self.folder_button)
        buttons.addStretch()
        self.close_button = QPushButton(tr("Schließen"))
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        self.run_button = QPushButton(tr("Rezept ausführen"))
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.start)
        buttons.addWidget(self.run_button)
        layout.addLayout(buttons)
        for signal in (self.source.textChanged, self.name.textChanged,
                       self.destination.textChanged, self.confirm.toggled):
            signal.connect(self.refresh)
        self.rebuild()

    @staticmethod
    def _row(*widgets):
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            layout.addWidget(widget, 1 if isinstance(widget, QLineEdit) else 0)
        return host

    def recipe(self):
        return {"format": "ForgePixRecipe", "schema_version": 1,
                "name": self.name.text().strip(), "steps": deepcopy(self._steps)}

    def set_recipe(self, recipe):
        self.name.setText(recipe["name"])
        self._steps = deepcopy(recipe["steps"])
        self.confirm.setChecked(False)
        self.rebuild(0)

    def current_index(self):
        return self.tree.indexOfTopLevelItem(self.tree.currentItem())

    def rebuild(self, selected=0):
        self.tree.clear()
        names = {key: tr(title) for key, title, _ in TASKS}
        for index, step in enumerate(self._steps):
            item = QTreeWidgetItem([f"{index + 1}. {names[step['task']]}",
                                    f"{step['strength'] * 100:.0f} %", tr("Bereit")])
            self.tree.addTopLevelItem(item)
        if self._steps:
            self.tree.setCurrentItem(self.tree.topLevelItem(max(0, min(selected, len(self._steps) - 1))))
        self.selection_changed()
        self.refresh()

    def selection_changed(self, *_):
        index = self.current_index()
        valid = 0 <= index < len(self._steps)
        self.parameters.setEnabled(valid)
        self.remove_button.setEnabled(valid)
        self.up_button.setEnabled(index > 0)
        self.down_button.setEnabled(valid and index < len(self._steps) - 1)
        if not valid:
            self.step_title.setText(tr("Schritt auswählen"))
            self.description.clear()
            self.model_label.clear()
            return
        step = self._steps[index]
        title, description = next((title, desc) for key, title, desc in TASKS if key == step["task"])
        self._editing = True
        self.step_title.setText(tr(title))
        self.description.setText(tr(description))
        self.strength.setValue(step["strength"] * 100)
        self.device.setCurrentIndex(self.device.findData(step["device"]))
        self.model_label.setText(tr("Modellversion fest im Rezept gespeichert.") + "\n" + step["model_id"])
        self.model_label.setToolTip("SHA256: " + step["model_sha256"])
        self._editing = False

    def change_parameters(self, *_):
        index = self.current_index()
        if self._editing or index < 0:
            return
        self._steps[index].update(strength=self.strength.value() / 100, device=self.device.currentData())
        self.tree.topLevelItem(index).setText(1, f"{self.strength.value():.0f} %")

    def add_step(self):
        try:
            import ai_restore
            import recipes
            candidates = [m for m in ai_restore.list_models(self.model_dir)
                          if m.get("available") and m.get("task") == self.task.currentData()]
            if not candidates:
                raise ValueError(tr("Kein verwendbares lokales Modell für diesen Schritt vorhanden."))
            self._steps.append(recipes.pin_step(candidates[0]["id"], model_dir=self.model_dir))
            self.rebuild(len(self._steps) - 1)
            self.feedback.setText(tr("Reihenfolge und Wirkung lassen sich pro Schritt anpassen."))
        except Exception as exc:
            self.feedback.setText(str(exc))

    def move_step(self, offset):
        index = self.current_index()
        target = index + offset
        if 0 <= index < len(self._steps) and 0 <= target < len(self._steps):
            self._steps[index], self._steps[target] = self._steps[target], self._steps[index]
            self.rebuild(target)

    def remove_step(self):
        index = self.current_index()
        if index >= 0:
            del self._steps[index]
            self.rebuild(index)

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Rezept öffnen"), "", tr("ForgePix-Rezept (*.fprecipe *.json)"))
        if path:
            try:
                import recipes
                self.set_recipe(recipes.load_recipe(path))
                self.feedback.setText(tr("Rezept geladen. Eingabebild und Schritte prüfen."))
            except Exception as exc:
                QMessageBox.warning(self, tr("Rezept öffnen"), str(exc))

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Rezept speichern"), "Astro.fprecipe",
                                             tr("ForgePix-Rezept (*.fprecipe)"))
        if path:
            try:
                import recipes
                if not Path(path).suffix:
                    path += ".fprecipe"
                recipes.save_recipe(path, self.recipe())
                self.feedback.setText(tr("Rezept gespeichert: ") + path)
            except Exception as exc:
                QMessageBox.warning(self, tr("Rezept speichern"), str(exc))

    def pick_source(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Linearen Stack wählen"), self.source.text(),
                                             "FITS / TIFF (*.fit *.fits *.fts *.tif *.tiff)")
        if path:
            self.source.setText(path)

    def pick_destination(self):
        path = QFileDialog.getExistingDirectory(self, tr("Ergebnisordner wählen"), self.destination.text())
        if path:
            self.destination.setText(path)

    def refresh(self, *_):
        source = Path(self.source.text().strip())
        destination = self.destination.text().strip()
        self.run_button.setEnabled(not self.is_running() and bool(self._steps) and bool(self.name.text().strip())
            and source.is_file() and source.suffix.lower() in {".fit", ".fits", ".fts", ".tif", ".tiff"}
            and self.confirm.isChecked() and (not destination or Path(destination).is_dir()))
        self.save_button.setEnabled(bool(self._steps) and bool(self.name.text().strip()))

    def is_running(self):
        return self.worker is not None

    def start(self):
        if self.is_running() or not self.run_button.isEnabled():
            return
        self.result_path = self.report = self.previews = self.project_step = None
        self.source_path = self.source.text().strip()
        self._close_when_finished = False
        request = dict(recipe=self.recipe(), source=self.source_path,
                       output_root=self.destination.text().strip() or str(Path(self.source_path).parent),
                       model_dir=self.model_dir, allow_experimental=self.confirm.isChecked())
        self.worker = _RecipeWorker(request, self.project, self.workspace, self)
        self.worker.progress.connect(self.show_progress)
        self.worker.message.connect(self.feedback.setText)
        self.worker.step_done.connect(lambda index: self.tree.topLevelItem(index - 1).setText(2, tr("Gesichert")))
        self.worker.finished.connect(self.finished_run)
        self.editor.setEnabled(False)
        self.run_button.setEnabled(False)
        self.result_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        self.output.hide()
        self.close_button.setText(tr("Abbrechen"))
        self.progress.setValue(0)
        self.progress.show()
        for index in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(index).setText(2, tr("Wartet"))
        self.feedback.setText(tr("Eingabe und Modellversionen werden geprüft …"))
        self.worker.start()

    def show_progress(self, index, count, done, total):
        self.progress.setValue(round(100 * (index - 1 + done / max(total, 1)) / max(count, 1)))
        if 1 <= index <= self.tree.topLevelItemCount():
            self.tree.topLevelItem(index - 1).setText(2, tr("Läuft"))

    def finished_run(self):
        worker = self.worker
        worker.wait()
        self.report, self.previews, self.project_step = worker.report, worker.previews, worker.project_step
        error = worker.error
        self.worker = None
        worker.deleteLater()
        self.editor.setEnabled(True)
        self.close_button.setText(tr("Schließen"))
        self.close_button.setEnabled(True)
        if self.report:
            self.result_path = self.report.get("result_path")
            statuses = {"pending": tr("Nicht ausgeführt"), "running": tr("Unterbrochen"),
                        "completed": tr("Gesichert"), "cancelled": tr("Abgebrochen"),
                        "failed": tr("Fehlgeschlagen")}
            for index, step in enumerate(self.report.get("steps", [])):
                if index < self.tree.topLevelItemCount():
                    item = self.tree.topLevelItem(index)
                    item.setText(2, tr("Sicherung fehlgeschlagen") if step.get("callback_status") == "failed"
                                 else statuses.get(step.get("status"), tr("Nicht ausgeführt")))
                    item.setToolTip(2, str(step.get("error") or step.get("callback_error") or ""))
            status = self.report.get("status")
            text = {"completed": tr("Rezept abgeschlossen. Ergebnisse und Laufbericht sind gespeichert."),
                    "cancelled": tr("Abgebrochen. Fertige Schritte bleiben im Laufordner erhalten."),
                    "failed": tr("Verarbeitung fehlgeschlagen. Fertige Schritte bleiben erhalten.")}.get(status, status)
            if self.report.get("error"):
                text += "\n" + str(self.report["error"])
            self.feedback.setText(text)
            self.progress.setValue(100 if status == "completed" else self.progress.value())
            self.output.setText(str(self.report.get("run_dir", "")))
            self.output.show()
            self.folder_button.setEnabled(bool(self.report.get("run_dir")))
        else:
            self.feedback.setText(error or tr("Rezept konnte nicht gestartet werden."))
        self.result_button.setEnabled(bool(self.result_path))
        self.refresh()
        if self._close_when_finished:
            super().reject()

    def open_run_folder(self):
        if self.report and self.report.get("run_dir"):
            from ui.components import reveal_in_files
            reveal_in_files(self.report["run_dir"])

    def accept_result(self):
        if not self.is_running() and self.result_path:
            self.accept()

    def cancel_and_close(self):
        if self.is_running():
            self._close_when_finished = True
            self.worker.cancel_event.set()
            self.close_button.setEnabled(False)
            self.feedback.setText(tr("Abbruch angefordert. Der laufende Schritt wird sicher beendet …"))
        else:
            super().reject()

    def reject(self):
        if self.is_running():
            self.worker.cancel_event.set()
            self.close_button.setEnabled(False)
            self.feedback.setText(tr("Abbruch angefordert. Fertige Schritte bleiben erhalten …"))
        else:
            super().reject()

    def closeEvent(self, event):
        if self.is_running():
            self.cancel_and_close()
            event.ignore()
        else:
            super().closeEvent(event)
