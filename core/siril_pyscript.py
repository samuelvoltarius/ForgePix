#!/usr/bin/env python3
"""
siril_pyscript.py — Brücke zu Sirils Python-Skript-Ökosystem (Siril ≥1.4) headless.

Siril 1.4 bringt eine Python-API (`sirilpy`) und mitgelieferte Skripte. Viele haben einen CLI-Modus
(`SirilInterface.is_cli()` + argparse) und laufen damit OHNE GUI. ForgePix steuert sie über ein SSF:
`load <bild>` → `pyscript <skript> <args>` → `save <out>`. ForgePix bleibt MIT (nichts gebündelt).

Headless-taugliche Skripte (CLI-Modus vorhanden): AutoBGE (Hintergrund/Gradient), AberrationRemover
(KI-Stern-/Aberrationskorrektur), Statistical_Stretch (Stretch), GraXpert-AI (via Siril).
NICHT headless (reine GUI): SCUNet_Denoise, DeepSNR & Co. — die brauchen Sirils GUI.
"""
import os
import glob
import shutil
import subprocess
import numpy as np
import cv2

import siril_engine   # für find_siril


def _scripts_dir():
    for base in (os.path.expanduser("~/Library/Application Support/org.siril.Siril/siril-scripts"),
                 os.path.expanduser("~/.config/siril/siril-scripts"),
                 os.path.expanduser("~/.siril/siril-scripts")):
        if os.path.isdir(base):
            return base
    return None


def find_script(name):
    """Pfad zu einem Siril-Python-Skript (z. B. 'AutoBGE.py') finden, oder None."""
    base = _scripts_dir()
    if not base:
        return None
    hits = glob.glob(os.path.join(base, "**", name), recursive=True)
    return hits[0] if hits else None


def available(name="AutoBGE.py", siril_path=None):
    return siril_engine.find_siril(siril_path) is not None and find_script(name) is not None


def run(bgr01, script, args=None, work_dir=None, siril_path=None, timeout=1800, log=print):
    """`bgr01` (float 0..1 BGR) durch ein Siril-Python-Skript headless schicken; Ergebnis-Array zurück.
    script: Dateiname (z. B. 'AberrationRemover.py'); args: Liste von CLI-Tokens (z. B. ['-strength','0.7'])."""
    cli = siril_engine.find_siril(siril_path)
    if not cli:
        raise RuntimeError("Siril (siril-cli) nicht gefunden")
    spath = find_script(script)
    if not spath:
        raise RuntimeError(f"Siril-Skript {script} nicht gefunden")
    work_dir = work_dir or os.path.join(os.path.dirname(spath), "_forgepix_tmp")
    os.makedirs(work_dir, exist_ok=True)
    import tifffile
    rgb16 = (np.clip(cv2.cvtColor(np.asarray(bgr01, np.float32), cv2.COLOR_BGR2RGB), 0, 1)
             * 65535).astype(np.uint16)
    tifffile.imwrite(os.path.join(work_dir, "in.tif"), rgb16, photometric="rgb")
    for f in glob.glob(os.path.join(work_dir, "out.*")):
        os.remove(f)
    argstr = " ".join(str(a) for a in (args or []))
    ssf = os.path.join(work_dir, "fp_bridge.ssf")
    with open(ssf, "w") as fh:
        fh.write(f'requires 1.4.0\ncd "{work_dir}"\nload in\npyscript "{spath}" {argstr}\nsave out\n')
    log(f"    Siril-pyscript: {script} {argstr} …")
    subprocess.run([cli, "-s", ssf], capture_output=True, text=True, timeout=timeout)
    outs = sorted(glob.glob(os.path.join(work_dir, "out.*")))
    if not outs:
        raise RuntimeError(f"Siril-pyscript {script}: keine Ausgabe")
    from astropy.io import fits
    d = fits.getdata(outs[0]).astype(np.float32)
    if d.ndim == 3 and d.shape[0] == 3:
        d = np.transpose(d, (1, 2, 0))
    if d.ndim == 3 and d.shape[2] == 3:
        d = d[..., ::-1]                                    # RGB→BGR
    elif d.ndim == 2:
        d = cv2.cvtColor(d, cv2.COLOR_GRAY2BGR)
    mx = float(d.max())
    if mx > 1.5:
        d = d / mx
    return np.clip(d, 0, 1)


# --- bequeme Wrapper für die headless-tauglichen Skripte ----------------------------------------
def autobge(bgr01, npoints=120, polydegree=2, rbfsmooth=0.1, **kw):
    """Hintergrund-/Gradienten-Extraktion (Siril AutoBGE, RBF/Polynom-DBE)."""
    return run(bgr01, "AutoBGE.py", ["-npoints", npoints, "-polydegree", polydegree,
                                     "-rbfsmooth", rbfsmooth], **kw)


def aberration_remover(bgr01, strength=0.7, protect_background=True, **kw):
    """KI-Stern-/Aberrationskorrektur (verzogene Rand-Sterne runden)."""
    a = ["-strength", strength]
    if protect_background:
        a += ["-protect_background"]
    return run(bgr01, "AberrationRemover.py", a, **kw)


def statistical_stretch(bgr01, median=0.25, sigma=3.0, **kw):
    """Statistischer Stretch (alternativer Auto-Stretch)."""
    return run(bgr01, "Statistical_Stretch.py", ["-median", median, "-sigma", sigma], **kw)
