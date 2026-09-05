#!/usr/bin/env python3
"""
core/komet.py — Kometen-Stacking: auf den KERN ausrichten statt auf die Sterne.

Das Problem, das kein normales Stacking löst: ein Komet bewegt sich zwischen den Aufnahmen
gegenüber den Sternen. Richtet man auf die Sterne aus (der Normalfall), wird der Komet zu einem
Streifen — genau das Objekt, wegen dem die Nacht draußen verbracht wurde. Richtet man auf den
Kern aus, werden die Sterne zu Streifen, der Komet aber scharf.

Diese Umsetzung findet den Kern SELBST, ohne dass jemand ihn anklicken muss (Siril und die
meisten anderen Programme verlangen das Markieren in zwei Frames):

  1. Auf die Sterne ausrichten (der vorhandene Weg).
  2. Aus den ausgerichteten Frames einen Median bilden — darin steht der Himmel still, der
     bewegte Komet mittelt sich weg.
  3. Diesen Median von jedem Frame abziehen. Übrig bleibt vor allem das, was sich bewegt.
  4. Im Rest je Frame den hellsten ausgedehnten Fleck suchen — das ist der Kern.
  5. Durch die gefundenen Orte eine GERADE legen (robust, mit Ausreißer-Verwurf). Ein Komet
     bewegt sich über eine Nacht praktisch geradlinig und gleichförmig; die Gerade fängt
     Fehlgriffe ab, die eine reine Punkt-zu-Punkt-Verschiebung übernehmen würde.
  6. Jeden Frame um seinen Geradenwert zurückschieben und stapeln.

EHRLICHE GRENZE: Schritt 4 findet den HELLSTEN bewegten Fleck. Bei einem sehr schwachen Kometen
in einem Feld mit veränderlichen Sternen oder Satellitenspuren kann das der falsche sein. Darum
meldet `spur_finden()` mit, wie gut die Gerade sitzt (Rest in Pixeln) und wie viele Frames als
Ausreißer verworfen wurden — wer diese Zahlen ignoriert, stapelt womöglich einen Satelliten.
"""
import os

import numpy as np
import cv2

from constants import log_print
import astro


def _rest_bild(frame, median):
    """Ein Frame minus dem Sternhimmel. Nur das Bewegte bleibt übrig."""
    d = astro._gray(frame) - astro._gray(median)
    return np.clip(d, 0, None)


def _hellster_fleck(rest, min_flaeche=6, max_flaeche=20000, sigma=4.0):
    """Schwerpunkt des hellsten ausgedehnten Flecks im Restbild, oder None.

    `min_flaeche` schließt einzelne Rauschspitzen und Restsäume von Sternen aus: ein Komet ist
    diffus und deckt viele Pixel ab, ein Sternrest sitzt auf ein bis zwei.
    """
    if rest is None or rest.size == 0:
        return None
    med = float(np.median(rest))
    mad = float(np.median(np.abs(rest - med))) * 1.4826 + 1e-9
    m = (rest > med + sigma * mad).astype(np.uint8)
    if m.sum() == 0:
        return None
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    bester, bestes_licht = None, 0.0
    for i in range(1, n):
        flaeche = int(stats[i, cv2.CC_STAT_AREA])
        if not (min_flaeche <= flaeche <= max_flaeche):
            continue
        x0, y0 = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
        bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        sel = (lab[y0:y0 + bh, x0:x0 + bw] == i)
        w = np.where(sel, rest[y0:y0 + bh, x0:x0 + bw], 0.0).astype(np.float64)
        licht = float(w.sum())
        if licht <= bestes_licht:
            continue
        yy, xx = np.mgrid[0:bh, 0:bw].astype(np.float64)
        bester = (x0 + float((w * xx).sum() / licht), y0 + float((w * yy).sum() / licht))
        bestes_licht = licht
    return bester


def _zeitachse(paths):
    """Aufnahmezeiten in Sekunden ab dem ersten Frame. Ohne Zeitstempel: die Bildnummer.

    Warum das zählt: bei Wolkenpausen sind die Abstände ungleich. Über die Bildnummer gerechnet
    säße der Kern dann falsch — die Gerade wird über die ZEIT gelegt, nicht über den Index.
    """
    try:
        from astropy.io import fits
        from datetime import datetime
    except Exception:
        return np.arange(len(paths), dtype=np.float64), False
    t = []
    for p in paths:
        wert = None
        if os.path.splitext(p)[1].lower() in (".fit", ".fits", ".fts"):
            try:
                s = str(fits.getheader(p).get("DATE-OBS", "")).strip()
                if s:
                    wert = datetime.fromisoformat(s.replace("Z", "")).timestamp()
            except Exception:
                wert = None
        t.append(wert)
    if any(v is None for v in t):
        return np.arange(len(paths), dtype=np.float64), False
    t = np.asarray(t, np.float64)
    return t - t[0], True


def _gerade_robust(t, v, runden=3):
    """Robuste Gerade v(t) = a·t + b. Gibt (a, b, behalten-Maske) zurück."""
    behalten = np.ones(len(t), bool)
    a, b = 0.0, float(np.median(v)) if len(v) else 0.0
    for _ in range(runden):
        if behalten.sum() < 3:
            break
        a, b = np.polyfit(t[behalten], v[behalten], 1)
        rest = v - (a * t + b)
        mad = float(np.median(np.abs(rest - np.median(rest)))) * 1.4826 + 1e-9
        behalten = np.abs(rest - np.median(rest)) <= 3.0 * mad
    return float(a), float(b), behalten


def spur_finden(reg_paths, log=log_print):
    """Kernbahn aus bereits sternregistrierten Frames bestimmen.

    Returns:
        dict mit `versatz` (Liste (dx, dy) je Frame, bezogen auf den ersten Frame),
        `gefunden` (in wie vielen Frames ein Kern gefunden wurde), `verworfen`,
        `rest_px` (mittlerer Abstand der Fundorte zur Geraden),
        `geschwindigkeit_px_pro_frame` und `echte_zeit` (ob Zeitstempel benutzt wurden).
        Bei zu wenig Material: None.
    """
    n = len(reg_paths)
    if n < 4:
        log("    Komet: mindestens 4 Frames noetig (%d vorhanden)" % n)
        return None
    frames = [astro._read_float(p) for p in reg_paths]
    median = np.median(np.stack([astro._gray(f) for f in frames]), axis=0)
    orte = []
    for f in frames:
        orte.append(_hellster_fleck(_rest_bild(f, median)))
    gefunden = [i for i, o in enumerate(orte) if o is not None]
    if len(gefunden) < 4:
        log("    Komet: nur in %d von %d Frames ein bewegtes Objekt gefunden — zu wenig"
            % (len(gefunden), n))
        return None
    t_all, echte_zeit = _zeitachse(reg_paths)
    t = t_all[gefunden]
    x = np.asarray([orte[i][0] for i in gefunden], np.float64)
    y = np.asarray([orte[i][1] for i in gefunden], np.float64)
    ax, bx, kx = _gerade_robust(t, x)
    ay, by, ky = _gerade_robust(t, y)
    behalten = kx & ky
    rest = np.hypot(x - (ax * t + bx), y - (ay * t + by))
    rest_px = float(np.mean(rest[behalten])) if behalten.any() else float("nan")
    # Versatz JEDES Frames aus der Geraden — auch der, in denen nichts gefunden wurde.
    x0, y0 = ax * t_all[0] + bx, ay * t_all[0] + by
    versatz = [(float(ax * tt + bx - x0), float(ay * tt + by - y0)) for tt in t_all]
    spanne = float(t_all[-1] - t_all[0]) or 1.0
    weg = float(np.hypot(ax, ay) * spanne)
    log("    Komet: in %d von %d Frames gefunden, %d als Ausreisser verworfen, "
        "Rest zur Geraden %.2f px" % (len(gefunden), n, int((~behalten).sum()), rest_px))
    log("    Komet: Wanderung ueber die Serie %.1f px%s"
        % (weg, " (echte Zeitstempel)" if echte_zeit else " (ohne Zeitstempel, ueber Bildnummer)"))
    return {"versatz": versatz, "gefunden": len(gefunden), "verworfen": int((~behalten).sum()),
            "rest_px": rest_px, "weg_px": weg, "echte_zeit": echte_zeit}


def auf_kern_verschieben(reg_paths, out_dir, versatz, log=log_print):
    """Sternregistrierte Frames um die Kernbahn zurückschieben und neu ablegen.

    Verschoben wird mit `INTER_LANCZOS4` und Randfortsetzung: die Verschiebungen sind meist
    nicht ganzzahlig, und ein hartes Abschneiden am Rand würde beim Stapeln dunkle Kanten
    erzeugen — dieselbe Ursache wie die dunklen Ränder, die Alfred im Stack aufgefallen sind.
    """
    os.makedirs(out_dir, exist_ok=True)
    raus = []
    for i, p in enumerate(reg_paths):
        f = astro._read_float(p)
        dx, dy = versatz[i] if i < len(versatz) else (0.0, 0.0)
        M = np.array([[1, 0, -dx], [0, 1, -dy]], np.float32)
        g = cv2.warpAffine(f, M, (f.shape[1], f.shape[0]),
                           flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
        ziel = os.path.join(out_dir, "k_%04d.tif" % i)
        from constants import imwrite
        imwrite(ziel, np.clip(g * 65535, 0, 65535).astype(np.uint16))
        raus.append(ziel)
    log("    Komet: %d Frames auf den Kern ausgerichtet" % len(raus))
    return raus


def stack_auf_kern(reg_paths, out_dir, method="median", kappa=2.5, log=log_print):
    """Kompletter Kometen-Durchgang auf bereits sternregistrierten Frames.

    `median` ist hier die richtige Voreinstellung und nicht `sigma`: nach dem Verschieben auf den
    Kern sind die STERNE die Ausreißer, und der Median wirft sie am gründlichsten weg. Ein
    Mittelwert liesse die Sternstreifen stehen.

    Returns: (ergebnis_bgr, info-dict) oder (None, None), wenn kein Kern gefunden wurde.
    """
    info = spur_finden(reg_paths, log=log)
    if info is None:
        return None, None
    pfade = auf_kern_verschieben(reg_paths, out_dir, info["versatz"], log=log)
    erg = astro.stack(pfade, method=method, kappa=kappa, log=log)
    return erg, info
