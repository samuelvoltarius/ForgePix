"""Equipment presets and editable optical geometry, independent of camera brand."""
import math
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel,
                               QComboBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox,
                               QSizePolicy)
from i18n import tr
import equipment
import filters
from ui.settings_io import app_settings


class EquipmentDialog(QDialog):
    def __init__(self, parent=None, initial_filter=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Ausrüstung"))
        self.resize(640, 600)
        self._applying_preset = False
        settings = app_settings()
        layout = QVBoxLayout(self)
        intro = QLabel(tr("Wähle Vorgaben oder trage eigene Werte ein. Die Angaben beschreiben "
                          "deine Optik; sie ersetzen keine Dark- oder Flat-Kalibrierung."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
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
        selected_filter = initial_filter or settings.value("equipment/filter", "keiner")
        self.filter.setCurrentIndex(max(0, self.filter.findData(selected_filter)))
        form.addRow(tr("Aufnahmefilter"), self.filter)
        self.filter_info = QLabel()
        self.filter_info.setWordWrap(True)
        form.addRow(self.filter_info)
        for key, combo in (("camera", self.camera), ("telescope", self.telescope),
                           ("corrector", self.corrector)):
            saved = settings.value("equipment/" + key, "manuell")
            for index in range(combo.count()):
                if combo.itemData(index)[0] == saved:
                    combo.setCurrentIndex(index)
                    break
        self.values = {}
        for key, label, low, high, default, suffix in [
            ("pitch", tr("Pixelgröße (ungebinnt)"), .1, 100, 3.76, " µm"),
            ("aperture", tr("Öffnung (Durchmesser)"), 1, 5000, 80, " mm"),
            ("focal", tr("Brennweite ohne Korrektor"), 1, 50000, 480, " mm"),
            ("factor", tr("Reducer / Barlow"), .1, 10, 1, " ×")]:
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setRange(low, high)
            spin.setSuffix(suffix)
            spin.setValue(self._saved_number(settings, key, default))
            self.values[key] = spin
            form.addRow(label, spin)
        self.binning = QSpinBox()
        self.binning.setRange(1, 16)
        self.binning.setValue(int(self._saved_number(settings, "binning", 1)))
        form.addRow(tr("Aufnahme-Binning"), self.binning)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        for combo in (self.camera, self.telescope, self.corrector, self.filter):
            combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            combo.setMinimumContentsLength(24)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setToolTip(combo.currentText())
            combo.currentTextChanged.connect(combo.setToolTip)
        self.camera.currentIndexChanged.connect(self.camera_changed)
        self.telescope.currentIndexChanged.connect(self.telescope_changed)
        self.corrector.currentIndexChanged.connect(self.corrector_changed)
        self.filter.currentIndexChanged.connect(self.refresh)
        for spin in self.values.values():
            spin.valueChanged.connect(self.values_changed)
        self.binning.valueChanged.connect(self.refresh)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr("Speichern"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Abbrechen"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.values_changed()

    @staticmethod
    def _saved_number(settings, key, default):
        try:
            value = float(settings.value("equipment/" + key, default))
            return value if math.isfinite(value) else default
        except (TypeError, ValueError):
            return default

    def _apply_preset(self, values):
        self._applying_preset = True
        try:
            for key, value in values.items():
                self.values[key].setValue(value)
        finally:
            self._applying_preset = False
        self.values_changed()

    def camera_changed(self):
        _, pitch = self.camera.currentData()
        if pitch is not None:
            self._apply_preset({"pitch": pitch})

    def telescope_changed(self):
        _, aperture, focal = self.telescope.currentData()
        if aperture is not None:
            self._apply_preset({"aperture": aperture, "focal": focal})

    def corrector_changed(self):
        _, factor = self.corrector.currentData()
        if factor is not None:
            self._apply_preset({"factor": factor})

    def values_changed(self):
        if self._applying_preset:
            return
        for combo, keys in ((self.camera, ("pitch",)),
                            (self.telescope, ("aperture", "focal")),
                            (self.corrector, ("factor",))):
            data = combo.currentData()
            if data and data[0] != "manuell":
                matches = all(value is not None and math.isclose(
                    self.values[key].value(), round(value, self.values[key].decimals()),
                    rel_tol=0, abs_tol=1e-9)
                    for key, value in zip(keys, data[1:]))
                if not matches:
                    # A changed focal length must not remain labelled as an
                    # unmodified manufacturer preset or change another field.
                    manual_index = next(i for i in range(combo.count())
                                        if combo.itemData(i)[0] == "manuell")
                    with QSignalBlocker(combo):
                        combo.setCurrentIndex(manual_index)
                    combo.setToolTip(combo.currentText())
        self.refresh()

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
        settings.setValue("astro_filter_key", self.filter.currentData())
        settings.remove("astro_filter")
        settings.sync()
        self.accept()
