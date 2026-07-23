#!/usr/bin/env python3
"""ui/appinfo.py — geteilte Pfad- und Namens-Konstanten für ForgePix (von mehreren ui-Modulen genutzt)."""
import os
import hashlib
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Projekt-Root (ui/ liegt darunter)
SCRIPT = os.path.join(HERE, "core", "focus_cull_stack.py")          # Pipeline-Skript liegt in core/
ICON = os.path.join(HERE, "assets", "ForgePix.icns")
ICON_PNG = os.path.join(HERE, "assets", "forgepix_512.png")
APP_NAME = "ForgePix"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def _cache_path(prefix, src):
    """Stabiler Temp-Cache-Pfad (md5 statt hash() — nicht zufallssalted, kollisionssicher).
    tempfile.gettempdir() statt hartem /tmp — sonst brechen alle Vorschauen unter Windows."""
    key = f"{src}:{os.path.getmtime(src)}".encode()
    return os.path.join(tempfile.gettempdir(), f"{prefix}{hashlib.md5(key).hexdigest()[:16]}.png")
