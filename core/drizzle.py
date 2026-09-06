"""Native square-drop reconstruction with exact affine pixel-area overlaps.

Fruchter & Hook (2002), https://arxiv.org/abs/astro-ph/9808087;
https://hst-docs.stsci.edu/drizzpac/chapter-3-description-of-the-drizzle-algorithm/3-3-weight-maps-and-correlated-noise

Coordinates address pixel centres. Values represent brightness per reference
pixel area, not counts per smaller output pixel: aperture sums need / scale**2.
The affine Jacobian converts input pixel counts to that reference area. Weights
are sums of fractional drop overlaps, not independent-sample or exposure counts.
Uncovered samples stay zero and MUST be interpreted using the returned weights.
"""
import math

import numpy as np
from scipy.sparse import coo_matrix

from constants import ForgePixFehler


def _cancelled(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()):
        raise ForgePixFehler("Drizzle-Verarbeitung abgebrochen.")


def _number(value, name, low, high):
    if isinstance(value, (bool, str)):
        raise ForgePixFehler("Drizzle: %s muss zwischen %s und %s liegen." % (name, low, high))
    try:
        value = float(value)
    except (ValueError, TypeError) as exc:
        raise ForgePixFehler("Drizzle: ungültiger Parameter %s." % name) from exc
    if not np.isfinite(value) or not low <= value <= high:
        raise ForgePixFehler("Drizzle: %s muss zwischen %s und %s liegen." % (name, low, high))
    return value


def _overlap_axis(size, output_size, slope, offset, pixfrac):
    """Sparse exact one-dimensional fractional overlaps for axis-aligned drops."""
    centres = slope * np.arange(size, dtype=np.float64) + offset
    width = abs(slope) * pixfrac
    left, right = centres - width / 2, centres + width / 2
    first = np.floor(left + .5).astype(np.int64)
    rows, cols, values = [], [], []
    for step in range(int(math.ceil(width)) + 1):
        row = first + step
        overlap = np.maximum(0, np.minimum(right, row + .5) - np.maximum(left, row - .5)) / width
        valid = (row >= 0) & (row < output_size) & (overlap > 0)
        rows.append(row[valid])
        cols.append(np.flatnonzero(valid))
        values.append(overlap[valid])
    return coo_matrix((np.concatenate(values), (np.concatenate(rows), np.concatenate(cols))),
                      shape=(output_size, size)).tocsr()


def _intersection_area(vertices):
    """Vectorised convex-polygon clipping to [0,1]²; at most eight vertices."""
    n = len(vertices)
    # Boundary-coincident vertices may appear twice while clipping. Keep spare
    # slots for those duplicates; the area formula handles them exactly.
    polygon = np.zeros((n, 16, 2), np.float64)
    polygon[:, :4] = vertices
    counts = np.full(n, 4, np.int64)
    columns = np.arange(16)[None, :]
    rows = np.arange(n)[:, None]
    for axis, bound, sign in ((0, 0., 1.), (0, 1., -1.), (1, 0., 1.), (1, 1., -1.)):
        active = columns < counts[:, None]
        previous = polygon[rows, (columns - 1) % np.maximum(counts[:, None], 1)]
        inside = (sign * (polygon[..., axis] - bound) >= 0) & active
        was_inside = sign * (previous[..., axis] - bound) >= 0
        crossing = (inside != was_inside) & active
        positions = np.cumsum(crossing.astype(np.int64) + inside, axis=1)
        new = np.zeros_like(polygon)
        r, c = np.nonzero(crossing)
        if len(r):
            start, end = previous[r, c], polygon[r, c]
            ratio = (bound - start[:, axis]) / (end[:, axis] - start[:, axis])
            point = start + ratio[:, None] * (end - start)
            new[r, positions[r, c] - inside[r, c] - 1] = point
        r, c = np.nonzero(inside)
        new[r, positions[r, c] - 1] = polygon[r, c]
        polygon, counts = new, positions[:, -1]
    active = columns < counts[:, None]
    local = polygon - polygon[:, :1]
    following = local[rows, (columns + 1) % np.maximum(counts[:, None], 1)]
    cross = local[..., 0] * following[..., 1] - local[..., 1] * following[..., 0]
    return np.abs(np.sum(np.where(active, cross, 0), axis=1)) / 2


class DrizzleAccumulator:
    """Streaming reconstruction; retain Float64 sums until the final division."""

    def __init__(self, shape, *, scale=2, pixfrac=.7, channels=3, cancel=None):
        _cancelled(cancel)
        try:
            shape = tuple(shape)
            valid_shape = (len(shape) == 2 and all(not isinstance(n, bool) and np.isfinite(n)
                                                  and int(n) == n and n > 0 for n in shape))
        except (TypeError, ValueError, OverflowError):
            valid_shape = False
        if not valid_shape or isinstance(channels, bool) or channels not in (1, 3):
            raise ForgePixFehler("Drizzle: ungültige Bildform oder Kanalzahl.")
        self.shape = tuple(map(int, shape))
        self.scale = _number(scale, "Scale", 1, 4)
        self.pixfrac = _number(pixfrac, "Pixfrac", np.finfo(np.float32).eps, 1)
        self.output_shape = tuple(int(math.ceil(n * self.scale)) for n in self.shape)
        self.channels = channels
        self.cancel, self._invalid = cancel, False
        try:
            _cancelled(cancel)
            self.flux = np.zeros((*self.output_shape, channels), np.float64)
            _cancelled(cancel)
            self.weights = np.zeros_like(self.flux)
        except (MemoryError, ValueError) as exc:
            raise ForgePixFehler("Drizzle: zu wenig Speicher für dieses Ausgaberaster.") from exc
        self.frames = 0

    def add(self, image, transform, *, weight=1., channel_map=None):
        if self._invalid:
            raise ForgePixFehler("Drizzle: ein abgebrochener oder fehlgeschlagener Akkumulator darf nicht weiterverwendet werden.")
        try:
            _cancelled(self.cancel)
            return self._add(image, transform, weight=weight, channel_map=channel_map)
        except Exception:
            # A frame may already have written some drops. Do not let callers
            # export that partial integration or continue it as a complete frame.
            self._invalid = True
            raise

    def _add(self, image, transform, *, weight=1., channel_map=None):
        image = np.asarray(image)
        if (image.shape not in (self.shape, (*self.shape, self.channels))
                or not np.issubdtype(image.dtype, np.number) or np.iscomplexobj(image)):
            raise ForgePixFehler("Drizzle: Aufnahme passt nicht zur Bildform/Kanalzahl.")
        if image.ndim == 2 and self.channels != 1 and channel_map is None:
            raise ForgePixFehler("Drizzle: ein CFA-Sensorbild benötigt eine explizite Farbzuordnung.")
        if channel_map is not None:
            channel_map = np.asarray(channel_map)
            if (image.ndim != 2 or self.channels != 3 or channel_map.shape != self.shape
                    or not np.isin(channel_map, (0, 1, 2)).all()):
                raise ForgePixFehler("Drizzle: ungültige CFA-Farbzuordnung.")
            channel_map = channel_map.astype(np.intp, copy=False)
        try:
            matrix = np.asarray(transform)
            if np.iscomplexobj(matrix):
                raise ValueError("komplexe Koordinaten sind nicht unterstützt")
            matrix = matrix.astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise ForgePixFehler("Drizzle: ungültige affine Transformation.") from exc
        if matrix.shape != (2, 3) or not np.isfinite(matrix).all():
            raise ForgePixFehler("Drizzle: Transformation muss eine endliche 2×3-Matrix sein.")
        singular = np.linalg.svd(matrix[:, :2], compute_uv=False)
        if singular.min() < .25 or singular.max() > 4:
            raise ForgePixFehler("Drizzle: singuläre oder unplausibel skalierte Transformation.")
        jacobian = abs(float(np.linalg.det(matrix[:, :2])))
        try:
            weight = np.asarray(weight)
            if np.iscomplexobj(weight):
                raise ValueError("komplexe Gewichte sind nicht unterstützt")
            weight = weight.astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise ForgePixFehler("Drizzle: Gewichte müssen reelle Zahlen sein.") from exc
        if weight.ndim == 0:
            weight = np.full(self.shape, weight, np.float64)
        if weight.shape != self.shape or not np.isfinite(weight).all() or np.any(weight < 0):
            raise ForgePixFehler("Drizzle: Gewichte müssen endlich, nichtnegativ und passend geformt sein.")
        valid = weight > 0
        if not valid.any():
            return False
        if not np.isfinite(image[valid]).all():
            raise ForgePixFehler("Drizzle: ein gültiger Eingabepixel enthält NaN oder Inf.")
        data = np.where(valid[..., None] if image.ndim == 3 else valid, image, 0).astype(np.float64)
        # Pixel centres map x -> scale*(M*x + 0.5) - 0.5, including at identity.
        with np.errstate(over="ignore", invalid="ignore"):
            scaled = matrix * self.scale
        scaled[:, 2] += (self.scale - 1) / 2
        if not np.isfinite(scaled).all():
            raise ForgePixFehler("Drizzle: Transformation überschreitet den Zahlenbereich.")
        half = self.pixfrac / 2
        bounds = np.array([[-half, -half], [self.shape[1] - 1 + half, -half],
                           [self.shape[1] - 1 + half, self.shape[0] - 1 + half],
                           [-half, self.shape[0] - 1 + half]]) @ scaled[:, :2].T + scaled[:, 2]
        if (np.any(bounds.max(axis=0) <= -.5)
                or np.any(bounds.min(axis=0) >= np.array(self.output_shape[::-1]) - .5)):
            return False
        if abs(scaled[0, 1]) < 1e-14 and abs(scaled[1, 0]) < 1e-14:
            wx = _overlap_axis(self.shape[1], self.output_shape[1], scaled[0, 0], scaled[0, 2], self.pixfrac)
            wy = _overlap_axis(self.shape[0], self.output_shape[0], scaled[1, 1], scaled[1, 2], self.pixfrac)
            added = False
            for channel in range(self.channels):
                _cancelled(self.cancel)
                channel_weight = weight if channel_map is None else weight * (channel_map == channel)
                plane = data[..., channel] if data.ndim == 3 else data
                projected_weight = (wx @ (wy @ channel_weight).T).T
                added = added or bool(np.any(projected_weight > 0))
                self.weights[..., channel] += projected_weight
                self.flux[..., channel] += (wx @ (wy @ (plane * channel_weight / jacobian)).T).T
        else:
            added = self._add_affine(data, weight, channel_map, scaled, jacobian)
        self.frames += int(added)
        return added

    def _add_affine(self, data, weight, channel_map, matrix, jacobian):
        half = self.pixfrac / 2
        corners = np.array([[-half, -half], [half, -half], [half, half], [-half, half]]) @ matrix[:, :2].T
        area = jacobian * (self.scale * self.pixfrac) ** 2
        span = np.ceil(np.ptp(corners, axis=0)).astype(int) + 1
        flat = np.flatnonzero(weight.ravel() > 0)
        oh, ow = self.output_shape
        flux, weights = self.flux.reshape(-1, self.channels), self.weights.reshape(-1, self.channels)
        added = False
        for start in range(0, len(flat), 4096):
            _cancelled(self.cancel)
            index = flat[start:start + 4096]
            x, y = index % self.shape[1], index // self.shape[1]
            centres = np.column_stack((x, y)) @ matrix[:, :2].T + matrix[:, 2]
            vertices = centres[:, None, :] + corners
            origin = np.floor(vertices.min(axis=1) + .5).astype(np.int64)
            values = data.reshape(-1, data.shape[-1])[index] if data.ndim == 3 else data.ravel()[index, None]
            iw = weight.ravel()[index]
            colours = channel_map.ravel()[index] if channel_map is not None else None
            for dy in range(span[1]):
                for dx in range(span[0]):
                    target = origin + (dx, dy)
                    keep = ((target[:, 0] >= 0) & (target[:, 0] < ow)
                            & (target[:, 1] >= 0) & (target[:, 1] < oh))
                    if not keep.any():
                        continue
                    subset = np.flatnonzero(keep)
                    local = (centres[keep] - target[keep] + .5)[:, None, :] + corners
                    fraction = _intersection_area(local) / area
                    positive = fraction > 0
                    subset, fraction = subset[positive], fraction[positive]
                    added = added or bool(len(subset))
                    dst = target[subset, 1] * ow + target[subset, 0]
                    contribution = fraction * iw[subset]
                    if colours is not None:
                        np.add.at(weights, (dst, colours[subset]), contribution)
                        np.add.at(flux, (dst, colours[subset]), values[subset, 0] * contribution / jacobian)
                    else:
                        for channel in range(self.channels):
                            np.add.at(weights[:, channel], dst, contribution)
                            np.add.at(flux[:, channel], dst, values[subset, channel] * contribution / jacobian)
        return added

    def finish(self):
        _cancelled(self.cancel)
        if self._invalid:
            raise ForgePixFehler("Drizzle: unvollständige Beiträge eines fehlgeschlagenen Frames werden nicht exportiert.")
        valid = self.weights > 0
        if not valid.any():
            raise ForgePixFehler("Drizzle: keine gültigen Beiträge innerhalb des Ausgaberaster.")
        with np.errstate(over="ignore", invalid="ignore"):
            image = np.divide(self.flux, self.weights, out=np.zeros_like(self.flux), where=valid).astype(np.float32)
            _cancelled(self.cancel)
            weights = self.weights.astype(np.float32)
        if not np.isfinite(image).all() or not np.isfinite(weights).all():
            raise ForgePixFehler("Drizzle: Ergebnis überschreitet den Float32-Bereich.")
        if np.any(valid & (weights == 0)):
            raise ForgePixFehler("Drizzle: positive Gewichte unterschreiten den Float32-Bereich.")
        if self.channels == 1:
            image, weights, valid = image[..., 0], weights[..., 0], valid[..., 0]
        return image, weights, valid
