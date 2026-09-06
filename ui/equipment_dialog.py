"""Equipment presets and editable optical geometry, independent of camera brand."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel,
                               QComboBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox)
from i18n import tr
import equipment
import filters
from ui.settings_io import app_settings


class EquipmentDialog(QDialog):
    def __init__(self, parent=None, initial_filter=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Ausrüstung"))
        self.resize(580, 420)
        layout = QVBoxLayout(self)
        intro = QLabel(tr("Wähle Vorgaben oder trage eigene Werte ein. Die Angaben beschreiben "
                          "deine Optik; sie ersetzen keine Dark- oder Flat-Kalibrierung."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        layout.addLayout(form)
        self.camera = QComboBox()
        for key, name, pitch in equipment.alle_kameras():
            self.camera.addItem(name, (key, pitch))
        self.telescope = QComboBox()
        for key, name, aperture, focal in equipment.alle_teleskope():
            self.telescope.addItem(name, (key, aperture, focal))
        form.addRow(tr("Kamera / Sensor"), self.camera)
        form.addRow(tr("Teleskop"), self.telescope)
        self.corrector = QComboBox()
        self.corrector.addItem(tr("Eigener Faktor"), ("manuell", None))
        for item in equipment.alle_korrektoren():
            self.corrector.addItem(item.name, (item.schluessel, item.faktor))
        form.addRow(tr("Korrektor"), self.corrector)
        self.filter = QComboBox()
        for item in filters.FILTER:
            self.filter.addItem(item.name, item.schluessel)
        selected_filter = initial_filter or app_settings().value("equipment/filter", "keiner")
        self.filter.setCurrentIndex(max(0, self.filter.findData(selected_filter)))
        form.addRow(tr("Aufnahmefilter"), self.filter)
        self.filter_info = QLabel()
        self.filter_info.setWordWrap(True)
        form.addRow(self.filter_info)
        for key, combo in (("camera", self.camera), ("telescope", self.telescope),
                           ("corrector", self.corrector)):
            saved = app_settings().value("equipment/" + key, "manuell")
            for index in range(combo.count()):
                if combo.itemData(index)[0] == saved:
                    combo.setCurrentIndex(index)
                    break
        self.values = {}
        for key, label, low, high, default, suffix in [
            ("pitch", tr("Pixelgröße"), .1, 100, 3.76, " µm"),
            ("aperture", tr("Öffnung"), 1, 5000, 80, " mm"),
            ("focal", tr("Brennweite"), 1, 50000, 480, " mm"),
            ("factor", tr("Reducer / Barlow"), .1, 10, 1, " ×")]:
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setRange(low, high)
            spin.setSuffix(suffix)
            spin.setValue(float(app_settings().value("equipment/" + key, default)))
            self.values[key] = spin
            form.addRow(label, spin)
        self.binning = QSpinBox()
        self.binning.setRange(1, 16)
        self.binning.setValue(int(app_settings().value("equipment/binning", 1)))
        form.addRow(tr("Aufnahme-Binning"), self.binning)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.camera.currentIndexChanged.connect(self.camera_changed)
        self.telescope.currentIndexChanged.connect(self.telescope_changed)
        self.corrector.currentIndexChanged.connect(self.corrector_changed)
        self.filter.currentIndexChanged.connect(self.refresh)
        for spin in self.values.values():
            spin.valueChanged.connect(self.refresh)
        self.binning.valueChanged.connect(self.refresh)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr("Speichern"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Abbrechen"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def camera_changed(self):
        _, pitch = self.camera.currentData()
        if pitch is not None:
            self.values["pitch"].setValue(pitch)

    def telescope_changed(self):
        _, aperture, focal = self.telescope.currentData()
        if aperture is not None:
            self.values["aperture"].setValue(aperture)
            self.values["focal"].setValue(focal)

    def corrector_changed(self):
        _, factor = self.corrector.currentData()
        if factor is not None:
            self.values["factor"].setValue(factor)

    def refresh(self):
        self.filter_info.setText(filters.beschreibung(filters.hole(self.filter.currentData())))
        focal = self.values["focal"].value() * self.values["factor"].value()
        scale = equipment.abbildungsskala(focal, self.values["pitch"].value(), self.binning.value())
        ratio = focal / self.values["aperture"].value()
        self.summary.setText(tr("Effektive Brennweite: {focal:.1f} mm · f/{ratio:.2f}\n"
                                "Bildmaßstab: {scale:.3f} Bogensekunden pro Pixel").format(
                                    focal=focal, ratio=ratio, scale=scale))

    def save(self):
        settings = app_settings()
        for key, spin in self.values.items():
            settings.setValue("equipment/" + key, spin.value())
        settings.setValue("equipment/binning", self.binning.value())
        for key, combo in (("camera", self.camera), ("telescope", self.telescope),
                           ("corrector", self.corrector)):
            settings.setValue("equipment/" + key, combo.currentData()[0])
        settings.setValue("equipment/filter", self.filter.currentData())
        settings.sync()
        self.accept()
