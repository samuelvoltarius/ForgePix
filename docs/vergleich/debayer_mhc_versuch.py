"""VERSUCH, nicht im Programm benutzt (Ergebnisse: docs/vergleich/SIRIL.md, Abschnitt Debayer).

Malvar-He-Cutler-Debayer (ICASSP 2004, „High-quality linear interpolation for demosaicing of
Bayer-patterned color images“) — nach den im Aufsatz veröffentlichten 5x5-Filtern."""
import numpy as np
import cv2

_G_AN_RB = np.array([[0, 0, -1, 0, 0], [0, 0, 2, 0, 0], [-1, 2, 4, 2, -1], [0, 0, 2, 0, 0], [0, 0, -1, 0, 0]], np.float32) / 8
_RB_AN_G_ZEILE = np.array([[0, 0, .5, 0, 0], [0, -1, 0, -1, 0], [-1, 4, 5, 4, -1], [0, -1, 0, -1, 0], [0, 0, .5, 0, 0]], np.float32) / 8
_RB_AN_G_SPALTE = _RB_AN_G_ZEILE.T.copy()
_RB_AN_BR = np.array([[0, 0, -1.5, 0, 0], [0, 2, 0, 2, 0], [-1.5, 0, 6, 0, -1.5], [0, 2, 0, 2, 0], [0, 0, -1.5, 0, 0]], np.float32) / 8


def debayer_mhc(raw, pattern, x_offset=0, y_offset=0):
    raw = np.asarray(raw, np.float32)
    tile = np.array(list(pattern)).reshape(2, 2)
    tile = np.roll(tile, (-int(y_offset) % 2, -int(x_offset) % 2), axis=(0, 1))
    h, w = raw.shape
    f = lambda k: cv2.filter2D(raw, -1, k, borderType=cv2.BORDER_REFLECT_101)
    g_rb = f(_G_AN_RB); rb_gz = f(_RB_AN_G_ZEILE); rb_gs = f(_RB_AN_G_SPALTE); rb_br = f(_RB_AN_BR)
    farbe = np.empty((h, w), "<U1")
    for y in range(2):
        for x in range(2):
            farbe[y::2, x::2] = tile[y, x]
    # in welcher Zeile liegt Rot? (für G-Pixel: rote Nachbarn waagerecht oder senkrecht)
    rot_zeile = np.zeros((h, w), bool)
    for y in range(2):
        if "R" in tile[y]:
            rot_zeile[y::2, :] = True
    out = np.empty((h, w, 3), np.float32)
    istR, istG, istB = farbe == "R", farbe == "G", farbe == "B"
    # Grün
    out[..., 1] = np.where(istG, raw, g_rb)
    # Rot
    out[..., 2] = np.where(istR, raw, np.where(istB, rb_br, np.where(rot_zeile, rb_gz, rb_gs)))
    # Blau: an G in blauer Zeile waagerecht
    out[..., 0] = np.where(istB, raw, np.where(istR, rb_br, np.where(~rot_zeile, rb_gz, rb_gs)))
    return out


def cfa_hotpixel(raw, k=6.0):
    """Hot-/Cold-Pixel im CFA-Rohbild ersetzen, BEVOR debayert wird: Vergleich mit dem Median der
    8 gleichfarbigen Nachbarn (Abstand 2), Schwelle k * robuste Streuung der Abweichungen."""
    raw = np.asarray(raw, np.float32)
    pad = np.pad(raw, 2, mode="reflect")
    h, w = raw.shape
    nachbarn = np.stack([pad[2 + dy:2 + dy + h, 2 + dx:2 + dx + w]
                         for dy in (-2, 0, 2) for dx in (-2, 0, 2) if (dy, dx) != (0, 0)])
    med = np.median(nachbarn, axis=0)
    d = raw - med
    s = 1.4826 * float(np.median(np.abs(d))) + 1e-9
    schlecht = np.abs(d) > k * s
    # echte Sternspitzen schützen: Nachbarn deutlich über Median-Hintergrund = Struktur, kein Hotpixel
    struktur = (nachbarn.max(axis=0) - med) > 0.5 * np.abs(d)
    ersetzen = schlecht & ~struktur
    out = raw.copy()
    out[ersetzen] = med[ersetzen]
    return out, int(ersetzen.sum())


def debayer_mhc_sauber(raw, pattern, x_offset=0, y_offset=0):
    r, _ = cfa_hotpixel(raw)
    return debayer_mhc(r, pattern, x_offset, y_offset)
