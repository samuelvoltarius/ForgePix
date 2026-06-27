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
    """Schärfe-Maß: Varianz des Laplace (höher = schärfer/besseres Seeing)."""
    g = _gray(frame)
    if g.dtype != np.uint8:
        g = cv2.convertScaleAbs(g)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


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
                log=print, preview_cb=None):
    """Lucky-Imaging-Stack aus einem Video. keep_pct = Anteil der schärfsten Frames (0..1).
    Richtet die Scheibe (Sonne/Mond) aus und mittelt; danach optionales Nachschärfen (Unsharp).
    Gibt ein 8-bit-BGR-Bild zurück."""
    scores, (total, w, h) = grade_video(path, max_frames=max_frames, log=log)
    if not scores:
        raise ValueError("keine lesbaren Frames")
    keep_n = max(1, int(len(scores) * max(0.01, min(1.0, keep_pct))))
    keep_idx = sorted(s[1] for s in scores[:keep_n])
    log(f"    Behalte die schärfsten {keep_n} von {len(scores)} Frames ({keep_pct*100:.0f} %)")

    # Referenz = SCHÄRFSTES Frame (nicht irgendeins). Daran wird subpixel-genau ausgerichtet.
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, scores[0][1])
    ok, ref = cap.read()
    if not ok or ref is None:
        raise ValueError("Referenzframe nicht lesbar")
    if ref.ndim == 2:
        ref = cv2.cvtColor(ref, cv2.COLOR_GRAY2BGR)
    ref_g = _gray(ref).astype(np.float32)
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)        # gegen Kanten-Artefakte der FFT

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
