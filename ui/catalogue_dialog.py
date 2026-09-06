"""Local Gaia catalogue manager; background I/O and new-file-only downloads."""
import io
from pathlib import Path
import threading
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QDoubleSpinBox, QCheckBox, QDialogButtonBox,
    QFileDialog, QProgressBar, QSizePolicy)

import gaia_lokal
from constants import ForgePixFehler
from i18n import tr


class _CatalogueWorker(QThread):
    message = Signal(str)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request
        self.cancel_event = threading.Event()
        self.catalogue = None
        self.result_path = None
        self.error = None

    def run(self):
        target, created = None, False
        try:
            if self.cancel_event.is_set():
                raise ForgePixFehler(tr("Vorgang abgebrochen."))
            if self.request["mode"] == "load":
                result = gaia_lokal.Katalog.laden(self.request["path"], log=self.message.emit)
                if result is None:
                    raise ForgePixFehler(tr("Die Datei enthält keinen lesbaren Sternkatalog."))
                if self.cancel_event.is_set():
                    raise ForgePixFehler(tr("Vorgang abgebrochen."))
                self.catalogue = result
                self.result_path = str(Path(self.request["path"]).resolve())
                return
            target = Path(self.request["path"])
            if target.exists():
                raise ForgePixFehler(tr("Die Ausgabedatei existiert bereits. Bitte einen neuen Namen wählen."))
            result = gaia_lokal.herunterladen(**self.request["field"], grenze=20000,
                timeout=120, cancel=self.cancel_event, log=self.message.emit)
            if not len(result):
                raise ForgePixFehler(tr("Keine passenden Sterne gefunden. Bitte Feld und Grenzhelligkeit prüfen."))
            result = gaia_lokal.zusammenfuehren(self.request.get("existing"), result)
            # Finish serialization before creating any output file. Exclusive
            # creation protects an existing catalogue even if a race occurs.
            buffer = io.BytesIO()
            result.speichern(buffer)
            if self.cancel_event.is_set():
                raise ForgePixFehler(tr("Vorgang abgebrochen."))
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                created = True
                stream.write(buffer.getbuffer())
            self.catalogue, self.result_path = result, str(target.resolve())
        except Exception as exc:
            self.error = str(exc)
            if created and target is not None:
                try:
                    target.unlink()
                except OSError:
                    pass


class CatalogueDialog(QDialog):
    """selected_path/catalogue are available after accepting a loaded catalogue."""

    def __init__(self, parent=None, catalogue_path=None, ra=None, dec=None, radius_deg=1.):
        super().__init__(parent)
        self.setWindowTitle(tr("Lokaler Sternkatalog"))
        self.resize(730, 630)
        self.worker = None
        self.catalogue = None
        self.selected_path = None
        self._close_when_finished = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        intro = QLabel(tr("Gaia-Sterne für deine Bildfelder speichern und später offline verwenden. "
                          "Ein Auszug enthält Positionen und Farbindizes; keine vollständigen Sternspektren."))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        local = QGroupBox(tr("Vorhandenen Katalog öffnen"))
        local.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        local_layout = QVBoxLayout(local)
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setPlaceholderText(tr("Lokale Katalogdatei (.npz) wählen"))
        self.open_button = QPushButton(tr("Datei wählen…"))
        self.open_button.clicked.connect(self.pick_catalogue)
        row.addWidget(self.path, 1)
        row.addWidget(self.open_button)
        local_layout.addLayout(row)
        self.metadata_text = QLabel(tr("Noch kein Katalog geladen."))
        self.metadata_text.setTextFormat(Qt.PlainText)
        self.metadata_text.setWordWrap(True)
        self.metadata_text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        local_layout.addWidget(self.metadata_text)
        layout.addWidget(local)

        self.download_group = QGroupBox(tr("Neuen Feldauszug von ESA Gaia laden"))
        download_layout = QVBoxLayout(self.download_group)
        form = QFormLayout()
        self.ra = self._spin(0, 360, 0 if ra is None else ra, 6)
        self.dec = self._spin(-90, 90, 0 if dec is None else dec, 6)
        self.radius = self._spin(.01, 5, radius_deg, 2)
        self.magnitude = self._spin(5, 18, 15.5, 1)
        self.ra.setToolTip(tr("RA in Grad von 0 bis 360. RA in Stunden vorher mit 15 multiplizieren."))
        self.radius.setToolTip(tr("1 Grad Radius entspricht 2 Grad Durchmesser."))
        self.magnitude.setToolTip(tr("Größere Werte laden auch schwächere Sterne und damit mehr Daten."))
        for label, widget in ((tr("Rektaszension RA (Grad)"), self.ra),
                              (tr("Deklination Dec (Grad)"), self.dec),
                              (tr("Feldradius (Grad)"), self.radius),
                              (tr("Grenzhelligkeit G (mag)"), self.magnitude)):
            form.addRow(label, widget)
        download_layout.addLayout(form)
        self.merge = QCheckBox(tr("Geladenen Katalog in der neuen Datei ergänzen"))
        self.merge.setEnabled(False)
        download_layout.addWidget(self.merge)
        row = QHBoxLayout()
        self.output = QLineEdit(str(Path(gaia_lokal.standard_pfad()).parent / "Kataloge" /
            ("gaia-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".npz")))
        self.output_button = QPushButton(tr("Speichern unter…"))
        self.output_button.clicked.connect(self.pick_output)
        row.addWidget(self.output, 1)
        row.addWidget(self.output_button)
        download_layout.addLayout(row)
        limits = QLabel(tr("Maximal 20.000 Sterne je Auszug. Zu große Abfragen werden abgewiesen. "
                           "Vorhandene Dateien werden nicht überschrieben. Internet wird nur für den Download benötigt."))
        limits.setWordWrap(True)
        download_layout.addWidget(limits)
        self.download_button = QPushButton(tr("Feldauszug laden und neu speichern"))
        self.download_button.setObjectName("primary")
        self.download_button.clicked.connect(self.start_download)
        download_layout.addWidget(self.download_button)
        layout.addWidget(self.download_group)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.feedback = QLabel(tr("Lokale Auszüge sind kein vollständiger Himmelskatalog."))
        self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.use_button = buttons.button(QDialogButtonBox.Ok)
        self.use_button.setText(tr("Katalog verwenden"))
        self.use_button.setEnabled(False)
        self.cancel_button = buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.setText(tr("Schließen"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if catalogue_path:
            self.load_path(catalogue_path)

    @staticmethod
    def _spin(low, high, value, decimals):
        field = QDoubleSpinBox()
        field.setDecimals(decimals)
        field.setRange(low, high)
        field.setValue(value)
        return field

    def pick_catalogue(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Sternkatalog öffnen"), self.path.text(), "Gaia (*.npz)")
        if path:
            self.load_path(path)

    def pick_output(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Neuen Katalog speichern"), self.output.text(),
            "Gaia (*.npz)", options=QFileDialog.DontConfirmOverwrite)
        if path:
            self.output.setText(path if path.lower().endswith(".npz") else path + ".npz")

    def is_running(self):
        return self.worker is not None

    def load_path(self, path):
        if not self.is_running():
            self.catalogue, self.selected_path = None, None
            self.merge.setChecked(False)
            self.merge.setEnabled(False)
            self.path.setText(str(path))
            self.metadata_text.setText(tr("Katalog wird geprüft …"))
            self._start({"mode": "load", "path": str(path)})

    def start_download(self):
        if self.is_running():
            return
        path = Path(self.output.text().strip())
        if not self.output.text().strip() or path.suffix.lower() != ".npz" or path.exists():
            self.feedback.setText(tr("Bitte einen neuen Dateinamen mit der Endung .npz wählen."))
            return
        self._start({"mode": "download", "path": str(path),
                     "existing": self.catalogue if self.merge.isChecked() else None,
                     "field": {"ra": self.ra.value(), "dec": self.dec.value(),
                               "radius_grad": self.radius.value(), "max_mag": self.magnitude.value()}})

    def _start(self, request):
        self.worker = _CatalogueWorker(request, self)
        self.worker.message.connect(self.feedback.setText)
        self.worker.finished.connect(self._finished)
        self.open_button.setEnabled(False)
        self.download_group.setEnabled(False)
        self.use_button.setEnabled(False)
        self.cancel_button.setText(tr("Abbrechen"))
        self.progress.setRange(0, 0)
        self.progress.show()
        self.feedback.setText(tr("Katalog wird geladen …"))
        self.worker.start()

    def _finished(self):
        worker, self.worker = self.worker, None
        self.open_button.setEnabled(True)
        self.download_group.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText(tr("Schließen"))
        self.progress.hide()
        if worker.catalogue is not None:
            self.catalogue, self.selected_path = worker.catalogue, worker.result_path
            self.path.setText(self.selected_path)
            meta = self.catalogue.metadata
            epoch = meta.get("reference_epoch_jyear")
            epoch_text = tr("unbekannt") if epoch is None else "J%s" % epoch
            fields = len(meta.get("fields", []))
            motion = tr("Eigenbewegung nicht fortgeschrieben.") if meta.get("proper_motion_applied") is False else tr("Eigenbewegungsstatus unbekannt.")
            self.metadata_text.setText(tr("{count} Sterne · Koordinatenepoche {epoch}\n"
                "{fields} dokumentierte Suchfelder. Räumliche Vollständigkeit nicht geprüft.\n{motion}").format(
                count=len(self.catalogue), epoch=epoch_text, fields=fields, motion=motion))
            self.feedback.setText(tr("Katalog geladen. Die ursprüngliche Datei bleibt erhalten."))
            self.merge.setEnabled(True)
        elif worker.cancel_event.is_set():
            self.feedback.setText(tr("Vorgang abgebrochen."))
        else:
            self.feedback.setText(worker.error or tr("Katalog konnte nicht geladen werden."))
            if self.catalogue is None:
                self.metadata_text.setText(tr("Kein verwendbarer Katalog geladen."))
        self.use_button.setEnabled(self.catalogue is not None and len(self.catalogue) > 0)
        worker.deleteLater()
        if self._close_when_finished:
            super().reject()

    def accept(self):
        if not self.is_running() and self.selected_path and self.catalogue is not None and len(self.catalogue):
            super().accept()

    def reject(self):
        if self.is_running():
            self._close_when_finished = True
            self.worker.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.feedback.setText(tr("Abbruch angefordert. Die laufende Netzanfrage wird beendet …"))
        else:
            super().reject()

    def cancel_and_close(self):
        self.reject()

    def closeEvent(self, event):
        if self.is_running():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
