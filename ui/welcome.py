#!/usr/bin/env python3
"""
ui/welcome.py — Startbildschirm & „Über"-Dialog für ForgePix (als Mixin in MainWindow gemischt).

Aus ui/main_window.py ausgelagert (Modularisierung). Methoden greifen über self auf das
MainWindow zu; reine UI-Erzeugung ohne eigene Zustandshaltung.
"""
import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QPushButton, QDialog, QScrollArea)

from i18n import tr
from ui.appinfo import ICON_PNG


class WelcomeMixin:
    """Startbildschirm-Aufbau, Modul-Auswahl, Resume und „Über ForgePix"."""

    def _build_welcome(self):
        """Start-Auswahlbildschirm: aufgeräumt, mit Logo, Modul-Karten und 3-Schritt-Ablauf."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 12, 16, 12)
        # Top-Bar: Einstellungen schon am Start erreichbar (Sprache/Anfänger-Profi/KI)
        topbar = QHBoxLayout()
        # Update-Hinweis (links, erscheint nur wenn eine neuere Version gefunden wurde)
        self.update_lbl = QLabel(""); self.update_lbl.setTextFormat(Qt.RichText)
        self.update_lbl.setOpenExternalLinks(True); self.update_lbl.setVisible(False)
        self.update_lbl.setStyleSheet("background:#1c2a1c;border:1px solid #2f5a32;border-radius:9px;"
                                      "padding:5px 12px;color:#9be39b;font-size:12px;font-weight:600;")
        topbar.addWidget(self.update_lbl)
        topbar.addStretch(1)
        info_btn = QPushButton(tr("ℹ️  Was ist das?"))
        info_btn.setToolTip(tr("Kurz erklärt, was ForgePix macht."))
        info_btn.clicked.connect(self._show_about)
        wset_btn = QPushButton(tr("⚙  Einstellungen"))
        wset_btn.setToolTip(tr("Sprache, Anfänger/Profi, KI-Server — schon vor dem Start einstellbar."))
        wset_btn.clicked.connect(self.settings_dialog.show)
        topbar.addWidget(info_btn); topbar.addWidget(wset_btn)
        outer.addLayout(topbar)
        outer.addStretch(1)

        # zentrierter Inhalts-Container mit fester Maximalbreite (auch auf breiten Screens schön)
        center = QHBoxLayout(); outer.addLayout(center)
        center.addStretch(1)
        box = QWidget(); box.setMaximumWidth(880); center.addWidget(box); center.addStretch(1)
        lay = QVBoxLayout(box); lay.setContentsMargins(24, 0, 24, 0); lay.setSpacing(0)

        # Logo + Titel
        if os.path.isfile(ICON_PNG):
            logo = QLabel(); logo.setAlignment(Qt.AlignCenter)
            logo.setPixmap(QPixmap(ICON_PNG).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            lay.addWidget(logo); lay.addSpacing(8)
        head = QLabel("ForgePix")
        head.setStyleSheet("font-size:32px;font-weight:800;letter-spacing:0.5px;")
        head.setAlignment(Qt.AlignCenter); lay.addWidget(head)
        tag = QLabel(tr("Fotos rein – fertiges Bild raus."))
        tag.setStyleSheet("color:#9aa09a;font-size:13px;"); tag.setAlignment(Qt.AlignCenter)
        lay.addWidget(tag); lay.addSpacing(20)
        sub = QLabel(tr("Schritt 1: Wähle ein Modul"))
        sub.setStyleSheet("color:#7bd36a;font-size:14px;font-weight:700;letter-spacing:0.3px;")
        sub.setAlignment(Qt.AlignCenter); lay.addWidget(sub); lay.addSpacing(16)

        grid = QGridLayout(); grid.setSpacing(18)
        # (Modul, großes Emoji, Titel, Kategorie, Beispiele, Empfehlungs-Pill)
        cards = [
            (0, "🔬", tr("Makro"), tr("Fokus-Stacking"),
             tr("Produkte · Münzen · Insekten · Food"), tr("10–40 Aufnahmen")),
            (1, "🌌", tr("Astro"), tr("Deep-Sky / Sterne"),
             tr("Milchstraße · Nebel · Galaxien"), tr("20–100+ Lights")),
            (2, "🌗", tr("Hybrid"), tr("Mosaik & Fokus+Astro"),
             tr("Mond · Sonne · große Panoramen"), tr("4–20+ Kacheln")),
            (3, "📷", tr("Langzeit"), tr("Belichtung ohne ND-Filter"),
             tr("Wasser · Wolken · Lichtspuren"), tr("10–300+ Bilder")),
        ]
        for n, (idx, emoji, name, cat, examples, pill) in enumerate(cards):
            card = QPushButton(); card.setCursor(Qt.PointingHandCursor); card.setMinimumHeight(212)
            card.setObjectName("card")
            cv = QVBoxLayout(card); cv.setContentsMargins(20, 20, 20, 18); cv.setSpacing(4)
            el = QLabel(emoji); el.setAlignment(Qt.AlignCenter); el.setStyleSheet("font-size:54px;")
            tl = QLabel(name); tl.setAlignment(Qt.AlignCenter)
            tl.setStyleSheet("font-size:22px;font-weight:800;color:#e8eae6;")
            cl = QLabel(cat); cl.setAlignment(Qt.AlignCenter)
            cl.setStyleSheet("color:#7bd36a;font-size:13px;font-weight:600;")
            xl = QLabel(examples); xl.setWordWrap(True); xl.setAlignment(Qt.AlignCenter)
            xl.setStyleSheet("color:#9aa09a;font-size:12px;")
            pl = QLabel(pill); pl.setAlignment(Qt.AlignCenter)
            pl.setStyleSheet("color:#7bd36a;background:#1c2a1c;border-radius:9px;"
                             "padding:3px 12px;font-size:11px;font-weight:600;")
            for w in (el, tl, cl, xl, pl):
                w.setAttribute(Qt.WA_TransparentForMouseEvents)  # Klicks gehen an die Karte
            cv.addWidget(el); cv.addSpacing(2); cv.addWidget(tl); cv.addWidget(cl)
            cv.addSpacing(4); cv.addWidget(xl); cv.addStretch(1)
            row = QHBoxLayout(); row.addStretch(1); row.addWidget(pl); row.addStretch(1); cv.addLayout(row)
            card.clicked.connect(lambda _=False, t=idx: self._choose_module(t))
            grid.addWidget(card, n // 2, n % 2)
        lay.addLayout(grid)
        lay.addSpacing(20)
        steps = QLabel(tr("So geht's:&nbsp;&nbsp; <b style='color:#7bd36a'>1</b> Modul wählen &nbsp;→&nbsp; "
                          "<b style='color:#7bd36a'>2</b> Ordner wählen oder aufs Fenster ziehen &nbsp;→&nbsp; "
                          "<b style='color:#7bd36a'>3</b> ⚡ Automatik"))
        steps.setTextFormat(Qt.RichText); steps.setAlignment(Qt.AlignCenter)
        steps.setStyleSheet("font-size:13px;color:#b9bdb6;")
        lay.addWidget(steps)

        # „Weiter wo du warst" — zuletzt verwendeten Ordner mit einem Klick wieder laden
        last = QSettings("ServeOne", "ForgePix").value("in", "") or ""
        if last and os.path.isdir(last):
            lay.addSpacing(14)
            rrow = QHBoxLayout(); rrow.addStretch(1)
            resume = QPushButton("↩  " + tr("Weiter") + ":  " + os.path.basename(last.rstrip("/")))
            resume.setObjectName("chip"); resume.setCursor(Qt.PointingHandCursor)
            resume.setToolTip(tr("Zuletzt verwendeten Ordner wieder öffnen") + ":\n" + last)
            resume.clicked.connect(lambda: self._resume_last(last))
            rrow.addWidget(resume); rrow.addStretch(1); lay.addLayout(rrow)

        outer.addStretch(2)
        return page

    def _resume_last(self, folder):
        """Zuletzt verwendeten Ordner + Modul wiederherstellen und in den Arbeitsbereich wechseln."""
        try:
            ti = int(QSettings("ServeOne", "ForgePix").value("task_i", self.task_box.currentIndex()))
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
