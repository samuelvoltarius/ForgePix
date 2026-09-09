#!/usr/bin/env python3
"""
core/pcc_echt.py — photometrische Farbkalibrierung gegen KATALOGFARBEN.

Der Unterschied zum Stern-Weissabgleich ist grundsaetzlich, nicht graduell:

* Ein **Weissabgleich** macht den DURCHSCHNITTSSTERN des Bildes neutral. Welche Farbe dabei
  herauskommt, haengt davon ab, welche Sterne zufaellig im Feld stehen — ein Feld voller roter
  Riesen wird blaustichig korrigiert. Und weil er alle Sterne zur Mitte zieht, daempft er ihre
  Farbunterschiede: an M51 gemessen fiel die Farbspreizung der Sterne von 27 auf 5.
* Eine **Farbkalibrierung** nutzt, dass jeder Katalogstern eine BEKANNTE Farbe hat (Gaia
  BP-RP). Sie misst, wie sich die gemessenen Kanalverhaeltnisse mit dieser bekannten Farbe
  aendern, und setzt den Nullpunkt auf eine DEFINIERTE Sternfarbe. Welche Sterne im Feld
  stehen, ist dann fast egal.

Verfahren:

1. Die Bildsterne ueber die Astrometrie den Katalogsternen zuordnen.
2. Je Stern die Fluesse in B, G und R messen (Blende minus lokaler Untergrund).
3. Die gemessenen Farbindizes log(B/G) und log(R/G) gegen BP-RP auftragen.
4. Robust eine Gerade durchlegen und ablesen, was sie bei der Bezugsfarbe sagt.
5. Die Kanaele so skalieren, dass ein Stern dieser Bezugsfarbe neutral herauskommt.

Bezugsfarbe ist BP-RP = 0,82 — die Farbe der Sonne. Ein sonnenaehnlicher Stern erscheint
danach weiss, alles andere behaelt seine Farbe RELATIV dazu. Das ist die uebliche Festlegung
(G2V-Weisspunkt); sie ist eine KONVENTION und wird darum im Bericht genannt.

GRENZEN, ehrlich:

* Ohne hinterlegte Kamera-Empfindlichkeitskurve ist das eine EMPIRISCHE Kalibrierung: sie
  macht die Farben untereinander stimmig und setzt den Nullpunkt, sie liefert aber keine
  absoluten Farbtemperaturen.
* Gemessen wird auf dem LINEAREN Bild. Auf gestreckten Daten waeren die Verhaeltnisse verzerrt.
* Gesaettigte Sterne und solche mit Nachbarn fallen heraus; bleiben zu wenige, wird abgebrochen
  statt geraten.
"""
import numpy as np
import cv2

try:
    from constants import log_print, ForgePixFehler
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)

    class ForgePixFehler(RuntimeError):
        pass


# Farbindex der Sonne in Gaia-Baendern. Wer einen anderen Weisspunkt will, setzt ihn hier —
# und muss ihn dann auch nennen, sonst ist die Farbe nicht nachvollziehbar.
BEZUGSFARBE_BP_RP = 0.82
MIN_STERNE = 20


def _flux(bild, x, y, blende=6, ring_innen=9, ring_aussen=14):
    """Fluss eines Sterns je Kanal: Blende minus lokaler Untergrund.

    Der Untergrund kommt aus einem Ring um den Stern (Median, nicht Mittel — ein Nachbarstern
    im Ring wuerde den Mittelwert verziehen und den Fluss kleinrechnen).
    """
    h, w = bild.shape[:2]
    xi, yi = int(round(x)), int(round(y))
    if not (ring_aussen < xi < w - ring_aussen and ring_aussen < yi < h - ring_aussen):
        return None
    aus = bild[yi-ring_aussen:yi+ring_aussen+1, xi-ring_aussen:xi+ring_aussen+1]
    n = 2 * ring_aussen + 1
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot(yy - ring_aussen, xx - ring_aussen)
    in_blende = r <= blende
    im_ring = (r >= ring_innen) & (r <= ring_aussen)
    if not (in_blende.any() and im_ring.any()):
        return None
    kanaele = []
    for k in range(aus.shape[2]):
        ebene = aus[..., k]
        untergrund = float(np.median(ebene[im_ring]))
        kanaele.append(float(ebene[in_blende].sum() - untergrund * in_blende.sum()))
    return kanaele


def _robuste_gerade(x, y):
    """Steigung und Achsenabschnitt, robust gegen Ausreisser (Theil-Sen-Prinzip).

    Ein gewoehnlicher Fit laesst sich von einem einzigen falsch zugeordneten Stern verziehen,
    und falsche Zuordnungen gibt es in dichten Feldern immer.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = len(x)
    if n < 3:
        return float("nan"), float("nan")
    # Bei vielen Punkten nicht alle Paare bilden — eine Stichprobe reicht und ist schnell.
    rng = np.random.default_rng(97)
    if n > 120:
        i = rng.integers(0, n, 4000)
        j = rng.integers(0, n, 4000)
    else:
        i, j = np.triu_indices(n, 1)
    dx = x[j] - x[i]
    gut = np.abs(dx) > 1e-6
    if not gut.any():
        return float("nan"), float("nan")
    steigungen = (y[j][gut] - y[i][gut]) / dx[gut]
    b = float(np.median(steigungen))
    a = float(np.median(y - b * x))
    return b, a


def farbkalibrieren(bgr, sternpositionen, katalogfarben, bezugsfarbe=BEZUGSFARBE_BP_RP,
                    log=log_print):
    """Kanaele so skalieren, dass ein Stern der Bezugsfarbe neutral erscheint.

    Args:
        bgr: LINEARES BGR-Bild, float.
        sternpositionen: [(x, y), ...] der zugeordneten Bildsterne.
        katalogfarben: BP-RP je Stern, gleiche Reihenfolge.
        bezugsfarbe: BP-RP, bei dem das Ergebnis neutral sein soll.

    Returns:
        (kalibriertes Bild, Bericht)
    """
    a = np.asarray(bgr, np.float32)
    if a.ndim != 3 or a.shape[2] != 3:
        raise ForgePixFehler("Farbkalibrierung braucht ein BGR-Bild.")
    farben = np.asarray(katalogfarben, float)
    messungen, benutzte_farben = [], []
    for (x, y), c in zip(sternpositionen, farben):
        if not np.isfinite(c):
            continue
        f = _flux(a, x, y)
        if f is None:
            continue
        b, g, r = f
        # Ein Stern taugt nur, wenn alle drei Kanaele deutlich positiv sind. Negative oder
        # winzige Fluesse kommen von Fehlzuordnungen und von Sternen am Rauschgrund.
        if min(b, g, r) <= 0 or g < 1e-6:
            continue
        # Gesaettigte fallen heraus: dort ist das Verhaeltnis von der Saettigung bestimmt,
        # nicht von der Sternfarbe.
        h, w = a.shape[:2]
        xi, yi = int(round(x)), int(round(y))
        if float(a[max(0, yi-3):yi+4, max(0, xi-3):xi+4].max()) > 0.98:
            continue
        messungen.append((np.log(b / g), np.log(r / g)))
        benutzte_farben.append(c)

    if len(messungen) < MIN_STERNE:
        raise ForgePixFehler(
            "Farbkalibrierung: nur %d brauchbare Sterne (mindestens %d noetig). Lieber "
            "abbrechen als mit zu wenigen kalibrieren." % (len(messungen), MIN_STERNE))

    messungen = np.asarray(messungen)
    benutzte_farben = np.asarray(benutzte_farben)
    steig_b, ab_b = _robuste_gerade(benutzte_farben, messungen[:, 0])
    steig_r, ab_r = _robuste_gerade(benutzte_farben, messungen[:, 1])
    if not (np.isfinite(steig_b) and np.isfinite(steig_r)):
        raise ForgePixFehler("Farbkalibrierung: die Farbbeziehung liess sich nicht bestimmen.")

    # Was die Gerade bei der Bezugsfarbe sagt — genau das soll 0 werden (also B/G = R/G = 1).
    log_bg = ab_b + steig_b * bezugsfarbe
    log_rg = ab_r + steig_r * bezugsfarbe
    faktor_b = float(np.exp(-log_bg))
    faktor_r = float(np.exp(-log_rg))
    aus = a.copy()
    aus[..., 0] *= faktor_b
    aus[..., 2] *= faktor_r

    # Wie gut haelt die Beziehung? Die Streuung um die Gerade sagt, wie verlaesslich das ist.
    rest_b = messungen[:, 0] - (ab_b + steig_b * benutzte_farben)
    rest_r = messungen[:, 1] - (ab_r + steig_r * benutzte_farben)
    bericht = dict(sterne=len(messungen), bezugsfarbe=float(bezugsfarbe),
                   faktor_b=faktor_b, faktor_r=faktor_r,
                   steigung_b=float(steig_b), steigung_r=float(steig_r),
                   streuung_b=float(np.median(np.abs(rest_b)) * 1.4826),
                   streuung_r=float(np.median(np.abs(rest_r)) * 1.4826),
                   farbspanne=(float(benutzte_farben.min()), float(benutzte_farben.max())),
                   verfahren="Gaia BP-RP gegen gemessene Kanalverhaeltnisse, "
                             "Nullpunkt bei BP-RP=%.2f (G2V-Konvention)" % bezugsfarbe)
    log("    Farbkalibrierung: %d Sterne, BP-RP %.2f bis %.2f, Faktoren B=%.3f R=%.3f "
        "(Streuung %.3f / %.3f)"
        % (bericht["sterne"], bericht["farbspanne"][0], bericht["farbspanne"][1],
           faktor_b, faktor_r, bericht["streuung_b"], bericht["streuung_r"]))
    if abs(steig_b) < 0.05 and abs(steig_r) < 0.05:
        log("    ACHTUNG: die gemessenen Farben haengen kaum von der Katalogfarbe ab "
            "(Steigungen %.3f / %.3f). Das deutet auf Fehlzuordnungen oder zu wenig "
            "Farbspanne im Feld — die Kalibrierung ist dann nicht verlaesslich."
            % (steig_b, steig_r))
    return np.clip(aus, 0, None), bericht
