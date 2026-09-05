#!/usr/bin/env python3
"""
core/masken.py — Masken: einen Arbeitsschritt nur dort wirken lassen, wo er hingehört.

Das ist der eigentliche Grund, warum PixInsight so viel mehr kann als eine Kette fester
Werkzeuge: dort lässt sich JEDER Schritt durch eine Maske hindurch anwenden. Entrauschen gehört
in den Hintergrund und nicht in die Sterne; lokaler Kontrast gehört in den Nebel und nicht in
den Himmel; eine Sättigungsanhebung im Rauschen macht das Bild nur bunter, nicht besser.

Der Baukasten hier ist klein und absichtlich langweilig:

    maske = masken.hintergrund(bild)            # oder sterne() / nebel() / helligkeit()
    ergebnis = masken.anwenden(bild, maske, astro.tv_denoise(bild, 0.5))

`anwenden()` mischt: wo die Maske 1 ist, gilt das bearbeitete Bild, wo sie 0 ist, das Original.
Weiche Übergänge sind der Normalfall — eine harte Kante zwischen bearbeitet und unbearbeitet
sieht man im fertigen Bild sofort als Umriss.

Alle Masken sind float32 in [0..1] und einkanalig, unabhängig davon, ob das Bild Farbe hat.
"""
import numpy as np
import cv2

from constants import log_print
import astro


def _lum(bild):
    return astro._gray(bild) if bild.ndim == 3 else np.asarray(bild, np.float32)


def helligkeit(bild, von=0.0, bis=1.0, weich=0.05):
    """Bereichsmaske: 1 zwischen `von` und `bis`, mit weichen Flanken der Breite `weich`.

    Das Pendant zu PixInsights RangeSelection. Nützlich, um etwa nur die mittleren Helligkeiten
    anzufassen — Himmel unten, ausgebrannte Sterne oben bleiben aussen vor.
    """
    l = np.clip(_lum(bild), 0, 1)
    w = max(float(weich), 1e-4)
    unten = np.clip((l - float(von)) / w, 0, 1)
    oben = np.clip((float(bis) - l) / w, 0, 1)
    return (unten * oben).astype(np.float32)


def sterne(bild, empfindlichkeit=6.0, min_flaeche=4, max_flaeche=2000,
           weiten=1, weich=1.0, log=log_print):
    """Sternmaske, eigenständig gerechnet — NICHT über `astro.remove_stars`.

    Warum eigenständig: `remove_stars` ist auf LINEARE Subs ausgelegt und nimmt dort jeden Blob
    ab einem einzigen Pixel mit. Auf einem GESTRECKTEN Bild ist das fatal, weil die Streckung
    das Rauschen mit anhebt: an einem echten Stack (10 Subs M27, gestreckt) kamen so 94 % des
    Bildes als „Stern" heraus. Mit einer Mindestfläche und einer Schwelle, die auf der
    vorzeichenbehafteten Streuung beruht, bleiben davon wenige Prozent übrig.

    Gefiltert wird nach Fläche UND Rundheit: ein Stern ist kompakt und etwa rund, ein
    Nebelfilament nicht.
    """
    l = _lum(bild)
    hg = cv2.medianBlur((np.clip(l, 0, 1) * 255).astype(np.uint8), 31).astype(np.float32) / 255.0
    rest = l - hg                                    # vorzeichenbehaftet, s. astro.remove_stars
    med = float(np.median(rest))
    mad = float(np.median(np.abs(rest - med))) * 1.4826 + 1e-9
    roh = (rest > med + float(empfindlichkeit) * mad).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(roh, 8)
    m = np.zeros_like(roh)
    behalten = 0
    for i in range(1, n):
        flaeche = int(stats[i, cv2.CC_STAT_AREA])
        if not (min_flaeche <= flaeche <= max_flaeche):
            continue
        bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        if bw <= 0 or bh <= 0 or not (0.35 <= bw / bh <= 2.9):
            continue
        m[lab == i] = 1
        behalten += 1
    if weiten > 0:
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                    (2 * int(weiten) + 1,) * 2))
    mf = m.astype(np.float32)
    if weich > 0:
        mf = cv2.GaussianBlur(mf, (0, 0), float(weich))
    return np.clip(mf, 0, 1)


def hintergrund(bild, quantil=60.0, weich=2.0, stern_maske=None):
    """Alles, was WEDER Stern NOCH Struktur ist — der leere Himmel.

    Zwei Bedingungen zusammen: dunkler als das `quantil`-Perzentil UND nicht in der Sternmaske.
    Die Helligkeitsschwelle allein reicht nicht, weil ein schwacher Stern im Aussenbereich
    dunkler sein kann als heller Nebel.

    `stern_maske` erspart den teuersten Teil: die Sternerkennung läuft sonst je Maske erneut,
    und sie ist mit Abstand der langsamste Schritt. Wer Hintergrund UND Nebel braucht, rechnet
    `sterne()` einmal und reicht das Ergebnis hier durch.
    """
    l = _lum(bild)
    schwelle = float(np.percentile(l, quantil))
    spanne = max(schwelle - float(np.percentile(l, 5)), 1e-4)
    dunkel = np.clip((schwelle - l) / spanne, 0, 1)
    sm = sterne(bild) if stern_maske is None else np.asarray(stern_maske, np.float32)
    m = np.clip(dunkel * (1.0 - sm), 0, 1)
    return cv2.GaussianBlur(m, (0, 0), float(weich)).astype(np.float32) if weich > 0 else m


def nebel(bild, quantil=60.0, weich=2.0, stern_maske=None):
    """Struktur ohne Sterne: heller als der Himmel, aber kein Stern.

    Genau der Bereich, in den lokaler Kontrast und Sättigung gehören. Im Himmel würden beide
    nur das Rauschen betonen — das ist an echten Daten schon einmal schiefgegangen und der
    Grund, warum es diese Maske gibt.
    """
    l = _lum(bild)
    sm = sterne(bild) if stern_maske is None else np.asarray(stern_maske, np.float32)
    schwelle = float(np.percentile(l, quantil))
    # Die Obergrenze OHNE Sterne bestimmen. Mit ihnen setzen wieder die hellsten Punkte im Bild
    # die Skala — dieselbe Ursache wie beim Weißpunkt der Streckung: ein Nebel bei 0,5 gegen
    # Sterne bei 1,0 kam so nur auf einen Maskenwert von 0,41 statt auf 1,0, und die Maske hat
    # dann genau dort am wenigsten gewirkt, wo sie gebraucht wird.
    ohne_sterne = l[sm < 0.2]
    obergrenze = float(np.percentile(ohne_sterne if ohne_sterne.size > 100 else l, 99.5))
    spanne = max(obergrenze - schwelle, 1e-4)
    hell = np.clip((l - schwelle) / spanne, 0, 1)
    m = np.clip(hell * (1.0 - sm), 0, 1)
    return cv2.GaussianBlur(m, (0, 0), float(weich)).astype(np.float32) if weich > 0 else m


def invertieren(maske):
    return np.clip(1.0 - np.asarray(maske, np.float32), 0, 1)


def weichzeichnen(maske, sigma=2.0):
    if sigma <= 0:
        return maske
    return cv2.GaussianBlur(np.asarray(maske, np.float32), (0, 0), float(sigma))


def verstaerken(maske, gamma=1.0):
    """Maske härter (gamma < 1) oder weicher (gamma > 1) machen."""
    g = max(float(gamma), 1e-3)
    return np.clip(np.asarray(maske, np.float32), 0, 1) ** g


def anwenden(original, maske, bearbeitet):
    """Bearbeitetes Bild durch die Maske hindurch auf das Original legen.

    Verträgt einkanalige Masken auf Farbbildern und umgekehrt; ungleiche Grössen werden
    abgelehnt statt stillschweigend skaliert — eine verrutschte Maske sieht man dem Ergebnis
    nicht an, und genau solche Fehler sind hinterher am teuersten zu finden.
    """
    a = np.asarray(original, np.float32)
    b = np.asarray(bearbeitet, np.float32)
    if a.shape != b.shape:
        raise ValueError("Original %s und bearbeitetes Bild %s passen nicht zusammen"
                         % (a.shape, b.shape))
    m = np.clip(np.asarray(maske, np.float32), 0, 1)
    if m.shape[:2] != a.shape[:2]:
        raise ValueError("Maske %s passt nicht zum Bild %s" % (m.shape[:2], a.shape[:2]))
    if a.ndim == 3 and m.ndim == 2:
        m = m[..., None]
    return np.clip(a * (1.0 - m) + b * m, 0, 1)


def anteil(maske):
    """Wie viel des Bildes deckt die Maske ab (0..1)? Für Log-Ausgaben und Plausibilität —
    eine Sternmaske über 10 % des Bildes ist keine Sternmaske mehr."""
    return float(np.clip(np.asarray(maske, np.float32), 0, 1).mean())
