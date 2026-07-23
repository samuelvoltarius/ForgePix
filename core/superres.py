#!/usr/bin/env python3
"""
superres.py — KI-Super-Resolution / Upscaling über Real-ESRGAN (BSD-3, ONNX) per onnxruntime.

Rein lokal, MIT-kompatibel: kein externes Programm, nur das ONNX-Modell + onnxruntime (CoreML/CUDA/CPU).
Funktioniert für JEDES Modul-Ergebnis (Makro, Astro, Panorama, HDR, …). Optional — wenn onnxruntime
oder das Modell fehlen, meldet `available()` False und der Aufrufer überspringt das Upscaling.

Das x2plus-Modell hat einen festen 64×64-Eingang → wir kacheln mit Überlappung und blenden weich.
"""
import os
import numpy as np
import cv2

_MODEL = os.path.expanduser("~/.forgepix/models/realesrgan_x2.onnx")
_SCALE = 2
_TILE = 64
_sessions = {}                      # Cache je aufgelöstem Modellpfad (Modellwechsel muss greifen)


def model_path(path=None):
    return path or os.environ.get("FORGEPIX_SUPERRES_MODEL") or _MODEL


def available(path=None):
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return os.path.exists(model_path(path))


def _get_session(path=None):
    # Cache-Key = aufgelöster Modellpfad — ein globaler Einzel-Cache würde einen späteren
    # Modellwechsel stillschweigend ignorieren (immer die erste Session zurückgeben).
    key = os.path.abspath(model_path(path))
    if key not in _sessions:
        import onnxruntime as ort
        prov = [p for p in ("CoreMLExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider")
                if p in ort.get_available_providers()]
        _sessions[key] = ort.InferenceSession(key, providers=prov)
    return _sessions[key]


def upscale(bgr01, overlap=8, blend=0.65, path=None, log=print):
    """`bgr01` (float 0..1 BGR) per Real-ESRGAN 2× hochskalieren. Gibt das 2×-Bild (BGR float 0..1).
    Gekachelt (64×64) mit Überlappung; die Kachel-Ausgaben werden gewichtet gemittelt (nahtlos).
    blend 0..1: Anteil des KI-Ergebnisses; der Rest kommt vom Lanczos-Upscale des Originals —
    das holt natürliche Mikro-Textur zurück und dämpft den typischen KI-„Plastik/Lack"-Look
    (1.0 = voll KI, 0.6–0.7 = natürlicher)."""
    sess = _get_session(path)
    iname = sess.get_inputs()[0].name
    rgb = np.clip(cv2.cvtColor(np.asarray(bgr01, np.float32), cv2.COLOR_BGR2RGB), 0, 1)
    H, W = rgb.shape[:2]
    stride = _TILE - 2 * overlap
    OH, OW = H * _SCALE, W * _SCALE
    acc = np.zeros((OH, OW, 3), np.float32)
    wsum = np.zeros((OH, OW, 1), np.float32)
    # weiche Kachel-Gewichtung (Hann-artig) gegen Nähte
    win = np.outer(np.hanning(_TILE * _SCALE), np.hanning(_TILE * _SCALE)).astype(np.float32)[..., None] + 1e-3
    ys = list(range(0, max(1, H - overlap), stride))
    xs = list(range(0, max(1, W - overlap), stride))
    n = len(ys) * len(xs)
    log(f"    Super-Resolution (Real-ESRGAN 2×, {n} Kacheln) …")
    for yi in ys:
        for xi in xs:
            y0, x0 = min(yi, H - _TILE) if H >= _TILE else 0, min(xi, W - _TILE) if W >= _TILE else 0
            tile = rgb[y0:y0 + _TILE, x0:x0 + _TILE]
            if tile.shape[0] != _TILE or tile.shape[1] != _TILE:
                tile = cv2.copyMakeBorder(tile, 0, _TILE - tile.shape[0], 0, _TILE - tile.shape[1],
                                          cv2.BORDER_REFLECT)
            inp = np.transpose(tile, (2, 0, 1))[None].astype(np.float32)
            out = sess.run(None, {iname: inp})[0][0]            # (3, 128, 128)
            out = np.clip(np.transpose(out, (1, 2, 0)), 0, 1)
            oy, ox = y0 * _SCALE, x0 * _SCALE
            # Bei Bildern < 64 px Kante wurde die Kachel auf 64 gepolstert — das Modell liefert
            # trotzdem 128: Ausgabe/Gewicht auf die tatsächliche Slice-Größe zuschneiden, sonst
            # Broadcast-ValueError gegen das kleinere Akku-Gitter.
            th = min(_TILE * _SCALE, OH - oy)
            tw = min(_TILE * _SCALE, OW - ox)
            acc[oy:oy + th, ox:ox + tw] += out[:th, :tw] * win[:th, :tw]
            wsum[oy:oy + th, ox:ox + tw] += win[:th, :tw]
    res = acc / np.maximum(wsum, 1e-6)
    out = np.clip(cv2.cvtColor(res, cv2.COLOR_RGB2BGR), 0, 1)
    if blend < 1.0:                                         # KI-„Plastik" mit Lanczos-Textur mischen
        lanc = cv2.resize(np.asarray(bgr01, np.float32), (OW, OH), interpolation=cv2.INTER_LANCZOS4)
        out = np.clip(out * blend + np.clip(lanc, 0, 1) * (1.0 - blend), 0, 1)
    return out
