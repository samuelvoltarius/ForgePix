#!/usr/bin/env python3
"""
core/farbkarte.py — Farbtreue an einer Farbkarte (X-Rite ColorChecker Classic, 24 Felder) messen
und daraus eine Farbkalibrierung rechnen (wie „Kalibrierung“ in Camera Raw bzw. ein
ColorChecker-Profil in Lightroom).

* Sollwerte: X-Rite ColorChecker24 „After November 2014“, xyY unter D50, übernommen aus den
  Referenzdaten von colour-science (BSD-3) — dort mit Quelle X-Rite. Nur Messwerte, kein Code.
* Farbabstand: CIEDE2000 (Sharma, Wu, Dalal 2005), hier selbst gerechnet; geprüft an den
  Testpaaren aus dieser Veröffentlichung (tests/test_farbkarte.py).
* Lage der Felder: `finden` sucht die Karte selbst (quadratische Felder im 4x6-Raster, Drehung
  über die Farben bestimmt); von Hand über die Mitten der vier Eckfelder 1 (dunkle Haut),
  6 (blaugrün), 19 (weiß) und 24 (schwarz) — so ist egal, wie die Karte im Bild liegt.
* Kalibrierung: 3x3-Matrix in linearem sRGB (kleinste Quadrate über die 24 Felder).

Kein Qt.
"""
import os

import numpy as np

NAMEN_XYY_D50 = [
    ("dunkle Haut", 0.43748360, 0.37852284, 0.09832436),
    ("helle Haut", 0.42224944, 0.37249369, 0.33620230),
    ("Himmelblau", 0.27614744, 0.29838157, 0.17855193),
    ("Blattgrün", 0.37331613, 0.45116914, 0.13467927),
    ("Blaue Blüte", 0.30289052, 0.28628691, 0.22871760),
    ("Blaugrün", 0.28640483, 0.38971778, 0.41435547),
    ("Orange", 0.52814772, 0.40533497, 0.31264162),
    ("Purpurblau", 0.23238585, 0.21120372, 0.10910902),
    ("Mittelrot", 0.50444755, 0.32706475, 0.18899996),
    ("Violett", 0.33347115, 0.25055230, 0.06276663),
    ("Gelbgrün", 0.39889345, 0.50414915, 0.43317594),
    ("Orangegelb", 0.49357600, 0.44428320, 0.42933776),
    ("Blau", 0.20522077, 0.16866548, 0.05596214),
    ("Grün", 0.32303796, 0.51041818, 0.22334376),
    ("Rot", 0.56287232, 0.33556281, 0.12780083),
    ("Gelb", 0.46775935, 0.47602443, 0.59929768),
    ("Magenta", 0.42131089, 0.26692462, 0.18951146),
    ("Cyan", 0.20912872, 0.30265801, 0.18060991),
    ("Weiß 9.5", 0.34891449, 0.36421258, 0.88069032),
    ("Neutral 8", 0.34558386, 0.35988061, 0.58997097),
    ("Neutral 6.5", 0.34414983, 0.35918507, 0.36486521),
    ("Neutral 5", 0.34576922, 0.35909383, 0.19062288),
    ("Neutral 3.5", 0.34264843, 0.35758352, 0.08817235),
    ("Schwarz 2", 0.34376747, 0.35605763, 0.03151319),
]
NEUTRAL = list(range(18, 24))          # Feldindizes 0-basiert: 19..24

_D50 = np.array([0.96422, 1.0, 0.82521])
_D65 = np.array([0.95047, 1.0, 1.08883])
_BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])
# linear sRGB (RGB-Reihenfolge) -> XYZ D65, IEC 61966-2-1
_RGB2XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                     [0.2126729, 0.7151522, 0.0721750],
                     [0.0193339, 0.1191920, 0.9503041]])


def srgb_linear(v):
    v = np.asarray(v, np.float64)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def linear_srgb(v):
    v = np.asarray(v, np.float64)
    return np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.maximum(v, 0) ** (1 / 2.4) - 0.055)


def _xyz_lab(xyz, weiss):
    t = np.asarray(xyz, np.float64) / weiss
    f = np.where(t > (6 / 29) ** 3, np.cbrt(t), t / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def soll_lab():
    """Sollwerte als Lab (D65, für den Vergleich mit sRGB-Bildern), Bradford-angepasst von D50."""
    x = np.array([v[1] for v in NAMEN_XYY_D50]); y = np.array([v[2] for v in NAMEN_XYY_D50])
    Y = np.array([v[3] for v in NAMEN_XYY_D50])
    xyz50 = np.stack([x * Y / y, Y, (1 - x - y) * Y / y], -1)
    kegel = _BRADFORD @ _D65 / (_BRADFORD @ _D50)
    M = np.linalg.inv(_BRADFORD) @ np.diag(kegel) @ _BRADFORD
    return _xyz_lab(xyz50 @ M.T, _D65)


def soll_srgb_linear():
    """Sollwerte als lineares sRGB (RGB-Reihenfolge, D65) — Ziel der Kalibrierung."""
    x = np.array([v[1] for v in NAMEN_XYY_D50]); y = np.array([v[2] for v in NAMEN_XYY_D50])
    Y = np.array([v[3] for v in NAMEN_XYY_D50])
    xyz50 = np.stack([x * Y / y, Y, (1 - x - y) * Y / y], -1)
    kegel = _BRADFORD @ _D65 / (_BRADFORD @ _D50)
    M = np.linalg.inv(_BRADFORD) @ np.diag(kegel) @ _BRADFORD
    return (xyz50 @ M.T) @ np.linalg.inv(_RGB2XYZ).T


def srgb_lab(rgb01):
    """sRGB (RGB-Reihenfolge, 0..1, gammakodiert) -> Lab (D65)."""
    return _xyz_lab(srgb_linear(rgb01) @ _RGB2XYZ.T, _D65)


def delta_e2000(lab1, lab2):
    """CIEDE2000 nach Sharma, Wu, Dalal (2005), kL = kC = kH = 1."""
    L1, a1, b1 = np.moveaxis(np.asarray(lab1, np.float64), -1, 0)
    L2, a2, b2 = np.moveaxis(np.asarray(lab2, np.float64), -1, 0)
    C1 = np.hypot(a1, b1); C2 = np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25.0 ** 7)))
    a1p = (1 + G) * a1; a2p = (1 + G) * a2
    C1p = np.hypot(a1p, b1); C2p = np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    dh = h2p - h1p
    dh = np.where(C1p * C2p == 0, 0.0, np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh)))
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lpm = (L1 + L2) / 2
    Cpm = (C1p + C2p) / 2
    hsum = h1p + h2p
    hpm = np.where(C1p * C2p == 0, hsum,
                   np.where(np.abs(h1p - h2p) <= 180, hsum / 2,
                            np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2)))
    T = (1 - 0.17 * np.cos(np.radians(hpm - 30)) + 0.24 * np.cos(np.radians(2 * hpm))
         + 0.32 * np.cos(np.radians(3 * hpm + 6)) - 0.20 * np.cos(np.radians(4 * hpm - 63)))
    dtheta = 30 * np.exp(-(((hpm - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cpm ** 7 / (Cpm ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / np.sqrt(20 + (Lpm - 50) ** 2)
    Sc = 1 + 0.045 * Cpm
    Sh = 1 + 0.015 * Cpm * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def feldmitten(p1, p6, p19, p24):
    """Mitten aller 24 Felder aus den Mitten der Eckfelder 1, 6, 19, 24 (x, y). Standardraster:
    4 Zeilen zu 6 Feldern; Feld k liegt in Zeile (k-1)//6, Spalte (k-1)%6."""
    p1, p6, p19, p24 = (np.asarray(p, np.float64) for p in (p1, p6, p19, p24))
    out = []
    for k in range(24):
        u = (k % 6) / 5.0; v = (k // 6) / 3.0
        oben = p1 * (1 - u) + p6 * u
        unten = p19 * (1 - u) + p24 * u
        out.append(oben * (1 - v) + unten * v)
    return np.array(out)


def felder_messen(bild_bgr, mitten, halbe_breite):
    """Median-Farbe je Feld (RGB-Reihenfolge, 0..1) in einem Quadrat um jede Mitte. Ein Feld, das
    über den Bildrand hinausragt, ist ein Bedienfehler (falsche Ecken) und wird gemeldet."""
    maxv = 65535.0 if bild_bgr.dtype == np.uint16 else (255.0 if bild_bgr.dtype == np.uint8 else 1.0)
    h, w = bild_bgr.shape[:2]
    r = int(round(halbe_breite))
    werte = []
    for i, (x, y) in enumerate(mitten):
        x, y = int(round(x)), int(round(y))
        if x - r < 0 or y - r < 0 or x + r >= w or y + r >= h:
            raise ValueError("Farbkarte: Feld %d (%s) liegt außerhalb des Bildes — Ecken prüfen"
                             % (i + 1, NAMEN_XYY_D50[i][0]))
        aus = bild_bgr[y - r:y + r + 1, x - r:x + r + 1].reshape(-1, 3).astype(np.float64) / maxv
        werte.append(np.median(aus, axis=0)[::-1])
    return np.array(werte)


def bewerten(rgb01, belichtung_angleichen=True):
    """ΔE2000 je Feld gegen die Sollwerte. Mit `belichtung_angleichen` wird die Helligkeit über
    das Feld Neutral 8 auf den Sollwert gebracht (linear, ein Faktor) — wie üblich, damit nicht
    die Belichtung, sondern die Farbwiedergabe gemessen wird."""
    rgb = np.asarray(rgb01, np.float64)
    if belichtung_angleichen:
        lin = srgb_linear(rgb)
        soll = soll_srgb_linear()
        f = soll[19, 1] / max(lin[19, 1], 1e-9)
        rgb = linear_srgb(np.clip(lin * f, 0, 1))
    de = delta_e2000(srgb_lab(rgb), soll_lab())
    return {"je_feld": de, "mittel": float(de.mean()), "median": float(np.median(de)),
            "max": float(de.max()), "bunt_mittel": float(de[:18].mean()),
            "grau_mittel": float(de[18:].mean())}


def kalibrierung_berechnen(rgb01):
    """3x3-Matrix in linearem sRGB, die die gemessenen Felder auf die Sollwerte bringt (kleinste
    Quadrate über alle 24 Felder). Zum Anwenden: `kalibrierung_anwenden`."""
    gem = srgb_linear(np.asarray(rgb01, np.float64))
    soll = soll_srgb_linear()
    M, *_ = np.linalg.lstsq(gem, soll, rcond=None)
    return M.T                                                  # soll ≈ M @ gem


def kalibrierung_anwenden(bild_bgr, M):
    """Matrix auf ein ganzes Bild (BGR, uint8/uint16/float 0..1, sRGB-gammakodiert). Was danach
    außerhalb 0..1 läge, wird zum Weiß bzw. Schwarz hin begrenzt — das ist bei einer Matrix
    unvermeidlich und betrifft nur sehr gesättigte Farben."""
    typ = bild_bgr.dtype
    maxv = 65535.0 if typ == np.uint16 else (255.0 if typ == np.uint8 else 1.0)
    lin = srgb_linear(bild_bgr[..., ::-1].astype(np.float64) / maxv)
    aus = linear_srgb(np.clip(lin @ np.asarray(M).T, 0, 1))[..., ::-1]
    if typ == np.uint16 or typ == np.uint8:
        return (aus * maxv + 0.5).astype(typ)
    return aus.astype(np.float32)


def _kandidaten(grau8):
    """Quadratische, helle-genug Flächen (Farbfelder) als (Mitte, Kantenlänge)."""
    import cv2
    funde = []
    for block in (31, 61, 121):
        b = cv2.adaptiveThreshold(grau8, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, block, -4)
        b = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        konturen, _ = cv2.findContours(b, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for k in konturen:
            flaeche = cv2.contourArea(k)
            if flaeche < 150:
                continue
            (cx, cy), (w, h), _ = cv2.minAreaRect(k)
            if min(w, h) <= 0 or max(w, h) / min(w, h) > 1.35 or flaeche / (w * h) < 0.8:
                continue
            funde.append((cx, cy, (w + h) / 2))
    return funde


def finden(bild_bgr, log=None):
    """Die Farbkarte im Bild finden. Gibt die 24 Feldmitten (x, y; Reihenfolge der X-Rite-
    Nummern) und die halbe Messbreite zurück. Wirft ValueError, wenn keine Karte sicher erkannt
    wird — lieber keine Kalibrierung als eine an der falschen Stelle.

    Verfahren: Quadrate finden, die größte Gruppe gleich großer Quadrate nehmen, ihr Rechteck
    (minAreaRect) als 6x4-Raster deuten, die Quadrate den Rasterplätzen zuordnen, daraus eine
    Homographie Raster -> Bild. Welche Ecke Feld 1 ist, entscheiden die Farben: von den vier
    möglichen Lagen gewinnt die mit dem kleinsten Farbabstand nach Weißabgleich."""
    import cv2
    maxv = 65535.0 if bild_bgr.dtype == np.uint16 else (255.0 if bild_bgr.dtype == np.uint8 else 1.0)
    h0, w0 = bild_bgr.shape[:2]
    s = min(1.0, 1600.0 / max(h0, w0))
    klein = cv2.resize(bild_bgr, (int(w0 * s), int(h0 * s)), interpolation=cv2.INTER_AREA)
    grau8 = (np.clip(cv2.cvtColor((klein / maxv).astype(np.float32), cv2.COLOR_BGR2GRAY), 0, 1) ** (1 / 2.2)
             * 255).astype(np.uint8) if maxv != 255.0 else cv2.cvtColor(klein, cv2.COLOR_BGR2GRAY)
    funde = _kandidaten(grau8)
    if len(funde) < 12:
        raise ValueError("Farbkarte nicht gefunden (nur %d quadratische Felder erkannt)" % len(funde))
    f = np.array(funde)
    # doppelte Funde (mehrere Schwellen) zusammenlegen
    eindeutig = []
    for x, y, k in f[np.argsort(-f[:, 2])]:
        if all(np.hypot(x - a, y - b) > 0.5 * k for a, b, _ in eindeutig):
            eindeutig.append((x, y, k))
    f = np.array(eindeutig)
    # größte Gruppe ähnlicher Kantenlänge
    beste = None
    for k in f[:, 2]:
        gruppe = f[np.abs(f[:, 2] / k - 1) < 0.25]
        if beste is None or len(gruppe) > len(beste):
            beste = gruppe
    if len(beste) < 12:
        raise ValueError("Farbkarte nicht gefunden (höchstens %d gleich große Felder)" % len(beste))
    kante = float(np.median(beste[:, 2]))
    # nur Quadrate, die nah beieinander liegen (die Karte), nicht verstreute Funde im Bild
    mitte = np.median(beste[:, :2], axis=0)
    abst = np.hypot(*(beste[:, :2] - mitte).T)
    beste = beste[abst < 6 * kante]
    pts = beste[:, :2].astype(np.float32)
    (cx, cy), (rw, rh), winkel = cv2.minAreaRect(pts)
    lang_ist_w = rw >= rh
    a = np.radians(winkel)
    ex = np.array([np.cos(a), np.sin(a)]); ey = np.array([-np.sin(a), np.cos(a)])
    if not lang_ist_w:
        ex, ey = ey, ex
        rw, rh = rh, rw
    rel = pts - np.array([cx, cy])
    u = rel @ ex; v = rel @ ey
    # Rasterplätze: 6 entlang der langen Achse, 4 entlang der kurzen
    sp = np.clip(np.round((u - u.min()) / max(u.max() - u.min(), 1e-6) * 5), 0, 5).astype(int)
    ze = np.clip(np.round((v - v.min()) / max(v.max() - v.min(), 1e-6) * 3), 0, 3).astype(int)
    if u.max() - u.min() < 3 * kante or v.max() - v.min() < 1.5 * kante:
        raise ValueError("Farbkarte nicht gefunden (die Felder bilden kein 6x4-Raster)")
    raster = np.stack([sp, ze], -1).astype(np.float32)
    belegt = {(int(a_), int(b_)) for a_, b_ in raster}
    if len(belegt) < 12:
        raise ValueError("Farbkarte nicht gefunden (nur %d von 24 Rasterplätzen belegt)" % len(belegt))
    H, _ = cv2.findHomography(raster, pts, cv2.RANSAC, 0.25 * kante)
    if H is None:
        raise ValueError("Farbkarte nicht gefunden (Raster passt nicht)")
    alle = np.array([[c, r] for r in range(4) for c in range(6)], np.float32)
    mitten_klein = cv2.perspectiveTransform(alle[None], H)[0]
    mitten = mitten_klein / s
    halb = 0.3 * kante / s
    # Lage: Raster (c, r) -> X-Rite-Nummer; vier Möglichkeiten (gespiegelt entlang c und/oder r)
    soll = soll_lab()
    beste_lage = None
    for fc in (False, True):
        for fr in (False, True):
            reihen = []
            for r in range(4):
                for c in range(6):
                    cc = 5 - c if fc else c
                    rr = 3 - r if fr else r
                    reihen.append(rr * 6 + cc)            # Rasterplatz (c, r) ist Feld Nr. reihen[...]
            ordnung = np.argsort(reihen)                  # Feld k -> Rasterindex
            m = mitten[ordnung]
            try:
                rgb = felder_messen(bild_bgr, m, halb)
            except ValueError:
                continue
            lin = srgb_linear(rgb)
            ziel = soll_srgb_linear()
            g = ziel[NEUTRAL].sum(0) / np.maximum(lin[NEUTRAL].sum(0), 1e-9)
            de = delta_e2000(srgb_lab(linear_srgb(np.clip(lin * g * (ziel[19, 1] / max((lin * g)[19, 1], 1e-9)), 0, 1))), soll)
            if beste_lage is None or de.mean() < beste_lage[0]:
                beste_lage = (float(de.mean()), m)
    if beste_lage is None or beste_lage[0] > 15:
        raise ValueError("Farbkarte nicht sicher erkannt (Farben passen in keiner Lage%s)"
                         % ("" if beste_lage is None else ", bestes ΔE %.1f" % beste_lage[0]))
    if log:
        log("Farbkarte gefunden: %d Felder erkannt, Kante %.0f px, ΔE nach Weißabgleich %.1f"
            % (len(beste), kante / s, beste_lage[0]))
    return beste_lage[1], halb


PROFIL_FORMAT = "forgepix-farbprofil/1"


def profil_erstellen(bild_bgr, quelle="", log=None):
    """Aus einem Bild mit Farbkarte (neutral entwickelt) ein Farbprofil machen: Karte finden,
    Matrix rechnen, ehrlich bewerten. „eins_ausgelassen“ rechnet die Matrix je Feld ohne dieses
    Feld und prüft sie daran — die Zahl an allen 24 Feldern wäre zu günstig (an der Testdatei
    2,40 gegen 2,69)."""
    mitten, halb = finden(bild_bgr, log=log)
    rgb = felder_messen(bild_bgr, mitten, halb)
    lin = srgb_linear(rgb)
    soll = soll_srgb_linear(); sl = soll_lab()
    M = kalibrierung_berechnen(rgb)
    loo = []
    for i in range(24):
        idx = [j for j in range(24) if j != i]
        Mi, *_ = np.linalg.lstsq(lin[idx], soll[idx], rcond=None)
        loo.append(float(delta_e2000(srgb_lab(linear_srgb(np.clip(lin[i] @ Mi, 0, 1))), sl[i])))
    vorher = bewerten(rgb)
    nachher = bewerten(linear_srgb(np.clip(lin @ M.T, 0, 1)), belichtung_angleichen=False)
    return {"format": PROFIL_FORMAT, "quelle": os.path.basename(quelle), "matrix": M.tolist(),
            "delta_e": {"vorher": round(vorher["mittel"], 2), "nachher": round(nachher["mittel"], 2),
                        "eins_ausgelassen": round(float(np.mean(loo)), 2),
                        "eins_ausgelassen_max": round(float(np.max(loo)), 2)}}


def profil_speichern(profil, pfad):
    import json
    with open(pfad, "w", encoding="utf-8", newline="\n") as f:
        json.dump(profil, f, indent=1, ensure_ascii=False)


def profil_laden(pfad):
    import json
    with open(pfad, encoding="utf-8") as f:
        p = json.load(f)
    if p.get("format") != PROFIL_FORMAT:
        raise ValueError("%s ist kein ForgePix-Farbprofil (Format %r)" % (pfad, p.get("format")))
    M = np.asarray(p.get("matrix"), np.float64)
    if M.shape != (3, 3) or not np.isfinite(M).all():
        raise ValueError("%s: Matrix ist keine gültige 3x3-Matrix" % pfad)
    return M
