#!/usr/bin/env python3
"""
focus_analysis.py — Fokus-Intelligenz für StackForge (klassisch, erklärbar, kein ML).

Alles dreht sich um eine pro-Frame Kachel-Schärfekarte (Varianz des Laplace je Kachel):

  • detect_blurry()   — verwackelte / global unscharfe Frames aussortieren (mit Begründung).
  • focus_sweep()     — welche Frames decken den Fokusbereich ab, welche sind redundant.
  • stack_optimizer() — wie viel Schärfen-Abdeckung bleibt bei weniger Bildern (50→40→30→20).
  • dof_calc()        — Optik-Rechner: Blende/Abbildung → DOF, Schrittweite, Bilderzahl.
  • stack_quality()   — Bewertung des fertigen Stacks: Schärfe, Halos, Ghosting → Score.

Reine OpenCV/NumPy. Auf kleinen Graustufen gerechnet → schnell, speicherschonend.
"""
import os
import numpy as np
import cv2
from constants import RAW_EXTS


def _load_gray(path, max_side=1000):
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(output_bps=8, use_camera_wb=True, no_auto_bright=True, half_size=True)
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    else:
        g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if g is None:
        return None
    if g.dtype != np.uint8:
        g = (g / 256).astype(np.uint8) if g.max() > 255 else g.astype(np.uint8)
    s = max(g.shape)
    if s > max_side:
        f = max_side / s
        g = cv2.resize(g, (int(g.shape[1] * f), int(g.shape[0] * f)), interpolation=cv2.INTER_AREA)
    return g


def tile_sharpness(gray, grid=12):
    """Schärfe je Kachel = Varianz des Laplace. Gibt Vektor der Länge grid*grid zurück."""
    lap = cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F)
    h, w = gray.shape
    th, tw = max(1, h // grid), max(1, w // grid)
    out = np.empty(grid * grid, np.float32)
    for gy in range(grid):
        for gx in range(grid):
            tile = lap[gy * th:(gy + 1) * th, gx * tw:(gx + 1) * tw]
            out[gy * grid + gx] = float(tile.var()) if tile.size else 0.0
    return out


def sharpness_matrix(paths, grid=12, max_side=1000, log=print):
    """(N_frames × grid²)-Matrix der Kachel-Schärfen. Nicht lesbare Frames → Nullzeile."""
    dim = grid * grid
    rows = []
    for i, p in enumerate(paths):
        g = _load_gray(p, max_side)
        rows.append(tile_sharpness(g, grid) if g is not None else np.zeros(dim, np.float32))
        log(f"  analysiere {i + 1}/{len(paths)}")
    return np.vstack(rows) if rows else np.zeros((0, dim), np.float32)


def detect_blurry(M, paths, rel=0.45):
    """Verwackelte / komplett unscharfe Frames: deren schärfste Kachel liegt deutlich unter
    dem typischen Serien-Maximum. Gibt Liste (index, name, ratio) der schlechten Frames."""
    if len(M) == 0:
        return []
    peak = M.max(axis=1)                 # schärfste Kachel je Frame
    typ = float(np.median(peak)) + 1e-9
    bad = []
    for i, pk in enumerate(peak):
        ratio = float(pk / typ)
        if ratio < rel:
            bad.append((i, os.path.basename(paths[i]), round(ratio, 2)))
    return bad


def focus_sweep(M, paths, content_frac=0.15):
    """Welche Frames decken den Fokusbereich ab? Pro Kachel gewinnt der schärfste Frame.
    Frames ohne gewonnene Kachel sind redundant."""
    n = len(M)
    if n == 0:
        return {"contrib": np.array([]), "total_tiles": 0, "contributing": [],
                "redundant": [], "sweep": (0, 0), "valid_mask": np.array([]), "winners": np.array([])}
    winners = M.argmax(axis=0)
    tile_peak = M.max(axis=0)
    pos = tile_peak[tile_peak > 0]
    thresh = content_frac * float(np.median(pos)) if pos.size else 0.0
    valid = tile_peak > thresh           # nur Kacheln mit echtem Bildinhalt
    contrib = np.zeros(n, int)
    for t, win in enumerate(winners):
        if valid[t]:
            contrib[win] += 1
    contributing = [i for i in range(n) if contrib[i] > 0]
    redundant = [i for i in range(n) if contrib[i] == 0]
    sweep = (min(contributing), max(contributing)) if contributing else (0, 0)
    return {"contrib": contrib, "total_tiles": int(valid.sum()), "contributing": contributing,
            "redundant": redundant, "sweep": sweep, "valid_mask": valid, "winners": winners}


def stack_optimizer(M, paths, levels=(1.0, 0.8, 0.6, 0.4), cover_thresh=0.8):
    """Greedy: Frames nach einzigartigem Schärfe-Beitrag ranken und schätzen, wie viel
    Fokus-Abdeckung bei nur K Bildern erhalten bleibt — OHNE erneutes Stacken.
    Eine Kachel gilt als abgedeckt, wenn ein gewählter Frame ≥cover_thresh ihrer maximal
    erreichbaren Schärfe liefert."""
    sweep = focus_sweep(M, paths)
    valid = sweep["valid_mask"]
    tile_idx = np.where(valid)[0]
    total = len(tile_idx)
    if total == 0:
        return {"order": list(range(len(paths))), "levels": [], "total_tiles": 0}
    tile_max = M[:, tile_idx].max(axis=0) + 1e-9
    ratioM = M[:, tile_idx] / tile_max          # (N × total): Anteil der Max-Schärfe je Kachel
    covered = np.zeros(total, bool)
    order, remaining = [], set(range(len(paths)))
    while remaining and not covered.all():
        best, best_gain = None, 0
        for i in remaining:
            gain = int(((ratioM[i] >= cover_thresh) & ~covered).sum())
            if gain > best_gain:
                best_gain, best = gain, i
        if best is None or best_gain <= 0:
            break
        order.append(best); remaining.discard(best)
        covered |= (ratioM[best] >= cover_thresh)
    # Restliche Frames (kein echter Zugewinn) nach Gesamtbeitrag anhängen
    order += sorted(remaining, key=lambda i: -int(sweep["contrib"][i]))
    out_levels = []
    for lvl in levels:
        k = max(1, int(round(lvl * len(paths))))
        sel = order[:k]
        cov = np.zeros(total, bool)
        for i in sel:
            cov |= (ratioM[i] >= cover_thresh)
        out_levels.append({"frames": k, "coverage": round(100.0 * cov.mean(), 1)})
    return {"order": order, "levels": out_levels, "total_tiles": total}


# ---------------------------------------------------------------- Optik (DOF) ----

SENSORS = {                     # Zerstreuungskreis (circle of confusion) in mm
    "fullframe": 0.029, "apsc": 0.019, "mft": 0.015, "medium": 0.047,
}


def dof_calc(f_number, focal_mm=105.0, magnification=None, distance_m=None,
             sensor="fullframe", overlap=0.30):
    """DOF (Schärfentiefe) je Aufnahme + empfohlene Schrittweite fürs Fokus-Stacking.
    Für Makro die Abbildung (magnification, z.B. 1.0 = 1:1) angeben; sonst die Distanz (m)."""
    N = float(f_number)
    c = SENSORS.get(sensor, 0.029)
    if magnification and magnification > 0:
        m = float(magnification)
        dof_mm = 2.0 * N * c * (1.0 + m) / (m * m)        # Makro-Näherung
    elif distance_m and distance_m > 0:
        f = float(focal_mm); s = distance_m * 1000.0
        H = (f * f) / (N * c) + f                          # Hyperfokaldistanz
        near = s * (H - f) / (H + s - 2 * f)
        far = s * (H - f) / (H - s) if H > s else float("inf")
        dof_mm = (far - near) if far != float("inf") else float("inf")
        m = f / (s - f) if s > f else 0.0
    else:
        return None
    step_mm = dof_mm * (1.0 - overlap) if dof_mm != float("inf") else float("inf")
    return {"dof_mm": dof_mm, "step_mm": step_mm, "magnification": m, "coc_mm": c}


def frames_for_depth(total_depth_mm, step_mm):
    """Benötigte Bilderzahl für eine Motivtiefe bei gegebener Schrittweite."""
    if step_mm <= 0 or step_mm == float("inf") or total_depth_mm <= 0:
        return 1
    return int(np.ceil(total_depth_mm / step_mm)) + 1


def read_exif_optics(path):
    """Brennweite / Blende / Sensor / Fokusdistanz aus den EXIF-Daten lesen (via exiftool).
    Gibt ein Dict zurück (Werte ggf. None) oder None, wenn exiftool fehlt/nichts lesbar ist.
    Sensor wird aus dem 35-mm-Äquivalent (Crop-Faktor) abgeleitet."""
    import shutil as _sh
    import subprocess
    import json as _json
    import re
    if not _sh.which("exiftool"):
        return None
    tags = ["-FocalLength", "-FNumber", "-Aperture", "-Model", "-Make",
            "-FocalLengthIn35mmFormat", "-FocusDistance", "-SubjectDistance",
            "-FocusDistance2", "-LensModel"]
    try:
        out = subprocess.run(["exiftool", "-json", *tags, path],
                             capture_output=True, text=True, timeout=30)
        d = _json.loads(out.stdout)[0]
    except Exception:
        return None

    def num(v):
        if v is None:
            return None
        m = re.search(r"[\d.]+", str(v))
        return float(m.group()) if m else None

    focal = num(d.get("FocalLength"))
    fn = num(d.get("FNumber")) or num(d.get("Aperture"))
    f35 = num(d.get("FocalLengthIn35mmFormat"))
    dist = (num(d.get("FocusDistance")) or num(d.get("SubjectDistance"))
            or num(d.get("FocusDistance2")))
    sensor = "fullframe"
    if focal and f35 and focal > 0:
        crop = f35 / focal
        sensor = ("fullframe" if crop < 1.2 else "apsc" if crop < 1.8
                  else "mft" if crop < 2.3 else "fullframe")
    return {"focal_mm": focal, "f_number": fn, "distance_m": dist, "sensor": sensor,
            "model": d.get("Model"), "lens": d.get("LensModel")}


# -------------------------------------------------------- Qualität des Stacks ----

def stack_quality(result_bgr, sources=None):
    """Bewertet das fertige Stack-Ergebnis (0–100) + menschenlesbare Befunde:
    Schärfe (Laplace-Varianz), Halos (Überschwinger an Kanten), Ghosting (Quell-Streuung)."""
    g = (cv2.cvtColor(result_bgr, cv2.COLOR_BGR2GRAY) if result_bgr.ndim == 3 else result_bgr)
    g = g.astype(np.float32)
    if g.max() > 255:
        g = g / 256.0
    g8 = np.clip(g, 0, 255).astype(np.uint8)

    sharp = float(cv2.Laplacian(g, cv2.CV_32F).var())
    edges = cv2.Canny(g8, 50, 150)
    blur = cv2.GaussianBlur(g, (0, 0), 2)
    overshoot = np.clip(g - blur, 0, None)
    halo = float(overshoot[edges > 0].mean()) if (edges > 0).any() else 0.0

    score = 100.0
    findings = []
    if halo > 6:
        findings.append("leichte Halos an Kanten — evtl. überschärft")
        score -= 12
    if sharp < 50:
        findings.append("Ergebnis wirkt insgesamt eher weich")
        score -= 12

    ghost_area = 0.0
    if sources and len(sources) >= 3:
        try:
            import stacker
            dm = stacker.disagreement_map(sources)
            ghost_area = float((dm > (dm.mean() + 4 * dm.std())).mean())
            if ghost_area > 0.002:
                findings.append("Ghosting/Bewegungszonen erkannt — Retusche oder Deghost prüfen")
                score -= 15
        except Exception:
            pass

    if not findings:
        findings.append("keine auffälligen Artefakte")
    return {"score": int(max(0, min(100, round(score)))),
            "sharpness": round(sharp, 1), "halo": round(halo, 2),
            "ghost_area_pct": round(100 * ghost_area, 3), "findings": findings}
