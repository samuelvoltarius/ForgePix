"""Small native channel workflow: measured inputs, explicit mapping, one output folder."""
from pathlib import Path

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QCheckBox, QDoubleSpinBox, QDialogButtonBox,
    QFileDialog, QWidget)

import channels
import filters
from i18n import tr


class ChannelsDialog(QDialog):
    def __init__(self, parent=None, source=None, filter_key=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Kanäle trennen und kombinieren"))
        self.resize(690, 450)
        self.filter_key = filter_key
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        self.mode = QComboBox()
        self.mode.addItem(tr("RGB in einzelne Kanäle trennen"), "split_rgb")
        profile = filters.hole(filter_key)
        self.has_dual = bool(profile and profile.art == "dualband" and
                             set(profile.linien) in ({"Ha", "OIII"}, {"SII", "OIII"}))
        if self.has_dual:
            self.mode.addItem(tr("Dualband: aufgenommene Linien abschätzen"), "split_dual")
        for name in channels.PRESETS:
            self.mode.addItem(tr("{name} aus vorhandenen Kanälen kombinieren").format(name=name), name)
        form = QFormLayout()
        form.addRow(tr("Verarbeitung"), self.mode)
        layout.addLayout(form)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.fields, self.gains, self.rows = {}, {}, {}
        for name in ("source", "R", "G", "B", "SII", "Ha", "OIII"):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            label = QLabel(tr("Farbbild") if name == "source" else name)
            label.setFixedWidth(70)
            line.addWidget(label)
            field = QLineEdit(source or "" if name == "source" else "")
            field.setPlaceholderText(tr("Lineares FITS oder TIFF wählen"))
            line.addWidget(field, 1)
            pick = QPushButton(tr("Wählen…"))
            pick.clicked.connect(lambda checked=False, edit=field: self.pick(edit))
            line.addWidget(pick)
            if name != "source":
                spin = QDoubleSpinBox()
                spin.setRange(0, 10)
                spin.setDecimals(3)
                spin.setValue(1)
                spin.setSuffix(" ×")
                spin.setToolTip(tr("Kanalstärke; 1 erhält die linearen Werte."))
                line.addWidget(spin)
                self.gains[name] = spin
            self.fields[name], self.rows[name] = field, row
            layout.addWidget(row)
            field.textChanged.connect(self.refresh)
        self.align = QCheckBox(tr("Sterne automatisch ausrichten"))
        self.align.setChecked(True)
        self.align.setToolTip(tr("Nur ausschalten, wenn die Kanäle bereits exakt aufeinander ausgerichtet sind."))
        layout.addWidget(self.align)
        self.destination = QLabel(tr("FITS, Float32-TIFF und Verarbeitungsbericht werden in einem neuen "
                                    "Unterordner neben der ersten Aufnahme gespeichert."))
        self.destination.setWordWrap(True)
        layout.addWidget(self.destination)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.run_button = buttons.button(QDialogButtonBox.Ok)
        self.run_button.setText(tr("Berechnen und speichern"))
        self.run_button.setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Abbrechen"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self.refresh)
        if self.has_dual:
            self.mode.setCurrentIndex(1)
        self.refresh()

    def pick(self, field):
        path, _ = QFileDialog.getOpenFileName(self, tr("Lineares FITS oder TIFF wählen"),
            field.text(), "FITS / TIFF (*.fit *.fits *.fts *.tif *.tiff)")
        if path:
            field.setText(path)

    def refresh(self):
        if not hasattr(self, "run_button"):
            return
        mode = self.mode.currentData()
        splitting = mode.startswith("split_")
        active = {"source"} if splitting else set(channels.PRESETS[mode])
        for name, row in self.rows.items():
            row.setVisible(name in active)
        self.align.setVisible(not splitting)
        if mode == "split_dual":
            profile = filters.hole(self.filter_key)
            self.description.setText(tr("{filter}: Rot schätzt {line}, Grün und Blau schätzen OIII. "
                "Die Sensorantworten überlappen; dies ist keine vollständige spektrale Trennung. "
                "Fehlende Linien werden nicht erzeugt.").format(filter=profile.name,
                line="SII" if "SII" in profile.linien else "Ha"))
        elif splitting:
            self.description.setText(tr("Rot, Grün und Blau werden ohne Streckung oder Normalisierung "
                                        "als einzelne lineare Bilder gespeichert."))
        else:
            r, g, b = channels.PRESETS[mode]
            self.description.setText(tr("Rot = {r} · Grün = {g} · Blau = {b}. "
                "Wähle einkanalige Aufnahmen desselben Sternfelds in gleicher Größe. "
                "Die Vorschau wird gestreckt, die gespeicherten Bilddaten bleiben linear.").format(r=r, g=g, b=b))
        self.run_button.setEnabled(all(Path(self.fields[key].text().strip()).is_file() for key in active))

    def request(self):
        mode = self.mode.currentData()
        if mode.startswith("split_"):
            return {"path": self.fields["source"].text().strip(),
                    "filter_key": self.filter_key if mode == "split_dual" else None}
        names = set(channels.PRESETS[mode])
        return {"paths": {key: self.fields[key].text().strip() for key in names},
                "preset": mode, "gains": {key: self.gains[key].value() for key in names},
                "align": self.align.isChecked()}
