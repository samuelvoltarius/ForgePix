"""Native local-catalogue solve with explicit, editable field hints."""
from pathlib import Path
import math
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from i18n import tr


def header_hints(path):
    """Use actual FITS hints; never infer a historical setup from today's preset."""
    from astropy.io import fits
    from astropy.coordinates import Angle
    from astropy import units as u
    header = fits.getheader(path)
    result = {}
    for key, fallback, unit, target in (("RA", "OBJCTRA", u.hourangle, "ra"),
                                        ("DEC", "OBJCTDEC", u.deg, "dec")):
        value = header.get(key, header.get(fallback))
        if value is not None:
            try:
                result[target] = float(value)
            except (ValueError, TypeError):
                result[target] = float(Angle(str(value), unit=unit).degree)
    # A genuine celestial WCS describes the output grid, including resampling.
    from astropy.wcs import WCS
    from astropy.wcs.utils import proj_plane_pixel_scales
    wcs = WCS(header).celestial
    if wcs.has_celestial:
        scales = proj_plane_pixel_scales(wcs)
        result["pixelscale_arcsec"] = float(math.sqrt(abs(scales[0] * scales[1])) * 3600)
    elif header.get("PIXSCALE"):
        result["pixelscale_arcsec"] = float(header["PIXSCALE"])
    elif (header.get("FOCALLEN") and header.get("XPIXSZ") and
          header.get("XBINNING", 1) == 1 and not header.get("FPDRZSCL")):
        result["pixelscale_arcsec"] = math.degrees(math.atan(float(header["XPIXSZ"]) /
                                                           (1000 * float(header["FOCALLEN"])))) * 3600
    return {key: value for key, value in result.items() if math.isfinite(value)}


class _AstrometryWorker(QThread):
    message = Signal(str)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request
        self.cancel_event = threading.Event()
        self.result = None
        self.error = None

    def run(self):
        try:
            from astrometry_file import solve_file
            self.result = solve_file(**self.request, cancel=self.cancel_event,
                log=lambda *parts, **kw: self.message.emit(" ".join(map(str, parts))))
        except Exception as exc:
            self.error = str(exc)


class AstrometryDialog(QDialog):
    def __init__(self, parent=None, source=None, catalogue=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Himmelsposition bestimmen"))
        self.resize(740, 540)
        self.worker = None
        self.result_path = self.report_path = self.result_report = None
        self._close_when_finished = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel(tr("Eigene Astrometrie · lokaler Sternkatalog"))
        title.setObjectName("sectionHeader")
        layout.addWidget(title)
        intro = QLabel(tr("Ordnet dein Bild einem Himmelsfeld zu. Benötigt einen passenden lokalen "
                          "Katalogauszug, die ungefähre Bildmitte und den Bildmaßstab. "
                          "Die Bildwerte werden unverändert in einem neuen FITS gespeichert."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.editor = QWidget()
        form = QFormLayout(self.editor)
        form.setContentsMargins(0, 0, 0, 0)
        self.source = QLineEdit(str(source or ""))
        source_pick = QPushButton(tr("Wählen …"))
        source_pick.clicked.connect(self.pick_source)
        form.addRow(tr("Linearer FITS-Stack"), self._row(self.source, source_pick))
        self.catalogue = QLineEdit(str(catalogue or ""))
        catalogue_pick = QPushButton(tr("Wählen …"))
        catalogue_pick.clicked.connect(self.pick_catalogue)
        form.addRow(tr("Lokaler Katalog"), self._row(self.catalogue, catalogue_pick))
        self.ra = QLineEdit()
        self.ra.setPlaceholderText(tr("0 bis 360 Grad"))
        form.addRow(tr("Rektaszension (RA)"), self.ra)
        self.dec = QLineEdit()
        self.dec.setPlaceholderText(tr("−90 bis +90 Grad"))
        form.addRow(tr("Deklination (DEC)"), self.dec)
        self.scale = QLineEdit()
        self.scale.setPlaceholderText(tr("Bogensekunden pro Pixel, z. B. 0,83"))
        form.addRow(tr("Bildmaßstab"), self.scale)
        self.hints_button = QPushButton(tr("Angaben aus FITS lesen"))
        self.hints_button.clicked.connect(self.read_hints)
        form.addRow("", self.hints_button)
        self.destination = QLineEdit()
        self.destination.setPlaceholderText(tr("Leer = eigener Ergebnisordner neben dem Bild"))
        destination_pick = QPushButton(tr("Wählen …"))
        destination_pick.clicked.connect(self.pick_destination)
        form.addRow(tr("Speicherort"), self._row(self.destination, destination_pick))
        layout.addWidget(self.editor)
        hint = QLabel(tr("Unterstützt kleine Bildfelder mit Suchhinweisen. Kein vollständiger "
                         "Blind-Solver und keine Farbkalibrierung. Bayer-Rohaufnahmen zuerst entwickeln."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.output = QLineEdit()
        self.output.setReadOnly(True)
        self.output.hide()
        layout.addWidget(self.output)
        layout.addStretch()
        row = QHBoxLayout()
        self.result_button = QPushButton(tr("Ergebnis ansehen"))
        self.result_button.setEnabled(False)
        self.result_button.clicked.connect(self.accept)
        row.addWidget(self.result_button)
        row.addStretch()
        self.close_button = QPushButton(tr("Schließen"))
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        self.run_button = QPushButton(tr("Position bestimmen"))
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.start)
        row.addWidget(self.run_button)
        layout.addLayout(row)
        for line in (self.source, self.catalogue, self.ra, self.dec, self.scale, self.destination):
            line.textChanged.connect(self.refresh)
        if source:
            self.read_hints()
        self.refresh()

    @staticmethod
    def _row(edit, button):
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return host

    def hints(self):
        values = [float(line.text().strip().replace(",", ".")) for line in (self.ra, self.dec, self.scale)]
        if (not all(math.isfinite(value) for value in values) or not 0 <= values[0] <= 360
                or not -90 <= values[1] <= 90 or not .01 <= values[2] <= 120):
            raise ValueError(tr("Bildmitte und Maßstab liegen außerhalb des gültigen Bereichs."))
        return dict(zip(("ra", "dec", "pixelscale_arcsec"), values))

    def read_hints(self):
        try:
            values = header_hints(self.source.text().strip())
            for key, edit in (("ra", self.ra), ("dec", self.dec), ("pixelscale_arcsec", self.scale)):
                edit.setText(f"{values[key]:.8f}" if key in values else "")
            self.feedback.setText(tr("FITS-Angaben übernommen. Fehlende Angaben ergänzen und den Katalogausschnitt prüfen."))
        except Exception as exc:
            self.feedback.setText(tr("Keine verwendbaren FITS-Angaben: ") + str(exc))

    def pick_source(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("FITS-Stack wählen"), self.source.text(), "FITS (*.fits *.fit *.fts)")
        if path:
            self.source.setText(path)
            self.read_hints()

    def pick_catalogue(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Lokalen Katalog wählen"), self.catalogue.text(), tr("Sternkatalog (*.npz)"))
        if path:
            self.catalogue.setText(path)

    def pick_destination(self):
        path = QFileDialog.getExistingDirectory(self, tr("Speicherort wählen"), self.destination.text())
        if path:
            self.destination.setText(path)

    def refresh(self, *_):
        try:
            self.hints()
            valid = True
        except ValueError:
            valid = False
        source = Path(self.source.text().strip())
        destination = self.destination.text().strip()
        self.run_button.setEnabled(not self.is_running() and valid and source.is_file()
            and source.suffix.lower() in {".fits", ".fit", ".fts"}
            and Path(self.catalogue.text().strip()).is_file() and (not destination or Path(destination).is_dir()))

    def is_running(self):
        return self.worker is not None

    def start(self):
        if self.is_running() or not self.run_button.isEnabled():
            return
        self.result_path = self.report_path = self.result_report = None
        self._close_when_finished = False
        self.worker = _AstrometryWorker(dict(source=self.source.text().strip(),
            catalogue_path=self.catalogue.text().strip(), hints=self.hints(),
            output_root=self.destination.text().strip() or None), self)
        self.worker.message.connect(self.feedback.setText)
        self.worker.finished.connect(self.finished_run)
        self.editor.setEnabled(False)
        self.run_button.setEnabled(False)
        self.result_button.setEnabled(False)
        self.output.hide()
        self.progress.show()
        self.close_button.setText(tr("Abbrechen"))
        self.feedback.setText(tr("Sterne und Katalog werden geprüft …"))
        self.worker.start()

    def finished_run(self):
        worker = self.worker
        worker.wait()
        self.worker = None
        self.editor.setEnabled(True)
        self.progress.hide()
        self.close_button.setText(tr("Schließen"))
        self.close_button.setEnabled(True)
        if worker.result:
            self.result_path, self.report_path = worker.result["result_path"], worker.result["report_path"]
            self.result_report = worker.result["report"]
            solution = self.result_report["solution"]
            self.feedback.setText(tr("Position bestätigt: {n} unabhängige Prüfsterne, mittlere Abweichung {rms:.3f} Pixel. "
                                      "Das neue FITS und der Prüfbericht sind gespeichert.").format(
                                          n=solution["validation_matches"], rms=solution["validation_rms_px"]))
            self.output.setText(self.result_path)
            self.output.show()
            self.result_button.setEnabled(True)
        else:
            self.feedback.setText(tr("Abgebrochen. Das Original bleibt erhalten.") if worker.cancel_event.is_set()
                                  else worker.error or tr("Keine bestätigte Lösung gefunden."))
        worker.deleteLater()
        self.refresh()
        if self._close_when_finished:
            super().reject()

    def cancel_and_close(self):
        self._close_when_finished = True
        self.reject()

    def reject(self):
        if self.is_running():
            self.worker.cancel_event.set()
            self.close_button.setEnabled(False)
            self.feedback.setText(tr("Abbruch angefordert. Die Berechnung wird sicher beendet …"))
        else:
            super().reject()

    def closeEvent(self, event):
        if self.is_running():
            self.cancel_and_close()
            event.ignore()
        else:
            super().closeEvent(event)
