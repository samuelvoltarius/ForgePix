#!/usr/bin/env python3
"""
core/astap.py — Plate-Solve mit ASTAP, auch BLIND (ohne Hinweis auf die Himmelsposition).

ASTAP (hnsky.org, frei, Windows/macOS/Linux) wird als eigenes Programm aufgerufen, nie
mitgeliefert; seine Sterndatenbank lädt der Nutzer selbst (welche, sagt `datenbank_fuer`).
Der eigene Solver (`astrometry.py`) braucht einen Hinweis; ASTAP springt ein, wenn keiner da ist
oder der eigene Solver scheitert.

Kommandozeile nach der ASTAP-Beschreibung: `-f Bild -fov Höhe° -r Suchradius° -ra h -spd Dec+90
-wcs`; blind = `-fov 0 -r 180`. Die Lösung steht danach in `<Bild>.wcs` (ein FITS-Kopf ohne
Daten). Am 23.11.2026 NICHT gegen ein echtes ASTAP geprüft (hier nicht installiert) — nur gegen
einen Nachbau, der die Kommandozeile entgegennimmt.
"""
import os
import subprocess
import tempfile

import numpy as np

try:
    from constants import log_print
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)

DOWNLOAD = "https://www.hnsky.org/astap.htm"

# Datenbank → Bildfeld-Spanne in Grad (laut ASTAP-Beschreibung)
DATENBANKEN = [("D80", 0.15, 6.0), ("D50", 0.2, 6.0), ("D20", 0.3, 6.0), ("D05", 0.6, 6.0),
               ("G05", 3.0, 20.0), ("W08", 20.0, 80.0)]


class AstapFehler(Exception):
    pass


def finden():
    """Pfad von ASTAP oder None."""
    import photometric
    art, pfad = photometric._find_solver()
    return pfad if art == "astap" else None


def datenbank_fuer(feld_grad):
    """Passende ASTAP-Datenbanken für ein Bildfeld (kürzere Seite in Grad), beste zuerst."""
    return [name for name, von, bis in DATENBANKEN if von <= feld_grad <= bis]


def loesen(bild, hinweise=None, befehl=None, timeout=300, log=log_print):
    """Bild (BGR/grau, linear) lösen. `hinweise` mit ra/dec (Grad) und optional
    pixelscale_arcsec → schneller Lauf; ohne → blind über den ganzen Himmel.
    `befehl`: Aufruf als Liste (für Tests); sonst das gefundene ASTAP. Gibt ein astropy-WCS."""
    from astropy.io import fits
    if befehl is None:
        pfad = finden()
        if not pfad:
            raise AstapFehler("ASTAP ist nicht installiert — herunterladen: %s (Programm und "
                              "eine Sterndatenbank, z. B. D50)" % DOWNLOAD)
        befehl = [pfad]
    a = np.asarray(bild, np.float32)
    grau = a.mean(axis=2) if a.ndim == 3 else a
    lo, hi = np.percentile(grau, [1.0, 99.99])
    daten = (np.clip((grau - lo) / max(float(hi - lo), 1e-12), 0, 1) * 65535).astype(np.uint16)
    with tempfile.TemporaryDirectory(prefix="forgepix_astap_") as d:
        datei = os.path.join(d, "solve.fits")
        fits.PrimaryHDU(daten).writeto(datei)
        cmd = list(befehl) + ["-f", datei, "-wcs"]
        h = hinweise or {}
        if h.get("ra") is not None and h.get("dec") is not None:
            cmd += ["-ra", "%.6f" % (float(h["ra"]) / 15.0), "-spd", "%.6f" % (float(h["dec"]) + 90.0),
                    "-r", "%g" % float(h.get("radius", 10))]
            if h.get("pixelscale_arcsec"):
                cmd += ["-fov", "%.4f" % (grau.shape[0] * float(h["pixelscale_arcsec"]) / 3600.0)]
            log("ASTAP: löse mit Hinweis RA %.3f°, Dec %+.3f° …" % (float(h["ra"]), float(h["dec"])))
        else:
            cmd += ["-fov", "0", "-r", "180"]
            log("ASTAP: löse blind (ganzer Himmel, kann einige Minuten dauern) …")
        try:
            lauf = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, cwd=d, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as e:
            raise AstapFehler("ASTAP: keine Lösung nach %d s" % timeout) from e
        wcs_datei = os.path.splitext(datei)[0] + ".wcs"
        if not os.path.isfile(wcs_datei):
            rest = (lauf.stdout or lauf.stderr or "").strip()[-300:]
            raise AstapFehler("ASTAP fand keine Lösung (Exit %d). Passt die Sterndatenbank zum "
                              "Bildfeld? %s" % (lauf.returncode, rest))
        import photometric
        wcs = photometric._read_wcs2d(wcs_datei)
        if wcs is None:
            # Ein reiner Kopf ohne SIMPLE-Karte ist kein vollständiges FITS — trotzdem lesen
            from astropy.io import fits as _fits
            from astropy.wcs import WCS
            try:
                w2 = WCS(_fits.Header.fromfile(wcs_datei), naxis=2)
                wcs = w2 if w2.has_celestial else None
            except Exception:
                wcs = None
        if wcs is None:
            raise AstapFehler("ASTAP schrieb eine Lösungsdatei ohne Himmelsposition.")
    mitte = wcs.pixel_to_world_values((grau.shape[1] - 1) / 2.0, (grau.shape[0] - 1) / 2.0)
    log("ASTAP: gelöst — Mitte RA %.4f°, Dec %+.4f°" % (float(mitte[0]), float(mitte[1])))
    return wcs
