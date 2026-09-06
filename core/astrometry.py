"""Native, bounded, hinted local-catalogue astrometry; no external solver or network.

Triangle correspondences discover a TAN + affine pixel model. A fixed third of
the detected stars is excluded from discovery, fitting and model selection, then
used once to decide whether the solution may be returned. This is not blind
all-sky solving, distortion calibration, epoch propagation or photometric PCC.
"""
from dataclasses import dataclass
from itertools import combinations
import math
from pathlib import Path
import re
import time

import numpy as np
from scipy.spatial import cKDTree, ConvexHull, QhullError
from scipy.stats import binom

from constants import ForgePixFehler, log_print


def _cancel(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()):
        raise ForgePixFehler("Astrometrie abgebrochen.")


def _number(value, name, minimum, maximum):
    if isinstance(value, (bool, np.bool_, str)) or np.iscomplexobj(value):
        raise ForgePixFehler("Astrometrie: %s muss eine Zahl sein." % name)
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ForgePixFehler("Astrometrie: ungültiges %s." % name) from exc
    if not np.isfinite(value) or not minimum <= value <= maximum:
        raise ForgePixFehler("Astrometrie: %s außerhalb des unterstützten Bereichs." % name)
    return value


def _shape(shape):
    try:
        if len(shape) != 2 or any(isinstance(v, bool) or int(v) != v or not 32 <= v <= 100000 for v in shape):
            raise ValueError()
        return tuple(map(int, shape))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ForgePixFehler("Astrometrie benötigt eine gültige Bildform (Höhe, Breite).") from exc


def _hints(hints, shape):
    if not isinstance(hints, dict):
        raise ForgePixFehler("Astrometrie benötigt RA, DEC und Bildmaßstab als Suchhinweise.")
    ra = _number(hints.get("ra"), "RA in Grad", 0, 360) % 360
    dec = _number(hints.get("dec"), "DEC in Grad", -90, 90)
    if hints.get("pixelscale_arcsec") is not None:
        scale = _number(hints["pixelscale_arcsec"], "Pixelmaßstab", .01, 120) / 3600
    elif hints.get("fov_width_deg") is not None:
        scale = _number(hints["fov_width_deg"], "Bildfeldbreite", .02, 5) / shape[1]
    elif hints.get("focal") is not None and hints.get("pixelsize") is not None:
        focal = _number(hints["focal"], "effektive Brennweite in mm", 10, 30000)
        pixel = _number(hints["pixelsize"], "effektive Pixelgröße in µm", .1, 100)
        scale = math.degrees(math.atan(pixel / (1000 * focal)))
    else:
        raise ForgePixFehler("Astrometrie: Bildfeldbreite, Pixelmaßstab oder Brennweite plus Pixelgröße fehlt.")
    width, height = shape[1] * scale, shape[0] * scale
    if not .02 <= width <= 5 or height > 5:
        raise ForgePixFehler("Lokale Astrometrie unterstützt Bildfelder von 0,02 bis 5 Grad je Achse.")
    diagonal = math.hypot(width, height)
    return ra, dec, scale, .9 * diagonal, .35 * diagonal


def _tangent(radec, ra, dec):
    """ICRS directions on the hinted gnomonic plane, in degrees."""
    lon, lat = np.radians(radec).T
    lon0, lat0 = np.radians([ra, dec])
    delta = lon - lon0
    divisor = np.sin(lat) * np.sin(lat0) + np.cos(lat) * np.cos(lat0) * np.cos(delta)
    if np.any(divisor <= 0):
        raise ForgePixFehler("Katalog enthält Sterne außerhalb der Tangentialprojektion.")
    return np.degrees(np.column_stack((np.cos(lat) * np.sin(delta) / divisor,
        (np.sin(lat) * np.cos(lat0) - np.cos(lat) * np.sin(lat0) * np.cos(delta)) / divisor)))


def _triangles(points, minimum_size, maximum_size):
    """Scale/rotation/parity invariant side ratios, with canonical vertex order."""
    indices = np.array(list(combinations(range(len(points)), 3)), dtype=np.int32)
    if not len(indices):
        return np.empty((0, 2)), np.empty((0, 3), dtype=np.int32)
    triangles = points[indices]
    sides = np.stack((np.linalg.norm(triangles[:, 1] - triangles[:, 2], axis=1),
                      np.linalg.norm(triangles[:, 0] - triangles[:, 2], axis=1),
                      np.linalg.norm(triangles[:, 0] - triangles[:, 1], axis=1)), axis=1)
    order = np.argsort(sides, axis=1)
    ordered = np.take_along_axis(sides, order, axis=1)
    longest = ordered[:, 2]
    ratios = ordered[:, :2] / np.maximum(longest[:, None], 1e-30)
    v, u = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    area = np.abs(v[:, 0] * u[:, 1] - v[:, 1] * u[:, 0])
    keep = ((longest >= minimum_size) & (longest <= maximum_size)
            & (ratios[:, 0] > .15) & (ratios[:, 1] - ratios[:, 0] > .01)
            & (1 - ratios[:, 1] > .01) & (area > .04 * longest ** 2))
    return ratios[keep], np.take_along_axis(indices, order, axis=1)[keep]


def _fit(points, target):
    center = points.mean(axis=0)
    design = np.column_stack((points - center, np.ones(len(points))))
    fit, _, rank, _ = np.linalg.lstsq(design, target, rcond=None)
    if rank != 3:
        return None
    fit[2] -= center @ fit[:2]
    return fit


def _plausible(fit, shape, center_limit_pixels):
    if fit is None or not np.isfinite(fit).all():
        return False
    singular = np.linalg.svd(fit[:2], compute_uv=False)
    center = np.array([(shape[1] - 1) / 2, (shape[0] - 1) / 2]) @ fit[:2] + fit[2]
    return (singular.min() >= .7 and singular.max() <= 1.3
            and singular.max() / singular.min() <= 1.08
            and np.linalg.norm(center) <= center_limit_pixels)


def _matches(points, reference, radius, forbidden=()):
    """Unique, unambiguous nearest neighbours; never reuse one catalogue star."""
    tree = reference if isinstance(reference, cKDTree) else cKDTree(reference)
    if tree.n < 2:
        return np.empty(0, int), np.empty(0, int), np.empty(0)
    distances, indices = tree.query(points, k=2)
    valid = (distances[:, 0] < radius) & (distances[:, 1] > radius * 1.5)
    order = np.flatnonzero(valid)[np.argsort(distances[valid, 0])]
    occupied, observed, catalog = set(map(int, forbidden)), [], []
    for index in order:
        star = int(indices[index, 0])
        if star not in occupied:
            occupied.add(star)
            observed.append(index)
            catalog.append(star)
    observed = np.asarray(observed, int)
    return observed, np.asarray(catalog, int), distances[observed, 0]


def _coverage(points, shape):
    try:
        area = float(ConvexHull(points).volume) / (shape[0] * shape[1])
    except QhullError:
        return 0., 0
    quadrants = (points[:, 0] >= shape[1] / 2).astype(int) + 2 * (points[:, 1] >= shape[0] / 2)
    return area, len(np.unique(quadrants))


@dataclass
class SolveResult:
    wcs: object
    report: dict
    matched_pixels: np.ndarray
    matched_radec: np.ndarray

    def to_header(self):
        header = self.wcs.to_header(relax=False)
        header["FPASOLVE"] = ("HINTED", "ForgePix native local catalogue solve")
        header["FPASRMS"] = (self.report["validation_rms_px"], "Held-out radial residual RMS, pixels")
        header["FPASVAL"] = (self.report["validation_matches"], "Independent validation stars, not fitted")
        header["FPASFIT"] = (self.report["fit_matches"], "Fitted catalogue stars")
        return header


def solve_positions(positions, shape, katalog, hints, *, cancel=None, log=log_print):
    """Solve brightness-ordered zero-based (x,y) centroids using a local Katalog.

    Search is bounded to 240 observations, 2,000 catalogue stars, 160 bright
    catalogue pattern stars and 4,000 hypotheses. Fixed acceptance gates are
    deliberately not user-adjustable. A failed held-out check ends this solve.
    """
    from astropy.wcs import WCS
    started = time.monotonic()
    _cancel(cancel)
    shape = _shape(shape)
    ra, dec, scale, radius, center_limit = _hints(hints, shape)
    try:
        original = np.asarray(positions)
        if np.iscomplexobj(original):
            raise ValueError()
        points = original.astype(np.float64)
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise ValueError()
        if np.any(points < 0) or np.any(points >= np.array(shape[::-1])):
            raise ValueError()
    except (TypeError, ValueError) as exc:
        raise ForgePixFehler("Astrometrie: ungültige Sternpositionen im Bild.") from exc
    # Deduplicate before splitting: the same source must never be its own holdout.
    selected = []
    for point in points[:600]:
        if not selected or np.min(np.linalg.norm(np.asarray(selected) - point, axis=1)) >= 3:
            selected.append(point)
        if len(selected) >= 240:
            break
    points = np.asarray(selected).reshape(-1, 2)
    if len(points) < 24:
        raise ForgePixFehler("Astrometrie: mindestens 24 getrennte Sterne für Suche und unabhängige Prüfung nötig.")
    heldout = np.arange(len(points)) % 3 == 0
    train, validation = points[~heldout], points[heldout]
    if katalog is None or not hasattr(katalog, "kegelsuche"):
        raise ForgePixFehler("Astrometrie: lokaler Gaia-Katalog fehlt.")
    metadata = getattr(katalog, "metadata", {})
    if metadata.get("reference_frame", "ICRS") != "ICRS":
        raise ForgePixFehler("Astrometrie unterstützt lokale Katalogkoordinaten im ICRS-Bezugssystem.")
    field = katalog.kegelsuche(ra, dec, radius)
    try:
        radec = np.column_stack((field["ra"], field["dec"]))
        magnitude = np.asarray(field["g_mag"])
        if np.iscomplexobj(radec) or np.iscomplexobj(magnitude):
            raise ValueError()
        radec, magnitude = radec.astype(np.float64), magnitude.astype(np.float64)
        if magnitude.shape != (len(radec),) or not np.isfinite(radec).all() or not np.isfinite(magnitude).all():
            raise ValueError()
        if np.any(np.abs(radec[:, 1]) > 90):
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise ForgePixFehler("Astrometrie: Katalogpositionen sind ungültig.") from exc
    order = np.argsort(magnitude, kind="stable")[:2000]
    radec = radec[order]
    # Identical catalogue rows cannot constitute independent references.
    _, unique = np.unique(np.round(radec, 9), axis=0, return_index=True)
    radec = radec[np.sort(unique)]
    if len(radec) < 24:
        raise ForgePixFehler("Astrometrie: lokaler Katalog enthält zu wenige Sterne in diesem Suchfeld.")
    tangent = _tangent(radec, ra, dec) / scale
    tree = cKDTree(tangent)
    log("  Eigene Astrometrie: %d Bildsterne, %d lokale Katalogsterne; %d Prüfsterne zurückgehalten."
        % (len(points), len(radec), len(validation)))
    _cancel(cancel)
    diagonal = math.hypot(*shape)
    descriptors, triples = _triangles(train[:48], diagonal * .12, diagonal * 1.05)
    cat_descriptors, cat_triples = _triangles(tangent[:160], diagonal * .08, diagonal * 1.4)
    if not len(descriptors) or not len(cat_descriptors):
        raise ForgePixFehler("Astrometrie: keine ausreichend verteilten Sternmuster im Suchfeld.")
    distances, indices = cKDTree(cat_descriptors).query(descriptors, k=min(4, len(cat_descriptors)))
    if distances.ndim == 1:
        distances, indices = distances[:, None], indices[:, None]
    candidates = np.argwhere(distances < .006)
    candidates = candidates[np.argsort(distances[tuple(candidates.T)], kind="stable")][:4000]
    best, best_score, attempted = None, (0, -np.inf), 0
    for row, column in candidates:
        if attempted % 32 == 0:
            _cancel(cancel)
            if time.monotonic() - started > 30:
                break
        attempted += 1
        fit = _fit(train[triples[row]], tangent[cat_triples[indices[row, column]]])
        if not _plausible(fit, shape, center_limit / scale):
            continue
        observed, catalog, residual = _matches(train @ fit[:2] + fit[2], tree, 3.)
        score = (len(observed), -float(np.median(residual)) if len(residual) else -np.inf)
        if score > best_score:
            best, best_score = fit, score
        if best_score[0] >= max(20, .9 * len(train)):
            break
    if best is None or best_score[0] < max(12, math.ceil(.3 * len(train))):
        raise ForgePixFehler("Astrometrie: kein belastbares Sternmuster gefunden. Bildmitte, Maßstab und Katalogfeld prüfen.")
    for _ in range(4):
        _cancel(cancel)
        observed, catalog, residual = _matches(train @ best[:2] + best[2], tree, 2.5)
        if len(observed) < 12:
            raise ForgePixFehler("Astrometrie: zu wenige eindeutige Sterne bei der Verfeinerung.")
        cutoff = min(2., max(.4, float(np.median(residual) + 4 * 1.4826 * np.median(np.abs(residual - np.median(residual))))))
        keep = residual <= cutoff
        if keep.sum() < 12:
            raise ForgePixFehler("Astrometrie: Sternzuordnungen sind nicht stabil.")
        observed, catalog = observed[keep], catalog[keep]
        best = _fit(train[observed], tangent[catalog])
        if not _plausible(best, shape, center_limit / scale):
            raise ForgePixFehler("Astrometrie: unplausibler Maßstab, Scherung oder Bildmittelpunkt.")
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.cunit = ["deg", "deg"]
    wcs.wcs.radesys = "ICRS"
    wcs.wcs.crval = [ra, dec]
    wcs.wcs.cd = best[:2].T * scale
    wcs.wcs.crpix = 1 - np.linalg.solve(best[:2].T, best[2])
    wcs.array_shape = shape
    predicted = np.column_stack(wcs.world_to_pixel_values(radec[:, 0], radec[:, 1]))
    fit_obs, fit_cat = observed, catalog
    fit_residual = np.linalg.norm(train[fit_obs] - predicted[fit_cat], axis=1)
    fit_area, fit_quadrants = _coverage(train[fit_obs], shape) if len(fit_obs) >= 3 else (0, 0)
    fit_rms = float(np.sqrt(np.mean(fit_residual ** 2))) if len(fit_obs) else np.inf
    if len(fit_obs) < max(12, math.ceil(.3 * len(train))) or fit_rms > .8 or fit_area < .12 or fit_quadrants < 3:
        raise ForgePixFehler("Astrometrie: Anpassungsfehler oder räumliche Sternabdeckung unzureichend.")
    # The one held-out decision: never refit or search another model after this.
    val_obs, val_cat, val_residual = _matches(validation, predicted, 2., forbidden=fit_cat)
    val_area, val_quadrants = _coverage(validation[val_obs], shape) if len(val_obs) >= 3 else (0, 0)
    val_rms = float(np.sqrt(np.mean(val_residual ** 2))) if len(val_obs) else np.inf
    inside = np.all((predicted >= -2) & (predicted <= np.array(shape[::-1]) + 2), axis=1)
    chance = min(1., int(inside.sum()) * math.pi * 2 ** 2 / (shape[0] * shape[1]))
    probability = float(binom.sf(len(val_obs) - 1, len(validation), chance))
    if (len(val_obs) < max(8, math.ceil(.45 * len(validation))) or val_rms > .8
            or val_area < .08 or val_quadrants < 3 or probability > 1e-10):
        raise ForgePixFehler("Astrometrie: unabhängige Prüfsterne bestätigen die Lösung nicht; kein WCS wird freigegeben.")
    center_pixel = np.array([(shape[1] - 1) / 2, (shape[0] - 1) / 2])
    center = wcs.pixel_to_world(*center_pixel)
    north_step = wcs.pixel_to_world(*(center_pixel + [0, 1]))
    singular = np.linalg.svd(wcs.wcs.cd, compute_uv=False) * 3600
    report = {
        "status": "solved", "method": "native-local-hinted-triangles-tan-affine-v1", "shape": list(shape),
        "hint_ra_deg": ra, "hint_dec_deg": dec, "search_radius_deg": radius,
        "center_ra_deg": float(center.ra.deg), "center_dec_deg": float(center.dec.deg),
        "pixelscale_arcsec": float(np.sqrt(abs(np.linalg.det(wcs.wcs.cd))) * 3600),
        "axis_scales_arcsec": singular.tolist(), "parity": int(np.sign(np.linalg.det(wcs.wcs.cd))),
        "positive_y_position_angle_deg": float(center.position_angle(north_step).deg),
        "detected_stars": len(points), "catalog_stars": len(radec), "hypotheses": attempted,
        "catalog_provenance": {key: metadata.get(key) for key in
            ("catalogue", "reference_frame", "reference_epoch_jyear", "proper_motion_applied")},
        "fit_matches": len(fit_obs), "fit_rms_px": fit_rms, "fit_hull_fraction": fit_area,
        "validation_stars": len(validation), "validation_matches": len(val_obs),
        "validation_rms_px": val_rms, "validation_max_px": float(np.max(val_residual)),
        "validation_hull_fraction": val_area, "validation_quadrants": val_quadrants,
        "uniform_chance_tail": probability, "split": "deduplicated brightness order; index % 3 == 0 held out once; never fitted",
        "elapsed_seconds": time.monotonic() - started,
        "limitations": ["Hinted field only; no all-sky blind search", "Fixed hinted TAN tangent point, affine model; no distortion terms",
            "Catalogue coordinates as stored; no proper-motion/epoch propagation", "Residuals are internal checks, not an absolute astrometric accuracy certification",
            "Chance statistic assumes uniformly distributed unrelated image detections", "No catalogue photometric or spectral color calibration"],
    }
    _cancel(cancel)
    log("  Eigene Astrometrie bestätigt: %d + %d unabhängige Sterne, Prüf-RMS %.3f px."
        % (len(fit_obs), len(val_obs), val_rms))
    return SolveResult(wcs, report, np.vstack((train[fit_obs], validation[val_obs])), radec[np.r_[fit_cat, val_cat]])


def solve(image, katalog, hints, *, cancel=None, log=log_print):
    """Detect stars in signed/HDR mono or BGR floats, preserving the input image."""
    from star_color import detect
    _cancel(cancel)
    array = np.asarray(image)
    if np.iscomplexobj(array) or not np.issubdtype(array.dtype, np.number):
        raise ForgePixFehler("Astrometrie benötigt ein reelles lineares Bild.")
    if array.ndim == 2:
        array = np.repeat(array[..., None], 3, axis=2)
    if array.ndim != 3 or array.shape[2] != 3 or not np.isfinite(array).all():
        raise ForgePixFehler("Astrometrie benötigt ein endliches Mono- oder RGB-Bild.")
    _shape(array.shape[:2])
    _hints(hints, array.shape[:2])
    with np.errstate(over="ignore"):
        measured = array.astype(np.float32)
    if not np.isfinite(measured).all():
        raise ForgePixFehler("Astrometrie: Bildwerte überschreiten den Messbereich.")
    points = detect(measured, max_stars=300)
    _cancel(cancel)
    return solve_positions(points, array.shape[:2], katalog, hints, cancel=cancel, log=log)


def solution_header(result, header=None):
    """Preserve scientific metadata, replace stale structural/scaling/WCS cards.

    Use with the original FITS data to keep its values and dtype. Coverage-file
    references are preserved; the workflow adapter must copy those companions.
    """
    from astropy.io import fits
    if not isinstance(result, SolveResult) or result.report.get("status") != "solved":
        raise ForgePixFehler("FITS-Export benötigt eine bestätigte Astrometrie-Lösung.")
    output = fits.Header(header).copy() if header is not None else fits.Header()
    obsolete = re.compile(
        r"^(SIMPLE|XTENSION|BITPIX|NAXIS\d*|PCOUNT|GCOUNT|EXTEND|BLOCKED|BSCALE|BZERO|BLANK|CHECKSUM|DATASUM|END|"
        r"WCSAXES[A-Z]?|WCSNAME[A-Z]?|WCSDIM|(?:CRPIX|CRVAL|CDELT|CTYPE|CUNIT|CNAME|CRDER|CSYER)\d+[A-Z]?|"
        r"(?:PC|CD|PV|PS)\d+_\d+[A-Z]?|(?:LONPOLE|LATPOLE|RADESYS|RADECSYS|EQUINOX|EPOCH)[A-Z]?|"
        r"(?:A|B|AP|BP)_(?:ORDER|DMAX|\d+_\d+)[A-Z]?|(?:CPDIS|CQDIS|CPERR|CQERR|D2IMDIS|D2IMERR)\d+|"
        r"(?:DP|DQ|D2IM|DET2IM)\d+(?:\..*)?|WAT\d+_\d+|LTV\d+|LTM\d+_\d+|CROTA\d+[A-Z]?)$"
    )
    for key in list(output):
        if obsolete.fullmatch(key):
            del output[key]
    output.update(result.to_header())
    output.add_history("ForgePix native hinted local-catalogue solve; independent validation; original pixels not resampled.")
    return output


def write_solution_fits(image, output_path, result, *, header=None, overwrite=False):
    """Write a separate FITS with new WCS; BGR arrays become RGB FITS planes.

    Float32/Float64 and integer values are preserved. The file/workflow adapter
    is responsible for copying coverage files referenced by the source header.
    """
    from astropy.io import fits
    output = solution_header(result, header)
    array = np.asarray(image)
    if array.dtype.kind not in "iuf" or array.shape not in (tuple(result.report["shape"]), (*result.report["shape"], 3)):
        raise ForgePixFehler("Astrometrie-FITS: Bildform passt nicht zur Lösung.")
    data = np.array(array, dtype=np.float32 if array.dtype.kind == "f" and array.dtype.itemsize < 4 else None, copy=True)
    if not np.isfinite(data).all():
        raise ForgePixFehler("Astrometrie-FITS: ungültige oder zu große Bildwerte.")
    if data.ndim == 3:
        data = np.ascontiguousarray(data[..., ::-1].transpose(2, 0, 1))
        for key in ("BAYERPAT", "XBAYROFF", "YBAYROFF"):
            output.remove(key, ignore_missing=True, remove_all=True)
    fits.PrimaryHDU(data, header=output).writeto(output_path, overwrite=overwrite, checksum=True)
    return str(Path(output_path))
