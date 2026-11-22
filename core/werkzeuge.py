#!/usr/bin/env python3
"""
core/werkzeuge.py — die Werkzeuge, die gebaut waren, aber in der Oberfläche fehlten.

Blink, Superbias, Larson-Sekanina, periodische Streifen und das Beschriften eines gelösten
Bildes gab es als Rechnung (`klassiker.py`, `annotation.py`), aber ohne Menüpunkt — und das
Beschriften nicht einmal auf der Kommandozeile. Hier steht je Werkzeug ein Aufruf „Datei rein,
Datei raus", den die Oberfläche und die Tests gleich benutzen. Kein Qt.

Jede Funktion sagt im Protokoll, was sie verwirft oder abschneidet; nichts verschwindet still.
"""
import os

import numpy as np

try:
    from constants import log_print
except ImportError:                                     # eigenstaendig aufrufbar
    def log_print(*a, **k):
        print(*a, **k)


def _neuer_pfad(pfad):
    """Nie überschreiben: belegt → _2, _3, …"""
    stamm, endung = os.path.splitext(pfad)
    kandidat, n = pfad, 2
    while os.path.exists(kandidat):
        kandidat = "%s_%d%s" % (stamm, n, endung)
        n += 1
    return kandidat


def _tiff32(pfad, bild):
    import tifffile
    a = np.asarray(bild, np.float32)
    if a.ndim == 3:
        tifffile.imwrite(pfad, a[..., ::-1], photometric="rgb")
    else:
        tifffile.imwrite(pfad, a, photometric="minisblack")
    return pfad


def _ausserhalb_melden(bild, log):
    """klassiker clippt auf [0, 1]. Wer Werte außerhalb hineinsteckt, soll es lesen."""
    a = np.asarray(bild)
    anteil = float(np.mean((a < 0) | (a > 1))) if a.size else 0.0
    if anteil > 0:
        log("    Achtung: %.3f %% der Pixel liegen außerhalb 0..1 und werden auf 0..1 begrenzt."
            % (100 * anteil))
    return anteil


# ----------------------------------------------------------------------------- Blink -------
def blink(dateien, ziel, dauer_ms=200, log=log_print):
    import klassiker
    if not dateien:
        raise ValueError("Keine Aufnahmen für das Daumenkino gewählt.")
    ergebnis = klassiker.blink(list(dateien), _neuer_pfad(ziel), dauer_ms=dauer_ms, log=log)
    if ergebnis["aufnahmen"] < len(dateien):
        log("    %d von %d Aufnahmen waren nicht lesbar und fehlen im Daumenkino."
            % (len(dateien) - ergebnis["aufnahmen"], len(dateien)))
    return ergebnis["datei"]


# ------------------------------------------------------------------------- Superbias -------
def superbias(dateien, ziel, log=log_print):
    """Superbias-Modell aus rohen Bias-Aufnahmen als FITS schreiben.

    Roh gelesen (ohne Debayer), wie die Kalibrierung ihre Master liest — sonst passt die Form
    nicht zu den Lights. Die Datei taugt danach als `--bias` oder im Bias-Ordner."""
    import astro
    import klassiker
    from astropy.io import fits
    roh, verworfen = [], []
    for p in dateien:
        try:
            roh.append(astro._read_float(p, debayer=False))
        except Exception as e:                           # benannt verwerfen, nicht still
            verworfen.append("%s (%s)" % (os.path.basename(p), e))
    for v in verworfen:
        log("    übersprungen: " + v)
    if len(roh) < 3:
        raise ValueError("Superbias braucht mindestens 3 lesbare Bias-Aufnahmen, %d gelesen."
                         % len(roh))
    formen = {r.shape for r in roh}
    if len(formen) > 1:
        raise ValueError("Bias-Aufnahmen haben verschiedene Größen: %s" % sorted(formen))
    modell, bericht = klassiker.superbias(roh, log=log)
    kopf = fits.Header()
    try:
        alt = fits.getheader(dateien[0])
        for k in ("INSTRUME", "GAIN", "OFFSET", "XBINNING", "YBINNING", "CCD-TEMP",
                  "BAYERPAT", "XBAYROFF", "YBAYROFF", "READOUTM"):
            if k in alt:
                kopf[k] = alt[k]
    except Exception as e:
        log("    Kopfdaten der ersten Bias-Aufnahme nicht übernommen: %s" % e)
    kopf["IMAGETYP"] = "Bias"
    kopf["FPSUPERB"] = (bericht["aufnahmen"], "ForgePix Superbias: Anzahl Aufnahmen")
    kopf.add_history("ForgePix Superbias: Sockel + Spalten + Zeilen + glatte Flaeche; "
                     "Hotpixel sind nicht enthalten.")
    daten = modell if modell.ndim == 2 else np.ascontiguousarray(modell[..., ::-1].transpose(2, 0, 1))
    ziel = _neuer_pfad(ziel)
    fits.PrimaryHDU(daten.astype(np.float32), header=kopf).writeto(ziel)
    log("    Superbias gespeichert: %s" % ziel)
    return ziel


# ------------------------------------------------------------------ Larson-Sekanina --------
def larson(quelle, ziel, winkel=15.0, zentrum=None, log=log_print):
    """Kometenstrukturen sichtbar machen. Reines Ansichtswerkzeug — die Helligkeiten danach
    sind Differenzen, keine Messwerte. Lineare Eingaben werden vorher gestreckt."""
    import astro
    import klassiker
    bild = astro._read_float(quelle)
    if float(np.median(bild)) < 0.05:                   # lineares, dunkles Bild: erst zeigen
        log("    Eingabe wirkt linear (Median %.4f) — für die Ansicht gestreckt." % float(np.median(bild)))
        bild = astro.autostretch(bild if bild.ndim == 3 else np.dstack([bild] * 3))
    _ausserhalb_melden(bild, log)
    aus = klassiker.larson_sekanina(bild, zentrum=zentrum, winkel=float(winkel))
    log("    Larson-Sekanina mit %.1f° — Ansicht, keine Messgröße." % float(winkel))
    return _tiff32(_neuer_pfad(ziel), aus)


# -------------------------------------------------------------- periodische Streifen -------
def streifen(quelle, ziel, staerke=1.0, log=log_print):
    import astro
    import klassiker
    bild = astro._read_float(quelle)
    _ausserhalb_melden(bild, log)
    aus, bericht = klassiker.periodisch_entfernen(bild, staerke=float(staerke), log=log)
    if bericht["punkte"] == 0:
        log("    Kein periodisches Muster gefunden — das Bild ist unverändert.")
    return _tiff32(_neuer_pfad(ziel), aus)


# ----------------------------------------------------------------------- Beschriften -------
def loesung_aus_fits(pfad):
    """Die Astrometrie-Lösung aus einem FITS-Kopf, in der Form, die `annotation` erwartet.

    ForgePix schreibt WCS über astropy als PC + CDELT, `annotation` rechnet mit CD — darum
    hier über astropy umgerechnet statt die Schlüssel zu raten. CRPIX wird nullbasiert (FITS
    zählt ab 1, die Pixel im Bild ab 0)."""
    from astropy.io import fits
    from astropy.wcs import WCS
    kopf = fits.getheader(pfad)
    if "CRVAL1" not in kopf:
        raise ValueError("Diese Datei hat keine Himmelsposition (kein WCS). Zuerst "
                         "„Himmelsposition bestimmen“ ausführen und das Ergebnis wählen.")
    wcs = WCS(kopf, naxis=2)
    if not wcs.wcs.ctype[0].endswith("TAN"):
        raise ValueError("Nur TAN-Projektion wird gezeichnet, gefunden: %s" % wcs.wcs.ctype[0])
    cd = wcs.pixel_scale_matrix
    return dict(crval1=float(wcs.wcs.crval[0]), crval2=float(wcs.wcs.crval[1]),
                crpix1=float(wcs.wcs.crpix[0]) - 1.0, crpix2=float(wcs.wcs.crpix[1]) - 1.0,
                cd1_1=float(cd[0, 0]), cd1_2=float(cd[0, 1]),
                cd2_1=float(cd[1, 0]), cd2_2=float(cd[1, 1]))


def beschriften(quelle, ziel, objekte_csv=None, max_mag=9.0, gitter=True, log=log_print):
    """Koordinatengitter, helle Gaia-Sterne und Objekte aus einer CSV ins Bild zeichnen."""
    import annotation
    import astro
    import gaia_lokal
    from constants import imwrite          # cv2.imwrite scheitert unter Windows an Umlauten
    loesung = loesung_aus_fits(quelle)
    bild = astro._read_float(quelle)
    if bild.ndim == 2:
        bild = np.dstack([bild] * 3)
    ansicht = astro.autostretch(bild)
    objekte = annotation.objekte_lesen(objekte_csv) if objekte_csv else None
    if objekte_csv and not objekte:
        log("    Die Objektliste enthielt keine lesbare Zeile (erwartet: name,ra,dec in Grad).")
    if not os.path.exists(gaia_lokal.standard_pfad()):
        log("    Kein lokaler Sternkatalog gefunden — Sterne werden nicht beschriftet. "
            "(Menü „Sternkatalog verwalten …“)")
    aus, bericht = annotation.annotieren(ansicht, loesung, objekte=objekte, max_mag=max_mag,
                                        gitter=gitter, log=log)
    ziel = _neuer_pfad(ziel)
    if not imwrite(ziel, aus):
        raise OSError("Bild nicht geschrieben: %s" % ziel)
    return ziel
