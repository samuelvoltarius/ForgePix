#!/usr/bin/env python3
"""
core/aufnahme.py — ein Ablaufplan für die eigene Aufnahme (der N.I.N.A.-Ersatz, Schritt 1).

Ein Plan ist eine Liste von Schritten „N Aufnahmen × Belichtung × Filter × Typ". Der Lauf
belichtet über einen Kamera-Anschluss (`alpaca.Kamera` oder `indi.Kamera`), dreht das Filterrad, liest
die Position der Montierung mit und schreibt jede Aufnahme als FITS mit vollständigen
Kopfdaten in einen Ordner. Diesen Ordner kann ForgePix gleichzeitig live stapeln; die
Kalibrierbilder (Dark/Flat/Bias) erkennt die vorhandene Header-Suche am IMAGETYP.

Dithern über PHD2 alle N Lights (`phd2.py`), mehrere Ziele (Mosaik-Panele) mit Zentrieren
(`zentrieren.py`), Meridian-Flip mit Warten, Flip, Nachzentrieren und neuem Führungsstart.
Autofokus steht in `autofokus.py`. Was hier NOCH NICHT ist (docs/plan/01): Bedingungen (Höhe,
Dämmerung), Autofokus im Plan. Kein Qt.
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
                 phd2=None, dither_alle=0, ziele=None, zentrierer=None, meridian_minuten=None,
                 takt=10.0, log=log_print):
        """ziele: Liste von {'name', 'ra_h', 'dec'} (z. B. Mosaik-Panele) — je Ziel wird
        hingeschwenkt, mit `zentrierer(ra_h, dec)` zentriert und der Plan abgearbeitet.
        meridian_minuten: Meridian-Flip so viele Minuten nach dem Meridian (None = aus)."""
        if not plan:
            raise ValueError("Der Ablaufplan ist leer.")
        self.kamera, self.plan, self.ordner = kamera, list(plan), ordner
        self.filterrad, self.montierung, self.objekt = filterrad, montierung, objekt
        self.phd2, self.dither_alle = phd2, int(dither_alle or 0)
        if self.dither_alle and self.phd2 is None:
            raise ValueError("Dithern verlangt eine PHD2-Verbindung.")
        self.ziele = list(ziele or [])
        if self.ziele and montierung is None:
            raise ValueError("Ziele anfahren verlangt eine verbundene Montierung.")
        if meridian_minuten is not None and montierung is None:
            raise ValueError("Meridian-Flip verlangt eine verbundene Montierung.")
        self.zentrierer, self.meridian_minuten, self.takt = zentrierer, meridian_minuten, float(takt)
        self._geflippt = False
        self._ziel = None
        self.flips = 0
        self.log = log
        self._abbruch = threading.Event()
        self.dateien = []

    def abbrechen(self):
        self._abbruch.set()

    @property
    def gesamt(self):
        return sum(s.anzahl for s in self.plan) * max(1, len(self.ziele))

    def _anfahren(self, ziel):
        self.log("Ziel: %s — RA %.4f h, Dec %+.4f°" % (ziel["name"], ziel["ra_h"], ziel["dec"]))
        if self.phd2 is not None:
            self.phd2.stoppen()
        if self.zentrierer is not None:
            self.zentrierer(ziel["ra_h"], ziel["dec"])
        else:
            self.montierung.schwenken(ziel["ra_h"], ziel["dec"])
        if self.phd2 is not None:
            self.phd2.guiding_starten()
        self._ziel, self._geflippt = ziel, False

    def _meridian(self, dauer):
        """Vor einer Belichtung: würde sie über die Flip-Grenze laufen, erst bis zur Grenze warten,
        dann flippen (gleiches Ziel neu anfahren — eine deutsche Montierung wechselt dabei die
        Seite), neu zentrieren, Führung neu starten. Einmal je Ziel."""
        if self.meridian_minuten is None or self._geflippt:
            return
        ha = self.montierung.stundenwinkel()
        if ha is None:
            self.log("Meridian-Flip aus: die Montierung meldet keinen Stundenwinkel (Sternzeit).")
            self.meridian_minuten = None
            return
        grenze = self.meridian_minuten / 60.0
        if ha + dauer / 3600.0 < grenze:
            return
        if ha < grenze:
            self.log("Warte %.1f min bis zum Meridian-Flip …" % ((grenze - ha) * 60))
        while ha < grenze:
            if self._abbruch.wait(self.takt):
                return
            ha = self.montierung.stundenwinkel()
        vorher = self.montierung.seite()
        self.log("Meridian-Flip (Stundenwinkel %+.1f min, Seite %s)" % (ha * 60, vorher or "unbekannt"))
        if self.phd2 is not None:
            self.phd2.stoppen()
        ra_h, dec = ((self._ziel["ra_h"], self._ziel["dec"]) if self._ziel else self.montierung.position())
        if self.zentrierer is not None:
            self.zentrierer(ra_h, dec)
        else:
            self.montierung.schwenken(ra_h, dec)
        nachher = self.montierung.seite()
        if vorher is not None and nachher == vorher:
            self.log("Achtung: Pfeilerseite nach dem Flip unverändert (%s) — hat die Montierung "
                     "wirklich geflippt?" % nachher)
        if self.phd2 is not None:
            self.phd2.guiding_starten()
        self._geflippt = True
        self.flips += 1

    def ausfuehren(self):
        os.makedirs(self.ordner, exist_ok=True)
        if any(s.filter for s in self.plan) and self.filterrad is None:
            raise ValueError("Der Plan nennt Filter, aber kein Filterrad ist verbunden.")
        info = self.kamera.info()
        self._nummer, self._lights = 0, 0
        for ziel in (self.ziele or [None]):
            if self._abbruch.is_set():
                break
            if ziel is not None:
                self._anfahren(ziel)
            self._plan_abarbeiten(info, ziel)
        fertig = len(self.dateien)
        if fertig < self.gesamt:
            self.log("Abgebrochen: %d von %d Aufnahmen gespeichert." % (fertig, self.gesamt))
        else:
            self.log("Ablaufplan fertig: %d Aufnahmen in %s" % (fertig, self.ordner))
        return self.dateien

    def _plan_abarbeiten(self, info, ziel):
        objekt = (ziel or {}).get("name") or self.objekt
        for schritt in self.plan:
            if self._abbruch.is_set():
                break
            if schritt.filter:
                self.log("Filter wechseln: %s" % schritt.filter)
                self.filterrad.wechseln(schritt.filter)
            for _ in range(schritt.anzahl):
                if self._abbruch.is_set():
                    break
                if schritt.typ == "Light" and self.montierung is not None:
                    self._meridian(schritt.belichtung)
                    if self._abbruch.is_set():
                        break
                self._nummer += 1
                nummer = self._nummer
                self.log("PHASE:Aufnahme %d/%d — %r" % (nummer, self.gesamt, schritt))
                position = None
                if self.montierung is not None and schritt.typ == "Light":
                    position = self.montierung.position()
                beginn = _dt.datetime.now(_dt.timezone.utc)
                bild = self.kamera.belichten(schritt.belichtung,
                                             licht=schritt.typ not in ("Dark", "Bias", "DarkFlat"),
                                             abbruch=self._abbruch, typ=schritt.typ)
                info["temperatur"] = self.kamera.temperatur()      # je Aufnahme frisch
                kopf = kopfdaten(info, schritt, beginn, position=position, objekt=objekt)
                pfad = fits_schreiben(os.path.join(self.ordner, dateiname(schritt, beginn, nummer)),
                                      bild, kopf)
                self.dateien.append(pfad)
                self.log("AUFNAHME:%s" % pfad)
                if schritt.typ == "Light":
                    self._lights += 1
                    if (self.dither_alle and self._lights % self.dither_alle == 0
                            and len(self.dateien) < self.gesamt and not self._abbruch.is_set()):
                        self.log("Dithern (nach %d Lights) …" % self._lights)
                        self.phd2.dithern()
