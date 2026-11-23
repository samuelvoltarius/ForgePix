#!/usr/bin/env python3
"""
core/aufnahme.py — ein Ablaufplan für die eigene Aufnahme (der N.I.N.A.-Ersatz, Schritt 1).

Ein Plan ist eine Liste von Schritten „N Aufnahmen × Belichtung × Filter × Typ". Der Lauf
belichtet über einen Kamera-Anschluss (`alpaca.Kamera` oder `indi.Kamera`), dreht das Filterrad, liest
die Position der Montierung mit und schreibt jede Aufnahme als FITS mit vollständigen
Kopfdaten in einen Ordner. Diesen Ordner kann ForgePix gleichzeitig live stapeln; die
Kalibrierbilder (Dark/Flat/Bias) erkennt die vorhandene Header-Suche am IMAGETYP.

Dithern über PHD2 alle N Lights (`phd2.py`); Autofokus steht in `autofokus.py`. Was hier NOCH
NICHT ist (docs/plan/01): Meridian-Flip, Plate-Solve zum Einrichten, Bedingungen (Höhe,
Dämmerung). Kein Qt.
"""
import datetime as _dt
import os
import threading

import numpy as np

try:
    from constants import log_print
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)

TYPEN = ("Light", "Dark", "Flat", "Bias", "DarkFlat")


class Schritt:
    """Ein Schritt des Plans. Fehlende Angaben bleiben None — kein erfundener Standardwert."""

    def __init__(self, anzahl, belichtung, typ="Light", filter=None):
        self.anzahl = int(anzahl)
        self.belichtung = float(belichtung)
        self.typ = str(typ)
        self.filter = filter or None
        if self.anzahl < 1:
            raise ValueError("Anzahl muss mindestens 1 sein, nicht %r" % anzahl)
        if self.belichtung < 0:
            raise ValueError("Belichtung darf nicht negativ sein, nicht %r" % belichtung)
        if self.typ not in TYPEN:
            raise ValueError("Unbekannter Aufnahmetyp %r; erlaubt: %s" % (typ, ", ".join(TYPEN)))

    def __repr__(self):
        return "%d × %.1f s %s%s" % (self.anzahl, self.belichtung, self.typ,
                                      " (%s)" % self.filter if self.filter else "")


def kopfdaten(info, schritt, belichtet_um, ziel=None, position=None, objekt=None):
    """FITS-Kopf so, wie ASIAIR und N.I.N.A. ihn schreiben — dieselben Schlüssel, die
    ForgePix beim Lesen auswertet (Kamera, Filter, Belichtung, Temperatur, Bayer)."""
    from astropy.io import fits
    kopf = fits.Header()
    kopf["IMAGETYP"] = schritt.typ
    kopf["EXPTIME"] = (schritt.belichtung, "Belichtung in Sekunden")
    kopf["EXPOSURE"] = schritt.belichtung
    kopf["DATE-OBS"] = (belichtet_um.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3], "Beginn, UTC")
    for schluessel, wert, text in (
            ("INSTRUME", info.get("name"), "Kamera"),
            ("XPIXSZ", info.get("pixel_um"), "Pixelgroesse in Mikrometern"),
            ("GAIN", info.get("gain"), None), ("OFFSET", info.get("offset"), None),
            ("CCD-TEMP", info.get("temperatur"), "Sensortemperatur in Grad C"),
            ("XBINNING", info.get("binning"), None), ("YBINNING", info.get("binning"), None),
            ("BAYERPAT", info.get("bayer"), None),
            ("FILTER", schritt.filter, None), ("OBJECT", objekt, None)):
        if wert is not None:                            # fehlt → fehlt, nicht 0
            kopf[schluessel] = (wert, text) if text else wert
    if info.get("bayer"):
        kopf["XBAYROFF"], kopf["YBAYROFF"] = 0, 0       # Muster ist bereits verschoben angegeben
    if position is not None:
        ra_h, dec = position
        kopf["RA"] = (ra_h * 15.0, "Bildmitte laut Montierung, Grad")
        kopf["DEC"] = (dec, "Bildmitte laut Montierung, Grad")
    kopf["SWCREATE"] = "ForgePix"
    return kopf


def dateiname(schritt, belichtet_um, nummer):
    teile = [schritt.typ]
    if schritt.filter:
        teile.append("".join(c if c.isalnum() else "_" for c in schritt.filter))
    teile += ["%.1fs" % schritt.belichtung, belichtet_um.strftime("%Y%m%d-%H%M%S"), "%04d" % nummer]
    return "_".join(teile) + ".fits"


def fits_schreiben(pfad, bild, kopf):
    """Erst fertig schreiben, dann umbenennen: der Live-Stapler darf keine halbe Datei sehen."""
    from astropy.io import fits
    zwischen = pfad + ".teil"
    fits.PrimaryHDU(np.asarray(bild), header=kopf).writeto(zwischen, overwrite=True)
    os.replace(zwischen, pfad)
    return pfad


class Lauf:
    """Einen Plan abarbeiten. `abbrechen()` stoppt nach der laufenden Belichtung (die Kamera
    bekommt abortexposure). Jede fertige Datei meldet sich mit einer Zeile `AUFNAHME:<pfad>`
    — maschinenlesbar, wie die anderen Marker der Oberfläche."""

    def __init__(self, kamera, plan, ordner, filterrad=None, montierung=None, objekt=None,
                 phd2=None, dither_alle=0, log=log_print):
        if not plan:
            raise ValueError("Der Ablaufplan ist leer.")
        self.kamera, self.plan, self.ordner = kamera, list(plan), ordner
        self.filterrad, self.montierung, self.objekt = filterrad, montierung, objekt
        self.phd2, self.dither_alle = phd2, int(dither_alle or 0)
        if self.dither_alle and self.phd2 is None:
            raise ValueError("Dithern verlangt eine PHD2-Verbindung.")
        self.log = log
        self._abbruch = threading.Event()
        self.dateien = []

    def abbrechen(self):
        self._abbruch.set()

    @property
    def gesamt(self):
        return sum(s.anzahl for s in self.plan)

    def ausfuehren(self):
        os.makedirs(self.ordner, exist_ok=True)
        if any(s.filter for s in self.plan) and self.filterrad is None:
            raise ValueError("Der Plan nennt Filter, aber kein Filterrad ist verbunden.")
        info = self.kamera.info()
        nummer = 0
        lights = 0
        for schritt in self.plan:
            if self._abbruch.is_set():
                break
            if schritt.filter:
                self.log("Filter wechseln: %s" % schritt.filter)
                self.filterrad.wechseln(schritt.filter)
            for _ in range(schritt.anzahl):
                if self._abbruch.is_set():
                    break
                nummer += 1
                self.log("PHASE:Aufnahme %d/%d — %r" % (nummer, self.gesamt, schritt))
                position = None
                if self.montierung is not None and schritt.typ == "Light":
                    position = self.montierung.position()
                beginn = _dt.datetime.now(_dt.timezone.utc)
                bild = self.kamera.belichten(schritt.belichtung,
                                             licht=schritt.typ not in ("Dark", "Bias", "DarkFlat"),
                                             abbruch=self._abbruch, typ=schritt.typ)
                info["temperatur"] = self.kamera.temperatur()      # je Aufnahme frisch
                kopf = kopfdaten(info, schritt, beginn, position=position, objekt=self.objekt)
                pfad = fits_schreiben(os.path.join(self.ordner, dateiname(schritt, beginn, nummer)),
                                      bild, kopf)
                self.dateien.append(pfad)
                self.log("AUFNAHME:%s" % pfad)
                if schritt.typ == "Light":
                    lights += 1
                    if (self.dither_alle and lights % self.dither_alle == 0
                            and len(self.dateien) < self.gesamt and not self._abbruch.is_set()):
                        self.log("Dithern (nach %d Lights) …" % lights)
                        self.phd2.dithern()
        fertig = len(self.dateien)
        if fertig < self.gesamt:
            self.log("Abgebrochen: %d von %d Aufnahmen gespeichert." % (fertig, self.gesamt))
        else:
            self.log("Ablaufplan fertig: %d Aufnahmen in %s" % (fertig, self.ordner))
        return self.dateien
