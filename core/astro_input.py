"""FITS-first input selection for ASIAIR and other astronomy capture folders."""
import os
from constants import FITS_EXTS

_CALIBRATION = ("dark", "flat", "bias", "offset")
_SKIP_DIRS = {"registered", "stack", "stack_work", "export", "masters", "cache", ".git"}


def fits_lights(folder):
    """Return light FITS only; JPEG previews never accompany them into an integration."""
    from astropy.io import fits
    paths = []
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if not os.path.isfile(p) or os.path.splitext(name)[1].lower() not in FITS_EXTS:
            continue
        low = name.lower()
        if low.startswith(_CALIBRATION + ("master", "stacked", "dso_stacked")):
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


def light_paths(folder, fallback):
    files = fallback(folder)
    if any(os.path.splitext(p)[1].lower() in FITS_EXTS for p in files):
        return fits_lights(folder)
    return files


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


def kalibrierung_nach_header(wurzeln, max_dateien=4000, log=None):
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
    if log:
        teile = ["%d %s" % (len(v), k) for k, v in gefunden.items() if v]
        log("    Kalibrierung aus den Headern: %s"
            % (", ".join(teile) if teile else "nichts gefunden"))
    return gefunden
