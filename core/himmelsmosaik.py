#!/usr/bin/env python3
"""
core/himmelsmosaik.py — Himmelsmosaik aus gelösten Bildern (wie Siril/PixInsight-Mosaik).

Anders als das Fotopanorama (`mosaic.py`) wird hier über die Himmelsposition (WCS) gearbeitet:
1. Jedes Panel braucht eine Lösung im FITS-Kopf (CRVAL/CD bzw. PC). Ohne → Fehler, kein Raten.
2. Ein gemeinsames TAN-Raster mit Norden oben, Maßstab des feinsten Panels, so groß wie alle
   Panele zusammen.
3. Jedes Panel wird darauf umgerechnet (Himmel → Panel-Pixel → bilinear), linear und ohne
   Beschneiden.
4. Die Hintergründe werden angeglichen: je überlappendem Paar der Median-Unterschied, dann eine
   Ausgleichsrechnung über alle Paare (erstes Panel fest). Die Versätze werden gemeldet.
5. Zusammenfügen mit weichen Rändern (Gewicht = Abstand zum Panelrand).

Pixel ohne Panel bleiben NaN im Ergebnis; ihr Anteil wird gemeldet. Kein Qt.
"""
import os

import numpy as np

try:
    from constants import log_print
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)


def _panel_laden(pfad):
    import astro
    from astropy.io import fits
    from astropy.wcs import WCS
    kopf = fits.getheader(pfad)
    if "CRVAL1" not in kopf:
        raise ValueError("%s hat keine Himmelsposition (WCS). Zuerst „Himmelsposition bestimmen“."
                         % os.path.basename(pfad))
    bild = np.asarray(astro._read_float(pfad), np.float32)
    if bild.ndim == 2:
        bild = bild[..., None]
    return bild, WCS(kopf, naxis=2).celestial


def ausgabe_raster(wcs_liste, formen, rand_px=2):
    """Gemeinsames TAN-WCS mit Norden oben und die Ausgabegröße (h, w)."""
    from astropy.wcs import WCS
    ecken_ra, ecken_dec, skalen = [], [], []
    for w, (h, b) in zip(wcs_liste, formen):
        xs = np.array([0, b - 1, b - 1, 0, (b - 1) / 2]); ys = np.array([0, 0, h - 1, h - 1, (h - 1) / 2])
        ra, dec = w.pixel_to_world_values(xs, ys)
        ecken_ra.append(ra); ecken_dec.append(dec)
        skalen.append(float(np.sqrt(abs(np.linalg.det(w.pixel_scale_matrix)))))
    ra = np.concatenate(ecken_ra); dec = np.concatenate(ecken_dec)
    # Mitte als Vektormittel (verträgt den 0/360-Sprung)
    v = np.stack([np.cos(np.radians(dec)) * np.cos(np.radians(ra)),
                  np.cos(np.radians(dec)) * np.sin(np.radians(ra)), np.sin(np.radians(dec))]).mean(axis=1)
    ra0 = float(np.degrees(np.arctan2(v[1], v[0])) % 360); dec0 = float(np.degrees(np.arcsin(v[2] / np.linalg.norm(v))))
    skala = min(skalen)
    aus = WCS(naxis=2)
    aus.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    aus.wcs.crval = [ra0, dec0]
    aus.wcs.cd = [[-skala, 0.0], [0.0, skala]]
    aus.wcs.crpix = [1.0, 1.0]
    x, y = aus.world_to_pixel_values(ra, dec)
    x0, y0 = np.floor(x.min()) - rand_px, np.floor(y.min()) - rand_px
    breite = int(np.ceil(x.max() - x0)) + rand_px + 1
    hoehe = int(np.ceil(y.max() - y0)) + rand_px + 1
    aus.wcs.crpix = [1.0 - x0, 1.0 - y0]
    return aus, (hoehe, breite)


def _umrechnen(bild, wcs_panel, wcs_aus, form, block=256):
    """Panel auf das Ausgaberaster legen. Gibt (Bild mit NaN außerhalb, Gewicht)."""
    import cv2
    h, w = form
    kan = bild.shape[2]
    aus = np.full((h, w, kan), np.nan, np.float32)
    gewicht = np.zeros((h, w), np.float32)
    ph, pw = bild.shape[:2]
    innen = np.zeros((ph, pw), np.uint8); innen[1:-1, 1:-1] = 1
    rand = cv2.distanceTransform(innen, cv2.DIST_L2, 3).astype(np.float32)
    rand /= max(float(rand.max()), 1.0)
    xs = np.arange(w, dtype=np.float64)
    for y0 in range(0, h, block):
        y1 = min(h, y0 + block)
        gx, gy = np.meshgrid(xs, np.arange(y0, y1, dtype=np.float64))
        ra, dec = wcs_aus.pixel_to_world_values(gx, gy)
        px, py = wcs_panel.world_to_pixel_values(ra, dec)
        px = px.astype(np.float32); py = py.astype(np.float32)
        drin = (px >= 0) & (px <= pw - 1) & (py >= 0) & (py <= ph - 1)
        if not drin.any():
            continue
        for k in range(kan):
            werte = cv2.remap(bild[..., k], px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            aus[y0:y1, :, k] = np.where(drin, werte, np.nan)
        g = cv2.remap(rand, px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        gewicht[y0:y1] = np.where(drin, g, 0)
    return aus, gewicht


def mosaik(pfade, log=log_print):
    """Gelöste FITS zu einem Himmelsmosaik. Gibt (Bild BGR/grau, astropy-WCS, Bericht)."""
    if len(pfade) < 2:
        raise ValueError("Ein Mosaik braucht mindestens zwei gelöste Bilder.")
    panele = [_panel_laden(p) for p in pfade]
    kanaele = {b.shape[2] for b, _ in panele}
    if len(kanaele) > 1:
        raise ValueError("Panele mischen Farbe und Mono — bitte einheitlich.")
    wcs_aus, form = ausgabe_raster([w for _, w in panele], [b.shape[:2] for b, _ in panele])
    if form[0] * form[1] > 400e6:
        raise ValueError("Das Mosaik wäre %d×%d Pixel — Panele gehören wohl nicht zusammen." % form)
    log("Himmelsmosaik: %d Panele → %d×%d Pixel" % (len(panele), form[1], form[0]))
    gelegt = [_umrechnen(b, w, wcs_aus, form) for b, w in panele]

    # Hintergrund angleichen: additive Versätze aus den Überlappungen, erstes Panel fest
    n = len(gelegt)
    zeilen, rechts = [], []
    paare = 0
    for i in range(n):
        for j in range(i + 1, n):
            beide = np.isfinite(gelegt[i][0][..., 0]) & np.isfinite(gelegt[j][0][..., 0])
            if beide.sum() < 500:
                continue
            d = float(np.median((gelegt[i][0][beide] - gelegt[j][0][beide]).mean(axis=-1)))
            z = np.zeros(n); z[i], z[j] = 1.0, -1.0
            zeilen.append(z); rechts.append(d); paare += 1
    if paare < n - 1:
        raise ValueError("Nicht alle Panele überlappen (nur %d Paare für %d Panele) — so ließe sich "
                         "der Hintergrund nicht angleichen." % (paare, n))
    z = np.zeros(n); z[0] = 1.0
    zeilen.append(z); rechts.append(0.0)
    versatz = np.linalg.lstsq(np.array(zeilen), np.array(rechts), rcond=None)[0]
    for i, v in enumerate(versatz):
        log("  Panel %d (%s): Hintergrund-Versatz %+.5f" % (i + 1, os.path.basename(pfade[i]), v))

    summe = np.zeros(form + (gelegt[0][0].shape[2],), np.float64)
    gewichte = np.zeros(form, np.float64)
    for (bild, g), v in zip(gelegt, versatz):
        ok = np.isfinite(bild[..., 0]) & (g > 0)
        summe[ok] += (bild[ok] - v) * g[ok][:, None]
        gewichte[ok] += g[ok]
    leer = gewichte <= 0
    with np.errstate(invalid="ignore", divide="ignore"):
        ergebnis = (summe / gewichte[..., None]).astype(np.float32)
    ergebnis[leer] = np.nan
    log("Himmelsmosaik: %.1f %% der Fläche ohne Panel (bleibt leer/NaN)" % (100 * leer.mean()))
    bericht = {"panele": n, "groesse": form, "versatz": [float(v) for v in versatz],
               "leer_anteil": float(leer.mean())}
    if ergebnis.shape[2] == 1:
        ergebnis = ergebnis[..., 0]
    return ergebnis, wcs_aus, bericht


def mosaik_speichern(pfade, ziel, log=log_print):
    """Mosaik rechnen und als FITS (mit WCS) schreiben. Nie überschreiben."""
    from astropy.io import fits
    if os.path.exists(ziel):
        raise ValueError("%s gibt es schon — bitte neuen Namen wählen." % ziel)
    bild, wcs, bericht = mosaik(pfade, log=log)
    kopf = wcs.to_header()
    kopf.add_history("ForgePix Himmelsmosaik aus %d Panelen" % len(pfade))
    daten = np.ascontiguousarray(bild[..., ::-1].transpose(2, 0, 1)) if bild.ndim == 3 else bild
    fits.PrimaryHDU(daten, header=kopf).writeto(ziel)
    return ziel, bericht
