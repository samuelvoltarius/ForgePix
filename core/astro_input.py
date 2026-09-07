"""FITS-first input selection for ASIAIR and other astronomy capture folders."""
import os
from constants import FITS_EXTS

_CALIBRATION = ("dark", "flat", "bias", "offset")
_SKIP_DIRS = {"registered", "stack", "stack_work", "export", "masters", "cache", ".git"}


_FERTIGE = ("stacked", "dso_stacked")


def fits_lights(folder, log=None):
    """Return light FITS only; JPEG previews never accompany them into an integration.

    Bereits gestapelte Ergebnisse (`Stacked_…`, `DSO_Stacked_…`) werden ausgelassen, damit ein
    Ergebnis nicht zusammen mit seinen eigenen Einzelaufnahmen noch einmal eingerechnet wird —
    das zaehlte dieselben Photonen doppelt.

    **Enthaelt der Ordner aber NUR solche Ergebnisse, werden sie benutzt.** Dann gibt es keine
    Einzelaufnahmen, die doppelt zaehlen koennten, und mehrere Naechte zu einem tieferen Bild
    zusammenzufassen ist genau das, was jemand damit vorhat. Vorher blieb in dem Fall nichts
    uebrig und der Lauf endete mit „Zu wenige Bilder fuer Astro" — ohne ein Wort darueber,
    dass es Dateien gab. An Alfreds Bestand gemessen betraf das **35 von 70 Ordnern**; der
    Seestar legt seine Subs in `<Objekt>_sub/` und das Ergebnis in `<Objekt>/`, gemischte
    Ordner gab es kein einziges Mal.
    """
    from astropy.io import fits
    paths, fertige = [], []
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if not os.path.isfile(p) or os.path.splitext(name)[1].lower() not in FITS_EXTS:
            continue
        low = name.lower()
        if low.startswith(_CALIBRATION + ("master",)):
            continue
        if low.startswith(_FERTIGE):
            fertige.append(p)
            continue
        try:
            header = fits.getheader(p)
            kind = str(header.get("IMAGETYP", header.get("FRAME", ""))).lower()
            if any(k in kind for k in _CALIBRATION) or kind.startswith("master"):
                continue
        except (OSError, ValueError):
            # Keep unreadable candidate visible: processing explains/retries the failure.
            pass
        paths.append(p)
    if fertige and not paths:
        if log:
            log("  Dieser Ordner enthaelt nur fertige Stapel (%d Datei(en)) und keine "
                "Einzelaufnahmen — sie werden zu einem tieferen Bild zusammengefasst."
                % len(fertige))
        return fertige
    if fertige and log:
        log("  %d bereits gestapelte Datei(en) ausgelassen: zusammen mit den Einzelaufnahmen "
            "wuerden dieselben Photonen doppelt gezaehlt." % len(fertige))
    return paths


def series_folders(root):
    """Find nested light series; calibration and generated output folders are excluded."""
    result = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d.lower() not in _SKIP_DIRS
                         and not d.lower().startswith(_CALIBRATION + ("stack-",)))
        if any(os.path.splitext(n)[1].lower() in FITS_EXTS for n in files):
            lights = fits_lights(folder)
            if lights:
                result.append((folder, len(lights)))
    return result


def light_paths(folder, fallback, log=None):
    files = fallback(folder)
    if any(os.path.splitext(p)[1].lower() in FITS_EXTS for p in files):
        return fits_lights(folder, log=log)
    return files


def nachbarordner_mit_aufnahmen(folder, mindestens=2):
    """Ordner in der Nachbarschaft, die mehr Aufnahmen enthalten. Liste von (pfad, anzahl).

    Warum: der Seestar legt das fertige Ergebnis in `<Objekt>/` und die Einzelaufnahmen in
    `<Objekt>_sub/`. Wer den erstgenannten waehlt, hat oft genau EINE Datei und bekam nur
    „Zu wenige Bilder fuer Astro" — waehrend nebenan 362 Aufnahmen liegen. Im Bestand haben
    18 von 21 solcher Ordner einen brauchbaren Nachbarn.
    """
    try:
        wurzel = os.path.dirname(os.path.abspath(folder))
        eigener = os.path.basename(os.path.abspath(folder))
        if not os.path.isdir(wurzel):
            return []
    except OSError:
        return []
    treffer = []
    for name in sorted(os.listdir(wurzel)):
        p = os.path.join(wurzel, name)
        if not os.path.isdir(p) or name == eigener:
            continue
        # Nur wirkliche Geschwister desselben Objekts: gleicher Anfang, laengerer Name.
        if not name.startswith(eigener):
            continue
        try:
            n = len(fits_lights(p))
        except OSError:
            continue
        if n >= mindestens:
            treffer.append((p, n))
    treffer.sort(key=lambda x: -x[1])
    return treffer


def _bildart(pfad):
    """Welche Art Aufnahme ist das? Aus dem FITS-Header, sonst aus dem Dateinamen.

    Rückgabe: "light", "dark", "flat", "bias" oder None (unbekannt/kein FITS).
    """
    from astropy.io import fits
    if os.path.splitext(pfad)[1].lower() not in FITS_EXTS:
        return None
    art = ""
    try:
        header = fits.getheader(pfad)
        art = str(header.get("IMAGETYP", header.get("FRAME", ""))).strip().lower()
    except (OSError, ValueError):
        art = ""
    if not art:
        art = os.path.basename(pfad).lower()
    if art.startswith("master") or "master" in art:
        return None
    for schluessel in ("dark", "flat", "bias", "offset"):
        if schluessel in art:
            return "bias" if schluessel == "offset" else schluessel
    if "light" in art:
        return "light"
    return None


def _kopf(pfad):
    """Die Vergleichsfelder eines FITS lesen. Leeres Dict, wenn es nicht geht."""
    try:
        from astropy.io import fits
        h = fits.getheader(pfad)
    except Exception:
        return {}
    def z(*n):
        for k in n:
            if k in h:
                try:
                    return float(h[k])
                except (TypeError, ValueError):
                    pass
        return None
    return {"kamera": str(h.get("INSTRUME", "")).strip(),
            "breite": h.get("NAXIS1"), "hoehe": h.get("NAXIS2"),
            "belichtung": z("EXPTIME", "EXPOSURE"),
            "filter": str(h.get("FILTER", "")).strip()}


def _passt_dazu(kandidat, licht, art):
    """Gehoert dieses Kalibrierbild zu diesen Lights?

    Sensor und Kamera muessen immer stimmen. Bei Darks zusaetzlich die Belichtungszeit: ein
    Dark anderer Laenge zieht den falschen Dunkelstrom ab, und das faellt im Ergebnis nicht
    auf. Bei Flats der Filter.
    """
    if not kandidat or not licht:
        return False
    if kandidat.get("kamera") and licht.get("kamera") and kandidat["kamera"] != licht["kamera"]:
        return False
    for feld in ("breite", "hoehe"):
        if kandidat.get(feld) and licht.get(feld) and kandidat[feld] != licht[feld]:
            return False
    if art == "dark":
        a, b = kandidat.get("belichtung"), licht.get("belichtung")
        if a is not None and b is not None and abs(a - b) > 0.51:
            return False
    if art == "flat":
        a, b = kandidat.get("filter"), licht.get("filter")
        if a and b and a != b:
            return False
    return True


def kalibrierung_nach_header(wurzeln, max_dateien=4000, log=None, passend_zu=None):
    """Darks, Flats und Bias über den FITS-HEADER finden, nicht über Ordnernamen.

    Warum es das braucht: die bisherige Suche kannte nur Ordner, die „dark", „flats" oder
    „bias" heissen. Wer seine Kalibrierbilder anders ablegt — lose im selben Ordner wie die
    Lights, oder in „Kalibrierung 2026-09" — bekam stillschweigend eine unkalibrierte
    Verrechnung. Der Header weiss es dagegen sicher; an Alfreds ASIAIR-Aufnahmen geprüft
    steht dort `IMAGETYP = 'Light'`.

    Args:
        wurzeln: Ordner, die durchsucht werden (Eingabeordner und sein übergeordneter).
        max_dateien: Obergrenze, damit ein versehentlich gewählter Riesenordner nicht
            minutenlang Header liest.

    Returns:
        dict mit "dark"/"flat"/"bias" -> Liste von Pfaden (leer, wenn nichts gefunden).
    """
    gefunden = {"dark": [], "flat": [], "bias": []}
    gesehen = set()
    gelesen = 0
    for wurzel in wurzeln:
        if not wurzel or not os.path.isdir(wurzel):
            continue
        for ordner, unterordner, dateien in os.walk(wurzel):
            unterordner[:] = [d for d in unterordner if d.lower() not in _SKIP_DIRS]
            for name in sorted(dateien):
                if os.path.splitext(name)[1].lower() not in FITS_EXTS:
                    continue
                pfad = os.path.join(ordner, name)
                echt = os.path.normcase(os.path.abspath(pfad))
                if echt in gesehen:
                    continue
                gesehen.add(echt)
                gelesen += 1
                if gelesen > max_dateien:
                    if log:
                        log("    Kalibrierung: mehr als %d FITS durchsucht — Abbruch der Suche."
                            % max_dateien)
                    return gefunden
                art = _bildart(pfad)
                if art in gefunden:
                    gefunden[art].append(pfad)

    # Nur behalten, was zu DIESEN Lights gehoert. Gesucht wird im uebergeordneten Ordner, und
    # zwar rekursiv — wer "D:/astro/M31" waehlt, durchsucht damit "D:/astro" mit allen anderen
    # Objekten, Kameras und Belichtungszeiten. Ohne diese Auswahl kamen fremde Darks in die
    # Liste, und der Lauf starb anschliessend an calibration_metadata.validate mit
    # "Kalibrierung/Aufnahmeserie passt nicht" — statt einfach ohne Kalibrierung zu rechnen.
    if passend_zu:
        lichter = [passend_zu] if isinstance(passend_zu, str) else list(passend_zu)
        licht = {}
        for p in lichter[:5]:
            licht = _kopf(p)
            if licht.get("breite"):
                break
        if licht:
            for art in gefunden:
                vorher = len(gefunden[art])
                behalten, unlesbar = [], 0
                for p in gefunden[art]:
                    k = _kopf(p)
                    if not k:
                        unlesbar += 1          # nicht lesbar ist NICHT dasselbe wie unpassend
                        continue
                    if _passt_dazu(k, licht, art):
                        behalten.append(p)
                gefunden[art] = behalten
                if log and unlesbar:
                    log("    Kalibrierung: %d %s-Aufnahme(n) nicht lesbar — uebergangen."
                        % (unlesbar, art))
                if log and vorher and not behalten:
                    log("    Kalibrierung: %d %s-Aufnahme(n) gefunden, aber keine passt zu "
                        "dieser Serie (Kamera, Sensorgroesse, Belichtung) — nicht verwendet."
                        % (vorher, art))
    if log:
        teile = ["%d %s" % (len(v), k) for k, v in gefunden.items() if v]
        log("    Kalibrierung aus den Headern: %s"
            % (", ".join(teile) if teile else "nichts gefunden"))
    return gefunden


def doppelte_aussortieren(paths, log=None):
    """Dieselbe Aufnahme nicht zweimal in den Stapel lassen.

    Wie sie entstehen: andere Programme (Siril, DeepSkyStacker) legen konvertierte oder
    umbenannte Kopien neben die Originale. Wer dann auf den Ordner zeigt, stapelt einzelne
    Aufnahmen doppelt — das Ergebnis sieht normal aus, gewichtet die Nacht aber falsch und
    bricht die Ausreisser-Erkennung, weil ein Wert zweimal in derselben Verteilung steht.

    Erkannt wird an `DATE-OBS` plus Belichtungszeit: zwei Aufnahmen mit identischem
    Belichtungsbeginn sind dieselbe Aufnahme, egal wie die Datei heisst. Ohne Zeitstempel
    bleibt die Datei drin — geraten wird nicht.

    Returns:
        (behalten, verworfen) als Listen von Pfaden.
    """
    from astropy.io import fits
    gesehen = {}
    behalten, verworfen = [], []
    for p in paths:
        schluessel = None
        if os.path.splitext(p)[1].lower() in FITS_EXTS:
            try:
                h = fits.getheader(p)
                beginn = str(h.get("DATE-OBS", "")).strip()
                if beginn:
                    schluessel = (beginn, str(h.get("EXPTIME", h.get("EXPOSURE", ""))).strip())
            except (OSError, ValueError):
                schluessel = None
        if schluessel is None or schluessel not in gesehen:
            if schluessel is not None:
                gesehen[schluessel] = p
            behalten.append(p)
        else:
            verworfen.append(p)
    if verworfen and log:
        log("    %d doppelte Aufnahme(n) aussortiert (gleicher Belichtungsbeginn): %s"
            % (len(verworfen), ", ".join(os.path.basename(p) for p in verworfen[:5])
               + (" …" if len(verworfen) > 5 else "")))
        log("    Solche Kopien legen andere Programme neben die Originale; doppelt gestapelt "
            "gewichten sie die Nacht falsch.")
    return behalten, verworfen
