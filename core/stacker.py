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


def _subject_centroid(bgr, min_area=2000):
    """Schwerpunkt des dominanten **Motivs** finden — für bewegte Makro-Motive vor ruhigem
    Hintergrund (Blüte, Insekt …). Cue = **Farbsättigung** über dem flauen Hintergrund. Farbe ist
    weitgehend FOKUS-unabhängig (anders als „Detail/Schärfe", das mit der Schärfeebene wandert) →
    stabiler Anker, auch wenn die Schärfe durch das Motiv läuft.
    Gibt (x, y, area) oder None (kein klares farbiges Motiv → normale Ausrichtung)."""
    if bgr is None or bgr.ndim != 3:
        return None
    im8 = bgr if bgr.dtype == np.uint8 else \
        np.clip(bgr / (256.0 if bgr.dtype == np.uint16 else 1.0), 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(im8, cv2.COLOR_BGR2HSV)
    sat = hsv[..., 1].astype(np.float32)
    s_bg = float(np.median(sat)); s_sig = float(np.median(np.abs(sat - s_bg))) * 1.4826 + 1e-6
    mask = ((sat > (s_bg + max(25.0, 3.0 * s_sig))) & (hsv[..., 2] > 40)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, _lbl, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n < 2:
        return None
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = int(stats[big, cv2.CC_STAT_AREA])
    if area < min_area:
        return None
    return float(cent[big][0]), float(cent[big][1]), area


def subject_motion_span(paths, sample=12):
    """Wie weit wandert das Motiv über die Serie? Gibt den maximalen Schwerpunkt-Versatz als
    Anteil der Bildbreite zurück (0..~1) oder None (kein klares Motiv). Für die Auto-Erkennung
    „bewegtes Motiv" in der Automatik. Liest nur eine Stichprobe (schnell)."""
    if len(paths) < 3:
        return None
    idx = np.linspace(0, len(paths) - 1, min(sample, len(paths))).astype(int)
    cents = []
    for i in idx:
        im = cv2.imread(paths[int(i)], cv2.IMREAD_UNCHANGED)
        if im is None:
            continue
        if im.ndim == 2:
            im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
        h, w = im.shape[:2]
        c = _subject_centroid(im)
        if c and w and h:
            cents.append((c[0] / w, c[1] / h))      # NORMIERT (0..1) — robust gegen Bildgrößen
    if len(cents) < 3:
        return None
    c = np.array(cents)
    return float(np.hypot(c[:, 0].max() - c[:, 0].min(), c[:, 1].max() - c[:, 1].min()))


def align_on_subject(images, ref_idx=None, max_shift_frac=0.25, log=print):
    """Frames so verschieben, dass das **Motiv** (nicht das ganze Bild) deckungsgleich liegt —
    der robuste Weg bei bewegtem Motiv vor ruhigem Hintergrund (Wind-Schwanken etc.). Frames, in
    denen kein klares Motiv gefunden wird oder die zu weit verschoben sind, werden VERWORFEN
    (zurückgegeben als None) — sonst kämen Geister zurück. Gibt (aligned_or_None_Liste) zurück."""
    n = len(images)
    if n < 2:
        return images
    if ref_idx is None:
        ref_idx = n // 2
    ref_c = _subject_centroid(images[ref_idx])
    if ref_c is None:                      # kein klares Motiv → Aufrufer fällt auf normale Ausrichtung zurück
        log("    (kein klares Motiv erkannt — Motiv-Ausrichtung übersprungen)")
        return None
    h, w = images[ref_idx].shape[:2]
    max_shift = max_shift_frac * max(h, w)
    out = [None] * n
    out[ref_idx] = images[ref_idx]
    kept = 1
    for i in range(n):
        if i == ref_idx:
            continue
        c = _subject_centroid(images[i])
        if c is None:
            continue                       # Motiv nicht gefunden → Frame raus
        dx, dy = ref_c[0] - c[0], ref_c[1] - c[1]
        if (dx * dx + dy * dy) ** 0.5 > max_shift:
            continue                       # Motiv zu weit verschoben → Frame raus (sonst Geist)
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        out[i] = cv2.warpAffine(images[i], M, (w, h), flags=cv2.INTER_LANCZOS4,
                                borderMode=cv2.BORDER_CONSTANT)
        kept += 1
    log(f"    Motiv-Ausrichtung: {kept}/{n} Frames passend (Rest verworfen — Motiv zu weit bewegt)")
    return [x for x in out if x is not None]


def _make_detector(detector="ORB"):
    """Feature-Detektor + passender Matcher."""
    if detector == "SIFT":
        return cv2.SIFT_create(), cv2.BFMatcher(cv2.NORM_L2)
    if detector == "AKAZE":
        return cv2.AKAZE_create(), cv2.BFMatcher(cv2.NORM_HAMMING)
    return cv2.ORB_create(5000), cv2.BFMatcher(cv2.NORM_HAMMING)


def _estimate_transform(src_img, dst_img, mode, det, matcher,
                        kp_dst=None, des_dst=None):
    """3×3-Transformation, die src_img-Koordinaten auf dst_img abbildet, oder None
    (zu wenige Merkmale/Treffer). kp_dst/des_dst optional vorbelegbar (spart Neuberechnung
    beim Verketten benachbarter Frames)."""
    if kp_dst is None:
        kp_dst, des_dst = det.detectAndCompute(_to_gray8(dst_img), None)
    kp, des = det.detectAndCompute(_to_gray8(src_img), None)
    if des is None or des_dst is None or len(kp) < 4 or len(kp_dst) < 4:
        return None
    matches = matcher.knnMatch(des, des_dst, k=2)
    good = [m for pair in matches if len(pair) == 2
            for m, nmatch in [pair] if m.distance < 0.75 * nmatch.distance]
    if len(good) < 8:
        return None
    src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_dst[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    if mode == "homography":
        M, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
        return M.astype(np.float32) if M is not None else None
    M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    return np.vstack([M, [0, 0, 1]]).astype(np.float32) if M is not None else None


def align_sequential(images, ref_idx=None, sub_mode="rigid", detector="ORB", log=print):
    """Sequenzielle (paarweise) Ausrichtung: jedes Frame auf seinen NACHBARN ausrichten und die
    Transformationen Richtung Referenz **aufkumulieren** — statt alle auf ein globales Referenzbild.
    Benachbarte Frames im Fokus-Stack sind fast identisch → sehr robuste Schätzung; Frame 1 direkt
    auf Frame 50 (sieht völlig anders aus) wäre fehleranfällig. Ideal für saubere Stativ-Reihen mit
    großem Fokusbereich. sub_mode: 'rigid' (empfohlen — driftet beim Verketten am wenigsten)."""
    n = len(images)
    if n < 2:
        return images
    if ref_idx is None:
        ref_idx = n // 2
    det, matcher = _make_detector(detector)
    h, w = images[ref_idx].shape[:2]
    out = [None] * n
    out[ref_idx] = images[ref_idx]
    feats = {}

    def F(i):                               # Keypoints je Frame cachen (dient als src und Nachbar-dst)
        if i not in feats:
            feats[i] = det.detectAndCompute(_to_gray8(images[i]), None)
        return feats[i]

    def warp(img, T):
        if sub_mode == "homography":
            return cv2.warpPerspective(img, T, (w, h), flags=cv2.INTER_LANCZOS4,
                                       borderMode=cv2.BORDER_CONSTANT)
        return cv2.warpAffine(img, T[:2], (w, h), flags=cv2.INTER_LANCZOS4,
                              borderMode=cv2.BORDER_CONSTANT)

    fail = 0
    cum = np.eye(3, dtype=np.float32)       # nach rechts: i → i-1 → … → ref
    for i in range(ref_idx + 1, n):
        kp_d, des_d = F(i - 1)
        M = _estimate_transform(images[i], images[i - 1], sub_mode, det, matcher, kp_d, des_d)
        if M is None:
            M = np.eye(3, dtype=np.float32); fail += 1
        cum = cum @ M
        out[i] = warp(images[i], cum)
    cum = np.eye(3, dtype=np.float32)       # nach links: i → i+1 → … → ref
    for i in range(ref_idx - 1, -1, -1):
        kp_d, des_d = F(i + 1)
        M = _estimate_transform(images[i], images[i + 1], sub_mode, det, matcher, kp_d, des_d)
        if M is None:
            M = np.eye(3, dtype=np.float32); fail += 1
        cum = cum @ M
        out[i] = warp(images[i], cum)
    log(f"    Sequenzielle Ausrichtung: {n} Frames verkettet"
        + (f" ({fail} Paar(e) ohne Treffer — als unverschoben übernommen)" if fail else ""))
    return out


def align_images(images, ref_idx=None, mode="rigid", detector="ORB", refine=True, log=print):
    """Richtet alle Bilder auf das Referenzbild aus. Gibt ausgerichtete Liste zurück.
    mode: 'rigid' (Verschiebung/Drehung/Skalierung), 'homography' (Perspektive),
    'subject' (auf das dominante Motiv — für bewegte Makro-Motive) oder
    'sequential' (paarweise Nachbar-Verkettung — robust bei großem Fokusbereich).
    refine: nach der Feature-Schätzung eine **ECC-Subpixel-Verfeinerung** (helligkeitsinvariant)
    aufsetzen — deutlich genauer als reine Merkmals-Korrespondenz, besonders an den (defokussierten)
    Stack-Enden, wo ORB wenig findet. Fällt bei Fehlschlag auf die Feature-Ausrichtung zurück."""
    n = len(images)
    if n < 2:
        return images
    if mode == "subject":
        res = align_on_subject(images, ref_idx, log=log)
        if res is not None:
            return res
        mode = "rigid"                     # Fallback, wenn kein klares Motiv
    if mode == "sequential":
        return align_sequential(images, ref_idx, sub_mode="rigid", detector=detector, log=log)
    if ref_idx is None:
        ref_idx = n // 2  # mittleres Bild als Referenz (meist gut fokussiert)
    det, matcher = _make_detector(detector)

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
                                         borderMode=cv2.BORDER_CONSTANT) if M is not None else img
        else:
            M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                               ransacReprojThreshold=3.0)
            if M is None:
                out[i] = img
            elif refine:
                # ECC-Subpixel-Verfeinerung auf der Feature-Schätzung aufsetzen (helligkeitsinvariant).
                # ECC-Konvention: warpMatrix bildet Referenz→Frame ab → init = invertierte Feature-M;
                # als WARP_INVERSE_MAP angewandt richtet es den Frame auf die Referenz aus. BORDER_CONSTANT
                # bleibt erhalten, damit crop_to_overlap die Warp-Ränder findet.
                try:
                    import align_local
                    init_ecc = cv2.invertAffineTransform(M)
                    warp, cc = align_local.ecc_refine(images[ref_idx], img, init=init_ecc, motion="affine")
                    out[i] = cv2.warpAffine(img, warp, (w, h),
                                            flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP,
                                            borderMode=cv2.BORDER_CONSTANT)
                except Exception:
                    out[i] = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LANCZOS4,
                                            borderMode=cv2.BORDER_CONSTANT)
            else:
                out[i] = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LANCZOS4,
                                        borderMode=cv2.BORDER_CONSTANT)
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


def disagreement_map_streamed(paths, max_side=700, align_mode="rigid", detector="ORB",
                              do_align=True, log=print):
    """Wie disagreement_map, aber speicherschonend: lädt EIN Frame nach dem anderen (downscaled,
    grau, aufs erste ausgerichtet) und berechnet die Pro-Pixel-Streuung online (Welford).
    Für sehr große/gestreamte Stacks, wo nicht alle Frames in den RAM passen."""
    ref_bgr = None
    mean = m2 = None
    count = 0

    def _small_gray(im):
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
        if g.dtype != np.uint8:
            g = (g / 256).astype(np.uint8) if g.max() > 255 else g.astype(np.uint8)
        s = max_side / max(g.shape)
        if s < 1.0:
            g = cv2.resize(g, (int(g.shape[1] * s), int(g.shape[0] * s)), interpolation=cv2.INTER_AREA)
        return g

    for p in paths:
        im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
        if im is None:
            continue
        g = _small_gray(im)
        if ref_bgr is None:
            ref_bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
            mean = np.zeros(g.shape, np.float32)
            m2 = np.zeros(g.shape, np.float32)
        else:
            if g.shape != ref_bgr.shape[:2]:
                g = cv2.resize(g, (ref_bgr.shape[1], ref_bgr.shape[0]))
            if do_align:
                try:
                    g = cv2.cvtColor(align_images([ref_bgr, cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)],
                                                  ref_idx=0, mode=align_mode, detector=detector,
                                                  log=lambda *a: None)[1], cv2.COLOR_BGR2GRAY)
                except Exception:
                    pass
        f = g.astype(np.float32)
        count += 1
        delta = f - mean
        mean += delta / count
        m2 += delta * (f - mean)
        log(f"    Geister-Analyse {count}/{len(paths)}")
    if count < 2:
        return None
    std = np.sqrt(m2 / count)
    std = cv2.GaussianBlur(std, (0, 0), 3)
    return std / (std.max() + 1e-6)


def ghost_overlay_from_map(result_bgr, dmap, thresh=0.35):
    """Rote Ghosting-Überlagerung aus einer fertigen Streuungs-Karte (dmap in [0..1])."""
    m = cv2.resize(dmap, (result_bgr.shape[1], result_bgr.shape[0]))
    base = (result_bgr / 256).astype(np.uint8) if result_bgr.dtype == np.uint16 else result_bgr.copy()
    a = (np.clip((m - thresh) / max(1e-6, 1 - thresh), 0, 1) * 0.6)[..., None]
    red = np.zeros_like(base); red[..., 2] = 255
    return (base * (1 - a) + red * a).astype(np.uint8)


def ghost_overlay(result_bgr, images, thresh=0.35):
    """Rote Überlagerung auf dem Ergebnis, wo die Frames stark uneinig sind (Ghosting-Verdacht)."""
    return ghost_overlay_from_map(result_bgr, disagreement_map(images), thresh)


def focus_stack_halofix(images, margin=0.02, soft=2.0, log=print):
    """Dual-Output-Halo-Retusche (Helicon-Retusche-Gedanke, automatisch): die Laplace-Pyramide
    (PMax) ist am schärfsten, erzeugt aber an kontrastreichen Kanten helle/dunkle HALOS — das sind
    Über-/Unterschwinger, also Werte, die in KEINEM einzelnen Quellbild vorkommen (heller als das
    hellste bzw. dunkler als das dunkelste Frame an dieser Stelle).

    Lösung ohne manuelles Pinseln: PMax rechnen (volle Schärfe), dann auf die **Pixel-Hülle** der
    Quellbilder (lokales Min..Max über alle Frames, +kleiner Toleranzrand) begrenzen. Genau die
    unmöglichen Halo-Werte werden gekappt, jedes echte Detail bleibt erhalten. In gekappten Zonen
    wird sanft zur halo-freien Tiefenkarte (DMap) übergeblendet, damit keine harten Klipp-Kanten
    entstehen. margin = Toleranz (Anteil des Wertebereichs), soft = Weichheit der Übergänge."""
    n = len(images)
    if n < 2:
        return images[0] if images else None
    dtype = images[0].dtype
    maxval = 65535.0 if dtype == np.uint16 else 255.0
    imgs = [im if im.ndim == 3 else cv2.cvtColor(im, cv2.COLOR_GRAY2BGR) for im in images]
    sharp = focus_stack(imgs, log=lambda *a: None).astype(np.float32)            # scharf, mit Halo
    base = focus_stack_depthmap(imgs, log=lambda *a: None).astype(np.float32)    # halo-frei
    lo = np.full_like(sharp, np.inf)
    hi = np.full_like(sharp, -np.inf)
    for im in imgs:                                       # Pixel-Hülle (Min..Max) über alle Frames
        f = im.astype(np.float32)
        lo = np.minimum(lo, f); hi = np.maximum(hi, f)
    m = float(margin) * maxval
    lo -= m; hi += m
    clamped = np.clip(sharp, lo, hi)                      # Halos (außerhalb der Hülle) kappen
    halo_amt = np.abs(sharp - clamped).mean(axis=2) if sharp.ndim == 3 else np.abs(sharp - clamped)
    if soft and soft > 0:                                 # in Halo-Zonen sanft zu DMap blenden
        wt = np.clip(halo_amt / (m + 1e-6), 0, 1)
        wt = cv2.GaussianBlur(wt, (0, 0), float(soft))[..., None]
        out = clamped * (1 - wt) + base * wt
    else:
        out = clamped
    frac = float((halo_amt > 1.0).mean())
    log(f"    Halo-Retusche: PMax auf Pixel-Hülle begrenzt ({frac*100:.1f}% Halo-Fläche korrigiert)")
    return np.clip(out, 0, maxval).astype(dtype)


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


def focus_stack_depthmap(images, sharp_blur=4, gamma=8.0, radius=None, smoothing=None, log=print):
    """Depth-Map-Fokus-Stacking (Helicon „DMap"/Zerene-Stil): pro Bildpunkt wird das **schärfste
    Frame** stark bevorzugt — über eine **potenzgewichtete Mischung** der Schärfekarten (Gewicht =
    Schärfe^gamma). Hohes gamma ≈ harte Auswahl des schärfsten Frames (volle Detailschärfe), bleibt
    aber ein weicher Blend der besten 1–2 Frames → **keine dunklen Löcher, keine harten Nähte, keine
    Pyramiden-Halos**. Auf flachen Flächen, wo alle Frames ähnlich sind, mittelt es sauber.
    Stärken: kontrastreiche Tiefenstruktur (Insekten, Münzen, Platinen, tiefe Makro-Stacks).

    Helicon-artige Regler:
      • radius    = Struktur-/Fenstergröße des Schärfemaßes (größer = ruhiger, aber weniger Feindetail).
                    Steuert die Glättung der Schärfekarte (Standard ≈ sharp_blur).
      • smoothing = Weichheit der Übergänge zwischen Quellbildern (Feathering der Gewichtskarten gegen
                    harte Nähte; 0 = aus)."""
    n = len(images)
    if n < 2:
        return images[0] if images else None
    rad = float(sharp_blur if radius is None else max(0.5, radius))
    sm = float(0.0 if smoothing is None else max(0.0, smoothing))
    dtype = images[0].dtype
    maxval = 65535.0 if dtype == np.uint16 else 255.0
    h, w = images[0].shape[:2]
    fl = [im.astype(np.float32) for im in images]
    # Schärfekarte je Bild: |Laplace| auf Graustufen, geglättet im Radius-Fenster (Region statt Pixel)
    S = np.empty((n, h, w), np.float32)
    for i, im in enumerate(fl):
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
        S[i] = cv2.GaussianBlur(np.abs(cv2.Laplacian(g, cv2.CV_32F)), (0, 0), rad)
        log(f"    Schärfekarte {i + 1}/{n}")
    # Potenzgewichte: Schärfe^gamma, je Pixel normiert. Hohes gamma → schärfstes Frame dominiert klar.
    Smax = S.max(axis=0, keepdims=True) + 1e-6
    Wt = (S / Smax) ** gamma                              # 0..1, schärfstes Frame = 1
    if sm > 0:                                            # Übergänge feathern (weiche Nähte)
        Wt = np.stack([cv2.GaussianBlur(Wt[i], (0, 0), sm) for i in range(n)])
    Wt /= Wt.sum(axis=0, keepdims=True) + 1e-6
    out = np.zeros_like(fl[0])
    for i in range(n):
        out += (Wt[i][..., None] if fl[i].ndim == 3 else Wt[i]) * fl[i]
    log(f"    Tiefenkarte verschmolzen (radius {rad:.1f}, smoothing {sm:.1f})")
    return np.clip(out, 0, maxval).astype(dtype)


def _focus_measure(bgr):
    """Schärfemaß je Pixel: Sum-Modified-Laplacian (SML) — robuster als Varianz-Laplace."""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) if bgr.ndim == 3 else bgr.astype(np.float32)
    lx = cv2.filter2D(g, cv2.CV_32F, np.array([[-1, 2, -1]], np.float32))
    ly = cv2.filter2D(g, cv2.CV_32F, np.array([[-1], [2], [-1]], np.float32))
    return np.abs(lx) + np.abs(ly)


def focus_stack_average(images, radius=9, smoothing=0, log=print):
    """Method A (Helicon): **gewichteter Mittelwert** nach lokalem Schärfemaß. Rauscharm und
    farbtreu — ideal für kurze/Freihand-Stacks und weiche Motive.
      • radius    = Fenster des Schärfemaßes (größer = ruhiger/weicher).
      • smoothing = zusätzliche Weichheit der Gewichtskarten (Feathering der Übergänge; 0 = aus)."""
    n = len(images)
    if n < 2:
        return images[0] if images else None
    radius = max(1, int(radius))
    dtype = images[0].dtype
    maxval = 65535.0 if dtype == np.uint16 else 255.0
    fl = [im.astype(np.float32) if im.ndim == 3 else cv2.cvtColor(im, cv2.COLOR_GRAY2BGR).astype(np.float32)
          for im in images]
    W = np.stack([cv2.boxFilter(_focus_measure(im), cv2.CV_32F, (radius, radius)) for im in images])
    W = (W + 1e-6)
    if smoothing and smoothing > 0:
        W = np.stack([cv2.GaussianBlur(W[i], (0, 0), float(smoothing)) for i in range(n)])
    W /= W.sum(axis=0, keepdims=True)
    out = np.zeros_like(fl[0])
    for i in range(n):
        out += W[i][..., None] * fl[i]
        log(f"    Method A: Frame {i + 1}/{n}")
    return np.clip(out, 0, maxval).astype(dtype)


def color_reassign(images, merged):
    """Farb-Neuzuweisung: für jeden Bildpunkt die ECHTE Farbe aus dem Quellframe nehmen, dessen
    Schärfemaß dort am höchsten ist (statt der gemischten Pyramiden-Farbe) — verhindert erfundene
    Farben/Farb-Halos. `merged` nur als Größen-Referenz."""
    n = len(images)
    fm = np.stack([_focus_measure(im) for im in images])     # (n,h,w)
    idx = np.argmax(fm, axis=0).astype(np.uint8)
    idx = cv2.medianBlur(idx, 5)                              # kohärente Regionen
    out = np.zeros_like(images[0])
    for i in range(n):
        m = idx == i
        if m.any():
            out[m] = images[i][m]
    return out


def focus_stack_wavelet(images, levels=5, log=print):
    """Wavelet-Merge (PetteriAimonen-Rezept, vereinfacht): pro Frame à-trous-Detailebenen, je Ebene
    den **betragsmäßig stärksten** Koeffizienten wählen, die Auswahl per **Konsistenz-Glättung**
    stabilisieren (gegen Rausch-/Fehlausrichtungs-Einrasten) → rekonstruieren; Farbe per
    color_reassign aus dem schärfsten Quellframe. Schärfer + rauschärmer als die naive Pyramide."""
    import wavelet as _wav
    n = len(images)
    if n < 2:
        return images[0] if images else None
    grays = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32) if im.ndim == 3
             else im.astype(np.float32) for im in images]
    decs = [_wav.atrous(g, levels) for g in grays]           # [(details, approx), ...]
    fused_details = []
    for lv in range(levels):
        layer = np.stack([decs[i][0][lv] for i in range(n)])  # (n,h,w)
        amax = np.abs(layer)
        idx = np.argmax(amax, axis=0)
        idx = cv2.medianBlur(idx.astype(np.uint8), 3).astype(np.int64)   # Konsistenz-Vote
        fused_details.append(np.take_along_axis(layer, idx[None], axis=0)[0])
    approx = np.mean(np.stack([decs[i][1] for i in range(n)]), axis=0)   # Basis = Mittel
    merged_gray = approx + sum(fused_details)
    merged = cv2.cvtColor(np.clip(merged_gray, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR) \
        if images[0].ndim == 3 else np.clip(merged_gray, 0, 255).astype(images[0].dtype)
    log(f"    Wavelet-Merge: {n} Frames, {levels} Ebenen")
    if images[0].ndim == 3:                                   # echte Farbe aus dem schärfsten Frame
        return color_reassign(images, merged)
    return merged


def _largest_rect(mask):
    """Größtes Rechteck aus 1-en in einer Binärmaske (Histogramm-Methode). Gibt (y0,y1,x0,x1)."""
    h, w = mask.shape
    heights = np.zeros(w + 1, np.int32)
    best = (0, 0, 0, 0, 0)
    for y in range(h):
        heights[:w] = np.where(mask[y] > 0, heights[:w] + 1, 0)
        stack = []
        for x in range(w + 1):
            start = x
            while stack and stack[-1][1] > heights[x]:
                sx, sh = stack.pop()
                area = sh * (x - sx)
                if area > best[0]:
                    best = (area, y - sh + 1, y + 1, sx, x)
                start = sx
            stack.append((start, int(heights[x])))
    return best[1], best[2], best[3], best[4]


def crop_to_overlap(images, thresh=3, log=print):
    """Auf das **größte voll-überlappte Rechteck** ausgerichteter Frames zuschneiden — entfernt die
    schwarzen Warp-Ränder UND die gedrehten Frame-Kanten (die „komischen Striche"), sodass jeder
    Bildpunkt im Ergebnis von ALLEN Frames abgedeckt ist. Gibt die zugeschnittene Liste zurück."""
    if len(images) < 2:
        return images
    h, w = images[0].shape[:2]
    common = np.ones((h, w), np.uint8)
    for im in images:
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
        common &= (g > thresh).astype(np.uint8)
    if common.sum() < 100:
        return images
    # größtes Rechteck auf verkleinerter Maske finden (schnell), dann auf Originalgröße skalieren
    ds = max(1, max(h, w) // 240)
    small = cv2.erode(common[::ds, ::ds], np.ones((3, 3), np.uint8))     # Sicherheitsrand
    if small.sum() < 20:
        small = common[::ds, ::ds]
    ry0, ry1, rx0, rx1 = _largest_rect(small)
    y0, y1, x0, x1 = ry0 * ds, ry1 * ds, rx0 * ds, rx1 * ds
    if (y1 - y0) < h * 0.2 or (x1 - x0) < w * 0.2:
        log(f"    (gemeinsames Rechteck nur ~{100*(y1-y0)*(x1-x0)//(h*w)} % — Frames stark versetzt)")
        if (y1 - y0) < 20 or (x1 - x0) < 20:
            return images
    return [im[y0:y1, x0:x1] for im in images]


def merge_tree(images, merge_fn, log=print):
    """Hierarchische („Baum-") Verschmelzung: 1+2, 3+4, … dann die Ergebnisse paarweise weiter,
    bis ein Bild übrig ist. Jede Verschmelzung kombiniert nur **zwei sehr ähnliche** Bilder →
    gutmütiger als alle Frames auf einmal flach zu mischen. merge_fn(liste_aus_2) → ein Bild."""
    level = [im for im in images if im is not None]
    if len(level) < 2:
        return level[0] if level else None
    rnd = 1
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            nxt.append(merge_fn(level[i:i + 2]) if i + 1 < len(level) else level[i])
        log(f"    Baum-Merge Runde {rnd}: {len(level)} → {len(nxt)}")
        level = nxt
        rnd += 1
    return level[0]


def focus_stack_streamed(paths, align_mode="rigid", detector="ORB", chunk=8,
                         do_align=True, method="pyramid", tree=False, log=print, preview_cb=None):
    """Speicherschonendes Stacken: liest Frames in Bündeln von `chunk` von der Platte,
    richtet sie aufs (globale) Referenzbild aus, verschmilzt je Bündel, dann die
    Zwischenergebnisse. RAM ~ max(chunk, Anzahl Bündel) Frames statt alle gleichzeitig.

    method: „pyramid" (Laplace-Pyramide, Standard) oder „depthmap" (Tiefenkarten-Auswahl).

    preview_cb(img_bgr, k): optionaler Callback für die Live-Vorschau — wird nach jedem Bündel
    mit dem bisher zusammengeführten (Teil-)Ergebnis aufgerufen."""
    def merge(grp):
        if method == "depthmap":
            return focus_stack_depthmap(grp, log=lambda *a: None)
        if method == "average":
            return focus_stack_average(grp, log=lambda *a: None)
        if method == "wavelet":
            return focus_stack_wavelet(grp, log=lambda *a: None)
        return focus_stack(grp, log=lambda *a: None)
    ref = cv2.imread(paths[len(paths) // 2], cv2.IMREAD_UNCHANGED)
    inters = []
    running = None
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
        if not grp:                         # Motiv-Ausrichtung kann alle Frames im Bündel verwerfen
            continue
        merged = merge(grp)
        inters.append(merged)
        log(f"    Bündel {i // chunk + 1}/{(n + chunk - 1) // chunk} verschmolzen "
            f"({len(grp)} Frames)")
        if preview_cb:
            running = merged if running is None else merge([running, merged])
            try:
                preview_cb(running, len(inters))
            except Exception:
                pass
    if not inters:                          # alle Bündel verworfen → Referenz zurückgeben
        log("    (kein Bündel übrig — Referenzbild als Ergebnis)")
        return ref
    if len(inters) == 1:
        return inters[0]
    log("    Bündel zusammenführen …")
    if tree:                                # Bündel-Ergebnisse hierarchisch (paarweise) verschmelzen
        return merge_tree(inters, lambda pair: merge(pair), log=log)
    return merge(inters)


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
        name="ForgePix", psdformat=PsdFormat.LE32BIT,
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
