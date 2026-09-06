"""Native linear channel extraction and composition, with explicit spectral limits.

RGB channel values are measurements of overlapping sensor responses. Dual-band
extraction estimates the red line from R and oxygen from (2G+B)/3; it is not a
QE-corrected spectral inversion. Missing emission lines are never synthesized.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

import cv2
import numpy as np
import tifffile

import astro
import filters
from constants import ForgePixFehler, imwrite, log_print, require_astropy


PRESETS = {"RGB": ("R", "G", "B"), "HOO": ("Ha", "OIII", "OIII"),
           "SOO": ("SII", "OIII", "OIII"), "SHO": ("SII", "Ha", "OIII")}
FITS_EXTENSIONS = {".fit", ".fits", ".fts"}


def read(path, mono=False):
    """Read a developed linear file; raw CFA and display files need other workflows."""
    source = Path(path)
    header = None
    if source.suffix.lower() in FITS_EXTENSIONS:
        fits = require_astropy("Lineare Kanäle lesen")
        header = fits.getheader(source)
        if header.get("BAYERPAT"):
            raise ForgePixFehler("Bitte zuerst die FITS-Serie kalibrieren und stacken; "
                                 "dieses Werkzeug benötigt fertige lineare Kanäle.")
        raw = fits.getdata(source)
        is_mono = raw.ndim == 2
    elif source.suffix.lower() in {".tif", ".tiff"}:
        with tifffile.TiffFile(source) as file:
            is_mono = len(file.series[0].shape) == 2
            try:
                metadata = json.loads(file.pages[0].description or "{}")
            except (ValueError, TypeError):
                metadata = {}
            if isinstance(metadata, dict) and metadata.get("forgepix"):
                if metadata.get("linear") is False:
                    raise ForgePixFehler("Dieses Bild wurde bereits gestreckt. Bitte das lineare Ergebnis wählen.")
                header = metadata
    else:
        raise ForgePixFehler("Bitte ein lineares FITS- oder TIFF-Bild verwenden.")
    if mono and not is_mono:
        raise ForgePixFehler("Für die Kombination bitte einkanalige Bilder wählen. "
                             "Ein Farbbild zuerst in Kanäle trennen.")
    if not mono and is_mono:
        raise ForgePixFehler("Zum Trennen wird ein lineares RGB-Farbbild benötigt.")
    image = astro._read_float(str(source))
    if not image.size or not np.isfinite(image).all():
        raise ForgePixFehler("Das Bild enthält ungültige Pixelwerte.")
    return (image[..., 0] if mono else image), header


def _coverage(path, header, shape):
    name = header.get("FPCOV") if header else None
    if not name:
        return np.ones(shape, bool)
    if not isinstance(name, str) or Path(name).name != name:
        raise ForgePixFehler("Ungültiger Verweis auf die Bildabdeckung.")
    sidecar = Path(path).parent / name
    if not sidecar.is_file():
        raise ForgePixFehler("Die benötigte Bildabdeckung fehlt: %s" % sidecar)
    mask = tifffile.imread(sidecar)
    if mask.shape != shape or not np.isin(mask, [0, 1]).all():
        raise ForgePixFehler("Die Bildabdeckung passt nicht zum Kanal.")
    return mask.astype(bool)


def extract(image, filter_key=None):
    a = np.asarray(image, np.float32)
    if a.ndim != 3 or a.shape[-1] != 3 or not a.size or not np.isfinite(a).all():
        raise ForgePixFehler("Kanäle benötigen ein gültiges RGB-Bild.")
    if not filter_key:
        return {name: a[..., index].copy() for name, index in (("R", 2), ("G", 1), ("B", 0))}
    profile = filters.hole(filter_key)
    if profile is None or profile.art != "dualband" or set(profile.linien) not in (
            {"Ha", "OIII"}, {"SII", "OIII"}):
        raise ForgePixFehler("Die Linienabschätzung benötigt einen bekannten Ha/OIII- "
                             "oder SII/OIII-Dualbandfilter.")
    red = "SII" if "SII" in profile.linien else "Ha"
    return {red: a[..., 2].copy(), "OIII": a[..., 1] * np.float32(2 / 3)
            + a[..., 0] * np.float32(1 / 3)}


def combine(planes, preset="RGB", gains=None):
    if preset not in PRESETS:
        raise ForgePixFehler("Unbekannte Kanalkombination: %s" % preset)
    required = PRESETS[preset]
    missing = sorted(set(required) - set(planes))
    if missing:
        raise ForgePixFehler("Für %s fehlt: %s. Nur vorhandene Aufnahmen verwenden."
                             % (preset, ", ".join(missing)))
    arrays = {key: np.asarray(planes[key], np.float32) for key in set(required)}
    shape = arrays[required[0]].shape
    gains = gains or {}
    for key, a in arrays.items():
        if a.ndim != 2 or a.shape != shape or not a.size or not np.isfinite(a).all():
            raise ForgePixFehler("Alle Kanäle müssen gültige, gleich große 2D-Bilder sein.")
        value = float(gains.get(key, 1))
        if not np.isfinite(value) or not 0 <= value <= 10:
            raise ForgePixFehler("Kanalstärken müssen zwischen 0 und 10 liegen.")
        arrays[key] = a * np.float32(value)
    result = np.stack([arrays[key] for key in reversed(required)], axis=-1)
    if not np.isfinite(result).all():
        raise ForgePixFehler("Die Kanalstärken erzeugen Werte außerhalb des Float32-Bereichs.")
    return result


def _source_record(path):
    source = Path(path)
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(source.resolve()), "sha256": digest}


def _destination(parent):
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="channels-", dir=parent))


def _write(path, image, line=None, estimate=False, coordinates=None):
    fits = require_astropy("Lineare Kanäle speichern")
    rgb = image[..., ::-1] if image.ndim == 3 else image
    metadata = {"forgepix": True, "linear": True, "FPLINE": line,
                "FPCHTYPE": "ESTIMATE" if estimate else "CHANNEL", "FPCOV": "coverage.tif"}
    if coordinates:
        metadata["FPCOORD"] = coordinates
    tifffile.imwrite(path.with_suffix(".tif"), rgb, metadata=None, description=json.dumps(metadata),
                     photometric="rgb" if image.ndim == 3 else "minisblack")
    header = fits.Header({"CREATOR": "ForgePix", "IMAGETYP": "MASTER LIGHT",
                          "FPCHTYPE": "ESTIMATE" if estimate else "CHANNEL", "FPCOV": "coverage.tif"})
    if line:
        header["FPLINE"] = line
    if coordinates:
        header["FPCOORD"] = coordinates
    data = np.moveaxis(rgb, -1, 0) if image.ndim == 3 else rgb
    fits.writeto(path.with_suffix(".fits"), data, header)


def split_file(path, filter_key=None, output_dir=None, log=log_print):
    image, header = read(path)
    planes = extract(image, filter_key)
    coverage = _coverage(path, header, image.shape[:2])
    record = _source_record(path)
    coordinates = (header.get("FPCOORD") if header else None) or uuid.uuid4().hex
    destination = _destination(output_dir or Path(path).parent)
    tifffile.imwrite(destination / "coverage.tif", coverage.astype(np.uint8), metadata=None)
    for line, plane in planes.items():
        _write(destination / line, plane, line, estimate=bool(filter_key), coordinates=coordinates)
    report = {"operation": "extract", "source": record, "filter": filter_key,
              "channels": list(planes), "shape": list(image.shape[:2]),
              "method": "R; OIII=(2*G+B)/3" if filter_key else "identity RGB split",
              "spectral_estimate": bool(filter_key),
              "limitations": "No sensor QE correction or removal of continuum/crosstalk." if filter_key else None}
    (destination / "channels.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log("Kanäle als lineare Float32-FITS und TIFF gespeichert: %s" % destination)
    return str(destination)


def combine_files(paths, preset="RGB", gains=None, align=True, output_dir=None, log=log_print):
    required = PRESETS.get(preset)
    if required is None or not set(required).issubset(paths):
        raise ForgePixFehler("Für diese Kombination fehlen Aufnahmen.")
    names = list(dict.fromkeys(required))
    planes, records, masks, coordinate_ids = {}, {}, {}, {}
    for key in names:
        plane, header = read(paths[key], mono=True)
        if header and header.get("FPLINE") and header["FPLINE"] != key:
            raise ForgePixFehler("%s ist als %s gespeichert, wurde aber %s zugeordnet."
                                 % (Path(paths[key]).name, header["FPLINE"], key))
        planes[key] = plane
        masks[key] = _coverage(paths[key], header, plane.shape)
        records[key] = _source_record(paths[key])
        records[key]["spectral_estimate"] = bool(header and header.get("FPCHTYPE") == "ESTIMATE")
        coordinate_ids[key] = header.get("FPCOORD") if header else None
    if preset != "RGB" and len({Path(paths[key]).resolve() for key in names}) != len(names):
        raise ForgePixFehler("Verschiedene Emissionslinien benötigen eigene Kanaldateien.")
    # Validate before alignment/writes. Equal dimensions do not prove alignment.
    combine(planes, preset, gains)
    reference = planes[names[0]]
    h, w = reference.shape
    coverage = masks[names[0]].copy()
    transforms = {}
    alignment_methods = {}
    if align:
        for key in names[1:]:
            shared_grid = coordinate_ids[key] and coordinate_ids[key] == coordinate_ids[names[0]]
            if shared_grid or np.array_equal(planes[key], reference):
                matrix = np.eye(2, 3, dtype=np.float32)
                alignment_methods[key] = "shared grid" if shared_grid else "identical pixels"
            else:
                alignment_methods[key] = "star transform"
                matrix = astro._estimate_star_transform(reference, planes[key])
                if matrix is None:
                    matrix = astro._estimate_star_transform_robust(reference, planes[key])
            if matrix is None or not np.isfinite(matrix).all():
                raise ForgePixFehler("%s konnte nicht sicher an %s ausgerichtet werden. "
                                     "Bitte Bilder desselben Sternfelds verwenden." % (key, names[0]))
            transforms[key] = matrix.tolist()
            support = cv2.warpAffine(masks[key].astype(np.float32), matrix, (w, h),
                                     flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            coverage &= support >= .999999
            planes[key] = cv2.warpAffine(planes[key], matrix, (w, h),
                                        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            log("%s an %s ausgerichtet." % (key, names[0]))
    else:
        for mask in masks.values():
            coverage &= mask
    if not coverage.any():
        raise ForgePixFehler("Die Kanäle haben keine gemeinsame Bildabdeckung.")
    result = combine(planes, preset, gains)
    result[~coverage] = 0
    destination = _destination(output_dir or Path(paths[names[0]]).parent)
    _write(destination / "combined_32bit", result,
           estimate=any(record["spectral_estimate"] for record in records.values()),
           coordinates=coordinate_ids[names[0]] or uuid.uuid4().hex)
    tifffile.imwrite(destination / "coverage.tif", coverage.astype(np.uint8), metadata=None)
    view = astro.mtf_stretch(np.clip(result, 0, 1), target_bg=.18, denoise_chroma=False)
    preview = destination / "preview.jpg"
    if not imwrite(str(preview), np.round(np.clip(view, 0, 1) * 255).astype(np.uint8)):
        raise ForgePixFehler("Die Kanalvorschau konnte nicht gespeichert werden.")
    report = {"operation": "combine", "preset": preset, "rgb_mapping": list(required),
              "sources": records, "gains": gains or {}, "alignment": "automatic" if align else "user supplied aligned images",
              "alignment_methods": alignment_methods,
              "reference": names[0], "transforms": transforms,
              "coordinate_ids": coordinate_ids,
              "interpolation": "bilinear", "coverage_fraction": float(coverage.mean()),
              "uncovered_pixels": "zero, identified by coverage.tif",
              "shape": list(result.shape), "range": [float(result.min()), float(result.max())]}
    (destination / "channels.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log("Kanalkombination gespeichert: %s" % destination)
    return str(preview)
