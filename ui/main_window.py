#!/usr/bin/env python3
"""
ui/main_window.py — ForgePix-Hauptfenster (PySide6).

Start-Auswahl der Module, Schritt-für-Schritt-Wizard, alle Einstellungen, Live-Log
und Ergebnis-Vorschau. Ruft focus_cull_stack.py als Subprozess auf (streamt stdout/stderr live).
Einstiegspunkt: focus_stack_gui.py (dünner Launcher) bzw. ForgePix.app.
"""
import os
import hashlib
import re
import subprocess
import sys

from i18n import tr, set_language, available_languages, current_language



from PySide6.QtCore import Qt, QProcess, QSettings, QRect, QSize, QThread, QTimer, Signal
from PySide6.QtGui import (QPixmap, QFont, QIcon, QPainter, QColor, QPen, QCursor, QImage,
                           QShortcut, QKeySequence, QAction)
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QFileDialog, QPlainTextEdit,
    QDoubleSpinBox, QSpinBox, QCheckBox, QMessageBox, QSplitter, QFrame, QComboBox,
    QScrollArea, QProgressBar, QToolButton, QDialog, QToolTip, QSlider, QStackedWidget,
    QMenu,
)

try:
    import cv2  # robuste Vorschau (auch 16-bit TIFF)
    import numpy as np
except Exception:
    cv2 = None
    np = None
FRAME_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
from ui.appinfo import HERE, SCRIPT, ICON, ICON_PNG, APP_NAME, IMG_EXTS, _cache_path  # noqa: E402,F401


from ui.theme import THEME
from ui.welcome import WelcomeMixin
from ui.settings_io import SettingsMixin
from ui.export import ExportMixin
from ui.result_view import ResultMixin
from ui.components import (CompareSlider, CurveWidget, AdjustDialog, RetouchDialog, _Canvas,
                           _bgr_to_pixmap, histogram_pixmap, adjust_image, HSL_BANDS,
                           help_btn, _row, reveal_in_files, open_path, notify)


from ui.workers import _AnalyzeWorker, _UpdateChecker, _version_newer  # noqa: F401


class MainWindow(WelcomeMixin, SettingsMixin, ExportMixin, ResultMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ForgePix — Fokus-Stacking mit KI")
        self.resize(1440, 900)  # großzügig, damit nichts abgeschnitten ist
        if os.path.isfile(ICON):
            self.setWindowIcon(QIcon(ICON))
        elif os.path.isfile(ICON_PNG):
            self.setWindowIcon(QIcon(ICON_PNG))
        self.proc = None
        self.setAcceptDrops(True)

        # Setup-Dialog (Sprache + KI + Server) — sammelt alle Configs an einem Ort
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Setup")
        self.settings_dialog.resize(560, 420)
        self._settings_lay = QVBoxLayout(self.settings_dialog)

        # Top-Level: Seite 0 = Modul-Auswahl (Start), Seite 1 = Arbeitsbereich
        self.top_stack = QStackedWidget()
        self.setCentralWidget(self.top_stack)
        self.welcome = self._build_welcome()
        self.top_stack.addWidget(self.welcome)          # Index 0

        root = QWidget()
        self.top_stack.addWidget(root)                  # Index 1
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(12)

        # Header mit Logo + Name
        header = QHBoxLayout()
        header.setSpacing(8)
        self.modules_btn = QPushButton(tr("◀ Module"))
        self.modules_btn.setToolTip(tr("Zur Modul-Auswahl zurück"))
        self.modules_btn.clicked.connect(lambda: self.top_stack.setCurrentIndex(0))
        header.addWidget(self.modules_btn)
        logo = QLabel()
        if os.path.isfile(ICON_PNG):
            logo.setPixmap(QPixmap(ICON_PNG).scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        try:
            from constants import VERSION as _VER
        except Exception:
            _VER = ""
        # Titel-Block: Name groß + Untertitel darunter (wirkt hochwertiger)
        tblock = QVBoxLayout(); tblock.setSpacing(0)
        trow = QHBoxLayout(); trow.setSpacing(6)
        title = QLabel("ForgePix"); title.setStyleSheet("font-size:21px;font-weight:800;letter-spacing:0.3px;")
        ver = QLabel(f"v{_VER}"); ver.setStyleSheet("color:#6f6a85;font-size:11px;")
        trow.addWidget(title); trow.addWidget(ver); trow.addStretch(1)
        subtitle = QLabel(tr("Computational Photography Suite"))
        subtitle.setStyleSheet("color:#7bd36a;font-size:11px;letter-spacing:0.4px;")
        tblock.addLayout(trow); tblock.addWidget(subtitle)
        header.addSpacing(6); header.addWidget(logo); header.addSpacing(10); header.addLayout(tblock)
        header.addStretch(1)
        task_lbl = QLabel(tr("Aufgabe:")); task_lbl.setStyleSheet("color:#908aa0;")
        header.addWidget(task_lbl)
        self.task_box = QComboBox()
        self.task_box.addItems([tr("🔬 Makro (Fokus)"), tr("🌌 Astro (Sterne)"),
                                tr("🌗 Hybrid (Mosaik)"), tr("📷 Langzeitbelichtung")])
        # 0=Makro, 1=Astro, 2=Hybrid, 3=Langzeit
        self.task_box.currentIndexChanged.connect(lambda _i: self._set_task())
        header.addWidget(self.task_box)
        header.addSpacing(14)
        mode_lbl = QLabel(tr("Modus:")); mode_lbl.setStyleSheet("color:#908aa0;")
        header.addWidget(mode_lbl)
        self.mode_box = QComboBox()
        self.mode_box.addItems([tr("🌱 Anfänger"), tr("🛠️ Profi")])  # 0=Anfänger, 1=Profi
        self.mode_box.currentIndexChanged.connect(lambda _i: self._apply_visibility())
        header.addWidget(self.mode_box)
        header.addSpacing(12)
        kbd_btn = QPushButton("⌨️")
        kbd_btn.setToolTip(tr("Tastenkürzel anzeigen (F1)"))
        kbd_btn.setFixedWidth(44)
        kbd_btn.clicked.connect(self._show_shortcuts)
        header.addWidget(kbd_btn)
        setup_btn = QPushButton(tr("⚙  Setup"))
        setup_btn.setToolTip(tr("Sprache, KI-Server und weitere Einstellungen"))
        setup_btn.clicked.connect(self.settings_dialog.show)
        header.addWidget(setup_btn)
        outer.addLayout(header)
        # Statuszeile statt nur grünem Strich — zeigt echten Fortschritt
        self.status_bar = QFrame(); self.status_bar.setFixedHeight(26)
        sbl = QHBoxLayout(self.status_bar); sbl.setContentsMargins(12, 0, 12, 0)
        self.status_dot = QLabel("●"); self.status_dot.setStyleSheet("color:#4caf50;font-size:13px;")
        self.status_lbl = QLabel(tr("Bereit")); self.status_lbl.setStyleSheet("color:#cfd2cd;font-size:12px;")
        sbl.addWidget(self.status_dot); sbl.addSpacing(6); sbl.addWidget(self.status_lbl); sbl.addStretch(1)
        self.status_bar.setStyleSheet("QFrame{background:#1b2a1b;border-bottom:2px solid #4caf50;}")
        outer.addWidget(self.status_bar)

        # Sprache — wandert ins Setup-Menü
        self.lang_box = QComboBox()
        self._lang_codes = [c for c, _n in available_languages()]
        for _c, _n in available_languages():
            self.lang_box.addItem(_n)
        if current_language() in self._lang_codes:
            self.lang_box.setCurrentIndex(self._lang_codes.index(current_language()))
        self.lang_box.currentIndexChanged.connect(self._on_language)
        self._settings_lay.addLayout(_row(tr("Sprache:"), self.lang_box))
        # Anfänger/Profi auch im Setup (synchron mit der Kopfzeile)
        self.set_mode = QComboBox()
        self.set_mode.addItems([tr("🌱 Anfänger"), tr("🛠️ Profi")])
        self.set_mode.setCurrentIndex(self.mode_box.currentIndex())
        self.set_mode.currentIndexChanged.connect(self.mode_box.setCurrentIndex)
        self.mode_box.currentIndexChanged.connect(self.set_mode.setCurrentIndex)
        self._settings_lay.addLayout(_row(tr("Modus:"), self.set_mode,
                                          tr("Anfänger = ein Klick. Profi = alle Regler + Wizard.")))

        # Beim Start dezent auf neue Versionen prüfen (nur GitHub-Releases-API, abschaltbar)
        self.chk_updates = QCheckBox(tr("Beim Start auf Updates prüfen"))
        self.chk_updates.setToolTip(tr("Fragt einmal beim Start die GitHub-Releases ab und zeigt "
                                       "einen Hinweis, wenn eine neuere Version vorliegt. Keine Daten gesendet."))
        self.chk_updates.setChecked(
            QSettings("ServeOne", "ForgePix").value("check_updates", "1") != "0")
        self.chk_updates.toggled.connect(
            lambda on: QSettings("ServeOne", "ForgePix").setValue("check_updates", "1" if on else "0"))
        self._settings_lay.addWidget(self.chk_updates)

        # Externe Tools (optional) — Pfade frei einstellbar; leer = automatisch suchen
        try:
            import tools_engine as _te
            import siril_engine as _se
            gx_def, sn_def, si_def = (_te.find_graxpert() or "", _te.find_starnet() or "",
                                      _se.find_siril() or "")
        except Exception:
            gx_def = sn_def = si_def = ""
        g_tools = QGroupBox(tr("Externe Tools (optional)"))
        gt = QGridLayout(g_tools)
        self.graxpert_path = QLineEdit(gx_def)
        self.graxpert_path.setPlaceholderText(tr("Pfad zu GraXpert (leer = automatisch suchen)"))
        self.starnet_path = QLineEdit(sn_def)
        self.starnet_path.setPlaceholderText(tr("Pfad zu StarNet++ (leer = automatisch suchen)"))
        self.siril_path = QLineEdit(si_def)
        self.siril_path.setPlaceholderText(tr("Pfad zu siril-cli (leer = automatisch suchen)"))
        for r, (lab, edit) in enumerate([("GraXpert", self.graxpert_path),
                                         ("StarNet++", self.starnet_path),
                                         ("Siril", self.siril_path)]):
            btn = QPushButton("…"); btn.setFixedWidth(36)
            btn.clicked.connect(lambda _=False, e=edit: self._pick_file_into(e))
            gt.addWidget(QLabel(lab), r, 0); gt.addWidget(edit, r, 1); gt.addWidget(btn, r, 2)
        gt.addWidget(help_btn("Pfade zu deinen installierten Tools. Leer lassen = ForgePix sucht "
                              "selbst (PATH + übliche Orte). GraXpert/StarNet → Ein-Klick in der "
                              "Ergebnis-Leiste; Siril → wählbare Astro-Engine. Alles optional."), 0, 3)
        self._settings_lay.addWidget(g_tools)

        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, 1)

        # ---- linke Spalte: Schritt-für-Schritt-Wizard ----
        left = QWidget()
        left.setMinimumWidth(450)
        left.setMaximumWidth(560)
        lv = QVBoxLayout(left)

        self.STEP_NAMES = [tr("1 · Fotos"), tr("2 · Auswahl & Ausrichtung"),
                           tr("3 · Ergebnis-Optionen")]
        self.crumb = QLabel()
        self.crumb.setStyleSheet("font-weight:bold;color:#7bd36a;")
        lv.addWidget(self.crumb)

        self.wizard = QStackedWidget()
        # eine scrollbare Seite je Schritt (KI liegt jetzt im Setup-Menü)
        self._wiz_lay = []
        for _ in range(3):
            page = QWidget(); play = QVBoxLayout(page)
            sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
            sc.setWidget(page)
            self.wizard.addWidget(sc)
            self._wiz_lay.append(play)
        lv.addWidget(self.wizard, 1)
        p1, p2, p3 = self._wiz_lay

        # Ordner  (Schritt 1)
        g_paths = QGroupBox(tr("Ordner"))
        pg = QVBoxLayout(g_paths)
        self.in_edit = QLineEdit()
        self.in_edit.setPlaceholderText("Ordner mit den Aufnahmen …")
        in_btn = QPushButton(tr("Wählen…")); in_btn.clicked.connect(self.pick_input)
        ih = _row(tr("Eingabe-Ordner"), self.in_edit); ih.addWidget(in_btn)
        pg.addLayout(ih)

        self.work_edit = QLineEdit()
        self.work_edit.setPlaceholderText("leer = <Eingabe>/../stack_work")
        work_btn = QPushButton("Wählen…"); work_btn.clicked.connect(self.pick_work)
        wh = _row(tr("Arbeits-Ordner"), self.work_edit); wh.addWidget(work_btn)
        pg.addLayout(wh)
        # Erweiterte Ordner-Optionen (im Anfänger-Modus ausgeblendet)
        self.adv_folder = QWidget()
        av = QVBoxLayout(self.adv_folder); av.setContentsMargins(0, 0, 0, 0)
        self.batch = QCheckBox("Batch: jeder Unterordner = eigener Stack")
        bh = QHBoxLayout(); bh.addWidget(self.batch, 1)
        bh.addWidget(help_btn("Wenn dein Ordner mehrere Foto-Serien in Unterordnern enthält "
                              "(z.B. mehrere Blumen), wird jede Serie einzeln verrechnet. "
                              "Die Automatik erkennt das auch von selbst."))
        av.addLayout(bh)
        self.watch = QCheckBox("Watch-Modus: Ordner beobachten und automatisch stacken")
        self.watch_settle = QSpinBox(); self.watch_settle.setRange(2, 120); self.watch_settle.setValue(5)
        self.watch_settle.setSuffix(" s"); self.watch_settle.setEnabled(False)
        self.watch.toggled.connect(self.watch_settle.setEnabled)
        wh2 = QHBoxLayout(); wh2.addWidget(self.watch, 1)
        wh2.addWidget(help_btn("Das Tool läuft weiter und verrechnet automatisch, sobald du neue "
                               "Fotos in den Ordner kopierst."))
        av.addLayout(wh2)
        av.addLayout(_row("Settle-Zeit", self.watch_settle,
                          "Wie viele Sekunden Ruhe (kein neues Foto), bevor automatisch "
                          "verrechnet wird — damit der Kopiervorgang sicher fertig ist."))
        pg.addWidget(self.adv_folder)
        p1.addWidget(g_paths)

        # Ein-Klick-Automatik (Hauptaktion)
        self.auto_btn = QPushButton("⚡  Automatik — beste Qualität (ein Klick)")
        self.auto_btn.setToolTip("Ordner wählen, hier klicken. Die KI bestimmt alle Einstellungen, "
                                 "RAW läuft in 16-bit, Ebenen-TIFF fürs Weiterbearbeiten wird erzeugt.")
        self.auto_btn.setMinimumHeight(46)
        self.auto_btn.setObjectName("primary")
        self.auto_btn.setStyleSheet("font-size:14px;")
        self.auto_btn.clicked.connect(lambda: self.run(auto=True))
        p1.addWidget(self.auto_btn)
        hint = QLabel("Ein Klick genügt. Für mehr Kontrolle mit „Weiter →“ durch die Schritte.")
        hint.setStyleSheet("color:#9aa09a;"); hint.setWordWrap(True)
        p1.addWidget(hint)

        # Vorlage (Motiv) — setzt passende Makro-Einstellungen
        self.preset_group = QGroupBox(tr("Vorlage (Motiv)"))
        pgv = QVBoxLayout(self.preset_group)
        pgl = QHBoxLayout()
        self.preset_box = QComboBox()
        self.preset_box.addItems([tr("Standard"), tr("Produkte"), tr("Münzen"), tr("Food")])
        self.preset_box.currentIndexChanged.connect(lambda i: self._apply_preset(i))
        pgl.addWidget(self.preset_box, 1)
        pgl.addWidget(help_btn("Schnellvorlage je Motiv: setzt sinnvolle Werte (Schärfen, "
                               "Ausrichtung, Erkennung). „Produkte/Münzen/Food“ — danach manuell "
                               "feinjustierbar."))
        pgv.addLayout(pgl)
        mk_info = QLabel(tr("Makro/Fokus: mehrere Nahaufnahmen mit Fokus von vorn nach hinten → "
                            "ein durchgehend scharfes Bild. Empfohlen: 10–40 Aufnahmen (so viele, "
                            "bis alles scharf abgedeckt ist), Stativ, gleiche Belichtung."))
        mk_info.setWordWrap(True); mk_info.setStyleSheet("color:#9aa09a;font-size:11px;")
        pgv.addWidget(mk_info)
        p1.addWidget(self.preset_group)

        # RAW-Entwicklung
        g_raw = QGroupBox(tr("RAW-Entwicklung"))
        rg = QGridLayout(g_raw)
        self.raw_dev = QCheckBox("RAWs zu TIFF entwickeln (treu, vor dem Stacking)")
        self.raw_dev.setChecked(True)
        self.raw_dev.setToolTip("RAW (ARW/NEF/CR2/DNG…) wird mit rawpy entwickelt, damit die "
                                "ganze Kette in hoher Bit-Tiefe läuft. Nicht-RAW bleibt unberührt.")
        self.raw_wb = QComboBox(); self.raw_wb.addItems(["camera", "auto", "daylight"])
        self.raw_bps = QComboBox(); self.raw_bps.addItems(["16", "8"])
        self.raw_auto_bright = QCheckBox("Auto-Helligkeit (sonst treu)")
        self.raw_half = QCheckBox("Halbe Auflösung (schneller)")
        for w in (self.raw_wb, self.raw_bps, self.raw_auto_bright, self.raw_half):
            self.raw_dev.toggled.connect(w.setEnabled)
        rg.addWidget(self.raw_dev, 0, 0, 1, 2)
        rg.addWidget(help_btn("RAW-Dateien (ARW/NEF/CR2/DNG …) werden zuerst schonend in ein "
                              "hochwertiges Bild umgewandelt, damit die volle Qualität fürs "
                              "Bearbeiten erhalten bleibt. Normale JPGs werden direkt verwendet."), 0, 2)
        rg.addWidget(QLabel("Weißabgleich"), 1, 0); rg.addWidget(self.raw_wb, 1, 1)
        rg.addWidget(help_btn("Wie Farben/Weiß interpretiert werden. „camera“ = Einstellung der "
                              "Kamera (empfohlen), „auto“ = Computer schätzt, „daylight“ = Tageslicht."), 1, 2)
        rg.addWidget(QLabel("Bit-Tiefe"), 2, 0); rg.addWidget(self.raw_bps, 2, 1)
        rg.addWidget(help_btn("Wie fein Farbabstufungen gespeichert werden. 16 = höchste Qualität "
                              "zum Bearbeiten (empfohlen), 8 = kleiner, weniger Spielraum."), 2, 2)
        rg.addWidget(self.raw_auto_bright, 3, 0, 1, 2)
        rg.addWidget(help_btn("Hellt das Bild automatisch auf. Aus = originalgetreu (empfohlen)."), 3, 2)
        rg.addWidget(self.raw_half, 4, 0, 1, 2)
        rg.addWidget(help_btn("Entwickelt RAW in halber Größe — schneller, weniger Details. "
                              "Gut zum schnellen Ausprobieren."), 4, 2)
        self.g_raw = g_raw
        p1.addWidget(g_raw)

        # Astro-Modus (Sterne) — eigener Algorithmus
        g_astro = QGroupBox(tr("Astro-Modus (Sterne)"))
        g_astro.setCheckable(True); g_astro.setChecked(False)
        self.astro_group = g_astro
        ar = QGridLayout(g_astro)
        self.astro_method = QComboBox()
        self.astro_method.addItems(["sigma", "winsor", "average", "median", "max"])
        self.astro_kappa = QDoubleSpinBox(); self.astro_kappa.setRange(1.0, 5.0)
        self.astro_kappa.setSingleStep(0.1); self.astro_kappa.setValue(2.5)
        self.astro_register = QCheckBox("Sterne ausrichten"); self.astro_register.setChecked(True)
        self.astro_qc = QCheckBox(tr("Schlechte Subs automatisch aussortieren")); self.astro_qc.setChecked(True)
        self.astro_stretch = QCheckBox("Vorschau strecken (asinh)"); self.astro_stretch.setChecked(True)
        self.astro_bg = QCheckBox("Hintergrund/Gradient entfernen")
        self.astro_fits = QCheckBox("Auch als FITS speichern")
        self.astro_align = QComboBox()
        self.astro_align.addItem(tr("Translation (Nachführung)"), "shift")
        self.astro_align.addItem(tr("Translation + Feldrotation (Alt-Az)"), "rotate")
        self.astro_cosmetic = QCheckBox(tr("Hot-/Cold-Pixel entfernen"))
        self.astro_drizzle = QComboBox()
        self.astro_drizzle.addItem(tr("Aus"), 1)
        self.astro_drizzle.addItem(tr("2× (feineres Sampling)"), 2)
        self.astro_dark = QLineEdit(); self.astro_dark.setPlaceholderText("optional: Dark-Ordner/-Datei")
        self.astro_flat = QLineEdit(); self.astro_flat.setPlaceholderText("optional: Flat-Ordner/-Datei")
        self.astro_bias = QLineEdit(); self.astro_bias.setPlaceholderText("optional: Bias-Ordner/-Datei")
        dbtn = QPushButton("…"); dbtn.setFixedWidth(36); dbtn.clicked.connect(lambda: self._pick_into(self.astro_dark))
        fbtn = QPushButton("…"); fbtn.setFixedWidth(36); fbtn.clicked.connect(lambda: self._pick_into(self.astro_flat))
        bbtn = QPushButton("…"); bbtn.setFixedWidth(36); bbtn.clicked.connect(lambda: self._pick_into(self.astro_bias))
        # Engine: eigene oder optional Siril (Pfad steht im Setup-Menü unter „Externe Tools“)
        self.astro_engine = QComboBox()
        self.astro_engine.addItem(tr("Eigene"), "own")
        self.astro_engine.addItem("Siril", "siril")
        ar.addWidget(QLabel("Methode"), 0, 0); ar.addWidget(self.astro_method, 0, 1, 1, 2)
        ar.addWidget(help_btn("Rauschen mitteln statt Schärfe wählen. „sigma“ (Kappa-Sigma) "
                              "entfernt Satelliten/Flugzeuge/Hot-Pixel — wie in Siril. "
                              "„max“ = Strichspuren."), 0, 3)
        ar.addWidget(QLabel("Kappa"), 1, 0); ar.addWidget(self.astro_kappa, 1, 1, 1, 2)
        ar.addWidget(self.astro_register, 2, 0, 1, 3)
        ar.addWidget(self.astro_qc, 3, 0, 1, 3)
        ar.addWidget(help_btn("Bewertet jede Aufnahme (Sternzahl/FWHM/Elongation/Wolken/Spuren) "
                              "und lässt schlechte Subs weg — mit Begründung im Log. Aus = alle "
                              "Aufnahmen verwenden."), 3, 3)
        ar.addWidget(self.astro_stretch, 4, 0, 1, 3)
        ar.addWidget(self.astro_bg, 5, 0, 1, 3)
        ar.addWidget(help_btn("Entfernt weiche Helligkeits-Gradienten (Lichtverschmutzung/Vignette). "
                              "Für stärkere Tools: das 32-bit-Linear-TIFF in GraXpert/StarNet++/"
                              "PixInsight öffnen."), 5, 3)
        ar.addWidget(QLabel("Dark"), 6, 0); ar.addWidget(self.astro_dark, 6, 1, 1, 1); ar.addWidget(dbtn, 6, 2)
        ar.addWidget(QLabel("Flat"), 7, 0); ar.addWidget(self.astro_flat, 7, 1, 1, 1); ar.addWidget(fbtn, 7, 2)
        ar.addWidget(QLabel("Bias"), 8, 0); ar.addWidget(self.astro_bias, 8, 1, 1, 1); ar.addWidget(bbtn, 8, 2)
        ar.addWidget(QLabel("Engine"), 9, 0); ar.addWidget(self.astro_engine, 9, 1, 1, 2)
        ar.addWidget(help_btn("„Eigene“ = ForgePix selbst (Standard, kein Fremdprogramm). "
                              "„Siril“ = optional dein installiertes Siril fernsteuern "
                              "(Konvertieren→Registrieren→Stacken). Pfad im Setup-Menü → "
                              "„Externe Tools“."), 9, 3)
        ar.addWidget(self.astro_fits, 10, 0, 1, 3)
        ar.addWidget(help_btn("Speichert das fertige Stack-Ergebnis zusätzlich als 32-bit-FITS "
                              "(neben dem TIFF) — für PixInsight/Siril. FITS-Lights werden auch "
                              "direkt eingelesen."), 10, 3)
        ar.addWidget(QLabel(tr("Ausrichtung")), 11, 0); ar.addWidget(self.astro_align, 11, 1, 1, 2)
        ar.addWidget(help_btn("Translation = nur Verschiebung (nachgeführte Montierung, schnell). "
                              "Translation + Feldrotation = richtet auch gedrehte Felder aus "
                              "(Alt-Az-Montierung ohne Rotator, lange Sessions) — per Stern-Merkmalen."), 11, 3)
        ar.addWidget(self.astro_cosmetic, 12, 0, 1, 2)
        ar.addWidget(QLabel(tr("Drizzle")), 12, 2); ar.addWidget(self.astro_drizzle, 12, 3)
        ar.addWidget(help_btn("Hot-/Cold-Pixel = entfernt helle/dunkle Einzelpixel (Sensor-Defekte) "
                              "vor dem Stacken. Drizzle 2× = doppelt hochskaliert integrieren "
                              "(feineres Sampling bei unterabgetasteten Daten; „Drizzle-lite“, keine "
                              "echte Pixel-Fraktion wie PixInsight)."), 13, 3)
        as_info = QLabel(tr("Astro: viele Aufnahmen desselben Himmelsausschnitts → Rauschen mitteln. "
                            "Empfohlen: 20–100+ Lights (mehr = weniger Rauschen) · Darks 15–30 · "
                            "Flats 15–30 · Bias 30+. Optional als Ordner/Datei angeben."))
        as_info.setWordWrap(True); as_info.setStyleSheet("color:#9aa09a;font-size:11px;")
        ar.addWidget(as_info, 14, 0, 1, 4)
        p1.addWidget(g_astro)

        # Hybrid — Mosaik (Mond/Sonne) ODER Fokus+Astro
        g_mos = QGroupBox(tr("Hybrid"))
        self.mosaic_group = g_mos
        mg = QGridLayout(g_mos)
        self.hybrid_kind = QComboBox()
        self.hybrid_kind.addItem(tr("Mosaik (Mond/Sonne)"), "mosaic")
        self.hybrid_kind.addItem(tr("Fokus + Astro (Rauschen + Schärfentiefe)"), "fa")
        mg.addWidget(QLabel(tr("Art")), 0, 0); mg.addWidget(self.hybrid_kind, 0, 1, 1, 2)
        mg.addWidget(help_btn("Mosaik = überlappende Kacheln zusammensetzen. "
                              "Fokus+Astro = je Fokus-Position mehrere Shots erst astro-stacken "
                              "(Rauschen senken), dann fokus-stacken (Schärfentiefe). Ideal für "
                              "lichtschwache Makro-/Mond-/Sonnen-Serien."), 0, 3)
        # Mosaik-Optionen
        self.mosaic_mode = QComboBox(); self.mosaic_mode.addItems(["panorama", "scans"])
        self.mos_row = QLabel(tr("Modus"))
        mg.addWidget(self.mos_row, 1, 0); mg.addWidget(self.mosaic_mode, 1, 1, 1, 2)
        mg.addWidget(help_btn("panorama=mit Rotation, scans=planar. ~30 % Überlappung empfohlen."), 1, 3)
        # Fokus+Astro-Optionen
        self.hybrid_group = QSpinBox(); self.hybrid_group.setRange(1, 99); self.hybrid_group.setValue(5)
        self.fa_row = QLabel(tr("Shots je Position"))
        mg.addWidget(self.fa_row, 2, 0); mg.addWidget(self.hybrid_group, 2, 1, 1, 2)
        mg.addWidget(help_btn("Nur wenn KEINE Unterordner: so viele aufeinanderfolgende Fotos = eine "
                              "Fokus-Position. Besser: je Position einen Unterordner anlegen."), 2, 3)
        hy_info = QLabel(tr("Hybrid: Mosaik = überlappende Kacheln (Mond/Sonne) zusammensetzen, "
                            "~30 % Überlappung, 4–20+ Kacheln. Fokus+Astro = je Fokus-Position "
                            "mehrere Shots (5–15) in einem Unterordner, mehrere Positionen."))
        hy_info.setWordWrap(True); hy_info.setStyleSheet("color:#9aa09a;font-size:11px;")
        mg.addWidget(hy_info, 3, 0, 1, 4)
        self.hybrid_kind.currentIndexChanged.connect(lambda _i: self._hybrid_kind_changed())
        p1.addWidget(g_mos)

        # Langzeitbelichtung
        g_le = QGroupBox(tr("Langzeitbelichtung"))
        self.longexp_group = g_le
        lg = QGridLayout(g_le)
        self.longexp_mode = QComboBox()
        self.longexp_mode.addItem(tr("Glatt — Wasser/Wolken (Mitteln)"), "smooth")
        self.longexp_mode.addItem(tr("Lichtspuren — Autos/Sterne (Aufhellen)"), "trails")
        self.longexp_mode.addItem(tr("Störer entfernen — Passanten/Autos (Median)"), "declutter")
        self.longexp_mode.addItem(tr("Aufhellen — dunkle Nacht (additiv)"), "bright")
        lg.addWidget(QLabel(tr("Effekt")), 0, 0); lg.addWidget(self.longexp_mode, 0, 1, 1, 2)
        lg.addWidget(help_btn("Glatt = seidiges Wasser/weiche Wolken (klassischer ND-Look). "
                              "Lichtspuren = helle Bewegungen sammeln (Autolichter, Startrails, "
                              "Feuerwerk). Störer entfernen = bewegte Objekte verschwinden "
                              "(Median). Aufhellen = Licht aufsummieren für dunkle Szenen."), 0, 3)
        self.longexp_align = QComboBox()
        self.longexp_align.addItem(tr("Stativ — nicht ausrichten"), "none")
        self.longexp_align.addItem(tr("Leichtes Verwackeln — Versatz"), "shift")
        self.longexp_align.addItem(tr("Freihand — Merkmale"), "feature")
        lg.addWidget(QLabel(tr("Ausrichten")), 1, 0); lg.addWidget(self.longexp_align, 1, 1, 1, 2)
        lg.addWidget(help_btn("Vom Stativ: „nicht ausrichten“. Bei leichtem Verwackeln „Versatz“ "
                              "(verschiebt), aus der Hand „Merkmale“ (richtet voll aus)."), 1, 3)
        # Virtuelle Belichtungszeit (gewichtetes Teil-Mitteln)
        self.longexp_strength = QSlider(Qt.Horizontal)
        self.longexp_strength.setRange(0, 100); self.longexp_strength.setValue(100)
        self.longexp_strength_lbl = QLabel("100 %")
        self.longexp_strength.valueChanged.connect(
            lambda v: self.longexp_strength_lbl.setText(f"{v} %"))
        lg.addWidget(QLabel(tr("Virtuelle Belichtung")), 2, 0)
        lg.addWidget(self.longexp_strength, 2, 1)
        lg.addWidget(self.longexp_strength_lbl, 2, 2)
        lg.addWidget(help_btn("„Virtuelle Belichtungszeit“: stufenlos zwischen Einzelbild "
                              "(0 % = Bewegung eingefroren, kurze Zeit) und voller Glättung/"
                              "Spuren (100 % = längste Zeit). Gewichtetes Teil-Mitteln mit einem "
                              "scharfen Referenzbild — wie eine kürzere/längere Verschlusszeit."), 2, 3)
        le_sug = QPushButton(tr("🤖 Effekt vorschlagen"))
        le_sug.setToolTip(tr("Analysiert die Bewegung in der Serie und schlägt den passenden Effekt vor"))
        le_sug.clicked.connect(self._suggest_longexp)
        lg.addWidget(le_sug, 3, 0, 1, 3)
        lg.addWidget(help_btn("Misst, wo & wie sich die Aufnahmen unterscheiden (klassisch, kein "
                              "Server nötig) und wählt Glatt/Lichtspuren/Störer/Aufhellen — mit "
                              "Begründung. Du kannst den Vorschlag jederzeit überstimmen."), 3, 3)
        le_info = QLabel(tr("Empfohlen: Glatt 10–30 · Lichtspuren 30–300+ (lückenlos) · "
                            "Störer entfernen 8–20 · Aufhellen 10–60. Vom Stativ, gleiche Belichtung."))
        le_info.setWordWrap(True); le_info.setStyleSheet("color:#9aa09a;font-size:11px;")
        lg.addWidget(le_info, 4, 0, 1, 4)
        p1.addWidget(g_le)

        # Selektion
        g_sel = QGroupBox(tr("Bildauswahl"))
        sg = QGridLayout(g_sel)
        self.dip = QDoubleSpinBox(); self.dip.setRange(0.0, 1.0); self.dip.setSingleStep(0.05)
        self.dip.setValue(0.40); self.dip.setDecimals(2)
        self.dip.setToolTip("Inneren Frame verwerfen, wenn Schärfe < ratio × min(Nachbarn).\n"
                            "Höher = strenger. 0 = nie wegen Einbruch verwerfen.")
        self.absmin = QDoubleSpinBox(); self.absmin.setRange(0.0, 1000.0); self.absmin.setValue(15.0)
        self.absmin.setToolTip("Frame verwerfen, wenn Schärfe darunter (strukturlos/leer).")
        self.maxside = QSpinBox(); self.maxside.setRange(400, 6000); self.maxside.setValue(1600)
        self.maxside.setSingleStep(100)
        self.maxside.setToolTip("Downscale-Langseite für die Schärfe-Analyse (Geschwindigkeit).")
        self.dedup = QCheckBox("Doppelte Aufnahmen aussortieren")
        self.dupthresh = QDoubleSpinBox(); self.dupthresh.setRange(0.0, 0.5)
        self.dupthresh.setDecimals(4); self.dupthresh.setSingleStep(0.001); self.dupthresh.setValue(0.004)
        self.dupthresh.setEnabled(False)
        self.dedup.toggled.connect(self.dupthresh.setEnabled)
        sg.addWidget(QLabel("Strenge gegen Verwackler"), 0, 0); sg.addWidget(self.dip, 0, 1)
        sg.addWidget(help_btn("Wie streng verwackelte Einzelfotos aussortiert werden. Höher = "
                              "strenger. Es fliegen nur Fotos raus, die deutlich unschärfer sind "
                              "als ihre Nachbarn (echte Verwackler) — nicht die natürlich weichen "
                              "Enden der Schärfereihe."), 0, 2)
        sg.addWidget(QLabel("Leere Bilder aussortieren"), 1, 0); sg.addWidget(self.absmin, 1, 1)
        sg.addWidget(help_btn("Fotos fast ganz ohne Struktur (komplett unscharf/schwarz) werden "
                              "aussortiert."), 1, 2)
        sg.addWidget(QLabel("Analyse-Genauigkeit"), 2, 0); sg.addWidget(self.maxside, 2, 1)
        sg.addWidget(help_btn("Wie groß die Fotos für die Schärfe-Messung verkleinert werden. "
                              "Höher = genauer, aber langsamer. 1600 ist ein guter Wert."), 2, 2)
        sg.addWidget(self.dedup, 3, 0, 1, 2)
        sg.addWidget(help_btn("Entfernt fast identische Doppelaufnahmen. Vorsicht: bei "
                              "Schärfereihen sehen Nachbarbilder absichtlich ähnlich aus — nur an, "
                              "wenn du wirklich doppelte Aufnahmen hast."), 3, 2)
        sg.addWidget(QLabel("Empfindlichkeit (Doppelte)"), 4, 0); sg.addWidget(self.dupthresh, 4, 1)
        sg.addWidget(help_btn("Wie ähnlich zwei Fotos sein müssen, um als Doppel zu gelten. "
                              "Kleiner = strenger."), 4, 2)
        self.reject_blurry = QCheckBox(tr("Verwackelte/unscharfe automatisch aussortieren"))
        self.reject_blurry.setChecked(True)
        self.blurry_rel = QDoubleSpinBox(); self.blurry_rel.setRange(0.10, 0.80)
        self.blurry_rel.setSingleStep(0.05); self.blurry_rel.setValue(0.45); self.blurry_rel.setDecimals(2)
        self.blurry_rel.setToolTip(tr("Schwelle: Foto raus, wenn die schärfste Stelle darunter "
                                      "(× Serien-Median) liegt. Höher = strenger."))
        self.reject_blurry.toggled.connect(self.blurry_rel.setEnabled)
        sg.addWidget(self.reject_blurry, 5, 0, 1, 1); sg.addWidget(self.blurry_rel, 5, 1)
        sg.addWidget(help_btn("Misst die Schärfe jeder Aufnahme in Kacheln und wirft Fotos raus, "
                              "die NIRGENDS richtig scharf sind (verwackelt/Fehlfokus) — mit "
                              "Begründung im Log. Der Wert rechts ist die Strenge (Standard 0.45). "
                              "Zusätzlich zur Nachbar-Strenge oben."), 5, 2)
        # Fokus-Werkzeuge: Reihe analysieren + DOF-Rechner
        tools = QHBoxLayout()
        self.analyze_btn = QPushButton(tr("🔍 Reihe analysieren"))
        self.analyze_btn.setToolTip(tr("Untersucht die Fokusreihe: verwackelte Fotos, redundante "
                                       "Aufnahmen, Fokus-Abdeckung und optimale Bildanzahl."))
        self.analyze_btn.clicked.connect(self.analyze_series)
        self.dof_btn = QPushButton(tr("📐 DOF-Rechner"))
        self.dof_btn.setToolTip(tr("Blende/Abbildung → Schärfentiefe, Schrittweite und benötigte "
                                   "Bildanzahl für volle Schärfe (Shooting-Assistent)."))
        self.dof_btn.clicked.connect(self.open_dof)
        tools.addWidget(self.analyze_btn); tools.addWidget(self.dof_btn)
        sg.addLayout(tools, 6, 0, 1, 3)
        self.g_sel = g_sel; p2.addWidget(g_sel)

        # Ausrichtung
        g_ab = QGroupBox(tr("Ausrichtung"))
        ag = QGridLayout(g_ab)
        self.align_on = QCheckBox("Fotos ausrichten"); self.align_on.setChecked(True)
        self.transform = QComboBox(); self.transform.addItems(["rigid", "homography"])
        self.detector = QComboBox(); self.detector.addItems(["ORB", "SIFT", "AKAZE"])
        self.align_on.toggled.connect(lambda v: (self.transform.setEnabled(v), self.detector.setEnabled(v)))
        ag.addWidget(self.align_on, 0, 0, 1, 2)
        ag.addWidget(help_btn("Richtet die Fotos exakt übereinander aus (gleicht winzige "
                              "Verschiebungen aus). Sollte fast immer an sein."), 0, 2)
        ag.addWidget(QLabel("Methode"), 1, 0); ag.addWidget(self.transform, 1, 1)
        ag.addWidget(help_btn("„rigid“ für Stativ/ruhige Aufnahmen, „homography“ wenn freihand "
                              "fotografiert wurde (gleicht auch Perspektive aus)."), 1, 2)
        ag.addWidget(QLabel("Erkennung"), 2, 0); ag.addWidget(self.detector, 2, 1)
        ag.addWidget(help_btn("Wie markante Punkte zum Ausrichten gefunden werden. ORB = schnell "
                              "(Standard), SIFT = genauer bei texturarmen Motiven, aber langsamer."), 2, 2)
        self.g_ab = g_ab; p2.addWidget(g_ab)

        # Zusammenrechnen + Ergebnis-Optionen
        g_stk = QGroupBox(tr("Zusammenrechnen & Ergebnis"))
        kg = QGridLayout(g_stk)
        self.sharpen = QDoubleSpinBox(); self.sharpen.setRange(0, 100); self.sharpen.setValue(0)
        self.sharpen.setSuffix(" %")
        self.denoise = QDoubleSpinBox(); self.denoise.setRange(0, 100); self.denoise.setValue(0)
        self.reverse = QCheckBox("Reihenfolge umkehren (Sweep hinten→vorne)")
        self.multilayer = QCheckBox("Ebenen-Datei zum Nachbearbeiten erzeugen")
        self.webjpg = QCheckBox("Zusätzlich ein JPG zum Teilen speichern")
        self.ai_enhance = QCheckBox("KI-Feinschliff (Schärfen/Klarheit/Entrauschen, treu)")
        self.ghost_map = QCheckBox("Geister-Karte erzeugen (zeigt Bewegungszonen)")
        self.deghost = QCheckBox("Deghost (Bewegungszonen entdoppeln)")
        self.prefix = QLineEdit("stack_")
        self.nostack = QCheckBox("Nur Auswahl (nicht zusammenrechnen)")
        kg.addWidget(QLabel("Nachschärfen"), 0, 0); kg.addWidget(self.sharpen, 0, 1)
        kg.addWidget(help_btn("Schärft das fertige Bild leicht nach (in %). 0 = aus. Makro oft 10–25 %."), 0, 2)
        kg.addWidget(QLabel("Rauschreduktion"), 1, 0); kg.addWidget(self.denoise, 1, 1)
        kg.addWidget(help_btn("Reduziert Bildrauschen im Ergebnis (kantenerhaltend). 0 = aus."), 1, 2)
        kg.addWidget(self.reverse, 2, 0, 1, 2)
        kg.addWidget(help_btn("Falls du die Schärfereihe von hinten nach vorne fotografiert hast."), 2, 2)
        kg.addWidget(self.multilayer, 3, 0, 1, 2)
        kg.addWidget(help_btn("Erzeugt eine Datei mit dem fertigen Bild + allen Einzelfotos als "
                              "Ebenen — Basis für den Retusche-Editor."), 3, 2)
        kg.addWidget(self.webjpg, 4, 0, 1, 2)
        kg.addWidget(help_btn("Speichert zusätzlich ein normales JPG zum Teilen/Verschicken."), 4, 2)
        kg.addWidget(self.ai_enhance, 5, 0, 1, 2)
        kg.addWidget(help_btn("Die Bild-KI empfiehlt schonende Werte für Schärfen/Klarheit/Entrauschen; "
                              "angewendet mit klassischen Filtern — keine Inhalte erfunden. Ohne "
                              "KI-Server wird ein fester, dezenter Standard genutzt."), 5, 2)
        kg.addWidget(self.ghost_map, 6, 0, 1, 2)
        kg.addWidget(help_btn("Erzeugt eine Karte (ghostmap.jpg), die rot zeigt, wo sich die Fotos "
                              "stark widersprechen — also wo Bewegung/Ghosting wahrscheinlich ist."), 6, 2)
        kg.addWidget(self.deghost, 7, 0, 1, 2)
        kg.addWidget(help_btn("In stark uneinigen Zonen wird der Median der Fotos genommen statt zu "
                              "mischen — reduziert Doppelkonturen bei Bewegung. Rest per Retusche."), 7, 2)
        kg.addWidget(QLabel("Datei-Name-Vorsatz"), 8, 0); kg.addWidget(self.prefix, 8, 1)
        kg.addWidget(help_btn("Vorsatz für den Dateinamen des Ergebnisses."), 8, 2)
        kg.addWidget(self.nostack, 9, 0, 1, 2)
        kg.addWidget(help_btn("Nur Fotos auswählen, noch nicht verrechnen — zum Prüfen der Auswahl."), 9, 2)
        self.g_stk = g_stk; p3.addWidget(g_stk)

        # Export für (zusätzliche, passend skalierte+geschärfte JPGs)
        g_exp = QGroupBox(tr("Export für (zusätzliche JPGs)"))
        xg = QGridLayout(g_exp)
        self.exp_targets = {}
        for col, (key, lbl) in enumerate([("instagram", "Instagram"), ("whatsapp", "WhatsApp"),
                                          ("web", "Web"), ("4k", "4K"), ("print", "Druck")]):
            cb = QCheckBox(lbl); self.exp_targets[key] = cb
            xg.addWidget(cb, col // 3, col % 3)
        xg.addWidget(help_btn("Erzeugt neben dem Hauptbild zusätzlich passend verkleinerte und "
                              "für die Plattform geschärfte JPGs (Instagram 1080px, WhatsApp 1600px, "
                              "Web 2048px, 4K 3840px, Druck = volle Größe)."), 1, 2)
        self.g_exp = g_exp; p3.addWidget(g_exp)

        # KI (optional)
        g_vlm = QGroupBox(tr("KI (optional)"))
        g_vlm.setCheckable(True); g_vlm.setChecked(False)
        self.vlm_group = g_vlm
        vg = QVBoxLayout(g_vlm)
        note = QLabel("Ohne KI läuft alles per Heuristik (überall lauffähig). Optional eine "
                      "Bild-KI zuschalten — lokal/Server oder ein Anbieter mit API-Schlüssel.")
        note.setWordWrap(True); note.setStyleSheet("color:#9aa09a;")
        vg.addWidget(note)
        self.vlm_provider = QComboBox()
        # (Anzeige, Endpoint, Modell-Vorschlag, braucht_key)
        self._providers = {
            "Lokal / eigener Server": ("http://localhost:8000/v1", "", False),
            "OpenAI (API-Key)": ("https://api.openai.com/v1", "gpt-4o-mini", True),
            "OpenRouter (API-Key)": ("https://openrouter.ai/api/v1", "google/gemini-2.0-flash-exp", True),
            "Eigene Adresse": ("", "", False),
        }
        self.vlm_provider.addItems(list(self._providers.keys()))
        self.vlm_provider.currentTextChanged.connect(self._on_provider)
        vg.addLayout(_row("Anbieter", self.vlm_provider,
                          "Schnellwahl: lokaler/eigener Server, OpenAI oder OpenRouter "
                          "(beide brauchen einen API-Schlüssel), oder eigene Adresse."))
        self.vlm_ep = QLineEdit("http://localhost:8000/v1")
        self.vlm_model = QLineEdit("")
        self.vlm_key = QLineEdit(); self.vlm_key.setEchoMode(QLineEdit.Password)
        self.vlm_key.setPlaceholderText("nur bei OpenAI/OpenRouter nötig")
        vg.addLayout(_row("Adresse (Endpoint)", self.vlm_ep,
                          "OpenAI-kompatibler Endpoint, endet meist auf /v1."))
        vg.addLayout(_row("Modell", self.vlm_model,
                          "Name des Bild-Modells (z.B. gpt-4o-mini oder das lokale Modell)."))
        vg.addLayout(_row("API-Schlüssel", self.vlm_key,
                          "Geheimer Schlüssel des Anbieters. Bleibt lokal gespeichert. "
                          "Hinweis: das ChatGPT-Abo ist KEIN API-Schlüssel."))
        self.vlm_wish = QLineEdit()
        self.vlm_wish.setPlaceholderText(tr("z. B. „seidiges Wasser, Personen scharf"))
        vg.addLayout(_row(tr("Wunsch (optional)"), self.vlm_wish,
                          tr("Freitext an die KI. Wird beim KI-Vorschlag wörtlich berücksichtigt.")))
        # Transparenz: was geht an die KI?
        _note = QLabel(tr("An die KI gehen nur: einige Vorschau-Frames, das Schärfeprofil, "
                          "EXIF-Eckdaten und dein Wunsch. Keine Originaldateien, keine Standortdaten."))
        _note.setWordWrap(True); _note.setStyleSheet("color:#9aa09a;font-size:11px;")
        vg.addWidget(_note)
        self.suggest_btn = QPushButton(tr("🤖  KI schlägt Settings vor"))
        self.suggest_btn.setToolTip("Analysiert eine Auswahl der Frames + das Schärfeprofil "
                                    "und schlägt Einstellungen vor (braucht KI-Server).")
        self.suggest_btn.clicked.connect(self.suggest)
        p3.addWidget(self.suggest_btn)

        # KI-Konfiguration ins Setup-Menü (statt eigenes Fenster / Wizard-Schritt)
        self._settings_lay.addWidget(g_vlm)
        self._settings_lay.addStretch(1)
        _ok = QPushButton("OK"); _ok.clicked.connect(self.settings_dialog.accept)
        self._settings_lay.addWidget(_ok)

        for pl in self._wiz_lay:
            pl.addStretch(1)

        # Navigation zwischen den Schritten
        nav = QHBoxLayout()
        self.back_btn = QPushButton(tr("◀ Zurück")); self.back_btn.clicked.connect(lambda: self._go_step(-1))
        self.next_btn = QPushButton(tr("Weiter ▶")); self.next_btn.clicked.connect(lambda: self._go_step(1))
        nav.addWidget(self.back_btn); nav.addWidget(self.next_btn)
        lv.addLayout(nav)

        # Aktions-Fußzeile (immer sichtbar)
        btns = QHBoxLayout()
        self.run_btn = QPushButton(tr("▶  Starten"))
        self.run_btn.clicked.connect(lambda: self.run(auto=False))
        self.stop_btn = QPushButton(tr("■  Stop")); self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        btns.addWidget(self.run_btn); btns.addWidget(self.stop_btn)
        lv.addLayout(btns)

        split.addWidget(left)

        # ---- MITTE: großes Bild + Ansicht-Umschalter + Aktionen ----
        center = QWidget()
        rv = QVBoxLayout(center)
        # Umschalter: Ergebnis · Fokus-Map · Geister-Karte
        vbar = QHBoxLayout(); vbar.setSpacing(6)
        self.view_result = QPushButton(tr("Ergebnis")); self.view_focusmap = QPushButton(tr("Fokus-Map"))
        self.view_ghost = QPushButton(tr("Geister-Karte"))
        for b, m in ((self.view_result, "result"), (self.view_focusmap, "focusmap"), (self.view_ghost, "ghost")):
            b.setCheckable(True); b.setEnabled(False)
            b.clicked.connect(lambda _=False, mode=m: self._set_view(mode))
            vbar.addWidget(b)
        self.view_result.setChecked(True); vbar.addStretch(1)
        rv.addLayout(vbar)
        self._preview_empty = ("<div style='font-size:64px'>📂</div>"
                               "<div style='font-size:16px;color:#cfd2cd;margin-top:8px'>"
                               + tr("Ordner hierher ziehen") + "</div>"
                               "<div style='font-size:12px;color:#8a8f88;margin-top:4px'>"
                               + tr("oder oben „Wählen…“ – dann ⚡ Automatik") + "</div>")
        self.preview = QLabel(self._preview_empty)
        self.preview.setTextFormat(Qt.RichText)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(320)
        self.preview.setStyleSheet("color:#8a8f88;border:2px dashed #34383f;border-radius:12px;")
        rv.addWidget(self.preview, 6)
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.hide()
        rv.addWidget(self.progress)
        res_btns = QHBoxLayout(); res_btns.setSpacing(8)
        # Primäre Aktionen als Buttons, alles Weitere im „Werkzeuge"-Menü (entrümpelt)
        self.cmp_btn = QPushButton(tr("🔍  Vorher/Nachher"))
        self.cmp_btn.setToolTip("Schieberegler: schärfstes Einzelfoto gegen das fertige Bild vergleichen.")
        self.cmp_btn.setEnabled(False); self.cmp_btn.clicked.connect(self.open_compare)
        self.adjust_btn = QPushButton(tr("🎚️  Bearbeiten"))
        self.adjust_btn.setToolTip("Camera-Raw: Belichtung, Kontrast, Weißabgleich, Klarheit, "
                                   "Farbe — mit Live-Vorschau und Histogramm.")
        self.adjust_btn.setEnabled(False); self.adjust_btn.clicked.connect(self.open_adjust)
        self.export_btn = QPushButton(tr("📦  Export"))
        self.export_btn.setToolTip(tr("Exportieren: Ziele, Schärfung, Photoshop-Ebenen, 16-bit (⌘E)."))
        self.export_btn.setEnabled(False); self.export_btn.clicked.connect(self.export_result)

        self.tools_btn = QToolButton()
        self.tools_btn.setText(tr("🛠  Werkzeuge  ▾")); self.tools_btn.setPopupMode(QToolButton.InstantPopup)
        self.tools_btn.setEnabled(False)
        menu = QMenu(self.tools_btn)

        def _act(text, fn):
            a = QAction(text, self); a.triggered.connect(fn); a.setEnabled(False)
            menu.addAction(a); return a
        self.openfolder_btn = _act(tr("📁  Ausgabe-Ordner"), self.open_folder)
        self.open_btn = _act(tr("Im Finder anzeigen"), self.open_result)
        self.ghost_btn = _act(tr("👻  Geister-Karte"), self.open_ghostmap)
        self.retouch_btn = _act(tr("✏️  Retusche"), self.open_retouch)
        self._astro_menu_sep = menu.addSeparator()
        self.graxpert_btn = _act(tr("🌌  GraXpert (Gradient)"), lambda: self._run_external_tool("graxpert"))
        self.starnet_btn = _act(tr("⭐  StarNet (starless)"), lambda: self._run_external_tool("starnet"))
        self.reimport_btn = _act(tr("📥  Bearbeitetes reimportieren"), self.reimport_result)
        self.send_btn = _act(tr("📤  Im Dateimanager zeigen"), self.send_to_tool)
        self.tools_btn.setMenu(menu)

        for b in (self.cmp_btn, self.adjust_btn, self.export_btn, self.tools_btn):
            res_btns.addWidget(b)
        res_btns.addStretch(1)
        rv.addLayout(res_btns)

        # Filmstreifen: alle Fotos mit Schärfe-Wert, behalten/verworfen (unter dem Bild)
        self.strip_label = QLabel("Bilder (grün = verwendet, rot = aussortiert):")
        self.strip_label.hide()
        rv.addWidget(self.strip_label)
        self.strip_scroll = QScrollArea()
        self.strip_scroll.setWidgetResizable(True)
        self.strip_scroll.setFixedHeight(132)
        self.strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.strip_host = QWidget()
        self.strip_lay = QHBoxLayout(self.strip_host)
        self.strip_lay.setAlignment(Qt.AlignLeft)
        self.strip_scroll.setWidget(self.strip_host)
        self.strip_scroll.hide()
        rv.addWidget(self.strip_scroll)

        # ---- RECHTS: Entscheidungs-Panel (Score/„Warum") + Log ----
        rightcol = QWidget()
        rc = QVBoxLayout(rightcol)
        rc.addWidget(QLabel(tr("Analyse & Ergebnis")))
        self.decision = QLabel(tr("Noch kein Ergebnis.\nWähle einen Ordner und starte die Automatik."))
        self.decision.setWordWrap(True); self.decision.setTextFormat(Qt.RichText)
        self.decision.setAlignment(Qt.AlignTop)
        self.decision.setStyleSheet("background:#1c1b22;border:1px solid #2a2836;border-radius:10px;"
                                    "padding:12px;color:#cfd2cd;")
        self.decision.linkActivated.connect(self._panel_link)
        dsc = QScrollArea(); dsc.setWidgetResizable(True); dsc.setWidget(self.decision)
        dsc.setFrameShape(QFrame.NoFrame)
        rc.addWidget(dsc, 3)

        # Schnell-Export: Ein-Klick-Presets direkt neben dem Ergebnis
        rc.addWidget(QLabel(tr("Schnell-Export")))
        chips = QWidget(); chl = QHBoxLayout(chips); chl.setContentsMargins(0, 0, 0, 0); chl.setSpacing(6)
        self.export_chips = []
        for key, lbl in [("instagram", "📷 Instagram"), ("web", "🌐 Web"),
                         ("print", "🖨 " + tr("Druck"))]:
            b = QPushButton(lbl); b.setObjectName("chip")
            b.setToolTip(tr("Ergebnis sofort in dieses Format exportieren (ohne Dialog)."))
            b.clicked.connect(lambda _=False, k=key: self._quick_export(k))
            b.setEnabled(False); chl.addWidget(b); self.export_chips.append(b)
        chl.addStretch(1)
        rc.addWidget(chips)

        rc.addWidget(QLabel(tr("Log")))
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont("Menlo", 10))
        self.log.setMaximumBlockCount(5000)
        rc.addWidget(self.log, 2)

        split.addWidget(center)
        split.addWidget(rightcol)
        split.setSizes([430, 720, 320])   # Einstellungen · Bild · Entscheidung
        split.setStretchFactor(1, 1)

        self.result_path = None
        self.before_path = None
        self._restore_settings()
        self._set_step(0)
        self._set_task()
        self._setup_shortcuts()
        # Dropdowns an Textlänge anpassen (gegen abgeschnittene Texte, auch bei EN)
        for cb in self.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        for cb in self.settings_dialog.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._maybe_check_updates()

    def _maybe_check_updates(self):
        """Beim Start einmal leise auf eine neuere Version prüfen (wenn nicht abgeschaltet)."""
        if QSettings("ServeOne", "ForgePix").value("check_updates", "1") == "0":
            return
        self._updchk = _UpdateChecker()
        self._updchk.found.connect(self._on_update_found)
        self._updchk.start()

    def _on_update_found(self, latest, url):
        from constants import VERSION
        if not _version_newer(latest, VERSION):
            return
        self.update_lbl.setText(
            f"⬆ {tr('Neue Version verfügbar')}: <b>{latest}</b> "
            f"<a href='{url}' style='color:#bdf0bd'>{tr('herunterladen')}</a>")
        self.update_lbl.setVisible(True)

    def _on_language(self, _i):
        code = self._lang_codes[self.lang_box.currentIndex()]
        QSettings("ServeOne", "ForgePix").setValue("language", code)
        QMessageBox.information(self, tr("Sprache:"),
                                "Die Sprache wird beim nächsten Start angewendet.\n"
                                "Language will be applied on next start.")

    def _apply_preset(self, i):
        """Makro-Vorlage anwenden (Produkte/Münzen/Food)."""
        if not hasattr(self, "dip"):
            return  # UI noch im Aufbau
        presets = {
            0: dict(dip=0.40, absmin=15, sharpen=0, transform="rigid", detector="ORB"),
            1: dict(dip=0.40, absmin=15, sharpen=15, transform="rigid", detector="ORB",
                    multilayer=True, webjpg=True),                       # Produkte
            2: dict(dip=0.45, absmin=18, sharpen=22, transform="rigid", detector="SIFT"),  # Münzen
            3: dict(dip=0.40, absmin=12, sharpen=12, transform="homography", detector="ORB",
                    webjpg=True),                                        # Food
        }
        p = presets.get(i, {})
        if "dip" in p: self.dip.setValue(p["dip"])
        if "absmin" in p: self.absmin.setValue(p["absmin"])
        if "sharpen" in p: self.sharpen.setValue(p["sharpen"])
        for key, combo in (("transform", self.transform), ("detector", self.detector)):
            if key in p:
                j = combo.findText(p[key])
                if j >= 0:
                    combo.setCurrentIndex(j)
        if "multilayer" in p: self.multilayer.setChecked(p["multilayer"])
        if "webjpg" in p: self.webjpg.setChecked(p["webjpg"])

    def _suggest_longexp(self):
        """Bewegungsanalyse der Serie → passenden Langzeit-Effekt vorschlagen (klassisch, kein Server)."""
        folder = self.in_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, tr("Effekt vorschlagen"),
                                    tr("Bitte zuerst einen Eingabe-Ordner mit der Serie wählen."))
            return
        try:
            import longexp
            import focus_cull_stack as F
            paths = F.list_images(folder)
            if len(paths) < 2:
                QMessageBox.information(self, tr("Effekt vorschlagen"),
                                        tr("Mindestens 2 Aufnahmen nötig."))
                return
            sug = longexp.suggest_mode(paths)
            i = self.longexp_mode.findData(sug["mode"])
            if i >= 0:
                self.longexp_mode.setCurrentIndex(i)
            QMessageBox.information(self, tr("Vorschlag"), sug["rationale"])
        except Exception as e:
            QMessageBox.warning(self, tr("Effekt vorschlagen"), f"{e}")

    # ---------- Tastatursteuerung ----------
    # Hinweis: Qt bildet "Ctrl+…" auf macOS automatisch auf ⌘ ab.
    SHORTCUTS = [
        ("Leertaste", "Vorher / Nachher"),
        ("← →", "Bild im Filmstreifen wechseln"),
        ("A", "Reihe analysieren"),
        ("S", "Stack / Automatik starten"),
        ("E", "Editor (Camera-Raw)"),
        ("G", "Geister-Karte"),
        ("F", "Fokus-Map"),
        ("R", "Retusche"),
        ("—", "—"),
        ("Ctrl+O", "Eingabe-Ordner wählen"),
        ("Ctrl+Return", "Automatik starten (beste Qualität)"),
        ("Ctrl+Shift+Return", "Manuell starten (Profi)"),
        ("Ctrl+E", "Exportieren"),
        ("Esc", "Stop / zurück zur Modul-Auswahl"),
        ("Ctrl+1 … Ctrl+4", "Modul: Makro / Astro / Hybrid / Langzeit"),
        ("Ctrl+B", "Anfänger ⟷ Profi umschalten"),
        ("Ctrl+M", "Zur Modul-Auswahl"),
        ("Ctrl+,", "Setup-Menü"),
        ("Ctrl+] / Ctrl+[", "Wizard: weiter / zurück"),
        ("F1 / Ctrl+/", "Diese Tastenkürzel anzeigen"),
    ]

    def _setup_shortcuts(self):
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)
            return s
        sc("Ctrl+O", self.pick_input)
        sc("Ctrl+Return", lambda: self.run(auto=True))
        sc("Ctrl+Enter", lambda: self.run(auto=True))
        sc("Ctrl+Shift+Return", lambda: self.run(auto=False) if self.mode_box.currentIndex() == 1 else None)
        sc("Ctrl+,", self.settings_dialog.show)
        sc("Ctrl+B", lambda: self.mode_box.setCurrentIndex(1 - self.mode_box.currentIndex()))
        sc("Ctrl+M", lambda: self.top_stack.setCurrentIndex(0))
        sc("Ctrl+E", self.export_result)
        sc("Ctrl+Shift+A", lambda: self.analyze_series() if not self.is_astro and not self.is_hybrid
           and not self.is_longexp else None)
        sc("Ctrl+D", self.open_dof)
        sc("Ctrl+]", lambda: self._go_step(1))
        sc("Ctrl+[", lambda: self._go_step(-1))
        sc("F1", self._show_shortcuts)
        sc("Ctrl+/", self._show_shortcuts)
        for n in range(4):
            sc(f"Ctrl+{n + 1}", lambda i=n: self._choose_module(i))
        sc("Esc", self._on_escape)

    def _on_escape(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.stop()
        elif self.top_stack.currentIndex() == 1:
            self.top_stack.setCurrentIndex(0)

    def _show_shortcuts(self):
        def disp(k):
            if sys.platform == "darwin":
                for a, b in (("Ctrl", "⌘"), ("Shift", "⇧"), ("Return", "⏎"),
                             ("Enter", "⏎"), ("Esc", "⎋")):
                    k = k.replace(a, b)
            return k
        rows = "".join(f"<tr><td style='padding:3px 14px 3px 0;color:#7bd36a;'><b>{disp(k)}</b></td>"
                       f"<td style='padding:3px 0;'>{tr(v)}</td></tr>" for k, v in self.SHORTCUTS)
        dlg = QDialog(self); dlg.setWindowTitle(tr("Tastenkürzel")); dlg.resize(420, 440)
        lay = QVBoxLayout(dlg)
        lbl = QLabel(f"<h3>{tr('Tastenkürzel')}</h3><table>{rows}</table>")
        lbl.setTextFormat(Qt.RichText)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(lbl)
        lay.addWidget(sc)
        b = QPushButton(tr("Schließen")); b.clicked.connect(dlg.accept); lay.addWidget(b)
        dlg.show(); self._sc_dlg = dlg

    def _set_task(self):
        i = self.task_box.currentIndex()
        self.is_astro = i == 1     # 1 = Astro
        self.is_hybrid = i == 2    # 2 = Hybrid (Mosaik / Fokus+Astro)
        self.is_longexp = i == 3   # 3 = Langzeitbelichtung
        self.astro_group.setChecked(self.is_astro)
        self._apply_visibility()

    def _hybrid_kind_changed(self):
        fa = self.hybrid_kind.currentData() == "fa"
        self.mos_row.setVisible(not fa); self.mosaic_mode.setVisible(not fa)
        self.fa_row.setVisible(fa); self.hybrid_group.setVisible(fa)
        if getattr(self, "is_hybrid", False):
            self.auto_btn.setText(tr("🌃  Fokus+Astro stacken") if fa
                                  else tr("🌗  Mosaik erstellen"))

    def _apply_visibility(self):
        """Eine zentrale Stelle: zeigt nur, was zu Modus (Anfänger/Profi) UND
        Aufgabe (Makro/Astro) passt. Das jeweils andere ist komplett ausgeblendet."""
        pro = self.mode_box.currentIndex() == 1  # 1 = Profi
        astro = getattr(self, "is_astro", False)
        hybrid = getattr(self, "is_hybrid", False)
        longexp = getattr(self, "is_longexp", False)
        makro = not astro and not hybrid and not longexp
        self._set_step(0)
        self.astro_group.setVisible(astro)
        self.mosaic_group.setVisible(hybrid)
        self.longexp_group.setVisible(longexp)
        self.preset_group.setVisible(makro)
        for g in (self.g_sel, self.g_ab, self.g_stk, self.g_exp):
            g.setVisible(makro)
        self.g_raw.setVisible(pro and makro)
        # Batch/Watch: Makro, Astro, Langzeit (je Unterordner eine Serie). Nicht Hybrid
        # (Mosaik nutzt alle Kacheln; Fokus+Astro nutzt Unterordner als Positionen).
        self.adv_folder.setVisible(pro and (makro or astro or longexp))
        # KI-Konfiguration liegt im Setup-Menü. Navigation nur im Profi-Makro-Fluss.
        nav = pro and makro
        for wdg in (self.crumb, self.back_btn, self.next_btn):
            wdg.setVisible(nav)
        self.suggest_btn.setVisible(nav)  # KI-Vorschlag nur im Profi-Makro-Fluss
        self.run_btn.setVisible(pro)
        if not pro:
            self.auto_btn.setText(tr("⚡  Loslegen — Ordner wählen, dann Automatik"))
        elif astro:
            self.auto_btn.setText(tr("🌌  Astro stacken"))
        elif hybrid:
            self._hybrid_kind_changed()
        elif longexp:
            self.auto_btn.setText(tr("📷  Langzeitbelichtung rechnen"))
        else:
            self.auto_btn.setText(tr("⚡  Automatik — beste Qualität (ein Klick)"))

    # ---------- Wizard-Schritte ----------
    def _set_step(self, i):
        i = max(0, min(self.wizard.count() - 1, i))
        self.wizard.setCurrentIndex(i)
        self.crumb.setText(tr("Schritt ") + self.STEP_NAMES[i])
        self.back_btn.setEnabled(i > 0)
        self.next_btn.setEnabled(i < self.wizard.count() - 1)

    def _go_step(self, delta):
        self._set_step(self.wizard.currentIndex() + delta)

    # ---------- Drag & Drop ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(os.path.isdir(u.toLocalFile()) or
                                          os.path.isfile(u.toLocalFile())
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        """Ordner (oder Datei → deren Ordner) fallen lassen → übernehmen und, im Makro,
        direkt die Reihen-Analyse starten."""
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            folder = p if os.path.isdir(p) else (os.path.dirname(p) if os.path.isfile(p) else None)
            if folder:
                # Modul-Auswahl offen? -> in den Arbeitsbereich wechseln + Modul erraten
                from_welcome = self.top_stack.currentIndex() == 0
                if from_welcome:
                    self.top_stack.setCurrentIndex(1)
                self.in_edit.setText(folder)
                self._append(f"📂 Ordner per Drag&Drop: {folder}\n")
                # Modul nur raten, wenn der Nutzer noch keins bewusst gewählt hat (Drop von der Auswahl)
                if from_welcome:
                    self._guess_and_apply_module(folder)
                self._set_status(tr("Ordner geladen: ") + os.path.basename(folder), color="#58a6ff", bg="#14202e")
                if self.mode_box.currentIndex() == 0:
                    # Null-Klick (Anfänger): direkt die Automatik starten — „rein → fertig"
                    self._append(tr("⚡ Anfänger-Modus: starte Automatik …") + "\n")
                    QTimer.singleShot(200, lambda: self.run(auto=True))
                else:
                    makro = not (getattr(self, "is_astro", False) or getattr(self, "is_hybrid", False)
                                 or getattr(self, "is_longexp", False))
                    if makro:  # Profi-Makro: gleich Reihen-Analyse
                        self.analyze_series()
                break

    def _guess_and_apply_module(self, folder):
        """Wahrscheinlichstes Modul aus dem Ordner raten und vorwählen (Einsteiger sparen die Wahl)."""
        try:
            from focus_analysis import guess_module
            key, reason = guess_module(folder)
        except Exception:
            return
        idx = {"makro": 0, "astro": 1, "hybrid": 2, "longexp": 3}.get(key, 0)
        if idx != self.task_box.currentIndex():
            self.task_box.setCurrentIndex(idx)
            self._set_task()
        label = self.task_box.currentText()
        self._append(f"🔎 {tr('Erkannt')}: {label} — {reason}\n")
        self._set_status(f"{tr('Erkannt')}: {label}", color="#7bd36a", bg="#1b2a1b")

    # ---------- Ordnerauswahl ----------
    def pick_input(self):
        d = QFileDialog.getExistingDirectory(self, "Eingabe-Ordner wählen", self.in_edit.text() or os.path.expanduser("~"))
        if d:
            self.in_edit.setText(d)
            self._set_status(tr("Ordner geladen: ") + os.path.basename(d), color="#58a6ff", bg="#14202e")

    def pick_work(self):
        d = QFileDialog.getExistingDirectory(self, "Arbeits-Ordner wählen", self.work_edit.text() or os.path.expanduser("~"))
        if d:
            self.work_edit.setText(d)

    def _pick_into(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Ordner wählen", edit.text() or os.path.expanduser("~"))
        if d:
            edit.setText(d)

    def _pick_file_into(self, edit):
        f, _ = QFileDialog.getOpenFileName(self, "Datei wählen", edit.text() or os.path.expanduser("~"))
        if f:
            edit.setText(f)

    def _on_provider(self, name):
        ep, model, _needs = self._providers.get(name, ("", "", False))
        if name != "Eigene Adresse":
            self.vlm_ep.setText(ep)
            self.vlm_model.setText(model)

    # ---------- Lauf ----------
    def _work_dir(self):
        w = self.work_edit.text().strip()
        if w:
            return os.path.abspath(w)
        inp = os.path.abspath(self.in_edit.text().strip())
        return os.path.join(os.path.dirname(inp), "stack_work")

    def _common_args(self, inp):
        """Eingabe/Arbeit, RAW-Entwicklung, Watch, VLM-Verbindung — für beide Modi."""
        args = [SCRIPT, "--input", os.path.abspath(inp), "--max-side", str(self.maxside.value())]
        if self.work_edit.text().strip():
            args += ["--work", os.path.abspath(self.work_edit.text().strip())]
        if self.raw_dev.isChecked():
            args += ["--raw-wb", self.raw_wb.currentText(), "--raw-bps", self.raw_bps.currentText()]
            if self.raw_auto_bright.isChecked():
                args += ["--raw-auto-bright"]
            if self.raw_half.isChecked():
                args += ["--raw-half"]
        else:
            args += ["--no-raw-develop"]
        if self.batch.isChecked():
            args += ["--batch"]
        if self.watch.isChecked():
            args += ["--watch", "--watch-settle", str(self.watch_settle.value())]
        if self.vlm_group.isChecked() and self.vlm_ep.text().strip():
            args += ["--vlm-endpoint", self.vlm_ep.text().strip(),
                     "--vlm-model", self.vlm_model.text().strip() or "gpt-4o-mini"]
            if self.vlm_key.text().strip():
                args += ["--vlm-key", self.vlm_key.text().strip()]
            if self.vlm_wish.text().strip():
                args += ["--wish", self.vlm_wish.text().strip()]
        chosen = [k for k, cb in self.exp_targets.items() if cb.isChecked()]
        if chosen:
            args += ["--export", ",".join(chosen)]
        if self.astro_group.isChecked():
            args += ["--astro", "--astro-method", self.astro_method.currentText(),
                     "--astro-kappa", str(self.astro_kappa.value())]
            if not self.astro_register.isChecked():
                args += ["--no-register"]
            if not self.astro_qc.isChecked():
                args += ["--no-astro-qc"]
            if self.astro_stretch.isChecked():
                args += ["--astro-stretch"]
            if self.astro_bg.isChecked():
                args += ["--bg-extract"]
            if self.astro_fits.isChecked():
                args += ["--fits-out"]
            args += ["--astro-align", self.astro_align.currentData()]
            if self.astro_cosmetic.isChecked():
                args += ["--astro-cosmetic"]
            if self.astro_drizzle.currentData() and int(self.astro_drizzle.currentData()) > 1:
                args += ["--astro-drizzle", str(self.astro_drizzle.currentData())]
            if self.astro_dark.text().strip():
                args += ["--dark", self.astro_dark.text().strip()]
            if self.astro_flat.text().strip():
                args += ["--flat", self.astro_flat.text().strip()]
            if self.astro_bias.text().strip():
                args += ["--bias", self.astro_bias.text().strip()]
            args += ["--astro-engine", self.astro_engine.currentData() or "own"]
            if self.siril_path.text().strip():
                args += ["--siril-path", self.siril_path.text().strip()]
        if getattr(self, "is_hybrid", False):
            if self.hybrid_kind.currentData() == "fa":
                args += ["--hybrid-fa", "--hybrid-group", str(self.hybrid_group.value()),
                         "--astro-method", self.astro_method.currentText(),
                         "--astro-kappa", str(self.astro_kappa.value())]
                if not self.astro_register.isChecked():
                    args += ["--no-register"]
            else:
                args += ["--mosaic", "--mosaic-mode", self.mosaic_mode.currentText()]
        if getattr(self, "is_longexp", False):
            args += ["--longexp",
                     "--longexp-mode", self.longexp_mode.currentData(),
                     "--longexp-align", self.longexp_align.currentData(),
                     "--longexp-strength", str(self.longexp_strength.value())]
        return args

    def _build_args(self, auto):
        inp = self.in_edit.text().strip()
        args = self._common_args(inp)
        if auto:
            return args + ["--auto"]
        # manueller Modus: alle Regler übernehmen
        args += ["--dip-ratio", str(self.dip.value()),
                 "--abs-min", str(self.absmin.value()),
                 "--prefix", self.prefix.text() or "stack_",
                 "--transform", self.transform.currentText(),
                 "--detector", self.detector.currentText(),
                 "--sharpen", str(self.sharpen.value()),
                 "--denoise", str(self.denoise.value())]
        if not self.align_on.isChecked():
            args += ["--no-align"]
        if self.reverse.isChecked():
            args += ["--reverse"]
        if self.multilayer.isChecked():
            args += ["--multilayer"]
        if self.webjpg.isChecked():
            args += ["--web-jpg"]
        if self.ai_enhance.isChecked():
            args += ["--ai-enhance"]
        if self.ghost_map.isChecked():
            args += ["--ghost-map"]
        if self.deghost.isChecked():
            args += ["--deghost"]
        if self.dedup.isChecked():
            args += ["--dedup", "--dup-thresh", str(self.dupthresh.value())]
        if self.reject_blurry.isChecked():
            args += ["--reject-blurry", "--blurry-rel", str(self.blurry_rel.value())]
        if self.nostack.isChecked():
            args += ["--no-stack"]
        if self.vlm_group.isChecked() and self.vlm_ep.text().strip():
            args += ["--vlm-qc"]  # manueller Wind/Bewegungs-QC
        return args

    def _start_pipeline(self, proc, args):
        """Pipeline-Subprozess starten — im gebündelten Binary (PyInstaller) über den
        `--cli`-Einstiegspunkt des Binaries selbst, sonst `python -u focus_cull_stack.py`."""
        if getattr(sys, "frozen", False):
            proc.start(sys.executable, ["--cli"] + args[1:])   # args[0] = SCRIPT-Pfad weglassen
        else:
            proc.start(sys.executable, ["-u"] + args)

    def run(self, auto=False):
        # Doppelstart verhindern (Tastenkürzel umgehen die deaktivierten Buttons)
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self._append("\n(Ein Lauf läuft bereits — bitte warten oder Stop.)\n")
            return
        inp = self.in_edit.text().strip()
        if not inp or not os.path.isdir(inp):
            QMessageBox.warning(self, "Fehler", "Bitte einen gültigen Eingabe-Ordner wählen.")
            return
        # Vorab-Check: genug Bilder vorhanden? (Astro/Langzeit/Mosaik brauchen ≥2)
        try:
            import focus_cull_stack as F
            n = len(F.list_images(inp))
            if n == 0:  # evtl. Batch/Hybrid mit Unterordnern
                n = sum(len(F.list_images(os.path.join(inp, d)))
                        for d in os.listdir(inp) if os.path.isdir(os.path.join(inp, d)))
            need = 1 if (getattr(self, "is_longexp", False) is False and not getattr(self, "is_astro", False)
                         and not getattr(self, "is_hybrid", False)) else 2
            if n < max(need, 1) or (need == 2 and n < 2):
                if QMessageBox.question(
                        self, tr("Wenige Bilder"),
                        tr("Im Ordner wurden nur %d Bild(er) gefunden. Trotzdem starten?") % n
                        ) != QMessageBox.Yes:
                    return
        except Exception:
            pass
        args = self._build_args(auto)
        self.log.clear()
        self.preview.setText("— läuft —"); self.preview.setPixmap(QPixmap())
        self.open_btn.setEnabled(False); self.retouch_btn.setEnabled(False)
        self.cmp_btn.setEnabled(False); self.openfolder_btn.setEnabled(False)
        self.export_btn.setEnabled(False); self.tools_btn.setEnabled(False)
        self.result_path = None; self.before_path = None; self._last_rationale = ""
        self.progress.setRange(0, 0); self.progress.show()  # erst „beschäftigt“
        if auto:
            self._append("⚡ AUTOMATIK — die KI bestimmt alle Einstellungen, max. Qualität.\n")
        self._append(f"$ python3 {' '.join(args)}\n")

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._on_output)
        self.proc.finished.connect(self._on_finished)
        self._start_pipeline(self.proc, args)
        self.run_btn.setEnabled(False); self.auto_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self._set_status(tr("Läuft …"), color="#d4a72c", bg="#2a2510")

    def stop(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            # SIGTERM zuerst (Watch-Modus beendet sauber zwischen zwei Stacks); danach hart
            self.proc.terminate()
            if not self.proc.waitForFinished(3000):
                self.proc.kill()
            self._append("\n[abgebrochen]\n")

    # ---------- KI-Vorschlag ----------
    def suggest(self):
        inp = self.in_edit.text().strip()
        if not inp or not os.path.isdir(inp):
            QMessageBox.warning(self, "Fehler", "Bitte zuerst einen gültigen Eingabe-Ordner wählen.")
            return
        ep = self.vlm_ep.text().strip()
        if not ep:
            QMessageBox.warning(self, "Fehler", "Für den Vorschlag wird der VLM-Endpoint benötigt.")
            return
        args = [SCRIPT, "--input", os.path.abspath(inp), "--suggest",
                "--vlm-endpoint", ep, "--vlm-model", self.vlm_model.text().strip() or "gpt-4o-mini",
                "--max-side", str(self.maxside.value())]
        if self.vlm_key.text().strip():
            args += ["--vlm-key", self.vlm_key.text().strip()]
        if self.vlm_wish.text().strip():
            args += ["--wish", self.vlm_wish.text().strip()]
        self._append("\n🤖 Hole KI-Vorschlag …\n")
        self.suggest_btn.setEnabled(False); self.run_btn.setEnabled(False); self.auto_btn.setEnabled(False)
        self.sug_proc = QProcess(self)
        self.sug_proc.readyReadStandardError.connect(
            lambda: self._append(ANSI.sub("", bytes(self.sug_proc.readAllStandardError()).decode(errors="replace"))))
        self.sug_proc.finished.connect(self._on_suggest_done)
        self._start_pipeline(self.sug_proc, args)

    def _on_suggest_done(self, code, _status):
        self.suggest_btn.setEnabled(True); self.run_btn.setEnabled(True); self.auto_btn.setEnabled(True)
        out = bytes(self.sug_proc.readAllStandardOutput()).decode(errors="replace").strip()
        import json as _json
        try:
            sug = _json.loads(out)
        except Exception:
            self._append(f"\n[Vorschlag fehlgeschlagen] {out[:300]}\n")
            QMessageBox.warning(self, "Vorschlag fehlgeschlagen", out[:500] or "keine Antwort")
            return
        if "error" in sug:
            QMessageBox.warning(self, "Vorschlag fehlgeschlagen", str(sug["error"]))
            return
        self._show_suggestion(sug)

    def _show_suggestion(self, s):
        summary = (
            f"Motiv: {s.get('subject', '?')}\n"
            f"Frames: {s.get('n_frames', '?')}\n\n"
            f"Einbruch-Ratio (dip):   {s.get('dip_ratio')}\n"
            f"Struktur-Minimum:       {s.get('abs_min')}\n"
            f"Duplikat-Culling:       {'an' if s.get('dedup') else 'aus'}\n"
            f"VLM-QC:                 {'an' if s.get('vlm_qc') else 'aus'}\n\n"
            f"Transform / Detektor:   {s.get('transform')} / {s.get('detector')}\n"
            f"Nachschärfen:           {s.get('sharpen')} %\n"
            f"Reihenfolge umkehren:   {'ja' if s.get('reverse') else 'nein'}\n\n"
            f"Begründung:\n{s.get('rationale', '')}"
        )
        self._append("\n--- KI-Vorschlag ---\n" + summary + "\n")
        box = QMessageBox(self)
        box.setWindowTitle("KI-Vorschlag")
        box.setIcon(QMessageBox.Information)
        box.setText("Vorgeschlagene Einstellungen:")
        box.setInformativeText(summary)
        apply_b = box.addButton("Übernehmen", QMessageBox.AcceptRole)
        box.addButton("Verwerfen", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is apply_b:
            self._apply_suggestion(s)
            self._append("[Vorschlag übernommen]\n")

    def _apply_suggestion(self, s):
        def set_combo(combo, val):
            if val:
                i = combo.findText(str(val))
                if i >= 0:
                    combo.setCurrentIndex(i)
        try:
            if s.get("dip_ratio") is not None:
                self.dip.setValue(float(s["dip_ratio"]))
            if s.get("abs_min") is not None:
                self.absmin.setValue(float(s["abs_min"]))
            self.dedup.setChecked(bool(s.get("dedup")))
            set_combo(self.transform, s.get("transform"))
            set_combo(self.detector, s.get("detector"))
            if s.get("sharpen") is not None:
                self.sharpen.setValue(float(s["sharpen"]))
            self.reverse.setChecked(bool(s.get("reverse")))
        except (TypeError, ValueError) as e:
            QMessageBox.warning(self, "Hinweis", f"Konnte nicht alle Werte übernehmen: {e}")

    def _append(self, text):
        sb = self.log.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        self.log.insertPlainText(text)
        if at_bottom:
            sb.setValue(sb.maximum())

    # ---------- Statuszeile ----------
    def _set_status(self, text, color="#4caf50", bg="#1b2a1b"):
        self.status_lbl.setText(text)
        self.status_dot.setStyleSheet(f"color:{color};font-size:13px;")
        self.status_bar.setStyleSheet(f"QFrame{{background:{bg};border-bottom:2px solid {color};}}")

    # Schlüsselwörter aus dem Log → menschenlesbare Statusphase
    _STATUS_PHASES = [
        ("RAW-Entwicklung", "RAW entwickeln …"), ("analysieren", "Analysiere Fotos …"),
        ("Sub-Bewertung", "Subs bewerten …"), ("Verwackelt-Filter", "Aussortieren …"),
        ("Registrier", "Ausrichten …"), ("Stacking", "Stacke …"), ("Stacken", "Stacke …"),
        ("Verschmelzen", "Verschmelzen …"), ("median", "Stacke …"), ("sigma-Rejection", "Stacke …"),
        ("Hintergrund", "Hintergrund …"), ("Mosaik", "Mosaik …"), ("Langzeitbelichtung", "Langzeit …"),
        ("Stack-Konfidenz", "Qualität prüfen …"), ("Export", "Exportieren …"),
    ]

    def _on_output(self):
        raw = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        clean = ANSI.sub("", raw).replace("\r", "\n")
        self._append(clean)
        # Fortschritt aus "i/N" ableiten (letzter Treffer im Chunk)
        m = None
        for m in FRAME_RE.finditer(clean):
            pass
        if m:
            i, n = int(m.group(1)), int(m.group(2))
            if 0 < i <= n:
                self.progress.setRange(0, 100); self.progress.setValue(int(i / n * 100))
        # Statusphase aktualisieren (gelb = arbeitet)
        for key, label in self._STATUS_PHASES:
            if key in clean:
                self._set_status(tr(label), color="#d4a72c", bg="#2a2510")
        # „Warum?"-Begründung aus dem Log mitschneiden (Motiv/Begründung/Vorschlag) fürs Panel
        for line in clean.splitlines():
            s = line.strip()
            for key in ("Begründung:", "Vorschlag:", "Motiv:"):
                if key in s:
                    self._last_rationale = s.split(key, 1)[1].strip() or self._last_rationale
        if "Fertig. Ergebnis in:" in clean:  # auch im Watch-/Batch-Modus laufend aktualisieren
            self._show_result()

    def _on_finished(self, code, _status):
        self.run_btn.setEnabled(True); self.auto_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        self.progress.setRange(0, 100); self.progress.setValue(100 if code == 0 else 0)
        self._append(f"\n[fertig, exit {code}]\n")
        if code == 0:
            self._show_result()
            self._set_status(tr("Fertig ✓"), color="#4caf50", bg="#1b2a1b")
            self._notify("ForgePix", "Stack fertig 🎉" if self.result_path else "Lauf fertig")
        else:
            self._set_status(tr("Abgebrochen / Fehler"), color="#e5534b", bg="#2a1414")

    def _notify(self, title, msg):
        notify(title, msg)

    # ---------- Ergebnis ----------
    def open_compare(self):
        if not (self.result_path and self.before_path):
            return
        after = self._preview_png(self.result_path)
        before = self._preview_png(self.before_path)
        if not (after and before):
            QMessageBox.information(self, "Vergleich", "Vorschau nicht verfügbar.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Vorher / Nachher — Trennstrich ziehen")
        lay = QVBoxLayout(dlg)
        lay.addWidget(CompareSlider(before, after))
        dlg.resize(940, 660)
        dlg.show()  # nicht-modal
        self._cmp_dlg = dlg  # Referenz halten

    def _clear_filmstrip(self):
        while self.strip_lay.count():
            it = self.strip_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _build_filmstrip(self, result_path):
        self._clear_filmstrip()
        report = os.path.join(os.path.dirname(os.path.dirname(result_path)), "cull_report.json")
        if not os.path.isfile(report) or cv2 is None:
            self.strip_label.hide(); self.strip_scroll.hide(); return
        try:
            import json as _json
            frames = _json.load(open(report)).get("frames", [])
        except Exception:
            return
        if not frames:
            return
        shown = frames[:80]
        self._strip_paths = [fr.get("path") for fr in shown if fr.get("path")]
        self._strip_idx = 0
        for fr in shown:
            thumb = self._thumb_png(fr.get("path"))
            btn = QToolButton()
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            if thumb:
                btn.setIcon(QIcon(thumb)); btn.setIconSize(QSize(120, 90))
            kept = fr.get("keep")
            mark = "✓" if kept else "✗"
            btn.setText(f"{mark} {fr.get('peak_sharp', 0):.0f}")
            color = "#3ad17a" if kept else "#e0506a"
            btn.setStyleSheet(f"QToolButton{{border:2px solid {color};border-radius:6px;padding:3px;"
                              f"{'' if kept else 'color:#e0506a;'}}}")
            tip = fr.get("name", "")
            if fr.get("reasons"):
                tip += "\n" + "; ".join(fr["reasons"])
            btn.setToolTip(tip)
            path = fr.get("path")
            btn.clicked.connect(lambda _=False, p=path: self._set_preview(p))
            self.strip_lay.addWidget(btn)
        self.strip_label.setText(f"Bilder ({sum(1 for f in shown if f.get('keep'))} verwendet, "
                                 f"{sum(1 for f in shown if not f.get('keep'))} aussortiert) — "
                                 f"grün = verwendet, rot = raus, klicken zum Ansehen:")
        self.strip_label.show(); self.strip_scroll.show()

    def _thumb_png(self, src):
        if not src or not os.path.isfile(src) or cv2 is None:
            return None
        img = cv2.imread(src, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if img.dtype != "uint8":
            img = (img / 256).astype("uint8") if img.max() > 255 else img.astype("uint8")
        h, w = img.shape[:2]
        f = 90 / h
        img = cv2.resize(img, (max(1, int(w * f)), 90), interpolation=cv2.INTER_AREA)
        out = _cache_path("sf_th_", src)
        cv2.imwrite(out, img)
        return out

    def open_result(self):
        if self.result_path:
            reveal_in_files(self.result_path)

    def open_folder(self):
        if self.result_path:
            open_path(os.path.dirname(self.result_path))

    def _best_export_file(self, bits=32):
        """Lineares TIFF fürs Weiterreichen finden. bits=32 → 32-bit-Float (GraXpert/PixInsight);
        bits=16 → 16-bit-TIFF (StarNet++ akzeptiert nur 16-bit). Sonst Ergebnis."""
        if self.result_path:
            d = os.path.dirname(self.result_path)
            tifs = [f for f in os.listdir(d) if f.lower().endswith((".tif", ".tiff"))]
            if bits == 32:
                for f in tifs:
                    if "32bit" in f.lower():
                        return os.path.join(d, f)
            else:  # 16-bit: ein lineares TIFF OHNE 32bit-Marker bevorzugen
                lin = [f for f in tifs if "32bit" not in f.lower()]
                if lin:
                    pref = [f for f in lin if "linear" in f.lower()] or lin
                    return os.path.join(d, pref[0])
            if self.result_path.lower().endswith((".tif", ".tiff")):
                return self.result_path
        return self.result_path

    def send_to_tool(self):
        f = self._best_export_file()
        if not f:
            return
        reveal_in_files(f)
        self._append(f"\n📤 Im Dateimanager: {os.path.basename(f)}\n   → in GraXpert / StarNet++ / "
                     "PixInsight öffnen, dann „📥 Bearbeitetes reimportieren“.\n")

    def _run_external_tool(self, which):
        """GraXpert/StarNet++ headless auf das lineare Ergebnis anwenden und automatisch
        reimportieren. Ohne gefundenes Tool: im Dateimanager zeigen (manueller Weg).
        Pfad kommt aus dem Setup-Menü (oder Auto-Erkennung)."""
        try:
            import tools_engine
        except Exception as e:
            QMessageBox.warning(self, which, f"{e}"); return
        # StarNet braucht 16-bit-TIFF, GraXpert nimmt 32-bit-Float
        f = self._best_export_file(bits=16 if which == "starnet" else 32)
        if not f or not os.path.isfile(f):
            QMessageBox.information(self, which, tr("Erst ein Astro-Ergebnis erzeugen."))
            return
        name = "GraXpert" if which == "graxpert" else "StarNet++"
        cfg_path = (self.graxpert_path.text().strip() if which == "graxpert"
                    else self.starnet_path.text().strip()) or None
        finder = tools_engine.find_graxpert if which == "graxpert" else tools_engine.find_starnet
        exe = finder(cfg_path)
        if not exe:
            reveal_in_files(f)
            self._append(f"\n📤 {name} nicht gefunden — Datei im Dateimanager: "
                         f"{os.path.basename(f)}\n   → Pfad im Setup-Menü setzen oder dort öffnen, "
                         "dann „📥 Bearbeitetes reimportieren“.\n")
            return
        runner = tools_engine.run_graxpert if which == "graxpert" else tools_engine.run_starnet
        self._append(f"\n⏳ {name} läuft … (kann dauern)\n")
        QApplication.processEvents()
        try:
            out = runner(f, path=cfg_path, log=self._append)
        except Exception as e:
            QMessageBox.warning(self, name, f"{name}: {e}")
            self._append(f"\n⚠️ {name} fehlgeschlagen: {e}\n")
            return
        self.result_path = out
        self.before_path = f          # „Vorher“ = Eingang, „Nachher“ = bearbeitet
        self._set_preview(out)
        self.cmp_btn.setEnabled(True); self.adjust_btn.setEnabled(True)
        self.open_btn.setEnabled(True); self.openfolder_btn.setEnabled(True)
        self._append(f"\n✅ {name} fertig & reimportiert: {os.path.basename(out)}\n")

    def reimport_result(self):
        start = os.path.dirname(self.result_path) if self.result_path else os.path.expanduser("~")
        f, _ = QFileDialog.getOpenFileName(self, "Bearbeitetes Bild wählen", start,
                                           "Bilder (*.tif *.tiff *.png *.jpg *.jpeg *.fit *.fits)")
        if not f:
            return
        self.result_path = f
        self.before_path = None
        self._set_preview(f)
        self.adjust_btn.setEnabled(True); self.open_btn.setEnabled(True)
        self.openfolder_btn.setEnabled(True)
        self._append(f"\n📥 Reimportiert: {os.path.basename(f)} — bereit zum Bearbeiten/Exportieren.\n")

    # ---------- Fokus-Werkzeuge ----------
    def analyze_series(self):
        """Fokusreihe analysieren (Hintergrund-Thread): Verwackler, redundante Frames,
        Abdeckung, optimale Bildanzahl. Read-only, blockiert die GUI nicht."""
        if getattr(self, "_analyze_worker", None) and self._analyze_worker.isRunning():
            return  # läuft schon
        folder = self.in_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, tr("Reihe analysieren"),
                                    tr("Bitte zuerst einen Eingabe-Ordner wählen.")); return
        try:
            import focus_cull_stack as F
        except Exception as e:
            QMessageBox.warning(self, tr("Reihe analysieren"), f"{e}"); return
        paths = F.list_images(folder)
        if len(paths) < 3:
            QMessageBox.information(self, tr("Reihe analysieren"),
                                    tr("Mindestens 3 Aufnahmen nötig.")); return
        # Fortschritts-/Abbruch-Dialog (unbestimmt), Analyse im Worker-Thread
        busy = QDialog(self); busy.setWindowTitle(tr("Reihe analysieren"))
        bl = QVBoxLayout(busy)
        bl.addWidget(QLabel(tr("Analysiere %d Aufnahmen …") % len(paths)))
        bar = QProgressBar(); bar.setRange(0, 0); bl.addWidget(bar)
        cancel = QPushButton(tr("Abbrechen")); bl.addWidget(cancel)
        self._analyze_busy = busy
        self._analyze_worker = _AnalyzeWorker(paths)

        self._analyze_cancelled = False

        def on_done(rep):
            busy.accept()
            if not self._analyze_cancelled:
                self._render_analysis(rep, paths)

        def on_fail(msg):
            busy.accept()
            if not self._analyze_cancelled:
                QMessageBox.warning(self, tr("Reihe analysieren"), msg)

        def do_cancel():
            # KEIN terminate() (cv2/numpy mitten im Lauf = Crash-Risiko): nur entkoppeln,
            # der Thread läuft im Hintergrund sauber zu Ende, das Ergebnis wird verworfen.
            self._analyze_cancelled = True
            busy.reject()

        self._analyze_worker.done.connect(on_done)
        self._analyze_worker.failed.connect(on_fail)
        cancel.clicked.connect(do_cancel)
        self._analyze_worker.start()
        busy.exec()

    def _render_analysis(self, rep, paths):
        """Analyse-Report als Dialog aufbauen (läuft im GUI-Thread, schnell)."""
        self._analyze_paths = paths
        self._analyze_M = rep["M"]
        sweep = rep["sweep"]; opt = rep["optimizer"]
        cnt = {"good": 0, "redundant": 0, "blurry": 0, "outlier": 0}
        for _i, st, _r in rep["status"]:
            cnt[st] += 1
        lines = [f"<b>{rep['n']} Aufnahmen erkannt.</b>", ""]
        lines.append("✅ <b>Fokusbereich vollständig</b>" if rep["complete"]
                     else f"⚠️ <b>Fokusbereich evtl. mit Lücken</b> ({rep['coverage']:.0f} % abgedeckt)")
        s0, s1 = sweep["sweep"]
        lines.append(f"🎯 Bild {s0 + 1}–{s1 + 1} tragen den Fokus · "
                     f"✓ {cnt['good']} nutzbar · ♻️ {cnt['redundant']} redundant · "
                     f"⚠️ {cnt['blurry']} verwackelt · ⤳ {cnt['outlier']} außerhalb der Reihe")
        # Auffällige Frames einzeln auflisten
        flagged = [(i, st, r) for i, st, r in rep["status"] if st in ("blurry", "outlier")]
        if flagged:
            lines.append("")
            for i, st, r in flagged[:20]:
                icon = "⚠️" if st == "blurry" else "⤳"
                lines.append(f"{icon} <b>Bild {i + 1}</b> ({os.path.basename(paths[i])}): {r}")
        lines.append("")
        lines.append("<b>📉 Optimale Bildanzahl</b> (Fokus-Abdeckung bei weniger Bildern):")
        lines.append("<table cellpadding=4>")
        for lvl in opt["levels"]:
            bar = "█" * int(lvl["coverage"] / 5)
            lines.append(f"<tr><td><b>{lvl['frames']}</b> Bilder</td>"
                         f"<td>{lvl['coverage']:.0f}%</td><td>{bar}</td></tr>")
        lines.append("</table>")
        lines.append("<i>100 % = volle Schärfen-Abdeckung wie mit allen Bildern.</i>")
        dlg = QDialog(self); dlg.setWindowTitle(tr("Reihen-Analyse")); dlg.resize(580, 500)
        lay = QVBoxLayout(dlg)
        txt = QLabel("<br>".join(lines)); txt.setWordWrap(True); txt.setTextFormat(Qt.RichText)
        txt.setAlignment(Qt.AlignTop)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(txt)
        lay.addWidget(sc)
        btns = QHBoxLayout()
        fmap = QPushButton(tr("🗺️ Fokus-Map zeigen"))
        fmap.setToolTip(tr("Färbt jeden Bereich danach, aus welchem Foto die schärfsten Details stammen."))
        fmap.clicked.connect(self.show_focus_map)
        close = QPushButton(tr("Schließen")); close.clicked.connect(dlg.accept)
        btns.addWidget(fmap); btns.addWidget(close)
        lay.addLayout(btns)
        dlg.show(); self._analyze_dlg = dlg

    def show_focus_map(self):
        """Fokus-Herkunfts-Karte als Bild anzeigen (welcher Frame liefert wo die Schärfe)."""
        paths = getattr(self, "_analyze_paths", None)
        if not paths:
            return
        try:
            import focus_analysis as fa
            fmap = fa.focus_map(paths, M=getattr(self, "_analyze_M", None))
            p = os.path.join("/tmp", "sf_focusmap.png")
            cv2.imwrite(p, fmap)
        except Exception as e:
            QMessageBox.warning(self, tr("Fokus-Map"), f"{e}"); return
        dlg = QDialog(self); dlg.setWindowTitle(tr("Fokus-Map — Herkunft der Schärfe")); dlg.resize(720, 600)
        lay = QVBoxLayout(dlg)
        info = QLabel(tr("Farbe = aus welchem Foto (Reihenfolge) die schärfsten Details kommen. "
                         "Blau = frühe, Rot = späte Aufnahmen. Gleichmäßiger Verlauf = saubere Reihe."))
        info.setWordWrap(True); info.setStyleSheet("color:#9aa09a;font-size:11px;")
        lay.addWidget(info)
        pic = QLabel(); pic.setAlignment(Qt.AlignCenter)
        pic.setPixmap(QPixmap(p).scaled(680, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(pic, 1)
        close = QPushButton(tr("Schließen")); close.clicked.connect(dlg.accept); lay.addWidget(close)
        dlg.show(); self._fmap_dlg = dlg

    def open_dof(self):
        """DOF-Rechner / Shooting-Assistent: Optik-Parameter → Schärfentiefe, Schrittweite,
        benötigte Bildanzahl."""
        import focus_analysis as fa
        dlg = QDialog(self); dlg.setWindowTitle(tr("DOF-Rechner / Shooting-Assistent")); dlg.resize(440, 360)
        lay = QVBoxLayout(dlg)
        form = QGridLayout()
        sensor = QComboBox()
        for k, lbl in [("fullframe", "Vollformat"), ("apsc", "APS-C"), ("mft", "MFT"),
                       ("medium", "Mittelformat")]:
            sensor.addItem(lbl, k)
        focal = QDoubleSpinBox(); focal.setRange(8, 1200); focal.setValue(105); focal.setSuffix(" mm")
        aperture = QDoubleSpinBox(); aperture.setRange(1.0, 64); aperture.setValue(8.0); aperture.setPrefix("f/")
        mag = QDoubleSpinBox(); mag.setRange(0.0, 10.0); mag.setSingleStep(0.1); mag.setValue(1.0)
        mag.setToolTip("Abbildungsmaßstab: 1.0 = 1:1 (Makro). 0 = stattdessen Distanz nutzen.")
        dist = QDoubleSpinBox(); dist.setRange(0.0, 1000); dist.setValue(0.0); dist.setSuffix(" m")
        depth = QDoubleSpinBox(); depth.setRange(0.1, 1000); depth.setValue(8.0); depth.setSuffix(" mm")
        overlap = QSpinBox(); overlap.setRange(0, 80); overlap.setValue(30); overlap.setSuffix(" %")
        rows = [("Sensor", sensor), ("Brennweite", focal), ("Blende", aperture),
                ("Abbildung (1:1=1.0)", mag), ("oder Distanz", dist),
                ("Motivtiefe", depth), ("Überlappung", overlap)]
        for r, (lab, wdg) in enumerate(rows):
            form.addWidget(QLabel(lab), r, 0); form.addWidget(wdg, r, 1)
        lay.addLayout(form)
        out = QLabel(); out.setWordWrap(True); out.setTextFormat(Qt.RichText)
        out.setStyleSheet("background:#202227;border-radius:8px;padding:10px;")
        lay.addWidget(out)

        def compute():
            d = fa.dof_calc(aperture.value(), focal_mm=focal.value(),
                            magnification=mag.value() if mag.value() > 0 else None,
                            distance_m=dist.value() if mag.value() <= 0 and dist.value() > 0 else None,
                            sensor=sensor.currentData(), overlap=overlap.value() / 100.0)
            if not d:
                out.setText("Bitte Abbildung <b>oder</b> Distanz angeben."); return
            if d["dof_mm"] == float("inf"):
                out.setText("Bei dieser Distanz/Blende reicht ein Bild (sehr große Schärfentiefe)."); return
            n = fa.frames_for_depth(depth.value(), d["step_mm"])
            out.setText(f"<b>Schärfentiefe je Bild:</b> {d['dof_mm']:.2f} mm<br>"
                        f"<b>Empfohlene Schrittweite:</b> {d['step_mm']:.2f} mm "
                        f"({overlap.value()} % Überlappung)<br>"
                        f"<b>Abbildung:</b> ~{d['magnification']:.2f}×<br><br>"
                        f"➡️ Für {depth.value():.1f} mm Motivtiefe: <b>{n} Aufnahmen</b>.")
        for w in (sensor, focal, aperture, mag, dist, depth, overlap):
            (w.valueChanged if hasattr(w, "valueChanged") else w.currentIndexChanged).connect(lambda *a: compute())

        def from_exif():
            start = self.in_edit.text().strip() or os.path.expanduser("~")
            f, _ = QFileDialog.getOpenFileName(dlg, tr("Foto wählen (EXIF lesen)"), start,
                                               "Bilder (*.arw *.nef *.cr2 *.cr3 *.dng *.jpg *.jpeg *.tif *.tiff)")
            if not f:
                return
            e = fa.read_exif_optics(f)
            if not e:
                QMessageBox.information(dlg, tr("Aus Foto lesen"),
                                       tr("Keine EXIF-Optikdaten gefunden (exiftool nötig).")); return
            if e.get("focal_mm"):
                focal.setValue(e["focal_mm"])
            if e.get("f_number"):
                aperture.setValue(e["f_number"])
            si = sensor.findData(e.get("sensor", "fullframe"))
            if si >= 0:
                sensor.setCurrentIndex(si)
            if e.get("distance_m"):                     # Distanz bekannt → Abbildung daraus
                dist.setValue(e["distance_m"]); mag.setValue(0.0)
            cam = e.get("model") or "?"; lens = e.get("lens") or "?"
            self._append(f"\n📷 EXIF: {cam} · {lens} · {e.get('focal_mm')}mm f/{e.get('f_number')}"
                         f"{' · '+str(e['distance_m'])+'m' if e.get('distance_m') else ''}\n")
            compute()

        exif_btn = QPushButton(tr("📷 Aus Foto lesen (EXIF)"))
        exif_btn.setToolTip(tr("Brennweite, Blende, Sensor und (falls vorhanden) Fokusdistanz "
                               "aus den EXIF-Daten eines Fotos übernehmen."))
        exif_btn.clicked.connect(from_exif)
        lay.addWidget(exif_btn)
        compute()
        btn = QPushButton(tr("Schließen")); btn.clicked.connect(dlg.accept); lay.addWidget(btn)
        dlg.show(); self._dof_dlg = dlg

    def _retouch_file(self):
        """Bevorzugt die Mehrschicht-TIFF, sonst das Stack-Ergebnis."""
        ml_dir = os.path.join(self._work_dir(), "multilayer")
        if os.path.isdir(ml_dir):
            tifs = [os.path.join(ml_dir, f) for f in os.listdir(ml_dir)
                    if f.lower().endswith((".tif", ".tiff"))]
            if tifs:
                return max(tifs, key=os.path.getmtime)
        return self.result_path

    def _ghostmap_path(self):
        if not self.result_path:
            return None
        p = os.path.join(os.path.dirname(os.path.dirname(self.result_path)), "ghostmap.jpg")
        return p if os.path.isfile(p) else None

    def open_ghostmap(self):
        p = self._ghostmap_path()
        if p:
            self._set_preview(p)
            self._append("\n👻 Geister-Karte angezeigt (rot = Bewegung/Ghosting-Verdacht). "
                         "Mit dem Retusche-Pinsel korrigierbar.\n")
        else:
            QMessageBox.information(self, "Keine Geister-Karte",
                                    "Beim Lauf war „Geister-Karte erzeugen“ nicht aktiv.")

    def open_adjust(self):
        if not self.result_path or cv2 is None:
            return
        img = cv2.imread(self.result_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            QMessageBox.warning(self, "Fehler", "Bild konnte nicht geladen werden.")
            return
        d = os.path.dirname(self.result_path)
        b, e = os.path.splitext(os.path.basename(self.result_path))
        dlg = AdjustDialog(img, os.path.join(d, f"{b}_bearbeitet{e}"), self)
        dlg.show()
        self._adjust_dlg = dlg

    def _gather_sources(self):
        """Ausgerichtete Quell-Frames fürs Retuschieren holen — bevorzugt aus der
        Mehrschicht-Datei (Seite 0 = Ergebnis), sonst aus den behaltenen Fotos."""
        ml_dir = os.path.join(self._work_dir(), "multilayer")
        if os.path.isdir(ml_dir):
            tifs = [os.path.join(ml_dir, f) for f in os.listdir(ml_dir)
                    if f.lower().endswith((".tif", ".tiff"))]
            if tifs:
                try:
                    import tifffile
                    pages = tifffile.imread(max(tifs, key=os.path.getmtime))
                    if pages.ndim == 4 and len(pages) > 1:  # (N,h,w,3) RGB
                        srcs = [cv2.cvtColor(p, cv2.COLOR_RGB2BGR) for p in pages[1:]]
                        return srcs, [f"Foto {i + 1}" for i in range(len(srcs))]
                except Exception:
                    pass
        # Fallback: behaltene Frames aus dem Report (ggf. nicht ausgerichtet)
        report = os.path.join(os.path.dirname(os.path.dirname(self.result_path)), "cull_report.json")
        srcs, names = [], []
        if os.path.isfile(report):
            try:
                import json as _json
                for fr in _json.load(open(report)).get("frames", []):
                    if fr.get("keep") and os.path.isfile(fr.get("path", "")):
                        im = cv2.imread(fr["path"], cv2.IMREAD_UNCHANGED)
                        if im is not None:
                            srcs.append(im); names.append(fr.get("name", f"Foto {len(srcs)}"))
            except Exception:
                pass
        return srcs, names

    def open_retouch(self):
        if not self.result_path or cv2 is None:
            QMessageBox.warning(self, "Kein Ergebnis", "Erst ein Bild erzeugen.")
            return
        res = cv2.imread(self.result_path, cv2.IMREAD_UNCHANGED)
        if res is None:
            QMessageBox.warning(self, "Fehler", "Ergebnis konnte nicht geladen werden.")
            return
        srcs, names = self._gather_sources()
        # Quellen auf Ergebnisgröße bringen
        srcs = [s for s in srcs if s is not None]
        srcs = [cv2.resize(s, (res.shape[1], res.shape[0])) if s.shape[:2] != res.shape[:2] else s
                for s in srcs]
        if not srcs:
            QMessageBox.warning(self, "Keine Quellfotos",
                                "Keine Quellfotos gefunden. Tipp: „Ebenen-Datei“ aktivieren.")
            return
        d = os.path.dirname(self.result_path)
        b, e = os.path.splitext(os.path.basename(self.result_path))
        save_path = os.path.join(d, f"{b}_retusche{e}")
        dlg = RetouchDialog(res, srcs, names, save_path, self)
        dlg.show()
        self._retouch_dlg = dlg
        self._append(f"\n✏️ Retusche-Editor geöffnet ({len(srcs)} Quellfotos).\n")

    def keyPressEvent(self, e):
        """Foto-Einzeltasten — feuern nur, wenn KEIN Textfeld den Fokus hat
        (Qt liefert die Taste sonst direkt ans Eingabefeld). Modul-Auswahl ausgenommen."""
        if self.top_stack.currentIndex() != 1 or (e.modifiers() & ~Qt.KeypadModifier):
            return super().keyPressEvent(e)
        k = e.key()
        makro = not (getattr(self, "is_astro", False) or getattr(self, "is_hybrid", False)
                     or getattr(self, "is_longexp", False))
        if k == Qt.Key_Space and self.cmp_btn.isEnabled():
            self.open_compare()
        elif k == Qt.Key_A and makro:
            self.analyze_series()
        elif k == Qt.Key_S:
            self.run(auto=self.mode_box.currentIndex() == 0)
        elif k == Qt.Key_E and self.adjust_btn.isEnabled():
            self.open_adjust()
        elif k == Qt.Key_G and self.ghost_btn.isEnabled():
            self.open_ghostmap()
        elif k == Qt.Key_F:
            (self.show_focus_map if getattr(self, "_analyze_paths", None) else self.analyze_series)()
        elif k == Qt.Key_R and self.retouch_btn.isEnabled() and self.retouch_btn.isVisible():
            self.open_retouch()
        elif k in (Qt.Key_Left, Qt.Key_Right):
            self._step_filmstrip(-1 if k == Qt.Key_Left else 1)
        else:
            return super().keyPressEvent(e)

    def _step_filmstrip(self, d):
        paths = getattr(self, "_strip_paths", None)
        if not paths:
            return
        self._strip_idx = (getattr(self, "_strip_idx", 0) + d) % len(paths)
        self._set_preview(paths[self._strip_idx])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        src = getattr(self, "_preview_src", None)
        if src:
            pix = QPixmap(src)
            if not pix.isNull():
                self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                  Qt.SmoothTransformation))

    # ---------- Einstellungen merken ----------
    def closeEvent(self, e):
        # Laufende Subprozesse/Threads sauber beenden (sonst Orphan-Prozess / QThread-Warnung)
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.terminate()
            if not self.proc.waitForFinished(2000):
                self.proc.kill()
        wk = getattr(self, "_analyze_worker", None)
        if wk and wk.isRunning():
            wk.wait(4000)
        # _updchk läuft als Daemon-Thread (kein QThread) -> stirbt mit dem Prozess, kein Wait nötig
        self._save_settings()
        QSettings("ServeOne", "ForgePix").setValue("geometry", self.saveGeometry())
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    # Sprache aus den Einstellungen laden, BEVOR die Oberfläche gebaut wird
    set_language(QSettings("ServeOne", "ForgePix").value("language", "de"))
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setStyleSheet(THEME)
    if os.path.isfile(ICON):
        app.setWindowIcon(QIcon(ICON))
    elif os.path.isfile(ICON_PNG):
        app.setWindowIcon(QIcon(ICON_PNG))
    # echtes Dock-Icon (macOS) zur Laufzeit setzen
    try:
        from AppKit import NSApplication, NSImage
        img = NSImage.alloc().initByReferencingFile_(ICON_PNG)
        if img:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
