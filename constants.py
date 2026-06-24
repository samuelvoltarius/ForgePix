#!/usr/bin/env python3
"""
constants.py — gemeinsame Konstanten für StackForge (eine zentrale Definition,
damit Module nicht auseinanderlaufen).
"""

VERSION = "1.6.0"

# Kamera-RAW-Formate, die rawpy entwickeln kann
RAW_EXTS = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".rw2", ".dng", ".orf", ".pef", ".srw"}

# Übliche Bildformate
STD_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}

# FITS (Astro)
FITS_EXTS = {".fit", ".fits", ".fts"}
