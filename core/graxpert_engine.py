#!/usr/bin/env python3
"""
graxpert_engine.py — optionales KI-Backend für Hintergrund-/Gradienten-Entfernung und Entrauschen
über die installierte GraXpert-App (https://github.com/Steffenhir/GraXpert, GPL-3.0).

ForgePix bleibt MIT: GraXpert wird NICHT mitgeliefert, sondern — falls vom Nutzer installiert — als
externes Tool aufgerufen (gleiches Muster wie die Siril-Integration). Liefert auf echten OSC-Daten ein
deutlich saubereres, gradientenfreies Ergebnis als die eingebaute RBF-Methode (VLLM-verifiziert: 3 → 1).
"""
import os
import glob
import shutil
import subprocess
import numpy as np

_CANDIDATES = [
    "/Applications/GraXpert.app/Contents/MacOS/GraXpert",
    os.path.expanduser("~/Applications/GraXpert.app/Contents/MacOS/GraXpert"),
    "/opt/GraXpert/GraXpert",
]


def find_cli(path=None):
    """Pfad zur GraXpert-CLI finden (übergebener Pfad, App-Bundle, oder im PATH), sonst None."""
    for c in ([path] if path else []) + _CANDIDATES + [shutil.which("graxpert"), shutil.which("GraXpert")]:
        if c and os.path.exists(c):
            return c
    return None


def available(path=None):
    return find_cli(path) is not None


def _remote_from_env():
    """Optionalen Remote-GPU-Host aus Umgebungsvariablen lesen — NUR wenn gesetzt, sonst None.
    FORGEPIX_GRAXPERT_REMOTE='user@host', FORGEPIX_GRAXPERT_REMOTE_BIN='/pfad/zu/graxpert'
    (optional FORGEPIX_SSH_PASS für Passwort-Login statt SSH-Key)."""
    host = os.environ.get("FORGEPIX_GRAXPERT_REMOTE")
    if not host:
        return None
    return {"host": host,
            "bin": os.environ.get("FORGEPIX_GRAXPERT_REMOTE_BIN", "graxpert"),
            "pass": os.environ.get("FORGEPIX_SSH_PASS")}


def _ssh_prefix(rem):
    base = []
    if rem.get("pass"):
        base = ["sshpass", "-p", rem["pass"]]
    return base


def _run_remote(inp, out_base, command, smoothing, gpu, rem, timeout, log):
    """GraXpert auf einem Remote-GPU-Host laufen lassen (SSH/SCP). Wirft bei jedem Fehler →
    der Aufrufer fällt dann auf lokal zurück. Key-basiert, oder Passwort via FORGEPIX_SSH_PASS."""
    host, gbin = rem["host"], rem["bin"]
    rdir = "~/.forgepix_graxpert"
    sp = _ssh_prefix(rem)
    o = dict(capture_output=True, text=True, timeout=timeout)
    log(f"    GraXpert {command} (Remote {host}, GPU) …")
    subprocess.run(sp + ["ssh", "-o", "BatchMode=" + ("no" if rem.get("pass") else "yes"),
                         host, f"mkdir -p {rdir} && rm -f {rdir}/gx_*"], **o)
    if subprocess.run(sp + ["scp", inp, f"{host}:{rdir}/gx_in.fits"], **o).returncode != 0:
        raise RuntimeError("scp-Upload fehlgeschlagen")
    rcmd = (f"{gbin} -cli -cmd {command} -gpu {'true' if gpu else 'false'} "
            f"-output {rdir}/gx_out {rdir}/gx_in.fits")
    if command == "background-extraction":
        rcmd += f" -smoothing {smoothing}"
    if subprocess.run(sp + ["ssh", host, rcmd], **o).returncode != 0:
        raise RuntimeError("Remote-GraXpert-Lauf fehlgeschlagen")
    # Ergebnisdatei auf dem Remote finden und zurückholen
    r = subprocess.run(sp + ["ssh", host, f"ls {rdir}/gx_out* 2>/dev/null | head -1"], **o)
    rfile = (r.stdout or "").strip()
    if not rfile:
        raise RuntimeError("Remote lieferte keine Ausgabe")
    ext = os.path.splitext(rfile)[1] or ".fits"
    if subprocess.run(sp + ["scp", f"{host}:{rfile}", out_base + ext], **o).returncode != 0:
        raise RuntimeError("scp-Download fehlgeschlagen")


def run(linear_bgr, work_dir, command="background-extraction", smoothing=0.2, gpu=False,
        path=None, remote=None, timeout=900, log=print):
    """`linear_bgr` (float32, HWC BGR, ~0..1) durch GraXpert schicken und das Ergebnis-Array
    (gleiche Form/Reihenfolge) zurückgeben. command: 'background-extraction' | 'denoising'.
    Arbeitet über FITS (GraXperts natives Format) — verlustfrei linear.
    remote: optionaler GPU-Host {host, bin, pass} für Beschleunigung; None = lokal (Default).
    Lokal funktioniert IMMER ohne Remote — der Spark/Remote ist reine Kür mit Fallback."""
    from astropy.io import fits
    os.makedirs(work_dir, exist_ok=True)
    inp = os.path.join(work_dir, "gx_input.fits")
    arr = np.clip(np.asarray(linear_bgr, np.float32), 0, None)
    if arr.ndim == 3:                                       # BGR→RGB, HWC→CHW (FITS-Konvention)
        data = np.transpose(arr[..., ::-1], (2, 0, 1))
    else:
        data = arr
    if os.path.exists(inp):
        os.remove(inp)
    fits.writeto(inp, data, overwrite=True)
    out_base = os.path.join(work_dir, "gx_out")
    for f in glob.glob(out_base + "*"):
        os.remove(f)
    # OPTIONALE Beschleunigung auf einem Remote-GPU-Host (z. B. DGX Spark) — nur wenn KONFIGURIERT.
    # Standard ist immer LOKAL; ForgePix braucht keinen Remote. Bei Remote-Fehler → lokaler Fallback.
    rem = remote if remote is not None else _remote_from_env()
    done = False
    if rem:
        try:
            _run_remote(inp, out_base, command, smoothing, gpu, rem, timeout, log)
            done = bool(sorted(glob.glob(out_base + "*")))
        except Exception as e:
            log(f"    GraXpert-Remote ({rem.get('host')}) fehlgeschlagen ({e}) → lokal")
    if not done:
        cli = find_cli(path)
        if cli is None:
            raise RuntimeError("GraXpert nicht gefunden (App installiert?)")
        cmd = [cli, "-cli", "-cmd", command, "-gpu", "true" if gpu else "false", "-output", out_base, inp]
        if command == "background-extraction":
            cmd += ["-smoothing", str(smoothing)]
        log(f"    GraXpert {command} (lokal, GPU={gpu}) …")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if not sorted(glob.glob(out_base + "*")):
            raise RuntimeError(f"GraXpert lieferte keine Ausgabe (rc={proc.returncode})")
    outs = sorted(glob.glob(out_base + "*"))
    if not outs:
        raise RuntimeError("GraXpert lieferte keine Ausgabe")
    d = fits.getdata(outs[0]).astype(np.float32)
    if d.ndim == 3 and d.shape[0] == 3:                    # CHW→HWC
        d = np.transpose(d, (1, 2, 0))
    if d.ndim == 3 and d.shape[2] == 3:                    # RGB→BGR
        d = d[..., ::-1]
    mx = float(d.max())
    if mx > 1.0:
        d = d / mx
    return np.clip(d, 0, None)
