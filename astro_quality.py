#!/usr/bin/env python3
"""
astro_quality.py — Sub-Bewertung für Astro (klassische Bildverarbeitung, erklärbar).

Misst pro Light-Frame: Sternzahl, FWHM (Schärfe), Elongation (Guidingfehler),
Hintergrund (Wolken/Mond/Lichtverschmutzung), Satellitenspuren. Daraus ein Score +
menschenlesbare Begründungen → schlechte Subs werden aussortiert.

Kein KI-Modell, kein GPU — nur OpenCV/NumPy. Genau die Probleme, die sich klassisch
gut lösen lassen (Satelliten, Wolken, Guiding, FWHM, Sternklassifikation).
"""
import os
import numpy as np
import cv2

from constants import RAW_EXTS


def _read_gray(path, max_side=1600):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fit", ".fits", ".fts"):
        from astropy.io import fits
        d = np.asarray(fits.getdata(path)).astype(np.float32)
        if d.ndim == 3:
            d = d[0] if d.shape[0] in (3, 4) else d.mean(axis=2)
        mx = float(np.nanmax(d)) or 1.0
        g = np.nan_to_num(d / mx * 255.0)
    elif ext in RAW_EXTS:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(output_bps=8, use_camera_wb=True, no_auto_bright=True, half_size=True)
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    else:
        g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if g is None:
        return None
    if g.dtype == np.uint16:
        g = (g / 256).astype(np.uint8)
    s = max(g.shape)
    if s > max_side:
        f = max_side / s
        g = cv2.resize(g, (int(g.shape[1] * f), int(g.shape[0] * f)), interpolation=cv2.INTER_AREA)
    return g.astype(np.float32)


def detect_stars(gray, max_stars=120):
    """Sterne als helle Blobs finden; pro Stern Größe (FWHM) und Elongation via
    Pixel-Kovarianz (echte Hauptachsen, erkennt auch diagonales Trailing)."""
    bg = float(np.median(gray))
    sigma = float(np.std(gray)) + 1e-6
    mask = (gray > bg + 5 * sigma).astype(np.uint8)
    n, labels, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    order = np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1  # größte zuerst
    stars = []
    for i in order[:max_stars]:
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < 3 or area > 800:
            continue
        ys, xs = np.where(labels == i)
        if len(xs) < 3:
            continue
        cov = np.cov(np.vstack([xs.astype(np.float32), ys.astype(np.float32)]))
        ev = np.linalg.eigvalsh(cov) if cov.ndim == 2 else np.array([area, area])
        ev = np.clip(ev, 1e-3, None)
        major, minor = float(ev.max()), float(ev.min())
        fwhm = 2.3548 * np.sqrt((major + minor) / 2.0)   # näherungsweise FWHM
        ecc = np.sqrt(major / minor)                      # 1.0 = rund, >1.5 = länglich
        stars.append((fwhm, ecc, area))
    return stars, bg


def detect_trail(gray):
    """Satelliten-/Flugzeugspur: lange dünne Linie im Bild (Hough)."""
    bg = float(np.median(gray)); sigma = float(np.std(gray)) + 1e-6
    mask = (gray > bg + 4 * sigma).astype(np.uint8) * 255
    lines = cv2.HoughLinesP(mask, 1, np.pi / 180, threshold=60,
                            minLineLength=int(0.30 * max(gray.shape)), maxLineGap=8)
    return lines is not None and len(lines) > 0


def analyze_frame(path):
    g = _read_gray(path)
    if g is None:
        return {"name": os.path.basename(path), "ok": False, "reasons": ["nicht lesbar"]}
    stars, bg = detect_stars(g)
    n = len(stars)
    fwhm = float(np.median([s[0] for s in stars])) if stars else 99.0
    ecc = float(np.median([s[1] for s in stars])) if stars else 9.0
    trail = detect_trail(g)
    return {"name": os.path.basename(path), "path": path, "stars": n,
            "fwhm": fwhm, "ecc": ecc, "bg": bg / 255.0, "trail": trail,
            "ok": True, "reasons": []}


def select_subs(paths, fwhm_factor=1.5, ecc_max=1.7, star_frac=0.5, bg_factor=1.6, log=print):
    """Alle Frames bewerten und schlechte aussortieren — mit Begründung je Frame.
    Schwellen relativ zum Median der Serie (robust gegen unterschiedliche Setups)."""
    frames = [analyze_frame(p) for p in paths]
    good = [f for f in frames if f["ok"]]
    if not good:
        return frames, [f["path"] for f in frames if f.get("path")]
    med_stars = float(np.median([f["stars"] for f in good]))
    med_fwhm = float(np.median([f["fwhm"] for f in good]))
    med_bg = float(np.median([f["bg"] for f in good]))
    kept = []
    for f in frames:
        if not f["ok"]:
            continue
        r = f["reasons"]
        if f["trail"]:
            r.append("Satelliten-/Flugzeugspur")
        if med_stars > 0 and f["stars"] < star_frac * med_stars:
            r.append(f"wenige Sterne ({f['stars']} vs. Median {med_stars:.0f}) — Wolken/Dunst?")
        if f["fwhm"] > fwhm_factor * med_fwhm:
            r.append(f"unscharf (FWHM {f['fwhm']:.1f} vs. {med_fwhm:.1f})")
        if f["ecc"] > ecc_max:
            r.append(f"längliche Sterne (Elongation {f['ecc']:.2f}) — Guidingfehler")
        if f["bg"] > bg_factor * med_bg:
            r.append(f"heller Hintergrund — Wolken/Mond/Lichtverschmutzung")
        f["keep"] = len(r) == 0
        log(f"  {f['name']}: Sterne={f['stars']} FWHM={f['fwhm']:.1f} "
            f"Elong={f['ecc']:.2f} BG={f['bg']:.3f} {'✓' if f['keep'] else '✗ ' + '; '.join(r)}")
        if f["keep"]:
            kept.append(f["path"])
    log(f"  -> {len(kept)}/{len(good)} Subs behalten")
    return frames, kept
