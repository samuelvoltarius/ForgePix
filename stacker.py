#!/usr/bin/env python3
"""
stacker.py — eigene Fokus-Stacking-Engine (OpenCV/NumPy), unabhängig von ShineStacker.

- align_images(): Frames per Feature-Matching (ORB/SIFT) auf ein Referenzbild ausrichten.
- focus_stack(): Verschmelzung per Laplace-Pyramide (schärfster Koeffizient je Bildpunkt).

Arbeitet intern in float32, erhält 8- oder 16-bit. Farb-Reihenfolge BGR (OpenCV).
Reine MIT-kompatible Abhängigkeiten (OpenCV, NumPy) — frei verwend-/verschenkbar.
"""
import numpy as np
import cv2


def _to_gray8(img):
    """8-bit-Graustufen fürs Feature-Matching (auch aus 16-bit)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if g.dtype == np.uint16:
        g = (g / 256).astype(np.uint8)
    elif g.dtype != np.uint8:
        g = np.clip(g, 0, 255).astype(np.uint8)
    return g


def align_images(images, ref_idx=None, mode="rigid", detector="ORB", log=print):
    """Richtet alle Bilder auf das Referenzbild aus. Gibt ausgerichtete Liste zurück.
    mode: 'rigid' (Verschiebung/Drehung/Skalierung) oder 'homography' (Perspektive)."""
    n = len(images)
    if n < 2:
        return images
    if ref_idx is None:
        ref_idx = n // 2  # mittleres Bild als Referenz (meist gut fokussiert)
    if detector == "SIFT":
        det = cv2.SIFT_create()
        matcher = cv2.BFMatcher(cv2.NORM_L2)
    elif detector == "AKAZE":
        det = cv2.AKAZE_create()
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    else:
        det = cv2.ORB_create(5000)
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    ref_gray = _to_gray8(images[ref_idx])
    kp_ref, des_ref = det.detectAndCompute(ref_gray, None)
    out = [None] * n
    out[ref_idx] = images[ref_idx]
    h, w = images[ref_idx].shape[:2]

    for i in range(n):
        if i == ref_idx:
            continue
        img = images[i]
        kp, des = det.detectAndCompute(_to_gray8(img), None)
        if des is None or des_ref is None or len(kp) < 4:
            log(f"    Frame {i + 1}: zu wenige Merkmale — unverändert übernommen")
            out[i] = img
            continue
        matches = matcher.knnMatch(des, des_ref, k=2)
        good = [m for pair in matches if len(pair) == 2
                for m, nmatch in [pair] if m.distance < 0.75 * nmatch.distance]
        if len(good) < 8:
            log(f"    Frame {i + 1}: nur {len(good)} Treffer — unverändert übernommen")
            out[i] = img
            continue
        src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp_ref[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        if mode == "homography":
            M, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
            out[i] = cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_LANCZOS4,
                                         borderMode=cv2.BORDER_REPLICATE) if M is not None else img
        else:
            M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                               ransacReprojThreshold=3.0)
            out[i] = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LANCZOS4,
                                    borderMode=cv2.BORDER_REPLICATE) if M is not None else img
        log(f"    Frame {i + 1}/{n}: ausgerichtet ({len(good)} Treffer)")
    return out


def _gaussian_pyramid(img, levels):
    pyr = [img]
    for _ in range(levels):
        img = cv2.pyrDown(img)
        pyr.append(img)
    return pyr


def _laplacian_pyramid(gauss):
    lap = []
    for i in range(len(gauss) - 1):
        size = (gauss[i].shape[1], gauss[i].shape[0])
        up = cv2.pyrUp(gauss[i + 1], dstsize=size)
        lap.append(gauss[i] - up)
    lap.append(gauss[-1])
    return lap


def disagreement_map(images, max_side=700):
    """Pro-Pixel-Streuung der (ausgerichteten) Frames in Graustufen, normiert [0..1].
    Hoch = Frames widersprechen sich = Kandidat für Bewegung/Ghosting."""
    small = []
    for im in images:
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
        if g.dtype != np.uint8:
            g = (g / 256).astype(np.uint8) if g.max() > 255 else g.astype(np.uint8)
        s = max_side / max(g.shape)
        if s < 1.0:
            g = cv2.resize(g, (int(g.shape[1] * s), int(g.shape[0] * s)), interpolation=cv2.INTER_AREA)
        small.append(g.astype(np.float32))
    std = np.stack(small).std(axis=0)
    std = cv2.GaussianBlur(std, (0, 0), 3)
    return std / (std.max() + 1e-6)


def ghost_overlay(result_bgr, images, thresh=0.35):
    """Rote Überlagerung auf dem Ergebnis, wo die Frames stark uneinig sind (Ghosting-Verdacht)."""
    m = disagreement_map(images)
    m = cv2.resize(m, (result_bgr.shape[1], result_bgr.shape[0]))
    base = (result_bgr / 256).astype(np.uint8) if result_bgr.dtype == np.uint16 else result_bgr.copy()
    a = (np.clip((m - thresh) / max(1e-6, 1 - thresh), 0, 1) * 0.6)[..., None]
    red = np.zeros_like(base); red[..., 2] = 255
    return (base * (1 - a) + red * a).astype(np.uint8)


def focus_stack(images, min_size=32, deghost=False, deghost_thresh=0.35, log=print):
    """Laplace-Pyramiden-Fusion: pro Pyramidenebene den schärfsten (energiereichsten)
    Koeffizienten je Bildpunkt wählen. Gibt das verschmolzene Bild im Eingabe-dtype zurück."""
    if not images:
        raise ValueError("keine Bilder")
    dtype = images[0].dtype
    maxval = 65535.0 if dtype == np.uint16 else 255.0
    # Graustufen → 3-Kanal, damit die Pyramiden-Fusion (erwartet HxWx3) robust läuft
    images = [im if im.ndim == 3 else cv2.cvtColor(im, cv2.COLOR_GRAY2BGR) for im in images]
    fl = [im.astype(np.float32) for im in images]
    h, w = fl[0].shape[:2]
    levels = max(1, int(np.log2(min(h, w) / min_size)))
    log(f"    Pyramide: {len(fl)} Frames, {levels} Ebenen")

    laps = [_laplacian_pyramid(_gaussian_pyramid(im, levels)) for im in fl]
    fused = []
    for l in range(levels + 1):
        layers = np.stack([lp[l] for lp in laps])  # (N,h,w,3)
        if l == levels:
            fused.append(layers.mean(axis=0))  # Basis: tonaler Mittelwert
        else:
            # Energie = geglättete |Laplace|-Summe über Kanäle, schärfster gewinnt
            energy = np.abs(layers).sum(axis=3)  # (N,h,w)
            energy = np.stack([cv2.GaussianBlur(e, (5, 5), 0) for e in energy])
            idx = energy.argmax(axis=0)  # (h,w)
            sel = np.take_along_axis(layers, idx[None, :, :, None], axis=0)[0]
            fused.append(sel)
        log(f"    Ebene {levels - l + 1}/{levels + 1} verschmolzen")

    img = fused[-1]
    for l in range(levels - 1, -1, -1):
        size = (fused[l].shape[1], fused[l].shape[0])
        img = cv2.pyrUp(img, dstsize=size) + fused[l]
    img = np.clip(img, 0, maxval)

    if deghost and len(fl) >= 3:
        # In Zonen, wo die Frames stark uneinig sind (Bewegung), Median statt Mischung
        # -> unterdrückt durchziehende/bewegte Objekte (Doppelkonturen).
        log("    Deghost: Median in Bewegungszonen")
        med = np.median(np.stack(fl), axis=0)
        m = disagreement_map(images)
        m = cv2.resize(m, (img.shape[1], img.shape[0]))
        mask = np.clip((m - deghost_thresh) / max(1e-6, 1 - deghost_thresh), 0, 1)[..., None]
        img = img * (1 - mask) + med * mask
    return np.clip(img, 0, maxval).astype(dtype)


def focus_stack_streamed(paths, align_mode="rigid", detector="ORB", chunk=8,
                         do_align=True, log=print):
    """Speicherschonendes Stacken: liest Frames in Bündeln von `chunk` von der Platte,
    richtet sie aufs (globale) Referenzbild aus, verschmilzt je Bündel, dann die
    Zwischenergebnisse. RAM ~ max(chunk, Anzahl Bündel) Frames statt alle gleichzeitig."""
    ref = cv2.imread(paths[len(paths) // 2], cv2.IMREAD_UNCHANGED)
    inters = []
    n = len(paths)
    for i in range(0, n, chunk):
        grp = [cv2.imread(p, cv2.IMREAD_UNCHANGED) for p in paths[i:i + chunk]]
        grp = [g for g in grp if g is not None]
        if not grp:
            continue
        grp = [cv2.resize(g, (ref.shape[1], ref.shape[0])) if g.shape[:2] != ref.shape[:2] else g
               for g in grp]
        if do_align:
            grp = align_images([ref] + grp, ref_idx=0, mode=align_mode,
                               detector=detector, log=lambda *a: None)[1:]
        inters.append(focus_stack(grp, log=lambda *a: None))
        log(f"    Bündel {i // chunk + 1}/{(n + chunk - 1) // chunk} verschmolzen "
            f"({len(grp)} Frames)")
    if len(inters) == 1:
        return inters[0]
    log("    Bündel zusammenführen …")
    return focus_stack(inters, log=lambda *a: None)


def unsharp_mask(img, amount_percent=0.0, radius=1.0):
    """Klassisches Nachschärfen (Unsharp Mask). amount in %, 0 = aus."""
    if amount_percent <= 0:
        return img
    a = amount_percent / 100.0
    f = img.astype(np.float32)
    blur = cv2.GaussianBlur(f, (0, 0), max(0.1, radius))
    out = f + a * (f - blur)
    maxval = 65535.0 if img.dtype == np.uint16 else 255.0
    return np.clip(out, 0, maxval).astype(img.dtype)


def local_contrast(img, amount_percent=0.0):
    """Klarheit / Mikrokontrast = Unsharp Mask mit großem Radius (treu, kein Erfinden)."""
    if amount_percent <= 0:
        return img
    r = max(3.0, min(img.shape[0], img.shape[1]) / 120.0)
    return unsharp_mask(img, amount_percent, r)


def write_layered_tiff(out_path, named_layers, flat_bgr=None):
    """Schreibt eine Photoshop-kompatible Ebenen-TIFF (öffnet in PS/GIMP/Affinity mit Layern).
    named_layers: Liste (Name, BGR-Bild) — das ERSTE wird die oberste Ebene.
    Eigenständig via psdtags (keine ShineStacker-Abhängigkeit)."""
    import tifffile
    import imagecodecs
    from psdtags import (TiffImageSourceData, PsdLayer, PsdLayers, PsdChannel, PsdChannelId,
                         PsdFormat, PsdKey, PsdRectangle, PsdUserMask, PsdBlendMode,
                         PsdClippingType, PsdLayerFlag, PsdLayerMask, PsdCompressionType,
                         PsdColorSpaceType, PsdEmpty, PsdFilterMask, PsdString)
    imgs = [(n, cv2.cvtColor(b, cv2.COLOR_BGR2RGB)) for n, b in named_layers]
    h, w = imgs[0][1].shape[:2]
    dtype = imgs[0][1].dtype
    maxv = 65535 if dtype == np.uint16 else 255
    transp = np.full((h, w), maxv, dtype=dtype)
    comp = PsdCompressionType.ZIP_PREDICTED
    key = PsdKey.LAYER_16 if dtype == np.uint16 else PsdKey.LAYER
    layers = [PsdLayer(
        name=name, rectangle=PsdRectangle(0, 0, h, w),
        channels=[
            PsdChannel(channelid=PsdChannelId.TRANSPARENCY_MASK, compression=comp, data=transp),
            PsdChannel(channelid=PsdChannelId.CHANNEL0, compression=comp, data=rgb[..., 0]),
            PsdChannel(channelid=PsdChannelId.CHANNEL1, compression=comp, data=rgb[..., 1]),
            PsdChannel(channelid=PsdChannelId.CHANNEL2, compression=comp, data=rgb[..., 2]),
        ],
        mask=PsdLayerMask(), opacity=255, blendmode=PsdBlendMode.NORMAL, blending_ranges=(),
        clipping=PsdClippingType.BASE, flags=PsdLayerFlag.PHOTOSHOP5,
        info=[PsdString(PsdKey.UNICODE_LAYER_NAME, name)],
    ) for name, rgb in reversed(imgs)]
    isd = TiffImageSourceData(
        name="StackForge", psdformat=PsdFormat.LE32BIT,
        layers=PsdLayers(key=key, has_transparency=False, layers=layers),
        usermask=PsdUserMask(colorspace=PsdColorSpaceType.RGB, components=(65535, 0, 0, 0), opacity=50),
        info=[PsdEmpty(PsdKey.PATTERNS),
              PsdFilterMask(colorspace=PsdColorSpaceType.RGB, components=(65535, 0, 0, 0), opacity=50)])
    flat = cv2.cvtColor(flat_bgr, cv2.COLOR_BGR2RGB) if flat_bgr is not None else imgs[0][1]
    tifffile.imwrite(out_path, flat, compression="adobe_deflate", metadata=None,
                     photometric="rgb",
                     extratags=[isd.tifftag(maxworkers=4),
                                (34675, 7, None, imagecodecs.cms_profile("srgb"), True)])


def denoise(img, amount_percent=0.0):
    """Kantenerhaltendes Entrauschen (Bilateralfilter, treu). amount in %, 0 = aus.
    Arbeitet normalisiert, damit 8- und 16-bit gleich behandelt werden."""
    if amount_percent <= 0:
        return img
    a = amount_percent / 50.0
    maxval = 65535.0 if img.dtype == np.uint16 else 255.0
    f = (img.astype(np.float32) / maxval)
    d = int(round(5 + a * 4))
    out = cv2.bilateralFilter(f, d, 0.02 + 0.06 * a, 6 + 6 * a)
    return np.clip(out * maxval, 0, maxval).astype(img.dtype)
