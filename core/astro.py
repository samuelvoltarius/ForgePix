#!/usr/bin/env python3
"""
astro.py — Astro-Stacking-Modul für ForgePix (Siril-inspiriert, eigenständig).

ANDERER Algorithmus als Fokus-Stacking: Ziel = Rauschen senken (SNR), nicht Schärfentiefe.
Pipeline:
  1. (optional) Kalibrierung: Master-Dark abziehen, durch Master-Flat teilen.
  2. Registrierung: Frames per Phasenkorrelation aufs Referenzbild ausrichten (Translation,
     sub-pixel; robust für nachgeführte Aufnahmen). -> ausgerichtete Temp-Frames auf Platte.
  3. Stacking mit Rejection: average / median / sigma (Kappa-Sigma) / winsor / max.
     Zweistufig über die Platte gerechnet -> speicherschonend auch bei 100+ Frames.
  4. (optional) Auto-Stretch (asinh) fürs Anzeigen des linearen Ergebnisses.

Speicher: hält nie alle Frames gleichzeitig im RAM (anders als der Fokus-Stacker).
Reine OpenCV/NumPy-Abhängigkeiten.
"""
import os

import numpy as np
import cv2

from constants import (RAW_EXTS, ForgePixFehler, imread, imwrite, log_print,
                       require_astropy)

# OSC-Bayer-Muster (FITS BAYERPAT) -> OpenCV-Debayer-Code. Achtung: OpenCVs Bayer-Benennung ist
# ggü. der üblichen FITS-Konvention um eine Zeile/Spalte verschoben (bekannte Falle).
_BAYER2CV = {
    "RGGB": cv2.COLOR_BayerBG2BGR,
    "BGGR": cv2.COLOR_BayerRG2BGR,
    "GRBG": cv2.COLOR_BayerGB2BGR,
    "GBRG": cv2.COLOR_BayerGR2BGR,
}


def detect_bayer(d):
    """CFA-Muster selbst erkennen, wenn kein BAYERPAT im Header steht. Probiert alle 4 Muster,
    debayert einen zentralen Ausschnitt und wählt das mit den GERINGSTEN Farb-Artefakten
    (falsche Muster erzeugen starkes Farb-Zipper/Schachbrett). Default RGGB bei Fehler."""
    try:
        a = np.nan_to_num(np.asarray(d)).astype(np.float32)
        if a.ndim != 2:
            return "RGGB"
        mx = float(a.max()) or 1.0
        h, w = a.shape
        cy, cx = (h // 4) * 2, (w // 4) * 2        # zentriert, gerade Offsets (CFA-Phase wahren)
        s = min(400, (min(h, w) // 2) * 2)
        crop = a[cy:cy + s, cx:cx + s]
        raw16 = np.clip(crop / mx * 65535.0, 0, 65535).astype(np.uint16)
        best, best_score = "RGGB", None
        for pat, code in _BAYER2CV.items():
            bgr = cv2.cvtColor(raw16, code).astype(np.float32) / 65535.0
            chroma = bgr - bgr.mean(axis=2, keepdims=True)   # Farbabweichung vom Grau
            score = float(np.mean(np.abs(cv2.Laplacian(chroma, cv2.CV_32F))))
            if best_score is None or score < best_score:
                best, best_score = pat, score
        return best
    except Exception:
        return "RGGB"


def _read_float(path, debayer=True):
    """Bild als float32 (BGR) lesen; lineare Float-FITS behalten ihre Messwerte."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fit", ".fits", ".fts"):
        fits = require_astropy("FITS-Dateien lesen")
        with fits.open(path) as hdul:
            hdu = hdul[0]
            if hdu.data is None:
                raise ValueError(f"FITS enthält kein Bild im primären HDU: {path}")
            source = np.asarray(hdu.data)
            # Float FITS are physical pixel values, not an undocumented ADU range.
            # Do not infer scaling from the brightest pixel or clip signed residuals.
            d = (source.astype(np.float32) / float(np.iinfo(source.dtype).max)
                 if np.issubdtype(source.dtype, np.integer)
                 else source.astype(np.float32))
            bayer = str(hdu.header.get("BAYERPAT", "")).strip().upper()
            header = hdu.header.copy()
        if d.size == 0 or not np.isfinite(d).all():
            raise ValueError(f"Ungültige FITS-Sensordaten (leer, NaN oder Inf): {path}")
        if d.ndim == 3 and d.shape[0] == 3:     # (C,H,W) -> (H,W,C)
            d = np.moveaxis(d, 0, -1)
        elif d.ndim != 2:
            raise ValueError(f"FITS benötigt ein 2D-Bild oder einen RGB-Würfel (3,H,W): {path}")
        # OSC-Kameras (z. B. Seestar/ASI) liefern Bayer-Rohdaten als 2D-FITS -> debayern = Farbe.
        # Nur ein explizites BAYERPAT rechtfertigt eine CFA-Interpolation.
        if d.ndim == 2:
            if not debayer:
                return d
            if bayer in _BAYER2CV:
                return debayer_float(d, bayer, header.get("XBAYROFF", 0),
                                     header.get("YBAYROFF", 0))
        f = d
        if f.ndim == 2:
            f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
        elif f.shape[2] == 3:
            f = cv2.cvtColor(f, cv2.COLOR_RGB2BGR)    # FITS = RGB -> BGR
        return f
    if ext in RAW_EXTS:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(output_bps=16, use_camera_wb=True, no_auto_bright=True,
                                  output_color=rawpy.ColorSpace.sRGB)
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR); maxv = 65535.0
    else:
        img = imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"Bild nicht lesbar: {path}")
        maxv = (1.0 if np.issubdtype(img.dtype, np.floating)
                else 65535.0 if img.dtype == np.uint16 else 255.0)
    f = img.astype(np.float32) / maxv
    if f.ndim == 2:
        f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
    return f


def debayer_float(raw, pattern, x_offset=0, y_offset=0):
    """Bilineare CFA-Interpolation ohne Quantisierung oder Clipping, Ausgabe BGR.

    Bekannte Sensorwerte bleiben erhalten. Am Rand werden nur vorhandene
    Nachbarn verwendet. Das ist keine detailadaptive oder CFA-Drizzle-Methode.
    """
    raw = np.asarray(raw, np.float32)
    if raw.ndim != 2 or min(raw.shape) < 2 or not np.isfinite(raw).all():
        raise ForgePixFehler("Debayer benötigt ein gültiges 2D-Sensorbild ab 2 × 2 Pixeln.")
    if pattern not in _BAYER2CV:
        raise ForgePixFehler("Unbekanntes Bayer-Muster: %s" % pattern)
    tile = np.array(list(pattern)).reshape(2, 2)
    tile = np.roll(tile, (-int(y_offset) % 2, -int(x_offset) % 2), axis=(0, 1))
    h, w = raw.shape
    output = np.empty((h, w, 3), np.float32)
    rb_kernel = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32)
    g_kernel = np.array([[0, 1, 0], [1, 4, 1], [0, 1, 0]], np.float32)
    for c, name in enumerate("BGR"):
        mask = np.zeros((h, w), np.float32)
        for y, x in np.argwhere(tile == name):
            mask[y::2, x::2] = 1
        kernel = g_kernel if name == "G" else rb_kernel
        weight = cv2.filter2D(mask, -1, kernel, borderType=cv2.BORDER_CONSTANT)
        values = cv2.filter2D(raw * mask, -1, kernel, borderType=cv2.BORDER_CONSTANT)
        output[..., c] = values / weight
    return output


def _master(paths, raw=False):
    """Master-Frame (Median) aus mehreren Kalibrier-Frames, oder einzelnes Frame."""
    if isinstance(paths, str):
        return _read_float(paths, debayer=not raw)
    fs = [_read_float(p, debayer=not raw) for p in paths]
    return np.median(np.stack(fs), axis=0)


def read_calibrated(path, dark=None, flat=None):
    """FITS-Sensordaten zuerst kalibrieren, danach debayern (keine interpolierten Masters)."""
    is_fits = os.path.splitext(path)[1].lower() in (".fit", ".fits", ".fts")
    if is_fits and all(m is None or m.ndim == 2 for m in (dark, flat)):
        raw = _read_float(path, debayer=False)
        if raw.ndim == 2:
            calibrated = calibrate(raw, dark, flat)
            fits = require_astropy("FITS-Kalibrierung")
            header = fits.getheader(path)
            pattern = str(header.get("BAYERPAT", "")).strip().upper()
            if pattern in _BAYER2CV:
                return debayer_float(calibrated, pattern, header.get("XBAYROFF", 0),
                                     header.get("YBAYROFF", 0))
            # Ohne explizites CFA-Muster ist ein FITS monochrom; keine erfundene Farbe.
            return cv2.cvtColor(calibrated.astype(np.float32), cv2.COLOR_GRAY2BGR)
    return calibrate(_read_float(path), dark, flat)


def calibrate(f, dark=None, flat=None):
    """Dark-Abzug und Flat-Division auf vorzeichenbehafteten linearen Werten.

    Negative Rauschwerte dürfen vor der Integration nicht abgeschnitten werden:
    das würde den Mittelwert des dunklen Himmels systematisch anheben.
    """
    f = np.asarray(f, dtype=np.float32)
    if f.size == 0 or not np.isfinite(f).all():
        raise ForgePixFehler("Die Aufnahme enthaelt ungueltige Pixelwerte.")
    for name, master in (("Dark", dark), ("Flat", flat)):
        if master is not None and master.shape != f.shape:
            raise ForgePixFehler("%s-Master passt nicht zur Aufnahme: %s statt %s"
                                 % (name, master.shape, f.shape))
        if master is not None and not np.isfinite(master).all():
            raise ForgePixFehler("%s-Master enthaelt ungueltige Pixelwerte." % name)
    out = f.copy()
    if dark is not None:
        out = out - dark
    if flat is not None:
        mean = float(np.mean(flat, dtype=np.float64))
        if mean <= 0:
            raise ForgePixFehler("Das Flat-Master ist leer oder zu dunkel. Bitte ein gueltiges Flat verwenden.")
        if np.any(flat <= 0):
            raise ForgePixFehler("Das Flat-Master enthält nichtpositive Pixel. Bitte die "
                                 "Flat-/Bias-/Darkflat-Kalibrierung prüfen; durch diese Pixel "
                                 "kann nicht geteilt werden.")
        fn = flat / mean
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            out = out / fn
    with np.errstate(over="ignore", invalid="ignore"):
        out = np.asarray(out, np.float32)
    if not np.isfinite(out).all():
        raise ForgePixFehler("Die Kalibrierung erzeugt ungültige Werte. Bitte Dark und Flat prüfen.")
    return out


def _gray(f):
    return f.mean(axis=2).astype(np.float32) if f.ndim == 3 else f.astype(np.float32)


def cosmetic_correct(f, strength=3.0):
    """Isolierte Ausreißer in Float32 korrigieren, aufgelöste Sternkerne schützen.

    Nachbar-Signal schützt Hot-Kandidaten mit räumlicher Struktur. Ein einzelner
    unterabgetasteter Stern ist ohne Defektkarte nicht sicher vom Hotpixel zu
    unterscheiden. Auf bereits debayerte oder Mono-Daten anwenden, nicht rohe CFA.
    """
    a = np.asarray(f, np.float32)
    if a.ndim not in (2, 3) or not a.size or not np.isfinite(a).all():
        raise ForgePixFehler("Die Hotpixel-Korrektur benötigt gültige Bildwerte.")
    if not np.isfinite(strength) or strength < 0:
        raise ForgePixFehler("Die Stärke der Hotpixel-Korrektur muss mindestens 0 sein.")
    out = a.copy()
    if strength == 0:
        return out
    planes = a[..., None] if a.ndim == 2 else a
    target = out[..., None] if out.ndim == 2 else out
    kernel = np.full((3, 3), 1 / 8, np.float32)
    kernel[1, 1] = 0
    for channel in range(planes.shape[-1]):
        plane = np.ascontiguousarray(planes[..., channel])
        median3 = cv2.medianBlur(plane, 3)
        median5 = cv2.medianBlur(plane, 5)
        diff = plane - median3
        center = float(np.median(diff))
        sigma = max(float(np.median(np.abs(diff - center))) * 1.4826,
                    float(np.max(np.abs(plane))) * np.finfo(np.float32).eps, 1e-30)
        neighbors = cv2.filter2D(plane, -1, kernel, borderType=cv2.BORDER_REFLECT_101)
        candidates = np.abs(diff) > strength * sigma
        adjacent = cv2.filter2D(candidates.astype(np.uint8), cv2.CV_16U,
                                kernel * 8, borderType=cv2.BORDER_CONSTANT)
        hot = (diff > strength * sigma) & (neighbors <= median5 + sigma)
        cold = (diff < -strength * sigma) & (neighbors >= median5 - sigma)
        isolated = (hot | cold) & (adjacent == 0)
        target[..., channel][isolated] = median3[isolated]
    return out







def unclip_stars(f, thresh=0.92, radius=6, max_stars=400, log=log_print):
    """Ausgefressene Sternkerne entsättigen: die FARBE aus den intakten Flanken zurückholen.

    Warum das nötig ist: bei hellen Sternen laufen ein oder mehrere Kanäle in die Sättigung.
    Sind alle drei voll, wird der Kern reinweiß — die Sternfarbe (die eigentliche Information
    über den Spektraltyp) ist im Kern verloren, obwohl sie in den nicht gesättigten FLANKEN
    noch vollständig steht. Ergebnis sonst: ein Feld aus weißen Scheiben statt blauer, gelber
    und roter Sterne. Siril nennt das `unclipstars` / „Desaturate Stars".

    Verfahren (klassisch, kein ML): Sterne mit gesättigtem Kern suchen; um jeden Stern einen
    Ring aus NICHT gesättigten Pixeln auswerten und daraus je Kanal die Amplitude über dem
    lokalen Hintergrund bestimmen; das Kanalverhältnis der Flanke dann auf den Kern übertragen.
    Die Helligkeit des Kerns bleibt, nur seine Farbe wird korrigiert — es wird nichts erfunden,
    die Information kommt aus demselben Stern.

    thresh: ab welchem Pegel ein Kanal als gesättigt gilt (0..1).
    radius: Radius des Kernbereichs; der Auswertering liegt direkt außerhalb.
    Gibt ein neues Bild zurück (Original bleibt unangetastet).
    """
    if f is None or f.ndim != 3 or f.shape[2] != 3:
        return f
    a = np.asarray(f, np.float32).copy()
    H, W = a.shape[:2]
    g = _gray(a)
    # Kandidaten: Sterne, deren Kern irgendwo in die Saettigung laeuft
    kandidaten = _star_centroids(g / (g.max() + 1e-6), max_stars=max_stars)
    r = max(2, int(radius))
    ring_r = r + max(2, r // 2)
    behandelt = 0
    for x, y in kandidaten:
        xi, yi = int(round(x)), int(round(y))
        if not (ring_r <= xi < W - ring_r and ring_r <= yi < H - ring_r):
            continue
        kern = a[yi - r:yi + r + 1, xi - r:xi + r + 1]
        if float(kern.max()) < thresh:
            continue                                  # gar nicht gesaettigt -> nichts zu tun
        umfeld = a[yi - ring_r:yi + ring_r + 1, xi - ring_r:xi + ring_r + 1]
        # Ringmaske: ausserhalb des Kerns, innerhalb des Umfelds
        yy, xx = np.mgrid[0:umfeld.shape[0], 0:umfeld.shape[1]]
        dist = np.sqrt((xx - ring_r) ** 2 + (yy - ring_r) ** 2)
        ring = (dist > r) & (dist <= ring_r)
        if ring.sum() < 8:
            continue
        # Hintergrund aus dem aeussersten Rand, Flankenamplitude als Ring minus Hintergrund
        rand = dist > ring_r - 1
        if rand.sum() < 4:
            continue
        bg = np.array([float(np.median(umfeld[..., c][rand])) for c in range(3)], np.float32)
        flanke = np.array([float(np.median(umfeld[..., c][ring])) for c in range(3)], np.float32) - bg
        if not np.all(np.isfinite(flanke)) or flanke.max() <= 1e-4:
            continue
        # Nur behandeln, wenn die Flanke selbst NICHT gesaettigt ist — sonst ist auch dort
        # keine Farbinformation mehr und jede "Rekonstruktion" waere geraten.
        if float(np.max([np.max(umfeld[..., c][ring]) for c in range(3)])) >= thresh:
            continue
        verh = flanke / float(flanke.max())            # Kanalverhaeltnis der Flanke
        kern_bg = kern - bg.reshape(1, 1, 3)
        spitze = float(np.max(kern_bg))
        if spitze <= 1e-4:
            continue
        # weiche Gewichtung: nur der wirklich gesaettigte Bereich wird umgefaerbt
        ky, kx = np.mgrid[0:kern.shape[0], 0:kern.shape[1]]
        kd = np.sqrt((kx - r) ** 2 + (ky - r) ** 2)
        w_ = np.clip(1.0 - kd / float(r + 1e-6), 0, 1)[..., None]
        neu_kern = bg.reshape(1, 1, 3) + spitze * verh.reshape(1, 1, 3) *             np.clip(kern_bg.max(axis=2, keepdims=True) / spitze, 0, 1)
        a[yi - r:yi + r + 1, xi - r:xi + r + 1] = kern * (1 - w_) + neu_kern * w_
        behandelt += 1
    log(f"    Sternkerne entsättigt: {behandelt} gesättigte Sterne eingefärbt")
    return np.clip(a, 0, 1)

def _rolling_median(werte, fenster):
    """Gleitender Median über ein 1D-Profil (Randbereiche gespiegelt).

    Nicht cv2.medianBlur: das kann bei float32 nur Fenstergröße 3 und 5. Das Profil hat
    nur so viele Werte wie das Bild Zeilen — ein Python-Fenster ist hier unkritisch."""
    v = np.asarray(werte, np.float32)
    n = v.size
    r = max(1, int(fenster) // 2)
    pad = np.pad(v, r, mode="reflect")
    return np.array([np.median(pad[i:i + 2 * r + 1]) for i in range(n)], np.float32)


def fix_banding(f, strength=1.0, vertical=False, protect_sigma=3.0):
    """Zeilen-/Spalten-Banding entfernen (Sensor-Ausleserauschen).

    Viele Kameras (klassisch Canon-DSLRs, aber auch etliche CMOS-Astrokameras) legen ein
    schwaches, ZEILENWEISE konstantes Offset über das Bild. Dark/Flat/Bias beseitigen das
    NICHT: der Versatz ist von Aufnahme zu Aufnahme verschieden, mittelt sich also auch im
    Stack nicht weg, sondern bleibt als feines Streifenmuster im gestreckten Bild stehen.

    Verfahren (klassisch, kein ML): je Zeile den robusten Median bilden, aber nur aus Pixeln
    NAHE dem Himmelshintergrund — Sterne und heller Nebel würden den Zeilenwert sonst
    verfälschen. Das so gewonnene Zeilenprofil enthält zwei Anteile: den echten,
    grossflächigen Helligkeitsverlauf (Gradient, Vignette) und den zeilenweisen Versatz.
    Nur der HOCHFREQUENTE Anteil ist Banding — er ergibt sich als Differenz zum über mehrere
    Zeilen geglätteten Profil und wird abgezogen. Der Gradient bleibt damit unangetastet
    (dafür ist background_extract zuständig).

    strength: 0..1 = anteiliges Abziehen, 1.0 = vollständig.
    vertical: True für spaltenweises Banding (Sensor um 90° gedreht ausgelesen).
    protect_sigma: Pixel mehr als so viele robuste Sigma über dem Median gelten als
                   Signal (Stern/Nebel) und gehen nicht in den Zeilenmedian ein.
    """
    if f is None or strength <= 0:
        return f
    a = np.asarray(f, np.float32)
    einzeln = (a.ndim == 2)
    if einzeln:
        a = a[..., None]
    if vertical:
        a = np.transpose(a, (1, 0, 2))

    out = a.copy()
    for c in range(a.shape[2]):
        k = a[..., c]
        # Signalmaske: alles deutlich über dem Hintergrund ausklammern (Sterne, Nebelkerne)
        med = float(np.median(k))
        mad = float(np.median(np.abs(k - med))) * 1.4826 + 1e-9
        himmel = k < (med + protect_sigma * mad)
        # Zeilenmedian nur über Himmel-Pixel; Zeilen ohne genug Himmel -> Gesamtmedian
        zeilen = np.empty(k.shape[0], np.float32)
        for y in range(k.shape[0]):
            werte = k[y][himmel[y]]
            zeilen[y] = np.median(werte) if werte.size >= max(8, k.shape[1] // 20) else med
        # grossflächigen Verlauf herausrechnen -> nur der zeilenweise Versatz bleibt
        fenster = max(3, (min(31, k.shape[0] // 8) | 1))          # ungerade
        glatt = _rolling_median(zeilen, fenster)
        versatz = (zeilen - glatt).astype(np.float32) * float(np.clip(strength, 0.0, 1.0))
        out[..., c] = k - versatz[:, None]

    if vertical:
        out = np.transpose(out, (1, 0, 2))
    if einzeln:
        out = out[..., 0]
    return out

def _star_centroids(g, max_stars=200):
    """Sternzentren (sub-pixel) als Punktwolke: Hintergrund abziehen, **rauschadaptive Schwelle
    (Median + 5·MAD)**, kleine helle Blobs als Sterne, nach Fläche sortiert.

    Wichtig: Otsu lieferte auf dünnen Astro-Frames nur eine Handvoll Sterne (zu strenge Schwelle),
    wodurch das Ausrichten zu wenig Stützpunkte hatte und Sterne im Stack verschmierten. Die
    MAD-Schwelle findet zuverlässig 100–200 Sterne — genug für robustes Offset-Voting + RANSAC."""
    a = (np.clip(g, 0, 1) * 255).astype(np.uint8)
    bg = cv2.medianBlur(a, 31)
    # VORZEICHENBEHAFTET rechnen. `cv2.subtract` schneidet negative Werte auf 0 ab — damit ist
    # die halbe Rauschverteilung platt, Median und MAD fallen auf 0, und die Schwelle rutscht auf
    # ihren Notwert von 3/255. Auf LINEAREN Subs faellt das nicht auf (das Rauschen liegt ohnehin
    # darunter, gemessen 0,10 % Maske so wie so), auf GESTRECKTEN Bildern ist es verheerend:
    # an einem echten Sub lag die MAD bei 0,000 statt 10,378, die Schwelle bei 3,0 statt 51,9,
    # und 39,9 % der Pixel galten als Sternkandidat statt 4,0 %.
    sub = a.astype(np.float32) - bg.astype(np.float32)
    med = float(np.median(sub))
    mad = float(np.median(np.abs(sub - med))) * 1.4826 + 1e-6
    th = (sub > max(med + 5.0 * mad, 3.0)).astype(np.uint8) * 255
    n, _lbl, stats, cent = cv2.connectedComponentsWithStats(th, connectivity=8)
    stars = [(cent[i][0], cent[i][1], int(stats[i, cv2.CC_STAT_AREA]))
             for i in range(1, n) if 2 <= stats[i, cv2.CC_STAT_AREA] <= 600]
    stars.sort(key=lambda s: -s[2])
    return np.array([[s[0], s[1]] for s in stars[:max_stars]], np.float32)


def _coarse_offset_vote(ref_pts, img_pts, nbright=80, tol=2.5, min_votes=8):
    """Dominanten Versatz (ref − img) aus den hellsten Sternpaaren per Voting bestimmen.

    Robust gegen feste Hotpixel/Amp-Glow (die würden für Versatz (0,0) stimmen) und gegen
    fehlende/zusätzliche Sterne: der echte Sternversatz bekommt die meisten übereinstimmenden
    Stimmen. Ersetzt die Phasenkorrelation, die bei Astro-Frames auf dem festen Fixed-Pattern
    statt auf den (gewanderten) Sternen einrastet. Gibt (ox, oy) oder None."""
    if len(ref_pts) < min_votes or len(img_pts) < min_votes:
        return None
    R, I = ref_pts[:nbright], img_pts[:nbright]
    offs = (R[:, None, :] - I[None, :, :]).reshape(-1, 2)        # alle Paar-Versätze
    # Voting vektorisiert (statt Python-Schleife über bis zu 6400 Kandidaten, pro Frame):
    # je Kandidat zählen, wie viele Versätze im tol-Fenster (Chebyshev) liegen.
    # KD-Baum: O(n log n) statt O(n²) — bei 6400 Kandidaten ~200× schneller. (Einziger
    # theoretischer Unterschied: <= tol statt < tol am exakten Fensterrand — bei
    # float-Sternzentren praktisch unmöglich.) Fallback ohne scipy: gechunktes Broadcasting.
    n = len(offs)
    try:
        from scipy.spatial import cKDTree
        counts = cKDTree(offs).query_ball_point(offs, r=tol, p=np.inf, return_length=True)
    except Exception:
        counts = np.empty(n, np.int32)
        step = max(1, 4_000_000 // max(1, n))                    # Chunk-Zeilen fürs RAM-Budget
        for s in range(0, n, step):
            counts[s:s + step] = (np.abs(offs[s:s + step, None, :] - offs[None, :, :])
                                  .max(2) < tol).sum(1)
    bestc = int(counts.max()) if n else 0
    if bestc < min_votes:
        return None
    best = offs[int(np.argmax(counts))]     # argmax = erster Index mit Maximalzahl (wie zuvor)
    # Mittel der zustimmenden Versätze (sub-pixel-genauer als ein einzelner Paar-Versatz)
    near = offs[np.abs(offs - best).max(1) < tol]
    return near.mean(0)


def _estimate_star_transform(refg, img_g):
    """Translation + Feldrotation aus tatsächlichen STERNPOSITIONEN schätzen (genauer = rundere
    Sterne). Grober Versatz per Offset-Voting (robust gegen Hotpixel), dann Nearest-Neighbor-Match
    + RANSAC-Affine. Gibt 2x3-Matrix oder None (dann Fallback ORB)."""
    ref_pts, img_pts = _star_centroids(refg), _star_centroids(img_g)
    if len(ref_pts) < 8 or len(img_pts) < 8:
        return None
    off = _coarse_offset_vote(ref_pts, img_pts)
    if off is None:
        return None
    shifted = img_pts + off                                     # img ≈ in ref-Raster gebracht
    src, dst = [], []
    for rp in ref_pts:                                          # ref-Stern -> nächster img-Stern
        d = np.linalg.norm(shifted - rp, axis=1)
        j = int(np.argmin(d))
        if d[j] < 4.0:                                          # Toleranz in px (nach Grobversatz)
            src.append(img_pts[j]); dst.append(rp)
    if len(src) < 6:
        return None
    M, inl = cv2.estimateAffinePartial2D(np.array(src, np.float32), np.array(dst, np.float32),
                                         method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None or (inl is not None and int(inl.sum()) < 6):
        return None
    return M


def _estimate_star_shift(refg, img_g):
    """REINE Translation aus dem Offset-Voting der Sternzentren — für align_mode='shift'
    (nachgeführte Montierung ohne Feldrotation). Bewusst KEINE Rotations-Schätzung: der Nutzer
    hat zugesichert, dass nur Drift/Dither vorliegt. Gibt 2x3-Translationsmatrix oder None."""
    ref_pts, img_pts = _star_centroids(refg), _star_centroids(img_g)
    if len(ref_pts) < 8 or len(img_pts) < 8:
        return None
    off = _coarse_offset_vote(ref_pts, img_pts)
    if off is None:
        return None
    return np.float32([[1, 0, off[0]], [0, 1, off[1]]])       # img + off ≈ ref


def match_stars_triangles(ref_pts, img_pts, n_use=60, tol=0.02, min_matches=6):
    """A3 — Asterismus-/Dreiecks-Matching (astroalign-Prinzip): Sternkorrespondenzen OHNE jede
    Annahme über Translation, Skalierung, Rotation ODER Spiegelung finden.

    Idee: Aus den hellsten Sternen werden Dreiecke gebildet und je Dreieck ein **invarianter
    Deskriptor** aus zwei normierten Seitenverhältnissen berechnet (kürzeste/längste und
    mittlere/längste Seite). Diese beiden Zahlen ändern sich nicht unter Skalierung, Rotation oder
    Spiegelung — nur die Sterngeometrie zählt. Über einen cKDTree im 2D-Deskriptorraum werden
    Ref-Dreiecke ihren ähnlichsten Img-Dreiecken zugeordnet; jedes übereinstimmende Dreieck
    "stimmt" für seine drei Stern-zu-Stern-Paare ab. Die Paare mit den meisten Stimmen gewinnen.

    Dadurch greift das Matching auch bei großer Feldrotation, Mosaik-Überlappung oder gemischter
    Optik (unterschiedliche Brennweite/Spiegelung), wo das translationsbasierte Offset-Voting
    versagt.

    Args:
        ref_pts, img_pts: (N,2)-Punktwolken (x,y), z. B. aus `_star_centroids`.
        n_use: nur die hellsten/ersten N Sterne je Bild verwenden (Dreiecks-Zahl ~ N³).
        tol: Toleranz im Deskriptorraum (euklidisch über die zwei Seitenverhältnisse).
        min_matches: Mindestanzahl gevoteter Sternpaare, sonst (None, None).

    Returns:
        (src, dst) — zwei (M,2)-Arrays korrespondierender Punkte (img → ref), oder (None, None).
        scipy optional; ohne scipy Fallback auf eine NumPy-Nächste-Nachbar-Suche.
    """
    ref_pts = np.asarray(ref_pts, np.float32)
    img_pts = np.asarray(img_pts, np.float32)
    if len(ref_pts) < 3 or len(img_pts) < 3:
        return None, None
    R = ref_pts[:n_use]
    I = img_pts[:n_use]

    def _descriptors(pts):
        """Alle Dreiecke (Index-Tripel) → invariante Deskriptoren (2D). Verwirft sehr schmale
        (kollineare) Dreiecke als instabil."""
        m = len(pts)
        descs, tris = [], []
        from itertools import combinations
        for a, b, c in combinations(range(m), 3):
            pa, pb, pc = pts[a], pts[b], pts[c]
            s = sorted([
                (float(np.linalg.norm(pb - pc)), (a,)),     # Seite gegenüber a
                (float(np.linalg.norm(pa - pc)), (b,)),
                (float(np.linalg.norm(pa - pb)), (c,)),
            ])
            L = s[2][0]
            if L < 1e-3:
                continue
            r1 = s[0][0] / L                                # kürzeste / längste
            r2 = s[1][0] / L                                # mittlere / längste
            if r1 < 0.05 or (L - s[1][0]) < 1e-3:           # zu kollinear → instabil
                continue
            # Eckenreihenfolge nach gegenüberliegender Seitenlänge sortieren → spiegel-/rotations-
            # invariante, konsistente Zuordnung der drei Punkte.
            order = (s[0][1][0], s[1][1][0], s[2][1][0])
            descs.append((r1, r2))
            tris.append(order)
        return np.array(descs, np.float32), tris

    rd, rtris = _descriptors(R)
    idd, itris = _descriptors(I)
    if len(rd) == 0 or len(idd) == 0:
        return None, None

    # Nächste Img-Deskriptoren zu jedem Ref-Deskriptor suchen.
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(idd)
        dists, idxs = tree.query(rd, k=1)
    except Exception:
        dists = np.empty(len(rd), np.float32)
        idxs = np.empty(len(rd), np.int64)
        for j, d in enumerate(rd):
            dd = np.linalg.norm(idd - d, axis=1)
            k = int(np.argmin(dd))
            dists[j] = dd[k]; idxs[j] = k

    # Voting: jedes gut passende Dreieckspaar stimmt für seine drei Eck-Korrespondenzen.
    votes = {}
    for j, (dist, k) in enumerate(zip(dists, idxs)):
        if dist > tol:
            continue
        rt = rtris[j]; it = itris[int(k)]
        for ri, ii in zip(rt, it):                          # img-Index → ref-Index
            votes[(ii, ri)] = votes.get((ii, ri), 0) + 1

    if not votes:
        return None, None
    # Pro Img-Stern die ref-Zuordnung mit den meisten Stimmen wählen (1:1, gegenseitig-konsistent).
    best_for_img = {}
    for (ii, ri), c in votes.items():
        if ii not in best_for_img or c > best_for_img[ii][1]:
            best_for_img[ii] = (ri, c)
    used_ref = {}
    pairs = []
    for ii, (ri, c) in sorted(best_for_img.items(), key=lambda kv: -kv[1][1]):
        if c < 2:                                           # mind. 2 Dreiecke müssen es bestätigen
            continue
        if ri in used_ref:                                  # ref-Stern schon vergeben → überspringen
            continue
        used_ref[ri] = True
        pairs.append((ii, ri))
    if len(pairs) < min_matches:
        return None, None
    src = np.array([I[ii] for ii, _ in pairs], np.float32)
    dst = np.array([R[ri] for _, ri in pairs], np.float32)
    return src, dst


def _estimate_star_transform_robust(refg, img_g, full_affine=False):
    """A3 — robuste Stern-Transform über Dreiecks-Matching (translationsfrei).

    Schätzt die Abbildung img → ref allein aus der Sterngeometrie und funktioniert daher auch über
    große Feldrotation, Mosaik-Überlappung oder Mischoptik (Skalierung/Spiegelung), wo das
    bestehende, translationsannehmende Offset-Voting (`_estimate_star_transform`) aussteigt.

    Ablauf: Sternzentren beider Bilder → `match_stars_triangles` → RANSAC-Affine. `full_affine=True`
    erlaubt zusätzlich Skalierung/Scherung/Spiegelung (volle Affine), sonst Ähnlichkeits-Affine
    (Translation+Rotation+gleichmäßige Skalierung). Fallback auf das bestehende Offset-Voting,
    wenn das Dreiecks-Matching keine ausreichenden Korrespondenzen liefert. Gibt 2x3 oder None.
    """
    ref_pts = _star_centroids(refg)
    img_pts = _star_centroids(img_g)
    if len(ref_pts) >= 3 and len(img_pts) >= 3:
        src, dst = match_stars_triangles(ref_pts, img_pts)
        if src is not None and len(src) >= 3:
            if full_affine:
                M, inl = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC,
                                              ransacReprojThreshold=3.0)
            else:
                M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                     ransacReprojThreshold=3.0)
            if M is not None and (inl is None or int(inl.sum()) >= 3):
                return M.astype(np.float32)
    # Fallback: bestehendes translationsbasiertes Verfahren
    return _estimate_star_transform(refg, img_g)


def _estimate_rotation(refg, img_g, detector="ORB", min_inliers=25):
    """Partielle Affine (Translation + Rotation, kein Scherung) per ORB-Merkmalen schätzen —
    Fallback, wenn das stern-basierte Voting den Versatz nicht findet (z. B. großer Dither-Sprung
    in einen wenig überlappenden Bereich). Gibt 2x3-Matrix nur bei genügend Inliern zurück, sonst
    None — damit unsicher ausgerichtete Frames lieber verworfen als verschmiert gestackt werden."""
    a = (np.clip(refg, 0, 1) * 255).astype(np.uint8)
    b = (np.clip(img_g, 0, 1) * 255).astype(np.uint8)
    # detector wirklich verdrahten: 'sift'/'akaze' auf Wunsch, sonst ORB — mit Fallback auf ORB,
    # falls das gewählte Feature im OpenCV-Build fehlt.
    det = None
    name = str(detector or "ORB").upper()
    try:
        if name == "SIFT":
            det = cv2.SIFT_create()
        elif name == "AKAZE":
            det = cv2.AKAZE_create()
    except Exception:
        det = None
    if det is None:
        det = cv2.ORB_create(5000)
    ka, da = det.detectAndCompute(a, None)
    kb, db = det.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return None
    # Binär-Deskriptoren (ORB/AKAZE) → Hamming; Float-Deskriptoren (SIFT) → L2
    norm = cv2.NORM_HAMMING if da.dtype == np.uint8 else cv2.NORM_L2
    bf = cv2.BFMatcher(norm, crossCheck=True)
    m = sorted(bf.match(da, db), key=lambda x: x.distance)[:300]
    if len(m) < min_inliers:
        return None
    src = np.float32([kb[x.trainIdx].pt for x in m]).reshape(-1, 1, 2)
    dst = np.float32([ka[x.queryIdx].pt for x in m]).reshape(-1, 1, 2)
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    if M is None or inl is None or int(inl.sum()) < min_inliers:
        return None
    return M


def _compose_affine(A, B):
    """Zwei 2x3-Affinen verketten: Ergebnis bildet ab wie erst B, dann A (A∘B)."""
    A3 = np.vstack([A, [0, 0, 1]]); B3 = np.vstack([B, [0, 0, 1]])
    return (A3 @ B3)[:2].astype(np.float32)


def _tps_refine(fw, refg_out, max_ctrl=150, min_resid=0.5, log=log_print, coverage=None):
    """Lokale (nicht-rigide) Feinregistrierung per Thin-Plate-Spline gegen RESTVERZEICHNUNG —
    Feldkrümmung bei Weitwinkel/Refraktor, atmosphärische Refraktion, leichtes Tilt. Nach der
    globalen Affin-Ausrichtung bleibende Restversätze der Sterne werden als glattes Warp-Feld
    herausgerechnet (Sterne werden über das ganze Feld rund). Nur aktiv, wenn genug Sternpaare
    mit echtem Restversatz da sind — sonst bleibt der Frame unverändert (kein Verschlimmbessern)."""
    def unchanged():
        return (fw, coverage) if coverage is not None else fw

    try:
        from scipy.interpolate import RBFInterpolator
    except Exception:
        return unchanged()
    fg = _gray(fw)
    rp = _star_centroids(refg_out, max_stars=max_ctrl)
    ip = _star_centroids(fg, max_stars=max_ctrl * 3)
    if len(rp) < 12 or len(ip) < 12:
        return unchanged()
    src, dst = [], []
    for r in rp:                                            # ref-Pos -> nächste Frame-Pos
        d = np.linalg.norm(ip - r, axis=1)
        j = int(np.argmin(d))
        if d[j] < 6.0:
            dst.append(r); src.append(ip[j])
    if len(src) < 12:
        return unchanged()
    src = np.array(src, np.float32); dst = np.array(dst, np.float32)
    resid = np.linalg.norm(src - dst, axis=1)
    if float(np.median(resid)) < min_resid:
        return unchanged()                                  # global schon sauber → nichts zu tun
    h, w = fg.shape[:2]
    try:
        rbf = RBFInterpolator(dst, src, kernel="thin_plate_spline", smoothing=1.0)
        gs = 48                                             # grobes Gitter, TPS ist glatt → hochskalieren
        gx, gy = np.meshgrid(np.linspace(0, w - 1, gs), np.linspace(0, h - 1, gs))
        q = np.stack([gx.ravel(), gy.ravel()], 1)
        mapped = rbf(q).reshape(gs, gs, 2).astype(np.float32)
        mapx = cv2.resize(mapped[..., 0], (w, h))
        mapy = cv2.resize(mapped[..., 1], (w, h))
        out = cv2.remap(fw, mapx, mapy, interpolation=cv2.INTER_LANCZOS4,
                        borderMode=cv2.BORDER_CONSTANT)
        if coverage is not None:
            support = cv2.erode(coverage.astype(np.uint8), np.ones((9, 9), np.uint8),
                                borderType=cv2.BORDER_CONSTANT, borderValue=0)
            valid = cv2.remap(support.astype(np.float32), mapx, mapy,
                              interpolation=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT) >= 0.99999
            out[~valid] = 0
        log(f"      TPS-Feinregistrierung: {len(src)} Sterne, Rest {float(np.median(resid)):.2f}px")
        return (out, valid) if coverage is not None else out
    except Exception:
        return unchanged()


def _warp_and_save(f, M, out_size, op, drizzle, tps_refg=None):
    import tifffile
    f = np.asarray(f, dtype=np.float32)
    if f.size == 0 or not np.isfinite(f).all():
        raise ForgePixFehler("Registrierung: Aufnahme enthaelt ungueltige Pixelwerte.")
    coverage = np.ones(f.shape[:2], np.uint8)
    if M is not None:
        if drizzle > 1:
            # VOLLE 2x3-Matrix skalieren (wie in drizzle_stack) — nur die Translation zu skalieren
            # ließe den linearen Teil (Rotation/Skala) unskaliert im drizzle-fachen Canvas
            # (registrierte Frames wären geometrisch falsch).
            M = (drizzle * M).astype(np.float32)
        # Integer translations need no interpolation support outside their pixel.
        integer_shift = (np.allclose(M[:, :2], np.eye(2), atol=1e-7)
                         and np.allclose(M[:, 2], np.rint(M[:, 2]), atol=1e-7))
        support = coverage if integer_shift else cv2.erode(
            coverage, np.ones((9, 9), np.uint8),
            borderType=cv2.BORDER_CONSTANT, borderValue=0)
        coverage = cv2.warpAffine(support.astype(np.float32), M, out_size,
                                 flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT) >= 0.99999
        f = cv2.warpAffine(f, M, out_size, flags=cv2.INTER_LANCZOS4,
                          borderMode=cv2.BORDER_CONSTANT)
    elif drizzle > 1:
        f = cv2.resize(f, out_size, interpolation=cv2.INTER_LANCZOS4)
        coverage = np.ones(f.shape[:2], bool)
    if tps_refg is not None:
        f, coverage = _tps_refine(f, tps_refg, log=lambda *a: None, coverage=coverage)
    f[~coverage.astype(bool)] = 0
    mask_path = str(op) + ".coverage.tif"
    tifffile.imwrite(mask_path, coverage.astype(np.uint8), metadata=None)
    rgb = f[..., ::-1] if f.ndim == 3 and f.shape[2] == 3 else f
    tifffile.imwrite(op, rgb, photometric="rgb" if rgb.ndim == 3 else "minisblack",
                     metadata=None, description="ForgePix registration; coverage=" + os.path.basename(mask_path))
    return op



def _ref_path(paths, ref_path=None):
    """Referenz-Sub waehlen: der uebergebene, sonst der mittlere der Serie.

    Der mittlere ist nur ein Notbehelf (Mitte der Session = Mitte der Drift). Wer die
    Sub-Bewertung hat, sollte den QUALITATIV besten uebergeben — siehe
    astro_quality.best_reference()."""
    if ref_path and ref_path in paths:
        return ref_path
    return paths[len(paths) // 2]


def register_and_cache(paths, out_dir, dark=None, flat=None, do_register=True,
                       align_mode="shift", cosmetic=False, drizzle=1, detector="ORB",
                       tps=False, ref_path=None, banding=0.0, log=log_print):
    """Frames kalibrieren + ausrichten, als float32-TIFF mit Abdeckungsmaske ablegen.

    align_mode: 'shift' = NUR Translation (Nachführung ohne Feldrotation, s. CLI --astro-align),
                'rotate' = Translation + Feldrotation (Alt-Az). Stern-basiert; phaseCorrelate wird
                bewusst NICHT genutzt — rastet bei Astro auf dem festen Fixed-Pattern statt auf
                den gewanderten Sternen ein.
    cosmetic:   Hot-/Cold-Pixel vor dem Ausrichten entfernen.
    banding:    Staerke der Zeilen-Banding-Korrektur je Sub (0 = aus). Muss VOR dem Ausrichten
                laufen: der Versatz haengt am Sensor, nicht am Himmel — nach dem Verschieben
                waere er ueber die Zeilen verschmiert und nicht mehr sauber zu fassen.
    drizzle:    Ausgabe-Hochskalierung (1=aus, 2=doppelte Kantenlänge, „Drizzle-lite").

    Parallel über alle Kerne (OpenCV gibt den GIL frei). Frames, die sich nicht an die Referenz
    ausrichten lassen (großer Dither-Sprung), werden in einem 2. Pass über eine Cluster-Brücke
    zurückgeholt statt verworfen. Gibt die Liste der ausgerichteten Pfade zurück."""
    from parallel import pmap
    os.makedirs(out_dir, exist_ok=True)
    drizzle = max(1, int(drizzle))
    ref = read_calibrated(_ref_path(paths, ref_path), dark, flat)
    if banding:
        ref = fix_banding(ref, strength=banding)
    if cosmetic:
        ref = cosmetic_correct(ref)
    refg = _gray(ref)
    out_size = (ref.shape[1] * drizzle, ref.shape[0] * drizzle)
    tps_refg = (cv2.resize(refg, out_size) if drizzle > 1 else refg) if tps else None
    if tps:
        log("    TPS-Feinregistrierung aktiv (lokale Restverzeichnung wird korrigiert)")

    def _prep(i):
        f = read_calibrated(paths[i], dark, flat)
        if f.shape[:2] != ref.shape[:2]:
            raise ForgePixFehler("Aufnahme passt nicht zur Referenzgroesse: %s (%s statt %s)"
                                 % (paths[i], f.shape[:2], ref.shape[:2]))
        if banding:
            f = fix_banding(f, strength=banding)
        if cosmetic:
            f = cosmetic_correct(f)
        return f

    def _one(i):
        f = _prep(i)
        op = os.path.join(out_dir, f"reg_{i:04d}.tif")
        if not do_register:
            return (i, _warp_and_save(f, None, out_size, op, drizzle))
        fg = _gray(f)
        if align_mode == "shift":
            # 'shift' = nur Translation: Rotations-Schätzungen werden bewusst übersprungen
            # (vorher wurde der Parameter nie gelesen und immer voll affin geschätzt).
            M = _estimate_star_shift(refg, fg)
        else:
            M = _estimate_star_transform(refg, fg)
            if M is None:
                # Dreiecks-Matching (translationsfrei, astroalign-Prinzip) als 2. Versuch,
                # BEVOR auf die ORB-Merkmals-Schätzung zurückgefallen wird.
                M = _estimate_star_transform_robust(refg, fg)
            if M is None:
                M = _estimate_rotation(refg, fg, detector)
        if M is None:
            return (i, None)                                 # 2. Pass versucht Cluster-Brücke
        return (i, _warp_and_save(f, M, out_size, op, drizzle, tps_refg))

    results = pmap(_one, list(range(len(paths))), memory_heavy=True)
    aligned = [op for _i, op in sorted(results) if op]
    skipped = [i for i, op in sorted(results) if op is None]
    log(f"    registriert {len(aligned)}/{len(paths)} (Pass 1)")

    # ---- Pass 2: weit weggeditherte Frames über eine Cluster-Brücke zurückholen ----
    # Sub-Referenz im Cluster wählen → per ORB an die Hauptreferenz brücken → jeden Frame an die
    # Sub-Referenz ausrichten und die Transforms verketten. JEDER zurückgeholte Frame wird verifiziert
    # (seine Sterne müssen nach der Transformation gut auf die Referenz fallen), sonst bleibt er außen
    # vor — so kann eine schwache Brücke kein Verschmieren zurückbringen.
    if do_register and len(skipped) >= 3:
        ref_pts = _star_centroids(refg)
        # _prep je Frame nur EINMAL laufen lassen (vorher lief es doppelt: fürs Grau hier und
        # nochmal fürs Warpen unten) — kostet etwas RAM für die übersprungenen Frames,
        # spart aber einen vollen Lese-/Kalibrier-Pass pro gerettetem Frame.
        preps = {i: _prep(i) for i in skipped}
        grays = {i: _gray(f) for i, f in preps.items()}
        subref = max(skipped, key=lambda i: len(_star_centroids(grays[i])))
        bridge = _estimate_rotation(refg, grays[subref], detector, min_inliers=10)  # subref -> ref
        rescued = 0
        if bridge is not None and len(ref_pts) >= 8:
            for i in skipped:
                S = (np.float32([[1, 0, 0], [0, 1, 0]]) if i == subref
                     else _estimate_star_transform(grays[subref], grays[i]))   # frame -> subref
                if S is None:
                    continue
                M = _compose_affine(bridge, S)               # frame -> subref -> ref
                # Verifizieren: Sterne des Frames mit M ins Ref-Raster bringen, gute Treffer zählen
                ip = _star_centroids(grays[i])
                if len(ip) < 8:
                    continue
                ext = np.hstack([ip, np.ones((len(ip), 1), np.float32)])
                tp = (M @ ext.T).T
                good = sum(1 for r in ref_pts if np.min(np.linalg.norm(tp - r, axis=1)) < 1.5)
                if good < 25:                                # zu wenige saubere Treffer → lieber lassen
                    continue
                op = os.path.join(out_dir, f"reg_{i:04d}.tif")
                aligned.append(_warp_and_save(preps.pop(i), M, out_size, op, drizzle, tps_refg))
                rescued += 1
        if rescued:
            log(f"    +{rescued} weit geditherte Frames über Cluster-Brücke zurückgeholt ({len(aligned)}/{len(paths)})")
    return sorted(aligned)


def drizzle_stack(paths, scale=2, pixfrac=0.7, dark=None, flat=None, cosmetic=False,
                  detector="ORB", ref_path=None, banding=0.0, log=log_print, *,
                  align_mode="rotate", do_register=True, transforms=None, masks=None,
                  cfa="auto", return_info=False, cancel=None):
    """Exact square-drop integration, including raw Bayer samples when specified.

    Float32 output uses input/reference pixel brightness units. Aperture sums
    require the output pixel area 1/scale². Float64 sums retain signed/HDR values;
    uncovered channel samples are zero placeholders, never interpolated. Call
    return_info=True to retain weights, channel coverage and registration history.
    This is a weighted mean, without rejection, WCS distortion or TPS resampling.
    """
    from drizzle import DrizzleAccumulator, _cancelled
    _cancelled(cancel)
    paths = list(paths)
    if not paths:
        raise ForgePixFehler("Drizzle: keine Eingabeaufnahmen.")
    if align_mode not in ("shift", "rotate") or cfa not in ("auto", "preserve", "debayer"):
        raise ForgePixFehler("Drizzle: unbekannter Registrierungs- oder CFA-Modus.")
    if transforms is not None and len(transforms) != len(paths):
        raise ForgePixFehler("Drizzle: eine Transformation pro Aufnahme ist erforderlich.")
    if masks is not None and len(masks) != len(paths):
        raise ForgePixFehler("Drizzle: eine Gewichtsmaske pro Aufnahme ist erforderlich.")
    reference = _ref_path(paths, ref_path)
    headers = {}
    for path in paths:
        _cancelled(cancel)
        extension = os.path.splitext(path)[1].lower()
        if extension in (".fit", ".fits", ".fts"):
            headers[path] = require_astropy("Drizzle-Sensormetadaten").getheader(path)
        elif extension in (".tif", ".tiff"):
            import json
            import tifffile
            with tifffile.TiffFile(path) as file:
                if file.pages[0].dtype == np.uint8:
                    raise ForgePixFehler("Drizzle benötigt lineare FITS oder mindestens 16-Bit-TIFF, keine 8-Bit-Anzeigebilder.")
                try:
                    metadata = json.loads(file.pages[0].description or "{}")
                except (ValueError, TypeError):
                    metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            headers[path] = (require_astropy("TIFF-Drizzle-Metadaten").Header.fromstring(metadata["fits_header"], sep="\n")
                             if isinstance(metadata.get("fits_header"), str) else {})
            if metadata.get("linear") is False:
                raise ForgePixFehler("Drizzle: dieses TIFF wurde bereits gestreckt. Lineare Aufnahmen verwenden.")
            for key in ("FPCOV", "BAYERPAT"):
                if key in metadata:
                    headers[path][key] = metadata[key]
            if headers[path].get("BAYERPAT"):
                raise ForgePixFehler("CFA-Drizzle benötigt rohe FITS-Sensorsamples; CFA-TIFF wird noch nicht unterstützt.")
        else:
            raise ForgePixFehler("Drizzle benötigt lineare FITS- oder TIFF-Aufnahmen; JPEGs und andere Anzeigebilder sind keine Messdaten.")
        if headers[path].get("FPLINEAR") is False:
            raise ForgePixFehler("Drizzle: die Aufnahme wurde bereits gestreckt. Lineare Aufnahmen verwenden.")
    patterns = {path: str(header.get("BAYERPAT", "")).strip().upper() for path, header in headers.items()}
    if any(pattern and pattern not in _BAYER2CV for pattern in patterns.values()):
        raise ForgePixFehler("Drizzle: unbekanntes CFA-Muster im FITS-Header.")
    preserve_cfa = cfa != "debayer" and bool(patterns[reference])
    if cfa == "preserve" and not preserve_cfa:
        raise ForgePixFehler("CFA-Drizzle benötigt ein explizites Bayer-Muster im FITS-Header.")
    if preserve_cfa and not all(patterns.values()):
        raise ForgePixFehler("Drizzle: rohe CFA- und bereits debayerte/Mono-Aufnahmen nicht mischen.")
    if not preserve_cfa and cfa != "debayer" and any(patterns.values()):
        raise ForgePixFehler("Drizzle: die Referenz und die Serie haben unterschiedliche CFA-Datenarten.")
    if preserve_cfa and (cosmetic or banding):
        raise ForgePixFehler("CFA-Drizzle erhält die Sensorsamples. Hotpixel-/Banding-Korrektur hier deaktivieren; rohe Darks/Flats sind unterstützt.")
    exposures = [float(h.get("EXPTIME", h.get("EXPOSURE", 0)) or 0) for h in headers.values()]
    known_exposures = [value for value in exposures if value > 0]
    if known_exposures and max(known_exposures) / min(known_exposures) > 1.01:
        raise ForgePixFehler("Drizzle: unterschiedliche Belichtungszeiten getrennt integrieren; Belichtungsnormalisierung ist hier noch nicht implementiert.")

    def prepare(path):
        _cancelled(cancel)
        if preserve_cfa:
            frame = calibrate(_read_float(path, debayer=False), dark, flat)
            if frame.ndim != 2:
                raise ForgePixFehler("CFA-Drizzle benötigt unveränderte zweidimensionale Sensorsamples.")
            header = headers[path]
            offsets = [header.get(key, 0) for key in ("XBAYROFF", "YBAYROFF")]
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) or int(v) != v for v in offsets):
                raise ForgePixFehler("Drizzle: Bayer-Offsets müssen ganze Pixel sein.")
            tile = np.array(["BGR".index(colour) for colour in patterns[path]]).reshape(2, 2)
            tile = np.roll(tile, (-int(offsets[1]) % 2, -int(offsets[0]) % 2), axis=(0, 1))
            colours = tile[np.arange(frame.shape[0])[:, None] % 2, np.arange(frame.shape[1])[None, :] % 2]
            # Debayer ONLY the registration proxy. The accumulator sees raw CFA.
            proxy = debayer_float(frame, patterns[path], *offsets)
        else:
            frame, colours = read_calibrated(path, dark, flat), None
            if banding:
                frame = fix_banding(frame, strength=banding)
            if cosmetic:
                frame = cosmetic_correct(frame)
            proxy = frame
        return frame, colours, _gray(proxy)

    ref, ref_colours, refg = prepare(reference)
    accumulator = DrizzleAccumulator(ref.shape[:2], scale=scale, pixfrac=pixfrac, channels=3, cancel=cancel)
    used, skipped, registrations = [], [], []
    identity = np.array([[1., 0., 0.], [0., 1., 0.]])
    log("    Drizzle: flächengewichtetes Mittel ohne Sigma-Rejection; keine erfundenen Pixel in Abdeckungslücken.")
    for index, path in enumerate(paths):
        _cancelled(cancel)
        frame, colours, gray = (ref, ref_colours, refg) if path == reference else prepare(path)
        if frame.shape != ref.shape:
            raise ForgePixFehler("Drizzle: Aufnahme passt nicht zur Referenzform: %s (%s statt %s)" % (path, frame.shape, ref.shape))
        if transforms is not None:
            matrix = transforms[index]
        elif not do_register or path == reference:
            matrix = identity
        elif align_mode == "shift":
            matrix = _estimate_star_shift(refg, gray)
        else:
            matrix = _estimate_star_transform(refg, gray)
            if matrix is None:
                matrix = _estimate_star_transform_robust(refg, gray)
            if matrix is None:
                matrix = _estimate_rotation(refg, gray, detector)
        if matrix is None:
            skipped.append(str(path))
            log("    Drizzle: keine belastbare Registrierung, Aufnahme ausgelassen: %s" % path)
            continue
        input_weight = 1. if masks is None else masks[index]
        coverage_name = headers[path].get("FPCOV")
        if coverage_name:
            from pathlib import Path
            import tifffile
            if not isinstance(coverage_name, str) or Path(coverage_name).name != coverage_name or "\\" in coverage_name:
                raise ForgePixFehler("Drizzle: ungültiger Verweis auf die Eingabeabdeckung.")
            coverage_path = Path(path).resolve().parent / coverage_name
            if not coverage_path.is_file() or coverage_path.resolve().parent != Path(path).resolve().parent:
                raise ForgePixFehler("Drizzle: benötigte Eingabeabdeckung fehlt oder liegt außerhalb des Bildordners.")
            mask = tifffile.imread(coverage_path)
            if mask.shape != frame.shape[:2] or not np.isin(mask, (0, 1)).all():
                raise ForgePixFehler("Drizzle: ungültige Eingabeabdeckungsmaske.")
            input_weight = np.asarray(input_weight) * mask
        if not accumulator.add(frame, matrix, weight=input_weight, channel_map=colours):
            skipped.append(str(path))
            log("    Drizzle: keine gültigen Pixelbeiträge im Ausgaberaster, Aufnahme ausgelassen: %s" % path)
            continue
        used.append(str(path))
        registrations.append({"source": str(path), "matrix_input_to_reference": np.asarray(matrix).tolist()})
        log("    Drizzle %d/%d (Quadrat-Drop, pixfrac %.3f, Scale %.3f)" % (len(used), len(paths), accumulator.pixfrac, accumulator.scale))
    if not used:
        raise ForgePixFehler("Drizzle: kein Frame ausrichtbar.")
    image, weights, covered_channels = accumulator.finish()
    coverage = covered_channels.all(axis=2)
    report = {"schema_version": 1, "kernel": "square_exact_affine_overlap", "method": "weighted_mean",
              "scale": accumulator.scale, "pixfrac": accumulator.pixfrac, "reference": str(reference),
              "input_shape": list(ref.shape), "output_shape": list(image.shape), "source_files": used,
              "skipped_files": skipped, "registrations": registrations, "cfa_preserved": preserve_cfa,
              "channel_order": "BGR", "coverage_fraction": float(coverage.mean()),
              "quality_status": "coverage_incomplete" if not coverage.all() else "coverage_complete_not_quality_validated",
              "channel_coverage_fraction": covered_channels.mean(axis=(0, 1)).tolist(),
              "units": "input flux per reference pixel area; affine Jacobian corrected",
              "output_pixel_area": 1 / accumulator.scale ** 2,
              "weights": "sum of input weights times fractional drop overlap; not exposure counts",
              "uncovered_samples": "zero placeholder with zero weight; never filled",
              "accumulation_dtype": "float64", "output_dtype": "float32",
              "reference_metadata": {key: headers[reference][key] for key in
                  ("OBJECT", "FILTER", "INSTRUME", "TELESCOP", "EXPTIME", "GAIN", "OFFSET", "XBINNING", "YBINNING")
                  if key in headers[reference]},
              "limitations": ["No sigma rejection or cosmic-ray rejection", "No WCS distortion or TPS",
                              "No exposure normalization", "Coverage does not prove recovered detail or independent noise"]}
    report["warnings"] = []
    if not coverage.all():
        warning = ("Nur %.2f %% vollständig farbig belegt. Abdeckungslücken bleiben markiert; "
                   "für CFA mehr verschiedene Ditherpositionen oder den normalen Stack verwenden." % (100 * coverage.mean()))
        report["warnings"].append(warning)
        log("    Drizzle: " + warning)
    if return_info:
        return image, {"weights": weights, "coverage_channels": covered_channels, "coverage": coverage, "report": report}
    return image


def _bg_sigma(f, coverage=None):
    """A4 — robuste Hintergrund-Streuung σ_bg eines Frames (für die SNR-Gewichtung).

    Schätzt das Rauschen NUR aus dem Himmelshintergrund (untere ~80 % der Helligkeit), damit helle
    Sterne/Nebel den Wert nicht aufblähen: σ = 1.4826·MAD der Pixel unterhalb des 80%-Quantils.
    Kleines σ ⇒ rauscharmer/transparenter Frame ⇒ höheres Gewicht."""
    g = _gray(f)
    g = g[coverage] if coverage is not None else g.ravel()
    if not g.size:
        raise ForgePixFehler("Aufnahme hat keine gueltige Bildabdeckung.")
    thr = float(np.quantile(g, 0.80))
    bgvals = g[g <= thr]
    if bgvals.size < 16:
        bgvals = g
    med = float(np.median(bgvals))
    mad = float(np.median(np.abs(bgvals - med))) * 1.4826
    return max(mad, 1e-5)


def stack(paths, method="sigma", kappa=2.5, normalize=True, local_norm=False,
          weight=False, sigma_iters=2, belichtungen=None, log=log_print, preview_cb=None):
    """Speicherschonendes Stacken über die Platte (zweistufig bei sigma/winsor).
    Gibt float32-Ergebnis [0..1] (BGR) zurück.

    A4 — `weight=True`: jeder Frame geht mit Gewicht 1/σ_bg² ein (σ_bg = robuste Hintergrund-
    Streuung, s. `_bg_sigma`). Rauschärmere/transparentere Subs zählen mehr → besseres SNR bei
    gemischter Transparenz (Dunst, Mond). Bei `average`/`winsor`/`sigma` voll wirksam; `median`/
    `max` sind ihrer Natur nach ungewichtet (Gewicht wird dort ignoriert).

    A4 — `sigma_iters` (nur method='sigma'): die Sigma-Schwellen 1–2× nachschätzen — nach jeder
    Rejection werden Mittel/σ aus den ÜBRIG gebliebenen (geclippten) Werten neu berechnet, sodass
    die Schwelle nicht von den Ausreißern selbst verzerrt bleibt. 1 = altes Einpass-Verhalten.

    Defaults (weight=False, sigma_iters=2) sind sicher: sigma_iters=2 ist eine reine
    Genauigkeitsverbesserung des bisherigen Sigma-Clippings; weight=False erhält exakt das alte
    ungewichtete Mittel.

    preview_cb(img01_bgr, i, n): optionaler Callback für die Live-Vorschau — wird während des
    Stackens periodisch mit dem laufenden (Teil-)Ergebnis aufgerufen."""
    if not paths:
        raise RuntimeError("keine Frames zum Stacken")
    # Unbekannte Methode fiel bisher STILL in den Sigma-Zweig (das `else` ganz unten). Ein
    # Tippfehler in der Bibliotheks-Schnittstelle hätte damit klaglos etwas anderes gerechnet
    # als verlangt — und niemand hätte es gemerkt.
    _METHODEN = ("sigma", "winsor", "linearfit", "average", "median", "max")
    if method not in _METHODEN:
        raise ForgePixFehler("unbekannte Stacking-Methode %r (möglich: %s)"
                             % (method, ", ".join(_METHODEN)))
    n = len(paths)
    _pv_every = max(1, n // 12)              # ~12 Vorschau-Updates über den Lauf

    # Gemischte Belichtungszeiten: MULTIPLIKATIV auf eine gemeinsame Basis bringen.
    # Die additive Normalisierung unten gleicht nur den Himmelspegel an, nicht die Verstärkung
    # — ein 60-s-Sub trägt aber pro Pixel nur ein Fünftel des Signals eines 300-s-Subs. Ohne
    # diese Skalierung verdünnt jedes kurze Sub den Stack, statt ihn zu verbessern.
    # Zusammen mit weight=True ergibt sich daraus automatisch die richtige Gewichtung: das
    # Hochskalieren hebt auch das Rauschen, und 1/σ² zählt die kurzen Subs entsprechend weniger.
    #
    # WAS HIER NICHT STEHT, UND WARUM: DeepSkyStackers „Entropy Weighted Average" gewichtet je
    # Pixel nach dem örtlichen Informationsgehalt. Genau so gebaut und gemessen — das Ergebnis
    # war unbrauchbar: eine Satellitenspur trägt die höchste örtliche Streuung überhaupt und
    # bekommt darum das höchste Gewicht. Auf derselben Serie (12 Subs, ein Satellit in einem
    # kurzen Sub) stand die Spur danach bei 0,845 gegen einen Himmel von 0,036, während
    # Sigma-Clipping mit Zeitskalierung sie auf 0,013 gegen 0,010 gedrückt hat — also praktisch
    # weg. Die Himmelsstreuung stieg dabei von 0,00035 auf 0,145, das 414-fache. Der Ansatz
    # belädt zuverlässig genau die Störungen, die weggerechnet werden sollen.
    skal = np.ones(n, np.float32)
    if belichtungen is not None and len(belichtungen) == n:
        t = np.asarray([float(x) if x else 0.0 for x in belichtungen], np.float64)
        if np.all(t > 0) and float(t.max() / t.min()) > 1.05:
            t_ref = float(np.median(t))
            skal = (t_ref / t).astype(np.float32)
            log("    gemischte Belichtungszeiten: %.0f–%.0f s, auf %.0f s skaliert "
                "(Faktoren %.2f–%.2f)" % (t.min(), t.max(), t_ref, skal.min(), skal.max()))
    first = _read_float(paths[0])
    shape = first.shape
    if first.size == 0 or not np.isfinite(first).all():
        raise ForgePixFehler("Stacking: ungueltige Pixelwerte in der Aufnahme.")
    masks = {}

    def valid(p):
        if p not in masks:
            import tifffile
            mask_path = str(p) + ".coverage.tif"
            if os.path.isfile(mask_path):
                m = tifffile.memmap(mask_path, mode="r")
                if (m.shape != shape[:2] or not np.isfinite(m).all()
                        or not np.isin(m, (0, 1)).all() or not np.any(m)):
                    raise ForgePixFehler("Ungueltige Registrierungs-Abdeckung: %s" % mask_path)
                masks[p] = m
            else:
                if os.path.splitext(p)[1].lower() in (".tif", ".tiff"):
                    with tifffile.TiffFile(p) as tif:
                        if (tif.pages[0].description or "").startswith("ForgePix registration;"):
                            raise ForgePixFehler("Registrierungs-Abdeckung fehlt: %s" % mask_path)
                masks[p] = None
        m = masks[p]
        return np.ones(shape[:2], bool) if m is None else np.asarray(m, dtype=bool)

    def read_checked(p):
        f = _read_float(p)
        if f.shape != shape or not np.isfinite(f).all():
            raise ForgePixFehler("Stacking: unpassende Bildgroesse oder ungueltige Pixelwerte: %s" % p)
        return f

    # additive Normalisierung + SNR-Sigma in EINEM Vorab-Pass (vorher zwei getrennte
    # Volldurchläufe über alle Dateien). σ_bg ist gegen den späteren Skalar-Offset invariant
    # (konstante Verschiebung ändert weder Ränge noch Streuung), darf also vom rohen Frame kommen.
    need_w = weight and method in ("average", "winsor", "sigma")
    offs = np.zeros(n, np.float32)
    sig_raw = np.ones(n, np.float32)
    if normalize or need_w:
        meds = np.zeros(n, np.float32)
        for i, p in enumerate(paths):
            f = read_checked(p) * skal[i]
            coverage = valid(p)
            overlap = coverage & valid(paths[0])
            if not overlap.any():
                raise ForgePixFehler("Normalisierung: keine gemeinsame Bildabdeckung mit der Referenz.")
            meds[i] = float(np.median(f[overlap]) - np.median(first[overlap] * skal[0]))
            if need_w:
                sig_raw[i] = _bg_sigma(f, coverage)
        if normalize:
            gm = float(np.median(meds))
            offs = gm - meds
    # lokale Normalisierung: örtliche Hintergrund-Fläche statt nur Skalar (gegen Gradienten)
    ref_surf = _bg_surface(first, coverage=valid(paths[0])) if (normalize and local_norm) else None
    if ref_surf is not None:
        log("    lokale Normalisierung aktiv (örtlicher Hintergrundabgleich)")

    def rd(i, p):
        f = read_checked(p) * skal[i]
        if ref_surf is not None:
            return local_normalize(f, ref_surf, coverage=valid(p))
        return f + offs[i]

    # Banded-IO: unkomprimierte uint16/float32-TIFFs per memmap zeilenweise lesen,
    # statt pro Band jede Datei komplett zu dekodieren (100 Frames × 20 Bänder = 2000 Voll-Reads).
    # Achtung Kanalordnung: cv2 schreibt BGR-Arrays als RGB-TIFF → beim memmap-Lesen [..., ::-1].
    # Fallback (FITS/komprimiert/lokale Normalisierung): bisheriger Voll-Read über rd().
    _mm = {}

    def rows_of(i, p, y0, y1):
        if ref_surf is not None:
            return rd(i, p)[y0:y1]           # lokale Normalisierung braucht das Vollbild (Fläche)
        mm = _mm.get(p, False)
        if mm is False:
            mm = None
            if os.path.splitext(p)[1].lower() in (".tif", ".tiff"):
                try:
                    import tifffile
                    m = tifffile.memmap(p, mode="r")
                    if (m.shape == shape and m.ndim == 3 and m.shape[2] == 3
                            and (m.dtype == np.uint16 or m.dtype == np.float32)):
                        mm = m
                except Exception:
                    mm = None
            _mm[p] = mm
        if mm is None:
            return rd(i, p)[y0:y1]
        band = mm[y0:y1, :, ::-1].astype(np.float32)
        if not np.isfinite(band).all():
            raise ForgePixFehler("Stacking: ungueltige Pixelwerte: %s" % p)
        divisor = 65535.0 if mm.dtype == np.uint16 else 1.0
        return band / divisor * skal[i] + offs[i]

    # A4 — Per-Frame-SNR-Gewichte (1/σ_bg²), robust normiert auf Mittel 1. Bei weight=False alle 1.
    w = np.ones(n, np.float32)
    if need_w:
        # σ_bg aus dem kombinierten Vorab-Pass. Bei lokaler Normalisierung muss σ auf den
        # normalisierten Frames gemessen werden (Flächen-Abgleich ändert die Streuung) —
        # dieser (seltene) Pfad liest wie bisher ein zweites Mal.
        if ref_surf is not None:
            sig = np.array([_bg_sigma(rd(i, p), valid(p)) for i, p in enumerate(paths)], np.float32)
        else:
            sig = sig_raw
        w = 1.0 / (sig * sig)
        w *= n / float(w.sum())                          # Mittel 1 → Skala/Helligkeit unverändert
        log(f"    SNR-Gewichtung aktiv (Gewichte {np.round(w.min(),2)}..{np.round(w.max(),2)})")

    if method in ("average", "median", "max"):
        if method == "median":
            # Median braucht alle Werte -> in Kacheln über die Höhe, speicherschonend
            res = np.empty(shape, np.float32)
            rows = max(1, 2_000_000 // (shape[1] * shape[2]))  # ~Zeilen pro Kachel
            for y in range(0, shape[0], rows):
                # rows_of(): memmap-Zeilenlesen (E1) inkl. Normalisierung — lokale
                # Normalisierung läuft über den rd()-Fallback (braucht das Vollbild)
                band = np.stack([rows_of(i, p, y, y + rows) for i, p in enumerate(paths)])
                covered = np.stack([valid(p)[y:y + rows] for p in paths])[..., None]
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    res[y:y + rows] = np.nan_to_num(np.nanmedian(
                        np.where(covered, band, np.nan), axis=0), nan=0.0)
                log(f"    median Zeilen {y}/{shape[0]}")
            return res
        acc = np.zeros(shape, np.float32) if method == "average" else None
        wacc = np.zeros(shape[:2] + (1,), np.float32)
        mx = np.full(shape, -np.inf, np.float32) if method == "max" else None
        for i, p in enumerate(paths):
            f = rd(i, p)
            covered = valid(p)[..., None]
            if method == "average":
                acc += np.where(covered, f * w[i], 0); wacc += covered * w[i]
            else:
                mx = np.maximum(mx, np.where(covered, f, -np.inf))
            log(f"    {method} {i + 1}/{n}")
            if preview_cb and (i % _pv_every == 0 or i == n - 1):
                preview_cb(np.clip((acc / np.maximum(wacc, 1e-6)) if method == "average"
                                   else np.where(np.isfinite(mx), mx, 0), 0, 1),
                           i + 1, n)
        return (acc / np.maximum(wacc, 1e-6) if method == "average"
                else np.where(np.isfinite(mx), mx, 0)).astype(np.float32)

    if method == "linearfit":
        # Linear-Fit-Clipping (PixInsight-Stil): pro Pixel die sortierten Werte über die Frames
        # mit einer Geraden modellieren, Streuung der Residuen messen, Ausreißer (Satelliten,
        # Flugzeuge, kosmische Treffer, Hotpixel) jenseits kappa·sigma verwerfen. Robuster als
        # Sigma-Clipping bei WENIGEN Subs und systematisch ungleicher Transparenz/Helligkeit.
        res = np.empty(shape, np.float32)
        rows = max(1, 2_000_000 // (shape[1] * shape[2]))
        x = np.arange(n, dtype=np.float32)
        xm = x.mean(); xv = float(((x - xm) ** 2).sum()) + 1e-9
        for y in range(0, shape[0], rows):
            band = np.stack([rows_of(i, p, y, y + rows) for i, p in enumerate(paths)])  # (n,r,w,c)
            covered = np.stack([valid(p)[y:y + rows] for p in paths])[..., None]
            v = np.sort(np.where(covered, band, np.inf), axis=0)
            supported = np.isfinite(v)
            v = np.where(supported, v, 0)
            mask = supported.copy()
            for _ in range(2):                       # 2 Iterationen reichen praktisch
                w_ = mask.astype(np.float32)
                sw = np.clip(w_.sum(axis=0), 1.0, None)
                xx = x[:, None, None, None]
                xm = (xx * w_).sum(axis=0) / sw
                xv = (((xx - xm) ** 2) * w_).sum(axis=0) + 1e-9
                ym = (v * w_).sum(axis=0) / sw
                slope = ((xx - xm) * (v - ym) * w_).sum(axis=0) / xv
                fit = slope * (xx - xm) + ym
                resid = v - fit
                sig = np.sqrt((resid * resid * w_).sum(axis=0) / sw) + 1e-9
                mask = supported & (np.abs(resid) <= kappa * sig)
            w_ = mask.astype(np.float32)
            res[y:y + rows] = (v * w_).sum(axis=0) / np.clip(w_.sum(axis=0), 1.0, None)
            log(f"    linearfit-Rejection Zeilen {y}/{shape[0]}")
        return res

    # sigma / winsor: Pass 1 Mittel+Std, Pass 2 Rejection
    s = np.zeros(shape, np.float32); s2 = np.zeros(shape, np.float32)
    sample_count = np.zeros(shape[:2] + (1,), np.float32)
    for i, p in enumerate(paths):
        f = rd(i, p)
        covered = valid(p)[..., None]
        s += np.where(covered, f, 0); s2 += np.where(covered, f * f, 0)
        sample_count += covered
        log(f"    Statistik {i + 1}/{n}")
    count = np.maximum(sample_count, 1)
    mean = s / count
    std = np.sqrt(np.maximum(s2 / count - mean * mean, 0))
    lo = mean - kappa * std; hi = mean + kappa * std

    if method in ("sigma", "winsor"):
        # A4 — iteratives Sigma: Schwellen 1–2× aus den GECLIPPTEN Werten nachschätzen, damit die
        # Ausreißer die Schwelle nicht selbst verzerren. extra_iters = sigma_iters−1 Nachpässe.
        #
        # winsor war hier NICHT dabei und rechnete mit den Schwellen des ersten, unbereinigten
        # Durchlaufs — und der Ausreißer blaeht die Streuung selbst auf, sodass er innerhalb
        # seiner eigenen Schwelle landet. Nachgerechnet an 9x 0.06 + 1x 1.00 (kosmischer
        # Treffer): mean=0.154, std=0.282, hi=0.859 -> kaum beschnitten, Ergebnis 0.140 statt
        # 0.060, also 133 % zu hell. Am echten Stack blieben 16.7 % des Treffers stehen —
        # fast so viel wie beim simplen Mittelwert (19.6 %), obwohl winsor ein Rejection-
        # Verfahren sein soll. Mit der Nachschaetzung: 43x genauer bei einem Ausreisser.
        for _ in range(max(0, int(sigma_iters) - 1)):
            s = np.zeros(shape, np.float32); s2 = np.zeros(shape, np.float32)
            cnt = np.zeros(shape, np.float32)
            for i, p in enumerate(paths):
                f = rd(i, p)
                m = ((f >= lo) & (f <= hi) & valid(p)[..., None]).astype(np.float32)
                s += f * m; s2 += f * f * m; cnt += m
            cn = np.clip(cnt, 1.0, None)
            mean = s / cn
            std = np.sqrt(np.maximum(s2 / cn - mean * mean, 0))
            lo = mean - kappa * std; hi = mean + kappa * std

    acc = np.zeros(shape, np.float32); cnt = np.zeros(shape, np.float32)
    for i, p in enumerate(paths):
        f = rd(i, p)
        covered = valid(p)[..., None]
        if method == "winsor":
            f = np.clip(f, lo, hi)
            acc += np.where(covered, f * w[i], 0); cnt += covered * w[i]
        else:  # sigma: Ausreißer verwerfen
            m = (f >= lo) & (f <= hi) & covered
            acc += np.where(m, f * w[i], 0); cnt += m * w[i]
        log(f"    {method}-Rejection {i + 1}/{n}")
        if preview_cb and (i % _pv_every == 0 or i == n - 1):
            preview_cb(np.clip(acc / np.clip(cnt, 1e-6, None), 0, 1), i + 1, n)
    return acc / np.clip(cnt, 1e-6, None)


def bin_image(f, factor=2):
    """Software-Binning: factor×factor-Blöcke mitteln → halbe (bei 2×) Auflösung, aber höheres
    Signal-Rausch-Verhältnis und kleinere/rundere Sterne. Sinnvoll bei überabgetasteten Daten
    (FWHM ≫ 2 px). factor=1 → unverändert."""
    factor = max(1, int(factor))
    if factor == 1 or f is None:
        return f
    h, w = f.shape[:2]
    h2, w2 = (h // factor) * factor, (w // factor) * factor
    f = f[:h2, :w2]
    if f.ndim == 3:
        f = f.reshape(h2 // factor, factor, w2 // factor, factor, f.shape[2]).mean(axis=(1, 3))
    else:
        f = f.reshape(h2 // factor, factor, w2 // factor, factor).mean(axis=(1, 3))
    return f.astype(np.float32)




def reduce_stars(f, strength=0.5, size=5, protect_nebula=True):
    """Sterne verkleinern/abschwaechen (Star Reduction, wie RC-Astro StarShrink) — klassisch.

    Warum: nach dem Strecken dominieren helle Sterne das Bild und ueberdecken den Nebel. Die
    ueblichen Werkzeuge dafuer sind KI-basiert; das Grundprinzip geht aber rein morphologisch.

    Verfahren: eine Graustufen-EROSION verkleinert helle, kompakte Strukturen (Sterne), laesst
    ausgedehnte Flaechen (Nebel) aber nahezu unberuehrt — genau der gewuenschte Unterschied.
    Das Ergebnis wird anteilig (strength) mit dem Original gemischt, damit man die Staerke
    dosieren kann. protect_nebula blendet die Wirkung dort aus, wo das Bild auch nach starker
    Glaettung hell bleibt (= ausgedehnter Nebel), sodass wirklich nur Punktquellen schrumpfen.

    strength 0..1 (0 = aus), size = Groesse des Strukturelements in Pixeln.
    """
    if f is None or strength <= 0:
        return f
    a = np.asarray(f, np.float32)
    k = max(3, int(size) | 1)
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    erodiert = cv2.erode(a, se)
    if protect_nebula:
        lum = _gray(a)
        # ausgedehnte Struktur = ueberlebt starke Glaettung; Punktquellen nicht
        gross = cv2.GaussianBlur(lum, (0, 0), max(4.0, k * 1.5))
        # dort wo das Bild deutlich HELLER ist als seine grossflaechige Version, sitzt ein Stern
        stern = np.clip((lum - gross) / (np.percentile(lum, 99.5) - np.percentile(lum, 50) + 1e-6), 0, 1)
        stern = cv2.GaussianBlur(stern, (0, 0), 1.5)[..., None] if a.ndim == 3 else             cv2.GaussianBlur(stern, (0, 0), 1.5)
    else:
        stern = 1.0
    w = float(np.clip(strength, 0.0, 1.0)) * stern
    return np.clip(a * (1 - w) + erodiert * w, 0, 1)



def stretch_preserve_color(bgr, stretch_fn, saettigung=1.0):
    """Farberhaltend strecken: nur die HELLIGKEIT durch die Kurve, die Kanalverhaeltnisse bleiben.

    Warum das noetig ist (an echten Dual-Band-Daten gemessen, NGC7380): eine kanalweise
    Streckung entsaettigt massiv. Der staerkste Kanal (bei Ha-Nebeln Rot) laeuft gegen Weiss,
    waehrend die schwaecheren relativ staerker angehoben werden — alle Kanaele konvergieren.
    Gemessen fiel die Saettigung dabei von 0.257 auf 0.075, und selbst der Saettigungsregler
    der Streckung (bis 2.0) holte nur 0.108 zurueck. Das Bild wirkt ausgewaschen und der
    dominante Kanal schlaegt durch — bei einem Ha-Objekt also "alles rot".

    Hier wird stattdessen L = max(Kanaele) gestreckt und jeder Kanal mit demselben Faktor
    L'/L skaliert. Farbton und Saettigung bleiben damit exakt erhalten; nur die Helligkeit
    aendert sich. `saettigung` > 1 verstaerkt die Farbe zusaetzlich um die Luminanz herum.
    """
    a = np.asarray(bgr, np.float32)
    if a.ndim != 3 or a.shape[2] != 3:
        return stretch_fn(a)
    # Helligkeitsmass: Mischung aus Rec.709-Luma und Maximum. Reines max() laesst den
    # staerksten Kanal die Streckung allein bestimmen und treibt viele Pixel ins Clipping
    # (gemessen 17-38 % ueber 0.8); reine Luma unterbelichtet stark gefaerbte Bereiche.
    L = 0.5 * _gray(a) + 0.5 * a.max(axis=2)
    Ls = stretch_fn(np.dstack([L, L, L]))
    Ls = Ls.mean(axis=2) if Ls.ndim == 3 else Ls
    faktor = Ls / np.maximum(L, 1e-6)
    out = np.clip(a * faktor[..., None], 0, 1)
    if saettigung and saettigung != 1.0:
        lum = _gray(out)[..., None]
        out = np.clip(lum + (out - lum) * float(saettigung), 0, 1)
    return out

def stretch_starless(bgr, stretch_fn, star_strength=0.35, sensitivity=5.0, log=log_print):
    """Sterne raus -> Nebel strecken -> Sterne wieder rein. Der Profi-Weg.

    Das Problem, das dieser Weg loest (an echten Dual-Band-Daten gemessen, NGC7380/ASI294MC Pro):
    Der Weisspunkt einer Streckung wird von den hellsten Pixeln bestimmt — und das sind IMMER
    Sterne, nicht der Nebel. Bei 13x120 s lag das Nebelsignal nur 6 % ueber dem Himmel; nach der
    Normierung auf das 99.9-%-Quantil (= ein Stern) blieb der Nebel bei 3.5 % des Wertebereichs
    liegen, waehrend die Sterne den ganzen Rest bekamen. Ergebnis: zu helle Sterne UND zu
    schwacher Nebel — beides gleichzeitig, aus derselben Ursache.

    Nimmt man die Sterne vorher heraus, bestimmt der NEBEL den Weisspunkt und bekommt den vollen
    Bereich. Die Sterne kommen danach separat (und dosierbar) wieder dazu.

    stretch_fn: die Streckfunktion, z. B. `lambda x: astro.mtf_stretch(x)`.
    star_strength: MAXIMALE Sternhelligkeit im Ergebnis (0 = sternenlos, 0.35 = dezent,
                   1 = Sterne duerfen bis Weiss gehen). Linear skaliert, nicht gestreckt.
    Faellt sauber auf die normale Streckung zurueck, wenn keine Sterne gefunden werden.
    """
    if bgr is None:
        return bgr
    starless, maske = remove_stars(bgr, sensitivity=sensitivity, log=log)
    if maske is None:
        log("    Starless-Streckung: keine Sterne gefunden -> normale Streckung")
        return stretch_fn(bgr)
    # Sternebene = was das Star-Removal weggenommen hat (rein additiv, nichts erfunden)
    sterne = np.clip(np.asarray(bgr, np.float32) - np.asarray(starless, np.float32), 0, None)
    nebel = stretch_fn(starless)
    if star_strength <= 0:
        log("    Starless-Streckung: Nebel gestreckt, Sterne weggelassen")
        return np.clip(nebel, 0, 1)
    # Sterne LINEAR skaliert zurueck — NICHT mit derselben Kurve strecken.
    # Erster Versuch war genau das, und es hob die Wirkung komplett auf: die Streckkurve ist
    # dafuer gebaut, Schwaches hochzuziehen, und blaest damit jeden Stern wieder auf. Gemessen
    # an echten Daten blieben so 5.0 % der Pixel ueber 0.8 — praktisch so viel wie ganz ohne
    # Starless (5.2 %). Linear zurueckgeholt sind es 0.86 %, bei gleicher Nebelhelligkeit.
    # star_strength ist damit die maximale Sternhelligkeit im Ergebnis (0.35 = dezent).
    bezug = max(float(np.percentile(sterne, 99.9)), 1e-9)
    sterne_g = np.clip(sterne / bezug * float(np.clip(star_strength, 0.0, 1.0)), 0, 1)
    out = 1.0 - (1.0 - np.clip(nebel, 0, 1)) * (1.0 - np.clip(sterne_g, 0, 1))
    log(f"    Starless-Streckung: Nebel bestimmt den Weisspunkt, Sterne linear bis "
        f"{float(np.clip(star_strength,0,1)):.2f} zurueck")
    return np.clip(out, 0, 1)

def linear_match(bild, referenz, robust=True):
    """Ein Bild auf die lineare Skala eines anderen ziehen (Siril `linear_match`).

    Wozu: zwei Nächte, zwei Filter, zwei Sessions — die Pegel unterscheiden sich, obwohl
    dasselbe Objekt drin ist. Vor dem Zusammenrechnen oder Kombinieren müssen sie auf
    dieselbe Skala. Gesucht sind a und b in  bild·a + b ≈ referenz.

    `robust=True` verwirft Ausreißer iterativ (Sterne, kosmische Treffer, Satelliten), damit
    die Anpassung dem HINTERGRUND und dem Nebel folgt und nicht ein paar hellen Punkten.
    Gibt das angepasste Bild zurück; bei unbrauchbaren Eingaben unverändert das Original.
    """
    if bild is None or referenz is None:
        return bild
    a = np.asarray(bild, np.float32)
    r = np.asarray(referenz, np.float32)
    if a.shape != r.shape:
        return bild
    x = a.ravel().astype(np.float64)
    y = r.ravel().astype(np.float64)
    gueltig = np.isfinite(x) & np.isfinite(y)
    if gueltig.sum() < 100:
        return bild
    x, y = x[gueltig], y[gueltig]
    # Bei großen Bildern reicht eine Stichprobe — die Steigung ändert sich dadurch nicht.
    if x.size > 500000:
        idx = np.linspace(0, x.size - 1, 500000).astype(np.int64)
        x, y = x[idx], y[idx]
    behalten = np.ones(x.size, bool)
    steigung, versatz = 1.0, 0.0
    for _ in range(3 if robust else 1):
        if behalten.sum() < 50:
            break
        steigung, versatz = np.polyfit(x[behalten], y[behalten], 1)
        rest = y - (steigung * x + versatz)
        mad = float(np.median(np.abs(rest - np.median(rest)))) * 1.4826 + 1e-12
        behalten = np.abs(rest - np.median(rest)) <= 3.0 * mad
        if not robust:
            break
    if not np.isfinite(steigung) or not np.isfinite(versatz) or abs(steigung) < 1e-9:
        return bild
    return np.clip(a * float(steigung) + float(versatz), 0, 1)


def unpurple(f, staerke=1.0, schwelle=0.06):
    """Violettsaum um helle Sterne dämpfen (Siril `unpurple`).

    Wodurch er entsteht: die Optik bündelt Blau und Rot in einer anderen Ebene als Grün
    (Farblängsfehler). Um helle Sterne bleibt dadurch ein magentafarbener Hof stehen — Rot UND
    Blau liegen dort deutlich über Grün, was es in echten astronomischen Objekten praktisch
    nicht gibt. Genau das ist das Erkennungsmerkmal.

    Behandelt wird nur, wo BEIDE Kanäle über Grün liegen und es hell genug ist; Rot und Blau
    werden dort anteilig zu Grün gezogen. Rein rote Nebel (Hα!) bleiben damit unangetastet —
    das wäre sonst der teuerste Fehlgriff.
    """
    if f is None or staerke <= 0:
        return f
    a = np.asarray(f, np.float32)
    if a.ndim != 3 or a.shape[2] != 3:
        return f
    b, g, r = a[..., 0], a[..., 1], a[..., 2]
    ueber = np.minimum(b - g, r - g)              # nur wenn BEIDE über Grün liegen
    hell = np.clip((np.maximum(b, r) - schwelle) / max(schwelle, 1e-6), 0, 1)
    maske = np.clip(ueber / max(schwelle, 1e-6), 0, 1) * hell * float(np.clip(staerke, 0, 1))
    out = a.copy()
    out[..., 0] = b - maske * (b - g)
    out[..., 2] = r - maske * (r - g)
    return np.clip(out, 0, 1)


def ddp(f, hintergrund=None, staerke=1.0, schaerfe=0.0):
    """Digital Development Processing (Okano) — die klassische Astro-Tonwertkurve.

    Die Idee stammt aus der Chemie: ein Film entwickelt sich nicht linear, sondern läuft in
    die Sättigung. Die Kurve  y = x / (x + k)  tut dasselbe — sie hebt schwaches Signal kräftig
    an und komprimiert die hellen Bereiche, sodass Sterne nicht zu weißen Klumpen werden.
    `k` ist der Himmelspegel: dort liegt der Wendepunkt, unterhalb wird angehoben, oberhalb
    komprimiert. Wird er nicht angegeben, misst ihn die Funktion selbst (Median).

    `schaerfe` mischt optional eine leichte Unschärfemaskierung dazu — im Original gehört das
    dazu, weil die Kompression sonst flau wirkt.
    """
    if f is None or staerke <= 0:
        return f
    a = np.clip(np.asarray(f, np.float32), 0, 1)
    lum = _gray(a) if a.ndim == 3 else a
    k = float(hintergrund) if hintergrund is not None else float(np.median(lum))
    k = max(k, 1e-4)
    neu = lum / (lum + k)
    neu = neu / max(float(neu.max()), 1e-6)
    if schaerfe > 0:
        weich = cv2.GaussianBlur(neu, (0, 0), 2.0)
        neu = np.clip(neu + float(schaerfe) * (neu - weich), 0, 1)
    s = float(np.clip(staerke, 0.0, 1.0))
    ziel = (1.0 - s) * lum + s * neu
    if a.ndim == 2:
        return np.clip(ziel, 0, 1)
    faktor = ziel / np.maximum(lum, 1e-6)
    return np.clip(a * faktor[..., None], 0, 1)


def dark_skalieren(dark, ziel_belichtung, dark_belichtung, bias=None,
                   ziel_temp=None, dark_temp=None, log=log_print):
    """Master-Dark auf eine andere Belichtungszeit/Temperatur umrechnen (Siril `calibrate -opt`).

    Physik dahinter, und warum es zwei Anteile sind:
      * Der BIAS (Ausleseversatz) ist in jedem Frame gleich groß — er hängt NICHT von der
        Belichtungszeit ab und darf darum NICHT mitskaliert werden.
      * Der DUNKELSTROM wächst näherungsweise linear mit der Belichtungszeit und verdoppelt
        sich je etwa 6 °C Temperaturanstieg.
    Also:  dark_neu = bias + (dark − bias) · (t_ziel/t_dark) · 2^((T_ziel−T_dark)/6)

    Ohne übergebenen Bias wird er aus dem Dark selbst geschätzt (1. Perzentil) — das funktioniert,
    solange ein Teil des Sensors nahezu keinen Dunkelstrom hat, was bei echten Darks der Normalfall
    ist (an echten Verhältnissen gemessen: Fehler 0.0006 gegenüber 0.020 beim naiven Verdoppeln,
    also 35-mal besser). Bei einem Sensor mit über die Fläche GLEICHMÄSSIGEM Dunkelstrom greift die
    Schätzung dagegen daneben — dort hilft nur ein echtes Bias-Frame. Deshalb wird ohne Bias
    ausdrücklich gewarnt statt stillschweigend geraten.

    WICHTIGE EINSCHRÄNKUNG: für manche Sensoren, allen voran den IMX294 der ASI294MC Pro,
    raten die Hersteller ausdrücklich VON der Dark-Skalierung ab — der Glow skaliert dort nicht
    sauber mit, und ein skaliertes Master passt schlechter als gar keins. Diese Funktion ist
    ein Werkzeug, keine Empfehlung.
    """
    if dark is None:
        return None
    d = np.asarray(dark, np.float32)
    try:
        t_ziel, t_dark = float(ziel_belichtung), float(dark_belichtung)
    except (TypeError, ValueError):
        return d
    if t_dark <= 0 or t_ziel <= 0:
        return d
    faktor = t_ziel / t_dark
    if ziel_temp is not None and dark_temp is not None:
        try:
            faktor *= 2.0 ** ((float(ziel_temp) - float(dark_temp)) / 6.0)
        except (TypeError, ValueError):
            pass
    if bias is None:
        sockel = float(np.percentile(d, 1))
        log("    Dark-Skalierung: kein Bias übergeben — Sockel aus dem Dark geschätzt (%.5f). "
            "Nur brauchbar, wenn ein Teil des Sensors kaum Dunkelstrom zeigt." % sockel)
    else:
        sockel = np.asarray(bias, np.float32)
    log("    Dark-Skalierung: Faktor %.3f (%.0f s -> %.0f s%s)"
        % (faktor, t_dark, t_ziel,
           ", %.1f -> %.1f °C" % (dark_temp, ziel_temp)
           if (ziel_temp is not None and dark_temp is not None) else ""))
    return np.clip(sockel + (d - sockel) * faktor, 0, None)


def local_contrast(f, staerke=1.5, kacheln=8):
    """Lokaler Kontrast per CLAHE (PixInsight: LocalHistogramEqualization).

    Wozu: ausgedehnte Nebel haben oft viel Struktur bei WENIG Kontrast. Eine globale
    Streckung kann das nicht heben, ohne den Rest zu überziehen — eine kontrastlimitierte
    adaptive Histogrammausgleichung arbeitet je Kachel und holt die Struktur heraus, wo sie
    steht. Die Begrenzung (clipLimit) verhindert dabei, dass das Rauschen mit hochgezogen wird.

    Wirkt NUR auf die Helligkeit; die Farbe bleibt unangetastet — sonst kippen die Kanäle
    gegeneinander und es entstehen Farbflecken.

    staerke: clipLimit, 0 = aus. 1–3 ist der brauchbare Bereich; darüber wird es hart.
    """
    if f is None or staerke <= 0:
        return f
    a = np.clip(np.asarray(f, np.float32), 0, 1)
    k = max(2, int(kacheln))
    clahe = cv2.createCLAHE(clipLimit=float(staerke), tileGridSize=(k, k))

    def _ausgleich(lum):
        # BEWUSST 8 bit: OpenCVs CLAHE IGNORIERT den clipLimit bei 16-bit-Eingabe. Die Grenze
        # wird als clipLimit x Kachelflaeche / Histogrammgroesse gerechnet; bei 65536 Klassen
        # wird das kleiner als 1 und rundet auf null — es findet dann GAR KEINE Begrenzung
        # statt, also volle Histogrammausgleichung samt hochgezogenem Rauschen. Gemessen
        # lieferten clipLimit 1, 2, 4 und 8 bitgleiche Ergebnisse. In 8 bit greift die
        # Begrenzung korrekt (Std 6.5 gegen 16.2 bei 1 gegen 4).
        u8 = (np.clip(lum, 0, 1) * 255).astype(np.uint8)
        return clahe.apply(u8).astype(np.float32) / 255.0

    if a.ndim == 2:
        return np.clip(_ausgleich(a), 0, 1)
    # Die 8-bit-Stufe betrifft nur den KORREKTURFAKTOR, nicht die Bilddaten selbst — die
    # bleiben in voller Genauigkeit erhalten.
    lum = _gray(a)
    faktor = _ausgleich(lum) / np.maximum(lum, 1e-6)
    return np.clip(a * faktor[..., None], 0, 1)


def tv_denoise(f, staerke=0.3, iterationen=5):
    """Kantenerhaltendes Entrauschen über wiederholte Total-Variation-Schritte.

    Das Gegenstück zu PixInsights TGVDenoise, klassisch umgesetzt: das Bild wird schrittweise
    in Richtung seiner kantenerhaltend geglätteten Fassung gezogen. Anders als ein Gauss- oder
    Medianfilter bleiben Kanten dabei stehen, weil der bilaterale Filter Pixel nur mit
    ÄHNLICH HELLEN Nachbarn mittelt.

    Der Baustein `_tv_step` steckte schon in der Dekonvolution (dort gegen Ringing); hier wird
    er als eigenständiges Entrauschen nutzbar gemacht. Wirkt auf die Helligkeit, damit keine
    Farbflecken entstehen.

    staerke: 0..1 je Schritt (0 = aus). iterationen: wie oft.
    """
    if f is None or staerke <= 0:
        return f
    a = np.clip(np.asarray(f, np.float32), 0, 1)
    w = float(np.clip(staerke, 0.0, 1.0))
    if a.ndim == 2:
        out = a
        for _ in range(max(1, int(iterationen))):
            out = _tv_step(out, w)
        return np.clip(out, 0, 1)
    lum = _gray(a)
    glatt = lum
    for _ in range(max(1, int(iterationen))):
        glatt = _tv_step(glatt, w)
    faktor = glatt / np.maximum(lum, 1e-6)
    return np.clip(a * faktor[..., None], 0, 1)


def _bg_anwenden(bild, flaeche, korrektur="sub"):
    """Hintergrundfläche anwenden — subtraktiv oder dividierend.

    'sub': Fläche abziehen, mittleren Pegel zurückgeben. Richtig für ADDITIVE Störungen
           (Lichtverschmutzung, Amp-Glow).
    'div': durch die auf ihren Median normierte Fläche teilen. Richtig für MULTIPLIKATIVE
           Störungen, vor allem Vignettierung: die Bildecke bekommt weniger LICHT, der Abfall
           ist also ein Faktor. Abziehen hebt dort nur den Pegel an, ohne das Signal selbst zu
           korrigieren — dunkle Ecken bleiben dunkel, und das Rauschen wird mit angehoben.
           Der Divisor wird nach unten begrenzt, damit ein sehr dunkler Rand nicht explodiert.
    """
    import numpy as _np
    flaeche = _np.asarray(flaeche, _np.float32)
    if str(korrektur).lower().startswith("div"):
        m = float(_np.median(flaeche))
        if abs(m) < 1e-6:
            return bild
        norm = _np.clip(flaeche / m, 0.25, 4.0)
        return bild / norm
    return bild - flaeche + float(_np.median(flaeche))


def background_extract(f, strength=0.12, method="rbf", grid=12, korrektur="sub",
                       log=log_print):
    """Hintergrund-/Gradienten-Entfernung (Lichtverschmutzung, Vignette).

    method='rbf' (Standard, DBE/GraXpert-Prinzip): das Bild kacheln, pro Kachel einen ROBUSTEN
    Sky-Wert (unteres Perzentil) als Stützpunkt nehmen, Stützpunkte verwerfen, die deutlich über dem
    Feld-Trend liegen (= echte Großstruktur/Nebel → NICHT mitmodellieren), dann eine glatte
    Thin-Plate-Spline-Fläche durch die verbliebenen Punkte legen und abziehen. Anders als ein
    Tiefpass-Blur folgt das NICHT dem ausgedehnten Nebel und frisst ihn daher nicht weg.
    method='blur': der alte einfache Tiefpass (Fallback, wenn scipy fehlt).

    korrektur='sub' (Standard) zieht die Fläche AB — richtig für additive Störungen:
    Lichtverschmutzung, Amp-Glow, Himmelshintergrund.
    korrektur='div' TEILT durch die Fläche — richtig für MULTIPLIKATIVE Störungen, allen voran
    Vignettierung. Ohne Flat ist das der einzige Weg, dunkle Ecken sauber wegzubekommen:
    Subtrahieren verschiebt dort nur den Pegel, während der Abfall in Wahrheit ein Faktor ist
    (die Ecke bekommt schlicht weniger Licht). GraXpert bietet dieselbe Wahl."""
    if method == "rbf":
        try:
            from scipy.interpolate import RBFInterpolator

            def _sky_flaeche(g, H, W):
                """Glatte Sky-Fläche für EINEN Kanal (oder None, wenn zu wenige Stützpunkte)."""
                ys = np.linspace(H * 0.06, H * 0.94, grid)
                xs = np.linspace(W * 0.06, W * 0.94, grid)
                pts, vals = [], []
                bh, bw = int(H / grid / 2), int(W / grid / 2)
                for y in ys:
                    for x in xs:
                        yi, xi = int(y), int(x)
                        tile = g[max(0, yi - bh):yi + bh, max(0, xi - bw):xi + bw]
                        if tile.size:
                            pts.append((x, y)); vals.append(float(np.percentile(tile, 25)))
                pts = np.array(pts, np.float32); vals = np.array(vals, np.float32)
                # Stützpunkte gegen einen GLATTEN 2D-Quadrat-Trend verwerfen (nicht global): so
                # bleiben großflächige Gradienten/Ecken-Glow (Lichtverschmutzung, Amp-Glow) im
                # Modell und werden mit abgezogen — nur lokal ÜBER dem Trend liegende Punkte
                # (= Nebel/Struktur) fliegen raus.
                px, py = pts[:, 0] / W, pts[:, 1] / H
                design = np.stack([np.ones_like(px), px, py, px * px, px * py, py * py], 1)
                keep = np.ones(len(vals), bool)
                for _ in range(3):
                    if keep.sum() < 6:
                        break
                    coef, *_ = np.linalg.lstsq(design[keep], vals[keep], rcond=None)
                    resid = vals - design @ coef
                    rmad = float(np.median(np.abs(resid - np.median(resid)))) * 1.4826 + 1e-6
                    keep = resid <= 2.5 * rmad          # nur Punkte ÜBER dem Trend (Nebel) raus
                if keep.sum() < max(8, grid):
                    return None, 0
                rbf = RBFInterpolator(pts[keep], vals[keep], kernel="thin_plate_spline",
                                      smoothing=1.0)
                gy, gx = np.mgrid[0:H, 0:W]
                return rbf(np.stack([gx.ravel(), gy.ravel()], 1)).reshape(H, W).astype(np.float32), int(keep.sum())

            H, W = f.shape[:2]
            if f.ndim == 3:
                # PRO KANAL modellieren. Vorher wurde EINE Graustufen-Fläche geschätzt und von
                # allen drei Kanälen gleich abgezogen — das kann einen FARBIGEN Hintergrund
                # grundsätzlich nicht entfernen. Genau der Normalfall: Lichtverschmutzung ist
                # rot/orange, Amp-Glow der ASI294MC Pro (IMX294) ist blau. Gemessen blieb an
                # einem blauen Ecken-Glow im Blaukanal +0.0913 stehen, während Rot mit -0.0541
                # ÜBERkorrigiert wurde — also ein neuer Farbstich statt eines sauberen Bildes.
                out = f.astype(np.float32).copy()
                n_pts = 0
                for c in range(f.shape[2]):
                    surf, n = _sky_flaeche(f[..., c].astype(np.float32), H, W)
                    if surf is None:
                        continue
                    n_pts = max(n_pts, n)
                    out[..., c] = _bg_anwenden(out[..., c], surf, korrektur)
                if n_pts:
                    log(f"    Hintergrund (RBF/DBE-Stil, je Kanal): {n_pts} Sky-Stützpunkte, "
                        f"Nebel geschützt")
                    return np.clip(out, 0, 1)
            else:
                surf, n = _sky_flaeche(f.astype(np.float32), H, W)
                if surf is not None:
                    log(f"    Hintergrund (RBF/DBE-Stil): {n} Sky-Stützpunkte, Nebel geschützt")
                    return np.clip(_bg_anwenden(f, surf, korrektur), 0, 1)
        except Exception as e:
            log(f"    Hintergrund: RBF nicht verfügbar ({e}) → Tiefpass")
    u16 = (np.clip(f, 0, 1) * 65535).astype(np.uint16)
    star_suppressed = cv2.medianBlur(u16, 5).astype(np.float32) / 65535.0
    sigma = max(8.0, min(f.shape[0], f.shape[1]) * strength / 3.0)
    bg = cv2.GaussianBlur(star_suppressed, (0, 0), sigma)
    return np.clip(_bg_anwenden(f, bg, korrektur), 0, 1)


def estimate_psf(f, size=21, max_stars=80):
    """PSF (Punktspreizfunktion) EMPIRISCH aus dem Bild schätzen: viele kleine, ungesättigte Sterne
    finden, je ein size×size-Fenster um den Stern ausschneiden, alle (auf das Maximum zentriert)
    mitteln → die mittlere Sternform = die PSF (Seeing/Optik/Nachführung). Normalisiert (Summe 1).
    Fallback auf eine schmale Gauss-PSF, wenn zu wenige saubere Sterne da sind."""
    g = _gray(f)
    g = g / (float(g.max()) + 1e-6)
    pts = _star_centroids(g, max_stars=max_stars * 3)
    h, w = g.shape[:2]
    half = size // 2
    acc = np.zeros((size, size), np.float32)
    n = 0
    for x, y in pts:
        xi, yi = int(round(x)), int(round(y))
        if half < xi < w - half and half < yi < h - half:
            patch = g[yi - half:yi + half + 1, xi - half:xi + half + 1].astype(np.float32)
            peak = float(patch.max())
            if 0.05 < peak < 0.9:                       # ungesättigt, über Rauschen
                patch = patch - float(np.median(patch))  # lokalen Hintergrund abziehen
                patch = np.clip(patch, 0, None)
                s = float(patch.sum())
                if s > 1e-6:
                    acc += patch / s
                    n += 1
        if n >= max_stars:
            break
    if n < 8:
        psf = cv2.getGaussianKernel(size, size / 6.0)
        psf = psf @ psf.T
        return (psf / psf.sum()).astype(np.float32)
    acc = cv2.GaussianBlur(acc, (3, 3), 0)              # leicht glätten gegen Rausch-PSF
    return (acc / (acc.sum() + 1e-9)).astype(np.float32)


def _tv_step(est, weight):
    """A5 — ein Total-Variation-Regularisierungsschritt: dämpft das aktuelle RL-Estimate leicht in
    Richtung seiner kantenerhaltenden, geglätteten Version. weight∈[0,1] mischt Original↔geglättet.
    Kantenerhaltend via bilateralem Filter (fällt auf Gauss zurück, falls nicht verfügbar)."""
    if weight <= 0:
        return est
    e = est.astype(np.float32)
    mx = float(e.max()) or 1.0
    try:
        sm = cv2.bilateralFilter((e / mx).astype(np.float32), d=5,
                                 sigmaColor=0.05, sigmaSpace=3.0) * mx
    except Exception:
        sm = cv2.GaussianBlur(e, (0, 0), 1.0)
    return (1.0 - weight) * e + weight * sm


def _rl_deconv(obs, psf, iterations, regularize=0.0, support=None):
    """Kern-Richardson-Lucy auf einem Graukanal (FFT-frei). Optional pro Iteration ein TV-Schritt
    (`regularize`) und eine Support-Maske (`support`, 0..1), die die multiplikative Korrektur lokal
    in Richtung 1 dämpft (Deringing in flachen Bereichen)."""
    psf = (psf / (psf.sum() + 1e-9)).astype(np.float32)
    psf_m = psf[::-1, ::-1].copy()
    obs = np.clip(obs, 1e-4, None)
    est = obs.copy()
    for _ in range(max(1, int(iterations))):
        conv = cv2.filter2D(est, -1, psf, borderType=cv2.BORDER_REFLECT)
        relative = obs / np.maximum(conv, 1e-6)
        corr = cv2.filter2D(relative, -1, psf_m, borderType=cv2.BORDER_REFLECT)
        if support is not None:
            corr = 1.0 + support * (corr - 1.0)          # außerhalb des Supports → kaum Korrektur
        est = np.clip(est * corr, 0, None)
        if regularize > 0:
            est = _tv_step(est, float(np.clip(regularize, 0, 1)))
    return est


def _detail_support(lum, thresh=2.5):
    """A5 — Support-/Detailmaske aus à-trous-artigen Detailebenen: Pixel mit echter Struktur (Sterne,
    Kanten, Nebel-Detail) bekommen 1, flacher Hintergrund ~0. Dort darf RL schärfen, im Flachen wird
    gedämpft → keine Ringe/verstärktes Rauschen in leeren Bereichen."""
    g = lum.astype(np.float32)
    detail = np.zeros_like(g)
    cur = g
    for s in (1.0, 2.0, 4.0):                             # mehrere Skalen aufsummieren
        blur = cv2.GaussianBlur(g, (0, 0), s)
        detail = np.maximum(detail, np.abs(cur - blur))
        cur = blur
    med = float(np.median(detail))
    mad = float(np.median(np.abs(detail - med))) * 1.4826 + 1e-6
    sup = np.clip((detail - med) / (thresh * mad), 0, 1).astype(np.float32)
    return cv2.GaussianBlur(sup, (0, 0), 2.0)            # weiche Ränder gegen Maskenkanten


def deconvolve(f, psf=None, iterations=15, star_protect=0.85, regularize=0.0,
               deringing=True, tiled_psf=False, tiles=3, log=log_print):
    """Dekonvolution (PixInsight/Deconvolution-Stil) — schärft echtes Detail zurück, das Seeing/Optik
    verschmiert haben. Richardson-Lucy (für Poisson-Statistik korrekt) auf der LUMINANZ, mit aus den
    Sternen geschätzter PSF (oder übergebener PSF). Wirkt auf LINEARE Daten (vor dem Strecken).

    A5 — `regularize` (0..1): Total-Variation-Regularisierung pro Iteration. RL verstärkt mit jeder
    Iteration auch Rauschen und neigt zu Ringeln; ein leichter kantenerhaltender Glättungsschritt je
    Iteration dämpft das, ohne echte Kanten zu verlieren (0 = aus, 0.05–0.2 typisch).

    A5 — `deringing` (Default True): eine Support-/Detailmaske aus den Detailebenen begrenzt die
    RL-Korrektur auf strukturierte Bereiche. In flachem Hintergrund (wo Ringe & Rauschverstärkung
    entstehen) wird die Korrektur lokal Richtung neutral gedämpft.

    A5 — `tiled_psf` (Default False): ortsabhängige PSF. Das Feld wird in `tiles`×`tiles` Kacheln
    geteilt, je Kachel aus den DORTIGEN Sternen eine eigene PSF geschätzt und separat dekonvolviert
    (mit Überlappung weich zusammengeblendet). Fängt über das Feld variierendes Seeing/Koma/Tilt ab.
    Fällt auf eine globale PSF zurück, wo eine Kachel zu wenige Sterne hat.

    Wichtig — Stern-Schutz: RL erzeugt an hellen, gesättigten Sternkernen gern dunkle Ringe/Übersch-
    winger. `star_protect` (Helligkeitsschwelle 0..1) blendet die hellsten Bereiche weich aufs Original
    zurück → schärferes Nebeldetail OHNE Ring-Artefakte um Sterne. Reine OpenCV/NumPy (FFT-frei)."""
    if f is None:
        return f
    lum = _gray(f).astype(np.float32)
    obs = np.clip(lum, 1e-4, None)
    support = _detail_support(lum) if deringing else None

    if tiled_psf:
        H, W = lum.shape[:2]
        nt = max(1, int(tiles))
        est = np.zeros_like(obs)
        wsum = np.zeros_like(obs)
        ov = 0.25                                        # 25 % Überlappung der Kacheln
        gpsf = psf if psf is not None else estimate_psf(f)
        ys = np.linspace(0, H, nt + 1).astype(int)
        xs = np.linspace(0, W, nt + 1).astype(int)
        for ti in range(nt):
            for tj in range(nt):
                y0, y1 = ys[ti], ys[ti + 1]
                x0, x1 = xs[tj], xs[tj + 1]
                py = int((y1 - y0) * ov); px = int((x1 - x0) * ov)
                ay0, ay1 = max(0, y0 - py), min(H, y1 + py)
                ax0, ax1 = max(0, x0 - px), min(W, x1 + px)
                sub = f[ay0:ay1, ax0:ax1]
                try:
                    lpsf = estimate_psf(sub)
                except Exception:
                    lpsf = gpsf
                if lpsf is None:
                    lpsf = gpsf
                sup = support[ay0:ay1, ax0:ax1] if support is not None else None
                tile_est = _rl_deconv(np.clip(_gray(sub), 1e-4, None), lpsf, iterations,
                                      regularize, sup)
                # Echtes weiches Fenster: Rampe von den Kachelrändern zur Mitte, damit sich
                # überlappende Kacheln WIRKLICH weich mischen. (Eine konstante Eins-Maske +
                # GaussianBlur mit Reflect-Rand blieb konstant 1 → das Blending war ein No-Op.)
                th_, tw_ = tile_est.shape[:2]
                my = max(1, int(th_ * ov)); mx2 = max(1, int(tw_ * ov))
                ry = np.minimum(1.0, np.minimum(np.arange(th_) + 1, th_ - np.arange(th_)) / my)
                rx = np.minimum(1.0, np.minimum(np.arange(tw_) + 1, tw_ - np.arange(tw_)) / mx2)
                wmask = np.outer(ry, rx).astype(np.float32)
                est[ay0:ay1, ax0:ax1] += tile_est * wmask
                wsum[ay0:ay1, ax0:ax1] += wmask
        est = est / np.clip(wsum, 1e-6, None)
    else:
        if psf is None:
            psf = estimate_psf(f)
        est = _rl_deconv(obs, psf, iterations, regularize, support)

    # Schärfungs-Verhältnis auf die Farbkanäle übertragen (Farbe bleibt erhalten)
    ratio = est / np.maximum(lum, 1e-4)
    ratio = np.clip(ratio, 0.3, 3.0)
    out = f.astype(np.float32) * ratio[..., None] if f.ndim == 3 else f.astype(np.float32) * ratio
    # Stern-Schutz: in den hellsten Zonen weich aufs Original zurückblenden (gegen RL-Ringe)
    if star_protect is not None and star_protect < 1.0:
        hi = np.clip((lum - star_protect) / max(1e-3, 1.0 - star_protect), 0, 1)
        hi = cv2.GaussianBlur(hi, (0, 0), 2.0)
        m = hi[..., None] if out.ndim == 3 else hi
        out = out * (1 - m) + f.astype(np.float32) * m
    psf_sz = psf.shape[0] if (psf is not None and not tiled_psf) else "tiled"
    log(f"    Dekonvolution: Richardson-Lucy {iterations} Iter., PSF {psf_sz}, "
        f"reg={regularize}, deringing={deringing}, Stern-Schutz {star_protect}")
    return np.clip(out, 0, 1)


def _extract_ha_oiii(bgr, unmix=0.20):
    """Hα und OIII aus Dual-Band-OSC SAUBER trennen (normalisiert, [0..1]).
    Übersprechen beim OSC-Sensor: Hα (656 nm) → v. a. Rot (leckt etwas in Grün), OIII (500 nm) →
    Grün+Blau (leckt etwas in Rot). Darum Hα=Rot, OIII=Blau (Grün am stärksten Hα-kontaminiert),
    Hintergrund pro Kanal abziehen, leichte lineare Entmischung, einzeln normalisieren."""
    f = bgr.astype(np.float32)
    b, _, r = f[..., 0], f[..., 1], f[..., 2]

    def _sub_bg(x):
        return np.clip(x - float(np.quantile(x, 0.30)), 0, None)

    ha, oiii = _sub_bg(r), _sub_bg(b)
    ha2 = np.clip(ha - unmix * oiii, 0, None)
    oiii2 = np.clip(oiii - unmix * ha, 0, None)

    def _norm(x):
        return np.clip(x / max(float(np.quantile(x, 0.999)), 1e-6), 0, 1)

    return _norm(ha2), _norm(oiii2)


def _star_desat(out, ha_n, oiii_n, strength=0.92):
    """Sterne (Kontinuum-Quellen) **neutral/weiß** ziehen — in Schmalband ist Sternfarbe ein
    Artefakt (durchs Dual-Band-Filter kommen nur Hα-Rot + OIII-Cyan → türkise Sternkugeln).
    Ausgedehnte Nebel behalten ihre Farbe.

    Zwei Stufen: kompakte Sternkerne über lokalen Kontrast erkennen (niedriges Helligkeits-Gate,
    damit auch mittelhelle Sterne erfasst werden) und die Maske um die **Sternhöfe** aufweiten —
    sonst bleibt der Glow heller Sterne farbig, während nur der Kern entsättigt wird."""
    lum = np.maximum(ha_n, oiii_n).astype(np.float32)
    smooth = cv2.medianBlur((lum * 255).astype(np.uint8), 9).astype(np.float32) / 255.0
    detail = np.clip(lum - smooth, 0, 1)
    core = np.clip(detail * 6.0, 0, 1) * np.clip((lum - 0.06) / 0.06, 0, 1)   # kompakte Sternkerne
    coreb = (core > 0.25).astype(np.uint8)
    # Hof-Aufweitung MIT Deckel. Eine feste 13x13-Dilation verschmilzt in sternreichen Feldern
    # die Hoefe zu einer Decke ueber das ganze Bild: gemessen wuchs die Maske von 1.3 % echten
    # Sternkernen auf 33 %, nach dem Weichzeichnen wirkte sie auf 65 % der Flaeche. Ergebnis war
    # eine halbierte Saettigung des GANZEN Bildes (0.472 -> 0.257) — der Nebel wurde mit
    # entfaerbt, obwohl nur Sterne gemeint waren.
    kern_anteil = float(coreb.mean())
    halo = coreb
    for k in (13, 9, 7, 5):
        kandidat = cv2.dilate(coreb, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        # hoechstens das Vierfache der Kernflaeche und nie mehr als 10 % des Bildes
        if float(kandidat.mean()) <= min(max(4.0 * kern_anteil, 0.01), 0.10):
            halo = kandidat
            break
    else:
        halo = coreb  # Hof drumherum
    mask = np.maximum(core, halo.astype(np.float32))
    mask = cv2.GaussianBlur(mask, (0, 0), 3)[..., None]
    gray = out.mean(axis=2, keepdims=True)
    return np.clip(out * (1 - strength * mask) + gray * (strength * mask), 0, 1)


def remove_stars(bgr, sensitivity=5.0, max_size=600, min_size=4, iterations=2, log=log_print,
                 full_mask=False):
    """A6 — Klassisches (nicht-ML) Star-Removal: liefert ein (teilweise) STERNLOSES Nebelbild plus
    die Sternmaske. Reines OpenCV/NumPy.

    Vorgehen:
      1. Sternmaske bauen — Hintergrund (großer Median) abziehen, rauschadaptive Schwelle
         (Median + sensitivity·MAD), nur kompakte, etwa runde Blobs bis `max_size` px² behalten
         (so bleiben ausgedehnte Nebelstrukturen außen vor).
      2. Maske leicht aufweiten (Sternhöfe mitnehmen).
      3. Sternkerne iterativ entfernen: morphologische Grauwert-Öffnung "schrumpft" helle Punkte,
         und der Bereich unter der Maske wird in float32 aus der Nebel-Umgebung gefüllt.
         Mehrere Iterationen knabbern größere Sterne weiter ab.

    EHRLICHE GRENZEN: Funktioniert gut für KLEINE bis MITTLERE Sterne. GROSSE, gesättigte Sterne mit
    ausgedehnten Halos/Beugungsspikes werden nur PARTIELL entfernt (Restglow/Ringe bleiben), und sehr
    sternreiche Felder über dichtem Nebel können lokal etwas Nebeltextur verlieren. Für saubere
    Resultate auf großen Sternen ist ein ML-Verfahren (StarNet/Starless) überlegen — das ist hier
    bewusst nicht enthalten (kein ML, keine externen Gewichte).

    Args:
        bgr: float32 [0..1] BGR (oder Grau).
        sensitivity: MAD-Faktor der Sternschwelle (kleiner = mehr Sterne erfasst).
        max_size: maximale Blobfläche (px²), die noch als Stern gilt (größer = Nebel, wird geschont).
        iterations: Erosions-/Inpaint-Durchgänge (mehr = aggressiver gegen größere Sterne).

    Returns:
        (starless, mask) — starless: float32 [0..1] gleiche Form/Channels wie Eingabe;
        mask: float32 [0..1] Sternmaske (1 = Stern).
    """
    if bgr is None:
        return bgr, None
    f = bgr.astype(np.float32)
    if f.size == 0 or not np.isfinite(f).all():
        raise ForgePixFehler("Sternentfernung: leere oder ungueltige Bilddaten.")
    g = _gray(f)
    g = g / (float(g.max()) + 1e-6)

    # 1) Sternmaske: Hintergrund weg, rauschadaptive Schwelle
    a = (np.clip(g, 0, 1) * 255).astype(np.uint8)
    bg = cv2.medianBlur(a, 31)
    sub = cv2.subtract(a, bg).astype(np.float32)
    med = float(np.median(sub))
    mad = float(np.median(np.abs(sub - med))) * 1.4826 + 1e-6
    th = (sub > max(med + sensitivity * mad, 3.0)).astype(np.uint8)

    n, lbl, stats, _cent = cv2.connectedComponentsWithStats(th, connectivity=8)
    mask = np.zeros_like(th)
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH]); bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        # Mindestfläche: ein einzelnes helles Pixel ist ein Treffer, kein Stern. Bisher stand
        # hier `area < 1`, was nichts ausschloss. Gemessen an einem echten Sub sank die Zahl der
        # Blobs dadurch von 165 auf 70 (linear, Maske 0,26 % auf 0,18 %) und auf einem
        # gestreckten Bild von 8313 auf 2079 (11,2 % auf 6,4 %).
        if area < min_size or area > max_size:
            continue
        # Kompaktheit: Sterne sind etwa rund; sehr langgezogene Strukturen (Nebelfilamente) raus
        if bw > 0 and bh > 0 and 0.3 <= bw / bh <= 3.3:
            mask[lbl == i] = 1
    # 2) Sternhöfe mitnehmen
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)

    # 3) Iterativ: helle Kerne morphologisch dämpfen + Maskenbereich aus Umgebung inpainten
    out = f.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    grow = mask.copy()
    used_mask = mask.copy()
    for _ in range(max(1, int(iterations))):
        # morphologische Grauwert-Öffnung drückt isolierte helle Punkte herunter
        opened = cv2.morphologyEx(out, cv2.MORPH_OPEN, kernel)
        sel = grow.astype(bool)
        if out.ndim == 3:
            for c in range(out.shape[2]):
                oc = out[..., c]; opc = opened[..., c]
                oc[sel] = np.minimum(oc[sel], opc[sel])
        else:
            opc = opened
            out[sel] = np.minimum(out[sel], opc[sel])
        # OpenCV supports float inpainting per plane. NS avoids Telea's
        # integer-scale intensity increments on normalized floating data.
        if out.ndim == 3:
            inpainted = np.stack([cv2.inpaint(np.ascontiguousarray(out[..., c]), grow,
                                             3, cv2.INPAINT_NS)
                                  for c in range(out.shape[2])], axis=-1)
        else:
            inpainted = cv2.inpaint(out, grow, 3, cv2.INPAINT_NS)
        if inpainted.ndim == 2 and out.ndim == 3:
            inpainted = inpainted[..., None]
        m3 = grow.astype(np.float32)
        m3 = m3[..., None] if out.ndim == 3 else m3
        out = out * (1 - m3) + inpainted * m3
        used_mask |= grow
        grow = cv2.dilate(grow, kernel, iterations=1)    # nächste Runde greift etwas weiter

    starless = out.astype(np.float32)
    log(f"    Star-Removal: {int(mask.sum())} Sternpixel maskiert, {iterations} Iter. "
        f"(klein/mittel ok; große Halos nur partiell)")
    # Source detection mask remains stable for star-centroid/flux consumers;
    # layer editing can request the complete interpolation footprint.
    return starless, (used_mask if full_mask else mask).astype(np.float32)


def _moffat_kern(radius, fwhm, beta=2.5):
    """Moffat-Profil als Kern, Summe 1. FWHM = 2·alpha·sqrt(2^(1/beta) − 1).

    Warum Moffat und nicht Gauss: echte Sterne haben durch Seeing breitere Flanken, als eine
    Gauss-Kurve sie hergibt. Setzt man Gauss-Sterne ein, wirken sie wie aufgeklebte Punkte.
    beta steuert genau diese Flanken (kleiner = breiter; 2.5 ist ein üblicher Himmelswert).
    """
    n = int(2 * radius + 1)
    y, x = np.mgrid[-radius:radius + 1, -radius:radius + 1].astype(np.float32)
    alpha = max(float(fwhm), 0.8) / (2.0 * np.sqrt(2.0 ** (1.0 / max(beta, 0.6)) - 1.0))
    k = (1.0 + (x * x + y * y) / (alpha * alpha)) ** (-float(beta))
    s = float(k.sum())
    return (k / s).astype(np.float32) if s > 1e-9 else np.zeros((n, n), np.float32)


def _stern_liste(rest, maske, min_flaeche=3, max_flaeche=900, halb=8):
    """Aus Restbild (Original − sternlos) und Sternmaske eine Liste (x, y, fwhm_px, fluss_bgr).

    Zwei Entscheidungen, die den Unterschied machen:

    1. **Gemessen wird auf einem FENSTER um den Stern, nicht innerhalb der Maske.** Die Maske ist
       eine Schwelle; wer nur über ihr rechnet, schneidet die Flanken ab und unterschätzt die
       Breite systematisch. Im ersten Entwurf kam so über ein ganzes Feld eine Zielbreite von
       1,2 px heraus — die Sterne verschwanden danach unter der Nachweisgrenze.

    2. **Als Breite zählt die KLEINERE Hauptachse.** Bei nachgeführten Strichen ist die lange
       Achse der Fehler, die kurze das echte Seeing. Nur so wird beim Neusetzen keine Schärfe
       vorgetäuscht und kein Nachführfehler nachgebaut.

    Die Maske wird vorher leicht geweitet, damit ein zerrissener Strich EIN Stern bleibt und
    nicht in Dutzende Bruchstücke zerfällt (ungeweitet: 1770 „Sterne" statt 60).
    """
    lum = _gray(rest) if rest.ndim == 3 else rest
    h, w = lum.shape[:2]
    m = (np.asarray(maske) > 0.5).astype(np.uint8)
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, lab, stats, mitte = cv2.connectedComponentsWithStats(m, 8)
    sterne = []
    for i in range(1, n):
        if not (min_flaeche <= int(stats[i, cv2.CC_STAT_AREA]) <= max_flaeche):
            continue
        x0, y0 = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
        x1 = min(w, x0 + int(stats[i, cv2.CC_STAT_WIDTH]))
        y1 = min(h, y0 + int(stats[i, cv2.CC_STAT_HEIGHT]))
        # Gerechnet wird über den EIGENEN Bereich des Sterns, nicht über ein festes Fenster.
        # Ein festes Fenster ist in beide Richtungen falsch: 8 px schnitten bei hellen Sternen
        # die Flanken ab (5 % Fluss zu wenig), mitwachsende Fenster überlappten bei Nachbarn und
        # zählten doppelt (9 % zu viel). Der Bereich der geweiteten Maske hat beide Probleme
        # nicht — ausserhalb davon ist `rest` ohnehin null, weil `remove_stars` nur dort ändert.
        sel = (lab[y0:y1, x0:x1] == i)
        wgt = np.where(sel, np.clip(lum[y0:y1, x0:x1], 0, None), 0.0).astype(np.float64)
        summe = float(wgt.sum())
        if summe <= 1e-8:
            continue
        yy, xx = np.mgrid[0:(y1 - y0), 0:(x1 - x0)].astype(np.float64)
        cx, cy = float((wgt * xx).sum() / summe), float((wgt * yy).sum() / summe)
        dx, dy = xx - cx, yy - cy
        vxx = float((wgt * dx * dx).sum() / summe)
        vyy = float((wgt * dy * dy).sum() / summe)
        vxy = float((wgt * dx * dy).sum() / summe)
        spur, det = vxx + vyy, vxx * vyy - vxy * vxy
        wurzel = np.sqrt(max(spur * spur / 4.0 - det, 0.0))
        klein = max(spur / 2.0 - wurzel, 0.05)                  # kleinere Hauptachse
        fwhm = 2.3548 * np.sqrt(klein)
        if rest.ndim == 3:
            fluss = [float(np.where(sel, np.clip(rest[y0:y1, x0:x1, c], 0, None), 0.0).sum())
                     for c in range(rest.shape[2])]
        else:
            fluss = [summe]
        sterne.append((x0 + cx, y0 + cy, float(fwhm), fluss))
    return sterne


def synthstar(bgr, groesse=1.0, beta=2.5, sensitivity=5.0, min_fwhm=1.2, log=log_print):
    """Sternprofile durch synthetische, runde PSFs ersetzen (Siril `synthstar`).

    Wogegen das hilft: Koma am Bildrand, Nachführfehler, Verkippung — alles Fehler, die die
    STERNE verformen, während der Nebel es kaum zeigt. Rechnerisch lässt sich das nicht
    „entzerren"; man kann die Sterne aber neu setzen. Vorgehen:
      1. Sterne entfernen (klassisch, ohne ML) → sternloses Bild + Maske.
      2. Aus dem Restbild je Stern Ort, Breite und Fluss messen (flussgewichtete Momente).
      3. Als Zielbreite die MEDIAN-Breite des Feldes nehmen — nicht die kleinste. Die kleinste
         wäre schärfer, würde aber überall dort, wo die Optik es nicht hergibt, Schärfe
         vortäuschen, die nie aufgenommen wurde.
      4. Runde Moffat-Profile mit demselben Fluss ins sternlose Bild zurücksetzen.

    Der Fluss bleibt je Kanal erhalten — die Sternfarben ändern sich also nicht, nur die Form.

    EHRLICHE GRENZE: das Verfahren erfindet die Sternform. Was auf dem Sensor eine Linie war,
    wird zu einem runden Punkt — das ist eine Darstellungsentscheidung, keine Rekonstruktion.
    Für Messzwecke (Photometrie, Astrometrie) ist das Ergebnis unbrauchbar.
    """
    if bgr is None:
        return bgr
    a = np.clip(np.asarray(bgr, np.float32), 0, 1)
    starless, maske = remove_stars(a, sensitivity=sensitivity, log=lambda *x: None)
    if maske is None:
        log("    synthstar: keine Sterne gefunden — Bild unverändert")
        return a
    deckung = float((np.asarray(maske) > 0.5).mean())
    if deckung > 0.10:
        # NOTBREMSE. Deckt die "Sternmaske" mehr als ein Zehntel des Bildes ab, ist sie keine
        # Sternmaske — dann steht dort Rauschen oder Nebel drin, und das Neusetzen wuerde das
        # Bild zerstoeren statt es zu verbessern. Gemessen an einem gestreckten Stack: Maske
        # 65 %, danach 27 % des Gesamtflusses weg und der Himmel halbiert. Ursache ist fast
        # immer, dass synthstar auf GESTRECKTE Daten losgelassen wurde; es gehoert auf die
        # linearen.
        log("    synthstar: Sternmaske deckt %.0f %% des Bildes ab — das sind keine Sterne. "
            "Bild unveraendert (synthstar gehört auf die LINEAREN Daten, nicht auf gestreckte)."
            % (100 * deckung))
        return a
    rest = np.clip(a - starless, 0, None)
    sterne = _stern_liste(rest, maske)
    if len(sterne) < 5:
        log("    synthstar: nur %d Sterne messbar — Bild unverändert" % len(sterne))
        return a
    ziel = max(float(np.median([s[2] for s in sterne])) * float(groesse), float(min_fwhm))
    out = starless.copy()
    h, w = out.shape[:2]
    kan = out.shape[2] if out.ndim == 3 else 1
    radius = max(3, int(round(3.0 * ziel)))
    kern = _moffat_kern(radius, ziel, beta)
    for (cx, cy, _fw, fluss) in sterne:
        xi, yi = int(round(cx)), int(round(cy))
        x0, y0 = max(0, xi - radius), max(0, yi - radius)
        x1, y1 = min(w, xi + radius + 1), min(h, yi + radius + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        k = kern[y0 - (yi - radius):(y1 - (yi - radius)), x0 - (xi - radius):(x1 - (xi - radius))]
        for c in range(kan):
            f = fluss[c] if c < len(fluss) else fluss[0]
            if out.ndim == 3:
                out[y0:y1, x0:x1, c] += k * f
            else:
                out[y0:y1, x0:x1] += k * f
    log("    synthstar: %d Sterne neu gesetzt, Zielbreite %.2f px (Moffat beta %.1f)"
        % (len(sterne), ziel, beta))
    return np.clip(out, 0, 1)


def dualband_hoo(bgr, unmix=0.20):
    """HOO-Palette: Rot=Hα, Grün+Blau=OIII → rote Hα-Nebel + tealfarbene OIII-Bereiche (zwei echte
    Signale, datentreu). Sterne werden neutralisiert."""
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    ha_n, oiii_n = _extract_ha_oiii(bgr, unmix)
    out = np.zeros((*ha_n.shape, 3), np.float32)
    out[..., 2] = ha_n                          # R = Hα
    out[..., 1] = oiii_n                        # G = OIII
    out[..., 0] = oiii_n                        # B = OIII → teal
    return _star_desat(out, ha_n, oiii_n)


def dualband_sho(bgr, unmix=0.20):
    """SYNTHETISCHE SHO-/Hubble-Palette aus Dual-Band (Ha+OIII) — **gold + blau** (klassisch).
    ⚠️ KEIN echtes SII in Dual-Band; SII wird aus Hα synthetisiert. Mapping wie in den Anleitungen:
    Rot = SII(≈Hα), Grün = 0.8·Hα + 0.2·OIII, Blau = OIII → Hα-Bereiche werden gold, OIII blau.
    Forciert den Gold-Look (auch bei reinen Hα-Zielen). Nicht wissenschaftlich, nur fürs Aussehen."""
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    ha, oiii = _extract_ha_oiii(bgr, unmix)
    out = np.zeros((*ha.shape, 3), np.float32)
    out[..., 2] = ha                            # R = SII(synthetisch ≈ Hα)
    out[..., 1] = np.clip(0.8 * ha + 0.2 * oiii, 0, 1)        # G → R+G = gold
    out[..., 0] = oiii                          # B = OIII → blau
    return _star_desat(out, ha, oiii)


def dualband_foraxx(bgr, unmix=0.20):
    """SYNTHETISCHE SHO-Palette im **Foraxx-Stil** (dynamisch, thecoldestnights.com): der Grün-Kanal
    wird je nach Hα·OIII-Stärke gemischt — G = f·Hα + (1−f)·OIII mit f = (Hα·OIII)^(1−Hα·OIII).
    Dadurch: reines Hα → rot, Hα+OIII gemischt → gold, reines OIII → blau. Nuancierter als das
    flache SHO, aber rein Hα-Ziele bleiben rot (kein erzwungenes Gold). SII synthetisch = Hα."""
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    ha, oiii = _extract_ha_oiii(bgr, unmix)
    prod = np.clip(ha * oiii, 1e-6, 1.0)
    fg = prod ** (1.0 - prod)
    out = np.zeros((*ha.shape, 3), np.float32)
    out[..., 2] = ha                            # R = SII(synthetisch ≈ Hα)
    out[..., 1] = np.clip(fg * ha + (1.0 - fg) * oiii, 0, 1)  # G = dynamischer Hα/OIII-Blend
    out[..., 0] = oiii                          # B = OIII
    return _star_desat(out, ha, oiii)


def dualband_bicolor(bgr, unmix=0.20):
    """Bicolor-Technik (nach Cannistra): aus zwei Kanälen (Hα, OIII) wird der fehlende **synthetisch
    errechnet**, damit Farben/Sterne natürlicher werden (weniger Magenta als reines HOO).
    Hier: Rot = Hα, Blau = OIII, **Grün = synthetisch** aus beiden (Mittel, OIII-betont):
    G = max(OIII, 0.5·Hα). Ergebnis: Hα-Bereiche bernstein/rot, OIII cyan-blau, Übergänge weich;
    Sterne werden neutraler. SII bleibt außen vor (nur Hα+OIII)."""
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    ha, oiii = _extract_ha_oiii(bgr, unmix)
    g = np.maximum(oiii, 0.5 * ha)              # synthetisches Grün aus den beiden Kanälen
    out = np.zeros((*ha.shape, 3), np.float32)
    out[..., 2] = ha                            # R = Hα
    out[..., 1] = np.clip(g, 0, 1)              # G = synthetisch (errechnet)
    out[..., 0] = oiii                          # B = OIII
    return _star_desat(out, ha, oiii)


def color_balance(f, strength=1.0):
    """Farbkalibrierung fürs Anzeigen (gegen Rotstich von OSC + LP-Filter):
      1. Himmelshintergrund PRO KANAL neutralisieren (Sky -> neutrales Grau),
      2. Kanäle so abgleichen, dass helle, unklippte Referenzen (Sterne) ~neutral werden.
    So treten die echten Nebelfarben hervor (rotes Ha, blaue Reflexion, teal O-III) statt alles rot.
    strength 0..1 blendet zwischen Original (0) und voller Kalibrierung (1) — einstellbar / KI-gesteuert.
    Wirkt nur aufs Vorschau-/JPG-Bild; die linearen Exports bleiben unangetastet."""
    if f is None or f.ndim != 3 or f.shape[2] != 3 or strength <= 0:
        return f
    src = f.astype(np.float32)
    bg = np.array([np.quantile(src[..., c], 0.30) for c in range(3)], np.float32)
    # Hintergrund neutralisieren, aber NICHT hart auf 0 clippen: ein kleiner Sockel bleibt stehen,
    # sonst hat der nachfolgende Stretch (MTF/asinh) keinen Hintergrund mehr zum Anheben (Bild wird
    # schwarz; an echten OSC-Daten verifiziert: Median 4 → 26). WICHTIG: der Sockel muss für ALLE
    # Kanäle GLEICH sein (neutrales Grau) — ein kanalweiser Sockel (bg_c·k) lässt den Kanal mit dem
    # höchsten Hintergrund (meist Blau) überstehen → Blaustich.
    pedestal = float(bg.min()) * 0.10                          # ein gemeinsamer, neutraler Sockel
    out = np.clip(src - (bg.reshape(1, 1, 3) - pedestal), 0, None)  # jeder Kanal-Hintergrund → pedestal
    hi = np.array([np.quantile(out[..., c], 0.995) for c in range(3)], np.float32)
    scale = np.clip(hi.mean() / np.clip(hi, 1e-6, None), 0.4, 2.5).astype(np.float32)
    out = np.clip(out * scale.reshape(1, 1, 3), 0, None)        # Sterne ~neutral -> echte Farben
    s = float(min(1.0, max(0.0, strength)))
    return out if s >= 1.0 else np.clip(src * (1 - s) + out * s, 0, None)


def photometric_balance(f, strength=1.0, max_stars=300, log=log_print):
    """Compatibility entry point for native stellar white balance, not PCC/SPCC.

    Circular stellar fluxes use a local background annulus. Unreliable fields
    remain unchanged; signed/HDR pixels survive the fitted color transform.
    """
    if f is None or f.ndim != 3 or f.shape[2] != 3:
        return f
    from star_color import balance
    return balance(f, strength, max_stars, log=log)


def neutralize_background(f, pct=25.0):
    """Hintergrund EXAKT farbneutral machen: pro Kanal den Himmels-Pegel (unteres Perzentil) auf
    denselben Zielwert ziehen. Unverzichtbar VOR einem aggressiven Stretch — die Stretch-Kurve ist
    nahe Null fast senkrecht, sodass schon eine winzige Kanal-Differenz (z. B. Blau 0.0033 vs Rot
    0.0028) zu einem massiven Farbstich aufgeblasen wird (an echten OSC-Daten gesehen: Blau→74,
    Rot→0.08). Treu/subtraktiv, erfindet nichts."""
    if f is None or f.ndim != 3 or f.shape[2] != 3:
        return f
    bg = np.array([np.percentile(f[..., c], pct) for c in range(3)], np.float32)
    target = float(bg.min())
    return np.clip(f - (bg - target).reshape(1, 1, 3), 0, None)


def remove_green_cast(f, amount=1.0):
    """SCNR-artige Grün-Entfernung (Average Neutral): Grün wird auf den Schnitt von Rot/Blau
    begrenzt. In der Deep-Sky-Fotografie ist Grün praktisch nie echtes Signal (Nebel sind rot/blau),
    ein Grünstich kommt von OSC-Bayer/Lichtverschmutzung. Subtraktiv/treu — fügt nichts hinzu.
    Entfernt zugleich grüne Hot-Pixel-/Stern-Sprenkel. amount 0..1."""
    if f is None or f.ndim != 3 or f.shape[2] != 3 or amount <= 0:
        return f
    out = f.astype(np.float32).copy()
    b, g, r = out[..., 0], out[..., 1], out[..., 2]      # BGR
    neutral = np.minimum(g, (b + r) * 0.5)
    out[..., 1] = g * (1 - amount) + neutral * amount
    return out


def _bg_surface(f, ds=8, coverage=None):
    """Glatte Hintergrund-/Gradienten-Fläche eines Frames (grob downsamplen + stark glätten →
    Sterne mitteln sich weg). Für die lokale Normalisierung."""
    g = f if f.ndim == 2 else f.mean(2)
    h, w = g.shape
    sw, sh = max(8, w // ds), max(8, h // ds)
    g = g.astype(np.float32)
    if coverage is not None:
        mask = np.asarray(coverage, dtype=np.float32)
        numerator = cv2.resize(g * mask, (sw, sh), interpolation=cv2.INTER_AREA)
        denominator = cv2.resize(mask, (sw, sh), interpolation=cv2.INTER_AREA)
        sigma = max(2.0, sw / 10.0)
        numerator = cv2.GaussianBlur(numerator, (0, 0), sigma)
        denominator = cv2.GaussianBlur(denominator, (0, 0), sigma)
        small = np.divide(numerator, denominator, out=np.zeros_like(numerator),
                          where=denominator > 1e-6)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    small = cv2.resize(g, (sw, sh), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), max(2.0, sw / 10.0))
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def local_normalize(frame, ref_surface, coverage=None):
    """Frame **örtlich** an die Referenz-Hintergrundfläche angleichen (statt nur per Skalar-Offset).
    Da die Frames registriert sind, hebt sich der gemeinsame Nebel in (ref_surf − frame_surf) auf —
    übrig bleibt der **örtliche Hintergrund-/Gradienten-Unterschied**, der korrigiert wird. Das macht
    die Ausreißer-Rejection erst korrekt (gegen Gradienten & Mehrfach-Sessions)."""
    corr = ref_surface - _bg_surface(frame, coverage=coverage)
    return frame + (corr[..., None] if frame.ndim == 3 else corr)


def _mtf(x, m):
    """Midtones Transfer Function (PixInsight-Primitive): MTF(x,m) = (m−1)x / ((2m−1)x − m).
    Reversibel, definiert auf [0,1]. m = Mitteltonbalance (klein = stark aufhellen)."""
    x = np.asarray(x, np.float32)
    den = (2.0 * m - 1.0) * x - m
    out = np.where(np.abs(den) < 1e-9, x, ((m - 1.0) * x) / den)
    return np.clip(out, 0, 1)


def mtf_stretch(f, target_bg=0.25, shadow=-2.8, saturation=1.05, denoise_chroma=True):
    """MTF-Auto-Stretch (PixInsight-AutoSTF-Stil): Schwarzpunkt aus Median+shadow·MAD, dann
    Mitteltonbalance so, dass der Himmelshintergrund auf `target_bg` (≈0.25) gehoben wird.
    Korrekt und reversibel — kontrollierter als asinh, mit definiertem Schwarzpunkt."""
    g = _gray(f)
    med = float(np.median(g))
    mad = float(np.median(np.abs(g - med))) * 1.4826 + 1e-6
    c0 = float(np.clip(med + shadow * mad, 0, 0.99))            # Schwarzpunkt (shadow<0 → unter Median)
    x = np.clip((f - c0) / max(1e-6, 1 - c0), 0, 1)
    mn = float(np.clip((med - c0) / max(1e-6, 1 - c0), 1e-4, 0.9999))
    T = target_bg
    m = mn * (T - 1.0) / (2 * T * mn - T - mn)                  # MTF(mn,m)=T nach m aufgelöst
    m = float(np.clip(m, 1e-3, 1 - 1e-3))
    out = _mtf(x, m)
    if saturation and saturation != 1.0 and out.ndim == 3:
        lum = _gray(out)[..., None]
        out = np.clip(lum + (out - lum) * saturation, 0, 1)
    if denoise_chroma and out.ndim == 3:
        lum = _gray(out)[..., None]
        out = np.clip(lum + cv2.GaussianBlur(out - lum, (0, 0), 3.0), 0, 1)
    return out


def ghs_stretch(f, D=2.5, b=-0.5, SP=0.18, black_clip=None, saturation=1.08,
                denoise_chroma=True, samples=4096, auto_sp=True):
    """Generalised-Hyperbolic-Stretch (GHS-Familie) — frei steuerbarer High-Dynamic-Stretch,
    der schwaches Nebel-Signal kräftig anhebt, ohne den hellen Kern/Sterne auszubrennen.
    Ergänzt MTF (fester Schwarzpunkt) und asinh um eine voll parametrische Kurve.

      • D  = Intensität (Stärke der Streckung; höher = aggressiver)
      • b  = Charakter der Kurve:  b<0 weicher Knick (asinh-artig), gegen 0 sanfter,
             stärker negativ = härterer, konzentrierter Knick (hyperbolisch)
      • SP = Symmetrie-/Pivotpunkt (0..1): die Helligkeit, um die herum am stärksten gestreckt
             wird — typ. knapp über dem Himmelshintergrund.

    Konstruiert über die kumulierte lokale Streckung (Integral einer überall positiven
    Streckfunktion) → garantiert monoton, bildet [0..1] streng auf [0..1] ab, erhält Schwarz/Weiß.
    Identische Kurve je Kanal (linked, wie in Siril)."""
    g = _gray(f)
    if black_clip is not None:
        bg = float(np.quantile(g, black_clip))
    else:
        med = float(np.median(g))
        mad = float(np.median(np.abs(g - med))) * 1.4826
        bg = med + 0.25 * mad
    # Schwarzpunkt setzen UND das Signal in den aktiven Bereich der Kurve normieren (wie asinh):
    # ohne diese Normierung liegt schwaches (lineares) Nebel-Signal nahe 0 und die Kurve hebt es nicht.
    sub = np.clip(f - bg, 0, None)
    # Das schwache Nebel-Signal so normieren, dass der Sky-Anker (75. Perzentil knapp über dem Himmel)
    # genau auf den Pivot SP fällt — dort streckt die Kurve am stärksten (sonst liegt das Signal weit
    # unter SP und bleibt schwarz). Gleichzeitig nie über den Daten-Max hinaus normieren, damit helle
    # Werte den Weißpunkt erreichen ([0..1]→[0..1] bleibt erhalten; bei Astro klippen die Sterne auf 1).
    if auto_sp:
        anchor = float(np.quantile(_gray(sub), 0.75)) + 1e-9
        datamax = float(np.quantile(_gray(sub), 0.9997)) + 1e-9
        norm = min(anchor / max(float(SP), 0.02), datamax) + 1e-6
    else:
        norm = float(np.quantile(_gray(sub), 0.9997)) + 1e-6
    x0 = np.clip(sub / norm, 0, 1)

    xs = np.linspace(0.0, 1.0, samples, dtype=np.float64)
    k = float(D) * float(D)
    ls = (1.0 + k * (xs - float(SP)) ** 2) ** float(b)         # lokale Streckung, Maximum bei SP
    cdf = np.cumsum(ls)
    cdf -= cdf[0]
    cdf /= (cdf[-1] + 1e-12)                                    # → streng [0..1], monoton
    out = np.interp(x0.ravel(), xs, cdf).reshape(x0.shape).astype(np.float32)

    if out.ndim == 3:
        if denoise_chroma:
            lum = _gray(out)[..., None]
            out = np.clip(lum + cv2.GaussianBlur(out - lum, (0, 0), 3.0), 0, 1)
        if saturation and saturation != 1.0:
            lum = _gray(out)[..., None]
            out = np.clip(lum + (out - lum) * saturation, 0, 1)
    return np.clip(out, 0, 1)


def autostretch(f, black_clip=None, strength=6.0, protect_core=True, saturation=1.05,
                denoise_chroma=True):
    """asinh-Auto-Stretch fürs Anzeigen des (linearen, dunklen) Astro-Ergebnisses.

    Zurückhaltend gehalten — Ziel ist eine *echte* Bearbeitung, kein Neon-Comic:
    schwaches Signal wird sichtbar, aber der Hintergrund bleibt dunkel und das Rauschen unten.

    strength  : wie stark schwaches Signal angehoben wird (höher = heller/aggressiver).
    protect_core: helle Bereiche (Nebel-Kern, helle Sterne) werden sanfter gestreckt, damit der
                  Kern nicht zu einem flachen weißen Klecks ausbleicht — Detail/Farbe bleibt.
    saturation: leichter Farb-Boost (Astro-Farben sind nach dem Strecken oft blass).
    denoise_chroma: Farb-Rauschen glätten (Luminanz bleibt scharf) — killt den bunten Grieß im
                    Hintergrund, ohne Schärfe zu kosten.
    black_clip: optionaler fester Schwarzpunkt als Quantil. Standard (None) = **robuster
                Himmelshintergrund** (Median + 0.5·MAD), damit der Hintergrund wirklich nach
                Schwarz geht und das Rauschen nicht hochgezogen wird."""
    g = _gray(f)
    if black_clip is not None:
        bg = np.quantile(g, black_clip)
    else:
        med = float(np.median(g))
        mad = float(np.median(np.abs(g - med))) * 1.4826      # robustes Sigma
        bg = med + 0.25 * mad                                  # Schwarzpunkt knapp über dem Himmel
        #  (weicher als 0.5·MAD: zeigt schwache Nebel-Außenbereiche, Hintergrund bleibt dunkel)
    x = np.clip(f - bg, 0, None)
    # Normierung NICHT auf die hellen Sterne (quantile 0.9997) — das quetscht schwachen Nebel auf
    # ~schwarz. Stattdessen einen Sky-Anker (75. Perzentil knapp über dem Himmel) so skalieren, dass
    # er im Display auf ~0.12 (dunkles Grau) landet — datenunabhängig (geschlossene asinh-Umkehrung),
    # an echten OSC-Daten verifiziert (vorher Median 4 → jetzt ~26, wie MTF).
    anchor = float(np.quantile(_gray(x), 0.75)) + 1e-9
    T = 0.12
    norm = anchor * strength / np.sinh(T * np.arcsinh(strength)) + 1e-6
    x = x / norm
    out = np.clip(np.arcsinh(x * strength) / np.arcsinh(strength), 0, 1)
    if protect_core:
        # In den hellsten ~20 % nur sanft strecken (Kern-Schutz) und mit der starken Kurve mischen.
        gentle = np.clip(np.arcsinh(x * (strength * 0.25)) / np.arcsinh(strength * 0.25), 0, 1)
        lum = _gray(out)
        hi = np.clip((lum - 0.80) / 0.20, 0, 1)
        hi = cv2.GaussianBlur(hi, (0, 0), 2)[..., None] if hi.ndim == 2 else hi[..., None]
        out = out * (1 - hi) + gentle * hi
    if denoise_chroma and out.ndim == 3:
        # Farb-Rauschen ist niederfrequent tolerierbar: Chroma weichzeichnen, Luminanz scharf lassen.
        lum = _gray(out)[..., None]
        chroma = cv2.GaussianBlur(out - lum, (0, 0), 3.0)
        out = np.clip(lum + chroma, 0, 1)
    if saturation != 1.0 and out.ndim == 3:
        lum = _gray(out)[..., None]
        out = np.clip(lum + (out - lum) * saturation, 0, 1)
    return np.clip(out, 0, 1)
