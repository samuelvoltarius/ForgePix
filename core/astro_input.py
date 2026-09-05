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
            if any(k in kind for k in _CALIBRATION):
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
                         and not d.lower().startswith(_CALIBRATION))
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
