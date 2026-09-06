"""Opt-in local model inference with a cancellable worker and preserved inputs."""
from pathlib import Path
import json
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from i18n import tr


TASKS = (
    ("denoise", "Rauschen reduzieren",
     "Dämpft Bildrauschen. Prüfe besonders schwache Nebel und kleine Sterne."),
    ("background", "Hintergrund ausgleichen",
     "Verringert Helligkeitsverläufe im Hintergrund. Prüfe, ob ausgedehnte Nebel erhalten bleiben."),
    ("deblur", "Unschärfe reduzieren",
     "Versucht feine Details deutlicher zu trennen. Prüfe Sternformen und helle Kanten."),
    ("starless", "Sterne entfernen",
     "Erzeugt eine Ansicht mit weniger Sternen. Große Sterne und Halos können zurückbleiben."),
)


def _execution_feedback(execution):
    """Describe the completed runtime record, without claiming GPU placement."""
    if not execution:
        return tr("Rechenbackend im Ergebnisbericht nicht angegeben.")
    if execution.get("applied") is False:
        return tr("0 % Wirkung: Original übernommen, kein Modell ausgeführt.")
    provider = execution.get("provider")
    if provider == "CPUExecutionProvider":
        if execution.get("fallback_used"):
            return tr("Mit Prozessor berechnet; Grafikbeschleunigung war nicht verfügbar.")
        return tr("Mit Prozessor berechnet.")
    names = {"CUDAExecutionProvider": "CUDA", "DmlExecutionProvider": "DirectML",
             "CoreMLExecutionProvider": "CoreML"}
    if provider in names:
        return tr("Rechenbackend: {name}.").format(name=names[provider])
    return tr("Rechenbackend im Ergebnisbericht nicht angegeben.")


class _RestoreWorker(QThread):
    progress = Signal(int, int)
    message = Signal(str)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request
        self.cancel_event = threading.Event()
        self.result = None
        self.error = None
        self.previews = None
        self.execution = None

    def run(self):
        try:
            import ai_restore
            self.result = ai_restore.run_file(
                **self.request, cancel=self.cancel_event,
                progress=self.progress.emit, log=lambda *parts, **_kwargs: self.message.emit(
                    " ".join(str(part) for part in parts)))
            # Read the execution record from this completed result. A provider
            # merely installed on the computer is not evidence of GPU work.
            try:
                report = json.loads((Path(self.result).parent / "ai_report.json").read_text(encoding="utf-8"))
                if isinstance(report.get("execution"), dict):
                    self.execution = report["execution"]
            except (OSError, ValueError, AttributeError):
                pass
            from ui.ai_preview import create_previews
            self.message.emit(tr("Vergleichsvorschau wird vorbereitet …"))
            self.previews = create_previews(self.request["source"], self.result, self.cancel_event)
        except Exception as exc:
            self.error = str(exc)


class AIRestoreDialog(QDialog):
    """Do not release this dialog until its worker's finished signal arrives."""

    def __init__(self, parent=None, source=None, model_dir=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Eigene KI-Bildverarbeitung"))
        self.resize(660, 620)
        self.worker = None
        self._close_when_finished = False
        self.result_path = None
        self.source_path = None
        self.show_comparison = False
        self.previews = None
        self.execution = None
        self.models = []
        self._catalogue_error = ""
        self._loaded_model_dir = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        status = QLabel(tr("EXPERIMENTELLE MODELLE"))
        status.setObjectName("sectionHeader")
        layout.addWidget(status)
        intro = QLabel(tr("Eigene Modelle verarbeiten dein Bild lokal. KI kann schwache Strukturen "
                          "oder Sternformen verändern. Prüfe das Ergebnis im Vergleich."))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.source = QLineEdit(source or "")
        self.source.setPlaceholderText(tr("Ungestreckten FITS- oder TIFF-Stack wählen"))
        self.source_pick = QPushButton(tr("Wählen…"))
        self.source_pick.clicked.connect(self.pick_source)
        form.addRow(tr("Lineares Bild"), self._row(self.source, self.source_pick))
        self.task = QComboBox()
        self.task.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for key, label, _description in TASKS:
            self.task.addItem(tr(label), key)
        form.addRow(tr("Funktion"), self.task)
        self.strength = QDoubleSpinBox()
        self.strength.setRange(0, 100)
        self.strength.setDecimals(0)
        self.strength.setSingleStep(5)
        self.strength.setValue(50)
        self.strength.setSuffix(" %")
        self.strength.setToolTip(tr("0 % erhält das Original, 100 % übernimmt die volle Modellwirkung."))
        form.addRow(tr("Wirkung"), self.strength)
        self.device = QComboBox()
        self.device.addItem(tr("Automatisch (Grafikkarte bevorzugen)"), "auto")
        self.device.addItem(tr("Nur Prozessor"), "cpu")
        self.device.setToolTip(tr("Automatisch verwendet ein verfügbares Grafik-Backend. Falls das nicht möglich ist, wird der Prozessor verwendet."))
        form.addRow(tr("Berechnung"), self.device)
        self.destination = QLineEdit()
        self.destination.setPlaceholderText(tr("Neuer Ergebnisordner neben der Quelldatei"))
        self.destination_pick = QPushButton(tr("Wählen…"))
        self.destination_pick.clicked.connect(self.pick_destination)
        form.addRow(tr("Speicherort"), self._row(self.destination, self.destination_pick))
        layout.addLayout(form)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.model_status = QLabel()
        self.model_status.setWordWrap(True)
        self.model_status.setObjectName("hint")
        layout.addWidget(self.model_status)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText(tr("Modellordner ändern"))
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle)
        self.model_directory = QLineEdit(str(model_dir) if model_dir else "")
        self.model_directory.setPlaceholderText(tr("Leer = mitgelieferte Modelle"))
        self.model_directory.editingFinished.connect(self.reload_models)
        self.model_pick = QPushButton(tr("Wählen…"))
        self.model_pick.clicked.connect(self.pick_models)
        self.reload_button = QPushButton(tr("Neu einlesen"))
        self.reload_button.clicked.connect(self.reload_models)
        self.advanced = self._row(self.model_directory, self.model_pick, self.reload_button)
        self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        layout.addWidget(self.advanced)
        self.confirm = QCheckBox(tr("Linearen Stack verwenden und experimentelles Modell testen"))
        self.confirm.setToolTip(tr("Keine Bayer-Rohaufnahme und kein bereits gestrecktes Bild verwenden. "
                                   "Das Original bleibt erhalten; das Ergebnis wird separat gespeichert."))
        layout.addWidget(self.confirm)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.output_path = QLineEdit()
        self.output_path.setReadOnly(True)
        self.output_path.hide()
        layout.addWidget(self.output_path)
        self.result_button = QPushButton(tr("Ergebnis ansehen"))
        self.result_button.clicked.connect(lambda: self.finish_with_result(False))
        self.compare_button = QPushButton(tr("Vorher / Nachher"))
        self.compare_button.clicked.connect(lambda: self.finish_with_result(True))
        self.result_actions = self._row(self.result_button, self.compare_button)
        self.result_actions.hide()
        self.feedback.setToolTip("")
        layout.addWidget(self.result_actions)
        layout.addStretch()
        self.run_button = QPushButton(tr("Berechnen und speichern"))
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.start)
        self.cancel_button = QPushButton(tr("Schließen"))
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self._row(self.run_button, self.cancel_button))
        for signal in (self.source.textChanged, self.task.currentIndexChanged,
                       self.confirm.toggled, self.destination.textChanged,
                       self.model_directory.textChanged):
            signal.connect(self.refresh)
        self.reload_models()

    @staticmethod
    def _row(*widgets):
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            line.addWidget(widget, 1 if isinstance(widget, QLineEdit) else 0)
        return row

    def is_running(self):
        # The worker may have returned but its queued finished signal still needs
        # handling. Retain the dialog until that handler clears the reference.
        return self.worker is not None

    def pick_source(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Linearen Stack wählen"), self.source.text(),
                                            "FITS / TIFF (*.fit *.fits *.fts *.tif *.tiff)")
        if path:
            self.source.setText(path)

    def pick_destination(self):
        path = QFileDialog.getExistingDirectory(self, tr("Speicherort wählen"), self.destination.text())
        if path:
            self.destination.setText(path)

    def pick_models(self):
        path = QFileDialog.getExistingDirectory(self, tr("Modellordner wählen"), self.model_directory.text())
        if path:
            self.model_directory.setText(path)
            self.reload_models()

    def reload_models(self):
        if self.is_running():
            return
        self._catalogue_error = ""
        self._loaded_model_dir = self.model_directory.text().strip()
        try:
            import ai_restore
            self.models = ai_restore.list_models(self.model_directory.text().strip() or None)
        except Exception as exc:
            self.models = []
            self._catalogue_error = str(exc)
        self.refresh()

    def selected_model(self):
        candidates = [model for model in self.models if model.get("task") == self.task.currentData()]
        return next((model for model in candidates if model.get("available")),
                    candidates[0] if candidates else None)

    def refresh(self):
        model = self.selected_model()
        self.description.setText(tr(next(description for task, _label, description in TASKS
                                         if task == self.task.currentData())))
        if model and model.get("available"):
            self.model_status.setText(tr("Lokales Modell: {name} · Experimenteller Einsatz").format(
                name=model["id"]))
        else:
            reason = (model or {}).get("reason") or self._catalogue_error
            self.model_status.setText(tr("Für diese Funktion ist kein verwendbares lokales Modell vorhanden.")
                                      + ("\n" + reason if reason else ""))
        source = Path(self.source.text().strip())
        supported = source.suffix.lower() in {".fit", ".fits", ".fts", ".tif", ".tiff"}
        destination = self.destination.text().strip()
        self.run_button.setEnabled(not self.is_running() and bool(model and model.get("available"))
                                   and source.is_file() and supported and self.confirm.isChecked()
                                   and self.model_directory.text().strip() == self._loaded_model_dir
                                   and (not destination or Path(destination).is_dir()))

    def _set_busy(self, busy):
        for widget in (self.source, self.source_pick, self.task, self.strength, self.device, self.destination,
                       self.destination_pick, self.confirm, self.advanced_toggle, self.advanced):
            widget.setEnabled(not busy)
        self.cancel_button.setText(tr("Abbrechen") if busy else tr("Schließen"))
        self.cancel_button.setEnabled(True)
        self.refresh()

    def start(self):
        if self.is_running() or not self.run_button.isEnabled():
            return
        self._close_when_finished = False
        self.result_path = None
        self.execution = None
        self.source_path = self.source.text().strip()
        self.output_path.hide()
        self.result_actions.hide()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.feedback.setText(tr("Modell wird geladen …"))
        self.feedback.setToolTip("")
        request = {"source": self.source_path, "model_id": self.selected_model()["id"],
                   "output_root": self.destination.text().strip() or None,
                   "model_dir": self.model_directory.text().strip() or None,
                   "strength": self.strength.value() / 100,
                   "device": self.device.currentData(),
                   "allow_experimental": True}
        self.worker = _RestoreWorker(request, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.message.connect(self.feedback.setText)
        self.worker.finished.connect(self._worker_finished)
        self._set_busy(True)
        self.worker.start()

    def _on_progress(self, done, total):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.feedback.setText(tr("Bild wird verarbeitet: {done} von {total} Bereichen").format(
                done=done, total=total))

    def _worker_finished(self):
        worker = self.worker
        if worker is None:
            return
        self.worker = None
        self._set_busy(False)
        self.progress.setRange(0, 100)
        if worker.result:
            self.result_path = str(worker.result)
            self.previews = worker.previews
            self.execution = worker.execution
            self.progress.setValue(100)
            message = tr("Fertig. Ergebnis separat gespeichert.")
            if worker.error:
                message = tr("Ergebnis gespeichert. Vorschau nicht verfügbar: {reason}").format(
                    reason=worker.error)
            self.feedback.setText(message + "\n" + _execution_feedback(self.execution))
            reasons = (self.execution or {}).get("fallback_reasons", [])
            if isinstance(reasons, list):
                self.feedback.setToolTip("\n".join(str(reason) for reason in reasons))
            self.output_path.setText(self.result_path)
            self.output_path.setToolTip(self.result_path)
            self.output_path.setCursorPosition(0)
            self.output_path.show()
            self.result_actions.show()
            self.compare_button.setEnabled(self.previews is not None)
        elif worker.cancel_event.is_set():
            self.progress.setValue(0)
            self.feedback.setText(tr("Verarbeitung abgebrochen. Das Original bleibt erhalten."))
        else:
            self.progress.setValue(0)
            self.feedback.setText(tr("Verarbeitung fehlgeschlagen: {reason}").format(
                reason=worker.error or tr("Kein Ergebnis erzeugt.")))
        worker.deleteLater()
        if self._close_when_finished:
            super().reject()

    def cancel_and_close(self):
        if self.is_running():
            self._close_when_finished = True
            self.worker.cancel_event.set()
            self.feedback.setText(tr("Verarbeitung wird sicher beendet …"))
            self.cancel_button.setEnabled(False)
        else:
            super().reject()

    def reject(self):
        self.cancel_and_close()

    def closeEvent(self, event):
        if self.is_running():
            self.cancel_and_close()
            event.ignore()
        else:
            super().closeEvent(event)

    def finish_with_result(self, compare):
        if self.is_running() or not self.result_path:
            return
        self.show_comparison = compare
        self.accept()
