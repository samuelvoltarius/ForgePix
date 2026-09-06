#!/usr/bin/env python3
"""ui/export.py — Export (Schnell-Chips + Dialog) als Mixin für MainWindow."""
import os
import json
import hashlib
from pathlib import Path
import shutil
import tempfile

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
                               QLabel, QCheckBox, QSpinBox, QPushButton, QMessageBox, QFileDialog)

from i18n import tr
from ui.components import reveal_in_files
from constants import imread, imwrite

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None


def _verified_ai_files(source, *, selected_only=False):
    """Verify the whole export group, or just the selected file on reimport."""
    changed = tr("Ergebnisdateien wurden verändert. Bitte das bearbeitete Bild als neues Ergebnis "
                 "einlesen; die bisherigen Begleitdateien können nicht gemeinsam exportiert werden.")
    try:
        provenance = (source.parent / "ai_report.json").read_bytes()
        details = json.loads(provenance)
    except (OSError, ValueError):
        raise ValueError(tr("Für dieses KI-Ergebnis fehlt ein gültiger Verarbeitungsbericht. "
                            "Bitte ein neues KI-Ergebnis erzeugen.")) from None
    records = details.get("output_integrity") if isinstance(details, dict) else None
    if not isinstance(records, list) or not records:
        raise ValueError(tr("Für dieses ältere KI-Ergebnis fehlen Datei-Prüfsummen. "
                            "Bitte ein neues KI-Ergebnis erzeugen, bevor lineare Dateien gemeinsam exportiert werden."))
    verified = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(changed)
        name, size, expected = record.get("name"), record.get("bytes"), record.get("sha256")
        if (not isinstance(name, str) or not name or Path(name).name != name or "/" in name or "\\" in name
                or name in verified or type(size) is not int or size < 0
                or not isinstance(expected, str) or len(expected) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in expected)):
            raise ValueError(changed)
        path = (source.parent / name).resolve()
        if path.parent != source.parent:
            raise ValueError(changed)
        if selected_only and path != source:
            verified[name] = (path, expected.lower(), size)
            continue
        try:
            if path.stat().st_size != size:
                raise ValueError(changed)
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected.lower():
                raise ValueError(changed)
        except OSError:
            raise ValueError(changed) from None
        verified[name] = (path, expected.lower(), size)
    outputs = details.get("outputs")
    if (not isinstance(outputs, list) or any(not isinstance(name, str) for name in outputs)
            or len(set(outputs)) != len(outputs) or set(outputs) != set(verified)
            or not {source.name, source.with_suffix(".fits").name}.issubset(verified)):
        raise ValueError(changed)
    return verified, provenance


class ExportMixin:
    """Ein-Klick-Export-Chips und ausführlicher Export-Dialog (Ziele/Schärfung/Ebenen/16-bit)."""

    def _verify_project_ai_export(self, source, provenance):
        """A saved AI group must still match its independent project proofs."""
        project = getattr(self, "_project", None)
        selected = project.data.get("selected_step") if project else None
        if not selected:
            return
        from project_store import resolve, verify
        step = project.step(selected)
        saved = resolve(step["result"]["path"], project.path.parent)
        if os.path.normcase(str(source)) != os.path.normcase(str(saved)):
            return  # A newly generated, unarchived result uses its own report.
        changed = tr("Ergebnisdateien wurden verändert. Bitte das bearbeitete Bild als neues Ergebnis "
                     "einlesen; die bisherigen Begleitdateien können nicht gemeinsam exportiert werden.")
        for record in (step["result"], *step["artifacts"]):
            if verify(record, project.path.parent)["status"] != "ok":
                raise ValueError(changed)
            path = resolve(record["path"], project.path.parent)
            if (provenance is not None and path == source.parent / "ai_report.json"
                    and hashlib.sha256(provenance).hexdigest() != record["sha256"]):
                raise ValueError(changed)

    def _write_ai_export(self, parent, linear=True, png=False, jpeg=False, preview_limit=None):
        """Copy scientific files byte-for-byte; encode only explicit display exports."""
        source = Path(self.result_path).resolve()
        display = self._ai_display_for_current()
        if (png or jpeg) and not display:
            raise ValueError(tr("Die Vergleichsvorschau fehlt. Lineare Daten können weiterhin kopiert werden."))
        if not any((linear, png, jpeg)):
            raise ValueError(tr("Bitte ein Exportformat wählen."))
        scientific, provenance = _verified_ai_files(source) if linear else ({}, None)
        self._verify_project_ai_export(source, provenance)
        output = Path(tempfile.mkdtemp(prefix="export-ai-", dir=parent))
        written = []
        if linear:
            for path, expected, size in scientific.values():
                shutil.copy2(path, output / path.name)
                with (output / path.name).open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if (output / path.name).stat().st_size != size or actual != expected:
                    raise ValueError(tr("Ergebnisdateien wurden während des Exports verändert. "
                                        "Bitte das bearbeitete Bild als neues Ergebnis einlesen."))
                written.append(path.name)
            (output / "ai_report.json").write_bytes(provenance)
            written.append("ai_report.json")
        if png or jpeg:
            from ui.ai_preview import export_display
            for enabled, suffix in ((png, ".png"), (jpeg, ".jpg")):
                if enabled:
                    name = "display_stretched" + suffix
                    options = [int(cv2.IMWRITE_JPEG_QUALITY), 95] if suffix == ".jpg" else None
                    export_display(source, output / name, display["parameters"],
                                   max_side=preview_limit, options=options)
                    written.append(name)
        (output / "export.json").write_text(json.dumps({
            "source": str(source), "scientific_files_copied_unchanged": bool(linear),
            "display_files_are_stretched": bool(png or jpeg),
            "display_parameters": display["parameters"] if display and (png or jpeg) else None,
            "display_max_side": preview_limit, "files": written}, indent=2), encoding="utf-8")
        return str(output)

    def _export_ai_result(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("KI-Ergebnis exportieren"))
        dialog.resize(520, 280)
        layout = QVBoxLayout(dialog)
        info = QLabel(tr("Lineare FITS- und TIFF-Daten werden unverändert kopiert. "
                         "Anzeigeexporte enthalten die sichtbare Streckung."))
        info.setWordWrap(True)
        layout.addWidget(info)
        linear = QCheckBox(tr("Lineares Ergebnis: Float32-FITS und TIFF"))
        linear.setChecked(True)
        png = QCheckBox(tr("Gestreckte Anzeige: PNG"))
        jpeg = QCheckBox(tr("Gestreckte Anzeige: JPG zum Teilen"))
        for checkbox in (linear, png, jpeg):
            layout.addWidget(checkbox)
        if not self._ai_display_for_current():
            png.setEnabled(False)
            jpeg.setEnabled(False)
        layout.addStretch()
        row = QHBoxLayout()
        cancel = QPushButton(tr("Abbrechen"))
        cancel.clicked.connect(dialog.reject)
        save = QPushButton(tr("Speicherort wählen und exportieren"))
        save.setObjectName("primary")
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)

        def execute():
            if not any(c.isChecked() for c in (linear, png, jpeg)):
                return
            parent = QFileDialog.getExistingDirectory(dialog, tr("Speicherort wählen"),
                                                      os.path.dirname(self.result_path))
            if not parent:
                return
            try:
                destination = self._write_ai_export(parent, linear.isChecked(), png.isChecked(), jpeg.isChecked())
            except Exception as exc:
                QMessageBox.warning(dialog, tr("Exportieren"), str(exc))
                return
            self._append(tr("KI-Ergebnis exportiert: {path}").format(path=destination) + "\n")
            reveal_in_files(destination)
            dialog.accept()

        save.clicked.connect(execute)
        dialog.show()
        self._export_dlg = dialog

    def _quick_export(self, key):
        """Ein-Klick-Export eines einzelnen Presets (ohne Dialog) direkt aus dem Panel."""
        if not self.result_path or cv2 is None:
            QMessageBox.information(self, tr("Exportieren"), tr("Erst ein Ergebnis erzeugen.")); return
        if self._is_ai_result_current():
            if key == "print":
                self._export_ai_result()
                return
            try:
                destination = self._write_ai_export(os.path.dirname(self.result_path), linear=False, jpeg=True,
                                                    preview_limit=1080 if key == "instagram" else 2048)
                self._append(tr("Gestreckte Anzeige exportiert: {path}").format(path=destination) + "\n")
                reveal_in_files(destination)
            except Exception as exc:
                QMessageBox.warning(self, tr("Exportieren"), str(exc))
            return
        if getattr(self, "_project_export_current", lambda: False)():
            return
        try:
            import focus_cull_stack as F
            stack_dir = os.path.dirname(self.result_path)
            export_dir = os.path.join(self._work_dir(), "export")
            os.makedirs(export_dir, exist_ok=True)
            F.export_targets(stack_dir, export_dir, [key],
                             only=os.path.basename(self.result_path))
        except Exception as e:
            QMessageBox.warning(self, tr("Exportieren"), f"{e}"); return
        self._append(f"\n📦 {key} → {export_dir}\n")
        reveal_in_files(export_dir)

    def export_result(self):
        """Export-Dialog: auswählen WAS exportiert wird (Ziele, Schärfung, Photoshop-Ebenen,
        16-bit-TIFF), dann schreiben + Ordner zeigen."""
        if not self.result_path or cv2 is None:
            QMessageBox.information(self, tr("Exportieren"), tr("Erst ein Ergebnis erzeugen.")); return
        if self._is_ai_result_current():
            self._export_ai_result()
            return
        if getattr(self, "_project_export_current", lambda: False)():
            return
        dlg = QDialog(self); dlg.setWindowTitle(tr("Exportieren")); dlg.resize(440, 480)
        lay = QVBoxLayout(dlg)

        g1 = QGroupBox(tr("Ziele")); g1l = QVBoxLayout(g1)
        targets = {}
        for key, lbl in [("webjpg", tr("Web-JPG (zum Teilen)")), ("instagram", "Instagram (1080 px)"),
                         ("whatsapp", "WhatsApp (1600 px)"), ("web", "Web (2048 px)"),
                         ("4k", "4K (3840 px)"), ("print", tr("Druck (16-bit-TIFF, volle Größe)"))]:
            cb = QCheckBox(lbl); targets[key] = cb; g1l.addWidget(cb)
        targets["webjpg"].setChecked(True)
        lay.addWidget(g1)

        g2 = QGroupBox(tr("Optionen")); g2l = QGridLayout(g2)
        psd = QCheckBox(tr("Photoshop-Ebenen-Datei (.tif mit Ebenen)"))
        tiff16 = QCheckBox(tr("16-bit-TIFF (verlustfrei)"))
        g2l.addWidget(psd, 0, 0, 1, 2); g2l.addWidget(tiff16, 1, 0, 1, 2)
        g2l.addWidget(QLabel(tr("Ausgabe-Schärfung")), 2, 0)
        sharp = QSpinBox(); sharp.setRange(0, 50); sharp.setValue(0); sharp.setSuffix(" %")
        sharp.setToolTip(tr("Leichtes Nachschärfen beim Export. 0 = aus."))
        g2l.addWidget(sharp, 2, 1)
        g2l.addWidget(QLabel(tr("JPG-Qualität")), 3, 0)
        jq = QSpinBox(); jq.setRange(60, 100); jq.setValue(92); g2l.addWidget(jq, 3, 1)
        lay.addWidget(g2)

        info = QLabel(); info.setStyleSheet("color:#9aa09a;font-size:11px;"); lay.addWidget(info)
        row = QHBoxLayout()
        ok = QPushButton(tr("Exportieren")); ok.setObjectName("primary")
        cancel = QPushButton(tr("Abbrechen"))
        row.addStretch(1); row.addWidget(cancel); row.addWidget(ok); lay.addLayout(row)
        cancel.clicked.connect(dlg.reject)

        def do_export():
            chosen = [k for k in ("instagram", "whatsapp", "web", "4k", "print") if targets[k].isChecked()]
            any_sel = (targets["webjpg"].isChecked() or tiff16.isChecked() or psd.isChecked() or chosen)
            if not any_sel:
                QMessageBox.information(dlg, tr("Exportieren"),
                                       tr("Bitte mindestens ein Ziel auswählen.")); return
            res = imread(self.result_path, cv2.IMREAD_UNCHANGED)
            if res is None:
                QMessageBox.warning(dlg, tr("Exportieren"),
                                    tr("Ergebnis konnte nicht geladen werden.")); return
            try:
                import focus_cull_stack as F
                import stacker
                stack_dir = os.path.dirname(self.result_path)
                export_dir = os.path.join(self._work_dir(), "export")
                os.makedirs(export_dir, exist_ok=True)
                base = os.path.splitext(os.path.basename(self.result_path))[0]
                written = 0
                if sharp.value() > 0:
                    res = stacker.unsharp_mask(res, sharp.value(), 0.8)
                if targets["webjpg"].isChecked():
                    if res.dtype == np.uint16:
                        img8 = (res / 256).astype(np.uint8)
                    elif res.dtype == np.uint8:
                        img8 = res
                    else:  # float -> 0..255
                        img8 = np.clip(res * (255.0 if res.max() <= 1.5 else 1.0), 0, 255).astype(np.uint8)
                    imwrite(os.path.join(export_dir, f"{base}_web.jpg"), img8,
                                [int(cv2.IMWRITE_JPEG_QUALITY), jq.value()]); written += 1
                if tiff16.isChecked():
                    if res.dtype == np.uint16:
                        out = res
                    elif res.dtype == np.uint8:
                        out = (res.astype(np.float32) * 257).astype(np.uint16)
                    else:  # float -> 16-bit
                        out = np.clip(res * (65535.0 if res.max() <= 1.5 else 257.0), 0, 65535).astype(np.uint16)
                    imwrite(os.path.join(export_dir, f"{base}_16bit.tif"), out,
                                [int(cv2.IMWRITE_TIFF_COMPRESSION), 1]); written += 1
                if chosen:
                    # NUR die echte Ergebnisdatei exportieren (kein Verzeichnis-Scan -> kein Müll)
                    F.export_targets(stack_dir, export_dir, chosen,
                                     only=os.path.basename(self.result_path)); written += len(chosen)
                if psd.isChecked():
                    srcs, names = self._gather_sources()
                    srcs = [s for s in srcs if s is not None] if srcs else []
                    if srcs:
                        srcs = [cv2.resize(s, (res.shape[1], res.shape[0])) if s.shape[:2] != res.shape[:2]
                                else s for s in srcs]
                        named = [("Stack (Ergebnis)", res)] + [(n, s) for n, s in zip(names, srcs)]
                        stacker.write_layered_tiff(os.path.join(export_dir, f"{base}_ebenen.tif"),
                                                   named, flat_bgr=res); written += 1
                    else:
                        QMessageBox.information(dlg, tr("Exportieren"),
                                               tr("Ebenen-Datei: keine Quellfotos gefunden (nur Fokus-Stacking)."))
            except Exception as e:
                QMessageBox.warning(dlg, tr("Exportieren"), f"{e}"); return
            self._append(f"\n📦 Exportiert ({written} Datei(en)) → {export_dir}\n")
            reveal_in_files(export_dir)
            dlg.accept()

        ok.clicked.connect(do_export)
        dlg.show(); self._export_dlg = dlg
