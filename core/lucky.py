#!/usr/bin/env python3
"""
lucky.py — „Lucky Imaging" für Sonne/Mond/Planeten aus einem VIDEO (AutoStakkert-Prinzip).

Aus tausenden Video-Frames werden die **schärfsten** behalten (gutes Seeing), aufeinander
**ausgerichtet** und **gemittelt** (mittelt das Rauschen weg, behält die Schärfe) — danach optional
geschärft. ForgePix wandelt das Video dafür selbst um (OpenCV-VideoCapture, mp4/avi).

Speicherschonend in zwei Durchgängen:
  1) jeden (gesampelten) Frame nur BEWERTEN (Schärfe = Laplace-Varianz) — nichts behalten.
  2) die besten X % erneut lesen, auf eine Referenz ausrichten (Scheiben-Schwerpunkt) und in einen
     Summen-Akku addieren → am Ende teilen. RAM ~ wenige Frames statt tausende.

Reine OpenCV/NumPy-Abhängigkeiten (MIT-kompatibel).
"""
import numpy as np
import cv2


def _gray(frame):
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame


def _sharpness(frame):
    """Schärfe-Maß fürs Frame-Ranking. Wichtig (AutoStakkert-Prinzip): (1) leicht vorglätten, sonst
    misst die Laplace-Varianz das RAUSCHEN statt das Seeing (Rauschen²-getrieben); (2) auf die mittlere
    Szenenhelligkeit NORMIEREN, sonst gewinnen einfach hellere Frames (Transparenz-/Höhenschwankung)."""
    g = _gray(frame)
    if g.dtype != np.uint8:
        g = cv2.convertScaleAbs(g)
    gb = cv2.GaussianBlur(g, (0, 0), 1.0)                      # Noise-Parameter (uint8 bleibt)
    lap_var = float(cv2.Laplacian(gb, cv2.CV_64F).var())
    mean = float(gb.mean()) + 1.0
    return lap_var / (mean * mean)                             # helligkeitsnormiert


def _disk_centroid(frame, thresh=None):
    """Schwerpunkt der hellen Scheibe (Sonne/Mond) auf dunklem Grund — für die Ausrichtung.
    Gibt (x, y) oder None (keine Scheibe)."""
    g = _gray(frame).astype(np.float32)
    t = thresh if thresh is not None else max(20.0, g.mean() + 0.5 * g.std())
    m = (g > t).astype(np.uint8)
    if m.sum() < 50:
        return None
    M = cv2.moments(m, binaryImage=True)
    if M["m00"] == 0:
        return None
    return M["m10"] / M["m00"], M["m01"] / M["m00"]


def grade_video(path, max_frames=3000, log=print):
    """Durchgang 1: Schärfe je (gesampeltem) Frame. Gibt sortierte Liste [(schärfe, frame_index)]
    (beste zuerst) + (gesamt_frames, breite, höhe) zurück."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"Video nicht lesbar: {path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    w = int(cap.get(3)); h = int(cap.get(4))
    step = max(1, total // max_frames) if total > max_frames else 1
    scores = []
    idx = 0
    read = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if idx % step == 0 and fr is not None:
            scores.append((_sharpness(fr), idx))
            read += 1
            if read % 200 == 0:
                log(f"    Bewerte Frames … {read}")
        idx += 1
    cap.release()
    scores.sort(key=lambda s: -s[0])
    log(f"    {read} Frames bewertet (von {total or idx})")
    return scores, (total or idx, w, h)


def lucky_stack(path, keep_pct=0.30, max_frames=3000, align=True, sharpen_amount=60,
                ref_topn=1, log=print, preview_cb=None):
    """Lucky-Imaging-Stack aus einem Video. keep_pct = Anteil der schärfsten Frames (0..1).
    Richtet die Scheibe (Sonne/Mond) aus und mittelt; danach optionales Nachschärfen (Unsharp).
    Gibt ein 8-bit-BGR-Bild zurück.

    `ref_topn` (L2 — Iterative Referenz): Die Ausrichtungs-Referenz wird nicht aus EINEM einzelnen
    Frame gebildet (das trägt das Restrauschen und das individuelle Seeing genau dieses Frames in
    jede Phasenkorrelation), sondern aus dem **Mittel der `ref_topn` schärfsten Frames**. Das ergibt
    eine rauschärmere, repräsentativere Vorlage und damit stabilere Subpixel-Versätze. ref_topn=1
    behält das alte Verhalten (schärfstes Einzelframe als Referenz)."""
    scores, (total, w, h) = grade_video(path, max_frames=max_frames, log=log)
    if not scores:
        raise ValueError("keine lesbaren Frames")
    keep_n = max(1, int(len(scores) * max(0.01, min(1.0, keep_pct))))
    keep_idx = sorted(s[1] for s in scores[:keep_n])
    log(f"    Behalte die schärfsten {keep_n} von {len(scores)} Frames ({keep_pct*100:.0f} %)")

    # Referenz: entweder das schärfste Einzelframe (ref_topn=1) ODER das Mittel der Top-N schärfsten
    # Frames (L2). Bei N>1 werden die Top-N aufeinander (auf das schärfste) ausgerichtet und gemittelt
    # → rauschärmere, stabilere Vorlage für die folgende Subpixel-Ausrichtung.
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)        # gegen Kanten-Artefakte der FFT
    cap = cv2.VideoCapture(path)
    ref_topn = max(1, int(ref_topn))
    top_idx = [s[1] for s in scores[:ref_topn]]
    cap.set(cv2.CAP_PROP_POS_FRAMES, top_idx[0])
    ok, ref = cap.read()
    if not ok or ref is None:
        raise ValueError("Referenzframe nicht lesbar")
    if ref.ndim == 2:
        ref = cv2.cvtColor(ref, cv2.COLOR_GRAY2BGR)
    if ref_topn > 1:
        ref_anchor_g = _gray(ref).astype(np.float32)
        ref_acc = ref.astype(np.float64).copy()
        ref_used = 1
        for ti in top_idx[1:]:
            cap.set(cv2.CAP_PROP_POS_FRAMES, ti)
            ok, tf = cap.read()
            if not ok or tf is None:
                continue
            if tf.ndim == 2:
                tf = cv2.cvtColor(tf, cv2.COLOR_GRAY2BGR)
            if align:
                (dx, dy), _ = cv2.phaseCorrelate(ref_anchor_g, _gray(tf).astype(np.float32), win)
                M = np.float32([[1, 0, dx], [0, 1, dy]])
                tf = cv2.warpAffine(tf, M, (w, h), flags=cv2.INTER_LANCZOS4,
                                    borderMode=cv2.BORDER_REPLICATE)
            ref_acc += tf.astype(np.float64)
            ref_used += 1
        ref = np.clip(ref_acc / ref_used, 0, 255).astype(np.uint8)
        log(f"    Referenz aus Mittel der {ref_used} schärfsten Frames (ref_topn={ref_topn})")
    ref_g = _gray(ref).astype(np.float32)

    acc = ref.astype(np.float64).copy()
    used = 1
    for k, fi in enumerate(keep_idx):
        if fi == scores[0][1]:
            continue                                        # Referenz schon drin
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        if fr.ndim == 2:
            fr = cv2.cvtColor(fr, cv2.COLOR_GRAY2BGR)
        if align:
            # Subpixel-Translation per Phasenkorrelation (auf der gefensterten Graustufe)
            (dx, dy), _resp = cv2.phaseCorrelate(ref_g, _gray(fr).astype(np.float32), win)
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            fr = cv2.warpAffine(fr, M, (w, h), flags=cv2.INTER_LANCZOS4,
                                borderMode=cv2.BORDER_REPLICATE)
        acc += fr.astype(np.float64)
        used += 1
        if used % 100 == 0:
            log(f"    Stapeln … {used}/{keep_n}")
            if preview_cb:
                try:
                    preview_cb(np.clip(acc / used, 0, 255).astype(np.uint8), used)
                except Exception:
                    pass
    cap.release()
    if used == 0:
        raise ValueError("kein Frame stapelbar")
    out = np.clip(acc / used, 0, 255).astype(np.uint8)
    log(f"    {used} Frames gemittelt")
    if sharpen_amount and sharpen_amount > 0:
        a = sharpen_amount / 100.0
        blur = cv2.GaussianBlur(out, (0, 0), 1.6)
        out = np.clip(out.astype(np.float32) * (1 + a) - blur.astype(np.float32) * a, 0, 255).astype(np.uint8)
        log(f"    Nachgeschärft (Unsharp {sharpen_amount} %)")
    return out


def _local_quality(patch):
    """Lokales Struktur-/Schärfemaß: Minimum der mittleren Gradientenbeträge in x und y.
    Das min(…) erzwingt echte 2-D-Struktur (eine reine 1-D-Kante zählt nicht)."""
    if patch.size < 9:
        return 0.0
    gx = np.abs(np.diff(patch.astype(np.float32), axis=1)).mean()
    gy = np.abs(np.diff(patch.astype(np.float32), axis=0)).mean()
    return float(min(gx, gy))


def _global_shift(ref_g, mov_g):
    """Grobe globale Subpixel-Translation (mov→ref) per Phasenkorrelation."""
    try:
        (dx, dy), _ = cv2.phaseCorrelate(ref_g, mov_g)
        return dx, dy
    except cv2.error:
        return 0.0, 0.0


def _feature_homography(ref_u8, mov_u8, orb=None, kr=None, dr=None, min_inliers=40):
    """Globale Homographie mov→ref aus ORB-Merkmalen (handhabt Schwenk/Rotation/Zoom/Perspektive,
    nicht nur Translation). Gibt (H, inliers) oder (None, 0). kr/dr = vorab berechnete Referenz-
    Merkmale (spart Zeit über viele Frames)."""
    if orb is None:
        orb = cv2.ORB_create(2000)
    if kr is None:
        kr, dr = orb.detectAndCompute(ref_u8, None)
    if dr is None or len(kr) < 10:
        return None, 0
    k, d = orb.detectAndCompute(mov_u8, None)
    if d is None or len(k) < 10:
        return None, 0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    try:
        matches = bf.knnMatch(d, dr, k=2)
    except cv2.error:
        return None, 0
    good = [a for a, b in (m for m in matches if len(m) == 2) if a.distance < 0.75 * b.distance]
    if len(good) < 12:
        return None, 0
    src = np.float32([k[x.queryIdx].pt for x in good]).reshape(-1, 1, 2)
    dst = np.float32([kr[x.trainIdx].pt for x in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if H is None or mask is None:
        return None, 0
    inl = int(mask.sum())
    return (H, inl) if inl >= min_inliers else (None, inl)


def lucky_stack_map(path, keep_global=0.6, keep_local=0.3, max_load=200,
                    ap_step=50, box_half=22, patch_half=34, search_half=12,
                    sharpen=1.0, drizzle=1.0, refine_passes=0, adaptive_ap=False,
                    pixfrac=0.6, log=print, preview_cb=None):
    """Multi-Point-(MAP)-Lucky-Imaging (AutoStakkert/PlanetarySystemStacker-Prinzip).

    1) Frames global nach Schärfe ranken, die besten `keep_global` laden + global ausrichten.
    2) Mittelbild als Referenz-Leinwand.
    3) Alignment-Punkt-Raster (nur APs mit echter Struktur).
    4) PRO AP: alle geladenen Frames nach LOKALEM Kontrast ranken → die besten `keep_local`.
    5) PRO AP+Frame: lokalen Subpixel-Versatz (matchTemplate + Parabel) bestimmen.
    6) Patches je AP mitteln (lokal ausgerichtet → scharf + entrauscht).
    7) Hann-gewichtet nahtlos zusammenblenden; Lücken = Mittelbild.

    Korrigiert das LOKALE Seeing, das die globale Mittelung nicht kann. Gibt 8-bit-BGR zurück.

    Erweiterungen (Defaults = altes Verhalten):

    `drizzle` (L1 — Drizzle/Super-Resolution, 1.0/1.5/3.0): Statt die schon gemessenen Subpixel-
    Versätze beim Patch-Mitteln per Interpolation „glattzubügeln", werden die Patch-Pixel als Energie
    auf ein um Faktor `drizzle` höher aufgelöstes Akku-Gitter gestreut (Drop-Kernel, `pixfrac`).
    Jedes Eingabepixel landet subpixel-genau und verteilt seine Energie auf die 4 Nachbarzellen des
    Zielorts. Bei echtem Jitter (statisches Stativ, viele Frames) hebt das die effektive Auflösung
    über das Eingaberaster. drizzle=1.0 → keine Vergrößerung. Die Ausgabe ist dann Faktor `drizzle`
    größer (z. B. 1.5× → 1,5-fache Kantenlänge). `pixfrac` (~0.6) = Tropfengröße (kleiner = schärfer,
    aber mehr Löcher); dünn abgedeckte Zellen werden zum Schluss aufgefüllt.

    `refine_passes` (L2 — Iterative Referenz, 2. Pass): Nach dem 1. MAP-Stack wird dessen
    GESCHÄRFTES Ergebnis als neues matchTemplate-Template benutzt und die lokalen AP-Versätze neu
    gemessen → schärfere Patch-Registrierung (behebt den Soft-Mean-Template-Bias). 0 = aus.

    `adaptive_ap` (L4 — Adaptive AP-Größe/-Dichte): Die AP-Platzierung wird aus der Kontrastkarte
    abgeleitet — zusätzliche, dichtere APs in detailreichen Zonen (hohes `_local_quality`), das
    grobe Grundraster bleibt zur Verankerung in glatten Zonen erhalten (2-Skalen). False = altes
    festes Raster."""
    scores, (total, w, h) = grade_video(path, max_frames=max(max_load * 3, 1500), log=log)
    if not scores:
        raise ValueError("keine lesbaren Frames")
    n_load = max(8, min(max_load, int(len(scores) * keep_global)))
    load_idx = sorted(s[1] for s in scores[:n_load])
    log(f"    MAP: lade {len(load_idx)} der schärfsten Frames")

    cap = cv2.VideoCapture(path)
    frames, grays = [], []
    for fi in load_idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        if fr.ndim == 2:
            fr = cv2.cvtColor(fr, cv2.COLOR_GRAY2BGR)
        frames.append(fr)
        grays.append(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32))
    cap.release()
    if len(frames) < 3:
        raise ValueError("zu wenige ladbare Frames")
    h, w = grays[0].shape

    # (1b) global ausrichten: strukturreichstes Frame = Referenz. AUTO-Modus:
    #   • statisches Ziel + Seeing → Phasenkorrelation (Translation; Homographie würde das Seeing
    #     überfitten), das LOKALE MAP unten korrigiert die Verzeichnung.
    #   • bewegte Szene (Schwenk/Drift/Rotation, z. B. Handnachführung) → ORB-HOMOGRAPHIE, sonst
    #     verschmiert der Stack zu Streifen. Wird automatisch erkannt: greift die Homographie bei
    #     genug Frames mit klarer Bewegung (>1.5 px Rest nach reiner Verschiebung), wird sie genutzt.
    ref_i = int(np.argmax([_local_quality(g) for g in grays]))
    refg = grays[ref_i]
    refu = refg.astype(np.uint8)
    orb = cv2.ORB_create(2000)
    kr, dr = orb.detectAndCompute(refu, None)
    # Bewegung schätzen: für eine Stichprobe Homographie testen, Versatz der Bildmitte messen
    motion_votes, sample = 0, list(range(0, len(frames), max(1, len(frames) // 12)))
    for i in sample:
        if i == ref_i:
            continue
        H, inl = _feature_homography(refu, grays[i].astype(np.uint8), orb, kr, dr)
        if H is not None:
            c = cv2.perspectiveTransform(np.float32([[[w / 2, h / 2]]]), H)[0, 0]
            if np.hypot(c[0] - w / 2, c[1] - h / 2) > 1.5:
                motion_votes += 1
    use_feature = motion_votes >= max(2, len(sample) // 3)
    log(f"    MAP: globale Ausrichtung = {'Feature-Homographie (bewegte Szene)' if use_feature else 'Phasenkorrelation (statisch)'}")
    keep = []
    for i in range(len(frames)):
        if i == ref_i:
            keep.append(i); continue
        if use_feature:
            H, inl = _feature_homography(refu, grays[i].astype(np.uint8), orb, kr, dr)
            if H is None:                                 # Inhalt schon weggewandert → Frame verwerfen
                continue
            frames[i] = cv2.warpPerspective(frames[i], H, (w, h), flags=cv2.INTER_LANCZOS4,
                                            borderMode=cv2.BORDER_REPLICATE)
            grays[i] = cv2.warpPerspective(grays[i], H, (w, h), flags=cv2.INTER_LANCZOS4,
                                           borderMode=cv2.BORDER_REPLICATE)
        else:
            dx, dy = _global_shift(refg, grays[i])
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            frames[i] = cv2.warpAffine(frames[i], M, (w, h), flags=cv2.INTER_LANCZOS4,
                                       borderMode=cv2.BORDER_REPLICATE)
            grays[i] = cv2.warpAffine(grays[i], M, (w, h), flags=cv2.INTER_LANCZOS4,
                                      borderMode=cv2.BORDER_REPLICATE)
        keep.append(i)
    if use_feature and len(keep) < len(frames):
        frames = [frames[i] for i in keep]
        grays = [grays[i] for i in keep]
        log(f"    MAP: {len(frames)} Frames mit ausreichender Überlappung behalten")

    # (2) Mittelbild
    mean_c = np.mean(np.stack([f.astype(np.float32) for f in frames]), axis=0)
    mean_g = cv2.cvtColor(mean_c.astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)

    # (3) AP-Raster, nur wo Struktur
    pad = patch_half + search_half + 2
    ys = list(range(pad, h - pad, ap_step))
    xs = list(range(pad, w - pad, ap_step))
    # Hell/Dunkel-Schwelle: APs sollen NICHT über den Scheibenrand/Hintergrund liegen
    bg = float(np.percentile(mean_g, 20))
    peak = float(np.percentile(mean_g, 97))
    disk_floor = bg + 0.18 * (peak - bg)
    def _scan_grid(step, offset_rows=True):
        """Kandidaten-APs auf einem Raster mit Schrittweite `step` (mit Struktur-Qualität)."""
        gys = list(range(pad, h - pad, step))
        gxs = list(range(pad, w - pad, step))
        out_c, qmx = [], 0.0
        for yi, y in enumerate(gys):
            for x in gxs:
                xx = x + (step // 2 if (offset_rows and yi % 2) else 0)   # versetztes Raster
                if xx >= w - pad:
                    continue
                box = mean_g[y - box_half:y + box_half, xx - box_half:xx + box_half]
                if float(box.min()) < disk_floor:              # Box berührt Rand/Hintergrund → raus
                    continue
                q = _local_quality(box)
                qmx = max(qmx, q)
                out_c.append((y, xx, q))
        return out_c, qmx

    cand, qmax = _scan_grid(ap_step)
    if adaptive_ap and cand:
        # (L4) 2-Skalen: feines Raster (halbe Schrittweite) zusätzlich, aber nur die detailreichsten
        # Punkte übernehmen — so verdichten sich APs dort, wo es Struktur gibt, ohne glatte Zonen
        # mit überflüssigen, schlecht korrelierenden APs zu überladen.
        fine_step = max(box_half, ap_step // 2)
        fcand, fqmax = _scan_grid(fine_step)
        qmax = max(qmax, fqmax)
        hi = qmax * 0.45                                       # nur klar überdurchschnittliche Zonen
        cand = cand + [(y, x, q) for (y, x, q) in fcand if q >= hi]
        log(f"    MAP: adaptive APs — feines Raster (Schritt {fine_step}) in Detailzonen")
    thr = qmax * 0.12
    # Duplikate (gleicher Ort aus beiden Rastern) entfernen, schärfster Wert gewinnt
    best = {}
    for (y, x, q) in cand:
        if q >= thr:
            best[(y, x)] = max(best.get((y, x), 0.0), q)
    aps = sorted(best.keys())
    if not aps:
        log("    MAP: keine Struktur-APs — Fallback auf globalen Mittel-Stack")
        return np.clip(mean_c, 0, 255).astype(np.uint8)
    log(f"    MAP: {len(aps)} Alignment-Punkte mit Struktur")

    # (4-7) pro AP — Setup
    dz = float(max(1.0, drizzle))
    H2, W2 = int(round(h * dz)), int(round(w * dz))           # Ziel-(Drizzle-)Raster
    wy = np.hanning(2 * patch_half)
    hann = (np.outer(wy, wy) + 1e-3).astype(np.float32)       # Gewicht im Eingaberaster
    keep_n = max(3, int(len(frames) * keep_local))
    # Vorab je Frame die lokale Qualität pro AP — ändert sich über Pässe nicht (basiert aufs Frame)
    pf = max(0.05, min(1.0, float(pixfrac)))

    def _drizzle_drop(acc2, wsum2, patch, hpatch, cx, cy):
        """Streut einen (Eingaberaster-)Patch per Drizzle-Drop-Kernel auf das Drizzle-Akku-Gitter.
        Jeder Patch-Pixel wird subpixel-genau (Faktor dz) platziert und seine mit `hpatch` gewichtete
        Energie bilinear auf die 4 Nachbarzellen verteilt (Tropfengröße via `pf`). cx,cy = Patch-
        Mittelpunkt im Eingaberaster."""
        ph, pw = patch.shape[:2]
        # Eingabe-Koordinaten der Patch-Pixel (Mitte des Patches sitzt auf (cx,cy))
        ox = cx - pw / 2.0 + 0.5
        oy = cy - ph / 2.0 + 0.5
        jj, ii = np.meshgrid(np.arange(pw, dtype=np.float32),
                             np.arange(ph, dtype=np.float32))
        # Zielkoordinaten im Drizzle-Gitter; pf staucht den Tropfen um den Pixelmittelpunkt
        tx = (ox + jj) * dz
        ty = (oy + ii) * dz
        fx = np.floor(tx).astype(np.int32); fy = np.floor(ty).astype(np.int32)
        wxr = (tx - fx) * pf; wyr = (ty - fy) * pf            # Tropfen-Überlapp in die nächste Zelle
        wxl = pf - wxr;       wyl = pf - wyr
        wv = (hpatch).astype(np.float32)
        for (oy2, ox2, wx, wyy) in ((0, 0, wxl, wyl), (0, 1, wxr, wyl),
                                    (1, 0, wxl, wyr), (1, 1, wxr, wyr)):
            gx = fx + ox2; gy = fy + oy2
            ok = (gx >= 0) & (gx < W2) & (gy >= 0) & (gy < H2)
            ww = (wx * wyy * wv)
            gxo = gx[ok]; gyo = gy[ok]; wwo = ww[ok]
            if gxo.size == 0:
                continue
            flat = gyo * W2 + gxo
            for c in range(3):
                np.add.at(acc2[..., c].reshape(-1), flat, (patch[..., c][ok] * wwo))
            np.add.at(wsum2.reshape(-1), flat, wwo)

    def _map_pass(template_g):
        """Ein MAP-Durchgang mit gegebener Template-Quelle (Graustufe im Eingaberaster).
        Gibt (acc2, wsum2) im Drizzle-Gitter zurück."""
        acc2 = np.zeros((H2, W2, 3), np.float64)
        wsum2 = np.zeros((H2, W2), np.float64)
        for k, (y, x) in enumerate(aps):
            box_q = [(_local_quality(g[y - box_half:y + box_half, x - box_half:x + box_half]), i)
                     for i, g in enumerate(grays)]
            box_q.sort(key=lambda t: -t[0])
            sel = [i for _, i in box_q[:keep_n]]
            tpl = template_g[y - box_half:y + box_half, x - box_half:x + box_half]
            patches = []
            for i in sel:
                sr = grays[i][y - box_half - search_half:y + box_half + search_half,
                              x - box_half - search_half:x + box_half + search_half]
                if sr.shape[0] < tpl.shape[0] or sr.shape[1] < tpl.shape[1]:
                    continue
                res = cv2.matchTemplate(sr, tpl, cv2.TM_CCOEFF_NORMED)
                _, peak, _, mx = cv2.minMaxLoc(res)
                if peak < 0.3:                                # Korrelations-Peak = Konfidenz: schwacher
                    continue                                  # Match (Fehlkorrelation) → verwerfen
                px, py = mx
                dx, dy = px - search_half, py - search_half
                if 0 < px < res.shape[1] - 1:
                    d = res[py, px - 1] - 2 * res[py, px] + res[py, px + 1]
                    if abs(d) > 1e-9:
                        dx += 0.5 * (res[py, px - 1] - res[py, px + 1]) / d
                if 0 < py < res.shape[0] - 1:
                    d = res[py - 1, px] - 2 * res[py, px] + res[py + 1, px]
                    if abs(d) > 1e-9:
                        dy += 0.5 * (res[py - 1, px] - res[py + 1, px]) / d
                patches.append(cv2.getRectSubPix(frames[i], (2 * patch_half, 2 * patch_half),
                                                 (float(x + dx), float(y + dy))).astype(np.float32))
            if not patches:
                continue
            stack = np.stack(patches)
            if len(patches) >= 4:                             # Sigma-Clip statt rohem Mittel
                mu = stack.mean(0); sd = stack.std(0) + 1e-3
                m = np.abs(stack - mu) <= 2.5 * sd
                patch_avg = (stack * m).sum(0) / np.clip(m.sum(0), 1, None)
            else:
                patch_avg = stack.mean(0)
            if dz > 1.0:
                _drizzle_drop(acc2, wsum2, patch_avg, hann, float(x), float(y))
            else:
                acc2[y - patch_half:y + patch_half, x - patch_half:x + patch_half] += \
                    hann[..., None] * patch_avg
                wsum2[y - patch_half:y + patch_half, x - patch_half:x + patch_half] += hann
            if k % 100 == 0:
                log(f"    MAP: AP {k}/{len(aps)}")
        return acc2, wsum2

    def _blend(acc2, wsum2):
        """Drizzle-Akku → fertiges Bild: normieren, Löcher (dünne Abdeckung) füllen, weich ins
        (hochskalierte) Mittelbild überblenden."""
        res = np.array(acc2)
        nz = wsum2 > 0
        res[nz] /= wsum2[nz, None]
        # L1: Löcher bei dünner Drizzle-Abdeckung füllen (kleine unbedeckte Zellen interpolieren)
        if dz > 1.0:
            holes = (~nz).astype(np.uint8)
            if holes.any():
                for c in range(3):
                    res[..., c] = cv2.inpaint(np.clip(res[..., c], 0, 255).astype(np.uint8),
                                              holes, 3, cv2.INPAINT_TELEA).astype(np.float64)
            mean_up = cv2.resize(mean_c, (W2, H2), interpolation=cv2.INTER_LANCZOS4)
            cover_ref = (hann.max() * dz * dz * pf * pf * 1.2)
        else:
            mean_up = mean_c
            cover_ref = hann.max() * 1.2
        cover = np.clip(wsum2 / max(cover_ref, 1e-6), 0, 1).astype(np.float32)
        cover = cv2.GaussianBlur(cover, (0, 0), max(1.0, patch_half * dz * 0.4))[..., None]
        return res * cover + mean_up * (1.0 - cover)

    # Pass 1
    acc2, wsum2 = _map_pass(mean_g)
    if not (wsum2 > 0).any():
        log("    MAP: keine Patches stapelbar — Fallback auf globalen Mittel-Stack")
        return np.clip(cv2.resize(mean_c, (W2, H2), interpolation=cv2.INTER_LANCZOS4)
                       if dz > 1.0 else mean_c, 0, 255).astype(np.uint8)
    out = _blend(acc2, wsum2)
    out = np.clip(out, 0, 255).astype(np.uint8)

    def _do_sharpen(img):
        if sharpen and sharpen > 0:
            try:
                import wavelet
                g = (1.0 + 2.2 * sharpen, 1.0 + 1.6 * sharpen, 1.0 + 1.0 * sharpen,
                     1.0 + 0.5 * sharpen, 1.0)
                return wavelet.wavelet_sharpen(img, gains=g, denoise=0.1)
            except Exception as e:
                log(f"    MAP: Schärfung übersprungen ({e})")
        return img

    out = _do_sharpen(out)

    # (L2) optionale Refine-Pässe: geschärftes Ergebnis (auf Eingaberaster zurück) als neues Template
    for rp in range(int(max(0, refine_passes))):
        if dz > 1.0:
            tmpl_full = cv2.resize(out, (w, h), interpolation=cv2.INTER_AREA)
        else:
            tmpl_full = out
        new_tpl_g = cv2.cvtColor(tmpl_full, cv2.COLOR_BGR2GRAY).astype(np.float32)
        log(f"    MAP: Refine-Pass {rp + 1}/{int(refine_passes)} (geschärftes Template)")
        acc2, wsum2 = _map_pass(new_tpl_g)
        if not (wsum2 > 0).any():
            break
        out = np.clip(_blend(acc2, wsum2), 0, 255).astype(np.uint8)
        out = _do_sharpen(out)

    log(f"    MAP: zusammengeblendet + Wavelet-geschärft "
        f"(sharpen={sharpen}, drizzle={dz}, refine_passes={refine_passes}, adaptive_ap={adaptive_ap})")
    return np.clip(out, 0, 255).astype(np.uint8)
