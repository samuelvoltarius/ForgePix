"""Native diagnostic aperture measurements on original mono/RGB pixel values.

No detection, color calibration, resampling, aperture correction or image writes.
Coordinates are zero-based pixel centers. RGB is explicitly file/RGB order, not
OpenCV BGR. Fractional circle/pixel overlap uses a fixed 16 x 16 subpixel grid;
this is an approximation, not an exact geometric intersection. See the aperture
definitions at https://photutils.readthedocs.io/en/stable/user_guide/aperture.html.

Reported errors propagate a linear weighted pixel estimator with *diagonal*
pixel variances, including the fitted sky-plane coefficients. Neither a supplied
variance map nor a gain describes covariance from registration/drizzle or RGB
demosaicing. Those missing terms and PSF/aperture/centroid systematics remain
explicitly unquantified. ``fit_eligible`` denotes a measurement candidate only;
the caller must still enforce catalog, epoch, linearity and calibration gates.
"""
from collections import Counter

import numpy as np
from scipy.spatial import cKDTree

_SUBPIXELS = 16
_MAX_STARS = 20000
_MIN_SKY_PIXELS = 24
_MIN_SKY_FRACTION = .5


def _cancel(cancel):
    if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
        raise InterruptedError("Aperture photometry cancelled.")


def _channel_parameter(value, channels, name):
    if value is None:
        return None
    raw = np.asarray(value)
    if raw.dtype.kind not in "iuf" or raw.shape not in ((), (channels,)):
        raise ValueError(name + " must be a positive scalar or one value per channel.")
    array = np.broadcast_to(raw.astype(np.float64), (channels,))
    if not np.isfinite(array).all() or np.any(array <= 0):
        raise ValueError(name + " must be finite and positive in original pixel units.")
    return array


def _map(value, shape, name):
    if value is None:
        return None
    raw = np.asarray(value)
    if raw.dtype.kind not in "buif":
        raise ValueError(name + " must contain real numeric values.")
    if raw.shape == shape[:2]:
        raw = raw[..., None]
    try:
        if raw.shape not in ((), shape, (*shape[:2], 1)):
            raise ValueError()
        return np.broadcast_to(raw, shape)
    except ValueError:
        raise ValueError(name + " must be a scalar, HW map, or a map matching the image.") from None


def _ids(source_ids, count):
    if source_ids is None:
        return [None] * count
    if len(source_ids) != count:
        raise ValueError("source_ids must have one integer identifier per position.")
    result = []
    for value in source_ids:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer, str)):
            raise ValueError("source_ids must be integers or decimal strings, never floats.")
        text = str(value)
        if not text.isascii() or not text.isdecimal():
            raise ValueError("source_ids must be nonnegative decimal identifiers.")
        result.append(str(int(text)))  # JSON consumers cannot round an int64 to a float.
    if len(set(result)) != len(result):
        raise ValueError("source_ids must be unique.")
    return result


def _weights(dx, dy, radii):
    """Geometric weights only; scientific image pixels are never interpolated."""
    result = [np.zeros(dx.shape, dtype=np.float64) for _ in radii]
    offsets = (np.arange(_SUBPIXELS) + .5) / _SUBPIXELS - .5
    for sy in offsets:
        for sx in offsets:
            radius2 = (dx + sx) ** 2 + (dy + sy) ** 2
            for weight, radius in zip(result, radii):
                weight += radius2 <= radius * radius
    return [weight / (_SUBPIXELS * _SUBPIXELS) for weight in result]


def _enough_sky(design, weights, keep, full_area):
    if keep.sum() < _MIN_SKY_PIXELS or weights[keep].sum() < _MIN_SKY_FRACTION * full_area:
        return False
    # Do not extrapolate a plane from a one-sided remnant of the annulus.
    quadrants = (design[keep, 1] >= 0).astype(int) + 2 * (design[keep, 2] >= 0)
    return bool(np.all(np.bincount(quadrants, minlength=4) >= 3))


def _sky_plane(design, values, weights, variance, full_area, cancel):
    keep = np.ones(len(values), dtype=bool)
    clipping_status = "converged"
    for iteration in range(6):
        _cancel(cancel)
        if not _enough_sky(design, weights, keep, full_area):
            return None
        root_w = np.sqrt(weights[keep])
        beta, _, rank, _ = np.linalg.lstsq(design[keep] * root_w[:, None],
                                          values[keep] * root_w[:, None], rcond=None)
        if rank != 3 or not np.isfinite(beta).all():
            return None
        residual = values - design @ beta
        median = np.median(residual[keep], axis=0)
        scatter = 1.482602218505602 * np.median(np.abs(residual[keep] - median), axis=0)
        # This floor affects rejection only, not reported measurement errors.
        floor = 64 * np.finfo(float).eps * np.maximum(np.max(np.abs(values[keep]), axis=0), 1e-300)
        noise = np.maximum(scatter, floor)
        if variance is not None:
            noise = np.maximum(noise, np.sqrt(variance))
        next_keep = keep & np.all(np.abs(residual - median) <= 4 * noise, axis=1)
        if np.array_equal(next_keep, keep):
            break
        if not _enough_sky(design, weights, next_keep, full_area):
            # In a noiseless field, arbitrarily small PSF wings can shrink MAD
            # until progressively discarding real sky support. Keep the last
            # supported diagnostic fit, but do not approve it as a reference.
            clipping_status = "support_limit"
            break
        keep = next_keep
        if iteration == 5:
            clipping_status = "iteration_limit"
    if not _enough_sky(design, weights, keep, full_area):
        return None
    root_w = np.sqrt(weights[keep])
    beta, _, rank, _ = np.linalg.lstsq(design[keep] * root_w[:, None],
                                      values[keep] * root_w[:, None], rcond=None)
    if rank != 3 or not np.isfinite(beta).all():
        return None
    residual = values[keep] - design[keep] @ beta
    scatter = 1.482602218505602 * np.median(np.abs(residual - np.median(residual, axis=0)), axis=0)
    return beta, keep, scatter, clipping_status


def measure_stars(image, positions_xy, *, source_ids=None, aperture_radius=6.0,
                  annulus_inner=9.0, annulus_outer=14.0, coverage=None,
                  saturation=None, variance=None, gain=None, cancel=None):
    """Measure supplied positions without changing sign, units or HDR range.

    ``image`` is a floating HW mono or HWC RGB array. ``coverage`` is a known
    binary HW/HWC map (or scalar); all channels use their common valid samples.
    Missing coverage is *unknown*, not an implicit all-valid mask. ``saturation``
    is a scalar or channel vector giving the caller's known physical saturation
    threshold. Missing saturation never yields an eligible reference star.

    ``variance`` supplies total diagonal pixel variance in image-units squared;
    scalar, HW and HWC maps are accepted. Otherwise robust annulus MAD estimates
    sky variance and ``gain`` (electrons per image unit, scalar/channel vector)
    adds source Poisson variance. A gain must describe this actual processed
    image, not merely a camera preset. If both are supplied the variance map is
    used without adding Poisson noise twice. Missing both still permits a sky-
    noise-only diagnostic but excludes the star as an uncertainty fit candidate.

    Each position, including unusable catalog references, participates in a
    cKDTree neighbor search. Apertures closer than twice their radius are rejected;
    every other neighbor masks sky pixels out to the aperture radius plus half a
    pixel diagonal. This does not model PSF wings or restore blended flux.
    A minimum two-pixel aperture/annulus gap keeps their pixel samples disjoint;
    the diagonal uncertainty sum would otherwise omit their covariance term.

    Returns strict JSON-compatible values, with decimal-string source IDs.
    Invalid contracts raise ValueError; cancellation raises InterruptedError.
    Individual invalid/masked/saturated/edge/blended positions remain in the
    report with exclusion reasons. No thresholds for catalog color fitting are
    imposed here and no calibrated image is produced.
    """
    _cancel(cancel)
    original = np.asarray(image)
    if (original.dtype.kind != "f" or not original.size or original.ndim not in (2, 3)
            or (original.ndim == 3 and original.shape[-1] != 3)):
        raise ValueError("image must be a floating HW mono or HWC RGB array.")
    pixels = np.asarray(original, dtype=np.float64)
    if pixels.ndim == 2:
        pixels = pixels[..., None]
    height, width, channels = pixels.shape
    positions_raw = np.asarray(positions_xy)
    if positions_raw.shape == (0,):
        positions_raw = np.empty((0, 2))
    if (positions_raw.dtype.kind not in "iuf" or positions_raw.ndim != 2 or positions_raw.shape[1] != 2
            or len(positions_raw) > _MAX_STARS):
        raise ValueError("positions_xy must be an N x 2 real array with at most 20000 positions.")
    positions = positions_raw.astype(np.float64)
    identifiers = _ids(source_ids, len(positions))
    radii_raw = np.asarray([aperture_radius, annulus_inner, annulus_outer])
    if radii_raw.shape != (3,) or radii_raw.dtype.kind not in "iuf" or any(
            isinstance(value, (bool, np.bool_)) for value in (aperture_radius, annulus_inner, annulus_outer)):
        raise ValueError("Aperture and annulus radii must be real numbers.")
    radii = radii_raw.astype(float)
    if not np.isfinite(radii).all() or not 0 < radii[0] < radii[1] < radii[2]:
        raise ValueError("Require 0 < aperture_radius < annulus_inner < annulus_outer.")
    radius, inner, outer = map(float, radii)
    if inner - radius < 2:
        raise ValueError("The sky annulus must start at least 2 pixels beyond the aperture radius.")
    known_coverage = _map(coverage, pixels.shape, "coverage")
    if known_coverage is not None and not np.isin(known_coverage, [0, 1]).all():
        raise ValueError("coverage must be a known binary mask.")
    variance_map = _map(variance, pixels.shape, "variance")
    saturation_levels = _channel_parameter(saturation, channels, "saturation")
    gains = _channel_parameter(gain, channels, "gain")
    model = ("provided_total_diagonal_variance" if variance is not None else
             "sky_mad_plus_source_poisson" if gain is not None else "sky_mad_only_source_poisson_unknown")
    report = {
        "format": "ForgePixAperturePhotometry", "schema_version": 1,
        "method": "native_subpixel_aperture_robust_sky_plane_v1", "diagnostic_only": True,
        "image_modified": False, "color_calibration": False, "image_shape": list(original.shape),
        "channels": ["mono"] if channels == 1 else ["R", "G", "B"],
        "parameters": {"aperture_radius": radius, "annulus_inner": inner, "annulus_outer": outer,
                       "subpixels_per_axis": _SUBPIXELS, "blend_distance": 2 * radius,
                       "minimum_aperture_annulus_gap": 2.,
                       "neighbor_sky_mask_radius": radius + float(np.sqrt(.5)),
                       "minimum_sky_pixels": _MIN_SKY_PIXELS, "minimum_sky_area_fraction": _MIN_SKY_FRACTION,
                       "sky_clip_sigma": 4., "sky_clip_iterations": 6},
        "coverage_known": coverage is not None, "saturation_known": saturation is not None,
        "saturation": None if saturation_levels is None else saturation_levels.tolist(),
        "gain_electrons_per_image_unit": None if gains is None else gains.tolist(),
        "uncertainty": {"model": model, "complete": False, "pixel_covariance_available": False,
                        "channel_covariance_available": False, "robust_selection_conditioned_on_retained_pixels": True,
                        "source_poisson_included": variance is not None or gain is not None,
                        "provided_variance_is_assumed_total": variance is not None,
                        "gain_added_to_provided_variance": False},
        "assumptions": ["Original floating pixel scale; RGB channel order; zero-based pixel centers.",
                        "Common subpixel aperture and common retained sky samples across channels.",
                        "Sky is locally planar; neighbor masks and robust rejection do not remove arbitrary PSF wings.",
                        "Uncertainty assumes independent pixels; registration, drizzle and demosaic covariance are not supplied.",
                        "Sky-model, clipping-selection, centroid, saturation-threshold and aperture/PSF systematics are not quantified.",
                        "No aperture correction; net flux is an aperture measurement, not total stellar flux.",
                        "Eligibility is conditional measurement suitability, not permission for color calibration."],
        "stars": [],
    }
    finite_positions = np.flatnonzero(np.isfinite(positions).all(axis=1) &
        (positions[:, 0] >= -outer - radius - 2) & (positions[:, 0] <= width + outer + radius + 2) &
        (positions[:, 1] >= -outer - radius - 2) & (positions[:, 1] <= height + outer + radius + 2))
    tree = cKDTree(positions[finite_positions]) if len(finite_positions) else None
    for index, (x, y) in enumerate(positions):
        _cancel(cancel)
        reasons = []
        row = {"index": index, "source_id": identifiers[index],
               "position_xy": [float(value) if np.isfinite(value) else None for value in (x, y)],
               "measured": False, "fit_eligible": False, "exclusion_reasons": reasons,
               "flux": None, "raw_aperture_sum": None, "sky": None, "sky_gradient": None,
               "flux_uncertainty": None, "snr": None, "uncertainty_complete": False}
        report["stars"].append(row)
        if coverage is None:
            reasons.append("coverage_unknown")
        if saturation is None:
            reasons.append("saturation_unknown")
        if variance is None and gain is None:
            reasons.append("source_poisson_unknown")
        if not np.isfinite([x, y]).all() or not (-.5 <= x < width - .5 and -.5 <= y < height - .5):
            reasons.append("invalid_position")
            continue
        distances, nearest = tree.query([x, y], k=min(2, len(finite_positions)))
        nearest, distances = np.atleast_1d(nearest), np.atleast_1d(distances)
        other = finite_positions[nearest] != index
        if np.any(distances[other] <= 2 * radius):
            reasons.append("blend")
            row["nearest_blend_neighbor_index"] = int(finite_positions[nearest[other][0]])
            continue
        if x - outer < -.5 or y - outer < -.5 or x + outer > width - .5 or y + outer > height - .5:
            reasons.append("annulus_outside_image")
            continue
        neighbors = finite_positions[tree.query_ball_point([x, y], outer + radius + 2)]
        neighbors = neighbors[neighbors != index]
        x0, x1 = max(0, int(np.ceil(x - outer - .5))), min(width - 1, int(np.floor(x + outer + .5)))
        y0, y1 = max(0, int(np.ceil(y - outer - .5))), min(height - 1, int(np.floor(y + outer + .5)))
        gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        dx, dy = gx - x, gy - y
        aperture, inner_weights, outer_weights = _weights(dx, dy, (radius, inner, outer))
        annulus = outer_weights - inner_weights
        patch = pixels[y0:y1 + 1, x0:x1 + 1]
        active = aperture > 0
        valid = np.isfinite(patch).all(axis=2)
        covered = (np.ones(valid.shape, bool) if known_coverage is None else
                   np.all(known_coverage[y0:y1 + 1, x0:x1 + 1], axis=2))
        saturated = (np.zeros(valid.shape, bool) if saturation_levels is None else
                     np.any(patch >= saturation_levels, axis=2))
        row["aperture_area"] = float(aperture.sum())
        row["aperture_weight_square_sum"] = float(np.sum(aperture ** 2))
        if not valid[active].all():
            reasons.append("nonfinite_aperture")
        if not covered[active].all():
            reasons.append("incomplete_aperture_coverage")
        if saturated[active].any():
            reasons.append("saturated_aperture")
        patch_variance = None
        if variance_map is not None:
            patch_variance = np.asarray(variance_map[y0:y1 + 1, x0:x1 + 1], dtype=np.float64)
            good_variance = np.all(np.isfinite(patch_variance) & (patch_variance >= 0), axis=2)
            if not good_variance[active].all():
                reasons.append("invalid_aperture_variance")
            valid &= good_variance
        if any(reason in reasons for reason in ("nonfinite_aperture", "incomplete_aperture_coverage",
                                                "saturated_aperture", "invalid_aperture_variance")):
            continue
        neighbor_mask = np.zeros(valid.shape, dtype=bool)
        for nx, ny in positions[neighbors]:
            neighbor_mask |= (gx - nx) ** 2 + (gy - ny) ** 2 <= (radius + np.sqrt(.5)) ** 2
        sky_mask = (annulus > 0) & valid & covered & ~saturated & ~neighbor_mask
        row["neighbor_masked_sky_pixels"] = int(np.count_nonzero((annulus > 0) & neighbor_mask))
        design = np.stack((np.ones_like(dx), dx, dy), axis=-1)
        sky_design, sky_values, sky_weights = design[sky_mask], patch[sky_mask], annulus[sky_mask]
        sky_variance = patch_variance[sky_mask] if patch_variance is not None else None
        full_sky_area = float(annulus.sum())
        try:
            fitted = _sky_plane(sky_design, sky_values, sky_weights, sky_variance, full_sky_area, cancel)
            if fitted is None:
                reasons.append("insufficient_sky_support")
                continue
            beta, keep, scatter, clipping_status = fitted
            if clipping_status != "converged":
                reasons.append("sky_clipping_" + clipping_status)
            aperture_weights = aperture[active]
            integrated_design = aperture_weights @ design[active]
            raw_flux = aperture_weights @ patch[active]
            sky_flux = integrated_design @ beta
            flux = raw_flux - sky_flux
            retained_design, retained_weights = sky_design[keep], sky_weights[keep]
            # Linear sky-estimate kernel: beta = inv(A'WA) A'W sky_pixels.
            matrix = retained_design.T @ (retained_weights[:, None] * retained_design)
            sky_kernel = retained_weights * (retained_design @ np.linalg.solve(matrix, integrated_design))
            if variance_map is not None:
                aperture_variance = patch_variance[active]
                retained_variance = sky_variance[keep]
            else:
                aperture_variance = np.broadcast_to(scatter ** 2, patch[active].shape).copy()
                retained_variance = np.broadcast_to(scatter ** 2, sky_values[keep].shape)
                if gains is not None:
                    aperture_variance += np.maximum(patch[active] - design[active] @ beta, 0) / gains
            variance_aperture = (aperture_weights ** 2) @ aperture_variance
            variance_sky = (sky_kernel ** 2) @ retained_variance
            uncertainty = np.sqrt(variance_aperture + variance_sky)
            outputs = [beta, scatter, flux, raw_flux, sky_flux, uncertainty, variance_aperture, variance_sky]
            if not all(np.isfinite(item).all() for item in outputs):
                reasons.append("nonfinite_measurement")
                continue
        except np.linalg.LinAlgError:
            reasons.append("sky_fit_failed")
            continue
        snr = [float(f / error) if error > 0 and np.isfinite(f / error) else None
               for f, error in zip(flux, uncertainty)]
        if np.any(flux <= 0):
            reasons.append("nonpositive_flux")
        if any(value is None for value in snr):
            reasons.append("uncertainty_unavailable")
        row.update(measured=True, fit_eligible=not reasons, flux=flux.tolist(), raw_aperture_sum=raw_flux.tolist(),
                   sky=beta[0].tolist(), sky_gradient={"dx": beta[1].tolist(), "dy": beta[2].tolist()},
                   sky_aperture_sum=sky_flux.tolist(), sky_scatter=scatter.tolist(),
                   flux_uncertainty=uncertainty.tolist(), snr=snr,
                   variance_components={"aperture": variance_aperture.tolist(), "sky_plane": variance_sky.tolist()},
                   sky_pixels=int(keep.sum()), sky_effective_area=float(retained_weights.sum()),
                   sky_rejected_pixels=int((~keep).sum()), sky_clipping_status=clipping_status)
    counts = Counter(reason for row in report["stars"] for reason in row["exclusion_reasons"])
    report["summary"] = {"positions": len(positions), "measured": sum(row["measured"] for row in report["stars"]),
                         "fit_eligible": sum(row["fit_eligible"] for row in report["stars"]),
                         "exclusions": dict(sorted(counts.items()))}
    _cancel(cancel)
    return report
