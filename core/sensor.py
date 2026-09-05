#!/usr/bin/env python3
"""
sensor.py — Sensor- und Optikdiagnose aus den Aufnahmen selbst.

Zwei Dinge, die Siril kann und ForgePix bisher nicht — beide brauchen KEINE Kalibrierframes,
was hier entscheidend ist: für viele Kameras liegen schlicht keine passenden Darks vor.

1. FELDKARTE (Siril `inspector` / `tilt`): die Sternbreite über das Bildfeld messen.
   Sind die Ecken schlechter als die Mitte, ist das Bildfeld gekrümmt — dagegen hilft ein
   Flattener. Ist EINE Seite schlechter als die gegenüberliegende, steht der Sensor schief
   oder der Auszug ist verkippt — das ist ein mechanisches Problem, das keine Software behebt.
   Die Unterscheidung ist der eigentliche Wert: sie sagt, ob man schrauben oder kaufen muss.

2. DEFEKTKARTE (Siril `find_hot` + `cosme`): dauerhaft auffällige Pixel finden.
   Ein Hotpixel sitzt in JEDER Aufnahme an derselben Sensorstelle. Der Himmel wandert durchs
   Dithering, der Defekt nicht. Wer über viele UNREGISTRIERTE Aufnahmen zählt, wie oft ein
   Pixel gegenüber seiner Nachbarschaft ausreißt, trennt beides sauber — ohne ein einziges
   Dark. Ein einzelner kosmischer Treffer erscheint nur einmal und fällt damit heraus.
"""

import numpy as np
import cv2

from constants import log_print


# --------------------------------------------------------------------- Feldkarte ---

def _fwhm_im_feld(g, y0, y1, x0, x1, max_sterne=40, fenster=7):
    """Mittlere Sternbreite in einem Bildausschnitt. None, wenn zu wenige Sterne.

    Gemessen wird das FLUSSGEWICHTETE zweite Moment in einem festen Fenster um jeden Stern,
    nicht die Fläche über einer Helligkeitsschwelle. Das ist der entscheidende Unterschied:
    ein stärker verwaschener Stern hat einen NIEDRIGEREN Gipfel und überschreitet eine feste
    Schwelle darum mit weniger Pixeln — die Flächenmessung sieht ihn fälschlich als KLEINER,
    was die Verbreiterung gerade wieder aufhebt. Genau daran war die erste Fassung blind:
    ein künstlich stark gekrümmtes Feld (Sigma 0.9 bis 2.9) kam als „gleichmäßig" heraus.
    """
    aus = g[y0:y1, x0:x1]
    if aus.size < 100:
        return None
    bg = float(np.median(aus))
    sigma = float(np.std(aus)) + 1e-6
    maske = (aus > bg + 4 * sigma).astype(np.uint8)
    n, _labels, stats, zentren = cv2.connectedComponentsWithStats(maske, 8)
    if n <= 1:
        return None
    reihenfolge = np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1
    r = max(3, int(fenster) // 2)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    breiten = []
    for i in reihenfolge:
        if not 2 <= int(stats[i, cv2.CC_STAT_AREA]) <= 800:
            continue
        cx, cy = zentren[i]
        xi, yi = int(round(cx)), int(round(cy))
        if not (r <= xi < aus.shape[1] - r and r <= yi < aus.shape[0] - r):
            continue
        fenster_bild = aus[yi - r:yi + r + 1, xi - r:xi + r + 1].astype(np.float32) - bg
        fluss = float(np.clip(fenster_bild, 0, None).sum())
        if fluss <= 1e-6:
            continue
        w = np.clip(fenster_bild, 0, None)
        # zweites Moment um den Schwerpunkt -> Sigma -> FWHM
        mx = float((w * xx).sum() / fluss)
        my = float((w * yy).sum() / fluss)
        var = float((w * ((xx - mx) ** 2 + (yy - my) ** 2)).sum() / fluss) / 2.0
        if var <= 1e-6:
            continue
        breiten.append(2.3548 * float(np.sqrt(var)))
        if len(breiten) >= max_sterne:
            break
    return float(np.median(breiten)) if len(breiten) >= 3 else None


def feldkarte(gray, gitter=3):
    """Sternbreite je Feld eines gitter×gitter-Rasters. Gibt ein 2D-Array (NaN = zu wenige Sterne)."""
    g = np.asarray(gray, np.float32)
    if g.ndim == 3:
        g = g.mean(axis=2)
    h, w = g.shape[:2]
    n = max(2, int(gitter))
    karte = np.full((n, n), np.nan, np.float32)
    for iy in range(n):
        for ix in range(n):
            v = _fwhm_im_feld(g, iy * h // n, (iy + 1) * h // n, ix * w // n, (ix + 1) * w // n)
            if v is not None:
                karte[iy, ix] = v
    return karte


def feld_urteil(karte):
    """Krümmung oder Verkippung? Gibt (kennzeichen, satz) zurück.

    Krümmung: alle Ecken schlechter als die Mitte, ungefähr gleichmäßig — der Klassiker bei
    Newton und schnellen Refraktoren, behebbar mit einem Flattener/Komakorrektor.
    Verkippung: eine SEITE deutlich schlechter als die gegenüberliegende — mechanisch, das
    heisst Auszug oder Adapter richten, keine Software.
    """
    k = np.asarray(karte, np.float32)
    if np.all(np.isnan(k)) or k.shape[0] < 3:
        return "unbekannt", "Zu wenige Sterne für eine Feldbeurteilung."
    mitte = float(k[k.shape[0] // 2, k.shape[1] // 2])
    ecken = [k[0, 0], k[0, -1], k[-1, 0], k[-1, -1]]
    ecken = [float(e) for e in ecken if not np.isnan(e)]
    if np.isnan(mitte) or len(ecken) < 3:
        return "unbekannt", "Zu wenige Sterne in Mitte oder Ecken."
    ecken_mittel = float(np.mean(ecken))
    kruemmung = (ecken_mittel - mitte) / max(mitte, 1e-6) * 100
    # Verkippung: Unterschied links/rechts und oben/unten
    links = float(np.nanmean(k[:, 0])); rechts = float(np.nanmean(k[:, -1]))
    oben = float(np.nanmean(k[0, :])); unten = float(np.nanmean(k[-1, :]))
    kipp_x = (rechts - links) / max(mitte, 1e-6) * 100
    kipp_y = (unten - oben) / max(mitte, 1e-6) * 100
    kipp = max(abs(kipp_x), abs(kipp_y))
    satz = ("Sternbreite: Mitte %.1f px, Ecken im Mittel %.1f px (%+.0f %%). "
            "Links/rechts %+.0f %%, oben/unten %+.0f %%." % (mitte, ecken_mittel, kruemmung,
                                                             kipp_x, kipp_y))
    # 18 % Seitenunterschied in der Sternbreite ist mit blossem Auge im Bild sichtbar und
    # damit meldenswert. Der erste Ansatz stand bei 25 % und liess einen synthetisch klar
    # verkippten Fall (22 %) durchrutschen.
    if kipp > 18 and kipp > abs(kruemmung) * 0.8:
        richtung = ("rechts" if kipp_x > 0 else "links") if abs(kipp_x) >= abs(kipp_y) \
            else ("unten" if kipp_y > 0 else "oben")
        return ("verkippung",
                satz + " Eine Seite ist deutlich schlechter (%s) — das deutet auf einen "
                "verkippten Sensor oder Auszug hin. Das ist mechanisch und mit Software nicht "
                "zu beheben." % richtung)
    if kruemmung > 25:
        return ("kruemmung",
                satz + " Die Ecken sind rundum schlechter als die Mitte — typische "
                "Bildfeldkrümmung. Ein Flattener/Komakorrektor hilft; die Aufnahmen selbst "
                "sind in Ordnung.")
    return "ok", satz + " Das Feld ist gleichmäßig — keine auffällige Krümmung oder Verkippung."


# ------------------------------------------------------------------- Defektkarte ---

def defektkarte(paths, max_frames=20, sigma=6.0, mindest_anteil=0.6, darks=None,
                quelle="auto", log=log_print):
    """Dauerhaft defekte Pixel finden — aus DARKS, wenn vorhanden, sonst aus den Lights.

    Ein Hotpixel sitzt in JEDER Aufnahme an derselben Sensorstelle; der Himmel wandert durchs
    Dithering. Gezählt wird je Aufnahme, welche Pixel gegenüber ihrer 3×3-Nachbarschaft
    ausreißen; als defekt gilt, was in mindestens `mindest_anteil` der Aufnahmen auffällt.
    Ein einzelner kosmischer Treffer erscheint nur einmal und fällt damit heraus — genau das
    unterscheidet diese Karte von einer Einzelbild-Kosmetik.

    `quelle`:
      "auto"   — Darks nehmen, wenn welche übergeben wurden, sonst die Lights (Standard)
      "darks"  — nur Darks; fehlen sie, wird nichts geliefert
      "lights" — bewusst die Lights, auch wenn Darks da sind

    WARUM DARKS BESSER SIND, wenn es sie gibt: dort gibt es kein Sternlicht, das mit einem
    Hotpixel verwechselt werden könnte. Aus Lights gewonnen ist die Karte trotzdem brauchbar —
    sie ist nur etwas konservativer, weil sehr kleine, sehr helle Sterne dem Kriterium ähneln.
    Für Kameras ohne passende Darks (der Normalfall bei wechselnden Temperaturen) ist es der
    einzige Weg überhaupt.

    ZUR EMPFINDLICHKEIT: die Schwelle ist NICHT fest, sondern leitet sich je Aufnahme aus der
    gemessenen robusten Streuung (MAD) ab. Damit passt sie sich dem Sensor, dem Gain und der
    Temperatur von selbst an — eine feste Tabelle je Kameramodell wäre geraten, nicht gemessen.

    Gibt (maske, anzahl) zurück; maske ist bool in Sensorgröße, oder (None, 0).
    """
    import astro                                   # spät, um Ringimporte zu vermeiden
    q = str(quelle or "auto").lower()
    dark_pfade = list(darks or [])
    if q == "darks" and len(dark_pfade) < 5:
        log("    Defektkarte: Darks verlangt, aber keine (mind. 5) vorhanden — übersprungen")
        return None, 0
    if q != "lights" and len(dark_pfade) >= 5:
        pfade = dark_pfade
        log("    Defektkarte: aus %d Darks (die bessere Quelle — kein Sternlicht)" % len(pfade))
    else:
        pfade = list(paths)
        if dark_pfade and q == "lights":
            log("    Defektkarte: bewusst aus den Lights, obwohl Darks vorliegen")
    if len(pfade) < 5:
        log("    Defektkarte: mindestens 5 Aufnahmen nötig — übersprungen")
        return None, 0
    if len(pfade) > max_frames:
        idx = np.linspace(0, len(pfade) - 1, max_frames).astype(int)
        pfade = [pfade[i] for i in sorted(set(idx))]

    treffer = None
    gezaehlt = 0
    for p in pfade:
        f = astro._read_float(p)
        if f is None:
            continue
        g = f.mean(axis=2).astype(np.float32) if f.ndim == 3 else f.astype(np.float32)
        if treffer is None:
            treffer = np.zeros(g.shape, np.uint16)
        elif g.shape != treffer.shape:
            continue
        # Abweichung gegenüber dem lokalen Median; robuste Streuung aus der MAD
        u16 = (np.clip(g, 0, 1) * 65535).astype(np.uint16)
        med = cv2.medianBlur(u16, 3).astype(np.float32) / 65535.0
        diff = g - med
        mad = float(np.median(np.abs(diff - np.median(diff)))) * 1.4826 + 1e-9
        treffer += (np.abs(diff) > sigma * mad).astype(np.uint16)
        gezaehlt += 1

    if treffer is None or gezaehlt < 5:
        log("    Defektkarte: zu wenige lesbare Aufnahmen — übersprungen")
        return None, 0
    maske = treffer >= max(3, int(round(mindest_anteil * gezaehlt)))
    n = int(maske.sum())
    anteil = 100.0 * n / maske.size
    log("    Defektkarte aus %d Aufnahmen: %d dauerhaft auffällige Pixel (%.4f %% des Sensors)"
        % (gezaehlt, n, anteil))
    # Plausibilitätsgrenze statt einer erfundenen Tabelle je Kameramodell: über 1 % ist keine
    # Defektkarte mehr, sondern ein Hinweis, dass etwas anderes schiefläuft (falsche Quelle,
    # stark verrauschte Frames, Bildfeld voller kleiner Sterne). Dann lieber nichts liefern,
    # als ein Prozent des Bildes wegzumedianen.
    if anteil > 1.0:
        log("    Defektkarte verworfen: %.2f %% wären unplausibel viele Defekte — vermutlich "
            "sehr verrauschte Aufnahmen oder ein sternreiches Feld. Lieber nichts ersetzen."
            % anteil)
        return None, 0
    return (maske if n else None), n


def defekte_ersetzen(f, maske):
    """Markierte Pixel durch den lokalen Median ersetzen (Siril `cosme`).

    Anders als eine Einzelbild-Kosmetik greift das NUR an den vorher bestimmten Stellen —
    echte Sterne bleiben also garantiert unangetastet, auch wenn sie klein und hell sind.
    """
    if f is None or maske is None:
        return f
    a = np.asarray(f, np.float32).copy()
    if a.shape[:2] != maske.shape:
        return f
    u16 = (np.clip(a, 0, 1) * 65535).astype(np.uint16)
    med = cv2.medianBlur(u16, 3).astype(np.float32) / 65535.0
    if a.ndim == 3:
        for c in range(a.shape[2]):
            kanal = a[..., c]
            kanal[maske] = med[..., c][maske] if med.ndim == 3 else med[maske]
            a[..., c] = kanal
    else:
        a[maske] = med[maske]
    return a


def karte_speichern(maske, pfad):
    """Defektkarte als Textdatei sichern (x y je Zeile), wie Sirils Bad-Pixel-Liste.
    So lässt sie sich einmal erzeugen und über eine ganze Session wiederverwenden."""
    if maske is None:
        return False
    try:
        ys, xs = np.where(maske)
        with open(pfad, "w", encoding="utf-8") as fh:
            fh.write("# ForgePix Defektkarte — je Zeile: x y (0-basiert)\n")
            for x, y in zip(xs, ys):
                fh.write("%d %d\n" % (int(x), int(y)))
        return True
    except OSError:
        return False


def karte_laden(pfad, form):
    """Defektkarte aus einer Textdatei lesen. `form` ist (hoehe, breite)."""
    try:
        maske = np.zeros(form, bool)
        with open(pfad, encoding="utf-8") as fh:
            for zeile in fh:
                zeile = zeile.strip()
                if not zeile or zeile.startswith("#"):
                    continue
                teile = zeile.split()
                if len(teile) < 2:
                    continue
                x, y = int(teile[0]), int(teile[1])
                if 0 <= y < form[0] and 0 <= x < form[1]:
                    maske[y, x] = True
        return maske if maske.any() else None
    except (OSError, ValueError):
        return None
