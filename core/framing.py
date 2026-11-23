#!/usr/bin/env python3
"""
core/framing.py — Bildfeld und Mosaik planen (wie N.I.N.A.s Framing-Assistent).

Aus Brennweite, Pixelgröße und Sensorgröße das Bildfeld; daraus ein Raster von Panelen mit
Überlappung und Drehung um eine Mitte. Gerechnet in der Tangentialebene (gnomonisch, wie FITS
„TAN“) und zurück auf den Himmel — so stimmen die Abstände auch nahe am Pol. Kein Qt.
"""
import math


def bildfeld(brennweite_mm, pixel_um, breite_px, hoehe_px, binning=1):
    """(Breite °, Höhe °, Pixelmaßstab ″/px)."""
    if brennweite_mm <= 0 or pixel_um <= 0 or breite_px <= 0 or hoehe_px <= 0 or binning < 1:
        raise ValueError("Brennweite, Pixelgröße, Sensorgröße und Binning müssen positiv sein.")
    skala = 206.264806 * pixel_um * binning / brennweite_mm
    return breite_px / binning * skala / 3600.0, hoehe_px / binning * skala / 3600.0, skala


def _aus_tangente(ra0, dec0, xi, eta):
    """Gnomonische Rückprojektion: Tangentialkoordinaten (Bogenmaß) → RA/Dec (Grad)."""
    a0, d0 = math.radians(ra0), math.radians(dec0)
    rho = math.hypot(xi, eta)
    if rho == 0:
        return ra0 % 360, dec0
    c = math.atan(rho)
    dec = math.asin(math.cos(c) * math.sin(d0) + eta * math.sin(c) * math.cos(d0) / rho)
    ra = a0 + math.atan2(xi * math.sin(c), rho * math.cos(d0) * math.cos(c) - eta * math.sin(d0) * math.sin(c))
    return math.degrees(ra) % 360, math.degrees(dec)


def panele(ra_grad, dec_grad, feld_breite, feld_hoehe, spalten=1, zeilen=1, ueberlappung=0.2,
           drehung_grad=0.0):
    """Mitten der Panele als Liste von {'name', 'ra_h', 'dec', 'spalte', 'zeile'}.

    Reihenfolge Zeile für Zeile, oben (Norden) beginnend; Spalte 1 im Osten (links im Bild,
    wenn Norden oben ist). `drehung_grad` dreht das ganze Raster am Himmel (Position Angle)."""
    if spalten < 1 or zeilen < 1:
        raise ValueError("Mindestens ein Panel.")
    if not 0.0 <= ueberlappung < 0.9:
        raise ValueError("Überlappung 0 … 0,9, nicht %r" % ueberlappung)
    sx = math.radians(feld_breite) * (1.0 - ueberlappung)
    sy = math.radians(feld_hoehe) * (1.0 - ueberlappung)
    th = math.radians(drehung_grad)
    aus = []
    for z in range(zeilen):
        for s in range(spalten):
            x = (s - (spalten - 1) / 2.0) * sx
            y = ((zeilen - 1) / 2.0 - z) * sy
            # Osten liegt bei wachsender RA → im Bild links: xi positiv nach Osten
            xi = -(x * math.cos(th) - y * math.sin(th))
            eta = x * math.sin(th) + y * math.cos(th)
            ra, dec = _aus_tangente(ra_grad, dec_grad, math.tan(xi), math.tan(eta))
            aus.append({"name": "Panel %d-%d" % (z + 1, s + 1), "ra_h": ra / 15.0, "dec": dec,
                        "spalte": s + 1, "zeile": z + 1})
    return aus
