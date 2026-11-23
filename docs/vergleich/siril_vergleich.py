#!/usr/bin/env python3
"""ForgePix gegen Siril an denselben Lights: gleiche Rejection (Sigma 3/3), keine Nachbearbeitung,
EINE Messung für beide.

    python docs/vergleich/siril_vergleich.py <ordner-mit-fits> <neuer-arbeitsordner>

Gemessen wird
* Hintergrund und Rauschen (robust, unteres 40-%-Drittel ohne leere Ränder),
* Sterngröße als Halbfluss-Radius (HFR) der 150 hellsten ungesättigten Einzelsterne — schwellenfrei;
  die 5-Sigma-Fläche aus astro_quality wäre hier unfair, weil ein rauschärmeres Bild eine
  niedrigere Schwelle und damit scheinbar dickere Sterne bekommt,
* Rauschen der ausgerichteten Einzelbilder (zeigt, wie stark die Interpolation glättet) und die
  Stapel-Wirkung: Stapel-Rauschen × √N ÷ Einzelbild-Rauschen (1,0 = reines Mittel).

Der Startschutz unten ist Pflicht: ForgePix richtet über mehrere Prozesse aus, und unter Windows
führt jeder davon ein ungeschütztes Skript noch einmal aus (am 23.11.2026 so passiert: 8 Läufe
gleichzeitig, 778 s statt 48 s gemessen).
"""
import glob
import json
import os
import sys
import time

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HIER, "..", "..", "core"), os.path.join(HIER, "..", "..")]

import numpy as np  # noqa: E402
import cv2  # noqa: E402


def rauschen(bild):
    """Robustes Hintergrundrauschen (MAD) der Helligkeit, innerer Bildteil, leere Ränder raus."""
    b = np.asarray(bild, np.float32)
    if b.ndim == 3:
        b = b.mean(axis=-1) if b.shape[-1] in (3, 4) else b.mean(axis=0)
    h, w = b.shape
    b = b[h // 8:-h // 8, w // 8:-w // 8]
    werte = b[b > 0]
    werte = werte[werte <= np.percentile(werte, 40)]
    med = np.median(werte)
    return float(np.median(np.abs(werte - med)) * 1.4826), float(med)


def sterne_hfr(lum, hinter_med, rausch, n=150, r=8):
    from scipy.ndimage import maximum_filter
    a = lum - hinter_med
    spitzen = (a == maximum_filter(a, size=2 * r + 1)) & (a > 20 * rausch)
    ys, xs = np.nonzero(spitzen)
    h, w = a.shape
    rand = (ys > r) & (ys < h - r - 1) & (xs > r) & (xs < w - r - 1)
    ys, xs = ys[rand], xs[rand]
    hell = a[ys, xs]
    satt = np.percentile(hell, 99) if len(hell) else 0
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    rr = np.sqrt(xx ** 2 + yy ** 2)
    innen = rr <= r
    hfr, ecc = [], []
    for i in np.argsort(-hell):
        if hell[i] >= satt:
            continue
        aus = a[ys[i] - r:ys[i] + r + 1, xs[i] - r:xs[i] + r + 1]
        if (aus > 0.5 * hell[i]).sum() > 60 or aus.max() > hell[i] * 1.001:
            continue                                     # Doppelstern / Nebelknoten
        f = np.clip(aus, 0, None) * innen
        s = f.sum()
        if s <= 0:
            continue
        hfr.append(float((f * rr).sum() / s))
        cx = (f * xx).sum() / s; cy = (f * yy).sum() / s
        cov = np.cov(np.vstack([(xx - cx).ravel(), (yy - cy).ravel()]), aweights=f.ravel() + 1e-12)
        ev = np.clip(np.linalg.eigvalsh(cov), 1e-6, None)
        ecc.append(float(np.sqrt(ev.max() / ev.min())))
        if len(hfr) >= n:
            break
    return (round(float(np.median(hfr)), 3) if hfr else None,
            round(float(np.median(ecc)), 3) if ecc else None, len(hfr))


def messen(bild):
    import astro
    lum = astro._gray(np.clip(bild, 0, None)).astype(np.float32)
    mad, med = rauschen(lum)
    hfr, ecc, n = sterne_hfr(lum, med, mad)
    return {"hintergrund": round(med, 5), "rauschen": float("%.3g" % mad), "hfr_px": hfr,
            "rundheit": ecc, "sterne_gemessen": n}


def main():
    import astro
    import siril_engine
    from astropy.io import fits
    from constants import imwrite
    quelle, aus = sys.argv[1], sys.argv[2]
    if os.path.exists(aus):
        raise SystemExit("Arbeitsordner gibt es schon: %s" % aus)
    os.makedirs(aus)
    paths = sorted(glob.glob(os.path.join(quelle, "*.fit")))
    erg = {"lights": len(paths)}

    t = time.time()
    reg = astro.register_and_cache(paths, os.path.join(aus, "fp_cache"), align_mode="rotate")
    fp = astro.stack(reg, method="sigma", kappa=3.0)
    erg["forgepix_s"] = round(time.time() - t, 1)
    imwrite(os.path.join(aus, "forgepix.tif"), np.clip(fp, 0, 1).astype(np.float32))

    t = time.time()
    si_pfad = siril_engine.run_siril_astro(paths, os.path.join(aus, "siril_arbeit"), kappa=3.0,
                                           subsky=False, rmgreen=False)
    erg["siril_s"] = round(time.time() - t, 1)
    si = cv2.imread(si_pfad, cv2.IMREAD_UNCHANGED).astype(np.float32)
    if si.max() > 1.5:                                   # Siril speichert das TIFF in 16 bit
        si = si / 65535.0

    erg["forgepix"] = messen(fp)
    erg["siril"] = messen(si)

    fp_einzel = [rauschen(cv2.imread(p, cv2.IMREAD_UNCHANGED))[0] for p in reg]
    si_einzel = [rauschen(fits.getdata(p))[0] for p in
                 sorted(glob.glob(os.path.join(aus, "siril_arbeit", "siril", "r_light_*.fit")))]
    for name, einzel in (("forgepix", fp_einzel), ("siril", si_einzel)):
        e = np.array(einzel)
        erg[name]["einzelbild_rauschen"] = float("%.3g" % np.median(e))
        erg[name]["glaettung_durch_ausrichten"] = round(float(np.median(e) / e.max()), 3)
        erg[name]["stapel_wirkung"] = round(erg[name]["rauschen"] * np.sqrt(len(e)) / float(np.median(e)), 3)
    print(json.dumps(erg, indent=1, ensure_ascii=False))
    with open(os.path.join(aus, "vergleich.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(erg, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
