#!/usr/bin/env python3
"""
siril_engine.py — OPTIONALE Anbindung an Siril (falls installiert).

StackForge bleibt eigenständig (eigene Engine = Standard). Wer Siril hat, kann es
als Astro-Engine wählen — StackForge schreibt ein Siril-Skript (.ssf) und ruft
`siril-cli` auf (Konvertieren → Registrieren → Rejection-Stacking → Speichern).

Kein Siril-Code wird kopiert (nur das Programm aufgerufen) → StackForge bleibt MIT.
"""
import os
import shutil
import subprocess


def find_siril(explicit=None):
    """Pfad zu siril-cli finden (explizit, PATH, oder macOS-App-Bundle)."""
    cands = [explicit] if explicit else []
    cands += [shutil.which("siril-cli"), shutil.which("siril"),
              "/Applications/Siril.app/Contents/MacOS/siril-cli",
              "/usr/bin/siril-cli", "/usr/local/bin/siril-cli"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def available(explicit=None):
    return find_siril(explicit) is not None


def run_siril_astro(paths, work_dir, kappa=3.0, dark=None, flat=None, bias=None,
                    siril_path=None, log=print):
    """Lights mit Siril stacken. Gibt Pfad zum Ergebnis-TIFF zurück.
    dark/flat/bias = optionale Master-Frame-Dateien."""
    cli = find_siril(siril_path)
    if not cli:
        raise RuntimeError("Siril (siril-cli) nicht gefunden")
    seq_dir = os.path.join(work_dir, "siril")
    if os.path.isdir(seq_dir):
        shutil.rmtree(seq_dir)
    os.makedirs(seq_dir)
    for i, p in enumerate(sorted(paths)):
        shutil.copy2(p, os.path.join(seq_dir, f"light_{i:04d}{os.path.splitext(p)[1].lower()}"))

    seq = "light_"
    # Mindestversion bewusst niedrig (1.0.0) — läuft auf älteren wie neueren Siril
    lines = ["requires 1.0.0", "convert light"]
    cal = []
    for opt, val in (("-dark=", dark), ("-flat=", flat), ("-bias=", bias)):
        if val and os.path.isfile(val):
            cal.append(opt + val)
    if cal:
        lines.append("calibrate light_ " + " ".join(cal) + " -cc=dark")
        seq = "pp_light_"
    lines += [f"register {seq}",
              f"stack r_{seq} rej {kappa} {kappa} -nonorm -out=result_stacked",
              "load result_stacked", "savetif siril_result"]
    script = os.path.join(seq_dir, "stack.ssf")
    open(script, "w").write("\n".join(lines) + "\n")
    log("  Siril: " + cli)
    log("  Skript: " + " ; ".join(lines))
    proc = subprocess.run([cli, "-d", seq_dir, "-s", script],
                          capture_output=True, text=True, timeout=3600)
    for ext in (".tif", ".tiff", ".fit", ".fits"):
        out = os.path.join(seq_dir, "siril_result" + ext)
        if os.path.isfile(out):
            return out
    tail = (proc.stderr or proc.stdout or "")[-400:]
    raise RuntimeError("Siril lieferte kein Ergebnis. Log-Ende:\n" + tail)
