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

from constants import RAW_EXTS

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


def _read_float(path):
    """Bild als float32 [0..1] (BGR) lesen — TIFF/PNG/JPG/FITS; RAW via rawpy."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fit", ".fits", ".fts"):
        from astropy.io import fits
        with fits.open(path) as hdul:
            hdu = hdul[0]
            d = np.asarray(hdu.data).astype(np.float32)
            bayer = str(hdu.header.get("BAYERPAT", "")).strip().upper()
        if d.ndim == 3 and d.shape[0] in (3, 4):     # (C,H,W) -> (H,W,C)
            d = np.moveaxis(d[:3], 0, -1)
        # OSC-Kameras (z. B. Seestar/ASI) liefern Bayer-Rohdaten als 2D-FITS -> debayern = Farbe.
        # BAYERPAT aus dem Header, sonst SELBST erkennen (gegen Dateien ohne Header-Eintrag).
        if d.ndim == 2:
            if bayer not in _BAYER2CV:
                bayer = detect_bayer(d)
            if bayer in _BAYER2CV:
                mx = float(np.nanmax(d)) or 1.0
                raw16 = np.clip(np.nan_to_num(d) / mx * 65535.0, 0, 65535).astype(np.uint16)
                bgr = cv2.cvtColor(raw16, _BAYER2CV[bayer])      # -> BGR (Farbe!)
                return bgr.astype(np.float32) / 65535.0
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
        if img is None:
            raise RuntimeError(f"Bild nicht lesbar: {path}")
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
    if not paths:
        raise RuntimeError("keine Frames zum Stacken")
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


def dualband_hoo(bgr, unmix=0.20):
    """Dual-Band-OSC (Hα+OIII) SAUBER in zwei Signale trennen und als HOO neu kombinieren.

    Übersprechen beim OSC-Sensor: Hα (656 nm) trifft v. a. Rot, leckt etwas in Grün; OIII (500 nm)
    trifft Grün+Blau, leckt etwas in Rot. Darum:
      - Hα  = Rot-Kanal (sieht fast nur Hα),
      - OIII = Blau-Kanal (sauberstes OIII; Grün ist am stärksten Hα-kontaminiert → nicht nehmen),
      - Hintergrund pro Kanal abziehen (sauberes Signal über 0),
      - leichte lineare ENTMISCHUNG (Hα := Hα − k·OIII, OIII := OIII − k·Hα) gegen Restkreuztalk,
      - beide einzeln normalisieren, dann Rot=Hα, Grün+Blau=OIII → klar zwei Töne (rot + teal).
    Treu: nur Kanal-Trennung/-Skalierung, nichts erfunden."""
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    f = bgr.astype(np.float32)
    b, _, r = f[..., 0], f[..., 1], f[..., 2]

    def _sub_bg(x):
        return np.clip(x - float(np.quantile(x, 0.30)), 0, None)   # Himmelshintergrund weg

    ha, oiii = _sub_bg(r), _sub_bg(b)
    ha2 = np.clip(ha - unmix * oiii, 0, None)     # Restkreuztalk rausrechnen
    oiii2 = np.clip(oiii - unmix * ha, 0, None)

    def _norm(x):
        hi = float(np.quantile(x, 0.999))
        return np.clip(x / max(hi, 1e-6), 0, 1)

    ha_n, oiii_n = _norm(ha2), _norm(oiii2)
    out = np.zeros_like(f)
    out[..., 2] = ha_n                          # R = Hα (rot)
    out[..., 1] = oiii_n                        # G = OIII
    out[..., 0] = oiii_n                        # B = OIII  → G+B = teal
    return out


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
    out = np.clip(src - bg.reshape(1, 1, 3), 0, None)          # Hintergrund neutral
    hi = np.array([np.quantile(out[..., c], 0.995) for c in range(3)], np.float32)
    scale = np.clip(hi.mean() / np.clip(hi, 1e-6, None), 0.4, 2.5).astype(np.float32)
    out = np.clip(out * scale.reshape(1, 1, 3), 0, None)        # Sterne ~neutral -> echte Farben
    s = float(min(1.0, max(0.0, strength)))
    return out if s >= 1.0 else np.clip(src * (1 - s) + out * s, 0, None)


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


def autostretch(f, black_clip=0.0008, strength=14.0, protect_core=True, saturation=1.25):
    """asinh-Auto-Stretch fürs Anzeigen des (linearen, dunklen) Astro-Ergebnisses.

    strength  : wie stark schwaches Signal angehoben wird (höher = heller/aggressiver).
    protect_core: helle Bereiche (Nebel-Kern, helle Sterne) werden sanfter gestreckt, damit der
                  Kern nicht zu einem flachen weißen Klecks ausbleicht — Detail/Farbe bleibt.
    saturation: leichter Farb-Boost (Astro-Farben sind nach dem Strecken oft blass)."""
    g = _gray(f)
    bg = np.quantile(g, black_clip)
    x = np.clip(f - bg, 0, None)
    norm = np.quantile(_gray(x), 0.9995) + 1e-6
    x = x / norm
    out = np.clip(np.arcsinh(x * strength) / np.arcsinh(strength), 0, 1)
    if protect_core:
        # In den hellsten ~15 % nur sanft strecken (Kern-Schutz) und mit der starken Kurve mischen.
        gentle = np.clip(np.arcsinh(x * (strength * 0.2)) / np.arcsinh(strength * 0.2), 0, 1)
        lum = _gray(out)
        hi = np.clip((lum - 0.85) / 0.15, 0, 1)
        hi = cv2.GaussianBlur(hi, (0, 0), 2)[..., None] if hi.ndim == 2 else hi[..., None]
        out = out * (1 - hi) + gentle * hi
    if saturation != 1.0 and out.ndim == 3:
        lum = _gray(out)[..., None]
        out = np.clip(lum + (out - lum) * saturation, 0, 1)
    return np.clip(out, 0, 1)
