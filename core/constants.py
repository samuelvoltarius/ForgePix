#!/usr/bin/env python3
"""
constants.py — gemeinsame Konstanten für ForgePix (eine zentrale Definition,
damit Module nicht auseinanderlaufen).
"""

import os

VERSION = "1.27.1-beta"

# Kamera-RAW-Formate, die rawpy entwickeln kann
RAW_EXTS = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".rw2", ".dng", ".orf", ".pef", ".srw"}

# Übliche Bildformate
STD_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}

# FITS (Astro)
FITS_EXTS = {".fit", ".fits", ".fts"}


def to_uint8(img):
    """Bild nach uint8 bringen (16-bit → /256). Eine Definition statt des
    verstreuten `(img/256).astype(uint8) if img.max()>255 …`-Idioms."""
    import numpy as np
    if img is None or img.dtype == np.uint8:
        return img
    if img.max() > 255:
        return (img / 256).astype(np.uint8)
    return img.astype(np.uint8)


# Rec.709-Luma-Koeffizienten in OpenCV-Kanalreihenfolge (B, G, R).
LUMA_BGR_709 = (0.0722, 0.7152, 0.2126)


def luma(bgr):
    """Rec.709-Luminanz eines BGR-Bilds (float). Eine Definition, damit
    „Luminanz" in allen Modulen dasselbe bedeutet (vorher 601/709 gemischt)."""
    b, g, r = LUMA_BGR_709
    return bgr[..., 0] * b + bgr[..., 1] * g + bgr[..., 2] * r


def force_utf8_stdio():
    """stdout/stderr hart auf UTF-8 stellen — MUSS als Erstes in jedem Einstiegspunkt laufen.

    Grund (echter Absturz, kein Schoenheitsfehler): unter Windows ist die Konsolen- und
    Pipe-Kodierung die Locale-Codepage (auf deutschen Systemen cp1252). Die Logzeilen
    enthalten aber ueberall Zeichen, die cp1252 NICHT kennt (→, ─, σ, α …).
    Jedes print() damit warf `UnicodeEncodeError` und riss die ganze Pipeline ab
    (auch `--help`). Die GUI liest den Kindprozess ohnehin als UTF-8 — vorher kam
    dort im besten Fall Buchstabensalat, im schlechtesten gar nichts.

    errors="replace": eine unbekannte Glyphe darf einen Stack NIE abbrechen.
    """
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass   # z. B. bereits ersetzter Stream (Tests/PyInstaller) — nie fatal


# ---------------------------------------------------------------------------
# Unicode-sichere Bild-Ein-/Ausgabe (Windows!)
#
# `cv2.imread`/`cv2.imwrite` reichen den Pfad unter Windows an die ANSI-C-Laufzeit
# weiter. Jeder Pfad mit Nicht-ASCII-Zeichen scheitert dort — schon ein deutsches
# „Blüte_01.jpg" oder ein Nutzerordner „C:\Users\Jürgen\\". Belegt gemessen:
#     cv2.imread("…/Blüte_normal.jpg")   -> None        (Bild wird nie geladen)
#     cv2.imwrite("…/out_Grün.jpg", img) -> True,      ABER es entsteht KEINE Datei
# Das zweite ist das gefährlichere: ForgePix meldete „Fertig", und das Ergebnis war weg.
# Auf dem Mac (Entwicklungssystem) fällt beides nicht auf, dort sind Pfade UTF-8.
#
# Lösung: Bytes selbst lesen/schreiben (numpy kann Unicode-Pfade) und nur das
# Dekodieren/Kodieren von OpenCV erledigen lassen.
# ---------------------------------------------------------------------------

def imread(path, flags=None):
    """Wie cv2.imread, aber unicode-pfadfest. Gibt wie das Original bei Fehler None zurück."""
    import cv2
    import numpy as np
    if flags is None:
        flags = cv2.IMREAD_COLOR
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except (OSError, ValueError):
        return None                      # fehlend/unlesbar -> None (imread-Semantik)
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, flags)


def imwrite(path, img, params=None):
    """Wie cv2.imwrite, aber unicode-pfadfest. Gibt True/False zurück — und zwar
    ehrlich: False heißt, es liegt auch wirklich keine Datei da."""
    import cv2
    import numpy as np
    ext = os.path.splitext(path)[1] or ".png"
    try:
        ok, buf = cv2.imencode(ext, img, params if params is not None else [])
        if not ok:
            return False
        np.asarray(buf).tofile(path)
        return True
    except (OSError, ValueError, cv2.error):
        return False


def log_print(*args, **kwargs):
    """Standard-Logger der Engine-Funktionen (`log=log_print` statt `log=print`).

    Warum nicht einfach `print`: die Logzeilen enthalten „→/σ/α/─". Wird ein Engine-Modul
    aus einem Prozess heraus benutzt, dessen stdout die Windows-Locale-Codepage hat
    (Tests, fremde Skripte, `python -c`), warf das blanke `print` einen UnicodeEncodeError
    — mitten in einem laufenden Stack. Eine Logzeile darf eine Berechnung NIE abbrechen.
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        import sys
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        safe = [str(a).encode(enc, "replace").decode(enc, "replace") for a in args]
        print(*safe, **kwargs)
