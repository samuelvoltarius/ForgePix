"""Check recorded FITS sensor settings before combining lights or masters.

Missing metadata remains unknown; catalogue defaults must not invent capture settings.
"""
from pathlib import Path
import math
import re
from constants import FITS_EXTS, ForgePixFehler

_FIELDS = {
    "camera": ("INSTRUME",), "gain": ("GAIN",), "offset": ("OFFSET", "BLKLEVEL"),
    "bin_x": ("XBINNING",), "bin_y": ("YBINNING",), "bayer": ("BAYERPAT",),
    "bayer_x": ("XBAYROFF",), "bayer_y": ("YBAYROFF",),
    "readout": ("READMODE", "READOUTM"), "filter": ("FILTER",),
    "exposure": ("EXPTIME", "EXPOSURE"), "temperature": ("CCD-TEMP",),
}
_NUMERIC = {"gain", "offset", "bin_x", "bin_y", "bayer_x", "bayer_y",
            "exposure", "temperature"}
_SENSOR = ("shape", "camera", "gain", "offset", "bin_x", "bin_y", "bayer",
           "bayer_x", "bayer_y", "readout")
_LABELS = {"shape": "Bildgröße", "camera": "Kamera", "gain": "Gain",
           "offset": "Offset", "bin_x": "Binning X", "bin_y": "Binning Y",
           "bayer": "Bayer-Muster", "bayer_x": "Bayer-Versatz X",
           "bayer_y": "Bayer-Versatz Y", "readout": "Auslesemodus",
           "filter": "Filter", "exposure": "Belichtungszeit", "temperature": "Sensortemperatur"}


def read_metadata(path):
    if Path(path).suffix.lower() not in FITS_EXTS:
        return None
    from astropy.io import fits
    try:
        h = fits.getheader(path)
    except (OSError, ValueError) as exc:
        raise ForgePixFehler(f"FITS-Kopfdaten nicht lesbar: {path}: {exc}") from exc
    result = {"path": str(path), "shape": tuple(h.get(f"NAXIS{i}")
              for i in range(1, int(h.get("NAXIS", 0)) + 1))}
    for field, aliases in _FIELDS.items():
        value = next((h[k] for k in aliases if k in h and str(h[k]).strip()), None)
        if value is None:
            result[field] = None
        elif field in _NUMERIC:
            try:
                value = float(value)
                result[field] = value if math.isfinite(value) else None
            except (TypeError, ValueError):
                result[field] = None
        else:
            result[field] = re.sub(r"\s+", "", str(value)).casefold()
    return result


def _compare(reference, candidate, fields, unknown, tolerances=None):
    for field in fields:
        a, b = reference.get(field), candidate.get(field)
        if a is None or b is None:
            unknown.add(_LABELS[field])
            continue
        tolerance = (tolerances or {}).get(field, 0.001)
        equal = abs(a - b) <= tolerance if field in _NUMERIC else a == b
        if not equal:
            raise ForgePixFehler(
                f"Kalibrierung/Aufnahmeserie passt nicht: {_LABELS[field]} {b!s} "
                f"in {candidate['path']} statt {a!s} in {reference['path']}. "
                "Bitte eine zusammengehörige Serie und passende Kalibrierbilder wählen.")


def validate(lights, masters, *, scale_dark=False):
    """Reject known mismatches, return a report of checks and missing metadata.

    masters maps dark/flat/bias to lists. Dark exposure scaling remains an explicit
    pipeline option; source darks must still share their own exposure and temperature.
    """
    unknown = set()
    light_meta = [m for p in lights if (m := read_metadata(p)) is not None]
    groups = {kind: [m for p in paths if (m := read_metadata(p)) is not None]
              for kind, paths in masters.items()}
    reference = light_meta[0] if light_meta else None
    if reference:
        for item in light_meta[1:]:
            _compare(reference, item, _SENSOR + ("filter",), unknown)
    for kind, group in groups.items():
        for item in group:
            if reference:
                fields = _SENSOR + (("filter",) if kind == "flat" else ())
                if kind == "dark":
                    fields += ("temperature",)
                    if not scale_dark:
                        fields += ("exposure",)
                for light in light_meta:
                    _compare(light, item, fields, unknown, {"temperature": 2.0, "exposure": .5})
            if len(group) > 1:
                _compare(group[0], item, _SENSOR + ("exposure",)
                         + (("filter",) if kind == "flat" else ("temperature",)),
                         unknown, {"temperature": 2.0})
    return {"fits_lights_checked": len(light_meta),
            "fits_calibration_checked": {k: len(v) for k, v in groups.items()},
            "missing_metadata": sorted(unknown), "known_mismatches": 0,
            "note": "Fehlende Kopfdaten sind unbekannt und wurden nicht durch Gerätevorgaben ersetzt."}
