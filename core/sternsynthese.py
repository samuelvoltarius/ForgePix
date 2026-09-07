#!/usr/bin/env python3
"""
core/sternsynthese.py — Trainingspaare für die Sternentfernung, mit EXAKTER Wahrheit.

**Warum es keine „verlässlichen Masken" gibt — und warum das nicht schlimm ist.**

Der naheliegende Weg wäre: echte Aufnahmen nehmen, die Sterne darin maskieren, und daraus
lernen lassen. Das kann nicht funktionieren, und zwar aus einem grundsätzlichen Grund: die
Maske müsste von einer Sternerkennung kommen — also von genau dem Verfahren, das das Modell
später ersetzen soll. Das Modell kann dabei bestenfalls so gut werden wie die Erkennung, und
deren Fehler lernt es gleich mit. An echten Daten gemessen deckte die vorhandene Sternmaske
je nach Streckung zwischen 0,17 % und 94 % des Bildes ab; auf so etwas lässt sich nichts
aufbauen.

Der Weg herum ist umgekehrt und liefert eine **exakte** Wahrheit: man nimmt eine sternarme
Szene, RECHNET Sterne mit bekannter Form an bekannte Orte, und hat damit

    ohne_sterne   — die Wahrheit, exakt, weil sie vor dem Hinzufügen existierte
    mit_sternen   — die Eingabe
    maske         — fällt als Nebenprodukt ab, ebenfalls exakt

Keine Erkennung, kein Schätzen, kein Zirkelschluss. Die Maske entsteht hier nicht durch
Suchen, sondern durch Wissen.

**Was dabei echt sein muss, damit es etwas taugt:**

* Die **Sternform** kommt aus `astro.estimate_psf()` — gemessen an den eigenen Aufnahmen,
  nicht als Gauss angenommen. Ein Modell, das auf Gauss-Sternen trainiert wird, sieht die
  breiteren Flanken echter Sterne nie.
* Die **Helligkeitsverteilung** folgt einem Potenzgesetz: wenige helle, viele schwache. Wer
  gleichverteilt würfelt, bekommt ein Feld, das es am Himmel nicht gibt.
* Der **Untergrund** ist eine echte Aufnahme, nicht synthetisch. Nebelstruktur, Rauschen und
  Gradient sind damit real; nur die Sterne sind gerechnet.

**Ehrliche Grenze:** die Szene ist trotzdem nicht ganz sternlos — der Untergrund enthält
Reststerne, die dort nicht markiert sind. Für das Training bedeutet das, dass das Modell
lernt, die GERECHNETEN Sterne zu entfernen und die vorhandenen stehen zu lassen. Darum
gehört ein sternarmer Untergrund gewählt (Galaxienfeld, Nebeldetail), und `reststerne()`
misst, wie sauber er ist.
"""
import numpy as np
import cv2

from constants import log_print
import astro


def reststerne(bild, empfindlichkeit=6.0):
    """Wie sternarm ist eine Szene? Gibt den Flächenanteil erkannter Sterne in Prozent.

    Zur Auswahl des Untergrunds: je kleiner, desto sauberer wird die Wahrheit. Über etwa 1 %
    lohnt es sich, eine andere Stelle zu nehmen.
    """
    import masken
    return 100.0 * float(masken.anteil(masken.sterne(bild, empfindlichkeit=empfindlichkeit)))


def _helligkeiten(n, rng, alpha=1.8, min_fluss=0.02, max_fluss=1.0):
    """Sternhelligkeiten nach einem Potenzgesetz: wenige helle, viele schwache.

    Am Himmel steigt die Zahl der Sterne mit abnehmender Helligkeit steil an. Gleichverteilt
    gewürfelte Helligkeiten ergeben ein Feld, das es so nicht gibt — und ein Modell, das nur
    mittelhelle Sterne kennt.
    """
    u = rng.random(n)
    # inverse Transformation eines Potenzgesetzes zwischen min und max
    a = 1.0 - alpha
    werte = (min_fluss ** a + u * (max_fluss ** a - min_fluss ** a)) ** (1.0 / a)
    return np.clip(werte, min_fluss, max_fluss)


def paar_erzeugen(untergrund, psf=None, anzahl=200, seed=None, rand=12,
                  min_abstand=6, farbstreuung=0.15, log=log_print):
    """Ein Trainingspaar erzeugen: (mit_sternen, ohne_sterne, maske, sternliste).

    Args:
        untergrund: eine ECHTE, moeglichst sternarme Aufnahme (float 0..1, BGR oder mono).
            Sie ist die Wahrheit — sie wird nicht veraendert.
        psf: die Sternform. Ohne Angabe wird sie aus dem Untergrund geschaetzt; enthaelt der
            zu wenige Sterne, faellt `estimate_psf` auf eine schmale Gauss-PSF zurueck.
        anzahl: wie viele Sterne gerechnet werden.
        farbstreuung: wie stark die Sternfarben streuen (0 = alle neutral). Echte Sterne sind
            blau bis rot; ein Modell, das nur weisse Sterne kennt, laesst farbige stehen.

    Returns:
        (mit_sternen, ohne_sterne, maske, sterne) — `maske` ist float 0..1 und EXAKT, weil sie
        beim Rechnen entsteht und nicht gesucht wird. `sterne` ist eine Liste (x, y, fluss).
    """
    rng = np.random.default_rng(seed)
    ohne = np.clip(np.asarray(untergrund, np.float32), 0, 1)
    if ohne.ndim == 2:
        ohne = cv2.cvtColor(ohne, cv2.COLOR_GRAY2BGR)
    h, w = ohne.shape[:2]
    if psf is None:
        psf = astro.estimate_psf(ohne)
    psf = np.asarray(psf, np.float32)
    psf = psf / (float(psf.sum()) + 1e-12)
    k = psf.shape[0] // 2

    orte = []
    versuche = 0
    while len(orte) < anzahl and versuche < anzahl * 40:
        versuche += 1
        x = int(rng.integers(rand, max(rand + 1, w - rand)))
        y = int(rng.integers(rand, max(rand + 1, h - rand)))
        if orte and min(abs(x - a) + abs(y - b) for a, b in orte) < min_abstand:
            continue
        orte.append((x, y))
    fluesse = _helligkeiten(len(orte), rng)

    sternebene = np.zeros((h, w, 3), np.float32)
    maske = np.zeros((h, w), np.float32)
    sterne = []
    for (x, y), fluss in zip(orte, fluesse):
        # Farbe: leichte Streuung um neutral, in beide Richtungen
        farbe = np.clip(1.0 + rng.normal(0, farbstreuung, 3), 0.4, 1.8).astype(np.float32)
        x0, y0 = max(0, x - k), max(0, y - k)
        x1, y1 = min(w, x + k + 1), min(h, y + k + 1)
        kx0, ky0 = x0 - (x - k), y0 - (y - k)
        stueck = psf[ky0:ky0 + (y1 - y0), kx0:kx0 + (x1 - x0)]
        if stueck.size == 0:
            continue
        sternebene[y0:y1, x0:x1] += stueck[..., None] * (float(fluss) * farbe)
        # EXAKTE Maske: alles, wo dieser Stern ueberhaupt Licht beitraegt, oberhalb einer
        # Schwelle relativ zu seinem eigenen Gipfel. Kein Suchen, kein Schaetzen.
        beitrag = stueck * float(fluss)
        maske[y0:y1, x0:x1] = np.maximum(maske[y0:y1, x0:x1],
                                         (beitrag >= 0.02 * beitrag.max()).astype(np.float32)
                                         if beitrag.max() > 0 else 0.0)
        sterne.append((float(x), float(y), float(fluss)))
    mit = np.clip(ohne + sternebene, 0, 1)
    log("    Sternsynthese: %d Sterne gerechnet, Maske deckt %.2f %% ab, "
        "Untergrund hatte %.2f %% Reststerne"
        % (len(sterne), 100 * float(maske.mean()), reststerne(ohne)))
    return mit, ohne, maske, sterne
