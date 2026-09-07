#!/usr/bin/env python3
"""
core/trainingspaare.py — Trainingsmaterial fuers Entrauschen aus den eigenen Naechten.

**Warum verrauschte Paare genuegen (Noise2Noise).** Ein Entrauscher braucht keine sauberen
Zielbilder. Zwei unabhaengig verrauschte Aufnahmen derselben Szene reichen, solange das
Rauschen mittelwertfrei und zwischen beiden unabhaengig ist — das Netz kann das Rauschen des
Zielbildes nicht vorhersagen und lernt daher, es wegzumitteln. Zwei Subs derselben Nacht
erfuellen genau das (Lehtinen u.a., 2018).

Das ist der Grund, warum eigene Aufnahmen hier besser sind als fremde Archivdaten: es gibt
davon tausende, sie stammen aus der Kamera, dem Himmel und dem Teleskop, um das es geht — und
sie brauchen keine Wahrheit, die es ohnehin nicht gaebe.

**Was hier NICHT geht, und warum es dabeisteht:**

* **Schaerfen.** Ein tieferer Stack ist nicht schaerfer, sondern derselbe Unschaerfegrad mit
  weniger Rauschen. In diesen Daten steckt keine schaerfere Wahrheit.
* **Gemischte Belichtungszeiten paaren.** Dann unterscheidet sich das SIGNAL und nicht nur das
  Rauschen, und das Netz lernt, Helligkeit umzurechnen statt zu entrauschen.
* **Aufnahmen aus verschiedenen Naechten paaren.** Anderer Himmel, andere Transparenz, oft
  andere Bildlage.

Drei Sorten Paar, alle aus derselben Serie:

    "n2n"       Sub A -> Sub B          beide verrauscht, klassisches Noise2Noise
    "tief"      wenige Subs -> viele    Ziel ist rauschaermer, aber nicht rauschfrei
    "kacheln"   dasselbe, in Ausschnitten
"""
import os
import random

import numpy as np
import cv2

from constants import log_print
import astro


def serien_finden(ordner, min_subs=20, log=log_print):
    """Serien gleicher Kamera UND gleicher Belichtung finden, die gross genug sind.

    Die Gruppierung laeuft ueber Kamera und Belichtungszeit, NICHT ueber den Objektnamen: in
    Alfreds Bestand heisst dieselbe Galaxie `M51`, `whirl`, `Whirlpool Galaxy` und
    `Whirlpool Galaxy(1)`. Wer nach Namen gruppiert, zerreisst die Serie — und paart im
    schlimmsten Fall Aufnahmen aus verschiedenen Naechten.
    """
    from astropy.io import fits
    gruppen = {}
    for wurzel, _unter, dateien in os.walk(ordner):
        for name in sorted(dateien):
            if os.path.splitext(name)[1].lower() not in (".fit", ".fits", ".fts"):
                continue
            p = os.path.join(wurzel, name)
            try:
                h = fits.getheader(p)
            except Exception:
                continue
            art = str(h.get("IMAGETYP", h.get("FRAME", ""))).strip().lower()
            if any(k in art for k in ("dark", "flat", "bias", "offset")) or "master" in art:
                continue
            t = h.get("EXPTIME", h.get("EXPOSURE"))
            try:
                t = round(float(t), 1)
            except (TypeError, ValueError):
                continue
            schluessel = (str(h.get("INSTRUME", "?")).strip(), t,
                          str(h.get("DATE-OBS", ""))[:10],       # Nacht
                          wurzel)                                # gleicher Ordner
            gruppen.setdefault(schluessel, []).append(p)
    brauchbar = {k: v for k, v in gruppen.items() if len(v) >= min_subs}
    log("    Trainingspaare: %d Serien mit mindestens %d Aufnahmen gefunden (von %d insgesamt)"
        % (len(brauchbar), min_subs, len(gruppen)))
    return brauchbar


def _ausrichten(bilder, log=log_print):
    """Auf das erste Bild ausrichten. Nicht ausrichtbare Frames fallen RAUS statt schief
    einzugehen — ein um zwei Pixel verschobenes Paar lehrt das Netz, Kanten zu verschieben."""
    ref = astro._gray(bilder[0])
    raus = [bilder[0]]
    verworfen = 0
    for f in bilder[1:]:
        M = astro._estimate_star_shift(ref, astro._gray(f))
        if M is None:
            verworfen += 1
            continue
        raus.append(cv2.warpAffine(f, M, (f.shape[1], f.shape[0]),
                                   flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE))
    if verworfen:
        log("    %d Aufnahme(n) nicht ausrichtbar — verworfen statt schief gepaart" % verworfen)
    return raus


def paare_aus_serie(pfade, art="n2n", kacheln=0, kachelgroesse=256, tief_n=4,
                    max_paare=200, seed=None, skala=1.0, log=log_print):
    """Trainingspaare aus EINER Serie erzeugen.

    Args:
        art: "n2n" (Sub gegen Sub), "tief" (wenige gegen alle) oder "kacheln".
        kacheln: bei >0 werden je Paar so viele zufaellige Ausschnitte gezogen.
        tief_n: wie viele Subs die Eingabeseite bei "tief" hat.
        skala: Verkleinerung beim Laden (1.0 = volle Aufloesung).

    Returns:
        Liste von (eingabe, ziel) — beide float32, gleiche Form.
    """
    rng = random.Random(seed)
    bilder = []
    for p in pfade:
        f = astro._read_float(p)
        if f is None:
            continue
        if f.ndim == 2:
            f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
        if skala != 1.0:
            f = cv2.resize(f, (0, 0), fx=skala, fy=skala)
        bilder.append(f)
    if len(bilder) < 2:
        return []
    bilder = _ausrichten(bilder, log=log)
    if len(bilder) < 2:
        return []

    paare = []
    if art == "tief":
        # Eingabe: wenige Subs. Ziel: ALLE. Das Ziel ist rauschaermer, aber nicht rauschfrei —
        # es bleibt eine Schaetzung, und genau so ist es im Docstring benannt.
        ziel = np.mean(np.stack(bilder), axis=0).astype(np.float32)
        indizes = list(range(len(bilder)))
        for _ in range(min(max_paare, max(1, len(bilder) // max(tief_n, 1)))):
            rng.shuffle(indizes)
            teil = [bilder[i] for i in indizes[:tief_n]]
            paare.append((np.mean(np.stack(teil), axis=0).astype(np.float32), ziel))
    else:
        # Noise2Noise: zwei VERSCHIEDENE Subs derselben Serie. Nie dasselbe Bild auf beiden
        # Seiten — dann waere die Aufgabe die Identitaet und das Netz lernte nichts.
        paarungen = [(a, b) for a in range(len(bilder)) for b in range(len(bilder)) if a != b]
        rng.shuffle(paarungen)
        for a, b in paarungen[:max_paare]:
            paare.append((bilder[a], bilder[b]))

    if kacheln > 0:
        h, w = paare[0][0].shape[:2]
        k = min(kachelgroesse, h, w)
        aus = []
        for ein, zi in paare:
            for _ in range(kacheln):
                y = rng.randrange(0, max(1, h - k + 1))
                x = rng.randrange(0, max(1, w - k + 1))
                aus.append((ein[y:y + k, x:x + k].copy(), zi[y:y + k, x:x + k].copy()))
        paare = aus
    log("    %d Paare erzeugt (Art %s, %d Aufnahmen)" % (len(paare), art, len(bilder)))
    return paare


def guete(paare):
    """Wie brauchbar sind die Paare? Gibt Kennzahlen statt eines Urteils.

    `rauschverhaeltnis` ist das Verhaeltnis der Rauschstaerken von Eingabe zu Ziel. Bei "n2n"
    liegt es bei etwa 1 (beide Seiten gleich verrauscht, so soll es sein), bei "tief" ueber 1
    (das Ziel ist ruhiger). Liegt es UNTER 1, sind Eingabe und Ziel vertauscht.
    """
    if not paare:
        return {"anzahl": 0}

    def rauschen(x):
        g = astro._gray(x) if x.ndim == 3 else x
        d = g <= np.percentile(g, 40)
        v = g[d]
        return float(np.median(np.abs(v - np.median(v))) * 1.4826)

    re = [rauschen(e) for e, _ in paare[:20]]
    rz = [rauschen(z) for _, z in paare[:20]]
    m_e, m_z = float(np.median(re)), float(np.median(rz))
    return {"anzahl": len(paare), "form": tuple(paare[0][0].shape),
            "rauschen_eingabe": m_e, "rauschen_ziel": m_z,
            "rauschverhaeltnis": (m_e / m_z) if m_z > 1e-12 else None}
