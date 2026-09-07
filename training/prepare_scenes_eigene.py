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
    """Eine Serie tief stapeln. Gibt (Mono-Ergebnis oder None, Anzahl verworfener Aufnahmen).

    Es wird STROEMEND gerechnet: eine laufende Summe statt einer Liste aller Aufnahmen. Der
    erste Entwurf hielt alle Aufnahmen und zusaetzlich alle ausgerichteten Kopien im Speicher —
    bei einer Serie mit 224 Subs zu 1080x1920 waren das rund 4 GB fuer eine einzige Serie.
    Jetzt liegen nie mehr als zwei Aufnahmen und die Summe gleichzeitig da.
    """
    import cv2
    import astro
    ref = None
    summe = None
    anzahl = 0
    verworfen = 0

    for p in pfade:
        try:
            f = astro._read_float(p)
        except Exception:
            verworfen += 1
            continue
        if f is None:
            verworfen += 1
            continue
        if f.ndim == 3:
            f = astro._gray(f)
        f = f.astype(np.float32)
        # ABGESCHNITTENE DATEIEN aussortieren. Im Archiv liegt mindestens eine (astropy meldet
        # "actual file length 262144, expected 23400000"). astropy fuellt den Rest mit Nullen
        # auf — die Datei laesst sich also lesen, hat die richtige Form und ist trotzdem zur
        # Haelfte leer. In einem Stapel faellt das niemandem auf, es zieht nur alles dunkler.
        if not np.isfinite(f).all() or float((f == 0).mean()) > 0.30:
            verworfen += 1
            continue
        if skala != 1.0:
            f = cv2.resize(f, (0, 0), fx=skala, fy=skala)

        if ref is None:
            ref, summe, anzahl = f, f.astype(np.float64), 1
            continue
        if f.shape != ref.shape:
            verworfen += 1
            continue
        # Verschiebung UND Feldrotation. Vorher stand hier `_estimate_star_shift`, das nur
        # Translation kann — an Alfreds Seestar-Serien (azimutale Montierung, also Bildfeld-
        # drehung) verwarf es 73 bis 98 % der Aufnahmen, und die wenigen behaltenen waren
        # verschmiert. Gemessen an 40 Subs von IC 434, Rotation bis -27,6 Grad:
        #     shift :  18 von 40 Frames, Rauschen 0,000166, FWHM 4,63 px, Exzentrizitaet 2,31
        #     robust:  40 von 40 Frames, Rauschen 0,000118, FWHM 2,63 px, Exzentrizitaet 1,32
        # Das Protokoll meldete dabei "239 Subs -> 24 Kacheln" und las sich wie ein Erfolg.
        M = astro._estimate_star_transform_robust(ref, f)
        if M is None:
            verworfen += 1
            continue
        summe += cv2.warpAffine(f, M, (f.shape[1], f.shape[0]),
                                flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
        anzahl += 1

    if verworfen:
        log("    %d von %d Aufnahme(n) verworfen (unlesbar, abgeschnitten oder nicht "
            "ausrichtbar)" % (verworfen, len(pfade)))
    if anzahl < 2:
        return None, verworfen
    return (summe / anzahl).astype(np.float32), verworfen


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
    zaehler = {"train": 0, "validation": 0, "test": 0}
    scherben = args.output / "_scherben"
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
        # SOFORT schreiben, eine Scherbe je Serie. Der erste Entwurf sammelte alle Kacheln im
        # Speicher und schrieb erst am Ende: nach 17 von 71 Serien belegte der Lauf 5,2 GB, bei
        # allen 71 waeren es ueber 20 GB gewesen — und ein Absturz in Serie 70 haette alles
        # gekostet, weil bis dahin keine einzige .npy auf der Platte lag.
        scherben.mkdir(parents=True, exist_ok=True)
        n_kacheln = len(kacheln)
        if kacheln:
            np.save(scherben / ("%s__%s.npy" % (wohin, name.replace("|", "_"))),
                    np.stack(kacheln).astype(np.float32))
        zaehler[wohin] += n_kacheln
        del kacheln, stapel
        aufzeichnungen.append({
            "serie": name, "kamera": schluessel[0], "belichtung_s": schluessel[1],
            "nacht": schluessel[2], "subs": len(pfade), "nicht_ausrichtbar": verworfen,
            "kacheln": n_kacheln, "menge": wohin,
            "sekunden": round(time.time() - t0, 1)})
        with fortschritt.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(aufzeichnungen[-1], ensure_ascii=False) + "\n")
        print("  [%d/%d] %s: %d Subs -> %d Kacheln (%s), %.0f s"
              % (i, len(reihen), name, len(pfade), n_kacheln, wohin, time.time() - t0),
              flush=True)

    # ANFUEGEN statt ueberschreiben. Der erste Entwurf schrieb Bank und Manifest bei jedem
    # Lauf neu — ein fortgesetzter Durchgang, in dem alle Serien schon erledigt waren, hat das
    # Manifest damit auf "counts: 0" gesetzt, obwohl die Kacheln noch auf der Platte lagen.
    # Genau die stille Sorte Datenverlust, die niemand bemerkt.
    endstand = {}
    for menge in ("train", "validation", "test"):
        ziel = args.output / ("%s.npy" % menge)
        teile = sorted(scherben.glob("%s__*.npy" % menge)) if scherben.exists() else []
        quellen = ([ziel] if ziel.exists() else []) + teile
        if not quellen:
            endstand[menge] = 0
            continue
        # Formen zuerst lesen, dann in eine memmap giessen: so liegt nie mehr als EINE Scherbe
        # gleichzeitig im Speicher.
        formen = [np.load(q, mmap_mode="r").shape for q in quellen]
        gesamt = sum(f[0] for f in formen)
        rest = formen[0][1:]
        assert all(f[1:] == rest for f in formen), "Kachelgroessen passen nicht zusammen"
        tmp = args.output / ("%s.npy.neu" % menge)
        ziel_arr = np.lib.format.open_memmap(tmp, mode="w+", dtype=np.float32,
                                             shape=(gesamt,) + rest)
        pos = 0
        for q in quellen:
            teil = np.load(q, mmap_mode="r")
            ziel_arr[pos:pos + teil.shape[0]] = teil
            pos += teil.shape[0]
            del teil
        ziel_arr.flush()
        del ziel_arr
        os.replace(tmp, ziel)          # atomar: entweder alt oder neu, nie halb
        for q in teile:
            q.unlink()
        endstand[menge] = gesamt
    try:
        scherben.rmdir()
    except OSError:
        pass
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
        "counts": endstand,
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
    print("  fertig: %s" % ", ".join("%s %d" % (k, v) for k, v in endstand.items()))
    print("  -> %s" % args.output)


if __name__ == "__main__":
    main()
