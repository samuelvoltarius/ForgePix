#!/usr/bin/env python3
"""
focus_stack_gui.py — GUI fuer focus_cull_stack.py (PySide6).

Ordnerauswahl + alle Einstellungen + Live-Log + Ergebnis-Vorschau.
Ruft focus_cull_stack.py als Subprozess auf (streamt stdout/stderr live).

Start:  python3 focus_stack_gui.py
"""
import os
import re
import subprocess
import sys

from i18n import tr, set_language, available_languages, current_language

from PySide6.QtCore import Qt, QProcess, QSettings, QRect, QSize
from PySide6.QtGui import QPixmap, QFont, QIcon, QPainter, QColor, QPen, QCursor, QImage
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QFileDialog, QPlainTextEdit,
    QDoubleSpinBox, QSpinBox, QCheckBox, QMessageBox, QSplitter, QFrame, QComboBox,
    QScrollArea, QProgressBar, QToolButton, QDialog, QToolTip, QSlider, QStackedWidget,
)

try:
    import cv2  # robuste Vorschau (auch 16-bit TIFF)
    import numpy as np
except Exception:
    cv2 = None
    np = None
FRAME_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Projekt-Root (ui/ liegt darunter)
SCRIPT = os.path.join(HERE, "focus_cull_stack.py")
SHINESTACKER = os.path.join(os.path.dirname(sys.executable), "shinestacker")
ICON = os.path.join(HERE, "assets", "StackForge.icns")
ICON_PNG = os.path.join(HERE, "assets", "stackforge_512.png")
APP_NAME = "StackForge"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


from ui.components import (CompareSlider, CurveWidget, AdjustDialog, RetouchDialog, _Canvas,
                           _bgr_to_pixmap, histogram_pixmap, adjust_image, HSL_BANDS,
                           help_btn, _row, reveal_in_files, open_path, notify)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StackForge — Fokus-Stacking mit KI")
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

        # Header mit Logo + Name
        header = QHBoxLayout()
        self.modules_btn = QPushButton(tr("◀ Module"))
        self.modules_btn.setToolTip(tr("Zur Modul-Auswahl zurück"))
        self.modules_btn.clicked.connect(lambda: self.top_stack.setCurrentIndex(0))
        header.addWidget(self.modules_btn)
        logo = QLabel()
        if os.path.isfile(ICON_PNG):
            logo.setPixmap(QPixmap(ICON_PNG).scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        title = QLabel("StackForge")
        title.setStyleSheet("font-size:22px;font-weight:bold;")
        sub = QLabel(tr("Fokus-Stacking mit KI"))
        sub.setStyleSheet("color:#888;")
        header.addWidget(logo); header.addWidget(title); header.addSpacing(10)
        header.addWidget(sub); header.addStretch(1)
        header.addWidget(QLabel(tr("Aufgabe:")))
        self.task_box = QComboBox()
        self.task_box.addItems([tr("🔬 Makro (Fokus)"), tr("🌌 Astro (Sterne)"),
                                tr("🌗 Hybrid (Mosaik)"), tr("📷 Langzeitbelichtung")])
        # 0=Makro, 1=Astro, 2=Hybrid, 3=Langzeit
        self.task_box.currentIndexChanged.connect(lambda _i: self._set_task())
        header.addWidget(self.task_box)
        header.addSpacing(12)
        header.addWidget(QLabel(tr("Modus:")))
        self.mode_box = QComboBox()
        self.mode_box.addItems([tr("🌱 Anfänger"), tr("🛠️ Profi")])  # 0=Anfänger, 1=Profi
        self.mode_box.currentIndexChanged.connect(lambda _i: self._apply_visibility())
        header.addWidget(self.mode_box)
        header.addSpacing(12)
        setup_btn = QPushButton(tr("⚙  Setup"))
        setup_btn.setToolTip(tr("Sprache, KI-Server und weitere Einstellungen"))
        setup_btn.clicked.connect(self.settings_dialog.show)
        header.addWidget(setup_btn)
        outer.addLayout(header)

        # Sprache — wandert ins Setup-Menü
        self.lang_box = QComboBox()
        self._lang_codes = [c for c, _n in available_languages()]
        for _c, _n in available_languages():
            self.lang_box.addItem(_n)
        if current_language() in self._lang_codes:
            self.lang_box.setCurrentIndex(self._lang_codes.index(current_language()))
        self.lang_box.currentIndexChanged.connect(self._on_language)
        self._settings_lay.addLayout(_row(tr("Sprache:"), self.lang_box))

        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, 1)

        # ---- linke Spalte: Schritt-für-Schritt-Wizard ----
        left = QWidget()
        left.setMaximumWidth(540)
        lv = QVBoxLayout(left)

        self.STEP_NAMES = [tr("1 · Fotos"), tr("2 · Auswahl & Ausrichtung"),
                           tr("3 · Ergebnis-Optionen")]
        self.crumb = QLabel()
        self.crumb.setStyleSheet("font-weight:bold;color:#b69bff;")
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
        self.auto_btn.setMinimumHeight(44)
        self.auto_btn.setStyleSheet("font-weight:bold;font-size:14px;")
        self.auto_btn.clicked.connect(lambda: self.run(auto=True))
        p1.addWidget(self.auto_btn)
        hint = QLabel("Ein Klick genügt. Für mehr Kontrolle mit „Weiter →“ durch die Schritte.")
        hint.setStyleSheet("color:#888;"); hint.setWordWrap(True)
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
        mk_info.setWordWrap(True); mk_info.setStyleSheet("color:#9b90b5;font-size:11px;")
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
        self.astro_stretch = QCheckBox("Vorschau strecken (asinh)"); self.astro_stretch.setChecked(True)
        self.astro_bg = QCheckBox("Hintergrund/Gradient entfernen")
        self.astro_fits = QCheckBox("Auch als FITS speichern")
        self.astro_dark = QLineEdit(); self.astro_dark.setPlaceholderText("optional: Dark-Ordner/-Datei")
        self.astro_flat = QLineEdit(); self.astro_flat.setPlaceholderText("optional: Flat-Ordner/-Datei")
        self.astro_bias = QLineEdit(); self.astro_bias.setPlaceholderText("optional: Bias-Ordner/-Datei")
        dbtn = QPushButton("…"); dbtn.clicked.connect(lambda: self._pick_into(self.astro_dark))
        fbtn = QPushButton("…"); fbtn.clicked.connect(lambda: self._pick_into(self.astro_flat))
        bbtn = QPushButton("…"); bbtn.clicked.connect(lambda: self._pick_into(self.astro_bias))
        # Engine: eigene oder optional Siril
        self.astro_engine = QComboBox(); self.astro_engine.addItem("Eigene", "own")
        try:
            import siril_engine
            if siril_engine.available():
                self.astro_engine.addItem("Siril (gefunden)", "siril")
                self._siril_default = siril_engine.find_siril()
            else:
                self._siril_default = ""
        except Exception:
            self._siril_default = ""
        self.siril_path = QLineEdit(self._siril_default)
        self.siril_path.setPlaceholderText("Pfad zu siril-cli (optional)")
        sbtn = QPushButton("…"); sbtn.clicked.connect(lambda: self._pick_file_into(self.siril_path))
        ar.addWidget(QLabel("Methode"), 0, 0); ar.addWidget(self.astro_method, 0, 1, 1, 2)
        ar.addWidget(help_btn("Rauschen mitteln statt Schärfe wählen. „sigma“ (Kappa-Sigma) "
                              "entfernt Satelliten/Flugzeuge/Hot-Pixel — wie in Siril. "
                              "„max“ = Strichspuren."), 0, 3)
        ar.addWidget(QLabel("Kappa"), 1, 0); ar.addWidget(self.astro_kappa, 1, 1, 1, 2)
        ar.addWidget(self.astro_register, 2, 0, 1, 3)
        ar.addWidget(self.astro_stretch, 3, 0, 1, 3)
        ar.addWidget(self.astro_bg, 4, 0, 1, 3)
        ar.addWidget(help_btn("Entfernt weiche Helligkeits-Gradienten (Lichtverschmutzung/Vignette). "
                              "Für stärkere Tools: das 32-bit-Linear-TIFF in GraXpert/StarNet++/"
                              "PixInsight öffnen."), 4, 3)
        ar.addWidget(QLabel("Dark"), 5, 0); ar.addWidget(self.astro_dark, 5, 1, 1, 1); ar.addWidget(dbtn, 5, 2)
        ar.addWidget(QLabel("Flat"), 6, 0); ar.addWidget(self.astro_flat, 6, 1, 1, 1); ar.addWidget(fbtn, 6, 2)
        ar.addWidget(QLabel("Bias"), 7, 0); ar.addWidget(self.astro_bias, 7, 1, 1, 1); ar.addWidget(bbtn, 7, 2)
        ar.addWidget(QLabel("Engine"), 8, 0); ar.addWidget(self.astro_engine, 8, 1, 1, 2)
        ar.addWidget(help_btn("„Eigene“ = StackForge selbst (Standard, kein Fremdprogramm). "
                              "„Siril“ = optional dein installiertes Siril fernsteuern "
                              "(Konvertieren→Registrieren→Stacken). Frei wählbar."), 8, 3)
        ar.addWidget(QLabel("Siril-Pfad"), 9, 0); ar.addWidget(self.siril_path, 9, 1, 1, 1); ar.addWidget(sbtn, 9, 2)
        ar.addWidget(self.astro_fits, 10, 0, 1, 3)
        ar.addWidget(help_btn("Speichert das fertige Stack-Ergebnis zusätzlich als 32-bit-FITS "
                              "(neben dem TIFF) — für PixInsight/Siril. FITS-Lights werden auch "
                              "direkt eingelesen."), 10, 3)
        as_info = QLabel(tr("Astro: viele Aufnahmen desselben Himmelsausschnitts → Rauschen mitteln. "
                            "Empfohlen: 20–100+ Lights (mehr = weniger Rauschen) · Darks 15–30 · "
                            "Flats 15–30 · Bias 30+. Optional als Ordner/Datei angeben."))
        as_info.setWordWrap(True); as_info.setStyleSheet("color:#9b90b5;font-size:11px;")
        ar.addWidget(as_info, 11, 0, 1, 4)
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
        hy_info.setWordWrap(True); hy_info.setStyleSheet("color:#9b90b5;font-size:11px;")
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
        le_info.setWordWrap(True); le_info.setStyleSheet("color:#9b90b5;font-size:11px;")
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
        note.setWordWrap(True); note.setStyleSheet("color:#888;")
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

        # ---- rechte Spalte: Log + Vorschau ----
        right = QWidget()
        rv = QVBoxLayout(right)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont("Menlo", 11))
        self.log.setMaximumBlockCount(5000)
        rv.addWidget(QLabel(tr("Log")))
        rv.addWidget(self.log, 3)
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.hide()
        rv.addWidget(self.progress)

        line = QFrame(); line.setFrameShape(QFrame.HLine); rv.addWidget(line)
        self.preview = QLabel("Ordner hierher ziehen oder oben wählen — dann ⚡ Automatik")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setStyleSheet("color:#888;border:1px solid #444;")
        rv.addWidget(QLabel(tr("Ergebnis")))
        rv.addWidget(self.preview, 2)
        res_btns = QHBoxLayout()
        self.cmp_btn = QPushButton(tr("🔍  Vorher/Nachher"))
        self.cmp_btn.setToolTip("Schieberegler: schärfstes Einzelfoto gegen das fertige Bild vergleichen.")
        self.cmp_btn.setEnabled(False)
        self.cmp_btn.clicked.connect(self.open_compare)
        self.openfolder_btn = QPushButton(tr("📁  Ausgabe-Ordner"))
        self.openfolder_btn.clicked.connect(self.open_folder); self.openfolder_btn.setEnabled(False)
        self.open_btn = QPushButton(tr("Im Finder"))
        self.open_btn.clicked.connect(self.open_result); self.open_btn.setEnabled(False)
        self.retouch_btn = QPushButton(tr("✏️  Retusche"))
        self.retouch_btn.setToolTip("Eigener Retusche-Editor: scharfe Stellen aus Einzelfotos "
                                    "übermalen (gegen Halos/Ghosting).")
        self.retouch_btn.clicked.connect(self.open_retouch); self.retouch_btn.setEnabled(False)
        self.adjust_btn = QPushButton(tr("🎚️  Bearbeiten"))
        self.adjust_btn.setToolTip("Camera-Raw: Belichtung, Kontrast, Weißabgleich, Klarheit, "
                                   "Farbe — mit Live-Vorschau und Histogramm.")
        self.adjust_btn.clicked.connect(self.open_adjust); self.adjust_btn.setEnabled(False)
        self.ghost_btn = QPushButton(tr("👻  Geister-Karte"))
        self.ghost_btn.setToolTip("Zeigt rot, wo Bewegung/Ghosting wahrscheinlich ist "
                                  "(nur wenn beim Lauf erzeugt).")
        self.ghost_btn.clicked.connect(self.open_ghostmap); self.ghost_btn.setEnabled(False)
        for b in (self.cmp_btn, self.openfolder_btn, self.open_btn, self.adjust_btn,
                  self.ghost_btn, self.retouch_btn):
            res_btns.addWidget(b)
        rv.addLayout(res_btns)
        # zweite Reihe: Weitergabe an externe Tools + Reimport
        res_btns2 = QHBoxLayout()
        self.send_btn = QPushButton(tr("📤  Für GraXpert/StarNet öffnen"))
        self.send_btn.setToolTip("Zeigt das (32-bit-lineare) Ergebnis im Dateimanager — dort in "
                                 "GraXpert / StarNet++ / PixInsight öffnen.")
        self.send_btn.clicked.connect(self.send_to_tool); self.send_btn.setEnabled(False)
        self.reimport_btn = QPushButton(tr("📥  Bearbeitetes reimportieren"))
        self.reimport_btn.setToolTip("Das im externen Tool bearbeitete Bild zurück in StackForge "
                                     "laden (für Vorschau/Bearbeiten/Export).")
        self.reimport_btn.clicked.connect(self.reimport_result); self.reimport_btn.setEnabled(False)
        res_btns2.addWidget(self.send_btn); res_btns2.addWidget(self.reimport_btn)
        res_btns2.addStretch(1)
        rv.addLayout(res_btns2)

        # Filmstreifen: alle Fotos mit Schärfe-Wert, behalten/verworfen
        self.strip_label = QLabel("Bilder (grün = verwendet, rot = aussortiert):")
        self.strip_label.hide()
        rv.addWidget(self.strip_label)
        self.strip_scroll = QScrollArea()
        self.strip_scroll.setWidgetResizable(True)
        self.strip_scroll.setFixedHeight(150)
        self.strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.strip_host = QWidget()
        self.strip_lay = QHBoxLayout(self.strip_host)
        self.strip_lay.setAlignment(Qt.AlignLeft)
        self.strip_scroll.setWidget(self.strip_host)
        self.strip_scroll.hide()
        rv.addWidget(self.strip_scroll)

        split.addWidget(right)
        split.setSizes([440, 660])

        self.result_path = None
        self.before_path = None
        self._restore_settings()
        self._set_step(0)
        self._set_task()
        # Dropdowns an Textlänge anpassen (gegen abgeschnittene Texte, auch bei EN)
        for cb in self.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        for cb in self.settings_dialog.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)

    def _on_language(self, _i):
        code = self._lang_codes[self.lang_box.currentIndex()]
        QSettings("ServeOne", "StackForge").setValue("language", code)
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

    def _build_welcome(self):
        """Start-Auswahlbildschirm: ein großes Kärtchen je Modul."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(40, 30, 40, 30)
        head = QLabel("StackForge")
        head.setStyleSheet("font-size:30px;font-weight:bold;")
        head.setAlignment(Qt.AlignCenter)
        sub = QLabel(tr("Was möchtest du stacken? Modul wählen — später jederzeit über „◀ Module“ wechselbar."))
        sub.setStyleSheet("color:#b69bff;font-size:14px;")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(head); lay.addWidget(sub); lay.addSpacing(18)

        grid = QGridLayout(); grid.setSpacing(16)
        cards = [
            (0, "🔬", tr("Makro / Fokus-Stacking"),
             tr("Mehrere Nahaufnahmen → ein durchgehend scharfes Bild. Produkte, Münzen, Insekten, Food.  "
                "Empfohlen: 10–40 Aufnahmen.")),
            (1, "🌌", tr("Astro"),
             tr("Sternenhimmel/Deep-Sky: kalibrieren, ausrichten, Rauschen mitteln, schlechte Subs aussortieren.  "
                "Empfohlen: 20–100+ Lights (+ Darks/Flats).")),
            (2, "🌗", tr("Hybrid"),
             tr("Mond-/Sonnen-Mosaik aus Kacheln — oder Fokus+Astro (erst entrauschen, dann fokus-stacken).  "
                "Mosaik 4–20+ Kacheln · Fokus+Astro 5–15 Shots je Position.")),
            (3, "📷", tr("Langzeitbelichtung"),
             tr("Aus einer Serie eine Langzeitbelichtung ohne ND-Filter: seidiges Wasser, Lichtspuren, Störer weg.  "
                "Empfohlen: 10–30 (Wasser) bis 300+ (Lichtspuren).")),
        ]
        for n, (idx, emoji, name, desc) in enumerate(cards):
            btn = QPushButton()
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(150)
            btn.setText(f"{emoji}\n\n{name}\n")
            btn.setToolTip(desc)
            btn.setStyleSheet(
                "QPushButton{font-size:17px;font-weight:bold;text-align:center;"
                "border:1px solid #4a3a6e;border-radius:12px;padding:14px;background:#241a38;}"
                "QPushButton:hover{background:#3c2d5e;border-color:#8a5cff;}")
            d = QLabel(desc); d.setWordWrap(True); d.setStyleSheet("color:#9b90b5;font-size:12px;")
            cell = QWidget(); cv = QVBoxLayout(cell); cv.setContentsMargins(0, 0, 0, 0)
            cv.addWidget(btn); cv.addWidget(d)
            btn.clicked.connect(lambda _=False, t=idx: self._choose_module(t))
            grid.addWidget(cell, n // 2, n % 2)
        lay.addLayout(grid)
        lay.addStretch(1)
        hint = QLabel(tr("Tipp: Im Anfänger-Modus genügt „Ordner wählen“ — die Automatik erklärt ihre Entscheidungen."))
        hint.setStyleSheet("color:#777;"); hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)
        return page

    def _choose_module(self, task_index):
        """Modul aus dem Startbildschirm wählen → Aufgabe setzen + in den Arbeitsbereich wechseln."""
        self.task_box.setCurrentIndex(task_index)
        self._set_task()
        self.top_stack.setCurrentIndex(1)

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
        self.adv_folder.setVisible(pro and makro)
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
        if e.mimeData().hasUrls() and any(os.path.isdir(u.toLocalFile())
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isdir(p):
                self.in_edit.setText(p)
                self._append(f"📂 Ordner per Drag&Drop: {p}\n")
                break

    # ---------- Ordnerauswahl ----------
    def pick_input(self):
        d = QFileDialog.getExistingDirectory(self, "Eingabe-Ordner wählen", self.in_edit.text() or os.path.expanduser("~"))
        if d:
            self.in_edit.setText(d)

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
        chosen = [k for k, cb in self.exp_targets.items() if cb.isChecked()]
        if chosen:
            args += ["--export", ",".join(chosen)]
        if self.astro_group.isChecked():
            args += ["--astro", "--astro-method", self.astro_method.currentText(),
                     "--astro-kappa", str(self.astro_kappa.value())]
            if not self.astro_register.isChecked():
                args += ["--no-register"]
            if self.astro_stretch.isChecked():
                args += ["--astro-stretch"]
            if self.astro_bg.isChecked():
                args += ["--bg-extract"]
            if self.astro_fits.isChecked():
                args += ["--fits-out"]
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
        if self.nostack.isChecked():
            args += ["--no-stack"]
        if self.vlm_group.isChecked() and self.vlm_ep.text().strip():
            args += ["--vlm-qc"]  # manueller Wind/Bewegungs-QC
        return args

    def run(self, auto=False):
        inp = self.in_edit.text().strip()
        if not inp or not os.path.isdir(inp):
            QMessageBox.warning(self, "Fehler", "Bitte einen gültigen Eingabe-Ordner wählen.")
            return
        args = self._build_args(auto)
        self.log.clear()
        self.preview.setText("— läuft —"); self.preview.setPixmap(QPixmap())
        self.open_btn.setEnabled(False); self.retouch_btn.setEnabled(False)
        self.cmp_btn.setEnabled(False); self.cmp_btn.setChecked(False); self.openfolder_btn.setEnabled(False)
        self.result_path = None; self.before_path = None
        self.progress.setRange(0, 0); self.progress.show()  # erst „beschäftigt“
        if auto:
            self._append("⚡ AUTOMATIK — die KI bestimmt alle Einstellungen, max. Qualität.\n")
        self._append(f"$ python3 {' '.join(args)}\n")

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._on_output)
        self.proc.finished.connect(self._on_finished)
        self.proc.start(sys.executable, ["-u"] + args)
        self.run_btn.setEnabled(False); self.auto_btn.setEnabled(False); self.stop_btn.setEnabled(True)

    def stop(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
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
        self._append("\n🤖 Hole KI-Vorschlag …\n")
        self.suggest_btn.setEnabled(False); self.run_btn.setEnabled(False); self.auto_btn.setEnabled(False)
        self.sug_proc = QProcess(self)
        self.sug_proc.readyReadStandardError.connect(
            lambda: self._append(ANSI.sub("", bytes(self.sug_proc.readAllStandardError()).decode(errors="replace"))))
        self.sug_proc.finished.connect(self._on_suggest_done)
        self.sug_proc.start(sys.executable, ["-u"] + args)

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
            f"Bündel-Größe:           {s.get('bunch')}\n"
            f"VLM-QC:                 {'an' if s.get('vlm_qc') else 'aus'}\n\n"
            f"Algorithmus:            {s.get('algo')}\n"
            f"Transform / Detektor:   {s.get('transform')} / {s.get('detector')}\n"
            f"Balance:                {s.get('balance_channel')} / {s.get('balance_map')}\n"
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
        if "Fertig. Ergebnis in:" in clean:  # auch im Watch-/Batch-Modus laufend aktualisieren
            self._show_result()

    def _on_finished(self, code, _status):
        self.run_btn.setEnabled(True); self.auto_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        self.progress.setRange(0, 100); self.progress.setValue(100 if code == 0 else 0)
        self._append(f"\n[fertig, exit {code}]\n")
        if code == 0:
            self._show_result()
            self._notify("StackForge", "Stack fertig 🎉" if self.result_path else "Lauf fertig")

    def _notify(self, title, msg):
        notify(title, msg)

    # ---------- Ergebnis ----------
    def _find_result(self):
        """Neuestes Stack-Bild finden — auch im Batch (<work>/<sub>/stack)."""
        wd = self._work_dir()
        cands = []
        for d in [os.path.join(wd, "stack")] + \
                 [os.path.join(wd, s, "stack") for s in (os.listdir(wd) if os.path.isdir(wd) else [])
                  if os.path.isdir(os.path.join(wd, s, "stack"))]:
            if os.path.isdir(d):
                cands += [os.path.join(d, f) for f in os.listdir(d)
                          if os.path.splitext(f)[1].lower() in IMG_EXTS]
        return max(cands, key=os.path.getmtime) if cands else None

    def _preview_png(self, src):
        """Beliebiges Bild (auch 16-bit TIFF) zu 8-bit-PNG für die Anzeige."""
        if not src or not os.path.isfile(src):
            return None
        if cv2 is None:
            return src  # Fallback: direkt versuchen
        img = cv2.imread(src, cv2.IMREAD_UNCHANGED)
        if img is None:
            return src if QPixmap(src).isNull() is False else None
        if img.dtype != "uint8":
            img = (img / 256).astype("uint8") if img.max() > 255 else img.astype("uint8")
        h, w = img.shape[:2]
        if max(h, w) > 1400:
            f = 1400 / max(h, w)
            img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        out = os.path.join("/tmp", "sf_prev_" + str(abs(hash(src + str(os.path.getmtime(src))))) + ".png")
        cv2.imwrite(out, img)
        return out

    def _set_preview(self, src):
        png = self._preview_png(src)
        self._preview_src = png
        if png:
            pix = QPixmap(png)
            if not pix.isNull():
                self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                  Qt.SmoothTransformation))
                self.preview.setToolTip(src)
                return
        self.preview.setText("(Vorschau nicht darstellbar)")

    def _sharpest_kept(self, result_path):
        """Schärfsten behaltenen Quell-Frame aus dem cull_report ziehen."""
        report = os.path.join(os.path.dirname(os.path.dirname(result_path)), "cull_report.json")
        if not os.path.isfile(report):
            return None
        try:
            import json as _json
            data = _json.load(open(report))
            kept = [f for f in data["frames"] if f.get("keep")]
            if kept:
                return max(kept, key=lambda f: f.get("peak_sharp", 0)).get("path")
        except Exception:
            pass
        return None

    def _representative_input(self):
        """Ein Original-Frame (mittlerer) als „Vorher“ für den Vergleich — modulübergreifend."""
        folder = self.in_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            return None
        try:
            import focus_cull_stack as F
            paths = F.list_images(folder)
            if not paths:  # Hybrid Fokus+Astro: Bilder liegen in Unterordnern
                for s in sorted(os.listdir(folder)):
                    sub = os.path.join(folder, s)
                    if os.path.isdir(sub):
                        paths = F.list_images(sub)
                        if paths:
                            break
            return paths[len(paths) // 2] if paths else None
        except Exception:
            return None

    def _show_result(self):
        res = self._find_result()
        if not res:
            self.preview.setText("(kein Stack-Output — Selektionslauf?)")
            return
        self.result_path = res
        # „Vorher“: schärfster behaltener Frame (Makro) — sonst ein repräsentatives Original
        self.before_path = self._sharpest_kept(res) or self._representative_input()
        self._set_preview(res)
        self.open_btn.setEnabled(True)
        self.openfolder_btn.setEnabled(True); self.adjust_btn.setEnabled(True)
        self.cmp_btn.setEnabled(bool(self.before_path))
        self.ghost_btn.setEnabled(bool(self._ghostmap_path()))
        self.send_btn.setEnabled(True); self.reimport_btn.setEnabled(True)
        # Retusche nur wo es Sinn macht (Fokus-Stacking): Makro + Hybrid Fokus+Astro
        fa = getattr(self, "is_hybrid", False) and self.hybrid_kind.currentData() == "fa"
        retouch_ok = (not getattr(self, "is_astro", False)
                      and not getattr(self, "is_longexp", False)
                      and (not getattr(self, "is_hybrid", False) or fa))
        self.retouch_btn.setVisible(retouch_ok)
        self.retouch_btn.setEnabled(retouch_ok)
        self._build_filmstrip(res)

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
        out = os.path.join("/tmp", "sf_th_" + str(abs(hash(src + str(os.path.getmtime(src))))) + ".png")
        cv2.imwrite(out, img)
        return out

    def open_result(self):
        if self.result_path:
            reveal_in_files(self.result_path)

    def open_folder(self):
        if self.result_path:
            open_path(os.path.dirname(self.result_path))

    def _best_export_file(self):
        """Bevorzugt das 32-bit-Linear-TIFF (für GraXpert/StarNet/PixInsight), sonst Ergebnis."""
        if self.result_path:
            d = os.path.dirname(self.result_path)
            for f in os.listdir(d):
                if "32bit" in f.lower() and f.lower().endswith((".tif", ".tiff")):
                    return os.path.join(d, f)
        return self.result_path

    def send_to_tool(self):
        f = self._best_export_file()
        if not f:
            return
        reveal_in_files(f)
        self._append(f"\n📤 Im Dateimanager: {os.path.basename(f)}\n   → in GraXpert / StarNet++ / "
                     "PixInsight öffnen, dann „📥 Bearbeitetes reimportieren“.\n")

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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        src = getattr(self, "_preview_src", None)
        if src:
            pix = QPixmap(src)
            if not pix.isNull():
                self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                  Qt.SmoothTransformation))

    # ---------- Einstellungen merken ----------
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
            "hybrid_kind": (lambda v: self.hybrid_kind.setCurrentIndex(int(v)), self.hybrid_kind.currentIndex),
            "hybrid_group": (lambda v: self.hybrid_group.setValue(int(v)), self.hybrid_group.value),
            "longexp_mode": (lambda v: self.longexp_mode.setCurrentIndex(int(v)), self.longexp_mode.currentIndex),
            "longexp_align": (lambda v: self.longexp_align.setCurrentIndex(int(v)), self.longexp_align.currentIndex),
            "longexp_strength": (lambda v: self.longexp_strength.setValue(int(v)), self.longexp_strength.value),
        }

    def _save_settings(self):
        st = QSettings("ServeOne", "StackForge")
        for k, (_set, get) in self._settings_map().items():
            st.setValue(k, get())

    def _restore_settings(self):
        st = QSettings("ServeOne", "StackForge")
        bool_keys = {"raw_dev", "raw_half", "vlm_on", "astro_fits"}
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

    def closeEvent(self, e):
        self._save_settings()
        QSettings("ServeOne", "StackForge").setValue("geometry", self.saveGeometry())
        super().closeEvent(e)


THEME = """
QWidget { background:#1a1326; color:#e8e3f5; font-size:13px; }
QGroupBox { border:1px solid #3a2d55; border-radius:8px; margin-top:14px; padding-top:8px; font-weight:bold; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; color:#b69bff; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background:#241a38; border:1px solid #3a2d55; border-radius:6px; padding:4px; color:#e8e3f5; }
QPlainTextEdit { background:#140f1f; }
QComboBox QAbstractItemView { background:#241a38; selection-background-color:#6b3fb0; }
QPushButton { background:#2e2247; border:1px solid #4a3a6e; border-radius:7px; padding:7px 12px; }
QPushButton:hover { background:#3c2d5e; }
QPushButton:pressed { background:#553f86; }
QPushButton:disabled { color:#6b6080; background:#221a33; }
QCheckBox::indicator, QGroupBox::indicator { width:16px; height:16px; }
QProgressBar { border:1px solid #3a2d55; border-radius:6px; background:#241a38; text-align:center; height:18px; }
QProgressBar::chunk { background:#8a5cff; border-radius:5px; }
QScrollBar:vertical { background:#1a1326; width:12px; } QScrollBar::handle:vertical { background:#3a2d55; border-radius:6px; }
QToolTip { background:#241a38; color:#e8e3f5; border:1px solid #6b3fb0; }
"""


def main():
    app = QApplication(sys.argv)
    # Sprache aus den Einstellungen laden, BEVOR die Oberfläche gebaut wird
    set_language(QSettings("ServeOne", "StackForge").value("language", "de"))
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
