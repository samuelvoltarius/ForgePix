"""ECHTE Rauschig/Sauber-Paare aus eigenen Aufnahmen — statt kuenstlichem Rauschen.

Warum das noetig ist, an einem Fehlschlag gelernt: ein Modell, das nur gegen kuenstlich
verrauschte Bilder trainiert und geprueft wird, kann gelernt haben, genau dieses Rauschen
umzukehren. Ein width-128-Lauf meldete am synthetischen Pruefstand einen MSE-Faktor von 73,4
und tat an einer echten Aufnahme NICHTS (1,05) — er hatte nie ein so ruhiges Bild gesehen,
weil der Rauschbereich am ROHEN Sensor bemessen war statt am debayerten. Mit echten Paaren
kann dieser Fehler nicht entstehen: die Wahrheit kommt aus denselben Daten wie der Eingang.

Das Verfahren, ohne eine einzige Zusatzaufnahme:

    rauschig  =  EINE registrierte Aufnahme
    sauber    =  Mittel der UEBRIGEN Aufnahmen derselben Serie

Das Auslassen der eigenen Aufnahme ist wichtig. Waere sie im Mittel enthalten, steckte ein
Teil ihres eigenen Rauschens in der Wahrheit, und das Modell koennte lernen, es zu behalten
statt es zu entfernen. Bei 60 Aufnahmen waeren das zwar nur 1/60, aber es kostet nichts, es
richtig zu machen: die Summe wird einmal gebildet, und je Aufnahme gilt

    sauber_i = (Summe - Aufnahme_i) / (N - 1)

Die Rauschminderung des sauberen Bildes ist sqrt(N-1) — bei 60 Aufnahmen rund 7,7-fach. Das
ist keine perfekte Wahrheit, aber eine ECHTE, und der Rest ist bekannt und messbar.

    python3 training/prepare_paare_echt.py --quellen "F:/astro-nas/astrofotos" "D:/astro" \\
        --output datasets/echte-paare-v1
"""
import argparse
import glob
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

_REF = {}


def _init(ref_pfad):
    """Einmal je Prozess: Referenzbild lesen und behalten."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
    import astro
    _REF.clear()
    f = astro._read_float(ref_pfad)
    _REF["grau"] = astro._gray(f) if f.ndim == 3 else f
    _REF["form"] = f.shape


def _ausrichten(pfad):
    """Eine Aufnahme lesen und auf die Referenz ausrichten. Gibt das Bild oder None."""
    import astro
    try:
        f = astro._read_float(pfad)
    except Exception:
        return None
    if f is None or f.ndim != 3 or f.shape != _REF["form"]:
        return None
    g = astro._gray(f)
    M = astro._estimate_star_transform_robust(_REF["grau"], g)
    if M is None:
        return None
    aus = cv2.warpAffine(f, M, (f.shape[1], f.shape[0]), flags=cv2.INTER_LANCZOS4,
                         borderValue=0)
    # Wo nach dem Ausrichten nichts liegt, darf keine Kachel entstehen.
    gueltig = cv2.warpAffine(np.ones(f.shape[:2], np.float32), M,
                             (f.shape[1], f.shape[0]), flags=cv2.INTER_NEAREST) > 0.5
    return aus.astype(np.float32), gueltig


def _serien(quellen, min_subs):
    """Ordner mit genug Aufnahmen finden. Gibt [(name, kamera, [pfade])]."""
    from astropy.io import fits
    gefunden = []
    for basis in quellen:
        if not os.path.isdir(basis):
            continue
        for name in sorted(os.listdir(basis)):
            ordner = os.path.join(basis, name)
            if not os.path.isdir(ordner) or name.lower() in ("darks", "flats", "bias"):
                continue
            dateien = [p for p in sorted(glob.glob(os.path.join(ordner, "*.fit"))
                                         + glob.glob(os.path.join(ordner, "*.fits")))
                       if "stacked" not in os.path.basename(p).lower()]
            if len(dateien) < min_subs:
                continue
            try:
                kopf = fits.getheader(dateien[0])
            except Exception:
                continue
            gefunden.append((name, str(kopf.get("INSTRUME", "?")).strip(), dateien))
    return gefunden


def bauen(quellen, ziel, min_subs=30, je_serie=60, kacheln=8, frames=20, groesse=256,
          prozesse=8):
    os.makedirs(ziel, exist_ok=True)
    rng = np.random.default_rng(4711)
    banken = {"rauschig": [], "sauber": []}
    aufzeichnung = []
    serien = _serien(quellen, min_subs)
    print("%d Serien mit mindestens %d Aufnahmen" % (len(serien), min_subs), flush=True)

    for nr, (name, kamera, dateien) in enumerate(serien, 1):
        t0 = time.time()
        genutzt = dateien[:je_serie]
        # Ausrichten. Die Referenz ist die erste Aufnahme der Serie.
        bilder, masken = [], None
        try:
            with ProcessPoolExecutor(max_workers=prozesse, initializer=_init,
                                     initargs=(genutzt[0],)) as ex:
                for ergebnis in ex.map(_ausrichten, genutzt):
                    if ergebnis is None:
                        continue
                    bild, gueltig = ergebnis
                    bilder.append(bild)
                    masken = gueltig if masken is None else (masken & gueltig)
        except Exception as e:
            print("  [%d/%d] %-16s uebersprungen: %s" % (nr, len(serien), name, e), flush=True)
            continue
        n = len(bilder)
        if n < min_subs:
            print("  [%d/%d] %-16s nur %d ausgerichtet, uebersprungen"
                  % (nr, len(serien), name, n), flush=True)
            continue

        summe = np.zeros_like(bilder[0], np.float64)
        for b in bilder:
            summe += b
        # Kachelplaetze im gemeinsam gueltigen Bereich
        ys, xs = np.nonzero(masken)
        if ys.size == 0:
            print("  [%d/%d] %-16s kein gemeinsamer Bereich" % (nr, len(serien), name),
                  flush=True)
            continue
        y0, y1 = int(ys.min()), int(ys.max()) - groesse + 1
        x0, x1 = int(xs.min()), int(xs.max()) - groesse + 1
        if y1 < y0 or x1 < x0:
            print("  [%d/%d] %-16s Bereich kleiner als eine Kachel" % (nr, len(serien), name),
                  flush=True)
            continue
        plaetze = []
        for _ in range(max(400, 40 * kacheln)):
            y = int(rng.integers(y0, y1 + 1))
            x = int(rng.integers(x0, x1 + 1))
            if masken[y:y+groesse, x:x+groesse].all():
                plaetze.append((y, x))
            if len(plaetze) == kacheln:
                break
        if not plaetze:
            print("  [%d/%d] %-16s keine vollstaendige Kachel" % (nr, len(serien), name),
                  flush=True)
            continue

        # Je Aufnahme: sie selbst als rauschig, das Mittel der UEBRIGEN als sauber.
        auswahl = rng.choice(n, size=min(frames, n), replace=False)
        for i in auswahl:
            sauber_bild = (summe - bilder[i]) / float(n - 1)
            for (y, x) in plaetze:
                banken["rauschig"].append(bilder[i][y:y+groesse, x:x+groesse].copy())
                banken["sauber"].append(
                    sauber_bild[y:y+groesse, x:x+groesse].astype(np.float32))
        aufzeichnung.append(dict(serie=name, kamera=kamera, aufnahmen=n,
                                 genutzte_frames=int(len(auswahl)), kacheln=len(plaetze),
                                 rauschminderung=float(np.sqrt(n - 1))))
        print("  [%d/%d] %-16s %3d Aufnahmen, %d Frames x %d Kacheln = %d Paare "
              "(Rauschminderung %.1fx, %.0f s)"
              % (nr, len(serien), name, n, len(auswahl), len(plaetze),
                 len(auswahl) * len(plaetze), np.sqrt(n - 1), time.time() - t0), flush=True)
        del bilder, summe

    if not banken["rauschig"]:
        raise SystemExit("Keine Paare entstanden.")
    for schluessel, werte in banken.items():
        np.save(os.path.join(ziel, schluessel + ".npy"), np.stack(werte))
    manifest = dict(schema_version=1, groesse=groesse, paare=len(banken["rauschig"]),
                    serien=aufzeichnung, seed=4711,
                    verfahren=("rauschig = eine registrierte Aufnahme; sauber = Mittel der "
                               "UEBRIGEN derselben Serie (leave-one-out)"),
                    grenzen=("Das saubere Bild hat Restrauschen (sqrt(N-1) geringer) und "
                             "teilt mit dem rauschigen das feste Muster des Sensors."))
    with open(os.path.join(ziel, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print()
    print("%d Paare aus %d Serien -> %s" % (len(banken["rauschig"]), len(aufzeichnung), ziel))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quellen", nargs="+", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--min-subs", type=int, default=30,
                    help="Mindestzahl Aufnahmen je Serie (Vorgabe 30 = Rauschminderung 5,4x)")
    ap.add_argument("--je-serie", type=int, default=60,
                    help="Wieviele Aufnahmen je Serie fuer das saubere Bild (Vorgabe 60)")
    ap.add_argument("--kacheln", type=int, default=8, help="Kachelplaetze je Serie")
    ap.add_argument("--frames", type=int, default=20,
                    help="Wieviele Aufnahmen je Serie als rauschige Seite dienen")
    ap.add_argument("--groesse", type=int, default=256)
    ap.add_argument("--prozesse", type=int, default=8)
    a = ap.parse_args()
    bauen(a.quellen, a.output, a.min_subs, a.je_serie, a.kacheln, a.frames, a.groesse,
          a.prozesse)
