#!/usr/bin/env python3
"""
core/autofokus.py — Autofokus über den Halbflussradius (HFR), wie N.I.N.A. ihn macht.

Ablauf: den Fokussierer in gleichen Schritten um die aktuelle Stelle herum fahren (immer aus
derselben Richtung, gegen Getriebespiel), an jeder Stelle belichten, die HFR der Sterne messen,
eine Hyperbel durch die gültigen Punkte legen (wie N.I.N.A.) und deren Minimum anfahren.

Abgesichert, damit er nie still eine falsche Stelle anfährt:
* Eine Stelle ohne messbare Sterne zählt als „nicht gemessen“ (None) — kein Platzhalterwert,
  der die Kurve verbiegt (CLAUDE.md: FWHM 99 im Median).
* Weniger als vier gültige Punkte, eine Kurve ohne Minimum oder ein Minimum außerhalb der
  gefahrenen Spanne → Fehler, und der Fokussierer fährt zurück an die Ausgangsstelle.

Arbeitet mit jedem Kamera-/Fokussierer-Anschluss, der `belichten(dauer)` bzw. `position()` und
`fahren(ziel)` hat (alpaca.py, indi.py). Kein Qt.
"""
import numpy as np

try:
    from constants import log_print
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)


def hfr(bild, max_sterne=60, min_sterne=3):
    """Median-HFR der hellsten Sterne in Pixeln, oder None, wenn zu wenige Sterne da sind.

    Gemessen wird nur am Stern selbst: seine Fläche über der Schwelle, etwas aufgeweitet (damit
    die schwachen Flanken mitzählen), OHNE andere Sterne im Fenster. Erste Fassung nahm ein
    festes Fenster — bei Unschärfe griff es in Nachbarsterne, und die HFR sprang (23.11.2026,
    gefunden am Autofokus-Test: Kurve nicht V-förmig, Fokus 99 Schritte daneben)."""
    import cv2
    a = np.asarray(bild, np.float32)
    if a.ndim == 3:
        a = a.mean(axis=2)
    bg = float(np.median(a))
    rauschen = float(np.median(np.abs(a - bg)) * 1.4826) or float(a.std()) or 1e-6
    maske = (a > bg + 5 * rauschen).astype(np.uint8)
    n, marken, werte, _ = cv2.connectedComponentsWithStats(maske, 8)
    if n <= 1:
        return None
    reihen = np.argsort(-werte[1:, cv2.CC_STAT_AREA]) + 1
    radien = []
    h, w = a.shape
    for i in reihen:
        flaeche = int(werte[i, cv2.CC_STAT_AREA])
        if not 3 <= flaeche <= 20000:
            continue
        x, y, bw, bh = (int(v) for v in werte[i, :4])
        rand = int(max(2, round(0.5 * np.sqrt(flaeche / np.pi))))
        x0, y0, x1, y1 = x - rand, y - rand, x + bw + rand, y + bh + rand
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
            continue                                   # angeschnittene Sterne verfälschen die HFR
        fenster = marken[y0:y1, x0:x1]
        eigen = (fenster == i).astype(np.uint8)
        kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rand + 1, 2 * rand + 1))
        bereich = cv2.dilate(eigen, kern).astype(bool) & ((fenster == 0) | (fenster == i))
        if ((fenster != 0) & (fenster != i) & cv2.dilate(eigen, kern).astype(bool)).any():
            continue                                   # Nachbar berührt den Stern: nicht messen
        stueck = np.where(bereich, np.clip(a[y0:y1, x0:x1] - bg, 0, None), 0.0)
        summe = float(stueck.sum())
        if summe <= 0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        cx = float((xx * stueck).sum() / summe)
        cy = float((yy * stueck).sum() / summe)
        radien.append(float((np.hypot(xx - cx, yy - cy) * stueck).sum() / summe))
        if len(radien) >= max_sterne:
            break
    if len(radien) < min_sterne:
        return None
    return float(np.median(radien))


def _kurve_anpassen(x, y):
    """Hyperbel HFR = √(a² + (k·(x − x0))²) (Optik: Unschärfescheibe wächst linear mit dem
    Abstand, die beste HFR ist endlich); Parabel nur als Startwert. Gibt (x0, a) oder wirft."""
    from scipy.optimize import curve_fit
    x = np.asarray(x, float); y = np.asarray(y, float)
    i = int(np.argmin(y))
    steigung = max(float(np.ptp(y)) / max(float(np.ptp(x)), 1e-9), 1e-6)

    def hyperbel(t, x0, a, k):
        return np.sqrt(a * a + (k * (t - x0)) ** 2)
    try:
        werte, _ = curve_fit(hyperbel, x, y, p0=(x[i], max(y[i], 1e-3), steigung), maxfev=20000)
    except RuntimeError as e:
        raise RuntimeError("HFR-Kurve ließ sich nicht anpassen: %s" % e) from e
    x0, a, k = werte
    if not np.isfinite(werte).all() or abs(k) < 1e-9:
        raise RuntimeError("Die HFR-Kurve hat kein Minimum — Schrittweite größer wählen.")
    return float(x0), float(abs(a))


def autofokus(kamera, fokussierer, schritt=100, punkte=7, belichtung=2.0, abbruch=None,
              log=log_print):
    """Fokus suchen und anfahren. Gibt {'position', 'hfr_erwartet', 'kurve': [(pos, hfr|None)]}."""
    if punkte < 5:
        raise ValueError("Mindestens 5 Messpunkte, nicht %d" % punkte)
    if schritt <= 0:
        raise ValueError("Schrittweite muss positiv sein, nicht %r" % schritt)
    start = int(round(fokussierer.position()))
    halb = punkte // 2
    stellen = [start + (i - halb) * int(schritt) for i in range(punkte)]
    log("Autofokus: %d Punkte von %d bis %d, je %.1f s" % (punkte, stellen[0], stellen[-1], belichtung))
    fokussierer.fahren(stellen[0] - int(schritt))      # Anlauf: immer von innen nach außen
    kurve = []
    try:
        for pos in stellen:
            if abbruch is not None and abbruch.is_set():
                raise RuntimeError("Autofokus abgebrochen")
            fokussierer.fahren(pos)
            wert = hfr(kamera.belichten(belichtung))
            kurve.append((pos, wert))
            log("  Position %d: HFR %s" % (pos, "—" if wert is None else "%.2f px" % wert))
        gueltig = [(p, v) for p, v in kurve if v is not None]
        if len(gueltig) < 4:
            raise RuntimeError("Nur %d von %d Punkten mit Sternen — Belichtung länger oder näher am "
                               "Fokus beginnen." % (len(gueltig), punkte))
        x = [p for p, _ in gueltig]
        y = [v for _, v in gueltig]
        bester, erwartet = _kurve_anpassen(x, y)
        if not stellen[0] <= bester <= stellen[-1]:
            raise RuntimeError("Das Minimum (%d) liegt außerhalb der gefahrenen Spanne %d…%d — "
                               "näher am Fokus neu starten." % (bester, stellen[0], stellen[-1]))
        ziel = int(round(bester))
    except Exception:
        log("Autofokus gescheitert — fahre zurück auf %d" % start)
        fokussierer.fahren(start - int(schritt))
        fokussierer.fahren(start)
        raise
    fokussierer.fahren(ziel - int(schritt))            # gleiche Anlaufrichtung wie beim Messen
    fokussierer.fahren(ziel)
    log("Autofokus: beste Position %d, erwartete HFR %.2f px" % (ziel, erwartet))
    return {"position": ziel, "hfr_erwartet": erwartet, "kurve": kurve, "start": start}
