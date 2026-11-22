"""Aufnahme steuern: eigene Geräte über ASCOM Alpaca oder ein vorhandenes N.I.N.A.

Zwei Wege in einem Fenster, beide laufen unter Windows, macOS und Linux, weil beide übers Netz
sprechen: die Geräte (oder N.I.N.A.) können am Teleskop-Rechner hängen, ForgePix läuft dort
oder am Schreibtisch. Die Rechnung steckt in core/alpaca.py, core/aufnahme.py und core/nina.py;
hier wird nur eingesammelt, angezeigt und im Hintergrund-Thread gestartet.
"""
import os

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QTabWidget, QWidget,
    QTableWidget, QHeaderView, QPlainTextEdit, QFileDialog, QCheckBox, QMessageBox)

import alpaca
import aufnahme
import indi
import nina
from i18n import tr
from ui.workers import _ToolWorker

_TYPEN_ALPACA = (("camera", "Kamera"), ("filterwheel", "Filterrad"),
                 ("focuser", "Fokussierer"), ("telescope", "Montierung"))


def _vorschau_pixmap(bild, breite=480):
    """Rohbild (uint16, ggf. Bayer) gestreckt als Graustufen-Vorschau."""
    import astro
    import cv2
    f = np.asarray(bild, np.float32)
    if f.ndim == 3:
        f = f.mean(axis=2)
    spanne = float(f.max() - f.min()) or 1.0
    g = astro.autostretch(np.dstack([(f - f.min()) / spanne] * 3))
    g = (np.clip(g, 0, 1) * 255).astype(np.uint8)
    h, w = g.shape[:2]
    g = cv2.resize(g, (breite, max(1, int(h * breite / w))), interpolation=cv2.INTER_AREA)
    from ui.components import _bgr_to_pixmap
    return _bgr_to_pixmap(g, max_w=breite)[0]          # liefert (pixmap, scale)


class AufnahmeDialog(QDialog):
    def __init__(self, parent=None, ordner_uebernehmen=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Aufnahme steuern"))
        self.resize(900, 720)
        self._ordner_uebernehmen = ordner_uebernehmen
        self._worker = None
        self._lauf = None
        self._geraete = {}
        self._nina_schon = set()
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._seite_alpaca(), tr("Eigene Geräte (Alpaca / INDI)"))
        tabs.addTab(self._seite_nina(), tr("N.I.N.A. fernsteuern"))
        layout.addWidget(tabs, 3)
        self.vorschau = QLabel(tr("Noch keine Testaufnahme."))
        self.vorschau.setAlignment(Qt.AlignCenter)
        self.vorschau.setMinimumHeight(160)
        layout.addWidget(self.vorschau, 2)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        layout.addWidget(self.log, 2)
        self._nina_timer = QTimer(self)
        self._nina_timer.setInterval(15000)
        self._nina_timer.timeout.connect(self._nina_abholen)

    # ------------------------------------------------------------------ Hilfen ------------
    def _schreiben(self, text):
        self.log.appendPlainText(str(text).rstrip("\n"))

    def _im_hintergrund(self, fn, fertig=None):
        if self._worker is not None and self._worker.isRunning():
            self._schreiben(tr("Es läuft noch ein Vorgang. Bitte warten."))
            return False
        wk = _ToolWorker(fn)
        wk.log.connect(self._schreiben)
        wk.failed.connect(lambda m: (self._schreiben("⚠️ " + m),
                                     QMessageBox.warning(self, tr("Aufnahme steuern"), m)))
        if fertig:
            wk.done.connect(fertig)
        self._worker = wk
        wk.start()
        return True

    def _ordner_feld(self):
        feld = QLineEdit()
        knopf = QPushButton(tr("Wählen…"))

        def waehlen():
            pfad = QFileDialog.getExistingDirectory(self, tr("Zielordner"), feld.text())
            if pfad:
                feld.setText(pfad)
        knopf.clicked.connect(waehlen)
        zeile = QHBoxLayout(); zeile.addWidget(feld, 1); zeile.addWidget(knopf)
        return feld, zeile

    # ------------------------------------------------------------------ Alpaca ------------
    def _seite_alpaca(self):
        seite = QWidget(); lay = QVBoxLayout(seite)
        hinweis = QLabel(tr(
            "ForgePix spricht die Geräte selbst an. ASCOM Alpaca: Geräte mit Alpaca (z. B. "
            "Seestar), jedes ASCOM-Gerät unter Windows über „ASCOM Remote“, die ASCOM-Simulatoren. "
            "INDI: die Treiber unter Linux und macOS (indiserver, z. B. auf einem Raspberry Pi am "
            "Teleskop, Astroberry, StellarMate, KStars/Ekos)."))
        hinweis.setWordWrap(True); lay.addWidget(hinweis)
        zeile = QHBoxLayout()
        self.a_art = QComboBox()
        self.a_art.addItem(tr("ASCOM Alpaca"), "alpaca")
        self.a_art.addItem(tr("INDI (indiserver)"), "indi")
        zeile.addWidget(self.a_art)
        self.a_host = QLineEdit("127.0.0.1")
        self.a_port = QSpinBox(); self.a_port.setRange(1, 65535); self.a_port.setValue(11111)
        suchen = QPushButton(tr("Im Netz suchen"))
        laden = QPushButton(tr("Geräte laden"))
        zeile.addWidget(QLabel(tr("Rechner"))); zeile.addWidget(self.a_host, 1)
        zeile.addWidget(QLabel(tr("Port"))); zeile.addWidget(self.a_port)
        zeile.addWidget(suchen); zeile.addWidget(laden)
        lay.addLayout(zeile)
        form = QFormLayout()
        self.a_wahl = {}
        for typ, name in _TYPEN_ALPACA:
            box = QComboBox(); box.addItem(tr("— keins —"), None)
            self.a_wahl[typ] = box
            form.addRow(tr(name), box)
        lay.addLayout(form)
        zeile = QHBoxLayout()
        verbinden = QPushButton(tr("Verbinden")); verbinden.setObjectName("primary")
        trennen = QPushButton(tr("Trennen"))
        self.a_status = QLabel(tr("Nicht verbunden."))
        self.a_status.setWordWrap(True)
        zeile.addWidget(verbinden); zeile.addWidget(trennen); zeile.addWidget(self.a_status, 1)
        lay.addLayout(zeile)
        zeile = QHBoxLayout()
        self.a_test = QDoubleSpinBox(); self.a_test.setRange(0.0, 3600.0); self.a_test.setValue(2.0)
        self.a_test.setSuffix(" s")
        test = QPushButton(tr("Testaufnahme"))
        zeile.addWidget(QLabel(tr("Belichtung"))); zeile.addWidget(self.a_test); zeile.addWidget(test)
        zeile.addStretch(1)
        lay.addLayout(zeile)

        lay.addWidget(QLabel(tr("Ablaufplan")))
        self.plan = QTableWidget(0, 4)
        self.plan.setHorizontalHeaderLabels([tr("Anzahl"), tr("Belichtung (s)"), tr("Typ"), tr("Filter")])
        self.plan.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.plan, 1)
        zeile = QHBoxLayout()
        plus = QPushButton(tr("Schritt hinzufügen")); minus = QPushButton(tr("Schritt entfernen"))
        zeile.addWidget(plus); zeile.addWidget(minus); zeile.addStretch(1)
        lay.addLayout(zeile)
        form = QFormLayout()
        self.a_objekt = QLineEdit(); self.a_objekt.setPlaceholderText(tr("z. B. M 27"))
        form.addRow(tr("Objekt"), self.a_objekt)
        self.a_ordner, ordner_zeile = self._ordner_feld()
        form.addRow(tr("Zielordner"), ordner_zeile)
        lay.addLayout(form)
        self.a_uebernehmen = QCheckBox(tr("Zielordner als Eingabe in ForgePix übernehmen (zum Live-Stapeln)"))
        self.a_uebernehmen.setChecked(True)
        lay.addWidget(self.a_uebernehmen)
        zeile = QHBoxLayout()
        self.a_start = QPushButton(tr("Ablaufplan starten")); self.a_start.setObjectName("primary")
        self.a_stopp = QPushButton(tr("Stopp")); self.a_stopp.setEnabled(False)
        zeile.addWidget(self.a_start); zeile.addWidget(self.a_stopp); zeile.addStretch(1)
        lay.addLayout(zeile)

        def art_gewechselt():
            ist_indi = self.a_art.currentData() == "indi"
            self.a_port.setValue(indi.STANDARD_PORT if ist_indi else 11111)
            suchen.setEnabled(not ist_indi)              # INDI hat keine Netzsuche
            self._indi_schliessen()
        self.a_art.currentIndexChanged.connect(art_gewechselt)
        suchen.clicked.connect(self._alpaca_suchen)
        laden.clicked.connect(self._alpaca_laden)
        verbinden.clicked.connect(self._alpaca_verbinden)
        trennen.clicked.connect(self._alpaca_trennen)
        test.clicked.connect(self._alpaca_test)
        plus.clicked.connect(lambda: self._schritt_hinzu())
        minus.clicked.connect(lambda: self.plan.removeRow(max(self.plan.currentRow(), self.plan.rowCount() - 1))
                              if self.plan.rowCount() else None)
        self.a_start.clicked.connect(self._alpaca_start)
        self.a_stopp.clicked.connect(self._alpaca_stopp)
        self._filter_namen = []
        self._schritt_hinzu()
        return seite

    def _modul(self):
        return indi if self.a_art.currentData() == "indi" else alpaca

    def _server(self):
        """Alpaca fragt je Anfrage neu; INDI hält eine Verbindung — die wird wiederverwendet,
        solange Rechner und Port gleich bleiben."""
        if self.a_art.currentData() != "indi":
            return alpaca.Server(self.a_host.text(), self.a_port.value())
        ziel = (self.a_host.text().strip(), self.a_port.value())
        alt = getattr(self, "_indi_server", None)
        if alt is not None and (alt.host, alt.port) == ziel:
            return alt
        self._indi_schliessen()
        self._indi_server = indi.Server(*ziel)
        return self._indi_server

    def _indi_schliessen(self):
        alt = getattr(self, "_indi_server", None)
        if alt is not None:
            alt.schliessen()
        self._indi_server = None

    def _schritt_hinzu(self, anzahl=10, belichtung=60.0):
        zeile = self.plan.rowCount()
        self.plan.insertRow(zeile)
        n = QSpinBox(); n.setRange(1, 10000); n.setValue(anzahl)
        b = QDoubleSpinBox(); b.setRange(0.0, 3600.0); b.setDecimals(3); b.setValue(belichtung)
        t = QComboBox()
        for typ in aufnahme.TYPEN:
            t.addItem(typ)
        f = QComboBox(); f.addItem(tr("— ohne Filterrad —"), None)
        for name in self._filter_namen:
            f.addItem(name, name)
        for spalte, w in enumerate((n, b, t, f)):
            self.plan.setCellWidget(zeile, spalte, w)

    def _alpaca_suchen(self):
        def suchen(log):
            return alpaca.suchen()

        def fertig(gefunden):
            if not gefunden:
                self._schreiben(tr("Kein Alpaca-Server hat geantwortet. Adresse von Hand eintragen "
                                   "(manche Netze sperren die Suche)."))
                return
            host, port = gefunden[0]
            self.a_host.setText(host); self.a_port.setValue(port)
            self._schreiben(tr("Gefunden: {liste}").format(
                liste=", ".join("%s:%d" % g for g in gefunden)))
        self._im_hintergrund(suchen, fertig)

    def _alpaca_laden(self):
        server = self._server()

        def fertig(liste):
            for typ, box in self.a_wahl.items():
                box.clear(); box.addItem(tr("— keins —"), None)
                for g in liste:
                    if g["typ"] == typ:
                        text = g["name"] if isinstance(g["nummer"], str) else "%s (#%d)" % (g["name"], g["nummer"])
                        box.addItem(text, g["nummer"])
                if box.count() > 1:
                    box.setCurrentIndex(1)
            self._schreiben(tr("{n} Geräte gefunden.").format(n=len(liste)))
        self._im_hintergrund(lambda log: server.geraete(), fertig)

    def _gewaehlt(self):
        server = self._server()
        m = self._modul()
        klassen = {"camera": m.Kamera, "filterwheel": m.Filterrad,
                   "focuser": m.Fokussierer, "telescope": m.Montierung}
        return {typ: klassen[typ](server, box.currentData())
                for typ, box in self.a_wahl.items() if box.currentData() is not None}

    def _alpaca_verbinden(self):
        geraete = self._gewaehlt()
        if not geraete:
            self._schreiben(tr("Zuerst „Geräte laden“ und mindestens ein Gerät wählen."))
            return

        def verbinden(log):
            # Jedes Gerät für sich: eine streikende Montierung darf die Kamera nicht mitreißen.
            # Was scheitert, wird genannt und bleibt draußen.
            stand, fehler = {}, []
            for typ, g in geraete.items():
                try:
                    g.verbinden()
                except Exception as e:                   # noqa: BLE001 — wird gemeldet
                    fehler.append("%s: %s" % (g.name, e))
                    log("⚠️ " + tr("Nicht verbunden: {name} — {grund}").format(name=g.name, grund=e))
                    continue
                stand[typ] = g
                log(tr("Verbunden: {name}").format(name=g.name))
            if not stand:
                raise RuntimeError("; ".join(fehler))
            namen = stand["filterwheel"].namen() if "filterwheel" in stand else []
            return stand, namen, fehler

        def fertig(ergebnis):
            stand, namen, fehler = ergebnis
            self._geraete = stand
            self._filter_namen = namen
            text = ", ".join(g.name for g in stand.values())
            if fehler:
                text += " — " + tr("nicht verbunden: {liste}").format(
                    liste=", ".join(f.split(":")[0] for f in fehler))
            self.a_status.setText(text)
            for zeile in range(self.plan.rowCount()):
                box = self.plan.cellWidget(zeile, 3)
                aktuell = box.currentData()
                box.clear(); box.addItem(tr("— ohne Filterrad —"), None)
                for name in namen:
                    box.addItem(name, name)
                if aktuell in namen:
                    box.setCurrentIndex(namen.index(aktuell) + 1)
        self._im_hintergrund(verbinden, fertig)

    def _alpaca_trennen(self):
        geraete = self._geraete

        def trennen(log):
            for g in geraete.values():
                g.trennen()
            return True

        def fertig(_):
            self._geraete = {}
            self.a_status.setText(tr("Nicht verbunden."))
        self._im_hintergrund(trennen, fertig)

    def _alpaca_test(self):
        kamera = self._geraete.get("camera")
        if kamera is None:
            self._schreiben(tr("Keine Kamera verbunden."))
            return
        dauer = self.a_test.value()
        self._im_hintergrund(lambda log: kamera.belichten(dauer),
                             lambda bild: self.vorschau.setPixmap(_vorschau_pixmap(bild)))

    def _plan_lesen(self):
        plan = []
        for zeile in range(self.plan.rowCount()):
            plan.append(aufnahme.Schritt(self.plan.cellWidget(zeile, 0).value(),
                                         self.plan.cellWidget(zeile, 1).value(),
                                         self.plan.cellWidget(zeile, 2).currentText(),
                                         self.plan.cellWidget(zeile, 3).currentData()))
        return plan

    def _alpaca_start(self):
        kamera = self._geraete.get("camera")
        ordner = self.a_ordner.text().strip()
        if kamera is None or not ordner:
            QMessageBox.information(self, tr("Aufnahme steuern"),
                                    tr("Bitte zuerst eine Kamera verbinden und einen Zielordner wählen."))
            return
        try:
            plan = self._plan_lesen()
            lauf = aufnahme.Lauf(kamera, plan, ordner, filterrad=self._geraete.get("filterwheel"),
                                 montierung=self._geraete.get("telescope"),
                                 objekt=self.a_objekt.text().strip() or None, log=self._schreiben)
        except ValueError as e:
            QMessageBox.warning(self, tr("Aufnahme steuern"), str(e))
            return
        if self.a_uebernehmen.isChecked() and self._ordner_uebernehmen:
            os.makedirs(ordner, exist_ok=True)
            self._ordner_uebernehmen(ordner)

        def laufen(log):
            lauf.log = log
            return lauf.ausfuehren()

        def fertig(_):
            self.a_start.setEnabled(True); self.a_stopp.setEnabled(False)
            self._lauf = None
        if self._im_hintergrund(laufen, fertig):
            self._lauf = lauf
            self._worker.failed.connect(lambda _m: fertig(None))
            self.a_start.setEnabled(False); self.a_stopp.setEnabled(True)

    def _alpaca_stopp(self):
        if self._lauf is not None:
            self._lauf.abbrechen()
            self._schreiben(tr("Stopp angefordert — die laufende Belichtung wird abgebrochen."))

    # ------------------------------------------------------------------ N.I.N.A. ----------
    def _seite_nina(self):
        seite = QWidget(); lay = QVBoxLayout(seite)
        hinweis = QLabel(tr(
            "Ein vorhandenes N.I.N.A. (Windows) von hier aus steuern. Dort muss das Plugin "
            "„Advanced API“ installiert und eingeschaltet sein."))
        hinweis.setWordWrap(True); lay.addWidget(hinweis)
        zeile = QHBoxLayout()
        self.n_host = QLineEdit("127.0.0.1")
        self.n_port = QSpinBox(); self.n_port.setRange(1, 65535); self.n_port.setValue(nina.STANDARD_PORT)
        verbinden = QPushButton(tr("Verbinden")); verbinden.setObjectName("primary")
        zeile.addWidget(QLabel(tr("Rechner"))); zeile.addWidget(self.n_host, 1)
        zeile.addWidget(QLabel(tr("Port"))); zeile.addWidget(self.n_port); zeile.addWidget(verbinden)
        lay.addLayout(zeile)
        self.n_status = QLabel(tr("Nicht verbunden.")); self.n_status.setWordWrap(True)
        self.n_status.setTextFormat(Qt.PlainText)
        lay.addWidget(self.n_status, 1)
        zeile = QHBoxLayout()
        start = QPushButton(tr("Ablaufplan starten")); stopp = QPushButton(tr("Ablaufplan stoppen"))
        status = QPushButton(tr("Status"))
        self.n_test = QDoubleSpinBox(); self.n_test.setRange(0.001, 3600.0); self.n_test.setValue(2.0)
        self.n_test.setSuffix(" s")
        test = QPushButton(tr("Testaufnahme"))
        for w in (start, stopp, status, self.n_test, test):
            zeile.addWidget(w)
        zeile.addStretch(1)
        lay.addLayout(zeile)
        form = QFormLayout()
        self.n_ordner, ordner_zeile = self._ordner_feld()
        form.addRow(tr("Zielordner"), ordner_zeile)
        lay.addLayout(form)
        zeile = QHBoxLayout()
        holen = QPushButton(tr("Gespeicherte Bilder abholen"))
        self.n_auto = QCheckBox(tr("alle 15 s automatisch abholen"))
        zeile.addWidget(holen); zeile.addWidget(self.n_auto); zeile.addStretch(1)
        lay.addLayout(zeile)
        hinweis = QLabel(tr(
            "Testaufnahmen liefert N.I.N.A. nur als Vorschaubild. Rohdaten zum Stapeln gibt es für "
            "Bilder, die ein Ablaufplan in N.I.N.A. gespeichert hat."))
        hinweis.setWordWrap(True); lay.addWidget(hinweis)

        verbinden.clicked.connect(self._nina_verbinden)
        start.clicked.connect(lambda: self._nina_befehl("start"))
        stopp.clicked.connect(lambda: self._nina_befehl("stop"))
        status.clicked.connect(lambda: self._nina_befehl("status"))
        test.clicked.connect(self._nina_test)
        holen.clicked.connect(self._nina_abholen)
        self.n_auto.toggled.connect(lambda an: self._nina_timer.start() if an else self._nina_timer.stop())
        return seite

    def _nina(self):
        return nina.Nina(self.n_host.text(), self.n_port.value())

    def _nina_verbinden(self):
        n = self._nina()

        def abfragen(log):
            return n.version(), n.geraete()

        def fertig(ergebnis):
            version, geraete = ergebnis
            zeilen = [tr("N.I.N.A. {nina}, Advanced API {api}").format(**version)]
            for name, g in geraete.items():
                zeilen.append("  %s: %s" % (name, g["name"] if g["verbunden"] else tr("nicht verbunden")))
            self.n_status.setText("\n".join(zeilen))
        self._im_hintergrund(abfragen, fertig)

    def _nina_befehl(self, was):
        n = self._nina()

        def befehl(log):
            if was == "start":
                n.sequenz_start()
            elif was == "stop":
                n.sequenz_stop()
            return nina.sequenz_zusammenfassung(n.sequenz_status())
        self._im_hintergrund(befehl, self._schreiben)

    def _nina_test(self):
        import tempfile
        n = self._nina()
        dauer = self.n_test.value()
        ziel = os.path.join(tempfile.gettempdir(), "forgepix_nina_vorschau.png")
        self._im_hintergrund(lambda log: n.testaufnahme(dauer, ziel),
                             lambda pfad: self.vorschau.setPixmap(
                                 QPixmap(pfad).scaledToWidth(480, Qt.SmoothTransformation)))

    def _nina_abholen(self):
        ordner = self.n_ordner.text().strip()
        if not ordner:
            self._schreiben(tr("Bitte zuerst einen Zielordner wählen."))
            self.n_auto.setChecked(False)
            return
        if self._worker is not None and self._worker.isRunning():
            return                                       # der Takt wartet einfach auf die nächste Runde
        n = self._nina()
        schon = self._nina_schon

        def holen(log):
            return n.neue_bilder_holen(ordner, schon)

        def fertig(neu):
            self._schreiben(tr("{n} neue Bilder abgeholt.").format(n=len(neu)))
        self._im_hintergrund(holen, fertig)

    def closeEvent(self, event):
        self._nina_timer.stop()
        self._indi_schliessen()
        if self._lauf is not None:
            self._lauf.abbrechen()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(5000)
        super().closeEvent(event)
