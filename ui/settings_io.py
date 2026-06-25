#!/usr/bin/env python3
"""ui/settings_io.py — Laden/Speichern der Einstellungen (QSettings) als Mixin für MainWindow."""
from PySide6.QtCore import QSettings


class SettingsMixin:
    """Mappt Widgets <-> QSettings und stellt sie beim Start wieder her (inkl. Alt-Namen-Migration)."""

    def _settings_map(self):
        return {
            "in": (self.in_edit.setText, self.in_edit.text),
            "work": (self.work_edit.setText, self.work_edit.text),
            "vlm_ep": (self.vlm_ep.setText, self.vlm_ep.text),
            "vlm_model": (self.vlm_model.setText, self.vlm_model.text),
            "vlm_key": (self.vlm_key.setText, self.vlm_key.text),
            "vlm_provider": (self.vlm_provider.setCurrentText, self.vlm_provider.currentText),
            "mode_i": (lambda v: self.mode_box.setCurrentIndex(int(v)), self.mode_box.currentIndex),
            "task_i": (lambda v: self.task_box.setCurrentIndex(int(v)), self.task_box.currentIndex),
            "raw_dev": (self.raw_dev.setChecked, self.raw_dev.isChecked),
            "raw_wb": (self.raw_wb.setCurrentText, self.raw_wb.currentText),
            "raw_bps": (self.raw_bps.setCurrentText, self.raw_bps.currentText),
            "raw_half": (self.raw_half.setChecked, self.raw_half.isChecked),
            "vlm_on": (self.vlm_group.setChecked, self.vlm_group.isChecked),
            "astro_fits": (self.astro_fits.setChecked, self.astro_fits.isChecked),
            "astro_align": (lambda v: self.astro_align.setCurrentIndex(int(v)), self.astro_align.currentIndex),
            "astro_cosmetic": (self.astro_cosmetic.setChecked, self.astro_cosmetic.isChecked),
            "astro_qc": (self.astro_qc.setChecked, self.astro_qc.isChecked),
            "reject_blurry": (self.reject_blurry.setChecked, self.reject_blurry.isChecked),
            "blurry_rel": (lambda v: self.blurry_rel.setValue(float(v)), self.blurry_rel.value),
            "astro_drizzle": (lambda v: self.astro_drizzle.setCurrentIndex(int(v)), self.astro_drizzle.currentIndex),
            "astro_auto": (self.astro_auto.setChecked, self.astro_auto.isChecked),
            "astro_dualband": (self.astro_dualband.setChecked, self.astro_dualband.isChecked),
            "astro_bright": (lambda v: self.astro_bright.setValue(float(v)), self.astro_bright.value),
            "astro_sat": (lambda v: self.astro_sat.setValue(float(v)), self.astro_sat.value),
            "astro_color": (lambda v: self.astro_color.setValue(float(v)), self.astro_color.value),
            "hybrid_kind": (lambda v: self.hybrid_kind.setCurrentIndex(int(v)), self.hybrid_kind.currentIndex),
            "hybrid_group": (lambda v: self.hybrid_group.setValue(int(v)), self.hybrid_group.value),
            "longexp_mode": (lambda v: self.longexp_mode.setCurrentIndex(int(v)), self.longexp_mode.currentIndex),
            "longexp_align": (lambda v: self.longexp_align.setCurrentIndex(int(v)), self.longexp_align.currentIndex),
            "longexp_strength": (lambda v: self.longexp_strength.setValue(int(v)), self.longexp_strength.value),
            "graxpert_path": (self.graxpert_path.setText, self.graxpert_path.text),
            "starnet_path": (self.starnet_path.setText, self.starnet_path.text),
            "siril_path": (self.siril_path.setText, self.siril_path.text),
        }

    def _save_settings(self):
        st = QSettings("ServeOne", "ForgePix")
        for k, (_set, get) in self._settings_map().items():
            st.setValue(k, get())

    def _restore_settings(self):
        st = QSettings("ServeOne", "ForgePix")
        # Einmalige Migration: Einstellungen vom alten Namen „StackForge" übernehmen
        if not st.allKeys():
            old = QSettings("ServeOne", "StackForge")
            if old.allKeys():
                for k in old.allKeys():
                    st.setValue(k, old.value(k))
        bool_keys = {"raw_dev", "raw_half", "vlm_on", "astro_fits", "astro_cosmetic", "astro_qc",
                     "astro_auto", "astro_dualband",
                     "reject_blurry"}
        for k, (setter, _g) in self._settings_map().items():
            v = st.value(k)
            if v is None or v == "":
                continue
            if k in bool_keys:
                v = (v is True or str(v).lower() == "true")
            try:
                setter(v)
            except Exception:
                pass
        geo = st.value("geometry")
        if geo is not None:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass
