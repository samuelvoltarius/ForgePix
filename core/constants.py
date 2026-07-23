#!/usr/bin/env python3
"""
constants.py — gemeinsame Konstanten für ForgePix (eine zentrale Definition,
damit Module nicht auseinanderlaufen).
"""

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
