#!/usr/bin/env python3
"""
cosmicclarity_engine.py — optionales KI-Backend für Schärfung/Dekonvolution (Seti Astro „Cosmic
Clarity", MIT-Lizenz, https://github.com/setiastro/cosmicclarity). Freie Alternative zu BlurXTerminator.

ForgePix ruft die installierte Cosmic-Clarity-CLI auf (gleiches Muster wie GraXpert/Siril). Das
Sharpen-Tool nutzt eine input/output-Ordner-Konvention im Programmverzeichnis und schreibt
``<name>_sharpened.tif``. Läuft auf Apple Silicon über MPS (GPU), sonst CPU.

WICHTIG (Starless-Regel): Schärfung gehört auf den STERNENLOSEN Nebel — „Non-Stellar Only".
"""
import os
import glob
import shutil
import subprocess
import numpy as np
import cv2
from constants import log_print

import siril_engine                      # nur fuer _windows_cands (kein Zyklus)

_CANDIDATES = [
    os.path.expanduser("~/cosmicclarity/SetiAstroCosmicClaritymac"),
    os.path.expanduser("~/cosmicclarity/SetiAstroCosmicClarity"),
    "/Applications/CosmicClarity/SetiAstroCosmicClaritymac",
    # Windows: .exe-Namen; ohne sie war Cosmic Clarity dort grundsaetzlich unauffindbar.
    os.path.expanduser("~/cosmicclarity/SetiAstroCosmicClarity.exe"),
    *siril_engine._windows_cands("CosmicClarity", ("SetiAstroCosmicClarity.exe",)),
]


def find_cli(path=None):
    for c in ([path] if path else []) + _CANDIDATES + [shutil.which("SetiAstroCosmicClaritymac"), shutil.which("SetiAstroCosmicClarity")]:
        if c and os.path.exists(c):
            return c
    return None


def available(path=None):
    return find_cli(path) is not None


def sharpen(bgr01, mode="Non-Stellar Only", nonstellar_strength=2.0, nonstellar_amount=0.7,
            stellar_amount=0.9, auto_psf=False, gpu=True, path=None, timeout=1800, log=log_print):
    """BGR-Float (0..1) mit Cosmic Clarity schärfen (KI-Dekonvolution) und Ergebnis zurückgeben.
    mode: 'Non-Stellar Only' (Nebel — für sternenlose Bilder!), 'Stellar Only', 'Both'."""
    cli = find_cli(path)
    if cli is None:
        raise RuntimeError("Cosmic Clarity nicht gefunden")
    exe_dir = os.path.dirname(cli)
    indir, outdir = os.path.join(exe_dir, "input"), os.path.join(exe_dir, "output")
    os.makedirs(indir, exist_ok=True); os.makedirs(outdir, exist_ok=True)
    # Eindeutiger Dateiname pro Lauf (PID + UUID) statt die input/output-Ordner komplett zu
    # wischen — parallele/fremde Dateien in den Tool-Ordnern bleiben unangetastet; die eigenen
    # Dateien werden im finally wieder entfernt.
    import uuid
    import tifffile
    import siril_engine
    stem = f"ccin_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    inp = os.path.join(indir, stem + ".tif")
    outs = []
    try:
        siril_engine.write_tiff16(inp, bgr01)               # gemeinsamer 16-bit-Writer
        cmd = [cli, "--sharpening_mode", mode,
               "--nonstellar_strength", str(nonstellar_strength),
               "--nonstellar_amount", str(nonstellar_amount),
               "--stellar_amount", str(stellar_amount)]
        if auto_psf:
            cmd.append("--auto_detect_psf")
        if not gpu:
            cmd.append("--disable_gpu")
        log(f"    Cosmic Clarity Schärfung ({mode}, GPU={gpu}) …")
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=exe_dir)
        # nur die EIGENE Ausgabe (<stem>_sharpened.tif) einsammeln, keine fremden Dateien
        outs = sorted(glob.glob(os.path.join(outdir, stem + "*")))
        if not outs:
            tail = ((proc.stderr or proc.stdout or "").strip())[-300:]
            raise RuntimeError(f"Cosmic Clarity lieferte keine Ausgabe (rc={proc.returncode})"
                               + (f": {tail}" if tail else ""))
        g = tifffile.imread(outs[0]).astype(np.float32)
        g = g / 65535.0 if g.max() > 1.5 else g
        if g.ndim == 3:
            g = cv2.cvtColor(g, cv2.COLOR_RGB2BGR)
        return np.clip(g, 0, 1)
    finally:
        for f in [inp] + list(outs):
            try:
                os.remove(f)
            except OSError:
                pass
