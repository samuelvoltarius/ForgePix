"""Observation metadata derived only from the lights actually used and reference.

FITS time semantics: Rots et al., sections 4.1/4.4/4.6,
https://arxiv.org/html/1409.7583v1 . DATE-OBS is not intrinsically a start time;
DATE-BEG/END describe bounds, and a DATE-AVG needs an explicitly stated method.
Astropy time-scale arithmetic: https://docs.astropy.org/en/stable/time/index.html .

This module reads primary headers only. Its hashes prove source *metadata*, not
pixel contents. It never reads current equipment settings, copies a source WCS,
or derives stack gain, saturation, variance, units or photometric qualification.
"""
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import warnings

import numpy as np
from astropy.io import fits
from astropy.time import Time, TimeDelta

_TEXT_CONSTANTS = ("OBJECT", "FILTER", "INSTRUME", "TELESCOP", "OBSERVER")
_NUMBER_CONSTANTS = ("CCD-TEMP", "SET-TEMP", "APTDIA", "OBSGEO-X", "OBSGEO-Y", "OBSGEO-Z")
_GEOMETRY = ("RA", "DEC", "OBJCTRA", "OBJCTDEC", "FOCALLEN", "XPIXSZ", "YPIXSZ", "XBINNING", "YBINNING")
_TIME = ("DATE-OBS", "MJD-OBS", "DATE-BEG", "MJD-BEG", "DATE-END", "MJD-END", "DATE-AVG", "MJD-AVG", "TIMESYS", "TREFPOS")
_RAW_NOISE = ("GAIN", "EGAIN", "OFFSET", "BLACKLEV", "BLACKLEVEL", "SATURATE", "SATLEVEL", "RDNOISE", "READNOIS")
_KEYS = set(_TEXT_CONSTANTS + _NUMBER_CONSTANTS + _GEOMETRY + _TIME + _RAW_NOISE +
            ("EXPTIME", "EXPOSURE", "BUNIT", "FPLINEAR", "FPDOMAIN", "BAYERPAT", "IMAGETYP", "IMAGETYPE", "BITPIX", "BSCALE", "BZERO"))
_OWN_CARDS = ("NCOMBINE", "FPTOTEXP", "FPNEXP", "FPNTIME", "FPETMETH", "FPETEXAC", "FPTEPOCH", "FPTSCAL",
              "FPTSPAN", "FPTSPR", "FPMHASH", "FPOBIN", "FPOSCALE", "FPRXPSZ", "FPRYPSZ", "FPRXBIN", "FPRYBIN", "PIXSCALE")


def _cancel(cancel):
    if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
        raise InterruptedError("Observation metadata collection cancelled.")


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _number(value, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        return None
    result = float(value)
    return result if math.isfinite(result) and (not positive or result > 0) else None


def _record(path, cancel):
    _cancel(cancel)
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() not in {".fits", ".fit", ".fts"}:
        raise ValueError("Observation metadata requires actual FITS light files.")
    before = path.stat()
    with path.open("rb") as stream:
        header = fits.Header.fromfile(stream)
        header_size = stream.tell()
        stream.seek(0)
        raw_header = stream.read(header_size)
    after = path.stat()
    if ((before.st_size, before.st_mtime_ns, before.st_ino) !=
            (after.st_size, after.st_mtime_ns, after.st_ino)):
        raise ValueError("A FITS source changed while its metadata was being read.")
    if header.get("SIMPLE") is not True or not isinstance(header.get("NAXIS"), int) or header["NAXIS"] < 2:
        raise ValueError("Observation metadata requires a primary FITS image header.")
    counts = Counter(card.keyword for card in header.cards)
    metadata = {}
    for key in sorted(_KEYS & set(header)):
        value = header[key]
        if isinstance(value, np.generic):
            value = value.item()
        valid = isinstance(value, (str, int, float, bool)) and not (isinstance(value, float) and not math.isfinite(value))
        metadata[key] = {"value": value if valid else None, "comment": header.comments[key],
                         "duplicate": counts[key] > 1, "valid_json_value": valid}
    return {"path": str(path), "bytes": before.st_size, "mtime_ns": before.st_mtime_ns,
            "primary_header_bytes": header_size, "primary_header_sha256": hashlib.sha256(raw_header).hexdigest(),
            "metadata": metadata}


def _get(record, key):
    card = record["metadata"].get(key, {})
    return None if card.get("duplicate") else card.get("value")


def _comment(record, key):
    return record["metadata"].get(key, {}).get("comment", "")


def _exposure(record):
    present = [key for key in ("EXPTIME", "EXPOSURE") if key in record["metadata"]]
    values = [_number(_get(record, key), positive=True) for key in present]
    if not present:
        return {"seconds": None, "status": "missing", "keywords": []}
    if any(value is None for value in values):
        return {"seconds": None, "status": "invalid", "keywords": present}
    if not all(math.isclose(value, values[0], rel_tol=1e-9, abs_tol=1e-6) for value in values):
        return {"seconds": None, "status": "conflicting_exposure_keywords", "keywords": present}
    return {"seconds": values[0], "status": "known", "keywords": present}


def _start_comment(comment):
    text = comment.lower()
    return (bool(re.search(r"\b(start|begin|beginning)\b", text))
            and bool(re.search(r"\b(exposure|observation|image)\b", text))
            and not re.search(r"\b(not|end|middle|midpoint|average)\b", text))


def _times(record, exposure, date_obs_is_start, tolerance):
    """Return JSON details plus complete physical exposure bounds, if established."""
    scale_value = _get(record, "TIMESYS")
    scale = "utc" if "TIMESYS" not in record["metadata"] else str(scale_value).lower().strip()
    info = {"status": "missing_start", "input_time_scale": scale,
            "default_timesys_utc": "TIMESYS" not in record["metadata"],
            "date_obs_start_override": date_obs_is_start, "reference_position": _get(record, "TREFPOS"),
            "begin_utc": None, "end_utc": None, "midpoint_utc": None}
    if scale not in {"utc", "tai", "tt", "tdb", "tcb", "tcg"}:
        info["status"] = "unsupported_time_scale"
        return info, None
    # This bounded workflow does not combine timestamps already light-time
    # corrected to different spatial origins. Scale conversion alone is not that correction.
    if _get(record, "TREFPOS") not in (None, "TOPOCENTER", "GEOCENTER"):
        info["status"] = "unsupported_time_reference_position"
        return info, None
    groups = {}
    try:
        for role in ("BEG", "OBS", "END", "AVG"):
            entries = []
            for prefix, fmt in (("DATE", "fits"), ("MJD", "mjd")):
                key = prefix + "-" + role
                if key not in record["metadata"]:
                    continue
                value = _get(record, key)
                if value is None or isinstance(value, bool):
                    raise ValueError("invalid_time_keyword:" + key)
                if fmt == "fits" and (not isinstance(value, str) or "T" not in value):
                    raise ValueError("time_of_day_missing:" + key)
                if fmt == "mjd" and _number(value) is None:
                    raise ValueError("invalid_time_keyword:" + key)
                instant = Time(value, format=fmt, scale=scale)
                if not np.isfinite(instant.tai.jd):
                    raise ValueError("invalid_time_keyword:" + key)
                entries.append((key, instant))
            if entries and any(abs((time.tai - entries[0][1].tai).sec) > tolerance for _, time in entries[1:]):
                raise ValueError("conflicting_" + role.lower() + "_aliases")
            groups[role] = entries
        begin = groups["BEG"][0][1] if groups["BEG"] else None
        obs_is_start = date_obs_is_start or any(_start_comment(_comment(record, key)) for key, _ in groups["OBS"])
        info["date_obs_start_comment"] = obs_is_start and not date_obs_is_start
        if groups["OBS"]:
            info["date_obs_role"] = "start" if obs_is_start else "ambiguous"
            if obs_is_start:
                observation = groups["OBS"][0][1]
                if begin is not None and abs((begin.tai - observation.tai).sec) > tolerance:
                    raise ValueError("conflicting_begin_and_observation_start")
                if begin is None:
                    begin = observation
                    info["begin_method"] = "DATE/MJD-OBS with explicit start semantics"
        if groups["BEG"]:
            info["begin_method"] = "DATE/MJD-BEG"
        end = groups["END"][0][1] if groups["END"] else None
        seconds = exposure["seconds"]
        if seconds is None:
            info["status"] = "exposure_missing_or_invalid"
            info["known_begin_utc"] = _iso(begin) if begin is not None else None
            info["known_end_utc"] = _iso(end) if end is not None else None
            return info, None
        if begin is None and end is not None:
            begin = end.tai - TimeDelta(seconds, format="sec")
            info["begin_method"] = "DATE/MJD-END minus exposure"
        if begin is None:
            info["status"] = "ambiguous_date_obs" if groups["OBS"] else "missing_start"
            return info, None
        predicted_end = begin.tai + TimeDelta(seconds, format="sec")
        if end is not None and abs((end.tai - predicted_end).sec) > tolerance:
            raise ValueError("conflicting_end_and_exposure")
        # Consistent aliases never replace the exposure-defined midpoint with a
        # separately defined header average of unknown weighting.
        middle = begin.tai + TimeDelta(seconds / 2, format="sec")
        if groups["AVG"] and abs((groups["AVG"][0][1].tai - middle).sec) > tolerance:
            raise ValueError("conflicting_average_and_exposure_midpoint")
        info.update(status="known", begin_utc=_iso(begin), end_utc=_iso(predicted_end),
                    midpoint_utc=_iso(middle), midpoint_tcb_jyear=float(middle.tcb.jyear))
        return info, (begin.tai, predicted_end, middle)
    except (ValueError, TypeError, OverflowError) as exc:
        info["status"] = "invalid_or_conflicting_time"
        info["reason"] = str(exc)
        return info, None


def _iso(time):
    utc = time.utc
    utc.precision = 9
    return str(utc.isot)


def _consistent(values):
    known = [value for value in values if value is not None]
    distinct = list(dict.fromkeys(known))
    if len(known) != len(values):
        status = "missing_or_invalid"
    elif len(distinct) != 1:
        status = "inconsistent"
    else:
        status = "consistent"
    return {"status": status, "known_count": len(known), "missing_indices": [i for i, value in enumerate(values) if value is None],
            "distinct_values": distinct}, (known[0] if status == "consistent" else None)


def _reference_geometry(record, output_bin, drizzle_scale):
    hints = {}
    for key in ("RA", "DEC", "OBJCTRA", "OBJCTDEC"):
        value = _get(record, key)
        if ((isinstance(value, str) and value.strip()) or _number(value) is not None):
            hints[key] = value
    focal = _number(_get(record, "FOCALLEN"), positive=True)
    if focal is not None:
        hints["FOCALLEN"] = focal
    pixel_info, scales = {}, []
    for axis in ("X", "Y"):
        pixel = _number(_get(record, axis + "PIXSZ"), positive=True)
        binning = _number(_get(record, axis + "BINNING"), positive=True)
        if binning is not None and not binning.is_integer():
            binning = None
        comment = _comment(record, axis + "PIXSZ").lower()
        convention, image_pixel, sensor_pixel = "unknown", None, None
        if pixel is not None:
            if "unbinned" in comment or "sensor pixel" in comment:
                convention, sensor_pixel = "reported_unbinned_sensor_pixel", pixel
                image_pixel = pixel * binning if binning is not None else None
            elif "with binning" in comment or "after binning" in comment or "binned pixel" in comment:
                convention, image_pixel = "reported_image_pixel_includes_camera_binning", pixel
                sensor_pixel = pixel / binning if binning is not None else None
            elif binning == 1:
                convention, image_pixel, sensor_pixel = "explicit_camera_bin_1", pixel, pixel
        pixel_info[axis] = {"reported_pixel_size_um": pixel, "camera_bin": binning,
                            "pixel_size_comment": _comment(record, axis + "PIXSZ"), "convention": convention,
                            "reference_image_pixel_size_um": image_pixel, "sensor_pixel_size_um": sensor_pixel}
        scales.append(math.degrees(math.atan(image_pixel / (1000 * focal))) * 3600
                      if image_pixel is not None and focal is not None else None)
    factor = output_bin / drizzle_scale
    scale = math.sqrt(scales[0] * scales[1]) * factor if all(value is not None for value in scales) else None
    if scale is not None and math.isfinite(scale) and scale > 0:
        hints["PIXSCALE"] = scale
    same_grid = output_bin == 1 and drizzle_scale == 1
    if same_grid:
        for axis in ("X", "Y"):
            for suffix, value in (("PIXSZ", pixel_info[axis]["reported_pixel_size_um"]), ("BINNING", pixel_info[axis]["camera_bin"])):
                if value is not None:
                    hints[axis + suffix] = value
    return {"hints": hints, "pixel_axes": pixel_info,
            "reference_pixelscale_axes_arcsec": scales, "output_pixelscale_arcsec": scale,
            "pixelscale_method": "geometric mean of atan(reported image-pixel microns / (1000 * focal mm)); times output_bin/drizzle_scale",
            "pixelscale_is_search_hint_not_wcs": True, "standard_pixel_cards_preserved": same_grid}


def build_metadata(paths, reference_path, *, date_obs_is_start=False, combination="sigma",
                   output_bin=1, drizzle_scale=1., time_tolerance_seconds=.001, cancel=None):
    """Summarize actual used lights; unknown or inconsistent fields stay absent.

    Paths must be distinct FITS light files, not the initially submitted list.
    An external geometric reference is allowed but never counted as a light.
    DATE-OBS requires the explicit boolean override or a clear start comment.
    Effective time is the exposure-duration-weighted mean of exposure midpoints,
    evaluated in continuous TAI seconds; UTC and TCB are output representations.
    It is not the sigma stack's unknown per-pixel statistical weighting epoch.
    """
    _cancel(cancel)
    if type(date_obs_is_start) is not bool:
        raise ValueError("date_obs_is_start must be an explicit boolean.")
    if (isinstance(output_bin, bool) or _number(output_bin, positive=True) is None or int(output_bin) != output_bin
            or _number(drizzle_scale, positive=True) is None or _number(time_tolerance_seconds, positive=True) is None):
        raise ValueError("Sampling and timing parameters must be finite and positive; output_bin must be an integer.")
    if not isinstance(combination, str) or not combination.strip():
        raise ValueError("combination must name the actual integration method.")
    if not isinstance(paths, (list, tuple)) or not paths:
        raise ValueError("Supply a nonempty list of actual used FITS lights.")
    resolved = [Path(path).resolve(strict=True) for path in paths]
    identities = [os.path.normcase(str(path)) for path in resolved]
    if len(set(identities)) != len(identities):
        raise ValueError("Actual used light paths must not contain duplicates.")
    reference_path = Path(reference_path).resolve(strict=True)
    records = [_record(path, cancel) for path in resolved]
    reference = next((record for record in records if os.path.normcase(record["path"]) == os.path.normcase(str(reference_path))), None)
    reference_is_used = reference is not None
    if reference is None:
        reference = _record(reference_path, cancel)
    exposures = [_exposure(record) for record in records]
    constants, consistency = {}, {}
    for key in _TEXT_CONSTANTS + _NUMBER_CONSTANTS + ("EXPTIME",):
        if key == "EXPTIME":
            values = [item["seconds"] for item in exposures]
        elif key in _TEXT_CONSTANTS:
            values = [value.strip() if isinstance(value := _get(record, key), str) and value.strip() else None for record in records]
        else:
            values = [_number(_get(record, key)) for record in records]
        consistency[key], value = _consistent(values)
        if value is not None:
            constants[key] = value
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        frame_times = [_times(record, exposure, date_obs_is_start, time_tolerance_seconds)
                       for record, exposure in zip(records, exposures)]
        valid = [i for i, (_, times) in enumerate(frame_times) if times is not None]
        valid_set = set(valid)
        timing = {"complete": len(valid) == len(records), "known_frames": len(valid),
                  "missing_or_invalid_indices": [i for i in range(len(records)) if i not in valid_set],
                  "status_counts": dict(Counter(info["status"] for info, _ in frame_times)),
                  "method": "exposure_duration_weighted_mean_of_exposure_midpoints_in_TAI",
                  "header_time_scale": "UTC", "effective_epoch_scale": "TCB", "consistency_tolerance_seconds": float(time_tolerance_seconds),
                  "per_pixel_weighting_verified": False, "barycentric_light_time_correction_applied": False,
                  "begin_utc": None, "end_utc": None, "average_utc": None, "average_mjd_utc": None,
                  "effective_epoch_tcb_jyear": None, "span_seconds": None, "midpoint_spread_seconds": None}
        if valid:
            beginning = min(frame_times[i][1][0] for i in valid)
            ending = max(frame_times[i][1][1] for i in valid)
            timing["known_subset_span"] = {"begin_utc": _iso(beginning), "end_utc": _iso(ending),
                                           "seconds": float((ending - beginning).sec), "complete": timing["complete"]}
        if timing["complete"]:
            offsets = np.array([(times[2] - beginning).sec for _, times in frame_times])
            weights = np.array([item["seconds"] for item in exposures])
            offset = float(np.average(offsets, weights=weights))
            average = beginning + TimeDelta(offset, format="sec")
            timing.update(begin_utc=_iso(beginning), end_utc=_iso(ending), average_utc=_iso(average),
                          begin_mjd_utc=float(beginning.utc.mjd), end_mjd_utc=float(ending.utc.mjd),
                          average_mjd_utc=float(average.utc.mjd), effective_epoch_tcb_jyear=float(average.tcb.jyear),
                          span_seconds=float((ending - beginning).sec),
                          midpoint_spread_seconds=float(np.sqrt(np.average((offsets - offset) ** 2, weights=weights))))
        timing["conversion_warnings"] = sorted({str(item.message) for item in emitted})
    known_exposures = [item["seconds"] for item in exposures if item["seconds"] is not None]
    summary = {"format": "ForgePixObservationMetadata", "schema_version": 1, "ncombine": len(records),
               "constants": constants, "consistency": consistency,
               "exposure": {"complete": len(known_exposures) == len(records), "known_frames": len(known_exposures),
                   "integration_seconds": float(math.fsum(known_exposures)) if len(known_exposures) == len(records) else None,
                   "known_subset_seconds": float(math.fsum(known_exposures)), "unit": "s", "per_frame": exposures,
                   "is_mean_stack_brightness_or_effective_gain": False},
               "timing": timing, "frame_timing": [info for info, _ in frame_times],
               "reference": {"path": str(reference_path), "is_used_light": reference_is_used,
                              **_reference_geometry(reference, int(output_bin), float(drizzle_scale))},
               "sampling": {"output_bin": int(output_bin), "drizzle_scale": float(drizzle_scale),
                            "output_to_reference_linear_factor": float(output_bin / drizzle_scale),
                            "output_pixel_area_in_reference_pixels": float((output_bin / drizzle_scale) ** 2),
                            "camera_bin_is_separate": True},
               "combination": combination, "sources": records, "reference_source": reference,
               "source_metadata_sha256": _json_hash({"lights": records, "reference": reference}),
               "limitations": ["Header provenance only: pixel contents were not hashed by this helper.",
                   "Inputs must be the actual accepted lights and actual geometric reference, supplied by the integration pipeline.",
                   "DATE-AVG is a declared exposure-weighted midpoint estimate, not exact sigma/median/drizzle per-pixel weighting.",
                   "Exposure sums describe acquisition duration; they do not multiply mean-stack brightness or establish effective gain.",
                   "No camera gain, saturation, variance, coverage, linearity or physical output units are inferred.",
                   "Reference pointing and optical sampling are search hints only; source WCS is never copied.",
                   "TCB represents the timestamp scale conversion only, without barycentric photon-arrival correction or clock-accuracy validation."]}
    verify_sources(summary, cancel=cancel)
    return summary


def verify_sources(summary, *, cancel=None):
    """Check metadata SHA, file size and mtime again before a later publication."""
    checked = set()
    for original in [*summary["sources"], summary["reference_source"]]:
        if original["path"] in checked:
            continue
        checked.add(original["path"])
        if _record(original["path"], cancel) != original:
            raise ValueError("A FITS source changed after observation metadata collection.")
    return True


def apply_to_header(header, summary):
    """Return a copy of a current-output header with the verified summary fields.

    Source WCS is not imported. A caller's existing current-grid WCS and output
    units/linearity/coverage are untouched. Stale acquisition times, reference
    hints and raw camera-noise cards are removed before adding this summary.
    The caller remains responsible for current scientific export metadata.
    """
    if summary.get("format") != "ForgePixObservationMetadata" or summary.get("schema_version") != 1:
        raise ValueError("Unsupported observation metadata summary.")
    output = fits.Header(header).copy()
    for key in _TEXT_CONSTANTS + _NUMBER_CONSTANTS + _GEOMETRY + _TIME + _RAW_NOISE + _OWN_CARDS + ("EXPTIME", "EXPOSURE", "TSTART", "TSTOP"):
        output.remove(key, ignore_missing=True, remove_all=True)
    for key, value in summary["constants"].items():
        if key in _TEXT_CONSTANTS + _NUMBER_CONSTANTS + ("EXPTIME",):
            output[key] = (value, "Same in all used lights" if key != "EXPTIME" else "Common single-light seconds, not sum")
    output["NCOMBINE"] = (summary["ncombine"], "Actual number of used light files")
    output["FPNEXP"] = (summary["exposure"]["known_frames"], "Used lights with known exposure duration")
    if summary["exposure"]["integration_seconds"] is not None:
        output["FPTOTEXP"] = (summary["exposure"]["integration_seconds"], "Sum of input exposures [s], not stack gain")
    timing = summary["timing"]
    output["FPNTIME"] = (timing["known_frames"], "Used lights with known complete exposure times")
    if timing["complete"]:
        output["TIMESYS"] = "UTC"
        for prefix, name in (("BEG", "begin"), ("END", "end"), ("AVG", "average")):
            output["DATE-" + prefix] = timing[name + "_utc"]
            output["MJD-" + prefix] = timing[name + "_mjd_utc"]
        output["FPETMETH"] = ("EXPOSURE_WEIGHTED_MIDPOINTS", "Exposure-duration weights")
        output["FPETEXAC"] = (False, "Exact per-pixel stacking time weights unknown")
        output["FPTEPOCH"] = (timing["effective_epoch_tcb_jyear"], "Effective epoch as TCB Julian year")
        output["FPTSCAL"] = ("TCB", "Time scale of FPTEPOCH only")
        output["FPTSPAN"] = (timing["span_seconds"], "Last exposure end minus first begin [s]")
        output["FPTSPR"] = (timing["midpoint_spread_seconds"], "Weighted midpoint standard deviation [s]")
    for key, value in summary["reference"]["hints"].items():
        if key in _GEOMETRY + ("PIXSCALE",):
            output[key] = (value, "Actual reference hint; not a solved output WCS")
    for axis in ("X", "Y"):
        detail = summary["reference"]["pixel_axes"][axis]
        for suffix, item in (("PSZ", "reported_pixel_size_um"), ("BIN", "camera_bin")):
            if detail[item] is not None:
                output["FPR" + axis + suffix] = (detail[item], "Actual reference acquisition metadata")
    output["FPOBIN"] = (summary["sampling"]["output_bin"], "Software output bin, separate from camera bin")
    output["FPOSCALE"] = (summary["sampling"]["drizzle_scale"], "Output drizzle scale relative to software bin")
    # A 64-digit hash leaves no room for a FITS-card comment; its contract is
    # documented in the JSON and module rather than truncating the header card.
    output["FPMHASH"] = summary["source_metadata_sha256"]
    output.add_history("ForgePix: observation metadata from actual used lights; original camera noise is not stack noise.")
    return output
