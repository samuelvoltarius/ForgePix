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


# Wie weit die Sensortemperatur eines Darks von den Lights abweichen darf.
#
# OHNE `--dark-skalieren` sind 2 K die Grenze: der Dunkelstrom verdoppelt sich je etwa 6 Grad,
# 2 K sind also schon 26 % Unterschied, die unkorrigiert abgezogen wuerden.
#
# MIT `--dark-skalieren` ist genau diese Abweichung das, was korrigiert wird — sie zu
# verbieten hiess, den Schalter fuer seinen eigenen Zweck zu sperren. Die Grenze bleibt aber
# endlich: das Modell 2^(dT/6) beschreibt den mittleren Dunkelstrom, nicht das Verhalten
# einzelner heisser Pixel, und die werden bei groesseren Spruengen nicht mehr vom selben
# Faktor getroffen. 10 K ist als Modellgrenze gesetzt, NICHT gemessen — wer sie ausreizt,
# sollte das Ergebnis ansehen.
TEMPERATUR_TOLERANZ_K = 2.0
TEMPERATUR_TOLERANZ_SKALIERT_K = 10.0


def validate(lights, masters, *, scale_dark=False):
    """Reject known mismatches, return a report of checks and missing metadata.

    masters maps dark/flat/bias to lists. Dark exposure scaling remains an explicit
    pipeline option; source darks must still share their own exposure and temperature.

    `scale_dark` weitet die Temperaturtoleranz fuer das Dark gegen die Lights — die Abweichung
    wird dann ja umgerechnet. Die Darks UNTEREINANDER muessen weiter zusammenpassen: ein
    Master aus Aufnahmen verschiedener Temperatur ist schon vor jeder Skalierung falsch.
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
                toleranz = {"exposure": .5,
                            "temperature": (TEMPERATUR_TOLERANZ_SKALIERT_K if scale_dark
                                            else TEMPERATUR_TOLERANZ_K)}
                for light in light_meta:
                    _compare(light, item, fields, unknown, toleranz)
            if len(group) > 1:
                _compare(group[0], item, _SENSOR + ("exposure",)
                         + (("filter",) if kind == "flat" else ("temperature",)),
                         unknown, {"temperature": TEMPERATUR_TOLERANZ_K})
    return {"fits_lights_checked": len(light_meta),
            "fits_calibration_checked": {k: len(v) for k, v in groups.items()},
            "missing_metadata": sorted(unknown), "known_mismatches": 0,
            "note": "Fehlende Kopfdaten sind unbekannt und wurden nicht durch Gerätevorgaben ersetzt."}
