#!/usr/bin/env python3
"""
astro.py — Astro-Stacking-Modul für ForgePix (Siril-inspiriert, eigenständig).

ANDERER Algorithmus als Fokus-Stacking: Ziel = Rauschen senken (SNR), nicht Schärfentiefe.
Pipeline:
  1. (optional) Kalibrierung: Master-Dark abziehen, durch Master-Flat teilen.
  2. Registrierung: Frames per Phasenkorrelation aufs Referenzbild ausrichten (Translation,
     sub-pixel; robust für nachgeführte Aufnahmen). -> ausgerichtete Temp-Frames auf Platte.
  3. Stacking mit Rejection: average / median / sigma (Kappa-Sigma) / winsor / max.
     Zweistufig über die Platte gerechnet -> speicherschonend auch bei 100+ Frames.
  4. (optional) Auto-Stretch (asinh) fürs Anzeigen des linearen Ergebnisses.

Speicher: hält nie alle Frames gleichzeitig im RAM (anders als der Fokus-Stacker).
Reine OpenCV/NumPy-Abhängigkeiten.
"""
import os
import numpy as np
import cv2

from constants import RAW_EXTS

# OSC-Bayer-Muster (FITS BAYERPAT) -> OpenCV-Debayer-Code. Achtung: OpenCVs Bayer-Benennung ist
# ggü. der üblichen FITS-Konvention um eine Zeile/Spalte verschoben (bekannte Falle).
_BAYER2CV = {
    "RGGB": cv2.COLOR_BayerBG2BGR,
    "BGGR": cv2.COLOR_BayerRG2BGR,
    "GRBG": cv2.COLOR_BayerGB2BGR,
    "GBRG": cv2.COLOR_BayerGR2BGR,
}


def detect_bayer(d):
    """CFA-Muster selbst erkennen, wenn kein BAYERPAT im Header steht. Probiert alle 4 Muster,
    debayert einen zentralen Ausschnitt und wählt das mit den GERINGSTEN Farb-Artefakten
    (falsche Muster erzeugen starkes Farb-Zipper/Schachbrett). Default RGGB bei Fehler."""
    try:
        a = np.nan_to_num(np.asarray(d)).astype(np.float32)
        if a.ndim != 2:
            return "RGGB"
        mx = float(a.max()) or 1.0
        h, w = a.shape
        cy, cx = (h // 4) * 2, (w // 4) * 2        # zentriert, gerade Offsets (CFA-Phase wahren)
        s = min(400, (min(h, w) // 2) * 2)
        crop = a[cy:cy + s, cx:cx + s]
        raw16 = np.clip(crop / mx * 65535.0, 0, 65535).astype(np.uint16)
        best, best_score = "RGGB", None
        for pat, code in _BAYER2CV.items():
            bgr = cv2.cvtColor(raw16, code).astype(np.float32) / 65535.0
            chroma = bgr - bgr.mean(axis=2, keepdims=True)   # Farbabweichung vom Grau
            score = float(np.mean(np.abs(cv2.Laplacian(chroma, cv2.CV_32F))))
            if best_score is None or score < best_score:
                best, best_score = pat, score
        return best
    except Exception:
        return "RGGB"


def _read_float(path):
    """Bild als float32 [0..1] (BGR) lesen — TIFF/PNG/JPG/FITS; RAW via rawpy."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fit", ".fits", ".fts"):
        from astropy.io import fits
        with fits.open(path) as hdul:
            hdu = hdul[0]
            d = np.asarray(hdu.data).astype(np.float32)
            bayer = str(hdu.header.get("BAYERPAT", "")).strip().upper()
        if d.ndim == 3 and d.shape[0] in (3, 4):     # (C,H,W) -> (H,W,C)
            d = np.moveaxis(d[:3], 0, -1)
        # OSC-Kameras (z. B. Seestar/ASI) liefern Bayer-Rohdaten als 2D-FITS -> debayern = Farbe.
        # BAYERPAT aus dem Header, sonst SELBST erkennen (gegen Dateien ohne Header-Eintrag).
        if d.ndim == 2:
            if bayer not in _BAYER2CV:
                bayer = detect_bayer(d)
            if bayer in _BAYER2CV:
                mx = float(np.nanmax(d)) or 1.0
                raw16 = np.clip(np.nan_to_num(d) / mx * 65535.0, 0, 65535).astype(np.uint16)
                bgr = cv2.cvtColor(raw16, _BAYER2CV[bayer])      # -> BGR (Farbe!)
                return bgr.astype(np.float32) / 65535.0
        mx = float(np.nanmax(d)) if d.size else 1.0
        f = d / mx if mx > 1.5 else np.clip(d, 0, 1)  # ADU -> 0..1
        if f.ndim == 2:
            f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
        elif f.shape[2] == 3:
            f = cv2.cvtColor(f, cv2.COLOR_RGB2BGR)    # FITS = RGB -> BGR
        return np.nan_to_num(f)
    if ext in RAW_EXTS:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(output_bps=16, use_camera_wb=True, no_auto_bright=True,
                                  output_color=rawpy.ColorSpace.sRGB)
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR); maxv = 65535.0
    else:
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"Bild nicht lesbar: {path}")
        maxv = 65535.0 if img.dtype == np.uint16 else 255.0
    f = img.astype(np.float32) / maxv
    if f.ndim == 2:
        f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
    return f


def _master(paths):
    """Master-Frame (Median) aus mehreren Kalibrier-Frames, oder einzelnes Frame."""
    if isinstance(paths, str):
        return _read_float(paths)
    fs = [_read_float(p) for p in paths]
    return np.median(np.stack(fs), axis=0)


def calibrate(f, dark=None, flat=None):
    out = f
    if dark is not None:
        out = out - dark
    if flat is not None:
        fn = flat / (float(flat.mean()) + 1e-6)
        out = out / np.clip(fn, 0.2, None)
    return np.clip(out, 0, None)


def _gray(f):
    return f.mean(axis=2).astype(np.float32) if f.ndim == 3 else f.astype(np.float32)


def cosmetic_correct(f, strength=3.0):
    """Hot-/Cold-Pixel entfernen (kosmetische Korrektur): einzelne Ausreißer ggü. dem lokalen
    Median ersetzen. Beseitigt helle/dunkle Einzelpixel (Sensor-Defekte/Cosmics) ohne Sterne
    anzutasten. Klassisch, kein ML."""
    u16 = (np.clip(f, 0, 1) * 65535).astype(np.uint16)
    med = cv2.medianBlur(u16, 3).astype(np.float32) / 65535.0
    diff = f - med
    sigma = float(np.std(diff)) + 1e-6
    mask = np.abs(diff) > strength * sigma
    out = f.copy()
    out[mask] = med[mask]
    return out


def _star_centroids(g, max_stars=200):
    """Sternzentren (sub-pixel) als Punktwolke: Hintergrund abziehen, **rauschadaptive Schwelle
    (Median + 5·MAD)**, kleine helle Blobs als Sterne, nach Fläche sortiert.

    Wichtig: Otsu lieferte auf dünnen Astro-Frames nur eine Handvoll Sterne (zu strenge Schwelle),
    wodurch das Ausrichten zu wenig Stützpunkte hatte und Sterne im Stack verschmierten. Die
    MAD-Schwelle findet zuverlässig 100–200 Sterne — genug für robustes Offset-Voting + RANSAC."""
    a = (np.clip(g, 0, 1) * 255).astype(np.uint8)
    bg = cv2.medianBlur(a, 31)
    sub = cv2.subtract(a, bg).astype(np.float32)
    med = float(np.median(sub))
    mad = float(np.median(np.abs(sub - med))) * 1.4826 + 1e-6
    th = (sub > max(med + 5.0 * mad, 3.0)).astype(np.uint8) * 255
    n, _lbl, stats, cent = cv2.connectedComponentsWithStats(th, connectivity=8)
    stars = [(cent[i][0], cent[i][1], int(stats[i, cv2.CC_STAT_AREA]))
             for i in range(1, n) if 2 <= stats[i, cv2.CC_STAT_AREA] <= 600]
    stars.sort(key=lambda s: -s[2])
    return np.array([[s[0], s[1]] for s in stars[:max_stars]], np.float32)


def _coarse_offset_vote(ref_pts, img_pts, nbright=80, tol=2.5, min_votes=8):
    """Dominanten Versatz (ref − img) aus den hellsten Sternpaaren per Voting bestimmen.

    Robust gegen feste Hotpixel/Amp-Glow (die würden für Versatz (0,0) stimmen) und gegen
    fehlende/zusätzliche Sterne: der echte Sternversatz bekommt die meisten übereinstimmenden
    Stimmen. Ersetzt die Phasenkorrelation, die bei Astro-Frames auf dem festen Fixed-Pattern
    statt auf den (gewanderten) Sternen einrastet. Gibt (ox, oy) oder None."""
    if len(ref_pts) < min_votes or len(img_pts) < min_votes:
        return None
    R, I = ref_pts[:nbright], img_pts[:nbright]
    offs = (R[:, None, :] - I[None, :, :]).reshape(-1, 2)        # alle Paar-Versätze
    best, bestc = None, 0
    for o in offs:
        c = int((np.abs(offs - o).max(1) < tol).sum())          # Übereinstimmungen
        if c > bestc:
            bestc, best = c, o
    if bestc < min_votes:
        return None
    # Mittel der zustimmenden Versätze (sub-pixel-genauer als ein einzelner Paar-Versatz)
    near = offs[np.abs(offs - best).max(1) < tol]
    return near.mean(0)


def _estimate_star_transform(refg, img_g):
    """Translation + Feldrotation aus tatsächlichen STERNPOSITIONEN schätzen (genauer = rundere
    Sterne). Grober Versatz per Offset-Voting (robust gegen Hotpixel), dann Nearest-Neighbor-Match
    + RANSAC-Affine. Gibt 2x3-Matrix oder None (dann Fallback ORB)."""
    ref_pts, img_pts = _star_centroids(refg), _star_centroids(img_g)
    if len(ref_pts) < 8 or len(img_pts) < 8:
        return None
    off = _coarse_offset_vote(ref_pts, img_pts)
    if off is None:
        return None
    shifted = img_pts + off                                     # img ≈ in ref-Raster gebracht
    src, dst = [], []
    for rp in ref_pts:                                          # ref-Stern -> nächster img-Stern
        d = np.linalg.norm(shifted - rp, axis=1)
        j = int(np.argmin(d))
        if d[j] < 4.0:                                          # Toleranz in px (nach Grobversatz)
            src.append(img_pts[j]); dst.append(rp)
    if len(src) < 6:
        return None
    M, inl = cv2.estimateAffinePartial2D(np.array(src, np.float32), np.array(dst, np.float32),
                                         method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None or (inl is not None and int(inl.sum()) < 6):
        return None
    return M


def match_stars_triangles(ref_pts, img_pts, n_use=60, tol=0.02, min_matches=6):
    """A3 — Asterismus-/Dreiecks-Matching (astroalign-Prinzip): Sternkorrespondenzen OHNE jede
    Annahme über Translation, Skalierung, Rotation ODER Spiegelung finden.

    Idee: Aus den hellsten Sternen werden Dreiecke gebildet und je Dreieck ein **invarianter
    Deskriptor** aus zwei normierten Seitenverhältnissen berechnet (kürzeste/längste und
    mittlere/längste Seite). Diese beiden Zahlen ändern sich nicht unter Skalierung, Rotation oder
    Spiegelung — nur die Sterngeometrie zählt. Über einen cKDTree im 2D-Deskriptorraum werden
    Ref-Dreiecke ihren ähnlichsten Img-Dreiecken zugeordnet; jedes übereinstimmende Dreieck
    "stimmt" für seine drei Stern-zu-Stern-Paare ab. Die Paare mit den meisten Stimmen gewinnen.

    Dadurch greift das Matching auch bei großer Feldrotation, Mosaik-Überlappung oder gemischter
    Optik (unterschiedliche Brennweite/Spiegelung), wo das translationsbasierte Offset-Voting
    versagt.

    Args:
        ref_pts, img_pts: (N,2)-Punktwolken (x,y), z. B. aus `_star_centroids`.
        n_use: nur die hellsten/ersten N Sterne je Bild verwenden (Dreiecks-Zahl ~ N³).
        tol: Toleranz im Deskriptorraum (euklidisch über die zwei Seitenverhältnisse).
        min_matches: Mindestanzahl gevoteter Sternpaare, sonst (None, None).

    Returns:
        (src, dst) — zwei (M,2)-Arrays korrespondierender Punkte (img → ref), oder (None, None).
        scipy optional; ohne scipy Fallback auf eine NumPy-Nächste-Nachbar-Suche.
    """
    ref_pts = np.asarray(ref_pts, np.float32)
    img_pts = np.asarray(img_pts, np.float32)
    if len(ref_pts) < 3 or len(img_pts) < 3:
        return None, None
    R = ref_pts[:n_use]
    I = img_pts[:n_use]

    def _descriptors(pts):
        """Alle Dreiecke (Index-Tripel) → invariante Deskriptoren (2D). Verwirft sehr schmale
        (kollineare) Dreiecke als instabil."""
        m = len(pts)
        descs, tris = [], []
        from itertools import combinations
        for a, b, c in combinations(range(m), 3):
            pa, pb, pc = pts[a], pts[b], pts[c]
            s = sorted([
                (float(np.linalg.norm(pb - pc)), (a,)),     # Seite gegenüber a
                (float(np.linalg.norm(pa - pc)), (b,)),
                (float(np.linalg.norm(pa - pb)), (c,)),
            ])
            L = s[2][0]
            if L < 1e-3:
                continue
            r1 = s[0][0] / L                                # kürzeste / längste
            r2 = s[1][0] / L                                # mittlere / längste
            if r1 < 0.05 or (L - s[1][0]) < 1e-3:           # zu kollinear → instabil
                continue
            # Eckenreihenfolge nach gegenüberliegender Seitenlänge sortieren → spiegel-/rotations-
            # invariante, konsistente Zuordnung der drei Punkte.
            order = (s[0][1][0], s[1][1][0], s[2][1][0])
            descs.append((r1, r2))
            tris.append(order)
        return np.array(descs, np.float32), tris

    rd, rtris = _descriptors(R)
    idd, itris = _descriptors(I)
    if len(rd) == 0 or len(idd) == 0:
        return None, None

    # Nächste Img-Deskriptoren zu jedem Ref-Deskriptor suchen.
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(idd)
        dists, idxs = tree.query(rd, k=1)
    except Exception:
        dists = np.empty(len(rd), np.float32)
        idxs = np.empty(len(rd), np.int64)
        for j, d in enumerate(rd):
            dd = np.linalg.norm(idd - d, axis=1)
            k = int(np.argmin(dd))
            dists[j] = dd[k]; idxs[j] = k

    # Voting: jedes gut passende Dreieckspaar stimmt für seine drei Eck-Korrespondenzen.
    votes = {}
    for j, (dist, k) in enumerate(zip(dists, idxs)):
        if dist > tol:
            continue
        rt = rtris[j]; it = itris[int(k)]
        for ri, ii in zip(rt, it):                          # img-Index → ref-Index
            votes[(ii, ri)] = votes.get((ii, ri), 0) + 1

    if not votes:
        return None, None
    # Pro Img-Stern die ref-Zuordnung mit den meisten Stimmen wählen (1:1, gegenseitig-konsistent).
    best_for_img = {}
    for (ii, ri), c in votes.items():
        if ii not in best_for_img or c > best_for_img[ii][1]:
            best_for_img[ii] = (ri, c)
    used_ref = {}
    pairs = []
    for ii, (ri, c) in sorted(best_for_img.items(), key=lambda kv: -kv[1][1]):
        if c < 2:                                           # mind. 2 Dreiecke müssen es bestätigen
            continue
        if ri in used_ref:                                  # ref-Stern schon vergeben → überspringen
            continue
        used_ref[ri] = True
        pairs.append((ii, ri))
    if len(pairs) < min_matches:
        return None, None
    src = np.array([I[ii] for ii, _ in pairs], np.float32)
    dst = np.array([R[ri] for _, ri in pairs], np.float32)
    return src, dst


def _estimate_star_transform_robust(refg, img_g, full_affine=False):
    """A3 — robuste Stern-Transform über Dreiecks-Matching (translationsfrei).

    Schätzt die Abbildung img → ref allein aus der Sterngeometrie und funktioniert daher auch über
    große Feldrotation, Mosaik-Überlappung oder Mischoptik (Skalierung/Spiegelung), wo das
    bestehende, translationsannehmende Offset-Voting (`_estimate_star_transform`) aussteigt.

    Ablauf: Sternzentren beider Bilder → `match_stars_triangles` → RANSAC-Affine. `full_affine=True`
    erlaubt zusätzlich Skalierung/Scherung/Spiegelung (volle Affine), sonst Ähnlichkeits-Affine
    (Translation+Rotation+gleichmäßige Skalierung). Fallback auf das bestehende Offset-Voting,
    wenn das Dreiecks-Matching keine ausreichenden Korrespondenzen liefert. Gibt 2x3 oder None.
    """
    ref_pts = _star_centroids(refg)
    img_pts = _star_centroids(img_g)
    if len(ref_pts) >= 3 and len(img_pts) >= 3:
        src, dst = match_stars_triangles(ref_pts, img_pts)
        if src is not None and len(src) >= 3:
            if full_affine:
                M, inl = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC,
                                              ransacReprojThreshold=3.0)
            else:
                M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                     ransacReprojThreshold=3.0)
            if M is not None and (inl is None or int(inl.sum()) >= 3):
                return M.astype(np.float32)
    # Fallback: bestehendes translationsbasiertes Verfahren
    return _estimate_star_transform(refg, img_g)


def _estimate_rotation(refg, img_g, detector="ORB", min_inliers=25):
    """Partielle Affine (Translation + Rotation, kein Scherung) per ORB-Merkmalen schätzen —
    Fallback, wenn das stern-basierte Voting den Versatz nicht findet (z. B. großer Dither-Sprung
    in einen wenig überlappenden Bereich). Gibt 2x3-Matrix nur bei genügend Inliern zurück, sonst
    None — damit unsicher ausgerichtete Frames lieber verworfen als verschmiert gestackt werden."""
    a = (np.clip(refg, 0, 1) * 255).astype(np.uint8)
    b = (np.clip(img_g, 0, 1) * 255).astype(np.uint8)
    det = cv2.ORB_create(5000)
    ka, da = det.detectAndCompute(a, None)
    kb, db = det.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return None
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    m = sorted(bf.match(da, db), key=lambda x: x.distance)[:300]
    if len(m) < min_inliers:
        return None
    src = np.float32([kb[x.trainIdx].pt for x in m]).reshape(-1, 1, 2)
    dst = np.float32([ka[x.queryIdx].pt for x in m]).reshape(-1, 1, 2)
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    if M is None or inl is None or int(inl.sum()) < min_inliers:
        return None
    return M


def _compose_affine(A, B):
    """Zwei 2x3-Affinen verketten: Ergebnis bildet ab wie erst B, dann A (A∘B)."""
    A3 = np.vstack([A, [0, 0, 1]]); B3 = np.vstack([B, [0, 0, 1]])
    return (A3 @ B3)[:2].astype(np.float32)


def _tps_refine(fw, refg_out, max_ctrl=150, min_resid=0.5, log=print):
    """Lokale (nicht-rigide) Feinregistrierung per Thin-Plate-Spline gegen RESTVERZEICHNUNG —
    Feldkrümmung bei Weitwinkel/Refraktor, atmosphärische Refraktion, leichtes Tilt. Nach der
    globalen Affin-Ausrichtung bleibende Restversätze der Sterne werden als glattes Warp-Feld
    herausgerechnet (Sterne werden über das ganze Feld rund). Nur aktiv, wenn genug Sternpaare
    mit echtem Restversatz da sind — sonst bleibt der Frame unverändert (kein Verschlimmbessern)."""
    try:
        from scipy.interpolate import RBFInterpolator
    except Exception:
        return fw
    fg = _gray(fw)
    rp = _star_centroids(refg_out, max_stars=max_ctrl)
    ip = _star_centroids(fg, max_stars=max_ctrl * 3)
    if len(rp) < 12 or len(ip) < 12:
        return fw
    src, dst = [], []
    for r in rp:                                            # ref-Pos -> nächste Frame-Pos
        d = np.linalg.norm(ip - r, axis=1)
        j = int(np.argmin(d))
        if d[j] < 6.0:
            dst.append(r); src.append(ip[j])
    if len(src) < 12:
        return fw
    src = np.array(src, np.float32); dst = np.array(dst, np.float32)
    resid = np.linalg.norm(src - dst, axis=1)
    if float(np.median(resid)) < min_resid:
        return fw                                           # global schon sauber → nichts zu tun
    h, w = fg.shape[:2]
    try:
        rbf = RBFInterpolator(dst, src, kernel="thin_plate_spline", smoothing=1.0)
        gs = 48                                             # grobes Gitter, TPS ist glatt → hochskalieren
        gx, gy = np.meshgrid(np.linspace(0, w - 1, gs), np.linspace(0, h - 1, gs))
        q = np.stack([gx.ravel(), gy.ravel()], 1)
        mapped = rbf(q).reshape(gs, gs, 2).astype(np.float32)
        mapx = cv2.resize(mapped[..., 0], (w, h))
        mapy = cv2.resize(mapped[..., 1], (w, h))
        out = cv2.remap(fw, mapx, mapy, interpolation=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
        log(f"      TPS-Feinregistrierung: {len(src)} Sterne, Rest {float(np.median(resid)):.2f}px")
        return out
    except Exception:
        return fw


def _warp_and_save(f, M, out_size, op, drizzle, tps_refg=None):
    if M is not None:
        if drizzle > 1:
            M = M.copy(); M[:, 2] *= drizzle
        f = cv2.warpAffine(f, M, out_size, flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
    elif drizzle > 1:
        f = cv2.resize(f, out_size, interpolation=cv2.INTER_LANCZOS4)
    if tps_refg is not None:
        f = _tps_refine(f, tps_refg, log=lambda *a: None)
    cv2.imwrite(op, np.clip(f * 65535, 0, 65535).astype(np.uint16),
                [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
    return op


def register_and_cache(paths, out_dir, dark=None, flat=None, do_register=True,
                       align_mode="shift", cosmetic=False, drizzle=1, detector="ORB",
                       tps=False, log=print):
    """Frames kalibrieren + ausrichten, als 16-bit-TIFF in out_dir ablegen.

    align_mode: 'shift'/'rotate' (stern-basiert; phaseCorrelate wird bewusst NICHT genutzt — rastet
                bei Astro auf dem festen Fixed-Pattern statt auf den gewanderten Sternen ein).
    cosmetic:   Hot-/Cold-Pixel vor dem Ausrichten entfernen.
    drizzle:    Ausgabe-Hochskalierung (1=aus, 2=doppelte Kantenlänge, „Drizzle-lite").

    Parallel über alle Kerne (OpenCV gibt den GIL frei). Frames, die sich nicht an die Referenz
    ausrichten lassen (großer Dither-Sprung), werden in einem 2. Pass über eine Cluster-Brücke
    zurückgeholt statt verworfen. Gibt die Liste der ausgerichteten Pfade zurück."""
    from parallel import pmap
    os.makedirs(out_dir, exist_ok=True)
    drizzle = max(1, int(drizzle))
    ref = calibrate(_read_float(paths[len(paths) // 2]), dark, flat)
    if cosmetic:
        ref = cosmetic_correct(ref)
    refg = _gray(ref)
    out_size = (ref.shape[1] * drizzle, ref.shape[0] * drizzle)
    tps_refg = (cv2.resize(refg, out_size) if drizzle > 1 else refg) if tps else None
    if tps:
        log("    TPS-Feinregistrierung aktiv (lokale Restverzeichnung wird korrigiert)")

    def _prep(i):
        f = calibrate(_read_float(paths[i]), dark, flat)
        if f.shape[:2] != ref.shape[:2]:
            f = cv2.resize(f, (ref.shape[1], ref.shape[0]))
        if cosmetic:
            f = cosmetic_correct(f)
        return f

    def _one(i):
        f = _prep(i)
        op = os.path.join(out_dir, f"reg_{i:04d}.tif")
        if not do_register:
            return (i, _warp_and_save(f, None, out_size, op, drizzle))
        fg = _gray(f)
        M = _estimate_star_transform(refg, fg)
        if M is None:
            M = _estimate_rotation(refg, fg, detector)
        if M is None:
            return (i, None)                                 # 2. Pass versucht Cluster-Brücke
        return (i, _warp_and_save(f, M, out_size, op, drizzle, tps_refg))

    results = pmap(_one, list(range(len(paths))), memory_heavy=True)
    aligned = [op for _i, op in sorted(results) if op]
    skipped = [i for i, op in sorted(results) if op is None]
    log(f"    registriert {len(aligned)}/{len(paths)} (Pass 1)")

    # ---- Pass 2: weit weggeditherte Frames über eine Cluster-Brücke zurückholen ----
    # Sub-Referenz im Cluster wählen → per ORB an die Hauptreferenz brücken → jeden Frame an die
    # Sub-Referenz ausrichten und die Transforms verketten. JEDER zurückgeholte Frame wird verifiziert
    # (seine Sterne müssen nach der Transformation gut auf die Referenz fallen), sonst bleibt er außen
    # vor — so kann eine schwache Brücke kein Verschmieren zurückbringen.
    if do_register and len(skipped) >= 3:
        ref_pts = _star_centroids(refg)
        grays = {i: _gray(_prep(i)) for i in skipped}
        subref = max(skipped, key=lambda i: len(_star_centroids(grays[i])))
        bridge = _estimate_rotation(refg, grays[subref], detector, min_inliers=10)  # subref -> ref
        rescued = 0
        if bridge is not None and len(ref_pts) >= 8:
            for i in skipped:
                S = (np.float32([[1, 0, 0], [0, 1, 0]]) if i == subref
                     else _estimate_star_transform(grays[subref], grays[i]))   # frame -> subref
                if S is None:
                    continue
                M = _compose_affine(bridge, S)               # frame -> subref -> ref
                # Verifizieren: Sterne des Frames mit M ins Ref-Raster bringen, gute Treffer zählen
                ip = _star_centroids(grays[i])
                if len(ip) < 8:
                    continue
                ext = np.hstack([ip, np.ones((len(ip), 1), np.float32)])
                tp = (M @ ext.T).T
                good = sum(1 for r in ref_pts if np.min(np.linalg.norm(tp - r, axis=1)) < 1.5)
                if good < 25:                                # zu wenige saubere Treffer → lieber lassen
                    continue
                op = os.path.join(out_dir, f"reg_{i:04d}.tif")
                aligned.append(_warp_and_save(_prep(i), M, out_size, op, drizzle, tps_refg))
                rescued += 1
        if rescued:
            log(f"    +{rescued} weit geditherte Frames über Cluster-Brücke zurückgeholt ({len(aligned)}/{len(paths)})")
    return aligned


def drizzle_stack(paths, scale=2, pixfrac=0.7, dark=None, flat=None, cosmetic=False,
                  detector="ORB", log=print):
    """ECHTES Drizzle (Variable-Pixel Linear Reconstruction, Fruchter & Hook — Punktkernel,
    inverse Formulierung). Anders als „Drizzle-lite“ (jeden Frame einzeln hochskalieren und mitteln,
    was die Interpolation verschmiert) wird hier das Resampling AUFGESCHOBEN: jeder Roh-Frame wird
    über seine Sub-Pixel-Registrierung mit einem geschrumpften „Drop“ (pixfrac) direkt auf das feine
    Ausgabegitter getropft, Fluss UND Gewicht akkumuliert. Aus geditherten Subs entsteht so echte
    Auflösungsrückgewinnung (kleinere, schärfere Sterne) statt nur Hochskalierung.

    scale: Gitter-Faktor (2 = doppelte Kantenlänge). pixfrac: Drop-Größe 0.1..1 (kleiner = schärfer,
    braucht aber mehr Frames für volle Abdeckung; 0.7 ist ein guter Kompromiss)."""
    scale = int(max(2, scale))
    pf = float(np.clip(pixfrac, 0.1, 1.0))
    ref = calibrate(_read_float(paths[len(paths) // 2]), dark, flat)
    if cosmetic:
        ref = cosmetic_correct(ref)
    refg = _gray(ref)
    H, W = ref.shape[:2]
    ch = ref.shape[2] if ref.ndim == 3 else 1
    OH, OW = H * scale, W * scale
    flux = np.zeros((OH, OW, ch), np.float32)
    wsum = np.zeros((OH, OW), np.float32)
    yy, xx = np.mgrid[0:OH, 0:OW].astype(np.float32)
    used = 0
    for k, p in enumerate(paths):
        f = calibrate(_read_float(p), dark, flat)
        if f.shape[:2] != (H, W):
            f = cv2.resize(f, (W, H))
        if cosmetic:
            f = cosmetic_correct(f)
        if f.ndim == 2:
            f = f[..., None]
        fg = _gray(f)
        M = _estimate_star_transform(refg, fg)
        if M is None:
            M = _estimate_rotation(refg, fg, detector)
        if M is None:
            continue
        Ms = (scale * M).astype(np.float32)              # frame -> Ausgabegitter
        Minv = cv2.invertAffineTransform(Ms)             # Ausgabegitter -> frame
        xs = Minv[0, 0] * xx + Minv[0, 1] * yy + Minv[0, 2]
        ys = Minv[1, 0] * xx + Minv[1, 1] * yy + Minv[1, 2]
        rx = np.round(xs); ry = np.round(ys)
        inb = (rx >= 0) & (rx < W) & (ry >= 0) & (ry < H)
        wgt = ((np.abs(xs - rx) <= pf / 2) & (np.abs(ys - ry) <= pf / 2) & inb).astype(np.float32)
        val = cv2.remap(f, xs, ys, interpolation=cv2.INTER_NEAREST,
                        borderMode=cv2.BORDER_CONSTANT)
        if val.ndim == 2:
            val = val[..., None]
        flux += val * wgt[..., None]
        wsum += wgt
        used += 1
        log(f"    Drizzle {used}/{len(paths)} (pixfrac {pf:.2f}, {scale}×)")
    if used == 0:
        raise RuntimeError("Drizzle: kein Frame ausrichtbar")
    out = flux / np.clip(wsum[..., None], 1e-6, None)
    holes = wsum < 1e-6
    if holes.any():                                       # nie getroffene Pixel sanft füllen
        u8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
        filled = cv2.inpaint(u8, holes.astype(np.uint8), 3, cv2.INPAINT_TELEA)
        out[holes] = filled[holes].astype(np.float32) / 255.0
        log(f"    Drizzle: {int(holes.sum())} unbedeckte Pixel gefüllt (mehr Frames/größeres pixfrac hilft)")
    return np.clip(out, 0, 1)


def _bg_sigma(f):
    """A4 — robuste Hintergrund-Streuung σ_bg eines Frames (für die SNR-Gewichtung).

    Schätzt das Rauschen NUR aus dem Himmelshintergrund (untere ~80 % der Helligkeit), damit helle
    Sterne/Nebel den Wert nicht aufblähen: σ = 1.4826·MAD der Pixel unterhalb des 80%-Quantils.
    Kleines σ ⇒ rauscharmer/transparenter Frame ⇒ höheres Gewicht."""
    g = _gray(f).ravel()
    thr = float(np.quantile(g, 0.80))
    bgvals = g[g <= thr]
    if bgvals.size < 16:
        bgvals = g
    med = float(np.median(bgvals))
    mad = float(np.median(np.abs(bgvals - med))) * 1.4826
    return max(mad, 1e-5)


def stack(paths, method="sigma", kappa=2.5, normalize=True, local_norm=False,
          weight=False, sigma_iters=2, log=print, preview_cb=None):
    """Speicherschonendes Stacken über die Platte (zweistufig bei sigma/winsor).
    Gibt float32-Ergebnis [0..1] (BGR) zurück.

    A4 — `weight=True`: jeder Frame geht mit Gewicht 1/σ_bg² ein (σ_bg = robuste Hintergrund-
    Streuung, s. `_bg_sigma`). Rauschärmere/transparentere Subs zählen mehr → besseres SNR bei
    gemischter Transparenz (Dunst, Mond). Bei `average`/`winsor`/`sigma` voll wirksam; `median`/
    `max` sind ihrer Natur nach ungewichtet (Gewicht wird dort ignoriert).

    A4 — `sigma_iters` (nur method='sigma'): die Sigma-Schwellen 1–2× nachschätzen — nach jeder
    Rejection werden Mittel/σ aus den ÜBRIG gebliebenen (geclippten) Werten neu berechnet, sodass
    die Schwelle nicht von den Ausreißern selbst verzerrt bleibt. 1 = altes Einpass-Verhalten.

    Defaults (weight=False, sigma_iters=2) sind sicher: sigma_iters=2 ist eine reine
    Genauigkeitsverbesserung des bisherigen Sigma-Clippings; weight=False erhält exakt das alte
    ungewichtete Mittel.

    preview_cb(img01_bgr, i, n): optionaler Callback für die Live-Vorschau — wird während des
    Stackens periodisch mit dem laufenden (Teil-)Ergebnis aufgerufen."""
    if not paths:
        raise RuntimeError("keine Frames zum Stacken")
    n = len(paths)
    _pv_every = max(1, n // 12)              # ~12 Vorschau-Updates über den Lauf
    first = _read_float(paths[0])
    shape = first.shape

    # additive Normalisierung: Hintergrund (Median) je Frame angleichen
    offs = np.zeros(n, np.float32)
    if normalize:
        meds = [float(np.median(_read_float(p))) for p in paths]
        gm = float(np.median(meds))
        offs = np.array([gm - m for m in meds], np.float32)
    # lokale Normalisierung: örtliche Hintergrund-Fläche statt nur Skalar (gegen Gradienten)
    ref_surf = _bg_surface(first) if (normalize and local_norm) else None
    if ref_surf is not None:
        log("    lokale Normalisierung aktiv (örtlicher Hintergrundabgleich)")

    def rd(i, p):
        f = _read_float(p)
        if ref_surf is not None:
            return local_normalize(f, ref_surf)
        return f + offs[i]

    # A4 — Per-Frame-SNR-Gewichte (1/σ_bg²), robust normiert auf Mittel 1. Bei weight=False alle 1.
    w = np.ones(n, np.float32)
    if weight and method in ("average", "winsor", "sigma"):
        sig = np.array([_bg_sigma(rd(i, p)) for i, p in enumerate(paths)], np.float32)
        w = 1.0 / (sig * sig)
        w *= n / float(w.sum())                          # Mittel 1 → Skala/Helligkeit unverändert
        log(f"    SNR-Gewichtung aktiv (Gewichte {np.round(w.min(),2)}..{np.round(w.max(),2)})")

    if method in ("average", "median", "max"):
        if method == "median":
            # Median braucht alle Werte -> in Kacheln über die Höhe, speicherschonend
            res = np.empty(shape, np.float32)
            rows = max(1, 2_000_000 // (shape[1] * shape[2]))  # ~Zeilen pro Kachel
            for y in range(0, shape[0], rows):
                band = np.stack([_read_float(p)[y:y + rows] + offs[i]
                                 for i, p in enumerate(paths)])
                res[y:y + rows] = np.median(band, axis=0)
                log(f"    median Zeilen {y}/{shape[0]}")
            return np.clip(res, 0, 1)
        acc = np.zeros(shape, np.float32) if method == "average" else None
        wacc = 0.0
        mx = np.zeros(shape, np.float32) if method == "max" else None
        for i, p in enumerate(paths):
            f = rd(i, p)
            if method == "average":
                acc += f * w[i]; wacc += w[i]            # gewichtetes Mittel (w[i]=1 → altes Mittel)
            else:
                mx = np.maximum(mx, f)
            log(f"    {method} {i + 1}/{n}")
            if preview_cb and (i % _pv_every == 0 or i == n - 1):
                preview_cb(np.clip((acc / max(wacc, 1e-6)) if method == "average" else mx, 0, 1),
                           i + 1, n)
        return np.clip(acc / max(wacc, 1e-6) if method == "average" else mx, 0, 1)

    if method == "linearfit":
        # Linear-Fit-Clipping (PixInsight-Stil): pro Pixel die sortierten Werte über die Frames
        # mit einer Geraden modellieren, Streuung der Residuen messen, Ausreißer (Satelliten,
        # Flugzeuge, kosmische Treffer, Hotpixel) jenseits kappa·sigma verwerfen. Robuster als
        # Sigma-Clipping bei WENIGEN Subs und systematisch ungleicher Transparenz/Helligkeit.
        res = np.empty(shape, np.float32)
        rows = max(1, 2_000_000 // (shape[1] * shape[2]))
        x = np.arange(n, dtype=np.float32)
        xm = x.mean(); xv = float(((x - xm) ** 2).sum()) + 1e-9
        for y in range(0, shape[0], rows):
            band = np.stack([rd(i, p)[y:y + rows] for i, p in enumerate(paths)])  # (n, r, w, c)
            v = np.sort(band, axis=0)
            mask = np.ones_like(v, dtype=bool)
            for _ in range(2):                       # 2 Iterationen reichen praktisch
                w_ = mask.astype(np.float32)
                sw = np.clip(w_.sum(axis=0), 1.0, None)
                ym = (v * w_).sum(axis=0) / sw
                slope = ((x[:, None, None, None] - xm) * (v - ym) * w_).sum(axis=0) / xv
                fit = slope * (x[:, None, None, None] - xm) + ym
                resid = v - fit
                sig = np.sqrt((resid * resid * w_).sum(axis=0) / sw) + 1e-9
                mask = np.abs(resid) <= kappa * sig
            w_ = mask.astype(np.float32)
            res[y:y + rows] = (v * w_).sum(axis=0) / np.clip(w_.sum(axis=0), 1.0, None)
            log(f"    linearfit-Rejection Zeilen {y}/{shape[0]}")
        return np.clip(res, 0, 1)

    # sigma / winsor: Pass 1 Mittel+Std, Pass 2 Rejection
    s = np.zeros(shape, np.float32); s2 = np.zeros(shape, np.float32)
    for i, p in enumerate(paths):
        f = rd(i, p)
        s += f; s2 += f * f
        log(f"    Statistik {i + 1}/{n}")
    mean = s / n
    std = np.sqrt(np.maximum(s2 / n - mean * mean, 0))
    lo = mean - kappa * std; hi = mean + kappa * std

    if method == "sigma":
        # A4 — iteratives Sigma: Schwellen 1–2× aus den GECLIPPTEN Werten nachschätzen, damit die
        # Ausreißer die Schwelle nicht selbst verzerren. extra_iters = sigma_iters−1 Nachpässe.
        for _ in range(max(0, int(sigma_iters) - 1)):
            s = np.zeros(shape, np.float32); s2 = np.zeros(shape, np.float32)
            cnt = np.zeros(shape, np.float32)
            for i, p in enumerate(paths):
                f = rd(i, p)
                m = ((f >= lo) & (f <= hi)).astype(np.float32)
                s += f * m; s2 += f * f * m; cnt += m
            cn = np.clip(cnt, 1.0, None)
            mean = s / cn
            std = np.sqrt(np.maximum(s2 / cn - mean * mean, 0))
            lo = mean - kappa * std; hi = mean + kappa * std

    acc = np.zeros(shape, np.float32); cnt = np.zeros(shape, np.float32)
    for i, p in enumerate(paths):
        f = rd(i, p)
        if method == "winsor":
            f = np.clip(f, lo, hi)
            acc += f * w[i]; cnt += w[i]                 # gewichtet (w[i]=1 → altes Verhalten)
        else:  # sigma: Ausreißer verwerfen
            m = (f >= lo) & (f <= hi)
            acc += np.where(m, f * w[i], 0); cnt += m * w[i]
        log(f"    {method}-Rejection {i + 1}/{n}")
        if preview_cb and (i % _pv_every == 0 or i == n - 1):
            preview_cb(np.clip(acc / np.clip(cnt, 1e-6, None), 0, 1), i + 1, n)
    return np.clip(acc / np.clip(cnt, 1e-6, None), 0, 1)


def bin_image(f, factor=2):
    """Software-Binning: factor×factor-Blöcke mitteln → halbe (bei 2×) Auflösung, aber höheres
    Signal-Rausch-Verhältnis und kleinere/rundere Sterne. Sinnvoll bei überabgetasteten Daten
    (FWHM ≫ 2 px). factor=1 → unverändert."""
    factor = max(1, int(factor))
    if factor == 1 or f is None:
        return f
    h, w = f.shape[:2]
    h2, w2 = (h // factor) * factor, (w // factor) * factor
    f = f[:h2, :w2]
    if f.ndim == 3:
        f = f.reshape(h2 // factor, factor, w2 // factor, factor, f.shape[2]).mean(axis=(1, 3))
    else:
        f = f.reshape(h2 // factor, factor, w2 // factor, factor).mean(axis=(1, 3))
    return f.astype(np.float32)


def background_extract(f, strength=0.12, method="rbf", grid=12, log=print):
    """Hintergrund-/Gradienten-Entfernung (Lichtverschmutzung, Vignette).

    method='rbf' (Standard, DBE/GraXpert-Prinzip): das Bild kacheln, pro Kachel einen ROBUSTEN
    Sky-Wert (unteres Perzentil) als Stützpunkt nehmen, Stützpunkte verwerfen, die deutlich über dem
    Feld-Trend liegen (= echte Großstruktur/Nebel → NICHT mitmodellieren), dann eine glatte
    Thin-Plate-Spline-Fläche durch die verbliebenen Punkte legen und abziehen. Anders als ein
    Tiefpass-Blur folgt das NICHT dem ausgedehnten Nebel und frisst ihn daher nicht weg.
    method='blur': der alte einfache Tiefpass (Fallback, wenn scipy fehlt)."""
    if method == "rbf":
        try:
            from scipy.interpolate import RBFInterpolator
            g = _gray(f)
            H, W = g.shape[:2]
            ys = np.linspace(H * 0.06, H * 0.94, grid)
            xs = np.linspace(W * 0.06, W * 0.94, grid)
            pts, vals = [], []
            bh, bw = int(H / grid / 2), int(W / grid / 2)
            for y in ys:
                for x in xs:
                    yi, xi = int(y), int(x)
                    tile = g[max(0, yi - bh):yi + bh, max(0, xi - bw):xi + bw]
                    if tile.size:
                        pts.append((x, y)); vals.append(float(np.percentile(tile, 25)))
            pts = np.array(pts, np.float32); vals = np.array(vals, np.float32)
            med = float(np.median(vals)); mad = float(np.median(np.abs(vals - med))) * 1.4826 + 1e-6
            keep = vals <= med + 2.5 * mad                  # Nebel-/Struktur-Stützpunkte verwerfen
            if keep.sum() >= max(8, grid):
                rbf = RBFInterpolator(pts[keep], vals[keep], kernel="thin_plate_spline", smoothing=1.0)
                gy, gx = np.mgrid[0:H, 0:W]
                surf = rbf(np.stack([gx.ravel(), gy.ravel()], 1)).reshape(H, W).astype(np.float32)
                surf = surf[..., None] if f.ndim == 3 else surf
                out = f - surf + float(np.median(surf))
                log(f"    Hintergrund (RBF/DBE-Stil): {int(keep.sum())} Sky-Stützpunkte, Nebel geschützt")
                return np.clip(out, 0, 1)
        except Exception as e:
            log(f"    Hintergrund: RBF nicht verfügbar ({e}) → Tiefpass")
    u16 = (np.clip(f, 0, 1) * 65535).astype(np.uint16)
    star_suppressed = cv2.medianBlur(u16, 5).astype(np.float32) / 65535.0
    sigma = max(8.0, min(f.shape[0], f.shape[1]) * strength / 3.0)
    bg = cv2.GaussianBlur(star_suppressed, (0, 0), sigma)
    out = f - bg + float(np.median(bg))
    return np.clip(out, 0, 1)


def estimate_psf(f, size=21, max_stars=80):
    """PSF (Punktspreizfunktion) EMPIRISCH aus dem Bild schätzen: viele kleine, ungesättigte Sterne
    finden, je ein size×size-Fenster um den Stern ausschneiden, alle (auf das Maximum zentriert)
    mitteln → die mittlere Sternform = die PSF (Seeing/Optik/Nachführung). Normalisiert (Summe 1).
    Fallback auf eine schmale Gauss-PSF, wenn zu wenige saubere Sterne da sind."""
    g = _gray(f)
    g = g / (float(g.max()) + 1e-6)
    pts = _star_centroids(g, max_stars=max_stars * 3)
    h, w = g.shape[:2]
    half = size // 2
    acc = np.zeros((size, size), np.float32)
    n = 0
    for x, y in pts:
        xi, yi = int(round(x)), int(round(y))
        if half < xi < w - half and half < yi < h - half:
            patch = g[yi - half:yi + half + 1, xi - half:xi + half + 1].astype(np.float32)
            peak = float(patch.max())
            if 0.05 < peak < 0.9:                       # ungesättigt, über Rauschen
                patch = patch - float(np.median(patch))  # lokalen Hintergrund abziehen
                patch = np.clip(patch, 0, None)
                s = float(patch.sum())
                if s > 1e-6:
                    acc += patch / s
                    n += 1
        if n >= max_stars:
            break
    if n < 8:
        psf = cv2.getGaussianKernel(size, size / 6.0)
        psf = psf @ psf.T
        return (psf / psf.sum()).astype(np.float32)
    acc = cv2.GaussianBlur(acc, (3, 3), 0)              # leicht glätten gegen Rausch-PSF
    return (acc / (acc.sum() + 1e-9)).astype(np.float32)


def _tv_step(est, weight):
    """A5 — ein Total-Variation-Regularisierungsschritt: dämpft das aktuelle RL-Estimate leicht in
    Richtung seiner kantenerhaltenden, geglätteten Version. weight∈[0,1] mischt Original↔geglättet.
    Kantenerhaltend via bilateralem Filter (fällt auf Gauss zurück, falls nicht verfügbar)."""
    if weight <= 0:
        return est
    e = est.astype(np.float32)
    mx = float(e.max()) or 1.0
    try:
        sm = cv2.bilateralFilter((e / mx).astype(np.float32), d=5,
                                 sigmaColor=0.05, sigmaSpace=3.0) * mx
    except Exception:
        sm = cv2.GaussianBlur(e, (0, 0), 1.0)
    return (1.0 - weight) * e + weight * sm


def _rl_deconv(obs, psf, iterations, regularize=0.0, support=None):
    """Kern-Richardson-Lucy auf einem Graukanal (FFT-frei). Optional pro Iteration ein TV-Schritt
    (`regularize`) und eine Support-Maske (`support`, 0..1), die die multiplikative Korrektur lokal
    in Richtung 1 dämpft (Deringing in flachen Bereichen)."""
    psf = (psf / (psf.sum() + 1e-9)).astype(np.float32)
    psf_m = psf[::-1, ::-1].copy()
    obs = np.clip(obs, 1e-4, None)
    est = obs.copy()
    for _ in range(max(1, int(iterations))):
        conv = cv2.filter2D(est, -1, psf, borderType=cv2.BORDER_REFLECT)
        relative = obs / np.maximum(conv, 1e-6)
        corr = cv2.filter2D(relative, -1, psf_m, borderType=cv2.BORDER_REFLECT)
        if support is not None:
            corr = 1.0 + support * (corr - 1.0)          # außerhalb des Supports → kaum Korrektur
        est = np.clip(est * corr, 0, None)
        if regularize > 0:
            est = _tv_step(est, float(np.clip(regularize, 0, 1)))
    return est


def _detail_support(lum, thresh=2.5):
    """A5 — Support-/Detailmaske aus à-trous-artigen Detailebenen: Pixel mit echter Struktur (Sterne,
    Kanten, Nebel-Detail) bekommen 1, flacher Hintergrund ~0. Dort darf RL schärfen, im Flachen wird
    gedämpft → keine Ringe/verstärktes Rauschen in leeren Bereichen."""
    g = lum.astype(np.float32)
    detail = np.zeros_like(g)
    cur = g
    for s in (1.0, 2.0, 4.0):                             # mehrere Skalen aufsummieren
        blur = cv2.GaussianBlur(g, (0, 0), s)
        detail = np.maximum(detail, np.abs(cur - blur))
        cur = blur
    med = float(np.median(detail))
    mad = float(np.median(np.abs(detail - med))) * 1.4826 + 1e-6
    sup = np.clip((detail - med) / (thresh * mad), 0, 1).astype(np.float32)
    return cv2.GaussianBlur(sup, (0, 0), 2.0)            # weiche Ränder gegen Maskenkanten


def deconvolve(f, psf=None, iterations=15, star_protect=0.85, regularize=0.0,
               deringing=True, tiled_psf=False, tiles=3, log=print):
    """Dekonvolution (PixInsight/Deconvolution-Stil) — schärft echtes Detail zurück, das Seeing/Optik
    verschmiert haben. Richardson-Lucy (für Poisson-Statistik korrekt) auf der LUMINANZ, mit aus den
    Sternen geschätzter PSF (oder übergebener PSF). Wirkt auf LINEARE Daten (vor dem Strecken).

    A5 — `regularize` (0..1): Total-Variation-Regularisierung pro Iteration. RL verstärkt mit jeder
    Iteration auch Rauschen und neigt zu Ringeln; ein leichter kantenerhaltender Glättungsschritt je
    Iteration dämpft das, ohne echte Kanten zu verlieren (0 = aus, 0.05–0.2 typisch).

    A5 — `deringing` (Default True): eine Support-/Detailmaske aus den Detailebenen begrenzt die
    RL-Korrektur auf strukturierte Bereiche. In flachem Hintergrund (wo Ringe & Rauschverstärkung
    entstehen) wird die Korrektur lokal Richtung neutral gedämpft.

    A5 — `tiled_psf` (Default False): ortsabhängige PSF. Das Feld wird in `tiles`×`tiles` Kacheln
    geteilt, je Kachel aus den DORTIGEN Sternen eine eigene PSF geschätzt und separat dekonvolviert
    (mit Überlappung weich zusammengeblendet). Fängt über das Feld variierendes Seeing/Koma/Tilt ab.
    Fällt auf eine globale PSF zurück, wo eine Kachel zu wenige Sterne hat.

    Wichtig — Stern-Schutz: RL erzeugt an hellen, gesättigten Sternkernen gern dunkle Ringe/Übersch-
    winger. `star_protect` (Helligkeitsschwelle 0..1) blendet die hellsten Bereiche weich aufs Original
    zurück → schärferes Nebeldetail OHNE Ring-Artefakte um Sterne. Reine OpenCV/NumPy (FFT-frei)."""
    if f is None:
        return f
    lum = _gray(f).astype(np.float32)
    obs = np.clip(lum, 1e-4, None)
    support = _detail_support(lum) if deringing else None

    if tiled_psf:
        H, W = lum.shape[:2]
        nt = max(1, int(tiles))
        est = np.zeros_like(obs)
        wsum = np.zeros_like(obs)
        ov = 0.25                                        # 25 % Überlappung der Kacheln
        gpsf = psf if psf is not None else estimate_psf(f)
        ys = np.linspace(0, H, nt + 1).astype(int)
        xs = np.linspace(0, W, nt + 1).astype(int)
        for ti in range(nt):
            for tj in range(nt):
                y0, y1 = ys[ti], ys[ti + 1]
                x0, x1 = xs[tj], xs[tj + 1]
                py = int((y1 - y0) * ov); px = int((x1 - x0) * ov)
                ay0, ay1 = max(0, y0 - py), min(H, y1 + py)
                ax0, ax1 = max(0, x0 - px), min(W, x1 + px)
                sub = f[ay0:ay1, ax0:ax1]
                try:
                    lpsf = estimate_psf(sub)
                except Exception:
                    lpsf = gpsf
                if lpsf is None:
                    lpsf = gpsf
                sup = support[ay0:ay1, ax0:ax1] if support is not None else None
                tile_est = _rl_deconv(np.clip(_gray(sub), 1e-4, None), lpsf, iterations,
                                      regularize, sup)
                wmask = np.ones_like(tile_est, np.float32)  # weiche Kachelränder
                wmask = cv2.GaussianBlur(wmask, (0, 0), max(2.0, min(wmask.shape) / 8.0))
                est[ay0:ay1, ax0:ax1] += tile_est * wmask
                wsum[ay0:ay1, ax0:ax1] += wmask
        est = est / np.clip(wsum, 1e-6, None)
    else:
        if psf is None:
            psf = estimate_psf(f)
        est = _rl_deconv(obs, psf, iterations, regularize, support)

    # Schärfungs-Verhältnis auf die Farbkanäle übertragen (Farbe bleibt erhalten)
    ratio = est / np.maximum(lum, 1e-4)
    ratio = np.clip(ratio, 0.3, 3.0)
    out = f.astype(np.float32) * ratio[..., None] if f.ndim == 3 else f.astype(np.float32) * ratio
    # Stern-Schutz: in den hellsten Zonen weich aufs Original zurückblenden (gegen RL-Ringe)
    if star_protect is not None and star_protect < 1.0:
        hi = np.clip((lum - star_protect) / max(1e-3, 1.0 - star_protect), 0, 1)
        hi = cv2.GaussianBlur(hi, (0, 0), 2.0)
        m = hi[..., None] if out.ndim == 3 else hi
        out = out * (1 - m) + f.astype(np.float32) * m
    psf_sz = psf.shape[0] if (psf is not None and not tiled_psf) else "tiled"
    log(f"    Dekonvolution: Richardson-Lucy {iterations} Iter., PSF {psf_sz}, "
        f"reg={regularize}, deringing={deringing}, Stern-Schutz {star_protect}")
    return np.clip(out, 0, 1)


def _extract_ha_oiii(bgr, unmix=0.20):
    """Hα und OIII aus Dual-Band-OSC SAUBER trennen (normalisiert, [0..1]).
    Übersprechen beim OSC-Sensor: Hα (656 nm) → v. a. Rot (leckt etwas in Grün), OIII (500 nm) →
    Grün+Blau (leckt etwas in Rot). Darum Hα=Rot, OIII=Blau (Grün am stärksten Hα-kontaminiert),
    Hintergrund pro Kanal abziehen, leichte lineare Entmischung, einzeln normalisieren."""
    f = bgr.astype(np.float32)
    b, _, r = f[..., 0], f[..., 1], f[..., 2]

    def _sub_bg(x):
        return np.clip(x - float(np.quantile(x, 0.30)), 0, None)

    ha, oiii = _sub_bg(r), _sub_bg(b)
    ha2 = np.clip(ha - unmix * oiii, 0, None)
    oiii2 = np.clip(oiii - unmix * ha, 0, None)

    def _norm(x):
        return np.clip(x / max(float(np.quantile(x, 0.999)), 1e-6), 0, 1)

    return _norm(ha2), _norm(oiii2)


def _star_desat(out, ha_n, oiii_n, strength=0.92):
    """Sterne (Kontinuum-Quellen) **neutral/weiß** ziehen — in Schmalband ist Sternfarbe ein
    Artefakt (durchs Dual-Band-Filter kommen nur Hα-Rot + OIII-Cyan → türkise Sternkugeln).
    Ausgedehnte Nebel behalten ihre Farbe.

    Zwei Stufen: kompakte Sternkerne über lokalen Kontrast erkennen (niedriges Helligkeits-Gate,
    damit auch mittelhelle Sterne erfasst werden) und die Maske um die **Sternhöfe** aufweiten —
    sonst bleibt der Glow heller Sterne farbig, während nur der Kern entsättigt wird."""
    lum = np.maximum(ha_n, oiii_n).astype(np.float32)
    smooth = cv2.medianBlur((lum * 255).astype(np.uint8), 9).astype(np.float32) / 255.0
    detail = np.clip(lum - smooth, 0, 1)
    core = np.clip(detail * 6.0, 0, 1) * np.clip((lum - 0.06) / 0.06, 0, 1)   # kompakte Sternkerne
    coreb = (core > 0.25).astype(np.uint8)
    halo = cv2.dilate(coreb, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))  # Hof drumherum
    mask = np.maximum(core, halo.astype(np.float32))
    mask = cv2.GaussianBlur(mask, (0, 0), 3)[..., None]
    gray = out.mean(axis=2, keepdims=True)
    return np.clip(out * (1 - strength * mask) + gray * (strength * mask), 0, 1)


def remove_stars(bgr, sensitivity=5.0, max_size=600, iterations=2, log=print):
    """A6 — Klassisches (nicht-ML) Star-Removal: liefert ein (teilweise) STERNLOSES Nebelbild plus
    die Sternmaske. Reines OpenCV/NumPy.

    Vorgehen:
      1. Sternmaske bauen — Hintergrund (großer Median) abziehen, rauschadaptive Schwelle
         (Median + sensitivity·MAD), nur kompakte, etwa runde Blobs bis `max_size` px² behalten
         (so bleiben ausgedehnte Nebelstrukturen außen vor).
      2. Maske leicht aufweiten (Sternhöfe mitnehmen).
      3. Sternkerne iterativ entfernen: morphologische Grauwert-Öffnung "schrumpft" helle Punkte,
         und der Bereich unter der Maske wird per Inpainting (Telea) aus der Nebel-Umgebung gefüllt.
         Mehrere Iterationen knabbern größere Sterne weiter ab.

    EHRLICHE GRENZEN: Funktioniert gut für KLEINE bis MITTLERE Sterne. GROSSE, gesättigte Sterne mit
    ausgedehnten Halos/Beugungsspikes werden nur PARTIELL entfernt (Restglow/Ringe bleiben), und sehr
    sternreiche Felder über dichtem Nebel können lokal etwas Nebeltextur verlieren. Für saubere
    Resultate auf großen Sternen ist ein ML-Verfahren (StarNet/Starless) überlegen — das ist hier
    bewusst nicht enthalten (kein ML, keine externen Gewichte).

    Args:
        bgr: float32 [0..1] BGR (oder Grau).
        sensitivity: MAD-Faktor der Sternschwelle (kleiner = mehr Sterne erfasst).
        max_size: maximale Blobfläche (px²), die noch als Stern gilt (größer = Nebel, wird geschont).
        iterations: Erosions-/Inpaint-Durchgänge (mehr = aggressiver gegen größere Sterne).

    Returns:
        (starless, mask) — starless: float32 [0..1] gleiche Form/Channels wie Eingabe;
        mask: float32 [0..1] Sternmaske (1 = Stern).
    """
    if bgr is None:
        return bgr, None
    f = bgr.astype(np.float32)
    g = _gray(f)
    g = g / (float(g.max()) + 1e-6)

    # 1) Sternmaske: Hintergrund weg, rauschadaptive Schwelle
    a = (np.clip(g, 0, 1) * 255).astype(np.uint8)
    bg = cv2.medianBlur(a, 31)
    sub = cv2.subtract(a, bg).astype(np.float32)
    med = float(np.median(sub))
    mad = float(np.median(np.abs(sub - med))) * 1.4826 + 1e-6
    th = (sub > max(med + sensitivity * mad, 3.0)).astype(np.uint8)

    n, lbl, stats, _cent = cv2.connectedComponentsWithStats(th, connectivity=8)
    mask = np.zeros_like(th)
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH]); bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        if area < 1 or area > max_size:
            continue
        # Kompaktheit: Sterne sind etwa rund; sehr langgezogene Strukturen (Nebelfilamente) raus
        if bw > 0 and bh > 0 and 0.3 <= bw / bh <= 3.3:
            mask[lbl == i] = 1
    # 2) Sternhöfe mitnehmen
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)

    # 3) Iterativ: helle Kerne morphologisch dämpfen + Maskenbereich aus Umgebung inpainten
    out = f.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    grow = mask.copy()
    for _ in range(max(1, int(iterations))):
        u8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
        # morphologische Grauwert-Öffnung drückt isolierte helle Punkte herunter
        opened = cv2.morphologyEx(u8, cv2.MORPH_OPEN, kernel)
        sel = grow.astype(bool)
        if out.ndim == 3:
            for c in range(out.shape[2]):
                oc = out[..., c]; opc = opened[..., c].astype(np.float32) / 255.0
                oc[sel] = np.minimum(oc[sel], opc[sel])
        else:
            opc = opened.astype(np.float32) / 255.0
            out[sel] = np.minimum(out[sel], opc[sel])
        # Telea-Inpainting füllt die Sternorte aus der Nebel-/Hintergrund-Nachbarschaft
        u8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
        inpainted = cv2.inpaint(u8, grow, 3, cv2.INPAINT_TELEA).astype(np.float32) / 255.0
        if inpainted.ndim == 2 and out.ndim == 3:
            inpainted = inpainted[..., None]
        m3 = grow.astype(np.float32)
        m3 = m3[..., None] if out.ndim == 3 else m3
        out = out * (1 - m3) + inpainted * m3
        grow = cv2.dilate(grow, kernel, iterations=1)    # nächste Runde greift etwas weiter

    starless = np.clip(out, 0, 1).astype(np.float32)
    log(f"    Star-Removal: {int(mask.sum())} Sternpixel maskiert, {iterations} Iter. "
        f"(klein/mittel ok; große Halos nur partiell)")
    return starless, mask.astype(np.float32)


def dualband_hoo(bgr, unmix=0.20):
    """HOO-Palette: Rot=Hα, Grün+Blau=OIII → rote Hα-Nebel + tealfarbene OIII-Bereiche (zwei echte
    Signale, datentreu). Sterne werden neutralisiert."""
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    ha_n, oiii_n = _extract_ha_oiii(bgr, unmix)
    out = np.zeros((*ha_n.shape, 3), np.float32)
    out[..., 2] = ha_n                          # R = Hα
    out[..., 1] = oiii_n                        # G = OIII
    out[..., 0] = oiii_n                        # B = OIII → teal
    return _star_desat(out, ha_n, oiii_n)


def dualband_sho(bgr, unmix=0.20):
    """SYNTHETISCHE SHO-/Hubble-Palette aus Dual-Band (Ha+OIII) — **gold + blau** (klassisch).
    ⚠️ KEIN echtes SII in Dual-Band; SII wird aus Hα synthetisiert. Mapping wie in den Anleitungen:
    Rot = SII(≈Hα), Grün = 0.8·Hα + 0.2·OIII, Blau = OIII → Hα-Bereiche werden gold, OIII blau.
    Forciert den Gold-Look (auch bei reinen Hα-Zielen). Nicht wissenschaftlich, nur fürs Aussehen."""
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    ha, oiii = _extract_ha_oiii(bgr, unmix)
    out = np.zeros((*ha.shape, 3), np.float32)
    out[..., 2] = ha                            # R = SII(synthetisch ≈ Hα)
    out[..., 1] = np.clip(0.8 * ha + 0.2 * oiii, 0, 1)        # G → R+G = gold
    out[..., 0] = oiii                          # B = OIII → blau
    return _star_desat(out, ha, oiii)


def dualband_foraxx(bgr, unmix=0.20):
    """SYNTHETISCHE SHO-Palette im **Foraxx-Stil** (dynamisch, thecoldestnights.com): der Grün-Kanal
    wird je nach Hα·OIII-Stärke gemischt — G = f·Hα + (1−f)·OIII mit f = (Hα·OIII)^(1−Hα·OIII).
    Dadurch: reines Hα → rot, Hα+OIII gemischt → gold, reines OIII → blau. Nuancierter als das
    flache SHO, aber rein Hα-Ziele bleiben rot (kein erzwungenes Gold). SII synthetisch = Hα."""
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    ha, oiii = _extract_ha_oiii(bgr, unmix)
    prod = np.clip(ha * oiii, 1e-6, 1.0)
    fg = prod ** (1.0 - prod)
    out = np.zeros((*ha.shape, 3), np.float32)
    out[..., 2] = ha                            # R = SII(synthetisch ≈ Hα)
    out[..., 1] = np.clip(fg * ha + (1.0 - fg) * oiii, 0, 1)  # G = dynamischer Hα/OIII-Blend
    out[..., 0] = oiii                          # B = OIII
    return _star_desat(out, ha, oiii)


def dualband_bicolor(bgr, unmix=0.20):
    """Bicolor-Technik (nach Cannistra): aus zwei Kanälen (Hα, OIII) wird der fehlende **synthetisch
    errechnet**, damit Farben/Sterne natürlicher werden (weniger Magenta als reines HOO).
    Hier: Rot = Hα, Blau = OIII, **Grün = synthetisch** aus beiden (Mittel, OIII-betont):
    G = max(OIII, 0.5·Hα). Ergebnis: Hα-Bereiche bernstein/rot, OIII cyan-blau, Übergänge weich;
    Sterne werden neutraler. SII bleibt außen vor (nur Hα+OIII)."""
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    ha, oiii = _extract_ha_oiii(bgr, unmix)
    g = np.maximum(oiii, 0.5 * ha)              # synthetisches Grün aus den beiden Kanälen
    out = np.zeros((*ha.shape, 3), np.float32)
    out[..., 2] = ha                            # R = Hα
    out[..., 1] = np.clip(g, 0, 1)              # G = synthetisch (errechnet)
    out[..., 0] = oiii                          # B = OIII
    return _star_desat(out, ha, oiii)


def color_balance(f, strength=1.0):
    """Farbkalibrierung fürs Anzeigen (gegen Rotstich von OSC + LP-Filter):
      1. Himmelshintergrund PRO KANAL neutralisieren (Sky -> neutrales Grau),
      2. Kanäle so abgleichen, dass helle, unklippte Referenzen (Sterne) ~neutral werden.
    So treten die echten Nebelfarben hervor (rotes Ha, blaue Reflexion, teal O-III) statt alles rot.
    strength 0..1 blendet zwischen Original (0) und voller Kalibrierung (1) — einstellbar / KI-gesteuert.
    Wirkt nur aufs Vorschau-/JPG-Bild; die linearen Exports bleiben unangetastet."""
    if f is None or f.ndim != 3 or f.shape[2] != 3 or strength <= 0:
        return f
    src = f.astype(np.float32)
    bg = np.array([np.quantile(src[..., c], 0.30) for c in range(3)], np.float32)
    # Hintergrund neutralisieren, aber NICHT hart auf 0 clippen: ein kleiner Sockel (10 %) bleibt
    # stehen, sonst hat der nachfolgende Stretch (MTF/asinh) keinen Hintergrund mehr zum Anheben und
    # das Bild bleibt fast schwarz (an echten OSC-Daten verifiziert: Median 4 → 26).
    out = np.clip(src - bg.reshape(1, 1, 3) * 0.90, 0, None)    # Hintergrund neutral, Sockel erhalten
    hi = np.array([np.quantile(out[..., c], 0.995) for c in range(3)], np.float32)
    scale = np.clip(hi.mean() / np.clip(hi, 1e-6, None), 0.4, 2.5).astype(np.float32)
    out = np.clip(out * scale.reshape(1, 1, 3), 0, None)        # Sterne ~neutral -> echte Farben
    s = float(min(1.0, max(0.0, strength)))
    return out if s >= 1.0 else np.clip(src * (1 - s) + out * s, 0, None)


def photometric_balance(f, strength=1.0, max_stars=300, log=print):
    """Photometrischer Farbabgleich (PCC-lite, OHNE Online-Sternkatalog): Anders als die einfache
    Quantil-Kalibrierung misst dies die ECHTEN Farben vieler einzelner, UNGESÄTTIGTER Sterne und
    gleicht die Kanäle so ab, dass die mittlere Sternfarbe neutral wird (Sterne sind im Mittel ~weiß).
    Robuster als der 99.5%-Quantil-Weißpunkt, weil gesättigte Sternkerne und gefärbter Nebel
    ausgeschlossen werden → echte, glaubwürdige Nebelfarben statt Farbstich.

    Hinweis: Das ist KEIN katalogbasiertes SPCC (das bräuchte Plate-Solving + Gaia-Abfrage online);
    es nutzt nur die statistische Weiß-Annahme der Sternpopulation im Bild — treu und reproduzierbar."""
    if f is None or f.ndim != 3 or f.shape[2] != 3 or strength <= 0:
        return f
    src = f.astype(np.float32)
    bg = np.array([np.quantile(src[..., c], 0.30) for c in range(3)], np.float32)
    out = np.clip(src - bg.reshape(1, 1, 3), 0, None)          # 1) Hintergrund neutralisieren
    g = _gray(out)
    pts = _star_centroids(g / (g.max() + 1e-6), max_stars=max_stars)
    cols = []
    H, W = g.shape[:2]
    for x, y in pts:
        xi, yi = int(round(x)), int(round(y))
        if 2 <= xi < W - 2 and 2 <= yi < H - 2:
            patch = out[yi - 2:yi + 3, xi - 2:xi + 3].reshape(-1, 3)
            peak = float(patch.max())
            if 0.02 < peak < 0.95:                            # ungesättigt UND über dem Rauschen
                cols.append(patch.mean(0))
    if len(cols) < 15:                                        # zu wenige Sterne → Quantil-Fallback
        log(f"    PCC-lite: nur {len(cols)} brauchbare Sterne → Standard-Farbabgleich")
        return color_balance(f, strength)
    med = np.median(np.array(cols, np.float32), axis=0) + 1e-6   # mittlere Sternfarbe (BGR)
    scale = np.clip(float(med.mean()) / med, 0.4, 2.5).astype(np.float32)
    out = np.clip(out * scale.reshape(1, 1, 3), 0, None)      # 2) mittleren Stern → neutral
    log(f"    PCC-lite: {len(cols)} Sterne, Kanal-Skalierung BGR={np.round(scale, 3)}")
    s = float(min(1.0, max(0.0, strength)))
    return out if s >= 1.0 else np.clip(src * (1 - s) + out * s, 0, None)


def remove_green_cast(f, amount=1.0):
    """SCNR-artige Grün-Entfernung (Average Neutral): Grün wird auf den Schnitt von Rot/Blau
    begrenzt. In der Deep-Sky-Fotografie ist Grün praktisch nie echtes Signal (Nebel sind rot/blau),
    ein Grünstich kommt von OSC-Bayer/Lichtverschmutzung. Subtraktiv/treu — fügt nichts hinzu.
    Entfernt zugleich grüne Hot-Pixel-/Stern-Sprenkel. amount 0..1."""
    if f is None or f.ndim != 3 or f.shape[2] != 3 or amount <= 0:
        return f
    out = f.astype(np.float32).copy()
    b, g, r = out[..., 0], out[..., 1], out[..., 2]      # BGR
    neutral = np.minimum(g, (b + r) * 0.5)
    out[..., 1] = g * (1 - amount) + neutral * amount
    return out


def _bg_surface(f, ds=8):
    """Glatte Hintergrund-/Gradienten-Fläche eines Frames (grob downsamplen + stark glätten →
    Sterne mitteln sich weg). Für die lokale Normalisierung."""
    g = f if f.ndim == 2 else f.mean(2)
    h, w = g.shape
    sw, sh = max(8, w // ds), max(8, h // ds)
    small = cv2.resize(g.astype(np.float32), (sw, sh), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), max(2.0, sw / 10.0))
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def local_normalize(frame, ref_surface):
    """Frame **örtlich** an die Referenz-Hintergrundfläche angleichen (statt nur per Skalar-Offset).
    Da die Frames registriert sind, hebt sich der gemeinsame Nebel in (ref_surf − frame_surf) auf —
    übrig bleibt der **örtliche Hintergrund-/Gradienten-Unterschied**, der korrigiert wird. Das macht
    die Ausreißer-Rejection erst korrekt (gegen Gradienten & Mehrfach-Sessions)."""
    corr = ref_surface - _bg_surface(frame)
    return frame + (corr[..., None] if frame.ndim == 3 else corr)


def _mtf(x, m):
    """Midtones Transfer Function (PixInsight-Primitive): MTF(x,m) = (m−1)x / ((2m−1)x − m).
    Reversibel, definiert auf [0,1]. m = Mitteltonbalance (klein = stark aufhellen)."""
    x = np.asarray(x, np.float32)
    den = (2.0 * m - 1.0) * x - m
    out = np.where(np.abs(den) < 1e-9, x, ((m - 1.0) * x) / den)
    return np.clip(out, 0, 1)


def mtf_stretch(f, target_bg=0.25, shadow=-2.8, saturation=1.05, denoise_chroma=True):
    """MTF-Auto-Stretch (PixInsight-AutoSTF-Stil): Schwarzpunkt aus Median+shadow·MAD, dann
    Mitteltonbalance so, dass der Himmelshintergrund auf `target_bg` (≈0.25) gehoben wird.
    Korrekt und reversibel — kontrollierter als asinh, mit definiertem Schwarzpunkt."""
    g = _gray(f)
    med = float(np.median(g))
    mad = float(np.median(np.abs(g - med))) * 1.4826 + 1e-6
    c0 = float(np.clip(med + shadow * mad, 0, 0.99))            # Schwarzpunkt (shadow<0 → unter Median)
    x = np.clip((f - c0) / max(1e-6, 1 - c0), 0, 1)
    mn = float(np.clip((med - c0) / max(1e-6, 1 - c0), 1e-4, 0.9999))
    T = target_bg
    m = mn * (T - 1.0) / (2 * T * mn - T - mn)                  # MTF(mn,m)=T nach m aufgelöst
    m = float(np.clip(m, 1e-3, 1 - 1e-3))
    out = _mtf(x, m)
    if saturation and saturation != 1.0 and out.ndim == 3:
        lum = _gray(out)[..., None]
        out = np.clip(lum + (out - lum) * saturation, 0, 1)
    if denoise_chroma and out.ndim == 3:
        lum = _gray(out)[..., None]
        out = np.clip(lum + cv2.GaussianBlur(out - lum, (0, 0), 3.0), 0, 1)
    return out


def ghs_stretch(f, D=2.5, b=-0.5, SP=0.18, black_clip=None, saturation=1.08,
                denoise_chroma=True, samples=4096, auto_sp=True):
    """Generalised-Hyperbolic-Stretch (GHS-Familie) — frei steuerbarer High-Dynamic-Stretch,
    der schwaches Nebel-Signal kräftig anhebt, ohne den hellen Kern/Sterne auszubrennen.
    Ergänzt MTF (fester Schwarzpunkt) und asinh um eine voll parametrische Kurve.

      • D  = Intensität (Stärke der Streckung; höher = aggressiver)
      • b  = Charakter der Kurve:  b<0 weicher Knick (asinh-artig), gegen 0 sanfter,
             stärker negativ = härterer, konzentrierter Knick (hyperbolisch)
      • SP = Symmetrie-/Pivotpunkt (0..1): die Helligkeit, um die herum am stärksten gestreckt
             wird — typ. knapp über dem Himmelshintergrund.

    Konstruiert über die kumulierte lokale Streckung (Integral einer überall positiven
    Streckfunktion) → garantiert monoton, bildet [0..1] streng auf [0..1] ab, erhält Schwarz/Weiß.
    Identische Kurve je Kanal (linked, wie in Siril)."""
    g = _gray(f)
    if black_clip is not None:
        bg = float(np.quantile(g, black_clip))
    else:
        med = float(np.median(g))
        mad = float(np.median(np.abs(g - med))) * 1.4826
        bg = med + 0.25 * mad
    # Schwarzpunkt setzen UND das Signal in den aktiven Bereich der Kurve normieren (wie asinh):
    # ohne diese Normierung liegt schwaches (lineares) Nebel-Signal nahe 0 und die Kurve hebt es nicht.
    sub = np.clip(f - bg, 0, None)
    # Das schwache Nebel-Signal so normieren, dass der Sky-Anker (75. Perzentil knapp über dem Himmel)
    # genau auf den Pivot SP fällt — dort streckt die Kurve am stärksten (sonst liegt das Signal weit
    # unter SP und bleibt schwarz). Gleichzeitig nie über den Daten-Max hinaus normieren, damit helle
    # Werte den Weißpunkt erreichen ([0..1]→[0..1] bleibt erhalten; bei Astro klippen die Sterne auf 1).
    if auto_sp:
        anchor = float(np.quantile(_gray(sub), 0.75)) + 1e-9
        datamax = float(np.quantile(_gray(sub), 0.9997)) + 1e-9
        norm = min(anchor / max(float(SP), 0.02), datamax) + 1e-6
    else:
        norm = float(np.quantile(_gray(sub), 0.9997)) + 1e-6
    x0 = np.clip(sub / norm, 0, 1)

    xs = np.linspace(0.0, 1.0, samples, dtype=np.float64)
    k = float(D) * float(D)
    ls = (1.0 + k * (xs - float(SP)) ** 2) ** float(b)         # lokale Streckung, Maximum bei SP
    cdf = np.cumsum(ls)
    cdf -= cdf[0]
    cdf /= (cdf[-1] + 1e-12)                                    # → streng [0..1], monoton
    out = np.interp(x0.ravel(), xs, cdf).reshape(x0.shape).astype(np.float32)

    if out.ndim == 3:
        if denoise_chroma:
            lum = _gray(out)[..., None]
            out = np.clip(lum + cv2.GaussianBlur(out - lum, (0, 0), 3.0), 0, 1)
        if saturation and saturation != 1.0:
            lum = _gray(out)[..., None]
            out = np.clip(lum + (out - lum) * saturation, 0, 1)
    return np.clip(out, 0, 1)


def autostretch(f, black_clip=None, strength=6.0, protect_core=True, saturation=1.05,
                denoise_chroma=True):
    """asinh-Auto-Stretch fürs Anzeigen des (linearen, dunklen) Astro-Ergebnisses.

    Zurückhaltend gehalten — Ziel ist eine *echte* Bearbeitung, kein Neon-Comic:
    schwaches Signal wird sichtbar, aber der Hintergrund bleibt dunkel und das Rauschen unten.

    strength  : wie stark schwaches Signal angehoben wird (höher = heller/aggressiver).
    protect_core: helle Bereiche (Nebel-Kern, helle Sterne) werden sanfter gestreckt, damit der
                  Kern nicht zu einem flachen weißen Klecks ausbleicht — Detail/Farbe bleibt.
    saturation: leichter Farb-Boost (Astro-Farben sind nach dem Strecken oft blass).
    denoise_chroma: Farb-Rauschen glätten (Luminanz bleibt scharf) — killt den bunten Grieß im
                    Hintergrund, ohne Schärfe zu kosten.
    black_clip: optionaler fester Schwarzpunkt als Quantil. Standard (None) = **robuster
                Himmelshintergrund** (Median + 0.5·MAD), damit der Hintergrund wirklich nach
                Schwarz geht und das Rauschen nicht hochgezogen wird."""
    g = _gray(f)
    if black_clip is not None:
        bg = np.quantile(g, black_clip)
    else:
        med = float(np.median(g))
        mad = float(np.median(np.abs(g - med))) * 1.4826      # robustes Sigma
        bg = med + 0.25 * mad                                  # Schwarzpunkt knapp über dem Himmel
        #  (weicher als 0.5·MAD: zeigt schwache Nebel-Außenbereiche, Hintergrund bleibt dunkel)
    x = np.clip(f - bg, 0, None)
    # Normierung NICHT auf die hellen Sterne (quantile 0.9997) — das quetscht schwachen Nebel auf
    # ~schwarz. Stattdessen einen Sky-Anker (75. Perzentil knapp über dem Himmel) so skalieren, dass
    # er im Display auf ~0.12 (dunkles Grau) landet — datenunabhängig (geschlossene asinh-Umkehrung),
    # an echten OSC-Daten verifiziert (vorher Median 4 → jetzt ~26, wie MTF).
    anchor = float(np.quantile(_gray(x), 0.75)) + 1e-9
    T = 0.12
    norm = anchor * strength / np.sinh(T * np.arcsinh(strength)) + 1e-6
    x = x / norm
    out = np.clip(np.arcsinh(x * strength) / np.arcsinh(strength), 0, 1)
    if protect_core:
        # In den hellsten ~20 % nur sanft strecken (Kern-Schutz) und mit der starken Kurve mischen.
        gentle = np.clip(np.arcsinh(x * (strength * 0.25)) / np.arcsinh(strength * 0.25), 0, 1)
        lum = _gray(out)
        hi = np.clip((lum - 0.80) / 0.20, 0, 1)
        hi = cv2.GaussianBlur(hi, (0, 0), 2)[..., None] if hi.ndim == 2 else hi[..., None]
        out = out * (1 - hi) + gentle * hi
    if denoise_chroma and out.ndim == 3:
        # Farb-Rauschen ist niederfrequent tolerierbar: Chroma weichzeichnen, Luminanz scharf lassen.
        lum = _gray(out)[..., None]
        chroma = cv2.GaussianBlur(out - lum, (0, 0), 3.0)
        out = np.clip(lum + chroma, 0, 1)
    if saturation != 1.0 and out.ndim == 3:
        lum = _gray(out)[..., None]
        out = np.clip(lum + (out - lum) * saturation, 0, 1)
    return np.clip(out, 0, 1)
