#!/usr/bin/env python3
"""HDR aus Belichtungsreihen messen: verschiedene Wege gegen die normale Kamera-Aufnahme.

    python docs/vergleich/hdr_vergleich.py <ordner-mit-raw-reihen> [anzahl_reihen=8]

Je Reihe (nach Belichtungszeit: kurz/normal/lang) gegen das eingebettete Kamerabild der normalen
Belichtung: Helligkeit (Median-Verhältnis), ausgebrannte und fast schwarze Fläche, und
„Zeichnung“ (mittlerer Laplace-Betrag) in den Bereichen, die in der normalen Aufnahme
ausgebrannt (>= 0,95) bzw. abgesoffen (<= 0,06) sind — jeweils relativ zur Belichtung, die dort
die meiste Information hat (kurz bzw. lang).

V0 = alter Weg (8 bit neutral, Fusion, Look „natural“), V1 = jetziger Standard (16 bit neutral,
Fusion, an das Kamerabild angeglichen), V1+look = V1 und zusätzlich „natural“, V2 = jede
Belichtung im Kamera-Look entwickelt, dann Fusion.
"""
import glob, os, sys, time
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "core")]
import cv2, numpy as np

LUMA = np.float32([0.0722, 0.7152, 0.2126])


def f01(b):
    return b.astype(np.float32) / (65535.0 if b.dtype == np.uint16 else 255.0)


def lum(b):
    return f01(b) @ LUMA


def detail(l, maske):
    lap = np.abs(cv2.Laplacian(cv2.GaussianBlur(l, (0, 0), 0.8), cv2.CV_32F))
    return float(lap[maske].mean()) if maske.any() else float("nan")


def messen(erg, kamera0, minus, plus, breite=1200):
    """Alles auf gleiche Größe; Masken aus der normalen Kameraaufnahme."""
    s = lambda b: cv2.resize(b, (breite, int(b.shape[0] * breite / b.shape[1])), interpolation=cv2.INTER_AREA)
    e, k, m, p = (lum(s(x)) for x in (erg, kamera0, minus, plus))
    if e.shape != k.shape:
        e = cv2.resize(e, (k.shape[1], k.shape[0]))
    hell = cv2.erode((k >= 0.95).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    dunkel = cv2.erode((k <= 0.06).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    ek = f01(s(erg)) if s(erg).shape[:2] == k.shape else cv2.resize(f01(erg), (k.shape[1], k.shape[0]))
    return {"median_rel": float(np.median(e) / np.median(k)),
            "ausgebrannt": float((ek.max(-1) >= 0.99).mean() * 100),
            "fast_schwarz": float((e < 0.02).mean() * 100),
            # Zeichnung relativ zur besten Einzelbelichtung für diesen Bereich
            "lichter_zeichnung": detail(e, hell) / max(detail(m, hell), 1e-9) if hell.mean() > 0.002 else None,
            "schatten_zeichnung": detail(e, dunkel) / max(detail(p, dunkel), 1e-9) if dunkel.mean() > 0.002 else None}


def main():
    import focus_cull_stack as F
    import hdr, kameralook
    import constants
    ordner = sys.argv[1]
    anzahl = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    alle = sorted(p for p in glob.glob(os.path.join(ordner, "*"))
                  if os.path.splitext(p)[1].lower() in constants.RAW_EXTS)
    gruppen = hdr.split_brackets(alle, log=lambda *a: None)
    wahl = [gruppen[i] for i in np.linspace(0, len(gruppen) - 1, min(anzahl, len(gruppen))).astype(int)]
    zeilen = {"V0": [], "V1": [], "V1+look": [], "V2": [], "Kamera0": []}
    for grp in wahl:
        zeiten = hdr.read_exposure_times(grp)
        o = np.argsort(zeiten)                         # kurz, mittel, lang
        p_minus, p_null, p_plus = grp[o[0]], grp[o[1]], grp[o[2]]
        kam = [kameralook.vorschau(p) for p in (p_minus, p_null, p_plus)]
        if any(x is None for x in kam):
            print("ohne Vorschau, übersprungen:", grp); continue
        t = time.time()
        v0 = hdr.apply_look(hdr.merge_exposures([F.develop_raw_to_bgr(p, bps=8, look="neutral") for p in grp],
                                                 log=lambda *a: None), "natural")
        n16 = [F.develop_raw_to_bgr(p, bps=16, look="neutral") for p in (p_minus, p_null, p_plus)]
        fus = hdr.merge_exposures(n16, log=lambda *a: None)
        v1, _ = kameralook.angleichen(fus, kam[1], log=lambda *a: None)
        v1l = hdr.apply_look(v1, "natural")
        k16 = [F.develop_raw_to_bgr(p, bps=16, look="kamera") for p in (p_minus, p_null, p_plus)]
        v2 = hdr.apply_look(hdr.merge_exposures(k16, log=lambda *a: None), "natural")
        for name, b in (("V0", v0), ("V1", v1), ("V1+look", v1l), ("V2", v2), ("Kamera0", kam[1])):
            zeilen[name].append(messen(b, kam[1], kam[0], kam[2]))
        print(os.path.basename(p_null), "%.0f s" % (time.time() - t), flush=True)
    for name, z in zeilen.items():
        def med(k):
            w = [r[k] for r in z if r[k] is not None and r[k] == r[k]]
            return "%.3f" % np.median(w) if w else "-"
        print("%-8s Helligkeit %s  ausgebrannt %s %%  fast schwarz %s %%  Lichter-Zeichnung %s  Schatten-Zeichnung %s"
              % (name, med("median_rel"), med("ausgebrannt"), med("fast_schwarz"), med("lichter_zeichnung"),
                 med("schatten_zeichnung")))


if __name__ == "__main__":
    main()
