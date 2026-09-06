"""Separate Gaia DR3/GSPC BVR field catalogue for native diagnostic photometry.

Positions, quality flags and standard-band flux densities are retained, never
interpreted as a camera's RGB response. No colour coefficients are calculated.

ESA data models and flag semantics:
https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html
https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_performance_verification/ssec_dm_synthetic_photometry_gspc.html
https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_cu9pvp/sec_cu9pvp_colours/
https://docs.astropy.org/en/stable/coordinates/apply_space_motion.html
"""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
import warnings
import zipfile

import numpy as np

import gaia_lokal
from constants import ForgePixFehler, log_print

FORMAT = "ForgePixPhotometricCatalogue"
SCHEMA_VERSION = 1
MAX_ROWS = 20000
MAX_BYTES = 32 * 1024 * 1024
GAIA_FLOATS = ("ra", "dec", "ref_epoch", "ra_error", "dec_error", "pmra", "pmdec",
    "pmra_error", "pmdec_error", "ra_dec_corr", "ra_pmra_corr", "ra_pmdec_corr",
    "dec_pmra_corr", "dec_pmdec_corr", "pmra_pmdec_corr", "ruwe", "phot_g_mean_mag",
    "phot_g_mean_flux_over_error", "bp_rp", "phot_bp_rp_excess_factor")
GAIA_INTS = ("astrometric_params_solved", "ipd_frac_multi_peak", "duplicated_source")
GSPC_FLOATS = ("c_star",) + tuple(f"{band}_jkc_{field}" for band in "bvr"
    for field in ("mag", "flux", "flux_error"))
GSPC_FLAGS = tuple(f"{band}_jkc_flag" for band in "bvr")
COLUMNS = ("source_id",) + GAIA_FLOATS + GAIA_INTS + ("phot_variable_flag",) + GSPC_FLOATS + GSPC_FLAGS
CONTEXT = {"release": "Gaia DR3", "reference_frame": "ICRS", "epoch_time_scale": "tcb",
    "proper_motion_ra_convention": "pm_ra_cosdec", "photometric_system": "GSPC standardised Johnson-Kron-Cousins",
    "flux_unit": "W m-2 nm-1", "position_unit": "deg", "position_error_unit": "mas",
    "proper_motion_unit": "mas yr-1", "source_id_scope": "Gaia DR3 only"}


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ForgePixFehler("Photometrischer Katalog: Vorgang abgebrochen.")


def _one_dimensional(values, name, length=None):
    array = np.ma.asarray(values)
    if array.ndim != 1 or (length is not None and len(array) != length):
        raise ForgePixFehler("Photometrischer Katalog: %s muss eine gleich lange 1-D-Spalte sein." % name)
    return array


def _identifiers(values):
    array = _one_dimensional(values, "source_id")
    if len(array) > MAX_ROWS or np.any(np.ma.getmaskarray(array)):
        raise ForgePixFehler("Photometrischer Katalog: zu viele oder fehlende Stern-IDs.")
    result = []
    for value in array:
        # Never accept a float, even an integral float: its lost low bits cannot
        # be recovered after a JSON/dataframe/numpy float conversion.
        if isinstance(value, (bool, np.bool_)):
            raise ForgePixFehler("source_id benötigt verlustfreie Ganzzahlen, keine Wahrheitswerte.")
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            value = int(value)
        if not isinstance(value, (int, np.integer)) or not 0 < int(value) <= np.iinfo(np.int64).max:
            raise ForgePixFehler("source_id benötigt positive verlustfreie int64-Werte; Fließkommazahlen sind unzulässig.")
        result.append(int(value))
    result = np.asarray(result, np.int64)
    if len(np.unique(result)) != len(result):
        raise ForgePixFehler("Photometrischer Katalog: doppelte Gaia-DR3-Stern-ID.")
    return result


def _float_column(values, name, count):
    array = _one_dimensional(values, name, count)
    if np.iscomplexobj(array) or array.dtype.kind == "b":
        raise ForgePixFehler("Photometrischer Katalog: %s muss reelle Messwerte enthalten." % name)
    try:
        result = np.ma.asarray(array, np.float64).filled(np.nan)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ForgePixFehler("Photometrischer Katalog: ungültige Messwerte in %s." % name) from exc
    if np.isinf(result).any():
        raise ForgePixFehler("Photometrischer Katalog: unendliche Messwerte in %s." % name)
    if (name.endswith("_error") or name in {"ruwe", "phot_g_mean_flux_over_error"}) and np.any(result < 0):
        raise ForgePixFehler("Photometrischer Katalog: negative Unsicherheit/Qualitätsgröße in %s." % name)
    if name.endswith("_corr") and np.any(np.abs(result) > 1):
        raise ForgePixFehler("Photometrischer Katalog: Korrelationskoeffizient außerhalb −1…1.")
    if name == "ref_epoch" and np.any(np.isfinite(result) & ((result < 1800) | (result > 2200))):
        raise ForgePixFehler("Photometrischer Katalog: Referenzepoche außerhalb 1800…2200.")
    return np.array(result, copy=True)


def _integer_column(values, name, count):
    array = _one_dimensional(values, name, count)
    result = np.full(count, -1, np.int16)
    mask = np.ma.getmaskarray(array)
    high = 100 if name == "ipd_frac_multi_peak" else 255 if name == "astrometric_params_solved" else 1
    for index, value in enumerate(array):
        if mask[index] or value is None:
            continue
        if name == "duplicated_source" and isinstance(value, str) and value.lower() in {"true", "false"}:
            value = int(value.lower() == "true")
        if isinstance(value, (bool, np.bool_)) and name == "duplicated_source":
            value = int(value)
        if not isinstance(value, (int, np.integer)) or isinstance(value, (bool, np.bool_)) or not -1 <= int(value) <= high:
            raise ForgePixFehler("Photometrischer Katalog: ungültige Ganzzahl/Flag in %s." % name)
        result[index] = int(value)
    return result


class PhotometricCatalogue:
    """Read-only arrays in source order; missing optional values remain explicit.

    quality_mask() is a conservative catalogue-only diagnostic selection, not
    proof of stability, correct image matching or calibrated camera colours.
    """

    def __init__(self, columns, metadata=None):
        if not isinstance(columns, dict) or set(columns) - set(COLUMNS) or not {"source_id", "ra", "dec"} <= set(columns):
            raise ForgePixFehler("Photometrischer Katalog: source_id/ra/dec fehlen oder unbekannte Spalten liegen vor.")
        data = {"source_id": _identifiers(columns["source_id"])}
        count = len(data["source_id"])
        for name in GAIA_FLOATS + GSPC_FLOATS:
            data[name] = _float_column(columns.get(name, np.full(count, np.nan)), name, count)
        if not np.isfinite(data["ra"]).all() or not np.isfinite(data["dec"]).all() or np.any(np.abs(data["dec"]) > 90):
            raise ForgePixFehler("Photometrischer Katalog: ungültige ICRS-Positionen.")
        data["ra"] %= 360.
        for name in GAIA_INTS + GSPC_FLAGS:
            data[name] = _integer_column(columns.get(name, np.full(count, -1, np.int16)), name, count)
        values = _one_dimensional(columns.get("phot_variable_flag", [None] * count), "phot_variable_flag", count)
        mask = np.ma.getmaskarray(values)
        variability = []
        for index, value in enumerate(values):
            value = "UNKNOWN" if mask[index] or value is None else str(value)
            if value not in {"UNKNOWN", "NOT_AVAILABLE", "VARIABLE", "CONSTANT"}:
                raise ForgePixFehler("Photometrischer Katalog: unbekanntes Variabilitätsflag.")
            variability.append(value)
        data["phot_variable_flag"] = np.asarray(variability, dtype="U13")
        try:
            supplied = {} if metadata is None else metadata
            if not isinstance(supplied, dict) or any(key in supplied and supplied[key] != value for key, value in CONTEXT.items()):
                raise ValueError()
            self.metadata = json.loads(json.dumps({**CONTEXT, "origin": "provided_arrays", **supplied}, allow_nan=False))
            if len(json.dumps(self.metadata).encode("utf-8")) > 262144:
                raise ValueError()
        except (TypeError, ValueError) as exc:
            raise ForgePixFehler("Photometrischer Katalog: ungültige oder widersprüchliche Metadaten.") from exc
        # Owned copies prevent caller mutation through the supplied arrays.
        for name, values in data.items():
            data[name] = np.array(values, copy=True)
            data[name].setflags(write=False)
        self.columns = MappingProxyType(data)

    def __len__(self):
        return len(self.columns["source_id"])

    def save(self, path):
        """Write a new NPZ, never overwrite an existing catalogue or legacy NPZ."""
        path = Path(path)
        if path.suffix.lower() != ".npz" or not path.parent.is_dir():
            raise ForgePixFehler("Photometrischer Katalog: neue .npz-Datei in vorhandenem Ordner wählen.")
        buffer = io.BytesIO()
        np.savez_compressed(buffer, format=np.asarray(FORMAT), schema_version=np.int64(SCHEMA_VERSION),
            metadata_json=np.asarray(json.dumps(self.metadata, allow_nan=False)), **self.columns)
        pending = None
        try:
            if path.exists():
                raise FileExistsError(str(path))
            descriptor, filename = tempfile.mkstemp(prefix=".fpphot-", suffix=".pending", dir=path.parent)
            pending = Path(filename)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(buffer.getbuffer())
                stream.flush()
                os.fsync(stream.fileno())
            if os.name == "nt":
                os.rename(pending, path)  # Windows rename is atomic and refuses an existing destination.
            else:
                os.link(pending, path)  # Atomic exclusive publication; never POSIX rename-overwrite.
        except OSError as exc:
            raise ForgePixFehler("Photometrischer Katalog konnte nicht neu gespeichert werden: %s" % exc) from exc
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
        return str(path.resolve())

    @classmethod
    def load(cls, path):
        """Only this explicit format is accepted; legacy positional NPZ is not upgraded."""
        try:
            path = Path(path)
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("Datei zu groß")
            with zipfile.ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > MAX_BYTES:
                    raise ValueError("entpackte Datei zu groß")
            with np.load(path, allow_pickle=False) as archive:
                if set(archive.files) != set(COLUMNS) | {"format", "schema_version", "metadata_json"}:
                    raise ValueError("kein vollständiges photometrisches Feldformat")
                version = archive["schema_version"].item()
                if archive["format"].item() != FORMAT or type(version) is not int or version != SCHEMA_VERSION:
                    raise ValueError("unbekanntes photometrisches Feldformat")
                metadata = json.loads(archive["metadata_json"].item())
                if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in CONTEXT.items()):
                    raise ValueError("fehlender Koordinaten-/Einheitenvertrag")
                return cls({name: archive[name] for name in COLUMNS}, metadata=metadata)
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
            raise ForgePixFehler("Photometrischer Katalog nicht lesbar: %s" % exc) from exc

    def positions_at(self, epoch_jyear, *, cancel=None):
        """Return target ICRS positions, row status/usable and a JSON-safe report.

        Target and reference epochs are Julian years in TCB. Uniform angular
        motion assumes zero radial velocity and unknown distance; no apparent
        parallax, perspective acceleration or covariance propagation is claimed.
        Unavailable positions are NaN, never silently reused reference positions.
        """
        _cancel(cancel)
        if epoch_jyear is not None:
            epoch_jyear = gaia_lokal._zahl(epoch_jyear, "Beobachtungsepoche")
            if not 1800 <= epoch_jyear <= 2200:
                raise ForgePixFehler("Beobachtungsepoche muss zwischen 1800 und 2200 liegen.")
        ra, dec = np.full(len(self), np.nan), np.full(len(self), np.nan)
        status = np.full(len(self), "missing_observation_epoch", dtype="U32")
        warning_messages = []
        if epoch_jyear is not None:
            ref = self.columns["ref_epoch"]
            known = np.isfinite(ref)
            status[:] = "missing_reference_epoch"
            status[known] = "missing_proper_motion"
            at_reference = known & (ref == epoch_jyear)
            ra[at_reference], dec[at_reference] = self.columns["ra"][at_reference], self.columns["dec"][at_reference]
            status[at_reference] = "reference_epoch"
            propagate = known & ~at_reference & np.isfinite(self.columns["pmra"]) & np.isfinite(self.columns["pmdec"])
            if np.any(propagate):
                from astropy.coordinates import SkyCoord
                from astropy.time import Time
                from astropy import units as u
                coordinates = SkyCoord(ra=self.columns["ra"][propagate] * u.deg,
                    dec=self.columns["dec"][propagate] * u.deg,
                    pm_ra_cosdec=self.columns["pmra"][propagate] * u.mas / u.yr,
                    pm_dec=self.columns["pmdec"][propagate] * u.mas / u.yr,
                    obstime=Time(ref[propagate], format="jyear", scale="tcb"), frame="icrs")
                with warnings.catch_warnings(record=True) as emitted:
                    warnings.simplefilter("always")
                    moved = coordinates.apply_space_motion(new_obstime=Time(epoch_jyear, format="jyear", scale="tcb"))
                warning_messages = sorted({str(item.message) for item in emitted})
                ra[propagate], dec[propagate] = moved.ra.degree, moved.dec.degree
                status[propagate] = "propagated_angular_motion"
                failed = propagate & (~np.isfinite(ra) | ~np.isfinite(dec))
                status[failed] = "propagation_failed"
                ra[failed], dec[failed] = np.nan, np.nan
        _cancel(cancel)
        usable = np.isfinite(ra) & np.isfinite(dec)
        labels, counts = np.unique(status, return_counts=True)
        report = {"target_epoch_jyear": epoch_jyear, "epoch_time_scale": "tcb", "reference_frame": "ICRS",
            "rows": len(self), "usable_positions": int(usable.sum()),
            "status_counts": dict(zip(labels.tolist(), counts.tolist())), "warnings": warning_messages,
            "method": "astropy.apply_space_motion; pm_ra_cosdec; unknown distance; radial velocity assumed zero",
            "covariance_propagated": False, "perspective_acceleration_modelled": False,
            "apparent_parallax_modelled": False, "usable_is_position_only": True}
        return {"source_id": self.columns["source_id"], "ra": ra, "dec": dec,
                "usable": usable, "status": status, "report": report}

    def _quality_rejections(self):
        c = self.columns
        rejected = {}
        for band in "bvr":
            prefix = band + "_jkc_"
            flux, error = c[prefix + "flux"], c[prefix + "flux_error"]
            with np.errstate(divide="ignore", invalid="ignore"):
                rejected[band + "_invalid_band"] = (~np.isfinite(c[prefix + "mag"]) | ~np.isfinite(flux)
                    | ~np.isfinite(error) | (flux <= 0) | (error <= 0) | (flux / error < 30)
                    | (c[prefix + "flag"] != 1))
        rejected["c_star"] = ~np.isfinite(c["c_star"]) | (np.abs(c["c_star"]) > .05)
        rejected["ruwe"] = ~np.isfinite(c["ruwe"]) | (c["ruwe"] > 1.4)
        rejected["multiple_peaks"] = (c["ipd_frac_multi_peak"] < 0) | (c["ipd_frac_multi_peak"] > 2)
        rejected["duplicated_or_unknown"] = c["duplicated_source"] != 0
        rejected["variable_or_missing_flag"] = np.isin(c["phot_variable_flag"], ["VARIABLE", "UNKNOWN"])
        rejected["astrometric_solution"] = ~np.isin(c["astrometric_params_solved"], [31, 95])
        return rejected

    def quality_mask(self):
        return ~np.logical_or.reduce(list(self._quality_rejections().values()))

    def quality_report(self):
        return {"rows": len(self), "eligible_catalogue_rows": int(self.quality_mask().sum()),
            "rejected_counts_overlap": {key: int(mask.sum()) for key, mask in self._quality_rejections().items()},
            "variability_not_available": int((self.columns["phot_variable_flag"] == "NOT_AVAILABLE").sum()),
            "gates": {"gspc_bvr_flags": 1, "band_snr_min": 30, "abs_c_star_max": .05,
                      "ruwe_max": 1.4, "ipd_frac_multi_peak_percent_max": 2,
                      "duplicated_source": False, "astrometric_params_solved": [31, 95]},
            "limitations": "Catalogue diagnostic selection only; NOT_AVAILABLE is not evidence of constant brightness; image measurement and epoch checks remain required."}


def download_field(ra, dec, radius_deg=1., max_mag=15.5, limit=20000, *, cancel=None, timeout=120, log=log_print):
    """Bounded native TAP join, retaining nulls and quality failures for diagnosis."""
    _cancel(cancel)
    ra, dec, radius_deg = gaia_lokal._suchgebiet(ra, dec, radius_deg)
    limit, max_mag = gaia_lokal._zahl(limit, "Zeilenlimit"), gaia_lokal._zahl(max_mag, "G-Grenze")
    if not 0 < radius_deg <= 5 or limit != int(limit) or not 1 <= limit <= MAX_ROWS or not 5 <= max_mag <= 18:
        raise ForgePixFehler("Photometrischer Feldauszug: Radius >0 bis 5°, G-Grenze 5…18 und höchstens 20.000 Sterne.")
    select = ["g." + name for name in ("source_id",) + GAIA_FLOATS + GAIA_INTS + ("phot_variable_flag",)]
    select += ["p." + name for name in GSPC_FLOATS + GSPC_FLAGS]
    query = ("SELECT TOP %d %s FROM gaiadr3.gaia_source AS g "
        "INNER JOIN gaiadr3.synthetic_photometry_gspc AS p ON g.source_id = p.source_id "
        "WHERE 1=CONTAINS(POINT('ICRS',g.ra,g.dec),CIRCLE('ICRS',%.10f,%.10f,%.10f)) "
        "AND g.phot_g_mean_mag < %.8f ORDER BY g.source_id"
        % (int(limit) + 1, ", ".join(select), ra, dec, radius_deg, max_mag))
    log("Gaia/GSPC: photometrischen Feldauszug laden; keine Farbkorrektur.")
    result = gaia_lokal._tap_abfrage(query, cancel=cancel, timeout=timeout, raw_rows=True)
    names, rows = result["columns"], result["rows"]
    if len(rows) > limit:
        raise ForgePixFehler("Photometrischer Katalog wäre abgeschnitten: Feld verkleinern oder hellere G-Grenze wählen.")
    if set(names) != set(COLUMNS) or len(names) != len(COLUMNS):
        raise ForgePixFehler("ESA lieferte nicht die benötigten photometrischen Katalogspalten.")
    columns = {name: [row[index] for row in rows] for index, name in enumerate(names)}
    # All JSON source_id values stay Python integers until strict int64 validation.
    metadata = {"origin": "ESA TAP", "tables": ["gaiadr3.gaia_source", "gaiadr3.synthetic_photometry_gspc"],
        "field": {"ra_deg": ra, "dec_deg": dec, "radius_deg": radius_deg, "max_mag": max_mag},
        "query": query, "row_limit": int(limit), "rows_received": len(rows), "row_limit_reached": False,
        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
        "credit": "ESA/Gaia/DPAC", "data_terms_url": "https://www.cosmos.esa.int/web/gaia-users/license",
        "server_columns": result.get("metadata", []), "spatial_completeness_proven": False}
    catalogue = PhotometricCatalogue(columns, metadata)
    _cancel(cancel)
    log("Gaia/GSPC: %d Sterne gespeichert im Speicher; %d bestehen die Katalog-Diagnoseauswahl."
        % (len(catalogue), int(catalogue.quality_mask().sum())))
    return catalogue
