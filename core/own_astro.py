"""ForgePix-native postprocessing. No external application or model is required."""
import os
import json
import tempfile
import numpy as np
import cv2
import tifffile
import astro
import wavelet
import filters
from constants import imwrite, ForgePixFehler, log_print


def develop(linear_bgr, background=True, denoise=.6, log=log_print, filter_key=None):
    """Conservative display rendering; input remains an untouched linear array."""
    f = np.asarray(linear_bgr, np.float32).copy()
    if not np.isfinite(f).all():
        raise ForgePixFehler("Das Bild enthaelt ungueltige Pixelwerte.")
    if background:
        log("  1/3 Hintergrund mit eigener Flaechenanpassung ausgleichen")
        f = astro.background_extract(f)
    profile = filters.hole(filter_key)
    narrowband = bool(profile and profile.art in ("dualband", "multiband", "schmalband"))
    if not narrowband:
        f = astro.neutralize_background(astro.color_balance(f))
    log("  2/3 Helligkeit sichtbar machen (MTF)")
    view = astro.mtf_stretch(f, target_bg=.18, denoise_chroma=False)
    log("  3/3 Rauschen auf mehreren Groessenskalen reduzieren")
    view = wavelet.wavelet_denoise(view, strength=denoise, levels=4)
    if not narrowband:
        view = astro.neutralize_background(astro.remove_green_cast(view))
    return np.clip(view, 0, 1)


def run(path, work_dir=None, log=log_print, filter_key=None):
    if os.path.splitext(path)[1].lower() not in (".fit", ".fits", ".fts", ".tif", ".tiff"):
        raise ForgePixFehler("Bitte das lineare FITS- oder TIFF-Ergebnis verwenden, keine JPEG-Vorschau.")
    parent = work_dir or os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="forgepix-developed-", dir=parent)
    view = develop(astro._read_float(path), log=log, filter_key=filter_key)
    tifffile.imwrite(os.path.join(work_dir, "developed_32bit.tif"), view[..., ::-1], photometric="rgb",
                     description=json.dumps({"forgepix": True, "linear": False, "filter": filter_key}))
    out = os.path.join(work_dir, "developed.jpg")
    if not imwrite(out, np.round(view * 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise ForgePixFehler("Das entwickelte Bild konnte nicht gespeichert werden.")
    with open(os.path.join(work_dir, "development.json"), "w", encoding="utf-8") as stream:
        json.dump({"source": os.path.abspath(path), "filter": filter_key,
                   "output": "stretched display rendering, not linear measurement data"}, stream, indent=2)
    return out
