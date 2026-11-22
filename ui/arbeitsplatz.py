"""Arbeitsplatz im PixInsight-Stil: ein Bild offen, jedes Werkzeug darauf, mit Maske und Verlauf.

Links die Werkzeuge (gruppiert, durchsuchbar, mit dem Namen des Vorbilds), in der Mitte das
Bild — wahlweise mit Bildschirm-Streckung (STF), die nur die ANZEIGE streckt, nie die Daten —,
rechts die Einstellungen und die Maske, unten der Verlauf. Die Rechnung steckt in
core/prozesse.py; hier wird nur eingesammelt, angezeigt und im Hintergrund gestartet."""
import json
import os

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QListWidget, QSplitter, QWidget, QScrollArea, QFileDialog, QMessageBox, QGroupBox, QPlainTextEdit)

import prozesse
from i18n import tr
from ui.workers import _ToolWorker

_ANZEIGE_MAX = 1400        # Kantenlänge der Anzeige; die Daten bleiben in voller Größe


class _Bildflaeche(QLabel):
    """Zeigt das Bild und meldet, welches Datenpixel unter dem Mauszeiger liegt."""

    def __init__(self, melden):
        super().__init__(tr("Kein Bild geöffnet."))
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)
        self._melden, self._massstab, self._groesse = melden, 1.0, (0, 0)

    def setzen(self, pixmap, massstab, groesse):
        self.setPixmap(pixmap)
        self._massstab, self._groesse = massstab, groesse

    def mouseMoveEvent(self, event):
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return
        dx = (self.width() - pm.width()) / 2.0
        dy = (self.height() - pm.height()) / 2.0
        x = int((event.position().x() - dx) / self._massstab)
        y = int((event.position().y() - dy) / self._massstab)
        if 0 <= x < self._groesse[1] and 0 <= y < self._groesse[0]:
            self._melden(x, y)


class Arbeitsplatz(QDialog):
    def __init__(self, parent=None, pfad=None, uebernehmen=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Arbeitsplatz"))
        self.resize(1400, 900)
        self._uebernehmen = uebernehmen
        self.arbeit = None
        self.kopf = None
        self.quelle = None
        self._worker = None
        self._zeige_maske = None
        self._probe = None
        self.prozess = None
        self._felder = {}
        self._baue()
        if pfad:
            self.oeffnen(pfad)

    # ------------------------------------------------------------------ Aufbau ------------
    def _baue(self):
        lay = QVBoxLayout(self)
        leiste = QHBoxLayout()
        self.k_oeffnen = QPushButton(tr("Öffnen…"))
        self.k_speichern = QPushButton(tr("Speichern…"))
        self.k_zurueck = QPushButton(tr("Rückgängig"))
        self.k_vor = QPushButton(tr("Wiederholen"))
        self.k_rezept = QPushButton(tr("Verlauf als Rezept speichern…"))
        self.k_rezept_laden = QPushButton(tr("Rezept anwenden…"))
        self.stf = QCheckBox(tr("Anzeige strecken (STF)"))
        self.stf.setChecked(True)
        self.stf.setToolTip(tr("Streckt nur die Anzeige, nie die Daten — wie PixInsights ScreenTransferFunction."))
        self.vorher = QCheckBox(tr("Original zeigen"))
        for w in (self.k_oeffnen, self.k_speichern, self.k_zurueck, self.k_vor, self.k_rezept,
                  self.k_rezept_laden, self.stf, self.vorher):
            leiste.addWidget(w)
        leiste.addStretch(1)
        self.pixelwert = QLabel("")
        self.pixelwert.setTextInteractionFlags(Qt.TextSelectableByMouse)
        leiste.addWidget(self.pixelwert)
        lay.addLayout(leiste)

        teiler = QSplitter(Qt.Horizontal)
        links = QWidget(); ll = QVBoxLayout(links)
        self.suche = QLineEdit(); self.suche.setPlaceholderText(tr("Werkzeug suchen (auch PixInsight-/Siril-Namen)"))
        self.baum = QTreeWidget(); self.baum.setHeaderHidden(True)
        ll.addWidget(self.suche); ll.addWidget(self.baum, 1)
        self._baum_fuellen()
        teiler.addWidget(links)

        self.flaeche = _Bildflaeche(self._pixel_melden)
        rollen = QScrollArea(); rollen.setWidgetResizable(True); rollen.setWidget(self.flaeche)
        teiler.addWidget(rollen)

        rechts = QWidget(); rl = QVBoxLayout(rechts)
        self.p_name = QLabel(tr("Werkzeug links wählen.")); self.p_name.setWordWrap(True)
        self.p_name.setStyleSheet("font-weight:600;font-size:14px;")
        self.p_vorbild = QLabel(""); self.p_vorbild.setWordWrap(True)
        self.p_text = QLabel(""); self.p_text.setWordWrap(True)
        self.p_phase = QLabel(""); self.p_phase.setWordWrap(True)
        self.p_phase.setStyleSheet("color:#9aa0a6;")
        self.p_extern = QLabel(""); self.p_extern.setWordWrap(True)
        self.p_extern.setStyleSheet("color:#e5a50a;")
        for w in (self.p_name, self.p_vorbild, self.p_text, self.p_phase, self.p_extern):
            rl.addWidget(w)
        self.p_form_host = QWidget(); self.p_form = QFormLayout(self.p_form_host)
        rl.addWidget(self.p_form_host)
        from ui.components import CurveWidget
        self.kurve = CurveWidget(self._kurve_geaendert)
        self.kurve.hide()
        rl.addWidget(self.kurve)
        self.p_experimentell = QCheckBox(tr("Experimentelles Modell bewusst verwenden"))
        self.p_experimentell.hide()
        rl.addWidget(self.p_experimentell)

        maske = QGroupBox(tr("Maske (wo das Werkzeug wirkt)")); ml = QFormLayout(maske)
        self.m_art = QComboBox()
        for art in prozesse.MASKEN:
            self.m_art.addItem(tr(art), art)
        self.m_von = QDoubleSpinBox(); self.m_von.setRange(0, 1); self.m_von.setSingleStep(0.05); self.m_von.setValue(0.2)
        self.m_bis = QDoubleSpinBox(); self.m_bis.setRange(0, 1); self.m_bis.setSingleStep(0.05); self.m_bis.setValue(1.0)
        self.m_weich = QDoubleSpinBox(); self.m_weich.setRange(0, 50); self.m_weich.setValue(2.0)
        self.m_umkehren = QCheckBox(tr("umkehren"))
        self.m_zeigen = QPushButton(tr("Maske zeigen"))
        ml.addRow(tr("Art"), self.m_art)
        ml.addRow(tr("Helligkeit von"), self.m_von); ml.addRow(tr("Helligkeit bis"), self.m_bis)
        ml.addRow(tr("weicher Rand"), self.m_weich); ml.addRow(self.m_umkehren); ml.addRow(self.m_zeigen)
        rl.addWidget(maske)
        self.k_anwenden = QPushButton(tr("Anwenden")); self.k_anwenden.setObjectName("primary")
        self.k_anwenden.setEnabled(False)
        self.k_probe = QPushButton(tr("Am Ausschnitt probieren"))
        self.k_probe.setToolTip(tr("Rechnet nur einen Ausschnitt aus der Bildmitte und zeigt vorher | nachher. Nichts wird übernommen."))
        self.k_probe.setEnabled(False)
        zeile = QHBoxLayout(); zeile.addWidget(self.k_probe); zeile.addWidget(self.k_anwenden)
        rl.addLayout(zeile)
        self.info = QPlainTextEdit(); self.info.setReadOnly(True); self.info.setMaximumBlockCount(500)
        rl.addWidget(QLabel(tr("Werte und Protokoll"))); rl.addWidget(self.info, 1)
        teiler.addWidget(rechts)
        teiler.setSizes([280, 800, 320])
        lay.addWidget(teiler, 1)

        lay.addWidget(QLabel(tr("Verlauf")))
        self.verlauf = QListWidget(); self.verlauf.setMaximumHeight(130)
        lay.addWidget(self.verlauf)

        self.k_oeffnen.clicked.connect(self._oeffnen_dialog)
        self.k_speichern.clicked.connect(self._speichern_dialog)
        self.k_zurueck.clicked.connect(self.rueckgaengig)
        self.k_vor.clicked.connect(self.wiederholen)
        self.k_rezept.clicked.connect(self._rezept_speichern)
        self.k_rezept_laden.clicked.connect(self._rezept_anwenden)
        self.stf.toggled.connect(lambda _: self._anzeigen())
        self.vorher.toggled.connect(lambda _: self._anzeigen())
        self.suche.textChanged.connect(self._baum_fuellen)
        self.baum.currentItemChanged.connect(lambda neu, _alt: self._prozess_waehlen(neu))
        self.k_anwenden.clicked.connect(self.anwenden)
        self.k_probe.clicked.connect(self.probieren)
        self.m_zeigen.clicked.connect(self._maske_zeigen)
        self._knoepfe()

    def _baum_fuellen(self, *_):
        suche = self.suche.text().strip().lower() if hasattr(self, "suche") else ""
        self.baum.clear()
        for nummer, gruppe in enumerate(prozesse.GRUPPEN, 1):
            treffer = [p for p in prozesse.PROZESSE if p.gruppe == gruppe and
                       (not suche or suche in (p.name + " " + p.vorbild + " " + p.beschreibung + " "
                                               + tr(p.name)).lower())]
            if not treffer:
                continue
            knoten = QTreeWidgetItem(["%d · %s" % (nummer, tr(gruppe))])
            for p in treffer:
                blatt = QTreeWidgetItem([tr(p.name)])
                blatt.setData(0, Qt.UserRole, p.id)
                blatt.setToolTip(0, p.vorbild)
                if p.extern is not None and not p.verfuegbar()[0]:
                    blatt.setText(0, tr(p.name) + "  " + tr("(nicht installiert)"))
                    blatt.setForeground(0, Qt.gray)
                knoten.addChild(blatt)
            self.baum.addTopLevelItem(knoten)
            knoten.setExpanded(True)

    # ------------------------------------------------------------------ Bild ---------------
    def oeffnen(self, pfad):
        bild, kopf = prozesse.bild_laden(pfad)
        self.arbeit = prozesse.Arbeitsbild(bild, quelle=pfad, log=self._schreiben)
        self._probe = None
        self.kopf, self.quelle = kopf, pfad
        self.setWindowTitle(tr("Arbeitsplatz") + " — " + os.path.basename(pfad))
        self._schreiben(tr("Geöffnet: {pfad} ({h}×{w})").format(pfad=pfad, h=bild.shape[0], w=bild.shape[1]))
        self._verlauf_zeigen(); self._anzeigen(); self._statistik(); self._knoepfe()

    def _oeffnen_dialog(self):
        pfad, _ = QFileDialog.getOpenFileName(self, tr("Bild öffnen"), os.path.dirname(self.quelle or ""),
                                              "FITS / TIFF (*.fit *.fits *.fts *.tif *.tiff)")
        if pfad:
            try:
                self.oeffnen(pfad)
            except Exception as e:                     # noqa: BLE001 — wird angezeigt
                QMessageBox.warning(self, tr("Arbeitsplatz"), str(e))

    def _anzeige_bild(self):
        if getattr(self, "_probe", None) is not None:
            vorher, nachher = self._probe
            trenner = np.ones((vorher.shape[0], 4, 3), np.float32)
            return np.hstack([vorher, trenner * float(np.max(nachher)), nachher]), self.stf.isChecked()
        if self._zeige_maske is not None:
            m = self._zeige_maske
            return np.dstack([m] * 3), False
        quelle = self.arbeit.original if self.vorher.isChecked() else self.arbeit.bild
        return quelle, self.stf.isChecked()

    def _anzeigen(self):
        if self.arbeit is None:
            return
        import cv2
        import astro
        from ui.components import _bgr_to_pixmap
        bild, strecken = self._anzeige_bild()
        h, w = bild.shape[:2]
        s = min(1.0, _ANZEIGE_MAX / float(max(h, w)))
        klein = cv2.resize(bild, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA) if s < 1 else bild
        if strecken:
            lo = float(np.percentile(klein, 0.1))
            klein = astro.autostretch(np.clip(klein - lo, 0, None))     # nur die Anzeige
        acht = (np.clip(klein, 0, 1) * 255).astype(np.uint8)
        pixmap, _ = _bgr_to_pixmap(acht, max_w=acht.shape[1])
        self.flaeche.setzen(pixmap, s, (h, w))

    def _pixel_melden(self, x, y):
        if self.arbeit is None:
            return
        v = self.arbeit.bild[y, x]
        werte = " ".join("%.5f" % float(t) for t in np.atleast_1d(v)[::-1])   # BGR -> R G B
        self.pixelwert.setText("x %d  y %d   R G B  %s" % (x, y, werte))

    def _statistik(self):
        zeilen = []
        for s in prozesse.statistik(self.arbeit.bild):
            zeilen.append("%-5s Median %.5f  MAD %.5f  Min %.4f  Max %.4f  ≤0 %.1f %%  ≥1 %.2f %%" % (
                s["kanal"], s["median"], s["mad"], s["min"], s["max"], 100 * s["unter_0"], 100 * s["ueber_1"]))
        self._schreiben("\n".join(zeilen))

    def _schreiben(self, text):
        self.info.appendPlainText(str(text).rstrip("\n"))

    # ------------------------------------------------------------------ Werkzeug -----------
    def _prozess_waehlen(self, eintrag):
        pid = eintrag.data(0, Qt.UserRole) if eintrag is not None else None
        while self.p_form.rowCount():
            self.p_form.removeRow(0)
        self._felder = {}
        self.prozess = prozesse.NACH_ID.get(pid)
        if self.prozess is None:
            self.p_name.setText(tr("Werkzeug links wählen.")); self.p_vorbild.setText(""); self.p_text.setText("")
            self.p_experimentell.hide(); self._knoepfe()
            return
        p = self.prozess
        self._probe = None
        self.p_name.setText(tr(p.name))
        self.p_vorbild.setText(tr("Vorbild: {vorbild}").format(vorbild=p.vorbild))
        self.p_text.setText(tr(p.beschreibung))
        self.p_phase.setText(tr("Wann: {phase}").format(phase=tr(prozesse.PHASE_TEXT[prozesse.PHASE[p.id]])))
        da, hinweis = p.verfuegbar()
        self.p_extern.setText("" if da or p.extern is None else hinweis)
        for par in p.params:
            if par.art == "bild":
                feld = QWidget(); zeile = QHBoxLayout(feld); zeile.setContentsMargins(0, 0, 0, 0)
                feld.pfad = QLineEdit(); feld.pfad.setPlaceholderText(tr("ausgerichtet, gleich groß") if par.pflicht else tr("optional"))
                knopf = QPushButton(tr("Wählen…"))
                knopf.clicked.connect(lambda _=False, f=feld.pfad: self._bild_waehlen(f))
                zeile.addWidget(feld.pfad, 1); zeile.addWidget(knopf)
            elif par.art == "text":
                feld = QLineEdit(str(par.standard or ""))
            elif par.art == "wahl":
                feld = QComboBox()
                for w in par.wahl:
                    feld.addItem(tr(w), w)
                feld.setCurrentIndex(par.wahl.index(par.standard))
            elif par.art == "schalter":
                feld = QCheckBox(); feld.setChecked(par.standard)
            elif par.art == "ganz":
                feld = QSpinBox(); feld.setRange(int(par.von), int(par.bis)); feld.setValue(int(par.standard))
            else:
                feld = QDoubleSpinBox(); feld.setDecimals(3); feld.setRange(par.von, par.bis)
                feld.setSingleStep(max((par.bis - par.von) / 100.0, 0.001)); feld.setValue(par.standard)
            self._felder[par.name] = feld
            self.p_form.addRow(tr(par.label), feld)
        self.p_experimentell.setVisible(p.experimentell)
        self.p_experimentell.setChecked(False)
        self.kurve.setVisible(p.id == "kurven")
        if p.id == "kurven":
            self.kurve.points = [list(xy) for xy in prozesse.kurven_punkte(self._felder["punkte"].text())]
            self.kurve.update()
            self._felder["punkte"].editingFinished.connect(self._kurve_aus_text)
        self._knoepfe()

    def _bild_waehlen(self, feld):
        pfad, _ = QFileDialog.getOpenFileName(self, tr("Bild öffnen"), os.path.dirname(self.quelle or ""),
                                              "FITS / TIFF (*.fit *.fits *.fts *.tif *.tiff)")
        if pfad:
            feld.setText(pfad)

    def _kurve_geaendert(self, punkte):
        feld = getattr(self, "_felder", {}).get("punkte")
        if feld is not None:
            feld.setText("; ".join("%.3f,%.3f" % (x, y) for x, y in sorted(punkte)))

    def _kurve_aus_text(self):
        try:
            self.kurve.points = [list(xy) for xy in prozesse.kurven_punkte(self._felder["punkte"].text())]
            self.kurve.update()
        except ValueError as e:
            self._schreiben("⚠️ " + str(e))

    def werte(self):
        aus = {}
        for name, feld in self._felder.items():
            if hasattr(feld, "pfad"):
                aus[name] = feld.pfad.text().strip() or None
            elif isinstance(feld, QLineEdit):
                aus[name] = feld.text()
            elif isinstance(feld, QComboBox):
                aus[name] = feld.currentData()
            elif isinstance(feld, QCheckBox):
                aus[name] = feld.isChecked()
            else:
                aus[name] = feld.value()
        return aus

    def maske(self):
        art = self.m_art.currentData()
        if art == "keine":
            return None
        return {"art": art, "von": self.m_von.value(), "bis": self.m_bis.value(),
                "umkehren": self.m_umkehren.isChecked(), "weich": self.m_weich.value()}

    def _maske_zeigen(self):
        if self.arbeit is None:
            return
        if self._zeige_maske is not None:
            self._zeige_maske = None
            self.m_zeigen.setText(tr("Maske zeigen"))
        else:
            spec = self.maske()
            if spec is None:
                return
            try:
                self._zeige_maske = prozesse.maske_bauen(self.arbeit.bild, **spec)
            except ValueError as e:
                QMessageBox.warning(self, tr("Arbeitsplatz"), str(e)); return
            self.m_zeigen.setText(tr("Bild zeigen"))
        self._anzeigen()

    def anwenden(self):
        if self.arbeit is None or self.prozess is None:
            return
        if self.prozess.experimentell and not self.p_experimentell.isChecked():
            QMessageBox.information(self, tr("Arbeitsplatz"),
                                    tr("Das ist ein experimentelles Modell. Bitte die Zusage ankreuzen."))
            return
        p, werte, maske = self.prozess, self.werte(), self.maske()
        erlaubt = self.p_experimentell.isChecked()
        arbeit = self.arbeit

        def fertig(_):
            self._probe = None
            self._zeige_maske = None; self.m_zeigen.setText(tr("Maske zeigen"))
            self._verlauf_zeigen(); self._anzeigen(); self._statistik(); self._knoepfe()
        self._schreiben(tr("Wende an: {name}").format(name=tr(p.name)))
        def rechnen(log):
            arbeit.log = log                       # Meldungen aus dem Hintergrund-Thread über das Signal
            try:
                return arbeit.anwenden(p.id, werte, maske, experimentell_erlaubt=erlaubt)
            finally:
                arbeit.log = self._schreiben
        self._hintergrund(rechnen, fertig)

    def probieren(self, kante=600):
        """Werkzeug an einem Ausschnitt der Bildmitte rechnen und vorher | nachher zeigen."""
        if self.arbeit is None or self.prozess is None:
            return
        p = self.prozess
        if p.aendert_groesse:
            self._schreiben(tr("Größenändernde Werkzeuge werden direkt angewendet (Rückgängig geht immer)."))
            return
        if p.experimentell and not self.p_experimentell.isChecked():
            QMessageBox.information(self, tr("Arbeitsplatz"),
                                    tr("Das ist ein experimentelles Modell. Bitte die Zusage ankreuzen."))
            return
        bild = self.arbeit.bild
        h, w = bild.shape[:2]
        y0, x0 = max(0, h // 2 - kante // 2), max(0, w // 2 - kante // 2)
        stueck = bild[y0:y0 + kante, x0:x0 + kante].copy()
        werte, spec, erlaubt = self.werte(), self.maske(), self.p_experimentell.isChecked()
        if any(par.bild for par in p.params):
            self._schreiben(tr("Werkzeuge mit zweitem Bild lassen sich nicht am Ausschnitt probieren."))
            return

        def rechnen(log):
            maske = prozesse.maske_bauen(stueck, **spec) if spec else None
            return stueck, prozesse.anwenden(stueck, p.id, werte, maske, experimentell_erlaubt=erlaubt, log=log)

        def fertig(paar):
            self._probe = paar
            self._schreiben(tr("Probe: links vorher, rechts nachher — nichts übernommen."))
            self._anzeigen(); self._knoepfe()
        self._hintergrund(rechnen, fertig)

    def _hintergrund(self, fn, fertig):
        if self._worker is not None and self._worker.isRunning():
            self._schreiben(tr("Es läuft noch ein Vorgang. Bitte warten."))
            return
        wk = _ToolWorker(fn)
        wk.log.connect(self._schreiben)
        wk.done.connect(fertig)
        wk.failed.connect(lambda m: (self._schreiben("⚠️ " + m), QMessageBox.warning(self, tr("Arbeitsplatz"), m),
                                     self._knoepfe()))
        self._worker = wk
        self._knoepfe(laeuft=True)
        wk.start()

    # ------------------------------------------------------------------ Verlauf ------------
    def _verlauf_zeigen(self):
        self.verlauf.clear()
        self.verlauf.addItem(tr("0 · Original"))
        for i, s in enumerate(self.arbeit.schritte, 1):
            p = prozesse.NACH_ID[s["id"]]
            text = "%d · %s  %s" % (i, tr(p.name), json.dumps(s["werte"], ensure_ascii=False))
            if s.get("maske"):
                text += "  [" + tr("Maske") + ": " + tr(s["maske"]["art"]) + "]"
            if i > self.arbeit.stand:
                text = "(" + text + ")"
            self.verlauf.addItem(text)
        self.verlauf.setCurrentRow(self.arbeit.stand)

    def rueckgaengig(self):
        if self.arbeit is not None and self.arbeit.kann_zurueck:
            self._probe = None
            self.arbeit.rueckgaengig()
            self._verlauf_zeigen(); self._anzeigen(); self._knoepfe()

    def wiederholen(self):
        if self.arbeit is not None and self.arbeit.kann_vor:
            self._probe = None
            self.arbeit.wiederholen()
            self._verlauf_zeigen(); self._anzeigen(); self._knoepfe()

    def _knoepfe(self, laeuft=False):
        offen = self.arbeit is not None
        for k in (self.k_speichern, self.k_rezept, self.k_rezept_laden):
            k.setEnabled(offen and not laeuft)
        self.k_zurueck.setEnabled(offen and not laeuft and self.arbeit.kann_zurueck)
        self.k_vor.setEnabled(offen and not laeuft and self.arbeit.kann_vor)
        bereit = offen and not laeuft and getattr(self, "prozess", None) is not None
        if bereit and self.prozess.extern is not None:
            bereit = self.prozess.verfuegbar()[0]
        self.k_anwenden.setEnabled(bereit)
        self.k_probe.setEnabled(bereit and not self.prozess.aendert_groesse)

    # ------------------------------------------------------------------ Dateien ------------
    def speichern(self, pfad):
        prozesse.bild_speichern(pfad, self.arbeit.zum_speichern(), self.kopf,
                                self.arbeit.schritte[:self.arbeit.stand])
        self._schreiben(tr("Gespeichert: {pfad}").format(pfad=pfad))
        if self._uebernehmen:
            self._uebernehmen(pfad, self.quelle)
        return pfad

    def _speichern_dialog(self):
        vorschlag = os.path.splitext(self.quelle or "bild")[0] + "_arbeitsplatz.fits"
        pfad, _ = QFileDialog.getSaveFileName(self, tr("Speichern"), vorschlag,
                                              "FITS (*.fits);;TIFF 32 bit (*.tif)")
        if not pfad:
            return
        if self.quelle and os.path.normcase(os.path.abspath(pfad)) == os.path.normcase(os.path.abspath(self.quelle)):
            QMessageBox.warning(self, tr("Arbeitsplatz"), tr("Das Original wird nicht überschrieben. Bitte einen neuen Namen wählen."))
            return
        try:
            self.speichern(pfad)
        except Exception as e:                         # noqa: BLE001 — wird angezeigt
            QMessageBox.warning(self, tr("Arbeitsplatz"), str(e))

    def _rezept_speichern(self):
        pfad, _ = QFileDialog.getSaveFileName(self, tr("Rezept speichern"), "arbeitsplatz.json", "JSON (*.json)")
        if pfad:
            prozesse.rezept_speichern(self.arbeit.rezept(), pfad)
            self._schreiben(tr("Rezept gespeichert: {pfad}").format(pfad=pfad))

    def _rezept_anwenden(self):
        pfad, _ = QFileDialog.getOpenFileName(self, tr("Rezept anwenden"), "", "JSON (*.json)")
        if not pfad:
            return
        rezept = prozesse.rezept_laden(pfad)
        arbeit = self.arbeit

        def nachspielen(log):
            if rezept.get("format") != prozesse.REZEPT_FORMAT:
                raise ValueError(tr("Kein Arbeitsplatz-Rezept."))
            for s in rezept["schritte"]:
                arbeit.anwenden(s["id"], s["werte"], s.get("maske"),
                                experimentell_erlaubt=s.get("experimentell", False))
            return len(rezept["schritte"])

        def fertig(n):
            self._schreiben(tr("{n} Schritte aus dem Rezept angewendet.").format(n=n))
            self._verlauf_zeigen(); self._anzeigen(); self._statistik(); self._knoepfe()
        self._hintergrund(nachspielen, fertig)

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(30000)
        super().closeEvent(event)
