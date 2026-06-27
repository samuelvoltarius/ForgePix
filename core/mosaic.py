#!/usr/bin/env python3
"""
mosaic.py — Mosaik/Panorama-Zusammensetzen für Modul „Hybrid" (Mond-/Sonnen-Mosaik).

Setzt überlappende Kacheln (Panels) zu einem großen Bild zusammen — z.B. mehrere
Aufnahmen vom Mond/Sonne, die zusammen die ganze Scheibe ergeben. Reine OpenCV-Lösung.
"""
import cv2
import numpy as np
from scipy.optimize import least_squares


def _to8(img):
    if img is None:
        return None
    if img.dtype == np.uint16:
        return (img / 256).astype(np.uint8)
    if img.dtype != np.uint8:
        return np.clip(img, 0, 255).astype(np.uint8)
    return img


def stitch_from_points(img_a, img_b, pts_a, pts_b, log=print):
    """MANUELLES Zusammensetzen über Kontrollpunkte (Hugin/PTGui-Prinzip): wenn die automatische
    Erkennung versagt (wenig Überlappung/Struktur, sich wiederholende Muster), gibt der/die Nutzer:in
    selbst zusammengehörige Punktpaare an (≥4) — daraus wird die Homographie B→A geschätzt, B in die
    Ebene von A gewarpt und nahtlos (distanzgewichtet gefedert) eingeblendet. Gibt das Panorama (BGR).

    pts_a/pts_b: Listen von (x, y) in Bild A bzw. B (gleiche Reihenfolge = zusammengehörig)."""
    a = _to8(img_a); b = _to8(img_b)
    pa = np.asarray(pts_a, np.float32); pb = np.asarray(pts_b, np.float32)
    if len(pa) < 4 or len(pa) != len(pb):
        raise ValueError("mindestens 4 zusammengehörige Punktpaare nötig")
    H, _ = cv2.findHomography(pb, pa, cv2.RANSAC, 5.0)
    if H is None:
        raise ValueError("Homographie aus den Punkten nicht bestimmbar")
    ha, wa = a.shape[:2]; hb, wb = b.shape[:2]
    cb = np.float32([[0, 0], [wb, 0], [wb, hb], [0, hb]]).reshape(-1, 1, 2)
    cbw = cv2.perspectiveTransform(cb, H).reshape(-1, 2)
    allp = np.vstack([cbw, [[0, 0], [wa, 0], [wa, ha], [0, ha]]])
    xmin, ymin = np.floor(allp.min(0)).astype(int)
    xmax, ymax = np.ceil(allp.max(0)).astype(int)
    T = np.float32([[1, 0, -xmin], [0, 1, -ymin], [0, 0, 1]])
    W, Hh = int(xmax - xmin), int(ymax - ymin)
    if W <= 0 or Hh <= 0 or W * Hh > 80_000_000:
        raise ValueError("ungültige Panorama-Größe (Punkte prüfen)")
    aw = cv2.warpPerspective(a, T, (W, Hh))
    bw = cv2.warpPerspective(b, T @ H, (W, Hh))
    ma = cv2.warpPerspective(np.full((ha, wa), 255, np.uint8), T, (W, Hh))
    mb = cv2.warpPerspective(np.full((hb, wb), 255, np.uint8), T @ H, (W, Hh))
    da = cv2.distanceTransform((ma > 0).astype(np.uint8), cv2.DIST_L2, 3)
    db = cv2.distanceTransform((mb > 0).astype(np.uint8), cv2.DIST_L2, 3)
    wsum = da + db + 1e-6
    blend = (aw.astype(np.float32) * da[..., None] + bw.astype(np.float32) * db[..., None]) / wsum[..., None]
    valid = ((ma > 0) | (mb > 0))[..., None]
    out = np.where(valid, np.clip(blend, 0, 255), 0).astype(np.uint8)
    log(f"    Kontrollpunkt-Stitch: {len(pa)} Punktpaare → {W}×{Hh}")
    return out


def stitch_detail(imgs, projection="spherical", log=print, masks=None):
    """Explizite cv2.detail-Pipeline (statt Black-Box-Stitcher) mit Kontrolle über **Projektion**,
    **Belichtungsausgleich** (BlocksGain) und **MultiBand-Nahtmischung** (enblend-Äquivalent) +
    GraphCut-Nähte. Gibt das Panorama (uint8 BGR) zurück oder wirft bei Fehlschlag.

    masks (P5 Include/Exclude): optionale Liste von Bitmaps (eine je Bild, gleiche
    Reihenfolge wie ``imgs``; Eintrag None = Vollbild). Wo eine Maske 0 ist, wird der
    betreffende Bildbereich VOR dem Warpen ausgeschlossen — der GraphCut-Seam-Finder
    sieht ihn nicht und legt keine Naht hindurch. So lassen sich bewegte Objekte
    (Satellitenspuren, vorbeiziehende Wolken, Personen) gezielt aus dem Mosaik nehmen.
    Die Masken ersetzen die sonst übliche 255-Vollbild-Initialisierung. Sie werden auf
    die Arbeitsauflösung (work_scale) skaliert und müssen die Originalgröße des jeweiligen
    Bildes haben (HxW)."""
    work_scale = min(1.0, 1000.0 / max(im.shape[1] for im in imgs))
    finder = cv2.SIFT_create() if hasattr(cv2, "SIFT_create") else cv2.ORB_create(1000)
    feats = []
    for im in imgs:
        s = cv2.resize(im, (0, 0), fx=work_scale, fy=work_scale) if work_scale < 1 else im
        feats.append(cv2.detail.computeImageFeatures2(finder, s))
    matcher = cv2.detail_BestOf2NearestMatcher(False, 0.55)
    pw = matcher.apply2(feats)
    matcher.collectGarbage()
    est = cv2.detail_HomographyBasedEstimator()
    ok, cams = est.apply(feats, pw, None)
    if not ok:
        raise RuntimeError("Kamera-Schätzung fehlgeschlagen")
    for c in cams:
        c.R = c.R.astype(np.float32)
    adj = cv2.detail_BundleAdjusterRay()
    adj.setConfThresh(0.7)
    ok, cams = adj.apply(feats, pw, cams)
    if not ok:
        raise RuntimeError("Bündelausgleich fehlgeschlagen")
    rmats = [np.copy(c.R) for c in cams]
    # WAVE_CORRECT_AUTO statt hart HORIZ: HORIZ verbiegt Multi-Row-/Gitter-Mosaike (z. B. Mond-Kachelraster)
    # vertikal. AUTO wählt Horizontal/Vertikal passend; Fallback HORIZ für ältere OpenCV ohne AUTO.
    try:
        cv2.detail.waveCorrect(rmats, cv2.detail.WAVE_CORRECT_AUTO)
    except (cv2.error, AttributeError):
        cv2.detail.waveCorrect(rmats, cv2.detail.WAVE_CORRECT_HORIZ)
    for c, R in zip(cams, rmats):
        c.R = R
    scale = float(np.median([c.focal for c in cams]))
    warper = cv2.PyRotationWarper(projection, scale * work_scale)
    corners, masks_w, imgs_w, sizes = [], [], [], []
    for i, (im, c) in enumerate(zip(imgs, cams)):
        s = cv2.resize(im, (0, 0), fx=work_scale, fy=work_scale) if work_scale < 1 else im
        K = c.K().astype(np.float32)
        corner, wimg = warper.warp(s, K, c.R, cv2.INTER_LINEAR, cv2.BORDER_REFLECT)
        # P5: nutzerdefinierte Include/Exclude-Maske statt Vollbild-255, falls vorhanden
        um = masks[i] if (masks is not None and i < len(masks)) else None
        if um is None:
            mask = 255 * np.ones(s.shape[:2], np.uint8)
        else:
            mask = (np.asarray(um) > 0).astype(np.uint8) * 255
            if mask.shape[:2] != im.shape[:2]:
                raise ValueError(f"Maske {i} hat Größe {mask.shape[:2]}, erwartet {im.shape[:2]}")
            if work_scale < 1:
                mask = cv2.resize(mask, (s.shape[1], s.shape[0]), interpolation=cv2.INTER_NEAREST)
        _, wmask = warper.warp(mask, K, c.R, cv2.INTER_NEAREST, cv2.BORDER_CONSTANT)
        corners.append(corner); imgs_w.append(wimg.astype(np.float32))
        masks_w.append(wmask); sizes.append((wimg.shape[1], wimg.shape[0]))
    comp = cv2.detail.ExposureCompensator_createDefault(cv2.detail.ExposureCompensator_GAIN_BLOCKS)
    comp.feed(corners, [w.astype(np.uint8) for w in imgs_w], masks_w)
    seamer = cv2.detail_GraphCutSeamFinder("COST_COLOR")
    seam_masks = seamer.find([i.astype(np.float32) for i in imgs_w], corners, masks_w)
    blender = cv2.detail_MultiBandBlender()
    dst_sz = cv2.detail.resultRoi(corners, sizes)
    blender.prepare(dst_sz)
    for idx in range(len(imgs_w)):
        comp.apply(idx, corners[idx], imgs_w[idx].astype(np.uint8), masks_w[idx])
        sm = cv2.resize(seam_masks[idx].get() if hasattr(seam_masks[idx], "get") else seam_masks[idx],
                        (masks_w[idx].shape[1], masks_w[idx].shape[0]), interpolation=cv2.INTER_NEAREST)
        m = cv2.bitwise_and(sm, masks_w[idx])
        blender.feed(imgs_w[idx].astype(np.int16), m, corners[idx])
    pano, _ = blender.blend(None, None)
    return _to8(np.clip(pano, 0, 255))


def _autocrop(img, thresh=8):
    """Schwarze Stitch-Ränder wegschneiden: das GRÖSSTE randvolle Rechteck finden (alle Pixel gültig),
    über den klassischen „maximal rectangle in a binary matrix"-Algorithmus (histogramm-basiert, O(H·W)).
    So bekommt das Panorama einen sauberen rechteckigen Rand statt schwarzer Zacken — der häufigste
    Profi-vs-Amateur-Unterschied. Bei großen Bildern auf der herunterskalierten Maske rechnen."""
    if img is None or img.ndim != 3:
        return img
    H, W = img.shape[:2]
    valid = (img.max(axis=2) > thresh).astype(np.uint8)
    scale = min(1.0, 1000.0 / max(H, W))
    vs = cv2.resize(valid, (max(1, int(W * scale)), max(1, int(H * scale))),
                    interpolation=cv2.INTER_NEAREST) if scale < 1.0 else valid
    h, w = vs.shape
    height = np.zeros(w, np.int32)
    best = (0, 0, 0, 0, 0)                                  # area, x0, y0, x1, y1
    for r in range(h):
        height = np.where(vs[r] > 0, height + 1, 0)
        hgt = height.tolist() + [0]
        stack = []
        for i in range(len(hgt)):
            while stack and hgt[i] < hgt[stack[-1]]:
                top = stack.pop()
                width = i if not stack else i - stack[-1] - 1
                area = hgt[top] * width
                if area > best[0]:
                    x0 = (stack[-1] + 1) if stack else 0
                    best = (area, x0, r - hgt[top] + 1, i - 1, r)
            stack.append(i)
    if best[0] == 0:
        return img
    _, x0, y0, x1, y1 = best
    x0, x1 = int(x0 / scale), int((x1 + 1) / scale)
    y0, y1 = int(y0 / scale), int((y1 + 1) / scale)
    crop = img[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
    if crop.shape[0] < H * 0.25 or crop.shape[1] < W * 0.25:
        return img                                         # Crop zu aggressiv → lieber Original lassen
    return crop


def stitch(paths, mode="panorama", projection="spherical", detail=True, autocrop=True, log=print):
    """Überlappende Kacheln zu einem Mosaik zusammensetzen.
    detail=True: explizite cv2.detail-Pipeline (Projektion/Belichtungsausgleich/MultiBand-Nähte),
    bei Fehlschlag Rückfall auf den klassischen cv2.Stitcher. Gibt (BGR-uint8, status) zurück.
    autocrop=True: schwarze Warp-Ränder auf das größte randvolle Rechteck zuschneiden (--no-autocrop = aus)."""
    _crop = _autocrop if autocrop else (lambda x: x)
    imgs = [_to8(cv2.imread(p, cv2.IMREAD_UNCHANGED)) for p in paths]
    imgs = [im if (im is None or im.ndim == 3) else cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
            for im in imgs]
    imgs = [im for im in imgs if im is not None]
    if len(imgs) < 2:
        raise RuntimeError("Mindestens 2 überlappende Kacheln nötig")
    log(f"  {len(imgs)} Kacheln zusammensetzen ({mode}, {projection}) …")
    if detail and mode != "scans":
        try:
            return _crop(stitch_detail(imgs, projection=projection, log=log)), "ok (detail)"
        except Exception as e:
            log(f"  detail-Pipeline fehlgeschlagen ({e}) → klassischer Stitcher")
    m = cv2.Stitcher_SCANS if mode == "scans" else cv2.Stitcher_PANORAMA
    st = cv2.Stitcher_create(m)
    status, pano = st.stitch(imgs)
    if status != cv2.Stitcher_OK:
        msgs = {1: "zu wenig Überlappung / zu wenige gemeinsame Merkmale",
                2: "Homographie-Schätzung fehlgeschlagen",
                3: "Kamera-Parameter-Anpassung fehlgeschlagen"}
        raise RuntimeError(f"Mosaik fehlgeschlagen ({msgs.get(status, status)}). "
                           f"Tipp: mehr Überlappung (~30 %) zwischen den Kacheln.")
    return _crop(pano), "ok"


# ─────────────────────────────────────────────────────────────────────────────
# P1 — Eigener Bündelausgleich mit Selbstkalibrierung der Linsen-Verzeichnung
# ─────────────────────────────────────────────────────────────────────────────

def _rodrigues(rvec):
    """Achswinkel-Vektor → 3×3-Rotationsmatrix (eigene Rodrigues-Formel, ohne cv2)."""
    rvec = np.asarray(rvec, np.float64)
    theta = np.linalg.norm(rvec)
    if theta < 1e-12:
        return np.eye(3)
    k = rvec / theta
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)


def _hugin_distort(xy, cx, cy, nrm, a, b, c):
    """Hugin/Panotools-Radialmodell auf normierte Bildkoordinaten anwenden.

    Punkte werden ab Bildmitte (cx, cy) genommen, mit ``nrm`` (halbe kürzere
    Bildseite) auf Einheitsradius normiert; der korrigierte Radius ist
    r_src = a·r⁴ + b·r³ + c·r² + d·r  mit  d = 1 − (a + b + c).  Rückgabe in Pixeln."""
    d = 1.0 - (a + b + c)
    dx = (xy[:, 0] - cx) / nrm
    dy = (xy[:, 1] - cy) / nrm
    r = np.sqrt(dx * dx + dy * dy) + 1e-12
    scale = (a * r**3 + b * r**2 + c * r + d)  # r_src/r
    return np.column_stack([cx + dx * scale * nrm, cy + dy * scale * nrm])


def bundle_adjust_distortion(point_pairs, image_shapes, f_init=None, log=print,
                             max_nfev=200):
    """P1 — Eigener Bündelausgleich MIT Selbstkalibrierung der Linsen-Verzeichnung.

    Minimiert den Reprojektionsfehler aller Kontrollpunkt-Paare über den Parametern
    [R_i (3 je Bild, Achswinkel), gemeinsame Brennweite f, Verzeichnung a, b, c]. Die
    Verzeichnung (Hugin-Modell r_src = a·r⁴+b·r³+c·r²+d·r, d=1−(a+b+c)) wird **allein aus
    den Korrespondenzen** geschätzt: weil sich überlappende Bilder die Tonnen-/Kissen-
    Verzeichnung in entgegengesetzte Richtungen zeigen, ist sie aus den Punktpaaren lösbar.
    Gelöst mit scipy.optimize.least_squares (TRF, robuster Huber-loss).

    Parameter
    ---------
    point_pairs : Liste von (i, j, pts_i, pts_j)
        Bildindizes i,j und je ein (N,2)-Array zusammengehöriger Pixelkoordinaten.
    image_shapes : Liste von (H, W) je Bild.
    f_init : optionale Start-Brennweite in Pixeln (Default: mittlere Bildbreite).

    Rückgabe
    --------
    dict mit ``R`` (Liste 3×3), ``f`` (float), ``a``/``b``/``c`` (floats),
    ``residual_init`` und ``residual_final`` (RMS-Reprojektionsfehler je vor/nach Opt.).

    Funktionsweise: jeder Punkt wird linsen-entzerrt, mit K⁻¹ in einen Strahl gehoben,
    per R_i in die Welt und per R_j⁻¹ ins Nachbarbild zurückprojiziert; die Differenz zur
    dort gemessenen (ebenfalls entzerrten) Lage ist das Residuum."""
    n = len(image_shapes)
    shapes = [(int(s[0]), int(s[1])) for s in image_shapes]
    if f_init is None:
        f_init = float(np.mean([w for _, w in shapes]))
    cx = [w / 2.0 for _, w in shapes]
    cy = [h / 2.0 for h, _ in shapes]
    nrm = [min(h, w) / 2.0 for h, w in shapes]

    def unpack(p):
        rs = [p[3 * i:3 * i + 3] for i in range(n)]
        f, a, b, c = p[3 * n], p[3 * n + 1], p[3 * n + 2], p[3 * n + 3]
        return rs, f, a, b, c

    def rays(idx, pts, f, a, b, c, R):
        und = _hugin_distort(pts, cx[idx], cy[idx], nrm[idx], a, b, c)
        x = (und[:, 0] - cx[idx]) / f
        y = (und[:, 1] - cy[idx]) / f
        v = np.column_stack([x, y, np.ones(len(x))])
        v = v / np.linalg.norm(v, axis=1, keepdims=True)
        return v @ R.T  # in Weltkoordinaten

    def residuals(p):
        rs, f, a, b, c = unpack(p)
        Rmats = [_rodrigues(r) for r in rs]
        res = []
        for i, j, pi, pj in pairs:
            wi = rays(i, pi, f, a, b, c, Rmats[i])
            # in Bild j projizieren
            cj = wi @ Rmats[j]                      # Weltstrahl in Kamera-j-Koord.
            z = np.clip(cj[:, 2], 1e-6, None)
            xj = cj[:, 0] / z * f + cx[j]
            yj = cj[:, 1] / z * f + cy[j]
            meas = _hugin_distort(pj, cx[j], cy[j], nrm[j], a, b, c)
            res.append((xj - meas[:, 0]))
            res.append((yj - meas[:, 1]))
        return np.concatenate(res) if res else np.zeros(1)

    pairs = [(int(i), int(j), np.asarray(pi, np.float64), np.asarray(pj, np.float64))
             for i, j, pi, pj in point_pairs]
    p0 = np.zeros(3 * n + 4)
    p0[3 * n] = f_init  # f; a=b=c=0 → reine Identitäts-Verzeichnung als Start
    r0 = residuals(p0)
    rms0 = float(np.sqrt(np.mean(r0 ** 2)))
    sol = least_squares(residuals, p0, method="trf", loss="huber",
                        f_scale=2.0, max_nfev=max_nfev)
    rs, f, a, b, c = unpack(sol.x)
    rms1 = float(np.sqrt(np.mean(sol.fun ** 2)))
    log(f"    Verzeichnungs-BA: RMS {rms0:.3f}px → {rms1:.3f}px  (f={f:.1f}, a={a:.4f}, b={b:.4f}, c={c:.4f})")
    return {"R": [_rodrigues(r) for r in rs], "f": f, "a": a, "b": b, "c": c,
            "residual_init": rms0, "residual_final": rms1}


# ─────────────────────────────────────────────────────────────────────────────
# P2 — Photometrische Optimierung (Vignette + Belichtung) aus Überlappungen
# ─────────────────────────────────────────────────────────────────────────────

def optimize_photometric(images, overlaps, log=print, max_nfev=120):
    """P2 — Vignette- und Belichtungs-Selbstkalibrierung aus Überlappungspixeln.

    Schätzt je Bild einen Belichtungs-Offset (multiplikativer Gain) und ein gemeinsames
    radiales Vignette-Modell  V(r) = 1 + Vb·r² + Vc·r⁴  (r = normierter Radius ab Bildmitte)
    aus den Helligkeitsverhältnissen korrespondierender Überlappungspixel zweier Kacheln.
    Per scipy.optimize.least_squares wird gefordert, dass entvignettierte & belichtungs-
    korrigierte Werte korrespondierender Pixel gleich werden. Anschließend werden die
    Kacheln **vor dem Warpen** entvignettiert/belichtungsangeglichen zurückgegeben.

    Parameter
    ---------
    images : Liste BGR/Grau-uint8/Float-Kacheln.
    overlaps : Liste von (i, j, pts_i, pts_j) — Bildindizes und je (N,2)-Pixelkoordinaten
        korrespondierender Überlappungspunkte (z. B. aus Feature-Matches).

    Rückgabe
    --------
    (corrected_images, params) — Liste korrigierter Bilder (gleiche dtype wie Eingabe,
    uint8 geclippt) und dict mit ``gain`` (Liste je Bild), ``Vb``, ``Vc``."""
    imgs = [im if im.ndim == 2 else cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in images]
    imgs = [im.astype(np.float64) for im in imgs]
    n = len(imgs)
    cx = [im.shape[1] / 2.0 for im in imgs]
    cy = [im.shape[0] / 2.0 for im in imgs]
    nrm = [min(im.shape[:2]) / 2.0 for im in imgs]

    def sample(idx, pts):
        x = np.clip(np.round(pts[:, 0]).astype(int), 0, imgs[idx].shape[1] - 1)
        y = np.clip(np.round(pts[:, 1]).astype(int), 0, imgs[idx].shape[0] - 1)
        vals = imgs[idx][y, x]
        rx = (x - cx[idx]) / nrm[idx]
        ry = (y - cy[idx]) / nrm[idx]
        return vals, rx * rx + ry * ry

    obs = []  # (i, vals_i, r2_i, j, vals_j, r2_j)
    for i, j, pi, pj in overlaps:
        vi, r2i = sample(int(i), np.asarray(pi, np.float64))
        vj, r2j = sample(int(j), np.asarray(pj, np.float64))
        obs.append((int(i), vi, r2i, int(j), vj, r2j))

    def vign(r2, Vb, Vc):
        return 1.0 + Vb * r2 + Vc * r2 * r2

    def residuals(p):
        loggain = p[:n]
        Vb, Vc = p[n], p[n + 1]
        res = []
        for i, vi, r2i, j, vj, r2j in obs:
            ci = vi / np.clip(vign(r2i, Vb, Vc), 0.2, 5.0) * np.exp(loggain[i])
            cj = vj / np.clip(vign(r2j, Vb, Vc), 0.2, 5.0) * np.exp(loggain[j])
            res.append(ci - cj)
        # schwache Verankerung: mittlerer log-Gain = 0 (sonst global unterbestimmt)
        res.append(np.array([np.mean(loggain) * 50.0]))
        return np.concatenate(res) if res else np.zeros(1)

    p0 = np.zeros(n + 2)
    sol = least_squares(residuals, p0, method="trf", loss="soft_l1",
                        f_scale=10.0, max_nfev=max_nfev)
    loggain = sol.x[:n]
    Vb, Vc = float(sol.x[n]), float(sol.x[n + 1])
    gains = np.exp(loggain)
    gains = gains / np.mean(gains)  # normieren, Gesamthelligkeit erhalten

    corrected = []
    for k, src in enumerate(images):
        h, w = src.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        r2 = ((xx - cx[k]) / nrm[k]) ** 2 + ((yy - cy[k]) / nrm[k]) ** 2
        V = np.clip(vign(r2, Vb, Vc), 0.2, 5.0)
        f = (gains[k] / V).astype(np.float32)
        if src.ndim == 3:
            f = f[..., None]
        out = src.astype(np.float32) * f
        corrected.append(np.clip(out, 0, 255).astype(np.uint8))
    log(f"    Photometrie: Gains {np.round(gains, 3).tolist()}  Vb={Vb:.4f} Vc={Vc:.4f}")
    return corrected, {"gain": gains.tolist(), "Vb": Vb, "Vc": Vc}


# ─────────────────────────────────────────────────────────────────────────────
# P4 — Manuelle N-Bild-Kontrollpunkte (Kette von Homographien)
# ─────────────────────────────────────────────────────────────────────────────

def stitch_from_points_multi(images, points_per_pair, log=print):
    """P4 — Manuelles Zusammensetzen von **N Bildern** über Kontrollpunkt-Paare.

    Erweiterung von ``stitch_from_points`` (nur 2 Bilder) auf beliebig viele Kacheln:
    der/die Nutzer:in gibt für aufeinanderfolgende (oder per ``points_per_pair`` benannte)
    Bildpaare zusammengehörige Punktpaare an. Die paarweisen Homographien werden in eine
    gemeinsame Referenz-Ebene (Bild 0) **verkettet** (H_k = H_0←1 · H_1←2 · …), alle Kacheln
    dorthin gewarpt und distanzgewichtet (feathered) zu einem breiteren Panorama geblendet.

    Parameter
    ---------
    images : Liste von ≥2 BGR/Grau-Bildern.
    points_per_pair : Liste von Einträgen ``(i, j, pts_i, pts_j)`` — Punktpaare, die Bild j
        auf Bild i abbilden (≥4 Paare je Eintrag). Es muss ein zusammenhängender Pfad zu
        Bild 0 existieren (typisch eine Kette 0–1, 1–2, 2–3 …).

    Rückgabe
    --------
    Panorama als BGR-uint8."""
    imgs = [_to8(im) for im in images]
    imgs = [im if im.ndim == 3 else cv2.cvtColor(im, cv2.COLOR_GRAY2BGR) for im in imgs]
    n = len(imgs)
    if n < 2:
        raise ValueError("mindestens 2 Bilder nötig")

    # paarweise Homographien H_{i<-j}: Punkte in j → Punkte in i
    pair_H = {}
    for i, j, pi, pj in points_per_pair:
        i, j = int(i), int(j)
        pa = np.asarray(pi, np.float32); pb = np.asarray(pj, np.float32)
        if len(pa) < 4 or len(pa) != len(pb):
            raise ValueError(f"Paar ({i},{j}): mindestens 4 zusammengehörige Punktpaare nötig")
        H, _ = cv2.findHomography(pb, pa, cv2.RANSAC, 5.0)
        if H is None:
            raise ValueError(f"Homographie für Paar ({i},{j}) nicht bestimmbar")
        pair_H[(i, j)] = H.astype(np.float64)
        pair_H[(j, i)] = np.linalg.inv(H).astype(np.float64)

    # Homographien aller Bilder in die Ebene von Bild 0 via BFS über den Paar-Graphen
    Hto0 = {0: np.eye(3)}
    adj = {}
    for (a, b) in pair_H:
        adj.setdefault(a, []).append(b)
    queue = [0]
    while queue:
        cur = queue.pop(0)
        for nb in adj.get(cur, []):
            if nb not in Hto0:
                Hto0[nb] = Hto0[cur] @ pair_H[(cur, nb)]
                queue.append(nb)
    if len(Hto0) != n:
        raise ValueError("nicht alle Bilder über Kontrollpunkte mit Bild 0 verbunden")

    # gemeinsame Leinwand bestimmen
    allc = []
    for k in range(n):
        h, w = imgs[k].shape[:2]
        cn = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        allc.append(cv2.perspectiveTransform(cn, Hto0[k].astype(np.float32)).reshape(-1, 2))
    allp = np.vstack(allc)
    xmin, ymin = np.floor(allp.min(0)).astype(int)
    xmax, ymax = np.ceil(allp.max(0)).astype(int)
    W, Hh = int(xmax - xmin), int(ymax - ymin)
    if W <= 0 or Hh <= 0 or W * Hh > 120_000_000:
        raise ValueError("ungültige Panorama-Größe (Punkte prüfen)")
    T = np.float64([[1, 0, -xmin], [0, 1, -ymin], [0, 0, 1]])

    acc = np.zeros((Hh, W, 3), np.float32)
    wacc = np.zeros((Hh, W), np.float32)
    for k in range(n):
        h, w = imgs[k].shape[:2]
        M = (T @ Hto0[k]).astype(np.float32)
        wimg = cv2.warpPerspective(imgs[k], M, (W, Hh))
        wm = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, Hh))
        dist = cv2.distanceTransform((wm > 0).astype(np.uint8), cv2.DIST_L2, 3)
        acc += wimg.astype(np.float32) * dist[..., None]
        wacc += dist
    valid = wacc > 1e-6
    out = np.zeros((Hh, W, 3), np.float32)
    out[valid] = acc[valid] / wacc[valid, None]
    log(f"    N-Bild-Kontrollpunkt-Stitch: {n} Bilder → {W}×{Hh}")
    return np.clip(out, 0, 255).astype(np.uint8)
