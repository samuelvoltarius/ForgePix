#!/usr/bin/env python3
"""Farbtreue der RAW-Entwicklung an einer Farbkarte (ColorChecker Classic) messen.

    python docs/vergleich/farbkarte_vergleich.py <raw> x1,y1 x6,y6 x19,y19 x24,y24 [halbe_breite]

Die vier Punkte sind die Mitten der Eckfelder 1 (dunkle Haut), 6 (blaugrün), 19 (weiß) und
24 (schwarz) im eingebetteten KAMERABILD (Vorschau) der Datei; für jede Entwicklung werden sie
über SIFT-Merkmale und eine Homographie übertragen (Entwicklungen haben andere Größe und
Ränder). Gemessen wird ΔE2000 gegen die X-Rite-Sollwerte, nach Angleichen der Belichtung über
Neutral 8 — einmal wie aufgenommen, einmal nach einem Weißabgleich über die Graufelder.

Für die Testdatei testdata/raw/Fujifilm/X-T4__DSCF0268.RAF:
    2240,2001 2226,985 2848,1999 2845,980 45
"""
import os
import sys

import cv2
import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HIER, "..", "..", "core")]


def homographie(von, nach):
    sift = cv2.SIFT_create(6000)
    g = lambda b: cv2.cvtColor((b / (65535.0 if b.dtype == np.uint16 else 255.0) * 255).astype(np.uint8),
                               cv2.COLOR_BGR2GRAY)
    k1, d1 = sift.detectAndCompute(g(von), None)
    k2, d2 = sift.detectAndCompute(g(nach), None)
    paare = cv2.BFMatcher().knnMatch(d1, d2, k=2)
    gut = [m for m, n in (p for p in paare if len(p) == 2) if m.distance < 0.7 * n.distance]
    H, _ = cv2.findHomography(np.float32([k1[m.queryIdx].pt for m in gut]),
                              np.float32([k2[m.trainIdx].pt for m in gut]), cv2.RANSAC, 2.0)
    return H


def main():
    import farbkarte as FK
    import focus_cull_stack as F
    import kameralook
    roh = sys.argv[1]
    ecken = [tuple(float(v) for v in a.split(",")) for a in sys.argv[2:6]]
    halb = float(sys.argv[6]) if len(sys.argv) > 6 else 40
    vorschau = kameralook.vorschau(roh)
    mitten_v = FK.feldmitten(*ecken)
    wege = {"Kamera-JPEG (eingebettet)": vorschau,
            "ForgePix neutral": F.develop_raw_to_bgr(roh, look="neutral"),
            "ForgePix wie die Kamera": F.develop_raw_to_bgr(roh, look="kamera")}
    for name, bild in wege.items():
        if bild is vorschau:
            mitten, h = mitten_v, halb
        else:
            H = homographie(vorschau, bild)
            mitten = cv2.perspectiveTransform(mitten_v[None].astype(np.float32), H)[0]
            h = halb * bild.shape[1] / vorschau.shape[1]
        rgb = FK.felder_messen(bild, mitten, h)
        wie = FK.bewerten(rgb)
        # Weißabgleich über die Graufelder (je Kanal ein Faktor), dann erneut
        lin = FK.srgb_linear(rgb)
        soll = FK.soll_srgb_linear()
        f = (soll[FK.NEUTRAL].sum(0) / lin[FK.NEUTRAL].sum(0))
        wb = FK.bewerten(FK.linear_srgb(np.clip(lin * f / f[1], 0, 1)))
        M = FK.kalibrierung_berechnen(rgb)
        kal = FK.bewerten(FK.linear_srgb(np.clip(FK.srgb_linear(rgb) @ M.T, 0, 1)), belichtung_angleichen=False)
        print("%-28s ΔE2000 wie aufgenommen: Mittel %.2f (bunt %.2f, grau %.2f, max %.2f) | "
              "nach Grau-Weißabgleich: %.2f (max %.2f) | mit Kalibrier-Matrix: %.2f (max %.2f)"
              % (name, wie["mittel"], wie["bunt_mittel"], wie["grau_mittel"], wie["max"],
                 wb["mittel"], wb["max"], kal["mittel"], kal["max"]), flush=True)


if __name__ == "__main__":
    main()
