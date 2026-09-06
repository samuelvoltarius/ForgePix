#!/usr/bin/env python3
"""
wavelet.py — à-trous (stationäre) Wavelet-Zerlegung + RegiStax-artige Multi-Skalen-Schärfung.

Statt eines einzelnen Unsharp-Masks (eine Skala, Halo-anfällig) zerlegt die à-trous-Transformation
das Bild in mehrere **Frequenzbänder** (fein → grob) und erlaubt, jedes **einzeln** zu verstärken
und zu entrauschen — wie die RegiStax-Wavelet-Regler. Halo-arm und rausch-kontrollierbar.

à trous: rekursiv mit einem B3-Spline-Kern [1,4,6,4,1]/16 tiefpassfiltern, den Kern je Ebene
**dilatieren** (Löcher einfügen) → keine Verkleinerung, Bild bleibt voll aufgelöst.
Detail-Ebene i = approx[i-1] − approx[i]. Rekonstruktion = Σ gain_i · detail_i + Rest-Approx.

Geteilt von: Lucky-Imaging (Final-Schärfung), Astro (Detail), RAW-Editor (Capture-Schärfung).
Reine OpenCV/NumPy-Abhängigkeiten (MIT-kompatibel).

Floating-Bilder behalten Vorzeichen und Dynamikumfang. Die Operatoren ändern
bei nichtneutralen Einstellungen Messwerte; Flusserhaltung ist nicht garantiert.
"""
import numpy as np
import cv2

_B3 = np.array([1, 4, 6, 4, 1], np.float32) / 16.0


def _image(value, color=False):
    image = np.asarray(value)
    valid_shape = image.ndim == 2 or (color and image.ndim == 3 and image.shape[2] == 3)
    if not valid_shape or image.size == 0:
        raise ValueError("Wavelets benötigen ein nichtleeres Graubild oder ein BGR-Bild mit drei Kanälen.")
    if image.dtype.kind not in "fiu" or not np.isfinite(image).all():
        raise ValueError("Wavelets benötigen reelle, endliche Pixelwerte.")
    return image


def _levels(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 0:
        raise ValueError("Die Anzahl der Wavelet-Ebenen muss eine nichtnegative ganze Zahl sein.")
    return int(value)


def _finite(value):
    if not np.isfinite(value).all():
        raise ValueError("Die Wavelet-Berechnung überschreitet den darstellbaren Wertebereich.")
    return value


def _dilated_kernel(level):
    """B3-Spline-Kern mit 2^level-1 Nullen zwischen den Taps (à-trous-„Löcher")."""
    step = 1 << level
    k = np.zeros(4 * step + 1, np.float32)
    k[::step] = _B3
    return k


def atrous(gray, levels=5):
    """à-trous-Zerlegung: Float64 bleibt Float64, sonst wird Float32 verwendet.

    Gibt (Detail-Ebenen fein bis grob, Rest) zurück, ohne Eingabewerte zu ändern.
    Null Ebenen liefert eine unabhängige Kopie als Rest.
    """
    gray = _image(gray)
    levels = _levels(levels)
    work_dtype = np.float64 if gray.dtype.kind == "f" and gray.dtype.itemsize > 4 else np.float32
    approx = _finite(gray.astype(work_dtype))
    depth = cv2.CV_64F if work_dtype == np.float64 else cv2.CV_32F
    details = []
    for i in range(levels):
        k = _dilated_kernel(i)
        sm = _finite(cv2.sepFilter2D(approx, depth, k, k, borderType=cv2.BORDER_REFLECT))
        with np.errstate(over="ignore", invalid="ignore"):
            detail = approx - sm
        details.append(_finite(detail))
        approx = sm
    return details, approx


def wavelet_sharpen(img, gains=(2.0, 1.6, 1.3, 1.1, 1.0), denoise=0.0, levels=None):
    """Multi-Skalen-Schärfung (RegiStax-Stil). gains[i] = Verstärkung der i-ten Detail-Ebene
    (Index 0 = feinste). denoise>0 = Soft-Threshold auf den feinen Ebenen (gegen Rausch-Verstärkung).
    Wirkt auf die BGR-Luminanz und addiert das Delta auf alle Farbkanäle.
    Floating-Ausgaben bleiben signiert/unbeschränkt, Float64 bleibt Float64.
    Ganzzahlen behalten den bisherigen Bereich (uint16: 0..65535, sonst 0..255).
    Ein neutraler Floating-Durchlauf liefert eine exakte, unabhängige Kopie.
    """
    img = _image(img, color=True)
    dtype = img.dtype
    floating = dtype.kind == "f"
    raw_gains = np.asarray(gains)
    if raw_gains.ndim != 1 or not raw_gains.size or raw_gains.dtype.kind not in "fiu":
        raise ValueError("Wavelet-Verstärkungen müssen eine nichtleere Folge reeller Zahlen sein.")
    gains = raw_gains.astype(np.float64)
    if not np.isfinite(gains).all():
        raise ValueError("Wavelet-Verstärkungen müssen endlich sein.")
    if not np.isscalar(denoise) or np.asarray(denoise).dtype.kind not in "fiu":
        raise ValueError("Die Entrauschungsstärke muss eine endliche nichtnegative Zahl sein.")
    denoise = float(denoise)
    if not np.isfinite(denoise) or denoise < 0:
        raise ValueError("Die Entrauschungsstärke muss eine endliche nichtnegative Zahl sein.")
    levels = len(gains) if levels is None else _levels(levels)
    levels = levels or len(gains)  # Preserve the photographic API's zero=automatic convention.
    if floating and denoise == 0 and np.all(gains[:levels] == 1):
        return img.copy()
    maxv = 65535.0 if dtype == np.uint16 else 255.0
    color = img.ndim == 3
    work_dtype = np.float64 if floating and dtype.itemsize > 4 else np.float32
    f = _finite(img.astype(work_dtype))
    # Luminanz schärfen, das DELTA auf alle Kanäle addieren → farbtreu, kein cvtColor-Konventions-Trap
    y = (0.114 * f[..., 0] + 0.587 * f[..., 1] + 0.299 * f[..., 2]) if color else f
    details, approx = atrous(y, levels)
    out = approx.copy()
    for i, d in enumerate(details):
        g = float(gains[i]) if i < len(gains) else 1.0
        if denoise > 0:                                     # feine Ebenen stärker entrauschen
            with np.errstate(over="ignore", invalid="ignore"):
                sigma = np.std(d, dtype=np.float64) if floating else np.std(d)
                t = denoise * float(sigma) * (0.6 ** i)
                d = np.sign(d) * np.maximum(np.abs(d) - t, 0.0)
            if not np.isfinite(t):
                raise ValueError("Die Wavelet-Entrauschungsstärke überschreitet den Wertebereich.")
        with np.errstate(over="ignore", invalid="ignore"):
            out = _finite(out + g * d)
    if color:
        with np.errstate(over="ignore", invalid="ignore"):
            delta = (out - y)[..., None]
            out = _finite(f + delta)
    if not floating:
        return np.clip(out, 0, maxv).astype(dtype)
    with np.errstate(over="ignore", invalid="ignore"):
        return _finite(out.astype(dtype))


def wavelet_denoise(img, strength=1.0, levels=4):
    """Reines Multi-Skalen-Entrauschen (Soft-Threshold je Ebene, BayesShrink-artig) — feine Ebenen
    stärker. Geteilt mit dem RAW-Editor. Gibt Eingabe-dtype zurück."""
    levels = _levels(levels)
    if levels == 0:
        raise ValueError("Entrauschen benötigt mindestens eine Wavelet-Ebene.")
    return wavelet_sharpen(img, gains=tuple([1.0] * levels), denoise=strength, levels=levels)
