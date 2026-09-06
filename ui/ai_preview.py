"""Display-only transforms for AI comparisons; scientific pixels stay untouched."""
import json
from pathlib import Path

import cv2
import numpy as np

from constants import ForgePixFehler, imwrite


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ForgePixFehler("KI-Verarbeitung abgebrochen.")


def display_parameters(source):
    """One linked-channel display transform, measured solely from the source."""
    low, high = (float(value) for value in np.percentile(source, [.1, 99.9]))
    scale = max(high - low, 1e-6)
    median = float(np.median(np.clip((source - low) / scale, 0, 1)))
    target = .18
    median = min(max(median, 1e-5), 1 - 1e-5)
    midtone = median * (target - 1) / (2 * target * median - target - median)
    return {"method": "source_linked_mtf_v1", "black": low, "scale": scale,
            "midtone": min(max(midtone, 1e-5), 1 - 1e-5), "target_background": target,
            "source_percentiles": [.1, 99.9], "display_only": True,
            "channels_linked": True}


def display_pixels(image, parameters, bits=8, max_side=None):
    """Apply supplied parameters without calculating new image statistics."""
    if bits not in (8, 16):
        raise ValueError("Display exports support 8 or 16 bits")
    x = np.clip((image.astype(np.float64) - parameters["black"]) / parameters["scale"], 0, 1)
    m = parameters["midtone"]
    shown = ((m - 1) * x) / ((2 * m - 1) * x - m)
    if max_side and max(shown.shape[:2]) > max_side:
        ratio = max_side / max(shown.shape[:2])
        shown = cv2.resize(shown, (max(1, round(shown.shape[1] * ratio)),
                                  max(1, round(shown.shape[0] * ratio))), interpolation=cv2.INTER_AREA)
    maximum = 255 if bits == 8 else 65535
    return np.rint(np.clip(shown, 0, 1) * maximum).astype(np.uint8 if bits == 8 else np.uint16)


def write_display(path, pixels, options=None):
    bgr = pixels[..., ::-1] if pixels.ndim == 3 else pixels
    if not imwrite(str(path), bgr, options):
        raise ForgePixFehler("Die Anzeige-Datei konnte nicht gespeichert werden: %s" % path)


def create_previews(source, result, cancel=None):
    """Write matched PNGs next to a freshly generated result, not over originals."""
    from ai_restore import read_source
    source, result = Path(source).resolve(), Path(result).resolve()
    _check_cancel(cancel)
    before = read_source(source)
    parameters = display_parameters(before)
    before_pixels = display_pixels(before, parameters, max_side=1400)
    del before
    _check_cancel(cancel)
    after = read_source(result)
    after_pixels = display_pixels(after, parameters, max_side=1400)
    del after
    _check_cancel(cancel)
    before_path, after_path = result.parent / "display_before.png", result.parent / "display_after.png"
    write_display(before_path, before_pixels)
    write_display(after_path, after_pixels)
    info = {"source": str(source), "result": str(result),
            "source_mtime_ns": source.stat().st_mtime_ns, "result_mtime_ns": result.stat().st_mtime_ns,
            "before": str(before_path), "after": str(after_path), "parameters": parameters,
            "note": "Both previews use the same source-derived display transform. FITS/TIFF stay unchanged."}
    (result.parent / "display.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def export_display(source, destination, parameters, bits=8, max_side=None, options=None):
    from ai_restore import read_source
    pixels = display_pixels(read_source(source), parameters, bits=bits, max_side=max_side)
    write_display(destination, pixels, options)
