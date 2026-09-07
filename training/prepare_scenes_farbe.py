"""Farb-Szenenbank aus den EINZELFILTERN des Hubble-Archivs.

Die Mono-Bank (`prepare_scenes.py`) nimmt jede Aufnahme fuer sich. Ein Farbmodell braucht
drei Kanaele — und die liegen im Archiv bereits vor: dasselbe Programm, derselbe Besuch,
dasselbe Instrument, nur ein anderer Filter.

Der entscheidende Punkt, an echten Daten geprueft: die fertigen Archivprodukte eines Besuchs
liegen auf DEMSELBEN Pixelraster. Gemessen an M16 (ACS/WFC, 5 Filter), M81 (ACS/HRC, 3) und
M8 (WFPC2/PC, 5): gleiche Bildgroesse, gleiches CRVAL1/CRVAL2, gleiches CRPIX1/CRPIX2, auf
fuenf Nachkommastellen. Es muss also NICHTS registriert werden — die Kanaele lassen sich
uebereinanderlegen. Geprueft wird es trotzdem bei jeder Gruppe; eine Annahme, die man nicht
nachrechnet, ist eine Wette.

Was diese Bank NICHT ist: echte Farbe. Hubble-Filter sind Schmal- und Breitbaender, keine
RGB-Filter. Fuer ein Entrauschungsmodell zaehlt aber nicht die Farbtreue, sondern dass die
drei Kanaele verwandt und doch verschieden sind und jeder sein eigenes Rauschen traegt.

Eine Einschraenkung, die beim Urteil mitgedacht werden muss: die Kanaele stammen aus
GETRENNTEN Belichtungen, ihr Rauschen ist also unabhaengig. Bei einer Farbkamera ist das
Rauschen ueber das Debayering zwischen den Kanaelen verbunden. Ein Modell, das nur hier
lernt, kennt diesen Fall nicht — darum gehoert die Bank aus den eigenen Kameras
(`prepare_scenes_eigene.py --farbe`) dazugemischt, nicht ersetzt.

    python3 training/prepare_scenes_farbe.py --input datasets/hst-diverse-001 \\
        --output datasets/farb-szenen-v1 --per-file 300
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from astropy.io import fits

# hst_<programm>_<besuch>_<instrument>_<detektor>_<filter>_<verbund>_dr[cz].fits
_NAME = re.compile(r"^hst_(\d+)_(\w+?)_([a-z0-9]+)_([a-z0-9]+)_(f\d+[a-z]+)_(\w+)_dr[cz]\.fits$")
# Wie weit CRVAL/CRPIX auseinanderliegen duerfen, bevor die Gruppe verworfen wird.
_MAX_CRVAL_ABWEICHUNG = 1e-6      # Grad
_MAX_CRPIX_ABWEICHUNG = 0.01      # Pixel
# Mindestabstand zwischen zwei benachbarten Kanaelen, damit sie verschiedene Farben
# und nicht dasselbe zweimal zeigen.
_MIN_ABSTAND_NM = 40


def _wellenlaenge(filtername):
    """f435w -> 435. Die Zahl im Hubble-Filternamen ist die Mittenwellenlaenge in nm."""
    ziffern = re.match(r"^f(\d+)", filtername)
    return int(ziffern.group(1)) if ziffern else 0


def _drei_filter(vorhanden):
    """Drei Filter fuer R, G, B waehlen — langwellig nach Rot, kurzwellig nach Blau.

    Breit- und Mittelbaender werden bevorzugt: ein Schmalband (Endung `n`) zeigt eine
    einzelne Emissionslinie und ist als Farbkanal irrefuehrend. Reicht es damit nicht fuer
    drei, wird mit Schmalbaendern aufgefuellt — sonst faellt eine Gruppe aus, die brauchbare
    Kanaele haette.
    """
    breit = sorted([f for f in vorhanden if not f.endswith("n")], key=_wellenlaenge)
    schmal = sorted([f for f in vorhanden if f.endswith("n")], key=_wellenlaenge)
    gewaehlt = breit if len(breit) >= 3 else sorted(breit + schmal, key=_wellenlaenge)
    if len(gewaehlt) < 3:
        return None
    if len(gewaehlt) > 3:
        # Die Aeusseren und die Mitte: gibt die groesste Farbspanne.
        gewaehlt = [gewaehlt[0], gewaehlt[len(gewaehlt) // 2], gewaehlt[-1]]
    # Die drei Kanaele muessen sich auch WELLENLAENGLICH unterscheiden. An echten Daten
    # aufgefallen: fuer NGC 6543 und NGC 7009 gab es nur Schmalbaender, und die Wahl fiel auf
    # f658n/f656n/f502n — Rot und Gruen lagen zwei Nanometer auseinander, also zwei praktisch
    # identische Kanaele. Ein Modell lernt daraus, dass Kanaele redundant sind; das ist bei
    # einer Farbkamera falsch.
    if any(_wellenlaenge(a) - _wellenlaenge(b) < _MIN_ABSTAND_NM
           for a, b in zip(gewaehlt[1:], gewaehlt[:-1])):
        return None
    return gewaehlt[::-1]        # R (lang), G, B (kurz)


def _lesen(pfad, groesse):
    """Bilddaten und Gueltigkeitsmaske einer Aufnahme. Gibt (daten, gueltig, kopf) oder None."""
    with fits.open(pfad, memmap=False) as hdus:
        daten = np.asarray(hdus["SCI"].data, dtype=np.float32)
        if daten.ndim != 2 or min(daten.shape) < groesse:
            return None
        gueltig = np.isfinite(daten)
        if "WHT" in hdus:
            gewicht = hdus["WHT"].data
            gueltig &= np.isfinite(gewicht) & (gewicht > 0)
        if "DQ" in hdus:
            gueltig &= hdus["DQ"].data == 0
        return daten, gueltig, dict(hdus["SCI"].header)


def _gleiches_raster(koepfe):
    """Liegen alle Kanaele auf demselben Pixelraster? Sonst muesste registriert werden."""
    erst = koepfe[0]
    for k in koepfe[1:]:
        for schluessel, grenze in (("CRVAL1", _MAX_CRVAL_ABWEICHUNG),
                                   ("CRVAL2", _MAX_CRVAL_ABWEICHUNG),
                                   ("CRPIX1", _MAX_CRPIX_ABWEICHUNG),
                                   ("CRPIX2", _MAX_CRPIX_ABWEICHUNG)):
            a, b = erst.get(schluessel), k.get(schluessel)
            if a is None or b is None or abs(float(a) - float(b)) > grenze:
                return False, schluessel
    return True, None


def prepare(root, output, per_file=300, size=256):
    output.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(605193)
    banks = {"train": [], "validation": [], "test": []}

    # --- Aufnahmen zu Zeigern gruppieren -------------------------------------------------
    gruppen, splits = {}, {}
    for metadata in sorted(root.glob("*/*.fits.json")):
        record = json.loads(metadata.read_text())
        if record["split"] not in banks or record.get("rights") != "PUBLIC":
            raise ValueError(f"Ungepruefter Split oder Rechtestatus: {metadata}")
        pfad = Path(str(metadata)[:-5])
        treffer = _NAME.match(pfad.name)
        if not treffer:
            continue
        programm, besuch, instrument, detektor, filtername, _ = treffer.groups()
        schluessel = (record["group"], programm, besuch, instrument, detektor)
        if splits.setdefault(record["group"], record["split"]) != record["split"]:
            raise ValueError(f"Objekt liegt in zwei Splits: {record['group']}")
        gruppen.setdefault(schluessel, {})[filtername] = (pfad, record)

    tauglich = {k: v for k, v in gruppen.items() if _drei_filter(list(v)) is not None}
    print("%d Zeiger, davon %d mit drei brauchbaren Filtern"
          % (len(gruppen), len(tauglich)), flush=True)

    records, verworfen = [], []
    for schluessel, dateien in sorted(tauglich.items()):
        ziel, programm, besuch, instrument, detektor = schluessel
        split = splits[ziel]
        filternamen = _drei_filter(list(dateien))
        kanaele, gueltig, koepfe, quellen = [], None, [], []
        for filtername in filternamen:
            pfad, record = dateien[filtername]
            with pfad.open("rb") as quelle:
                digest = hashlib.file_digest(quelle, "sha256").hexdigest()
            if digest != record["sha256"]:
                raise ValueError(f"Pruefsumme der Quelle stimmt nicht: {pfad}")
            gelesen = _lesen(pfad, size)
            if gelesen is None:
                kanaele = None
                break
            daten, gut, kopf = gelesen
            if kanaele and daten.shape != kanaele[0].shape:
                kanaele = None
                break
            kanaele.append(daten)
            koepfe.append(kopf)
            quellen.append(dict(filter=filtername, source=str(pfad), uri=record["uri"],
                                sha256=digest))
            gueltig = gut if gueltig is None else (gueltig & gut)
        if not kanaele or len(kanaele) != 3:
            verworfen.append((schluessel, "Kanaele nicht lesbar oder verschieden gross"))
            continue
        passt, wo = _gleiches_raster(koepfe)
        if not passt:
            verworfen.append((schluessel, "Pixelraster weicht ab (%s)" % wo))
            continue

        # JE KANAL normieren. Die Filter haben verschiedene Durchlaessigkeit und
        # Belichtungszeit; ohne das waere die Farbbalance reine Willkuer und das Modell
        # lernte den Filtersatz statt das Bild.
        gestapelt = np.empty(kanaele[0].shape + (3,), np.float32)
        norm = []
        for k, daten in enumerate(kanaele):
            pixel = daten[gueltig]
            if not pixel.size:
                break
            tief, hoch = np.percentile(pixel, [.1, 99.9])
            skala = max(float(hoch - tief), 1e-6)
            gestapelt[..., k] = (daten - tief) / skala
            norm.append(dict(offset=float(tief), scale=skala))
        if len(norm) != 3:
            verworfen.append((schluessel, "ein Kanal ohne gueltige Pixel"))
            continue

        ys, xs = np.nonzero(gueltig)
        if ys.size == 0:
            verworfen.append((schluessel, "keine gemeinsam gueltigen Pixel"))
            continue
        y0, y1 = int(ys.min()), int(ys.max()) - size + 1
        x0, x1 = int(xs.min()), int(xs.max()) - size + 1
        if y1 < y0 or x1 < x0:
            verworfen.append((schluessel, "gueltiger Bereich kleiner als eine Kachel"))
            continue

        angenommen = []
        for _ in range(max(2000, 60 * per_file)):
            y = int(rng.integers(y0, y1 + 1))
            x = int(rng.integers(x0, x1 + 1))
            if not gueltig[y:y+size, x:x+size].all():
                continue
            kachel = gestapelt[y:y+size, x:x+size]
            if not np.isfinite(kachel).all():
                continue
            banks[split].append(np.asarray(kachel, dtype=np.float32))
            angenommen.append([x, y])
            if len(angenommen) == per_file:
                break
        records.append(dict(group=ziel, programme=programm, visit=besuch,
                            instrument=instrument, detector=detektor, split=split,
                            channels=quellen, normalization=norm,
                            patches_xy=angenommen, ground_truth=False))
        print("%-9s %s/%s %s_%s  %s -> %s %d Kacheln"
              % (ziel, programm, besuch, instrument, detektor,
                 "/".join(filternamen), split, len(angenommen)), flush=True)

    for schluessel, grund in verworfen:
        print("verworfen: %s — %s" % (schluessel[0], grund), flush=True)
    if not banks["train"] or not banks["validation"]:
        raise ValueError("Es braucht unabhaengige Objekte fuer Training und Pruefung")
    for split, werte in banks.items():
        if werte:
            np.save(output / f"{split}.npy", np.stack(werte))
    manifest = dict(schema_version=1, size=size, seed=605193, channels=3,
        counts={k: len(v) for k, v in banks.items()}, records=records,
        rejected=[[list(k), g] for k, g in verworfen],
        use="Public HST single-filter products combined per pointing into RGB scene bases",
        channel_assignment="longest wavelength -> R, middle -> G, shortest -> B",
        registration="none required; identical pixel grid per pointing, verified per group",
        source_noise_retained=True, ground_truth=False,
        credit="NASA/ESA Hubble; observing programmes; STScI/MAST",
        limitations=("HST filters are not RGB filters; per-channel noise is independent "
                     "because channels come from separate exposures, unlike a debayered "
                     "colour camera"))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["counts"]), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--per-file", type=int, default=300,
                    help="Kacheln je Zeiger (nicht je Datei — ein Zeiger sind drei Dateien)")
    args = ap.parse_args()
    if args.per_file < 1:
        ap.error("per-file muss positiv sein")
    prepare(args.input, args.output, args.per_file)
