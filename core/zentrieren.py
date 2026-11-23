#!/usr/bin/env python3
"""
core/zentrieren.py — Plate-Solve und Zentrieren, wie N.I.N.A.s „Slew and Center“.

Ablauf: belichten → mit dem eigenen Solver (`astrometry.py`, lokaler Gaia-Katalog, Hinweis aus
der Montierungsposition) die echte Bildmitte bestimmen → ist sie weiter als die Toleranz vom
Ziel weg, die Montierung auf die gemessene Position abgleichen („Sync“) und erneut auf das Ziel
schwenken → wiederholen, bis es passt oder die Versuche aufgebraucht sind.

Scheitert das Lösen, wird nicht geraten: Fehler mit Grund. Kein Qt.
"""
import math

import numpy as np

try:
    from constants import log_print
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)


def winkelabstand(ra1, dec1, ra2, dec2):
    """Bogenabstand in Grad (alle Angaben in Grad)."""
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def bildmitte(bild, katalog, ra_grad, dec_grad, pixelskala, log=log_print, astap_befehl=None):
    """Gelöste Bildmitte (RA, Dec in Grad) und das WCS. Erst der eigene Solver (schnell,
    offline); scheitert er und ist ASTAP da, ASTAP mit demselben Hinweis."""
    import astrometry
    hinweise = {"ra": ra_grad % 360, "dec": dec_grad, "pixelscale_arcsec": pixelskala}
    h, w = np.asarray(bild).shape[:2]
    try:
        wcs = astrometry.solve(bild, katalog, hinweise, log=log).wcs
    except Exception as eigener:
        import astap
        if astap_befehl is None and not astap.finden():
            raise
        log("Eigener Solver ohne Lösung (%s) — versuche ASTAP" % eigener)
        wcs = astap.loesen(bild, dict(hinweise, radius=5), befehl=astap_befehl, log=log)
    ra, dec = wcs.pixel_to_world_values((w - 1) / 2.0, (h - 1) / 2.0)
    return float(ra) % 360, float(dec), wcs


def zentrieren(kamera, montierung, ziel_ra_h, ziel_dec, katalog, pixelskala, belichtung=3.0,
               toleranz_bogenmin=1.0, versuche=4, abbruch=None, log=log_print):
    """Auf das Ziel schwenken und so lange nachführen, bis die gelöste Mitte innerhalb der
    Toleranz liegt. Gibt {'abstand_bogenmin', 'versuche', 'mitte': (ra_h, dec)} zurück."""
    ziel_ra = float(ziel_ra_h) * 15.0
    montierung.schwenken(ziel_ra_h, ziel_dec)
    abstand = None
    for versuch in range(1, int(versuche) + 1):
        if abbruch is not None and abbruch.is_set():
            raise RuntimeError("Zentrieren abgebrochen")
        glaube_ra_h, glaube_dec = montierung.position()
        bild = kamera.belichten(belichtung)
        ra, dec, _ = bildmitte(bild, katalog, glaube_ra_h * 15.0, glaube_dec, pixelskala, log=log)
        abstand = winkelabstand(ra, dec, ziel_ra, ziel_dec) * 60.0
        log("Zentrieren %d: Bildmitte RA %.4f h, Dec %+.4f° — %.2f′ vom Ziel"
            % (versuch, ra / 15.0, dec, abstand))
        if abstand <= toleranz_bogenmin:
            return {"abstand_bogenmin": abstand, "versuche": versuch, "mitte": (ra / 15.0, dec)}
        montierung.synchronisieren(ra / 15.0, dec)
        montierung.schwenken(ziel_ra_h, ziel_dec)
    raise RuntimeError("Nach %d Versuchen noch %.2f′ vom Ziel (Toleranz %.2f′) — Montierung "
                       "oder Bildmaßstab prüfen." % (versuche, abstand, toleranz_bogenmin))
