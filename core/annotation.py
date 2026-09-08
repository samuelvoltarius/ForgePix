#!/usr/bin/env python3
"""
core/annotation.py — ein gestapeltes Bild beschriften.

Was in ein annotiertes Astrobild gehoert und woher es hier kommt:

* **Koordinatengitter und Bildfeld** — aus der Astrometrie gerechnet, nicht geschaetzt.
* **Helle Sterne mit Helligkeit** — aus dem lokalen Gaia-Katalog, der ohnehin fuer die
  photometrische Farbkalibrierung da ist.
* **Deep-Sky-Objekte** — aus einer Katalogdatei, die der Nutzer mitgibt (CSV:
  `name,ra,dec[,typ]`, Grad). ForgePix bringt KEINE eingebaute Objektliste mit; erfundene
  Koordinaten waeren schlimmer als gar keine.

Alle Positionen laufen ueber dieselbe Loesung, mit der auch die Farbkalibrierung arbeitet —
was hier gezeichnet wird, steht also an derselben Stelle wie das, was gemessen wurde.
"""
import csv
import math
import os

import numpy as np
import cv2

try:
    from constants import log_print
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)


_WEISS = (255, 255, 255)
_GELB = (80, 220, 255)          # BGR
_GRAU = (150, 150, 150)


def _wcs_aus_loesung(loesung):
    """Die vier Zahlen, die eine Himmelsposition in Pixel umrechnen.

    Erwartet wird, was `astrometry.solve` liefert. Fehlt etwas, wird das gesagt statt geraten.
    """
    for schluessel in ("crval1", "CRVAL1"):
        if schluessel in loesung:
            break
    else:
        raise ValueError("Die Loesung enthaelt kein CRVAL1 — ohne Loesung keine Beschriftung.")
    hole = lambda a, b: float(loesung.get(a, loesung.get(b)))
    return dict(ra0=hole("crval1", "CRVAL1"), dec0=hole("crval2", "CRVAL2"),
                x0=hole("crpix1", "CRPIX1"), y0=hole("crpix2", "CRPIX2"),
                cd11=hole("cd1_1", "CD1_1"), cd12=hole("cd1_2", "CD1_2"),
                cd21=hole("cd2_1", "CD2_1"), cd22=hole("cd2_2", "CD2_2"))


def himmel_zu_pixel(ra, dec, wcs):
    """Gnomonische Projektion — dieselbe, die FITS-WCS meint (TAN)."""
    ra0 = math.radians(wcs["ra0"])
    dec0 = math.radians(wcs["dec0"])
    ra_r = np.radians(np.asarray(ra, float))
    dec_r = np.radians(np.asarray(dec, float))
    cos_c = (np.sin(dec0) * np.sin(dec_r)
             + np.cos(dec0) * np.cos(dec_r) * np.cos(ra_r - ra0))
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = np.degrees(np.cos(dec_r) * np.sin(ra_r - ra0) / cos_c)
        eta = np.degrees((np.cos(dec0) * np.sin(dec_r)
                          - np.sin(dec0) * np.cos(dec_r) * np.cos(ra_r - ra0)) / cos_c)
    det = wcs["cd11"] * wcs["cd22"] - wcs["cd12"] * wcs["cd21"]
    if abs(det) < 1e-20:
        raise ValueError("Die CD-Matrix der Loesung ist entartet.")
    dx = (wcs["cd22"] * xi - wcs["cd12"] * eta) / det
    dy = (-wcs["cd21"] * xi + wcs["cd11"] * eta) / det
    hinter = cos_c <= 0                      # auf der anderen Himmelshaelfte
    x = np.where(hinter, np.nan, wcs["x0"] + dx)
    y = np.where(hinter, np.nan, wcs["y0"] + dy)
    return x, y


def objekte_lesen(pfad):
    """Eine Objektliste lesen: CSV mit name,ra,dec[,typ] in Grad."""
    objekte = []
    with open(pfad, encoding="utf-8-sig", newline="") as fh:
        for zeile in csv.DictReader(fh):
            schluessel = {k.strip().lower(): v for k, v in zeile.items() if k}
            try:
                objekte.append(dict(name=(schluessel.get("name") or "").strip(),
                                    ra=float(schluessel["ra"]), dec=float(schluessel["dec"]),
                                    typ=(schluessel.get("typ") or schluessel.get("type")
                                         or "").strip()))
            except (KeyError, TypeError, ValueError):
                continue
    return objekte


def annotieren(bild, loesung, objekte=None, gaia=None, max_mag=9.0, gitter=True,
               log=log_print):
    """Ein Bild beschriften. Gibt eine BGR-Kopie mit Zeichnung zurueck.

    Args:
        bild: BGR float [0..1] oder uint8.
        loesung: die Astrometrie-Loesung (CRVAL/CRPIX/CD).
        objekte: Liste aus `objekte_lesen` — Deep-Sky-Objekte mit Namen.
        gaia: Pfad zum lokalen Gaia-Katalog; ohne Angabe der Standardpfad.
        max_mag: bis zu welcher Helligkeit Sterne beschriftet werden (kleiner = heller).
        gitter: Koordinatengitter zeichnen.
    """
    a = np.asarray(bild)
    if a.dtype != np.uint8:
        a = (np.clip(a, 0, 1) * 255).astype(np.uint8)
    if a.ndim == 2:
        a = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
    aus = a.copy()
    h, w = aus.shape[:2]
    wcs = _wcs_aus_loesung(loesung)
    skala = math.hypot(wcs["cd11"], wcs["cd21"]) * 3600.0        # Bogensekunden je Pixel
    bericht = dict(bogensek_px=skala, breite_grad=w * skala / 3600.0,
                   hoehe_grad=h * skala / 3600.0, sterne=0, objekte=0)

    if gitter:
        # Ein Gitter mit rundem Abstand: so viele Linien, dass es lesbar bleibt.
        spanne = max(w, h) * skala / 3600.0
        for schritt in (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0):
            if spanne / schritt <= 8:
                break
        ra_mitte, dec_mitte = wcs["ra0"], wcs["dec0"]
        for k in range(-8, 9):
            dec = round(dec_mitte / schritt) * schritt + k * schritt
            if abs(dec) > 89.5:
                continue
            ras = ra_mitte + np.linspace(-spanne, spanne, 200) / max(
                math.cos(math.radians(dec)), 1e-3)
            x, y = himmel_zu_pixel(ras, np.full_like(ras, dec), wcs)
            punkte = [(int(xx), int(yy)) for xx, yy in zip(x, y)
                      if np.isfinite(xx) and np.isfinite(yy) and -50 < xx < w + 50
                      and -50 < yy < h + 50]
            for p1, p2 in zip(punkte, punkte[1:]):
                cv2.line(aus, p1, p2, _GRAU, 1, cv2.LINE_AA)
            if punkte:
                cv2.putText(aus, "%+.2f" % dec, punkte[0], cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, _GRAU, 1, cv2.LINE_AA)
            ra = round(ra_mitte / schritt) * schritt + k * schritt
            decs = dec_mitte + np.linspace(-spanne, spanne, 200)
            x, y = himmel_zu_pixel(np.full_like(decs, ra), decs, wcs)
            punkte = [(int(xx), int(yy)) for xx, yy in zip(x, y)
                      if np.isfinite(xx) and np.isfinite(yy) and -50 < xx < w + 50
                      and -50 < yy < h + 50]
            for p1, p2 in zip(punkte, punkte[1:]):
                cv2.line(aus, p1, p2, _GRAU, 1, cv2.LINE_AA)

    # --- helle Sterne aus dem lokalen Gaia-Katalog ---------------------------------------
    try:
        import gaia_lokal
        pfad = gaia or gaia_lokal.standard_pfad()
        if os.path.exists(pfad):
            d = np.load(pfad)
            if "ra" in d and "dec" in d and "g_mag" in d:
                hell = np.asarray(d["g_mag"]) <= float(max_mag)
                ra_s, dec_s = np.asarray(d["ra"])[hell], np.asarray(d["dec"])[hell]
                mag = np.asarray(d["g_mag"])[hell]
                x, y = himmel_zu_pixel(ra_s, dec_s, wcs)
                drin = (np.isfinite(x) & np.isfinite(y) & (x > 0) & (x < w)
                        & (y > 0) & (y < h))
                for xx, yy, mm in zip(x[drin], y[drin], mag[drin]):
                    cv2.circle(aus, (int(xx), int(yy)), 10, _WEISS, 1, cv2.LINE_AA)
                    cv2.putText(aus, "%.1f" % mm, (int(xx) + 12, int(yy) - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, _WEISS, 1, cv2.LINE_AA)
                bericht["sterne"] = int(drin.sum())
    except Exception as e:
        log("    (Sterne aus dem Katalog nicht beschriftet: %s)" % e)

    # --- Deep-Sky-Objekte aus der mitgegebenen Liste --------------------------------------
    for o in (objekte or []):
        x, y = himmel_zu_pixel(np.array([o["ra"]]), np.array([o["dec"]]), wcs)
        xx, yy = float(x[0]), float(y[0])
        if not (np.isfinite(xx) and np.isfinite(yy) and 0 < xx < w and 0 < yy < h):
            continue
        cv2.circle(aus, (int(xx), int(yy)), 26, _GELB, 2, cv2.LINE_AA)
        beschriftung = o["name"] + ((" (%s)" % o["typ"]) if o.get("typ") else "")
        cv2.putText(aus, beschriftung, (int(xx) + 30, int(yy) + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, _GELB, 2, cv2.LINE_AA)
        bericht["objekte"] += 1

    # --- Fussnote: was das Bild zeigt, in Zahlen ------------------------------------------
    zeile = ("Feld %.2f x %.2f Grad   %.2f\"/px   Mitte RA %.4f  Dec %+.4f"
             % (bericht["breite_grad"], bericht["hoehe_grad"], skala,
                wcs["ra0"], wcs["dec0"]))
    cv2.rectangle(aus, (0, h - 30), (w, h), (0, 0, 0), -1)
    cv2.putText(aus, zeile, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, _WEISS, 1,
                cv2.LINE_AA)
    log("    Beschriftet: %d Sterne, %d Objekte, %.2f\"/px"
        % (bericht["sterne"], bericht["objekte"], skala))
    return aus, bericht
