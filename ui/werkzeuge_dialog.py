"""Astro-Werkzeuge im Menü: was gebaut war, aber nur auf der Kommandozeile (oder gar nicht)
erreichbar. Jede Funktion bekommt das Hauptfenster und benutzt dessen Hintergrund-Lauf;
die Rechnung steckt in core/werkzeuge.py bzw. in der Pipeline (Lucky, Lichtkurve)."""
import os

from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout,
    QDoubleSpinBox, QDialogButtonBox, QFileDialog, QInputDialog, QMessageBox, QLabel)

from i18n import tr

_BILDER = "FITS / TIFF (*.fit *.fits *.fts *.tif *.tiff)"
_FITS = "FITS (*.fit *.fits *.fts)"
_VIDEO = "Video (*.mp4 *.avi *.mov *.mkv *.m4v *.ser)"


def _zeilen(log):
    """Werkzeug-Meldungen kommen ohne Zeilenende; das Protokoll braucht eins."""
    return lambda text: log(str(text).rstrip("\n") + "\n")


def _quelle(fenster, titel, filter_=_BILDER):
    vorschlag = fenster._best_export_file(bits=32) or ""
    pfad, _ = QFileDialog.getOpenFileName(fenster, titel, vorschlag, filter_)
    return pfad or None


def _ziel(fenster, titel, vorschlag, filter_):
    pfad, _ = QFileDialog.getSaveFileName(fenster, titel, vorschlag, filter_)
    return pfad or None


def blink(fenster):
    import werkzeuge
    from ui.components import open_path
    dateien, _ = QFileDialog.getOpenFileNames(fenster, tr("Daumenkino: Aufnahmen wählen"), "", _BILDER)
    if not dateien:
        return
    ziel = _ziel(fenster, tr("Daumenkino speichern"),
                 os.path.join(os.path.dirname(dateien[0]), "blink.gif"), "GIF (*.gif)")
    if not ziel:
        return
    fenster._run_tool_async(tr("Daumenkino (Blink)"),
                            lambda log: werkzeuge.blink(dateien, ziel, log=_zeilen(log)),
                            lambda out: (fenster._append(tr("Daumenkino gespeichert: {path}").format(path=out) + "\n"),
                                         open_path(out)))


def superbias(fenster):
    import werkzeuge
    dateien, _ = QFileDialog.getOpenFileNames(fenster, tr("Superbias: mindestens 3 Bias-Aufnahmen wählen"),
                                              "", _FITS)
    if not dateien:
        return
    if len(dateien) < 3:
        QMessageBox.information(fenster, "Superbias", tr("Bitte mindestens 3 Bias-Aufnahmen wählen."))
        return
    ziel = _ziel(fenster, tr("Superbias speichern"),
                 os.path.join(os.path.dirname(dateien[0]), "superbias.fits"), _FITS)
    if not ziel:
        return
    fenster._run_tool_async("Superbias",
                            lambda log: werkzeuge.superbias(dateien, ziel, log=_zeilen(log)),
                            lambda out: fenster._append(
                                tr("Superbias gespeichert: {path} — als Bias-Master verwenden.").format(path=out) + "\n"))


def larson(fenster):
    import werkzeuge
    quelle = _quelle(fenster, tr("Kometenbild wählen"))
    if not quelle:
        return
    winkel, ok = QInputDialog.getDouble(fenster, "Larson-Sekanina",
                                        tr("Drehwinkel in Grad (typisch 5 bis 30):"), 15.0, 1.0, 90.0, 1)
    if not ok:
        return
    ziel = os.path.splitext(quelle)[0] + "_larson.tif"
    fenster._run_tool_async("Larson-Sekanina",
                            lambda log: werkzeuge.larson(quelle, ziel, winkel=winkel, log=_zeilen(log)),
                            lambda out: fenster._adopt_result(out, quelle))


def streifen(fenster):
    import werkzeuge
    quelle = _quelle(fenster, tr("Bild mit Streifenmuster wählen"))
    if not quelle:
        return
    staerke, ok = QInputDialog.getDouble(fenster, tr("Streifenmuster entfernen"),
                                         tr("Stärke (0 = aus, 1 = voll):"), 1.0, 0.0, 1.0, 2)
    if not ok:
        return
    ziel = os.path.splitext(quelle)[0] + "_ohne_streifen.tif"
    fenster._run_tool_async(tr("Streifenmuster entfernen"),
                            lambda log: werkzeuge.streifen(quelle, ziel, staerke=staerke, log=_zeilen(log)),
                            lambda out: fenster._adopt_result(out, quelle))


def beschriften(fenster):
    import werkzeuge
    quelle = _quelle(fenster, tr("Bild mit Himmelsposition wählen"), _FITS)
    if not quelle:
        return
    csv, _ = QFileDialog.getOpenFileName(
        fenster, tr("Objektliste (CSV: name,ra,dec in Grad) — Abbrechen für keine"), "", "CSV (*.csv)")
    ziel = os.path.splitext(quelle)[0] + "_beschriftet.png"
    fenster._run_tool_async(tr("Objekte und Gitter einzeichnen"),
                            lambda log: werkzeuge.beschriften(quelle, ziel, objekte_csv=csv or None,
                                                              log=_zeilen(log)),
                            lambda out: fenster._adopt_result(out, quelle))


def lucky(fenster):
    from ui.appinfo import SCRIPT
    video, _ = QFileDialog.getOpenFileName(fenster, tr("Video von Sonne, Mond oder Planet wählen"), "", _VIDEO)
    if not video:
        return
    fenster._live_stop_file = None
    fenster._pipeline_starten([SCRIPT, "--input", os.path.abspath(video), "--lucky",
                               "--work", os.path.join(os.path.dirname(os.path.abspath(video)), "lucky_work")])


class LichtkurveDialog(QDialog):
    """Die Angaben für `--photometrie`: Serie, Zielstern, Vergleichssterne, Blende."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Lichtkurve messen"))
        form = QFormLayout(self)
        erklaerung = QLabel(tr("Positionen in Pixeln der ERSTEN Aufnahme. Besser drei "
                               "Vergleichssterne als einer: ein veränderlicher Vergleichsstern "
                               "verdirbt sonst die ganze Messreihe."))
        erklaerung.setWordWrap(True)
        form.addRow(erklaerung)
        self.ordner = QLineEdit()
        knopf = QPushButton(tr("Wählen…"))
        knopf.clicked.connect(self._waehlen)
        zeile = QHBoxLayout(); zeile.addWidget(self.ordner, 1); zeile.addWidget(knopf)
        form.addRow(tr("Aufnahmeserie"), zeile)
        self.stern = QLineEdit(); self.stern.setPlaceholderText("812,604")
        form.addRow(tr("Zielstern X,Y"), self.stern)
        self.vergleich = QLineEdit(); self.vergleich.setPlaceholderText("700,580;905,640;760,710")
        form.addRow(tr("Vergleichssterne X,Y;X,Y"), self.vergleich)
        self.blende = QDoubleSpinBox(); self.blende.setRange(1.0, 50.0); self.blende.setValue(5.0)
        form.addRow(tr("Blende (Pixel)"), self.blende)
        self.aavso = QLineEdit(); self.aavso.setPlaceholderText(tr("leer = keine AAVSO-Datei"))
        form.addRow(tr("AAVSO-Sternname"), self.aavso)
        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        knoepfe.accepted.connect(self.accept); knoepfe.rejected.connect(self.reject)
        form.addRow(knoepfe)

    def _waehlen(self):
        pfad = QFileDialog.getExistingDirectory(self, tr("Aufnahmeserie"), self.ordner.text())
        if pfad:
            self.ordner.setText(pfad)

    def argumente(self):
        from ui.appinfo import SCRIPT
        ordner = self.ordner.text().strip()
        if not os.path.isdir(ordner):
            raise ValueError(tr("Bitte einen Ordner mit der Aufnahmeserie wählen."))
        if not self.stern.text().strip() or not self.vergleich.text().strip():
            raise ValueError(tr("Zielstern und mindestens ein Vergleichsstern sind nötig."))
        args = [SCRIPT, "--input", ordner, "--photometrie", "--stern", self.stern.text().strip(),
                "--vergleich", self.vergleich.text().strip(), "--blende", "%g" % self.blende.value()]
        if self.aavso.text().strip():
            args += ["--aavso", self.aavso.text().strip()]
        return args


def lichtkurve(fenster):
    dialog = LichtkurveDialog(fenster)
    while dialog.exec() == QDialog.Accepted:
        try:
            args = dialog.argumente()
        except ValueError as e:
            QMessageBox.warning(fenster, tr("Lichtkurve messen"), str(e))
            continue
        fenster._live_stop_file = None
        fenster._pipeline_starten(args)
        return
