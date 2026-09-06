"""Read-only catalogue aperture diagnostics in the original FITS pixel units.

This does not fit or apply a colour calibration. The report records missing
acquisition evidence instead of inferring camera response from equipment names.
"""
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import tempfile

import numpy as np
import tifffile
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy import units as u
from astropy.wcs import WCS
from astropy.wcs.utils import skycoord_to_pixel

from ai_restore import _cancelled, _file_integrity
from aperture_photometry import measure_stars
from constants import ForgePixFehler, log_print
from photometric_catalogue import PhotometricCatalogue


def _proof(path, cancel):
    return dict(_file_integrity(Path(path), cancel), path=str(Path(path).resolve()))


def _read_fits(path):
    if path.suffix.lower() not in {".fit", ".fits", ".fts"}:
        raise ForgePixFehler("Die Sternmessung benötigt ein FITS, keine JPEG- oder TIFF-Vorschau.")
    with fits.open(path, memmap=False) as hdus:
        if len(hdus) != 1 or hdus[0].data is None:
            raise ForgePixFehler("Die Sternmessung benötigt genau ein Bild im primären FITS-HDU.")
        data, header = hdus[0].data, hdus[0].header.copy()
        if (data.ndim not in (2, 3) or (data.ndim == 3 and data.shape[0] != 3)
                or data.dtype.kind not in "uif" or not data.size):
            raise ForgePixFehler("Das FITS benötigt ein Mono-Bild oder RGB-Ebenen (3, Höhe, Breite).")
        dtype = str(data.dtype)
        if data.dtype.kind in "ui" and data.dtype.itemsize == 8:
            if np.any(data > 2**53) or (data.dtype.kind == "i" and np.any(data < -(2**53))):
                raise ForgePixFehler("64-Bit-Ganzzahlpixel außerhalb ±2^53 sind nicht verlustfrei als Float64 messbar.")
        # Astropy has already applied BSCALE/BZERO. Do not normalize or clip.
        image = np.array(np.moveaxis(data, 0, -1) if data.ndim == 3 else data, dtype=np.float64)
    return image, header, dtype


def observation_epoch(header, override=None):
    """Return an explicitly supported Julian epoch and its provenance.

    A stack's DATE-OBS alone is not a time average of its contributing samples.
    The caller may supply a documented effective epoch; it remains an override.
    """
    if override is not None:
        if isinstance(override, (bool, str)) or not np.isfinite(override) or not 1800 <= override <= 2200:
            raise ForgePixFehler("Die Aufnahmeepoche muss eine endliche Jahreszahl zwischen 1800 und 2200 sein.")
        return {"jyear": float(override), "source": "explicit_effective_epoch", "time_scale": "tcb",
                "status": "provided", "stack_epoch_weighting_verified": False}
    scale = str(header.get("TIMESYS", "UTC")).lower()
    # UT1 requires an independently provisioned Earth-rotation table; this
    # offline diagnostic must not trigger an automatic IERS network request.
    if scale not in {"utc", "tai", "tt", "tdb", "tcb", "tcg"}:
        return {"jyear": None, "status": "unsupported_time_scale", "time_scale": scale}
    # Only a stated average is meaningful for a combined image. Single-frame
    # timing cannot silently become stack timing when a frame count is absent.
    times = []
    for key, fmt in (("MJD-AVG", "mjd"), ("DATE-AVG", "fits")):
        if key in header:
            try:
                value = float(header[key]) if fmt == "mjd" else str(header[key])
                t = Time(value, format=fmt, scale=scale)
                if not np.isfinite(t.tcb.jyear):
                    raise ValueError()
                times.append((key, t))
            except (ValueError, TypeError, OverflowError):
                return {"jyear": None, "status": "invalid_average_time", "source": key}
    if times:
        if len(times) == 2 and abs((times[0][1] - times[1][1]).to_value(u.s)) > 1:
            return {"jyear": None, "status": "conflicting_average_times"}
        key, t = times[0]
        return {"jyear": float(t.tcb.jyear), "source": key, "status": "header_average",
                "time_scale": "tcb", "input_time_scale": scale, "default_timesys_utc": "TIMESYS" not in header,
                "stack_epoch_weighting_verified": False}
    return {"jyear": None, "status": "effective_epoch_missing",
            "date_obs": str(header.get("DATE-OBS", "")) or None,
            "reason": "DATE-OBS is not a documented effective stack epoch; supply an average or explicit epoch."}


def _coverage(source, header, shape, cancel):
    """Read declared sampling masks, allowing holes but never treating weights as variance."""
    records, masks = [], []
    for key in ("FPCOV", "FPDRZCOV", "FPDRZWGT"):
        if key not in header:
            continue
        name = header[key]
        if (not isinstance(name, str) or not name or Path(name).name != name or Path(name).drive
                or any(c in name for c in ("/", "\\", "\x00", ":")) or name in {".", ".."}):
            raise ForgePixFehler("Ungültiger Verweis auf die Bildabdeckung.")
        path = (source.parent / name).resolve()
        if path.parent != source.parent or path == source or not path.is_file():
            raise ForgePixFehler("Die angegebene Bildabdeckung fehlt oder liegt außerhalb des Bildordners.")
        proof = _proof(path, cancel)
        data = tifffile.imread(path)
        allowed = (shape[:2],) if key == "FPCOV" else (shape[:2], shape)
        if data.dtype.kind not in "buif" or data.shape not in allowed or not np.isfinite(data).all():
            raise ForgePixFehler("Die Sampling-Begleitdatei passt nicht zum FITS-Bild.")
        if key != "FPDRZWGT" and not np.isin(data, [0, 1]).all():
            raise ForgePixFehler("Die Bildabdeckung muss eine binäre Maske sein.")
        if np.any(data < 0):
            raise ForgePixFehler("Sampling-Gewichte dürfen nicht negativ sein.")
        valid = data > 0
        masks.append(np.all(valid, axis=-1) if valid.ndim == 3 else valid)
        records.append(dict(proof, header_key=key, shape=list(data.shape),
                            meaning="sampling_support_only_not_variance"))
    return (np.logical_and.reduce(masks) if masks else None), records


def _finite(value):
    if isinstance(value, (str, np.str_)):
        return str(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    value = float(value)
    return value if np.isfinite(value) else None


def diagnose_file(source, catalogue_path, output_root=None, *, epoch_jyear=None,
                  saturation=None, variance_path=None, linear_confirmed=False,
                  aperture_radius=6., annulus_inner=9., annulus_outer=14.,
                  cancel=None, log=log_print):
    """Publish JSON/CSV measurements only. Original FITS and catalogue stay untouched.

    Saturation is an explicit threshold in the physical input pixel units; raw
    camera limits/gain and overlap weights are not silently reused for a stack.
    Variance, if supplied, must be a FITS image of the same shape in input-unit².
    It describes diagonal variance only, not resampling covariance.
    """
    source, catalogue_path = Path(source).resolve(), Path(catalogue_path).resolve()
    parent = Path(output_root).resolve() if output_root else source.parent
    if not parent.is_dir():
        raise ForgePixFehler("Bitte einen vorhandenen Ergebnisordner wählen.")
    if type(linear_confirmed) is not bool:
        raise ForgePixFehler("Die Linearitätsbestätigung muss ein Wahrheitswert sein.")
    _cancelled(cancel)
    proofs = [_proof(source, cancel), _proof(catalogue_path, cancel)]
    image, header, dtype = _read_fits(source)
    if header.get("BAYERPAT") and image.ndim == 2:
        raise ForgePixFehler("Bayer-Rohdaten zuerst kalibrieren, registrieren und debayern oder drizzeln.")
    if header.get("FPLINEAR") is False:
        raise ForgePixFehler("Für Sternphotometrie bitte das lineare FITS vor dem Stretch wählen.")
    if ("AI" in str(header.get("FPDOMAIN", "")).upper() or header.get("FPAITASK")
            or str(header.get("FPCHTYPE", "")).upper() in {"RESIDUAL", "ESTIMATE"}):
        raise ForgePixFehler("Für Sternphotometrie bitte das gemessene lineare FITS vor KI und Sternentfernung wählen.")
    try:
        wcs = WCS(header, fix=False).celestial
        if not wcs.has_celestial or wcs.pixel_n_dim != 2:
            raise ValueError()
        matrix = wcs.pixel_scale_matrix
        if not np.isfinite(matrix).all() or np.linalg.matrix_rank(matrix) != 2:
            raise ValueError()
        # Validate the image projection, not just the presence of two CTYPE cards.
        center = wcs.pixel_to_world((image.shape[1] - 1) / 2, (image.shape[0] - 1) / 2)
        if not np.isfinite([center.icrs.ra.deg, center.icrs.dec.deg]).all():
            raise ValueError()
    except Exception as exc:
        raise ForgePixFehler("Dem FITS fehlt eine gültige Himmelslösung (WCS). Bitte zuerst die eigene Astrometrie ausführen.") from exc
    epoch = observation_epoch(header, epoch_jyear)
    catalogue = PhotometricCatalogue.load(catalogue_path)
    positions = catalogue.positions_at(epoch["jyear"])
    columns = catalogue.columns
    quality = catalogue.quality_mask()
    # Reference coordinates keep a diagnostic visible if epoch/PM are missing.
    # Such rows are explicitly excluded from any future colour fit.
    usable = np.asarray(positions["usable"], bool)
    ra = np.where(usable, positions["ra"], columns["ra"])
    dec = np.where(usable, positions["dec"], columns["dec"])
    sky = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
    try:
        x, y = skycoord_to_pixel(sky, wcs, origin=0, mode="all")
    except Exception as exc:
        raise ForgePixFehler("Katalogpositionen konnten nicht auf das FITS abgebildet werden.") from exc
    margin = float(annulus_outer) + float(aperture_radius)
    selected = np.flatnonzero(np.isfinite(x) & np.isfinite(y) & (x >= -margin) & (y >= -margin)
        & (x <= image.shape[1] - 1 + margin) & (y <= image.shape[0] - 1 + margin))
    if selected.size > 20000:
        raise ForgePixFehler("Die Diagnose ist auf 20.000 Sterne im Bildfeld begrenzt. Bitte einen kleineren Katalogauszug wählen.")
    coverage, support = _coverage(source, header, image.shape, cancel)
    proofs.extend(support)
    variance = None
    if variance_path is not None:
        variance_path = Path(variance_path).resolve()
        proofs.append(_proof(variance_path, cancel))
        variance, _, _ = _read_fits(variance_path)
        if variance.shape != image.shape or variance_path == source:
            raise ForgePixFehler("Die Varianz benötigt eine eigene FITS-Datei in derselben Bildform und Eingangseinheit².")
    _cancelled(cancel)
    log("Native Sternmessung: %d Katalogpositionen; ausschließlich Diagnose, keine Farbänderung." % selected.size)
    measurement = measure_stars(image, np.column_stack((x[selected], y[selected])),
        source_ids=columns["source_id"][selected], aperture_radius=aperture_radius,
        annulus_inner=annulus_inner, annulus_outer=annulus_outer, coverage=coverage,
        saturation=saturation, variance=variance, cancel=cancel)
    linear = header.get("FPLINEAR") is True or linear_confirmed
    for row, index in zip(measurement["stars"], selected):
        row["catalogue"] = {key: _finite(value[index]) for key, value in columns.items() if key != "source_id"}
        row["position_epoch_status"] = str(positions["status"][index])
        row["position_at_observation_epoch"] = bool(usable[index])
        row["catalogue_quality_passed"] = bool(quality[index])
        # Diagnostic usability is distinct from production photometric approval.
        row["aperture_eligible"] = bool(row.get("fit_eligible", False))
        row["fit_eligible"] = False
        row["calibration_applied"] = False
    measurement["summary"]["aperture_eligible"] = sum(row["aperture_eligible"] for row in measurement["stars"])
    measurement["summary"]["fit_eligible"] = 0
    report = {"format": "ForgePixPhotometryDiagnostics", "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(), "source": proofs[0], "catalogue": proofs[1],
        "source_files": proofs[2:], "catalogue_metadata": catalogue.metadata,
        "catalogue_quality": catalogue.quality_report(),
        "epoch": epoch, "position_propagation": positions["report"],
        "image": {"shape": list(image.shape), "original_dtype": dtype,
                  "unit": header.get("BUNIT"), "pixel_normalization": "none",
                  "flux_semantics": "weighted aperture sum in input pixel units",
                  "drizzle_output_pixel_area": _finite(header["FPPIXARE"]) if "FPPIXARE" in header else None,
                  "pixel_area_correction_applied": False,
                  "linear_evidence": "header" if header.get("FPLINEAR") is True else "explicit" if linear_confirmed else "unknown",
                  "filter": header.get("FILTER"), "wcs_used": True,
                  "wcs_independently_validated_in_this_step": False,
                  "sampling_support_known": coverage is not None,
                  "saturation_source": "explicit_input_units" if saturation is not None else "unknown",
                  "variance_source": str(variance_path) if variance_path is not None else None,
                  "variance_contract": "input_unit_squared_diagonal_only" if variance is not None else None},
        "measurement": measurement, "catalogue_rows": len(columns["source_id"]),
        "positions_in_or_near_image": int(selected.size), "pixels_unchanged": True,
        "image_written": False, "color_calibration_applied": False, "release_approved": False,
        "limitations": ["Diagnostics only: no PCC/SPCC fit or channel gains.",
            "GSPC Johnson-Kron-Cousins magnitudes are not camera RGB fluxes.",
            "No measured aperture correction or correlated-noise covariance validation.",
            "A saturation threshold on a stack does not prove unsaturated individual exposures.",
            "No inference of historic filters, gain or transmission from current equipment."]}
    if not linear:
        report["limitations"].append("Input linearity is unknown; measurements cannot qualify colour calibration.")
    # Recheck every dependency before making a result directory visible.
    def verify_sources():
        for proof in proofs:
            now = _proof(proof["path"], cancel)
            if (now["sha256"], now["bytes"]) != (proof["sha256"], proof["bytes"]):
                raise ForgePixFehler("Eine Quelldatei wurde während der Sternmessung verändert.")
    verify_sources()
    _cancelled(cancel)
    staging = Path(tempfile.mkdtemp(prefix="stack-photometry-pending-", dir=parent))
    destination = parent / staging.name.replace("-pending-", "-", 1)
    created = []
    try:
        report_path = staging / "photometry_report.json"
        created.append(report_path)
        with report_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        csv_path = staging / "stars.csv"
        created.append(csv_path)
        channels = measurement["channels"]
        with csv_path.open("x", encoding="utf-8", newline="") as stream:
            fields = ["source_id", "x", "y", "position_epoch_status", "measured", "fit_eligible"]
            fields += [f"{key}_{c}" for key in ("flux", "flux_uncertainty", "snr") for c in channels]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in measurement["stars"]:
                item = {key: row.get(key) for key in fields[:6]}
                item["x"], item["y"] = row["position_xy"]
                for key in ("flux", "flux_uncertainty", "snr"):
                    values = row.get(key) or [None] * len(channels)
                    item.update({f"{key}_{c}": v for c, v in zip(channels, values)})
                writer.writerow(item)
            stream.flush()
            os.fsync(stream.fileno())
        verify_sources()
        _cancelled(cancel)
        staging.rename(destination)
        return {"report_path": str(destination / report_path.name), "csv_path": str(destination / csv_path.name), "report": report}
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        staging.rmdir()
        raise
