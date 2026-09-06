"""Native aperture-based stellar white balance on linear BGR measurements.

This is a statistical white-reference assumption, not catalog PCC or SPCC.
Background-subtracted circular apertures follow the usual aperture/annulus
measurement (https://photutils.readthedocs.io/en/stable/user_guide/aperture.html).
The implementation is NumPy/OpenCV only and never clips scientific pixels.
"""
import cv2
import numpy as np

from constants import ForgePixFehler, log_print


def _image(image):
    a = np.asarray(image, dtype=np.float32)
    if a.ndim != 3 or a.shape[2] != 3 or not a.size or not np.isfinite(a).all():
        raise ForgePixFehler("Stern-Weißabgleich benötigt ein gültiges lineares RGB-Bild.")
    return a


def detect(image, max_stars=300):
    """Find isolated local maxima using float measurements, without 8-bit conversion."""
    a = _image(image)
    gray = a.mean(axis=2, dtype=np.float64).astype(np.float32)
    # Removing a smooth field here only locates stars; measurements use the original.
    residual = gray - cv2.GaussianBlur(gray, (0, 0), 8)
    med = float(np.median(residual))
    noise = float(np.median(np.abs(residual - med))) * 1.4826
    dynamic = float(np.max(residual) - med)
    if dynamic <= 0:
        return np.empty((0, 2), dtype=np.float64)
    threshold = med + max(6 * noise, dynamic * 1e-5)
    peaks = (residual > threshold) & (residual == cv2.dilate(residual, np.ones((5, 5), np.uint8)))
    ys, xs = np.nonzero(peaks)
    order = np.argsort(residual[ys, xs])[::-1]
    selected = []
    for index in order:
        x, y = int(xs[index]), int(ys[index])
        if not (15 <= x < a.shape[1] - 15 and 15 <= y < a.shape[0] - 15):
            continue
        if any((x - xx) ** 2 + (y - yy) ** 2 < 15 ** 2 for xx, yy in selected):
            continue
        local = np.maximum(residual[y - 3:y + 4, x - 3:x + 4] - med, 0).astype(np.float64)
        yy, xx = np.mgrid[-3:4, -3:4]
        total = float(local.sum())
        if total <= 0:
            continue
        cx, cy = float((local * xx).sum() / total), float((local * yy).sum() / total)
        variance = float((local * ((xx - cx) ** 2 + (yy - cy) ** 2)).sum() / total)
        if variance < .6:  # isolated defective pixels are not stellar color references
            continue
        selected.append((x + cx, y + cy))
        if len(selected) >= max_stars:
            break
    return np.asarray(selected, dtype=np.float64).reshape(-1, 2)


def measure(image, positions, saturation=None):
    """Circular radius-6 flux minus a robust local sky plane from radius 9..14.

    Pixel centers define the aperture. Positive flux in every channel is needed;
    S/N here is only a sky-scatter selection statistic (no camera noise model).
    Unknown detector saturation cannot be inferred reliably from scaled floats.
    """
    a = _image(image)
    points = np.asarray(positions, dtype=np.float64).reshape(-1, 2)
    if saturation is not None and (not np.isfinite(saturation) or saturation <= 0):
        raise ForgePixFehler("Die Sättigungsgrenze muss positiv und endlich sein.")
    rows = []
    rejected = {key: 0 for key in ("position", "crowded", "saturation", "signal", "profile")}
    h, w = a.shape[:2]
    for i, (x, y) in enumerate(points):
        if not np.isfinite([x, y]).all() or not (15 <= x < w - 15 and 15 <= y < h - 15):
            rejected["position"] += 1
            continue
        distance = np.sum((points - [x, y]) ** 2, axis=1)
        if np.any((distance < 15 ** 2) & (np.arange(len(points)) != i)):
            rejected["crowded"] += 1
            continue
        xi, yi = int(round(x)), int(round(y))
        if not (15 <= xi < w - 15 and 15 <= yi < h - 15):
            rejected["position"] += 1
            continue
        patch = a[yi - 15:yi + 16, xi - 15:xi + 16].astype(np.float64)
        gy, gx = np.mgrid[yi - 15:yi + 16, xi - 15:xi + 16]
        dx, dy = gx - x, gy - y
        radius2 = dx * dx + dy * dy
        aperture = radius2 <= 36
        annulus = (radius2 >= 81) & (radius2 <= 196)
        values = patch[aperture]
        if saturation is not None and np.any(values >= saturation):
            rejected["saturation"] += 1
            continue
        # A symmetric unsaturated PSF centered between pixels can have four
        # identical maxima. Require a larger plateau when saturation is unknown.
        peak = np.max(values, axis=0)
        plateau = np.sum(values == peak, axis=0)
        if np.any(plateau >= 9):
            rejected["saturation"] += 1
            continue
        design = np.stack([np.ones_like(dx), dx, dy], axis=-1)
        fit, sky = design[annulus], patch[annulus]
        keep = np.ones(len(sky), dtype=bool)
        for _ in range(3):
            coefficients = np.linalg.lstsq(fit[keep], sky[keep], rcond=None)[0]
            residual = sky - fit @ coefficients
            spread = 1.4826 * np.median(np.abs(residual[keep] - np.median(residual[keep], axis=0)), axis=0)
            floor = np.maximum(np.abs(sky).max(axis=0) * np.finfo(np.float32).eps * 4, 1e-35)
            new_keep = np.all(np.abs(residual) <= 3.5 * np.maximum(spread, floor), axis=1)
            if new_keep.sum() < len(sky) // 2 or np.array_equal(new_keep, keep):
                break
            keep = new_keep
        coefficients = np.linalg.lstsq(fit[keep], sky[keep], rcond=None)[0]
        residual = sky[keep] - fit[keep] @ coefficients
        spread = 1.4826 * np.median(np.abs(residual - np.median(residual, axis=0)), axis=0)
        sky_plane = design @ coefficients
        signal = patch - sky_plane
        flux = signal[aperture].sum(axis=0)
        uncertainty = np.maximum(spread, floor) * np.sqrt(aperture.sum() * (1 + aperture.sum() / keep.sum()))
        if np.any(flux <= 10 * uncertainty):
            rejected["signal"] += 1
            continue
        profile = np.maximum(signal.mean(axis=2), 0) * aperture
        total = profile.sum()
        variance = (profile * radius2).sum() / total if total > 0 else 0
        if not .6 <= variance <= 18:
            rejected["profile"] += 1
            continue
        rows.append({"x": float(x), "y": float(y), "flux_bgr": flux.tolist(),
                     "sky_bgr": coefficients[0].tolist(), "sky_snr_bgr": (flux / uncertainty).tolist()})
    return rows, rejected


def balance(image, strength=1.0, max_stars=300, *, positions=None, saturation=None,
            neutralize=True, log=log_print, return_info=False):
    """Fit robust per-star log color ratios; apply one affine transform per channel.

    Empty/unreliable fields stay unchanged. No quantile fallback impersonates a
    star measurement. Narrowband images must be excluded by the calling workflow.
    """
    src = _image(image)
    if not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ForgePixFehler("Die Stärke muss zwischen 0 und 1 liegen.")
    if isinstance(max_stars, bool) or int(max_stars) != max_stars or not 10 <= max_stars <= 2000:
        raise ForgePixFehler("Es werden 10 bis 2000 Referenzsterne unterstützt.")
    info = {"method": "native_stellar_white_balance", "catalog_calibration": False,
            "applied": False, "gains_bgr": [1., 1., 1.], "offsets_bgr": [0., 0., 0.],
            "strength": float(strength), "stars_detected": 0, "stars_used": 0,
            "saturation_known": saturation is not None,
            "assumption": "Median stellar color is neutral; no catalog colors or spectral response.",
            "aperture_radius_px": 6, "sky_annulus_px": [9, 14]}
    if strength == 0:
        info["reason"] = "disabled"
        return (src.copy(), info) if return_info else src.copy()
    points = detect(src, max_stars) if positions is None else np.asarray(positions, dtype=np.float64)
    rows, rejected = measure(src, points, saturation=saturation)
    info.update(stars_detected=int(len(points)), stars_measured=len(rows), rejected=rejected)
    if len(rows) < 10:
        info["reason"] = "insufficient_stellar_references"
    else:
        flux = np.asarray([row["flux_bgr"] for row in rows])
        ratios = np.log(flux / flux[:, 1:2])[:, [0, 2]]
        median = np.median(ratios, axis=0)
        spread = 1.4826 * np.median(np.abs(ratios - median), axis=0)
        keep = np.all(np.abs(ratios - median) <= np.maximum(3.5 * spread, .04), axis=1)
        info["rejected"]["color_outlier"] = int((~keep).sum())
        info["stars_used"] = int(keep.sum())
        if keep.sum() < 10:
            info["reason"] = "insufficient_consistent_colors"
        else:
            color = np.exp(np.median(ratios[keep], axis=0))
            gains = np.array([1 / color[0], 1., 1 / color[1]])
            info["measured_gains_bgr"] = gains.tolist()
            if np.any((gains < .25) | (gains > 4)):
                info["reason"] = "color_gains_out_of_range"
            else:
                sky = np.median(np.asarray([row["sky_bgr"] for row in rows])[keep], axis=0)
                offsets = np.full(3, float(np.min(sky * gains))) - sky * gains if neutralize else np.zeros(3)
                gains = 1 + strength * (gains - 1)
                offsets *= strength
                info.update(applied=True, reason="measured", gains_bgr=gains.tolist(),
                            offsets_bgr=offsets.tolist(), sky_bgr=sky.tolist())
    if info["applied"]:
        with np.errstate(over="ignore", invalid="ignore"):
            out = (src.astype(np.float64) * np.asarray(info["gains_bgr"]) + info["offsets_bgr"]).astype(np.float32)
        if not np.isfinite(out).all():
            raise ForgePixFehler("Der Weißabgleich überschreitet den Float32-Wertebereich.")
        log("  Nativer Stern-Weißabgleich: %d Referenzen, BGR-Faktoren %s. Keine Katalog-Farbkalibrierung."
            % (info["stars_used"], np.round(info["gains_bgr"], 3)))
    else:
        out = src.copy()
        log("  Stern-Weißabgleich unverändert: keine ausreichend verlässlichen Sternfarben (%s)."
            % info["reason"])
    return (out, info) if return_info else out
