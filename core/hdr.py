#!/usr/bin/env python3
"""
hdr.py — HDR aus Belichtungsreihen (AEB) per Exposure Fusion (Mertens).

Kein Tonemapping-Gefrickel: Die Mertens-Fusion verrechnet eine Belichtungsreihe (z. B. −1/0/+1 EV)
direkt zu EINEM gut durchgezeichneten Bild — Lichter aus den dunkleren, Schatten aus den helleren
Aufnahmen. Robust und natürlich, ganz ohne bekannte Belichtungszeiten. Optional MTB-Ausrichtung für
freihändige Reihen. Reine OpenCV/NumPy-Abhängigkeiten (MIT-kompatibel).

Wichtig: HDR (Belichtungsreihe) ≠ Fokus-Stacking (Schärfereihe) — zwei verschiedene Dinge.
"""
import numpy as np
import cv2


def _to8(img):
    """Nach 8-bit BGR (Mertens erwartet 8-bit-Bilder)."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.dtype == np.uint16:
        return (img / 256).astype(np.uint8)
    if img.dtype != np.uint8:
        return np.clip(img, 0, 255).astype(np.uint8)
    return img


def merge_exposures(images, align=True, log=print):
    """Eine Belichtungsreihe (Liste BGR-Bilder mit unterschiedlicher Belichtung) zu einem
    durchgezeichneten 8-bit-Bild verschmelzen (Mertens Exposure Fusion).
    align=True richtet freihändige Reihen vorher per MTB (Median-Threshold-Bitmap) aus."""
    if not images:
        raise ValueError("keine Bilder")
    imgs = [_to8(im) for im in images]
    if len(imgs) == 1:
        return imgs[0]
    h, w = imgs[0].shape[:2]
    imgs = [cv2.resize(im, (w, h)) if im.shape[:2] != (h, w) else im for im in imgs]
    if align:
        # 1) Feature-basiert (rigide) — fängt Verschiebung UND Drehung der Freihand-Reihe ab.
        #    Belichtungsunterschiede stören ORB kaum (Matching auf normierten Graustufen).
        try:
            import stacker
            imgs = stacker.align_images(imgs, mode="rigid", log=lambda *a: None)
            log("    HDR: Belichtungen ausgerichtet (rigide)")
        except Exception as e:
            # 2) Fallback: MTB (nur Verschiebung, belichtungs-invariant)
            try:
                cv2.createAlignMTB().process(imgs, imgs)
                log(f"    HDR: rigide Ausrichtung fehlgeschlagen ({e}) → MTB")
            except Exception as e2:
                log(f"    HDR: Ausrichtung übersprungen ({e2})")
    fused = cv2.createMergeMertens().process(imgs)      # float 0..1
    out = np.clip(fused * 255.0, 0, 255).astype(np.uint8)
    log(f"    HDR: {len(imgs)} Belichtungen verschmolzen (Exposure Fusion)")
    return out


def apply_look(bgr, preset="natural"):
    """Treuer Tonlook für HDR/Exposure-Fusion (die von Natur aus flach wirkt). Kein Erfinden von
    Inhalten — nur klassische Tonwert-/Kontrastbearbeitung im LAB-Raum:
      • Schwarzpunkt anheben (Tiefe)  • Kontrast-S-Kurve (Sigmoid, pinnt 0/1)
      • Clarity (lokaler Kontrast via großem Unsharp auf L)  • Sättigung
      • „dramatisch" zusätzlich CLAHE (adaptiver lokaler Kontrast).
    presets: neutral (aus), natural (Standard, dezent), vivid (kräftig), dramatic (stark)."""
    P = {
        "neutral":  dict(black=0.00, contrast=0.0, clarity=0.00, sat=1.00, clahe=0.0),
        "natural":  dict(black=0.015, contrast=3.0, clarity=0.18, sat=1.08, clahe=0.0),
        "vivid":    dict(black=0.030, contrast=4.5, clarity=0.32, sat=1.20, clahe=0.0),
        "dramatic": dict(black=0.045, contrast=5.5, clarity=0.45, sat=1.28, clahe=2.0),
    }
    p = P.get(preset, P["natural"])
    if preset == "neutral":
        return bgr
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0] / 255.0
    if p["black"] > 0:                                   # Schwarzpunkt → etwas Tiefe
        L = np.clip((L - p["black"]) / (1.0 - p["black"]), 0, 1)
    k = p["contrast"]
    if k > 0:                                            # Sigmoid-S-Kurve, pinnt 0 und 1
        s = lambda x: 1.0 / (1.0 + np.exp(-k * (x - 0.5)))
        s0, s1 = s(0.0), s(1.0)
        L = (s(L) - s0) / (s1 - s0)
    if p["clarity"] > 0:                                 # lokaler Kontrast (großer Radius = Halo-arm)
        sigma = max(3.0, min(L.shape[:2]) / 50.0)
        blur = cv2.GaussianBlur(L, (0, 0), sigma)
        L = np.clip(L + p["clarity"] * (L - blur), 0, 1)
    Lb = np.clip(L * 255.0, 0, 255).astype(np.uint8)
    if p["clahe"] > 0:
        Lb = cv2.createCLAHE(clipLimit=p["clahe"], tileGridSize=(8, 8)).apply(Lb)
    lab[..., 0] = Lb.astype(np.float32)
    if p["sat"] != 1.0:                                  # Sättigung über a/b-Kanäle
        lab[..., 1] = np.clip(128 + (lab[..., 1] - 128) * p["sat"], 0, 255)
        lab[..., 2] = np.clip(128 + (lab[..., 2] - 128) * p["sat"], 0, 255)
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def _exposure_time(path):
    """Belichtungszeit (Sekunden) aus EXIF, oder None."""
    try:
        import subprocess
        import json
        out = subprocess.run(["exiftool", "-j", "-n", "-ExposureTime", path],
                             capture_output=True, text=True).stdout
        return float(json.loads(out)[0].get("ExposureTime"))
    except Exception:
        return None


def split_brackets(paths, size=0, log=print):
    """Eine Dateiliste in einzelne Belichtungsreihen aufteilen.
    size>0: feste Gruppengröße (z. B. 3 für klassisches AEB).
    size=0: automatisch — neue Reihe, sobald die Belichtungszeit deutlich zurückspringt
            (Reihe startet wieder bei der kürzesten/dunkelsten Belichtung). Klappt EXIF nicht,
            wird die gesamte Liste als EINE Reihe behandelt."""
    if size and size > 0:
        groups = [paths[i:i + size] for i in range(0, len(paths), size)]
        return [g for g in groups if len(g) >= 2]
    evs = [_exposure_time(p) for p in paths]
    if any(e is None or e <= 0 for e in evs):
        return [paths]                                   # EXIF unklar → eine Reihe
    groups, cur = [], [paths[0]]
    for i in range(1, len(paths)):
        # deutlicher Sprung nach unten (lange → kurze Belichtung) = neue Reihe beginnt
        if evs[i] < evs[i - 1] * 0.5:
            groups.append(cur)
            cur = [paths[i]]
        else:
            cur.append(paths[i])
    groups.append(cur)
    groups = [g for g in groups if len(g) >= 2]
    log(f"    HDR: {len(groups)} Belichtungsreihe(n) erkannt")
    return groups or [paths]
