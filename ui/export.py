#!/usr/bin/env python3
"""ui/export.py — Export (Schnell-Chips + Dialog) als Mixin für MainWindow."""
import os

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
                               QLabel, QCheckBox, QSpinBox, QPushButton, QMessageBox)

from i18n import tr
from ui.components import reveal_in_files
from constants import imread, imwrite

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None


class ExportMixin:
    """Ein-Klick-Export-Chips und ausführlicher Export-Dialog (Ziele/Schärfung/Ebenen/16-bit)."""

    def _quick_export(self, key):
        """Ein-Klick-Export eines einzelnen Presets (ohne Dialog) direkt aus dem Panel."""
        if not self.result_path or cv2 is None:
            QMessageBox.information(self, tr("Exportieren"), tr("Erst ein Ergebnis erzeugen.")); return
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
