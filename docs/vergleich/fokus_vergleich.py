#!/usr/bin/env python3
"""Fokus-Stacking messen: jede ForgePix-Methode gegen die schärfste Einzelaufnahme je Kachel und
gegen ein Referenz-Ergebnis (z. B. `expected.jpg` von focus-stack).

    python docs/vergleich/fokus_vergleich.py <ordner-mit-fokusreihe> <neuer-arbeitsordner> [referenz.jpg]

Kennzahlen
* **Schärfe-Ausbeute** je 64-px-Kachel: Schärfe des Ergebnisses ÷ Schärfe der schärfsten
  Einzelaufnahme an derselben Stelle (Einzelaufnahmen auf das Ergebnis ausgerichtet). 1,0 = so
  scharf wie das beste Einzelbild. Gezählt nur Kacheln mit Struktur (das schärfste Einzelbild
  über dem 25-%-Perzentil), sonst entscheidet das Rauschen glatter Flächen.
  Median und Anteil der Kacheln unter 0,8 (dort ist der Fokus verpasst).
  **Über 1,0 ist nicht besser**: das sind Halos, Säume oder verstärktes Rauschen.
* **Ähnlichkeit zur Referenz** (mittleres SSIM der Helligkeit, nach Ausrichtung), falls eine da ist.
* Zeit.

Schärfe = Varianz des Laplace-Filters nach leichter Glättung (σ 1), auf der Helligkeit.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.abspath(os.path.join(HIER, "..", ".."))
METHODEN = ["pyramid", "depthmap", "average", "halofix", "pyramid-consistent", "wavelet"]


def grau(b):
    return cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32) / (65535.0 if b.dtype == np.uint16 else 255.0)


_SIFT = None


def ausrichten(bild, ziel, min_korr=0.6):
    """`bild` per SIFT-Merkmalen + Homographie auf `ziel` legen (das Ergebnis eines Stapels ist
    oft ZUGESCHNITTEN — erste Fassung stauchte die Einzelbilder auf seine Größe und verglich
    danach falsche Stellen: Korrelation 0,5). None, wenn die Ausrichtung nicht trägt
    (Korrelation nach dem Verschieben unter `min_korr`) — dann zählt das Bild nicht mit. Die
    Grenze ist bewusst niedrig: ein unscharfes Einzelbild ähnelt dem scharfen Ergebnis von
    Natur aus weniger (gemessen 0,76 gegen 0,95), und es soll trotzdem mitzählen."""
    global _SIFT
    if _SIFT is None:
        _SIFT = cv2.SIFT_create(4000)
    g8 = lambda b: (np.clip(grau(b), 0, 1) * 255).astype(np.uint8)
    ka, da = _SIFT.detectAndCompute(g8(bild), None)
    kz, dz = _SIFT.detectAndCompute(g8(ziel), None)
    if da is None or dz is None:
        return None
    paare = cv2.BFMatcher().knnMatch(da, dz, k=2)
    gut = [m for m, n2 in (p for p in paare if len(p) == 2) if m.distance < 0.75 * n2.distance]
    if len(gut) < 30:
        return None
    src = np.float32([ka[m.queryIdx].pt for m in gut]); dst = np.float32([kz[m.trainIdx].pt for m in gut])
    M, _ = cv2.findHomography(src, dst, cv2.RANSAC, 2.0)
    if M is None:
        return None
    aus = cv2.warpPerspective(bild, M, (ziel.shape[1], ziel.shape[0]),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    a, z = grau(aus), grau(ziel)
    h, w = z.shape
    korr = float(np.corrcoef(a[h // 10:-h // 10, w // 10:-w // 10].ravel(),
                             z[h // 10:-h // 10, w // 10:-w // 10].ravel())[0, 1])
    return aus if korr >= min_korr else None


def schaerfe_kacheln(g, k=64):
    lap = cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 1.0), cv2.CV_32F)
    h, w = g.shape
    ny, nx = h // k, w // k
    lap = lap[:ny * k, :nx * k].reshape(ny, k, nx, k)
    return lap.var(axis=(1, 3))


def ssim(a, b):
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    mu_a = cv2.GaussianBlur(a, (0, 0), 1.5); mu_b = cv2.GaussianBlur(b, (0, 0), 1.5)
    va = cv2.GaussianBlur(a * a, (0, 0), 1.5) - mu_a ** 2
    vb = cv2.GaussianBlur(b * b, (0, 0), 1.5) - mu_b ** 2
    cab = cv2.GaussianBlur(a * b, (0, 0), 1.5) - mu_a * mu_b
    s = ((2 * mu_a * mu_b + c1) * (2 * cab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (va + vb + c2))
    h, w = s.shape
    return float(s[h // 20:-h // 20, w // 20:-w // 20].mean())   # Ränder (Ausrichtung) raus


def messen(ergebnis, eingaben, referenz=None):
    eg = grau(ergebnis)
    e_s = schaerfe_kacheln(eg)
    beste = None
    uebersprungen = 0
    for b in eingaben:
        a = ausrichten(b, ergebnis)
        if a is None:
            uebersprungen += 1
            continue
        s = schaerfe_kacheln(grau(a))
        beste = s if beste is None else np.maximum(beste, s)
    rand = 1                                              # Randkacheln: Ausrichtungssäume
    e_s = e_s[rand:-rand, rand:-rand]; beste = beste[rand:-rand, rand:-rand]
    struktur = beste > np.percentile(beste, 25)
    q = (e_s / np.maximum(beste, 1e-12))[struktur]
    aus = {"ausbeute_median": round(float(np.median(q)), 3),
           "kacheln_unter_0_8_%": round(100 * float((q < 0.8).mean()), 1),
           "kacheln_ueber_1_3_%": round(100 * float((q > 1.3).mean()), 1),
           "einzelbilder_nicht_ausrichtbar": uebersprungen}
    if referenz is not None:
        r = ausrichten(referenz, ergebnis)
        aus["ssim_zur_referenz"] = None if r is None else round(ssim(eg, grau(r)), 4)
    return aus


def main():
    quelle, arbeit = sys.argv[1], sys.argv[2]
    ref_pfad = sys.argv[3] if len(sys.argv) > 3 else None
    if os.path.exists(arbeit):
        raise SystemExit("Arbeitsordner gibt es schon: %s" % arbeit)
    eingang = os.path.join(arbeit, "eingang")
    os.makedirs(eingang)
    bilder = sorted(p for p in glob.glob(os.path.join(quelle, "*"))
                    if p.lower().endswith((".jpg", ".jpeg", ".tif", ".tiff", ".png"))
                    and (ref_pfad is None or os.path.abspath(p) != os.path.abspath(ref_pfad)))
    for p in bilder:
        shutil.copy2(p, eingang)
    eingaben = [cv2.imread(p, cv2.IMREAD_UNCHANGED) for p in bilder]
    referenz = cv2.imread(ref_pfad) if ref_pfad else None
    erg = {"bilder": len(bilder), "methoden": {}}
    if referenz is not None:
        erg["referenz"] = messen(referenz, eingaben)
        print("Referenz", erg["referenz"], flush=True)
    for m in METHODEN:
        work = os.path.join(arbeit, m)
        t = time.time()
        lauf = subprocess.run([sys.executable, os.path.join(WURZEL, "core", "focus_cull_stack.py"),
                               "--input", eingang, "--work", work, "--focus-method", m],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL)
        dauer = round(time.time() - t, 1)
        stapel = sorted(glob.glob(os.path.join(work, "stack", "*")))
        if lauf.returncode != 0 or not stapel:
            erg["methoden"][m] = {"fehler": (lauf.stderr or lauf.stdout)[-400:], "s": dauer}
            print(m, "FEHLER", erg["methoden"][m]["fehler"], flush=True)
            continue
        e = messen(cv2.imread(stapel[0], cv2.IMREAD_UNCHANGED), eingaben, referenz)
        e["s"] = dauer
        erg["methoden"][m] = e
        print(m, e, flush=True)
    with open(os.path.join(arbeit, "fokus_vergleich.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(erg, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
