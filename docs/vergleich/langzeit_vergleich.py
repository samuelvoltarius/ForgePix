#!/usr/bin/env python3
"""Langzeitbelichtung aus Einzelbildern messen (core/longexp.combine).

    python docs/vergleich/langzeit_vergleich.py <video> <neuer-arbeitsordner> [anzahl=90]

1. **Treue:** Vom Stativ (Video unverändert) muss „smooth“ das reine Mittel aller Bilder sein und
   „declutter“ der reine Median — beides lässt sich exakt nachrechnen.
2. **Aus der Hand:** Das Video ist NICHT vom Stativ, sondern aus der Hand gefilmt (gemessen bis
   ~15 px Versatz) — also ein echter Freihand-Fall. Gemessen wird die Schärfe fester Felsen (zwei
   feste Ausschnitte, im Bild ausgewählt) je Ausrichtung, geteilt durch die Schärfe derselben
   Ausschnitte im mittleren Einzelbild. 1,0 = so scharf wie ein Einzelbild; darunter verwischt.
   (Erste Fassung nahm das reine Mittel als „Stativ-Wahrheit“ — das ist bei diesem Video selbst
   verwischt, und die Merkmals-Ausrichtung schien „doppelt so scharf wie die Wahrheit“.)
"""
import glob
import json
import os
import sys
import time

import cv2
import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HIER, "..", "..", "core")]


def ssim(a, b):
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    mu_a = cv2.GaussianBlur(a, (0, 0), 1.5); mu_b = cv2.GaussianBlur(b, (0, 0), 1.5)
    va = cv2.GaussianBlur(a * a, (0, 0), 1.5) - mu_a ** 2
    vb = cv2.GaussianBlur(b * b, (0, 0), 1.5) - mu_b ** 2
    cab = cv2.GaussianBlur(a * b, (0, 0), 1.5) - mu_a * mu_b
    return ((2 * mu_a * mu_b + c1) * (2 * cab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (va + vb + c2))


def grau(b):
    return cv2.cvtColor(np.asarray(b, np.float32), cv2.COLOR_BGR2GRAY)


def bilder_ziehen(video, ordner, anzahl):
    os.makedirs(ordner)
    c = cv2.VideoCapture(video)
    pfade = []
    while len(pfade) < anzahl:
        ok, f = c.read()
        if not ok:
            break
        p = os.path.join(ordner, "f_%04d.png" % len(pfade))
        cv2.imwrite(p, f)
        pfade.append(p)
    return pfade


def main():
    import longexp
    video, arbeit = sys.argv[1], sys.argv[2]
    anzahl = int(sys.argv[3]) if len(sys.argv) > 3 else 90
    if os.path.exists(arbeit):
        raise SystemExit("Arbeitsordner gibt es schon: %s" % arbeit)
    os.makedirs(arbeit)
    pfade = bilder_ziehen(video, os.path.join(arbeit, "stativ"), anzahl)
    stapel = np.stack([cv2.imread(p).astype(np.float32) / 255 for p in pfade])
    erg = {"bilder": len(pfade)}

    # 1. Treue
    for modus, wahr in (("smooth", stapel.mean(axis=0)), ("declutter", np.median(stapel, axis=0))):
        t = time.time()
        r = longexp.combine(pfade, mode=modus, align="none", work_dir=arbeit, log=lambda *a: None)
        erg["treue_" + modus] = {"max_abweichung": round(float(np.abs(r - wahr).max()), 6),
                                 "mittlere_abweichung": float("%.3g" % np.abs(r - wahr).mean()),
                                 "s": round(time.time() - t, 1)}
        print(modus, erg["treue_" + modus], flush=True)

    del stapel
    mitte = cv2.imread(pfade[len(pfade) // 2]).astype(np.float32) / 255
    # feste Felsen: oben links und unten rechts (Bild 1080x1920, hochkant)
    kaesten = [(150, 550, 20, 400), (1550, 1880, 720, 1060)]

    def schaerfe(b):
        g = grau(b)
        lap = np.abs(cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 1.0), cv2.CV_32F))
        return [float(lap[y0:y1, x0:x1].mean()) for y0, y1, x0, x1 in kaesten]

    einzel = schaerfe(mitte)
    erg["vorschlag"] = longexp.suggest_mode(pfade)
    print("Vorschlag", erg["vorschlag"]["mode"], erg["vorschlag"]["align"], flush=True)
    for align in ("none", "shift", "feature"):
        t0 = time.time()
        try:
            r = longexp.combine(pfade, mode="smooth", align=align, work_dir=arbeit, log=lambda *a: None)
        except Exception as e:
            erg["hand_" + align] = {"fehler": "%s: %s" % (type(e).__name__, str(e)[:200])}
            print(align, erg["hand_" + align], flush=True)
            continue
        s = schaerfe(r)
        erg["hand_" + align] = {"felsen_schaerfe_rel": [round(x / e, 3) for x, e in zip(s, einzel)],
                                "s": round(time.time() - t0, 1)}
        print(align, erg["hand_" + align], flush=True)
    with open(os.path.join(arbeit, "langzeit_vergleich.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(erg, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
