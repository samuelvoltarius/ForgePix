"""Zusatzprogramme: was ForgePix nutzen kann, ob es gefunden wurde, und ein Knopf zur offiziellen
Download-Seite. Nichts wird von hier aus installiert — der Knopf öffnet nur den Browser."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QHBoxLayout)

import zusatzprogramme
from i18n import tr


class ZusatzprogrammeDialog(QDialog):
    def __init__(self, parent=None, oeffnen=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Zusatzprogramme"))
        self.resize(1000, 520)
        self._oeffnen = oeffnen or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        lay = QVBoxLayout(self)
        erklaerung = QLabel(tr(
            "ForgePix ruft diese Programme auf, liefert sie aber nicht mit — ihre Lizenzen erlauben "
            "das nicht, oder es sind eigene große Programme. „Herunterladen“ öffnet die offizielle "
            "Seite im Browser. Nach der Installation ForgePix neu starten oder „Neu suchen“."))
        erklaerung.setWordWrap(True)
        lay.addWidget(erklaerung)
        self.tabelle = QTableWidget(0, 5)
        self.tabelle.setHorizontalHeaderLabels([tr("Programm"), tr("Wofür"), tr("Systeme"), tr("Gefunden"), ""])
        self.tabelle.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabelle.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabelle.verticalHeader().setVisible(False)
        lay.addWidget(self.tabelle, 1)
        zeile = QHBoxLayout()
        neu = QPushButton(tr("Neu suchen"))
        neu.clicked.connect(self.fuellen)
        zeile.addStretch(1); zeile.addWidget(neu)
        lay.addLayout(zeile)
        self.fuellen()

    def fuellen(self):
        self.stand = zusatzprogramme.stand()
        self.tabelle.setRowCount(len(self.stand))
        for i, s in enumerate(self.stand):
            wofuer = tr(s["wofuer"]) + (("\n" + tr(s["hinweis"])) if s["hinweis"] else "")
            gefunden = s["pfad"] or tr("nicht gefunden")
            for spalte, text in enumerate((s["name"], wofuer, tr(s["systeme"]), gefunden)):
                feld = QTableWidgetItem(text)
                feld.setToolTip(text)
                self.tabelle.setItem(i, spalte, feld)
            knopf = QPushButton(tr("Herunterladen") if not s["pfad"] else tr("Seite öffnen"))
            knopf.setToolTip(s["url"])
            knopf.clicked.connect(lambda _=False, url=s["url"]: self._oeffnen(url))
            self.tabelle.setCellWidget(i, 4, knopf)
        self.tabelle.resizeRowsToContents()
