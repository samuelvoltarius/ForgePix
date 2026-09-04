#!/usr/bin/env python3
"""
siril_engine.py — OPTIONALE Anbindung an Siril (falls installiert).

ForgePix bleibt eigenständig (eigene Engine = Standard). Wer Siril hat, kann es
als Astro-Engine wählen — ForgePix schreibt ein Siril-Skript (.ssf) und ruft
`siril-cli` auf (Konvertieren → Registrieren → Rejection-Stacking → Speichern).

Kein Siril-Code wird kopiert (nur das Programm aufgerufen) → ForgePix bleibt MIT.
"""
import os
import shutil
import subprocess

import numpy as np
import cv2
from constants import log_print


def _windows_cands(ordner, relpfade):
    r"""Windows-Installationsorte durchspielen: Program Files, Program Files (x86),
    %LOCALAPPDATA%\Programs und %ProgramData%. Auf Nicht-Windows leere Liste.

    Hintergrund: ForgePix entstand auf macOS, die Sucher kannten nur /Applications
    und /usr/local/bin. Windows-Installer tragen ihre Tools ueblicherweise NICHT in
    den PATH ein — `shutil.which` allein findet sie also nicht."""
    if os.name != "nt":
        return []
    basen = [os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
             os.environ.get("ProgramData", r"C:\ProgramData"),
             os.path.expanduser("~")]
    out = []
    for b in basen:
        if not b:
            continue
        for rel in relpfade:
            out.append(os.path.join(b, ordner, *rel.split("/")))
    return out


def find_siril(explicit=None):
    """Pfad zu siril-cli finden (explizit, PATH, oder macOS-App-Bundle).
    Zentrale Kandidatenliste für ALLE Module (photometric importiert von hier) — der
    GUI-Binary-Kandidat (…/MacOS/Siril) stammt aus der früheren photometric-Kopie."""
    cands = [explicit] if explicit else []
    cands += [shutil.which("siril-cli"), shutil.which("siril"),
              # macOS
              "/Applications/Siril.app/Contents/MacOS/siril-cli",
              "/Applications/Siril.app/Contents/MacOS/Siril",
              # Linux
              "/usr/bin/siril-cli", "/usr/local/bin/siril-cli",
              # Windows — der Installer legt siril-cli.exe unter bin/ ab und traegt
              # NICHTS in den PATH ein. Ohne diese Kandidaten fand ForgePix ein
              # installiertes Siril auf Windows nie (gepruefte Installation 1.4.2).
              *_windows_cands("Siril", ("bin/siril-cli.exe", "bin/siril.exe",
                                        "siril-cli.exe", "siril.exe"))]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def write_tiff16(path, img01, bgr=True):
    """float [0..1] als 16-bit-RGB-TIFF schreiben — gemeinsamer Helper für alle Engine-Brücken
    (Siril-pyscript, Cosmic Clarity, Starless). bgr=True: Eingabe ist BGR (OpenCV-Konvention)
    und wird nach RGB gedreht; bgr=False: Eingabe ist bereits RGB. Gibt den Pfad zurück."""
    import tifffile
    a = np.asarray(img01, np.float32)
    if bgr:
        a = cv2.cvtColor(a, cv2.COLOR_BGR2RGB)
    tifffile.imwrite(path, (np.clip(a, 0, 1) * 65535).astype(np.uint16), photometric="rgb")
    return path


def fits_scale01(d):
    """FITS-Daten auf eine FESTE Skala ~[0..1] bringen — NICHT aufs frame-eigene Maximum
    normieren: ein Hotpixel/Satellit würde sonst die Helligkeit des ganzen Frames verschieben
    (inkonsistent zwischen Subs und Engines). int-Daten über ihren Typ-Maximalwert, ADU-Float-
    Daten per 16-/8-bit-Konvention (>255 → /65535, sonst /255); Werte ≤1.5 gelten als bereits
    normiert und bleiben unverändert."""
    a = np.asarray(d)
    if np.issubdtype(a.dtype, np.integer):
        return a.astype(np.float32) / float(np.iinfo(a.dtype).max)
    a = a.astype(np.float32)
    mx = float(np.nanmax(a)) if a.size else 0.0
    if mx > 1.5:
        a = a / (65535.0 if mx > 255.0 else 255.0)
    return a


def read_fits_bgr(path, gray2bgr=True):
    """Ergebnis-FITS (RGB-Cube oder 2D) als float-BGR mit fester Normierung lesen — gemeinsamer
    Helper für die Siril-/GraXpert-/PCC-Brücken (statt dreier leicht verschiedener Kopien).
    gray2bgr=False lässt 2D-Daten zweidimensional (GraXpert-Verhalten)."""
    from astropy.io import fits
    d = fits_scale01(fits.getdata(path))
    if d.ndim == 3 and d.shape[0] == 3:                     # (C,H,W) → (H,W,C)
        d = np.transpose(d, (1, 2, 0))
    if d.ndim == 3 and d.shape[2] == 3:
        d = np.ascontiguousarray(d[..., ::-1])              # RGB → BGR
    elif d.ndim == 2 and gray2bgr:
        d = cv2.cvtColor(d, cv2.COLOR_GRAY2BGR)
    return d


def available(explicit=None):
    return find_siril(explicit) is not None


def run_siril_astro(paths, work_dir, kappa=3.0, dark=None, flat=None, bias=None,
                    siril_path=None, subsky=True, rmgreen=True, log=log_print):
    """Lights mit Siril stacken und Sirils Kern-Nachbearbeitung anwenden. Gibt Pfad zum Ergebnis-TIFF
    zurück. dark/flat/bias = optionale Master-Frame-Dateien.
    subsky=True: Sirils Hintergrund-/Gradienten-Extraktion (Polynom) auf das Stack-Ergebnis.
    rmgreen=True: Sirils SCNR-Grünentfernung (Average Neutral) — bei OSC fast immer sinnvoll."""
    cli = find_siril(siril_path)
    if not cli:
        raise RuntimeError("Siril (siril-cli) nicht gefunden")
    seq_dir = os.path.join(work_dir, "siril")
    if os.path.isdir(seq_dir):
        shutil.rmtree(seq_dir)
    os.makedirs(seq_dir)
    for i, p in enumerate(sorted(paths)):
        shutil.copy2(p, os.path.join(seq_dir, f"light_{i:04d}{os.path.splitext(p)[1].lower()}"))

    # OSC (Farb-CFA) erkennen → Siril beim Konvertieren debayern lassen, sonst kommt nur Grau raus.
    debayer = ""
    try:
        from astropy.io import fits
        p0 = sorted(paths)[0]
        if os.path.splitext(p0)[1].lower() in (".fit", ".fits", ".fts"):
            if str(fits.getheader(p0).get("BAYERPAT", "")).strip():
                debayer = " -debayer"
                log("  OSC/CFA erkannt → Siril debayert (Farbe)")
    except Exception:
        pass

    seq = "light_"
    # Mindestversion bewusst niedrig (1.0.0) — läuft auf älteren wie neueren Siril
    lines = ["requires 1.0.0", "convert light" + debayer]
    cal = []
    for opt, val in (("-dark=", dark), ("-flat=", flat), ("-bias=", bias)):
        if val and os.path.isfile(val):
            cal.append(opt + val)
    if cal:
        lines.append("calibrate light_ " + " ".join(cal) + " -cc=dark")
        seq = "pp_light_"
    lines += [f"register {seq}",
              f"stack r_{seq} rej {kappa} {kappa} -nonorm -out=result_stacked",
              "load result_stacked"]
    if subsky:
        lines.append("subsky 1")                            # Siril-Hintergrund/Gradient (Polynom Grad 1)
    if rmgreen:
        lines.append("rmgreen 0")                           # Siril-SCNR (Average Neutral) gegen Grünstich
    lines.append("savetif siril_result")
    script = os.path.join(seq_dir, "stack.ssf")
    with open(script, "w") as fh:                           # L5: Handle sicher schließen
        fh.write("\n".join(lines) + "\n")
    log("  Siril: " + cli)
    log("  Skript: " + " ; ".join(lines))
    try:
        proc = subprocess.run([cli, "-d", seq_dir, "-s", script],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Siril: Zeitüberschreitung (60 min)")
    for ext in (".tif", ".tiff", ".fit", ".fits"):
        out = os.path.join(seq_dir, "siril_result" + ext)
        if os.path.isfile(out):
            return out
    tail = (proc.stderr or proc.stdout or "")[-400:]
    raise RuntimeError("Siril lieferte kein Ergebnis. Log-Ende:\n" + tail)
