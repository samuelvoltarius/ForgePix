#!/usr/bin/env python3
"""Szenenbank aus den EIGENEN Aufnahmen — bodengebundene Wirklichkeit statt HST.

Warum das gebraucht wird, steht in `training/train_restoration.py` selbst:

    limitations="Synthetic and added-degradation HST scene tests; no real independent
                 clean/noisy pairs, held-out camera or astrophotometric release qualification"

Die bisherige Szenenbank besteht aus Hubble-Aufnahmen. Die sind wissenschaftlich sauber, aber
sie stammen von ÜBER der Atmosphäre: andere Sternabbildung, anderes Ausleserauschen, kein
Seeing, kein Himmelshintergrund einer Stadt. Ein Modell, das nur solche Szenen kennt, sieht die
Verhältnisse nie, unter denen es später arbeiten soll.

Dieses Skript baut die Bank aus Alfreds eigenen Nächten. Eine Serie wird tief gestapelt — das
ist die rauschärmste Fassung, die diese Daten hergeben — und daraus werden Kacheln gezogen.

**Was hier bewusst NICHT behauptet wird:** dass diese Kacheln rauschfrei sind. Sie sind es
nicht, und das Manifest sagt es ausdrücklich. Ein tiefer Stack hat weniger Rauschen als ein
Sub, aber er ist keine Wahrheit. Wer sie als saubere Zielbilder behandelt, trainiert dem
Modell das Restrauschen als Signal an.

Aufruf::

    python -m training.prepare_scenes_eigene --quellen D:/astro Y:/Backup/astro \
        --output ~/forgepix-training/datasets/scene-bank-eigene-001

Der Lauf ist FORTSETZBAR: bereits verarbeitete Serien stehen im Fortschrittsprotokoll und
werden übersprungen. Ein abgebrochener Durchgang kostet damit nur die angefangene Serie.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))


def _stapeln(pfade, skala, log):
    """Eine Serie tief stapeln. Gibt das Mono-Ergebnis oder None."""
    import cv2
    import astro
    bilder, unbrauchbar = [], 0
    for p in pfade:
        try:
            f = astro._read_float(p)
        except Exception:
            unbrauchbar += 1
            continue
        if f is None:
            unbrauchbar += 1
            continue
        if f.ndim == 3:
            f = astro._gray(f)
        f = f.astype(np.float32)
        # ABGESCHNITTENE DATEIEN aussortieren. Im Archiv liegt mindestens eine (astropy meldet
        # "actual file length 262144, expected 23400000"). astropy fuellt den Rest mit Nullen
        # auf — die Datei laesst sich also lesen, hat die richtige Form und ist trotzdem zur
        # Haelfte leer. In einem Stapel faellt das niemandem auf, es zieht nur alles dunkler.
        if not np.isfinite(f).all():
            unbrauchbar += 1
            continue
        leer = float((f == 0).mean())
        if leer > 0.30:
            unbrauchbar += 1
            continue
        if skala != 1.0:
            f = cv2.resize(f, (0, 0), fx=skala, fy=skala)
        bilder.append(f)
    if unbrauchbar:
        log("    %d Aufnahme(n) unbrauchbar (abgeschnitten oder ungueltig) — aussortiert"
            % unbrauchbar)
    if len(bilder) < 2:
        return None, unbrauchbar
    ref = bilder[0]
    aus, verworfen = [ref], unbrauchbar
    for f in bilder[1:]:
        if f.shape != ref.shape:
            verworfen += 1
            continue
        M = astro._estimate_star_shift(ref, f)
        if M is None:
            verworfen += 1
            continue
        aus.append(cv2.warpAffine(f, M, (f.shape[1], f.shape[0]),
                                  flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE))
    if len(aus) < 2:
        return None, verworfen
    return np.mean(np.stack(aus), axis=0).astype(np.float32), verworfen


def _kacheln(bild, groesse, anzahl, rng, min_struktur=1e-5):
    """Kacheln ziehen und die langweiligen verwerfen.

    Eine Kachel aus reinem Himmel enthält nichts zu lernen und verdünnt die Bank nur. Als Mass
    dient die Streuung nach Abzug des lokalen Mittels — nicht die Helligkeit, denn ein heller
    Gradient ohne Struktur wäre genauso wertlos.
    """
    import cv2
    h, w = bild.shape[:2]
    if h < groesse or w < groesse:
        return []
    raus, versuche = [], 0
    while len(raus) < anzahl and versuche < anzahl * 12:
        versuche += 1
        y = int(rng.integers(0, h - groesse + 1))
        x = int(rng.integers(0, w - groesse + 1))
        k = bild[y:y + groesse, x:x + groesse]
        if not np.isfinite(k).all():
            continue
        struktur = float(np.std(k - cv2.blur(k, (17, 17))))
        if struktur < min_struktur:
            continue
        raus.append(k.copy())
    return raus


def _kameras_in(pfade, hoechstens=40):
    """Welche Kameras stecken wirklich in dieser Serie? Stichprobe ueber die Header."""
    from astropy.io import fits
    kameras = set()
    for p in pfade[:hoechstens]:
        try:
            kameras.add(str(fits.getheader(p).get("INSTRUME", "?")).strip())
        except Exception:
            continue
    return kameras


def _kameras_zaehlen(aufzeichnungen):
    """Welche Kamera wie viele Kacheln beigesteuert hat, je Menge."""
    aus = {}
    for a in aufzeichnungen:
        kam = a.get("kamera") or "unbekannt"
        menge = a.get("menge") or "?"
        aus.setdefault(kam, {}).setdefault(menge, 0)
        aus[kam][menge] += int(a.get("kacheln") or 0)
    return aus


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quellen", nargs="+", required=True, help="Ordner mit den Aufnahmen")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--min-subs", type=int, default=20)
    ap.add_argument("--groesse", type=int, default=256)
    ap.add_argument("--je-serie", type=int, default=24, help="Kacheln je Serie")
    ap.add_argument("--skala", type=float, default=1.0)
    ap.add_argument("--max-serien", type=int, default=0, help="0 = alle")
    ap.add_argument("--kamera", default=None,
                    help="Nur Serien dieser Kamera (Teilzeichenkette, z. B. 294MC). Ohne "
                         "Angabe kommen ALLE Kameras in dieselbe Bank — fuer Szenenvielfalt "
                         "ist das gewollt, fuer ein kameraspezifisches Modell nicht.")
    args = ap.parse_args()

    import trainingspaare
    from constants import force_utf8_stdio
    force_utf8_stdio()

    args.output.mkdir(parents=True, exist_ok=True)
    fortschritt = args.output / "fortschritt.jsonl"
    erledigt = set()
    if fortschritt.exists():
        for zeile in fortschritt.read_text(encoding="utf-8").splitlines():
            try:
                erledigt.add(json.loads(zeile)["serie"])
            except Exception:
                continue
        print("  %d Serien bereits erledigt — werden uebersprungen" % len(erledigt))

    serien = {}
    for quelle in args.quellen:
        if not os.path.isdir(quelle):
            print("  Quelle nicht erreichbar, uebersprungen: %s" % quelle, file=sys.stderr)
            continue
        serien.update(trainingspaare.serien_finden(quelle, min_subs=args.min_subs))
    if args.kamera:
        vorher = len(serien)
        serien = {k: v for k, v in serien.items() if args.kamera.lower() in k[0].lower()}
        print("  Kamerafilter %r: %d von %d Serien" % (args.kamera, len(serien), vorher))
    reihen = sorted(serien.items(), key=lambda kv: -len(kv[1]))
    if args.max_serien:
        reihen = reihen[:args.max_serien]
    print("  %d Serien zu verarbeiten" % len(reihen))

    rng = np.random.default_rng(20260907)
    banks = {"train": [], "validation": [], "test": []}
    aufzeichnungen = []
    for i, (schluessel, pfade) in enumerate(reihen, 1):
        name = "%s|%g|%s|%s" % (schluessel[0], schluessel[1], schluessel[2],
                                hashlib.sha256(schluessel[3].encode("utf-8")).hexdigest()[:8])
        if name in erledigt:
            continue
        t0 = time.time()
        # Sicherung gegen gemischte Kameras: die Gruppierung trennt sie zwar, aber ein Stapel
        # aus zwei Sensoren waere unbrauchbar und faellt niemandem auf — verschiedene
        # Pixelmassstaebe ergeben verschieden breite Sterne im selben Bild.
        kameras = _kameras_in(pfade)
        if len(kameras) > 1:
            print("  [%d/%d] %s — UEBERSPRUNGEN: mehrere Kameras in einer Serie (%s)"
                  % (i, len(reihen), name, ", ".join(sorted(kameras))), file=sys.stderr)
            continue
        stapel, verworfen = _stapeln(pfade, args.skala, print)
        if stapel is None:
            print("  [%d/%d] %s — nicht stapelbar, uebersprungen" % (i, len(reihen), name))
            continue
        kacheln = _kacheln(stapel, args.groesse, args.je_serie, rng)
        # Aufteilung JE SERIE, nicht je Kachel: Kacheln derselben Nacht duerfen nie ueber
        # Trainings- und Testmenge verteilt werden, sonst prueft der Test, was er kennt.
        wohin = "train" if (i % 10) not in (0, 5) else ("validation" if i % 10 == 5 else "test")
        banks[wohin].extend(kacheln)
        aufzeichnungen.append({
            "serie": name, "kamera": schluessel[0], "belichtung_s": schluessel[1],
            "nacht": schluessel[2], "subs": len(pfade), "nicht_ausrichtbar": verworfen,
            "kacheln": len(kacheln), "menge": wohin,
            "sekunden": round(time.time() - t0, 1)})
        with fortschritt.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(aufzeichnungen[-1], ensure_ascii=False) + "\n")
        print("  [%d/%d] %s: %d Subs -> %d Kacheln (%s), %.0f s"
              % (i, len(reihen), name, len(pfade), len(kacheln), wohin, time.time() - t0),
              flush=True)

    # ANFUEGEN statt ueberschreiben. Der erste Entwurf schrieb Bank und Manifest bei jedem
    # Lauf neu — ein fortgesetzter Durchgang, in dem alle Serien schon erledigt waren, hat das
    # Manifest damit auf "counts: 0" gesetzt, obwohl die Kacheln noch auf der Platte lagen.
    # Genau die stille Sorte Datenverlust, die niemand bemerkt.
    for menge, liste in banks.items():
        ziel = args.output / ("%s.npy" % menge)
        vorhanden = np.load(ziel) if ziel.exists() else None
        if liste:
            neu_arr = np.stack(liste).astype(np.float32)
            zusammen = np.concatenate([vorhanden, neu_arr]) if vorhanden is not None else neu_arr
            np.save(ziel, zusammen)
            banks[menge] = zusammen
        elif vorhanden is not None:
            banks[menge] = vorhanden
    # Die Aufzeichnungen kommen aus dem Fortschrittsprotokoll — dort steht ALLES, auch was
    # frueheren Laeufen gehoert.
    alle_aufzeichnungen = []
    if fortschritt.exists():
        for zeile in fortschritt.read_text(encoding="utf-8").splitlines():
            try:
                alle_aufzeichnungen.append(json.loads(zeile))
            except Exception:
                continue
    manifest = {
        "schema_version": 1,
        "size": args.groesse,
        "counts": {k: (len(v) if not isinstance(v, np.ndarray) else int(v.shape[0]))
                   for k, v in banks.items()},
        # Kameras aufschluesseln. Die Bank MISCHT Kameras, wenn nicht gefiltert wird — fuer
        # Szenenvielfalt ist das gewollt, aber wer ein kameraspezifisches Modell trainiert,
        # muss es wissen. Verschiedene Sensoren haben verschiedene Pixelmassstaebe, damit
        # verschieden breite Sterne, und verschiedenes Ausleserauschen.
        "kameras": _kameras_zaehlen(alle_aufzeichnungen),
        "kamerafilter": args.kamera,
        "records": alle_aufzeichnungen,
        "use": "Bodengebundene Szenen aus eigenen Aufnahmen, als Grundlage fuer synthetische "
               "Degradation. NICHT als rauschfreie Wahrheit.",
        "source_noise_retained": True,
        "ground_truth": False,
        "hinweis": "Jede Kachel stammt aus einem tiefen Stapel derselben Nacht. Ein tiefer "
                   "Stapel hat weniger Rauschen als ein Sub, ist aber keine Wahrheit. Wer ihn "
                   "als sauberes Zielbild behandelt, trainiert dem Modell das Restrauschen "
                   "als Signal an. Aufteilung erfolgt JE SERIE, damit keine Kacheln derselben "
                   "Nacht ueber Trainings- und Testmenge verteilt werden.",
        "erstellt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  fertig: %s" % ", ".join(
        "%s %d" % (k, (len(v) if not isinstance(v, np.ndarray) else int(v.shape[0])))
        for k, v in banks.items()))
    print("  -> %s" % args.output)


if __name__ == "__main__":
    main()
