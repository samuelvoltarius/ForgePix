#!/usr/bin/env python3
"""
ui/welcome.py — Startbildschirm & „Über"-Dialog für ForgePix (als Mixin in MainWindow gemischt).

Aus ui/main_window.py ausgelagert (Modularisierung). Methoden greifen über self auf das
MainWindow zu; reine UI-Erzeugung ohne eigene Zustandshaltung.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QPushButton, QDialog, QScrollArea)

from i18n import tr
from ui.settings_io import app_settings
from ui.appinfo import ICON_PNG


class WelcomeMixin:
    """Startbildschirm-Aufbau, Modul-Auswahl, Resume und „Über ForgePix"."""

    def _build_welcome(self):
        """Astro-first workspace entry with a clear primary action."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(48, 32, 48, 32)
        top = QHBoxLayout()
        brand = QLabel("ForgePix")
        brand.setStyleSheet("font-size:24px;font-weight:700;")
        top.addWidget(brand)
        self.update_lbl = QLabel("")
        self.update_lbl.setTextFormat(Qt.RichText)
        self.update_lbl.setOpenExternalLinks(True)
        self.update_lbl.hide()
        top.addWidget(self.update_lbl)
        top.addStretch()
        about = QPushButton(tr("Über ForgePix"))
        about.clicked.connect(self._show_about)
        settings = QPushButton(tr("Einstellungen"))
        settings.clicked.connect(self.settings_dialog.show)
        top.addWidget(about)
        top.addWidget(settings)
        outer.addLayout(top)
        outer.addStretch()
        body = QWidget()
        body.setMaximumWidth(880)
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(18)
        eyebrow = QLabel(tr("ASTROFOTOGRAFIE"))
        eyebrow.setObjectName("sectionHeader")
        content.addWidget(eyebrow)
        title = QLabel(tr("Mehr aus deinen Aufnahmen."))
        title.setWordWrap(True)
        title.setStyleSheet("font-size:36px;font-weight:600;")
        content.addWidget(title)
        description = QLabel(tr("FITS-Aufnahmen prüfen, ausrichten und zusammenfügen. "
                               "Danach entwickelst du dein Bild Schritt für Schritt."))
        description.setWordWrap(True)
        description.setObjectName("hint")
        content.addWidget(description)
        start = QPushButton(tr("Astro-Projekt starten"))
        start.setObjectName("primary")
        start.setMinimumHeight(46)
        start.clicked.connect(lambda: self._choose_module(1))
        content.addWidget(start)
        workflow = QLabel(tr("01  Aufnahmen     /     02  Kalibrierung & Stack     /     03  Entwicklung & Export"))
        workflow.setWordWrap(True)
        workflow.setObjectName("hint")
        content.addWidget(workflow)
        last = app_settings().value("in", "") or ""
        if last and os.path.isdir(last):
            resume = QPushButton(tr("Letzten Ordner öffnen") + ": " + os.path.basename(last.rstrip("/")))
            resume.clicked.connect(lambda: self._resume_last(last))
            content.addWidget(resume)
        content.addSpacing(28)
        other = QLabel(tr("Weitere Arbeitsbereiche"))
        other.setObjectName("hint")
        content.addWidget(other)
        tools = QHBoxLayout()
        for index, label in [(0, tr("Fokus-Stacking")), (2, tr("Mosaik")),
                             (3, tr("Langzeitbelichtung")), (4, tr("HDR"))]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, value=index: self._choose_module(value))
            tools.addWidget(button)
        content.addLayout(tools)
        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(body, 1)
        center.addStretch()
        outer.addLayout(center)
        outer.addStretch(2)
        return page

    def _resume_last(self, folder):
        """Zuletzt verwendeten Ordner + Modul wiederherstellen und in den Arbeitsbereich wechseln."""
        try:
            ti = int(app_settings().value("task_i", self.task_box.currentIndex()))
        except (TypeError, ValueError):
            ti = self.task_box.currentIndex()
        self._choose_module(ti)
        self.in_edit.setText(folder)

    def _choose_module(self, task_index):
        """Modul aus dem Startbildschirm wählen → Aufgabe setzen + in den Arbeitsbereich wechseln."""
        self.task_box.setCurrentIndex(task_index)
        self._set_task()
        self.top_stack.setCurrentIndex(1)

    def _show_about(self):
        """Kurze, klare Erklärung was ForgePix ist und kann (für Einsteiger)."""
        html = tr(
            "<h3>Was ist ForgePix?</h3>"
            "<p>ForgePix macht aus <b>vielen Fotos ein besseres Bild</b> — vollautomatisch, "
            "und es <b>erklärt dabei, was es tut</b>.</p>"
            "<p><b>🔬 Makro:</b> mehrere Nahaufnahmen mit wanderndem Fokus → ein durchgehend "
            "scharfes Bild.<br>"
            "<b>🌌 Astro:</b> viele Aufnahmen des Sternenhimmels → rauschfrei.<br>"
            "<b>🌗 Hybrid:</b> Mond-/Sonnen-Mosaik oder Fokus+Astro.<br>"
            "<b>📷 Langzeitbelichtung:</b> aus einer Serie ohne ND-Filter (seidiges Wasser, "
            "Lichtspuren …).</p>"
            "<p><b>So einfach:</b> Modul wählen → Ordner wählen (oder aufs Fenster ziehen) → "
            "⚡ Automatik. Im <b>Anfänger-Modus</b> genügt ein Klick; der <b>Profi-Modus</b> "
            "öffnet alle Regler.</p>"
            "<p>Die KI ist <b>optional</b> — alles läuft auch ohne Server. Sie <b>berät</b> nur "
            "und verändert nie heimlich Pixel.</p>"
            "<p style='color:#9aa09a'>Mehr in der Anleitung (docs/GUIDE) und mit dem „?“ an jeder "
            "Einstellung. Tastenkürzel: F1.</p>")
        dlg = QDialog(self); dlg.setWindowTitle(tr("Über ForgePix")); dlg.resize(520, 460)
        lay = QVBoxLayout(dlg)
        lbl = QLabel(html); lbl.setWordWrap(True); lbl.setTextFormat(Qt.RichText); lbl.setAlignment(Qt.AlignTop)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(lbl); lay.addWidget(sc)
        try:
            from constants import VERSION as _v
        except Exception:
            _v = ""
        web = QLabel(f"<a href='https://forgepix.app' style='color:#7bd36a'>forgepix.app</a>  ·  v{_v} · Beta")
        web.setOpenExternalLinks(True); web.setAlignment(Qt.AlignCenter)
        lay.addWidget(web)
        b = QPushButton(tr("Schließen")); b.clicked.connect(dlg.accept); lay.addWidget(b)
        dlg.show(); self._about_dlg = dlg
