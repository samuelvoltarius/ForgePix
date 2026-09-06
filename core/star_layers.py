"""Native classical star/background layers, preserving a reconstructable float residual.

The estimated background under stars is interpolation, not recovered hidden sky.
The residual can contain negative values; keeping it signed preserves reconstruction.
"""
import json
import os
from pathlib import Path
import tempfile
import numpy as np
import tifffile
import cv2
import astro
from constants import ForgePixFehler, imwrite, log_print


def split(image, log=log_print):
    source = np.asarray(image, np.float32)
    if source.ndim != 3 or source.shape[-1] != 3 or not np.isfinite(source).all():
        raise ForgePixFehler("Sternebenen benötigen ein gültiges lineares RGB-Bild.")
    nebula, mask = astro.remove_stars(source, log=log, full_mask=True)
    stars = source - nebula
    return nebula, stars, mask


def combine(nebula, stars, neb_amt=1.0, star_amt=1.0):
    n, s = np.asarray(nebula, np.float32), np.asarray(stars, np.float32)
    if n.shape != s.shape or n.ndim != 3 or n.shape[-1] != 3:
        raise ForgePixFehler("Stern- und Nebelebene müssen dieselbe Bildgröße haben.")
    if not np.isfinite(n).all() or not np.isfinite(s).all():
        raise ForgePixFehler("Ungültige Pixelwerte in den Sternebenen.")
    amounts = np.asarray([neb_amt, star_amt], np.float32)
    if not np.isfinite(amounts).all() or np.any(amounts < 0) or np.any(amounts > 4):
        raise ForgePixFehler("Ebenenstärken müssen zwischen 0 und 4 liegen.")
    return n * amounts[0] + s * amounts[1]


def recombine(work_dir, neb_amt=1.0, star_amt=1.0):
    work = Path(work_dir)
    # Layers are stored RGB; work internally in BGR for the common preview path.
    n = tifffile.imread(work / "nebula_32bit.tif")[..., ::-1]
    s = tifffile.imread(work / "stars_32bit.tif")[..., ::-1]
    result = combine(n, s, neb_amt, star_amt)
    # A fresh result prevents slider edits from overwriting an exported prior result.
    destination = Path(tempfile.mkdtemp(prefix="mix-", dir=work))
    tifffile.imwrite(destination / "combined_32bit.tif", result[..., ::-1], photometric="rgb")
    view = astro.mtf_stretch(np.clip(result, 0, 1), target_bg=.18, denoise_chroma=False)
    out = destination / "preview.jpg"
    if not imwrite(str(out), np.round(np.clip(view, 0, 1) * 255).astype(np.uint8)):
        raise ForgePixFehler("Die Ebenenvorschau konnte nicht gespeichert werden.")
    (destination / "mix.json").write_text(json.dumps({"nebula": float(neb_amt),
        "stars": float(star_amt), "operation": "signed additive float32"}, indent=2), encoding="utf-8")
    return str(out)


def run(path, work_dir=None, log=log_print):
    source = Path(path)
    if source.suffix.lower() not in {".fit", ".fits", ".fts", ".tif", ".tiff"}:
        raise ForgePixFehler("Bitte das lineare FITS- oder TIFF-Bild verwenden.")
    parent = Path(work_dir) if work_dir else source.parent
    parent.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="star-layers-", dir=parent))
    image = astro._read_float(str(source))
    log("Eigene klassische Sternentfernung: kleine Sterne, große Halos nur teilweise.")
    nebula, stars, mask = split(image, log=log)
    for name, layer in (("nebula", nebula), ("stars", stars)):
        tifffile.imwrite(destination / (name + "_32bit.tif"), layer[..., ::-1], photometric="rgb")
    tifffile.imwrite(destination / "mask.tif", mask.astype(np.float32))
    (destination / "layers.json").write_text(json.dumps({"source": str(source.resolve()),
        "method": "classical morphology and float Navier-Stokes inpainting",
        "scientific_limit": "Interpolated sky estimate; signed residual is not a pure stellar flux map.",
        "reconstruction_max_error": float(np.max(np.abs(combine(nebula, stars) - image)))},
        indent=2), encoding="utf-8")
    return recombine(destination)
