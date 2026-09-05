#!/usr/bin/env python3
"""
core/photometrie.py — echte Messphotometrie: Lichtkurven aus einer Aufnahmeserie.

Nicht zu verwechseln mit `core/photometric.py`: das dort ist Farbkalibrierung (PCC), also
Bildbearbeitung. Hier geht es um Messung — wie hell ist dieser Stern, und wie ändert sich das
über die Nacht? Damit werden veränderliche Sterne, Bedeckungsveränderliche und
Exoplaneten-Transite erfasst; die Ergebnisse lassen sich an die AAVSO melden.

Das Verfahren ist Blenden-Photometrie mit Ringhintergrund (aperture photometry):

    Fluss = Σ(Blende) − Fläche(Blende) · Median(Ring)

Der Ring liegt um die Blende herum und schätzt den Himmel DORT, nicht irgendwo im Bild — bei
einem Gradienten wäre alles andere falsch. Der Median statt des Mittels, weil im Ring fast immer
ein schwacher Stern mitliegt.

**Warum differentiell gemessen wird:** die absolute Helligkeit schwankt von Aufnahme zu Aufnahme
mit Dunst, Höhe über dem Horizont und Fokus. Diese Schwankung trifft aber ALLE Sterne im Feld
gleich. Wird der Zielstern gegen die Summe mehrerer Vergleichssterne gerechnet, fällt sie heraus.
Genau deshalb ist Photometrie mit einer einfachen Kamera überhaupt möglich.

**Was diese Messung NICHT ist:** eine absolute Helligkeitsbestimmung. Ohne Standardsterne und
Farbterme kommt eine INSTRUMENTELLE Helligkeit heraus. Wer absolute Werte braucht, muss die
Vergleichssterne aus einem Katalog nehmen und den Farbterm bestimmen — `aavso_export()` schreibt
darum den Nullpunkt mit und markiert die Werte klar als instrumentell, wenn keine
Katalog-Helligkeit angegeben wurde.

Und noch eine Warnung, die zusammengehört: auf Bildern, durch die `astro.synthstar()` gelaufen
ist, darf hier nicht gemessen werden. Dort ist die Sternform erfunden.
"""
import math
import os
from datetime import datetime, timezone

import numpy as np
import cv2

from constants import log_print
import astro


# --------------------------------------------------------------------------- Messung
def _ringe(form, x, y, r_blende, r_innen, r_aussen):
    """Boolesche Masken für Blende und Hintergrundring um (x, y)."""
    h, w = form[:2]
    x0, y0 = max(0, int(x - r_aussen) - 1), max(0, int(y - r_aussen) - 1)
    x1, y1 = min(w, int(x + r_aussen) + 2), min(h, int(y + r_aussen) + 2)
    if x1 <= x0 or y1 <= y0:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float64)
    d2 = (xx - x) ** 2 + (yy - y) ** 2
    return (slice(y0, y1), slice(x0, x1),
            d2 <= r_blende * r_blende,
            (d2 >= r_innen * r_innen) & (d2 <= r_aussen * r_aussen))


def schwerpunkt(bild, x, y, radius=6):
    """Den Stern im Fenster neu einfangen (flussgewichteter Schwerpunkt).

    Unverzichtbar: zwischen zwei Aufnahmen wandert das Feld um einige Pixel. Wer starr an der
    einmal angegebenen Position misst, misst nach einer Stunde den Himmel daneben.
    """
    lum = astro._gray(bild) if bild.ndim == 3 else bild
    h, w = lum.shape[:2]
    x0, y0 = max(0, int(x) - radius), max(0, int(y) - radius)
    x1, y1 = min(w, int(x) + radius + 1), min(h, int(y) + radius + 1)
    z = lum[y0:y1, x0:x1].astype(np.float64)
    if z.size == 0:
        return None
    z = z - float(np.median(z))
    z = np.clip(z, 0, None)
    s = float(z.sum())
    if s <= 1e-9:
        return None
    yy, xx = np.mgrid[0:(y1 - y0), 0:(x1 - x0)].astype(np.float64)
    return (x0 + float((z * xx).sum() / s), y0 + float((z * yy).sum() / s))


def fluss_messen(bild, x, y, r_blende=5.0, r_innen=9.0, r_aussen=14.0, nachfuehren=True):
    """Blenden-Photometrie an einer Stelle. Gibt ein dict oder None zurück.

    Enthält `fluss`, `himmel` (je Pixel), `snr`, die tatsächlich benutzte Position und
    `gesaettigt` — ein ausgefressener Stern liefert einen zu KLEINEN Fluss, und das
    stillschweigend, weil oben einfach Werte fehlen. Deshalb wird es mitgemeldet.
    """
    lum = astro._gray(bild) if bild.ndim == 3 else np.asarray(bild, np.float32)
    if nachfuehren:
        neu = schwerpunkt(lum, x, y, radius=int(max(r_blende * 1.5, 5)))
        if neu is not None:
            x, y = neu
    teile = _ringe(lum.shape, x, y, r_blende, r_innen, r_aussen)
    if teile is None:
        return None
    sy, sx, blende, ring = teile
    z = lum[sy, sx].astype(np.float64)
    if blende.sum() < 3 or ring.sum() < 10:
        return None
    himmel = float(np.median(z[ring]))
    himmel_streu = float(np.median(np.abs(z[ring] - himmel))) * 1.4826
    n_pix = float(blende.sum())
    fluss = float(z[blende].sum()) - n_pix * himmel
    rauschen = himmel_streu * math.sqrt(n_pix) + 1e-12
    return {"x": float(x), "y": float(y), "fluss": fluss, "himmel": himmel,
            "snr": fluss / rauschen, "pixel": int(n_pix),
            "gesaettigt": bool(float(z[blende].max()) >= 0.995)}


def instrumentelle_helligkeit(fluss, nullpunkt=25.0):
    """−2,5·log10(Fluss) + Nullpunkt. Bei Fluss ≤ 0 (zu schwach) None statt eines Fantasiewerts."""
    if fluss is None or fluss <= 0:
        return None
    return -2.5 * math.log10(fluss) + float(nullpunkt)


# --------------------------------------------------------------------- Zeit und Serie
def _zeitpunkt(pfad):
    """Aufnahmezeit als datetime (UTC) aus DATE-OBS, sonst die Änderungszeit der Datei."""
    if os.path.splitext(pfad)[1].lower() in (".fit", ".fits", ".fts"):
        try:
            from astropy.io import fits
            s = str(fits.getheader(pfad).get("DATE-OBS", "")).strip()
            if s:
                d = datetime.fromisoformat(s.replace("Z", ""))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    try:
        return datetime.fromtimestamp(os.path.getmtime(pfad), tz=timezone.utc)
    except OSError:
        return None


def julianisches_datum(zeit):
    """JD aus einem datetime. Die AAVSO erwartet JD, keine Kalenderzeit."""
    if zeit is None:
        return None
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    # Unix-Epoche 1970-01-01 00:00 UTC = JD 2440587.5
    return 2440587.5 + zeit.timestamp() / 86400.0


def lichtkurve(paths, ziel, vergleich, r_blende=5.0, r_innen=9.0, r_aussen=14.0,
               nullpunkt=25.0, katalog_helligkeit=None, log=log_print):
    """Differentielle Lichtkurve über eine Aufnahmeserie.

    Args:
        paths: die Aufnahmen, in beliebiger Reihenfolge (sortiert wird nach Zeit).
        ziel: (x, y) des Zielsterns in der ERSTEN Aufnahme.
        vergleich: Liste von (x, y) der Vergleichssterne. Mindestens einer, besser drei —
            ein einzelner Vergleichsstern, der selbst veränderlich ist, verdirbt die ganze
            Messreihe, und mit dreien fällt so einer durch die Streuung auf.
        katalog_helligkeit: bekannte Helligkeit der Vergleichssumme. Nur damit werden aus
            instrumentellen Werten echte.

    Returns:
        dict mit `punkte` (je Aufnahme ein dict), `streuung_vergleich` (die Vergleichssterne
        gegeneinander — das ist die ehrliche Messgenauigkeit) und `instrumentell` (bool).
    """
    if not paths or not vergleich:
        return None
    reihen = []
    for p in paths:
        z = _zeitpunkt(p)
        reihen.append((julianisches_datum(z) or 0.0, p))
    reihen.sort()

    punkte = []
    einzeln = [[] for _ in vergleich]
    for jd, p in reihen:
        f = astro._read_float(p)
        if f is None:
            continue
        mz = fluss_messen(f, ziel[0], ziel[1], r_blende, r_innen, r_aussen)
        if mz is None or mz["fluss"] <= 0:
            log("    Photometrie: %s — Zielstern nicht messbar" % os.path.basename(p))
            continue
        fl_v, ok = [], True
        for k, (vx, vy) in enumerate(vergleich):
            mv = fluss_messen(f, vx, vy, r_blende, r_innen, r_aussen)
            if mv is None or mv["fluss"] <= 0:
                ok = False
                break
            fl_v.append(mv["fluss"])
            einzeln[k].append(mv["fluss"])
        if not ok:
            log("    Photometrie: %s — Vergleichsstern nicht messbar" % os.path.basename(p))
            continue
        summe_v = float(sum(fl_v))
        # Der differentielle Wert: Ziel gegen die Vergleichssumme. Dunst, Hoehe und Fokus
        # treffen beide gleich und fallen hier heraus.
        delta = -2.5 * math.log10(mz["fluss"] / summe_v)
        punkte.append({
            "jd": jd, "datei": os.path.basename(p),
            "fluss": mz["fluss"], "vergleich_fluss": summe_v,
            "delta_mag": delta,
            "mag": (delta + float(katalog_helligkeit)) if katalog_helligkeit is not None
                   else instrumentelle_helligkeit(mz["fluss"], nullpunkt),
            "snr": mz["snr"], "gesaettigt": mz["gesaettigt"],
            "x": mz["x"], "y": mz["y"],
        })

    if not punkte:
        return None
    # Ehrliche Messgenauigkeit: wie stabil sind die Vergleichssterne UNTEREINANDER? Was dort
    # an Streuung uebrig bleibt, ist die Untergrenze fuer alles, was am Ziel gemessen wird.
    streuung = None
    if len(vergleich) >= 2 and all(len(e) == len(einzeln[0]) for e in einzeln) and einzeln[0]:
        arr = np.asarray(einzeln, np.float64)
        verh = -2.5 * np.log10(arr[0] / np.maximum(arr[1:].sum(axis=0), 1e-12))
        streuung = float(np.std(verh))
    # Zeitachse pruefen. Ohne DATE-OBS faellt `_zeitpunkt` auf die Aenderungszeit der Datei
    # zurueck — und wenn eine Serie in einem Rutsch konvertiert wurde, tragen alle Dateien
    # dieselbe Sekunde. Die Lichtkurve sieht dann vollstaendig normal aus, jede Periodensuche
    # darauf ist aber Unsinn (im Test kam 24,00 h statt 3,00 h heraus). Das muss auffallen.
    spanne_h = (max(q["jd"] for q in punkte) - min(q["jd"] for q in punkte)) * 24.0
    zeit_brauchbar = spanne_h > 1e-3
    if not zeit_brauchbar:
        log("    Photometrie: ACHTUNG — alle Aufnahmen tragen dieselbe Zeit (Spanne %.5f h). "
            "Ohne DATE-OBS im Header ist die Zeitachse unbrauchbar; Periodensuche und "
            "AAVSO-Meldung sind damit sinnlos." % spanne_h)
    gesaettigt = sum(1 for p in punkte if p["gesaettigt"])
    if gesaettigt:
        log("    Photometrie: %d von %d Messungen ausgefressen — diese Werte sind ZU KLEIN "
            "und gehoeren nicht in eine Meldung" % (gesaettigt, len(punkte)))
    log("    Photometrie: %d Messpunkte, Streuung der Vergleichssterne %s"
        % (len(punkte), ("%.4f mag" % streuung) if streuung is not None
           else "nicht bestimmbar (nur ein Vergleichsstern)"))
    return {"punkte": punkte, "streuung_vergleich": streuung,
            "instrumentell": katalog_helligkeit is None,
            "gesaettigt": gesaettigt, "zeit_brauchbar": zeit_brauchbar,
            "spanne_stunden": spanne_h}


def periode_schaetzen(punkte, min_stunden=0.2, max_stunden=24.0, schritte=2000):
    """Grobe Periodensuche (Lomb-Scargle von Hand, ohne scipy).

    Für Bedeckungsveränderliche und Pulsationsveränderliche reicht das, um eine Hausnummer zu
    bekommen. Es ist ausdrücklich KEINE Ersatzanalyse — bei ungleichen Abständen und wenigen
    Nächten liefert jede Periodensuche Nebenmaxima, und die sehen echt aus. Darum kommt die
    Stärke des Maximums mit zurück: ist sie klein, ist die Periode geraten.
    """
    if not punkte or len(punkte) < 8:
        return None
    t = np.asarray([p["jd"] for p in punkte], np.float64) * 24.0     # Stunden
    if float(t.max() - t.min()) < 1e-3:
        # Ohne echte Zeitachse ist jede Periode geraten. Lieber nichts als eine Zahl, die
        # aussieht wie ein Ergebnis.
        return None
    y = np.asarray([p["delta_mag"] for p in punkte], np.float64)
    t = t - t.mean()
    y = y - y.mean()
    if float(np.std(y)) < 1e-9:
        return None
    perioden = np.linspace(float(min_stunden), float(max_stunden), int(schritte))
    staerke = np.zeros_like(perioden)
    for i, P in enumerate(perioden):
        w = 2.0 * np.pi / P
        c, s = np.cos(w * t), np.sin(w * t)
        # kleinste Quadrate an eine Sinusschwingung: erklaerter Varianzanteil
        A = np.vstack([c, s]).T
        try:
            loesung, *_ = np.linalg.lstsq(A, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        rest = y - A @ loesung
        staerke[i] = 1.0 - float(rest.var()) / float(y.var())
    k = int(np.argmax(staerke))
    return {"periode_stunden": float(perioden[k]), "staerke": float(staerke[k]),
            "kurve": (perioden, staerke)}


# ------------------------------------------------------------------------ AAVSO-Export
def aavso_export(kurve, datei, stern, filter_="CV", beobachter="UNKNOWN",
                 vergleich_name="ENSEMBLE", vergleich_mag="na", check_name="na",
                 check_mag="na", log=log_print):
    """Lichtkurve im AAVSO Extended File Format schreiben.

    Das Format ist zeilenweise Text mit einem Kopf aus `#`-Zeilen. Pflichtfelder sind Name,
    JD, Helligkeit, Filter und Beobachterkürzel.

    Zwei Dinge werden bewusst NICHT verschwiegen:
      * Sind die Werte instrumentell (kein Katalogbezug), steht das als Kommentar im Kopf UND
        im Bemerkungsfeld jeder Zeile. Instrumentelle Werte ohne Kennzeichnung in eine Datenbank
        zu geben, wäre der schlimmste denkbare Fehler dieses Moduls.
      * Ausgefressene Messungen werden übersprungen und im Kopf gezählt. Ihr Fluss ist zu klein,
        und zwar systematisch — als Messpunkt wären sie schlicht falsch.

    Der Filterschlüssel `CV` heisst bei der AAVSO „clear, mit V verglichen" und ist für
    Aufnahmen ohne Photometriefilter der ehrliche Eintrag.
    """
    if not kurve or not kurve.get("punkte"):
        return False
    unsicher = kurve.get("streuung_vergleich")
    zeilen = [
        "#TYPE=EXTENDED",
        "#OBSCODE=%s" % beobachter,
        "#SOFTWARE=ForgePix",
        "#DELIM=,",
        "#DATE=JD",
        "#OBSTYPE=CCD",
    ]
    if kurve.get("instrumentell"):
        zeilen.append("#Hinweis: INSTRUMENTELLE Helligkeiten ohne Katalogbezug — "
                      "nicht als absolute Werte verwenden.")
    if kurve.get("zeit_brauchbar") is False:
        log("    AAVSO-Export abgelehnt: alle Aufnahmen tragen dieselbe Zeit. Eine Meldung mit "
            "unbrauchbarer Zeitachse waere schlimmer als keine.")
        return False
    if unsicher is not None:
        zeilen.append("#Streuung der Vergleichssterne untereinander: %.4f mag" % unsicher)
    uebersprungen = 0
    daten = []
    for p in kurve["punkte"]:
        if p.get("gesaettigt"):
            uebersprungen += 1
            continue
        if p.get("mag") is None:
            uebersprungen += 1
            continue
        bemerkung = "instrumentell" if kurve.get("instrumentell") else "na"
        daten.append(",".join([
            str(stern), "%.5f" % p["jd"], "%.4f" % p["mag"],
            ("%.4f" % unsicher) if unsicher is not None else "na",
            str(filter_), "NO", "STD", str(vergleich_name), str(vergleich_mag),
            str(check_name), str(check_mag), "na", "na", "na", bemerkung,
        ]))
    if uebersprungen:
        zeilen.append("#%d Messungen ausgelassen (ausgefressen oder nicht messbar)"
                      % uebersprungen)
    zeilen.append("#NAME,DATE,MAG,MERR,FILT,TRANS,MTYPE,CNAME,CMAG,KNAME,KMAG,AIRMASS,"
                  "GROUP,CHART,NOTES")
    zeilen.extend(daten)
    if not daten:
        log("    AAVSO-Export: keine brauchbare Messung uebrig — nichts geschrieben")
        return False
    with open(datei, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(zeilen) + "\n")
    log("    AAVSO-Export: %d Messungen nach %s (%d ausgelassen)"
        % (len(daten), os.path.basename(datei), uebersprungen))
    return True


def kurve_zeichnen(kurve, datei, breite=900, hoehe=420):
    """Die Lichtkurve als Bild — zum Ansehen, nicht zum Auswerten.

    Helligkeit läuft nach OBEN heller, die Achse ist also umgedreht. Das ist in der Astronomie
    so üblich und für jeden verwirrend, der es nicht erwartet; darum steht es auch im Bild.
    """
    if not kurve or not kurve.get("punkte"):
        return False
    p = kurve["punkte"]
    t = np.asarray([q["jd"] for q in p], np.float64)
    y = np.asarray([q["delta_mag"] for q in p], np.float64)
    t = (t - t.min()) * 24.0
    bild = np.full((hoehe, breite, 3), 250, np.uint8)
    rand = 60
    tw = max(float(t.max()), 1e-6)
    ymin, ymax = float(y.min()), float(y.max())
    yspan = max(ymax - ymin, 1e-4)
    def px(i):
        x = rand + (t[i] / tw) * (breite - 2 * rand)
        # umgedreht: kleinere Magnitude = heller = weiter oben
        yy = rand + ((y[i] - ymin) / yspan) * (hoehe - 2 * rand)
        return int(x), int(yy)
    cv2.rectangle(bild, (rand, rand), (breite - rand, hoehe - rand), (200, 200, 200), 1)
    for i in range(len(t)):
        cv2.circle(bild, px(i), 3, (40, 40, 200), -1)
    cv2.putText(bild, "Stunden seit Beginn", (rand, hoehe - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 80, 80), 1, cv2.LINE_AA)
    cv2.putText(bild, "delta mag (unten = heller)", (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 80, 80), 1, cv2.LINE_AA)
    from constants import imwrite
    return bool(imwrite(datei, bild))
