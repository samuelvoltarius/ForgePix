#!/usr/bin/env python3
"""
astro.py — Astro-Stacking-Modul für StackForge (Siril-inspiriert, eigenständig).

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

from constants import RAW_EXTS


def _read_float(path):
    """Bild als float32 [0..1] (BGR) lesen — TIFF/PNG/JPG/FITS; RAW via rawpy."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fit", ".fits", ".fts"):
        from astropy.io import fits
        d = np.asarray(fits.getdata(path)).astype(np.float32)
        if d.ndim == 3 and d.shape[0] in (3, 4):     # (C,H,W) -> (H,W,C)
            d = np.moveaxis(d[:3], 0, -1)
        mx = float(np.nanmax(d)) if d.size else 1.0
        f = d / mx if mx > 1.5 else np.clip(d, 0, 1)  # ADU -> 0..1
        if f.ndim == 2:
            f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
        elif f.shape[2] == 3:
            f = cv2.cvtColor(f, cv2.COLOR_RGB2BGR)    # FITS = RGB -> BGR
        return np.nan_to_num(f)
    if ext in RAW_EXTS:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(output_bps=16, use_camera_wb=True, no_auto_bright=True,
                                  output_color=rawpy.ColorSpace.sRGB)
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR); maxv = 65535.0
    else:
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        maxv = 65535.0 if img.dtype == np.uint16 else 255.0
    f = img.astype(np.float32) / maxv
    if f.ndim == 2:
        f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
    return f


def _master(paths):
    """Master-Frame (Median) aus mehreren Kalibrier-Frames, oder einzelnes Frame."""
    if isinstance(paths, str):
        return _read_float(paths)
    fs = [_read_float(p) for p in paths]
    return np.median(np.stack(fs), axis=0)


def calibrate(f, dark=None, flat=None):
    out = f
    if dark is not None:
        out = out - dark
    if flat is not None:
        fn = flat / (float(flat.mean()) + 1e-6)
        out = out / np.clip(fn, 0.2, None)
    return np.clip(out, 0, None)


def _gray(f):
    return f.mean(axis=2).astype(np.float32) if f.ndim == 3 else f.astype(np.float32)


def cosmetic_correct(f, strength=3.0):
    """Hot-/Cold-Pixel entfernen (kosmetische Korrektur): einzelne Ausreißer ggü. dem lokalen
    Median ersetzen. Beseitigt helle/dunkle Einzelpixel (Sensor-Defekte/Cosmics) ohne Sterne
    anzutasten. Klassisch, kein ML."""
    u16 = (np.clip(f, 0, 1) * 65535).astype(np.uint16)
    med = cv2.medianBlur(u16, 3).astype(np.float32) / 65535.0
    diff = f - med
    sigma = float(np.std(diff)) + 1e-6
    mask = np.abs(diff) > strength * sigma
    out = f.copy()
    out[mask] = med[mask]
    return out


def _estimate_rotation(refg, img_g, detector="ORB"):
    """Partielle Affine (Translation + Rotation, kein Scherung) per Stern-Merkmalen schätzen.
    Für Alt-Az-Montierungen mit Feldrotation. Gibt 2x3-Matrix oder None (Fallback Translation)."""
    a = (np.clip(refg, 0, 1) * 255).astype(np.uint8)
    b = (np.clip(img_g, 0, 1) * 255).astype(np.uint8)
    det = cv2.ORB_create(4000)
    ka, da = det.detectAndCompute(a, None)
    kb, db = det.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return None
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    m = sorted(bf.match(da, db), key=lambda x: x.distance)[:200]
    if len(m) < 8:
        return None
    src = np.float32([kb[x.trainIdx].pt for x in m]).reshape(-1, 1, 2)
    dst = np.float32([ka[x.queryIdx].pt for x in m]).reshape(-1, 1, 2)
    M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    return M


def register_and_cache(paths, out_dir, dark=None, flat=None, do_register=True,
                       align_mode="shift", cosmetic=False, drizzle=1, detector="ORB", log=print):
    """Frames kalibrieren + ausrichten, als 16-bit-TIFF in out_dir ablegen.

    align_mode: 'shift' = Phasenkorrelation (nur Translation, schnell, Nachführung) ·
                'rotate' = Stern-Merkmale (Translation + Feldrotation, für Alt-Az).
    cosmetic:   Hot-/Cold-Pixel vor dem Ausrichten entfernen.
    drizzle:    Ausgabe-Hochskalierung (1 = aus, 2 = doppelte Kantenlänge) — feineres Sampling
                bei unterabgetasteten Daten („Drizzle-lite": Hochskalieren + Integrieren, keine
                echte Pixel-Fraktion wie PixInsight/DrizzleIntegration).
    Gibt die Liste der ausgerichteten Pfade zurück."""
    os.makedirs(out_dir, exist_ok=True)
    drizzle = max(1, int(drizzle))
    ref = calibrate(_read_float(paths[len(paths) // 2]), dark, flat)
    if cosmetic:
        ref = cosmetic_correct(ref)
    refg = _gray(ref)
    win = cv2.createHanningWindow((refg.shape[1], refg.shape[0]), cv2.CV_32F)
    out_size = (ref.shape[1] * drizzle, ref.shape[0] * drizzle)
    aligned = []
    for i, p in enumerate(paths):
        f = calibrate(_read_float(p), dark, flat)
        if f.shape[:2] != ref.shape[:2]:
            f = cv2.resize(f, (ref.shape[1], ref.shape[0]))
        if cosmetic:
            f = cosmetic_correct(f)
        if do_register:
            M = None
            if align_mode == "rotate":
                M = _estimate_rotation(refg, _gray(f), detector)
                if M is not None and drizzle > 1:
                    M = M.copy(); M[:, 2] *= drizzle  # Translation auf Zielraster skalieren
            if M is None:  # Fallback / 'shift': Phasenkorrelation (Translation)
                (dx, dy), _resp = cv2.phaseCorrelate(refg * win, _gray(f) * win)
                M = np.float32([[1, 0, dx * drizzle], [0, 1, dy * drizzle]])
            elif align_mode != "rotate":
                M[:, 2] *= drizzle
            f = cv2.warpAffine(f, M, out_size,
                               flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
        elif drizzle > 1:
            f = cv2.resize(f, out_size, interpolation=cv2.INTER_LANCZOS4)
        op = os.path.join(out_dir, f"reg_{i:04d}.tif")
        cv2.imwrite(op, np.clip(f * 65535, 0, 65535).astype(np.uint16),
                    [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
        aligned.append(op)
        log(f"    registriert {i + 1}/{len(paths)}")
    return aligned


def stack(paths, method="sigma", kappa=2.5, normalize=True, log=print):
    """Speicherschonendes Stacken über die Platte (zweistufig bei sigma/winsor).
    Gibt float32-Ergebnis [0..1] (BGR) zurück."""
    n = len(paths)
    first = _read_float(paths[0])
    shape = first.shape

    # additive Normalisierung: Hintergrund (Median) je Frame angleichen
    offs = np.zeros(n, np.float32)
    if normalize:
        meds = [float(np.median(_read_float(p))) for p in paths]
        gm = float(np.median(meds))
        offs = np.array([gm - m for m in meds], np.float32)

    if method in ("average", "median", "max"):
        if method == "median":
            # Median braucht alle Werte -> in Kacheln über die Höhe, speicherschonend
            res = np.empty(shape, np.float32)
            rows = max(1, 2_000_000 // (shape[1] * shape[2]))  # ~Zeilen pro Kachel
            for y in range(0, shape[0], rows):
                band = np.stack([_read_float(p)[y:y + rows] + offs[i]
                                 for i, p in enumerate(paths)])
                res[y:y + rows] = np.median(band, axis=0)
                log(f"    median Zeilen {y}/{shape[0]}")
            return np.clip(res, 0, 1)
        acc = np.zeros(shape, np.float32) if method == "average" else None
        mx = np.zeros(shape, np.float32) if method == "max" else None
        for i, p in enumerate(paths):
            f = _read_float(p) + offs[i]
            if method == "average":
                acc += f
            else:
                mx = np.maximum(mx, f)
            log(f"    {method} {i + 1}/{n}")
        return np.clip(acc / n if method == "average" else mx, 0, 1)

    # sigma / winsor: Pass 1 Mittel+Std, Pass 2 Rejection
    s = np.zeros(shape, np.float32); s2 = np.zeros(shape, np.float32)
    for i, p in enumerate(paths):
        f = _read_float(p) + offs[i]
        s += f; s2 += f * f
        log(f"    Statistik {i + 1}/{n}")
    mean = s / n
    std = np.sqrt(np.maximum(s2 / n - mean * mean, 0))
    lo = mean - kappa * std; hi = mean + kappa * std
    acc = np.zeros(shape, np.float32); cnt = np.zeros(shape, np.float32)
    for i, p in enumerate(paths):
        f = _read_float(p) + offs[i]
        if method == "winsor":
            f = np.clip(f, lo, hi)
            acc += f; cnt += 1
        else:  # sigma: Ausreißer verwerfen
            m = (f >= lo) & (f <= hi)
            acc += np.where(m, f, 0); cnt += m
        log(f"    {method}-Rejection {i + 1}/{n}")
    return np.clip(acc / np.clip(cnt, 1, None), 0, 1)


def background_extract(f, strength=0.12):
    """Klassische Hintergrund-/Gradienten-Entfernung (Lichtverschmutzung, Vignette).
    Modelliert den glatten Hintergrund (sternunterdrückt + stark geglättet) und zieht ihn ab.
    Kein KI-Tool wie GraXpert, aber wirksam gegen weiche Gradienten."""
    u16 = (np.clip(f, 0, 1) * 65535).astype(np.uint16)
    star_suppressed = cv2.medianBlur(u16, 5).astype(np.float32) / 65535.0
    sigma = max(8.0, min(f.shape[0], f.shape[1]) * strength / 3.0)
    bg = cv2.GaussianBlur(star_suppressed, (0, 0), sigma)
    out = f - bg + float(np.median(bg))
    return np.clip(out, 0, 1)


def autostretch(f, black_clip=0.001):
    """asinh-Stretch fürs Anzeigen des (linearen, dunklen) Astro-Ergebnisses."""
    g = _gray(f)
    bg = np.quantile(g, black_clip)
    x = np.clip(f - bg, 0, None)
    x = x / (np.quantile(x, 0.9995) + 1e-6)
    out = np.arcsinh(x * 10.0) / np.arcsinh(10.0)
    return np.clip(out, 0, 1)
