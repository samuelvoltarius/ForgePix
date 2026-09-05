"""ForgePix-native postprocessing. No external application or model is required."""
import os
import numpy as np
import cv2
import tifffile
import astro
import wavelet
from constants import imwrite, ForgePixFehler, log_print


def develop(linear_bgr, background=True, denoise=.6, log=log_print):
    """Conservative display rendering; input remains an untouched linear array."""
    f = np.asarray(linear_bgr, np.float32).copy()
    if not np.isfinite(f).all():
        raise ForgePixFehler("Das Bild enthaelt ungueltige Pixelwerte.")
    if background:
        log("  1/3 Hintergrund mit eigener Flaechenanpassung ausgleichen")
        f = astro.background_extract(f)
    f = astro.neutralize_background(astro.color_balance(f))
    log("  2/3 Helligkeit sichtbar machen (MTF)")
    view = astro.mtf_stretch(f, target_bg=.18, denoise_chroma=False)
    log("  3/3 Rauschen auf mehreren Groessenskalen reduzieren")
    view = wavelet.wavelet_denoise(view, strength=denoise, levels=4)
    return np.clip(astro.neutralize_background(astro.remove_green_cast(view)), 0, 1)


def run(path, work_dir=None, log=log_print):
    if os.path.splitext(path)[1].lower() not in (".fit", ".fits", ".fts", ".tif", ".tiff"):
        raise ForgePixFehler("Bitte das lineare FITS- oder TIFF-Ergebnis verwenden, keine JPEG-Vorschau.")
    work_dir = work_dir or os.path.join(os.path.dirname(path), "forgepix_developed")
    os.makedirs(work_dir, exist_ok=True)
    view = develop(astro._read_float(path), log=log)
    tifffile.imwrite(os.path.join(work_dir, "developed_32bit.tif"), view[..., ::-1], photometric="rgb")
    out = os.path.join(work_dir, "developed.jpg")
    if not imwrite(out, np.round(view * 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise ForgePixFehler("Das entwickelte Bild konnte nicht gespeichert werden.")
    return out
