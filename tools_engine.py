#!/usr/bin/env python3
"""
tools_engine.py — OPTIONALE Anbindung an externe Astro-Tools (GraXpert, StarNet++).

StackForge bleibt eigenständig. Wer GraXpert und/oder StarNet++ installiert hat, kann das
fertige (32-bit-lineare) Ergebnis mit EINEM Klick durchschicken statt es von Hand zu öffnen:
  • GraXpert   — Hintergrund-/Gradienten-Entfernung (KI), per Kommandozeile.
  • StarNet++   — Sterne entfernen (starless) bzw. Sternmaske, per Kommandozeile.

Kein fremder Code wird kopiert — die Programme werden nur aufgerufen → StackForge bleibt MIT.
Ist ein Tool nicht installiert, fällt die GUI auf „im Dateimanager zeigen“ zurück.
"""
import os
import shutil
import subprocess

_MAC = "/Applications"


def find_graxpert(explicit=None):
    """Pfad zur GraXpert-CLI/-App finden (explizit, PATH, gängige Installationsorte)."""
    cands = [explicit] if explicit else []
    cands += [shutil.which("graxpert"), shutil.which("GraXpert"),
              "/Applications/GraXpert.app/Contents/MacOS/GraXpert",
              "/usr/local/bin/graxpert", "/usr/bin/graxpert",
              os.path.expanduser("~/.local/bin/graxpert")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def find_starnet(explicit=None):
    """Pfad zur StarNet++-CLI finden. StarNet bringt je nach Plattform `starnet++`,
    `StarNetv2CLI` o.ä. mit."""
    cands = [explicit] if explicit else []
    cands += [shutil.which("starnet++"), shutil.which("StarNetv2CLI"),
              shutil.which("starnet2"), shutil.which("StarNet++"),
              "/usr/local/bin/starnet++", "/Applications/StarNet/StarNetv2CLI"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def graxpert_available(explicit=None):
    return find_graxpert(explicit) is not None


def starnet_available(explicit=None):
    return find_starnet(explicit) is not None


def run_graxpert(infile, outfile=None, op="background-extraction", path=None, log=print):
    """GraXpert headless auf eine Datei anwenden. Gibt den Ergebnis-Pfad zurück.
    op: 'background-extraction' (Standard) | 'denoising'."""
    exe = find_graxpert(path)
    if not exe:
        raise RuntimeError("GraXpert nicht gefunden")
    if outfile is None:
        b, e = os.path.splitext(infile)
        outfile = f"{b}_graxpert{e or '.tif'}"
    cmd = [exe, "-cli", "-cmd", op, infile, "-output", outfile]
    log("  GraXpert: " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    # GraXpert hängt je nach Version ein Suffix an — flexibel nach dem Ergebnis suchen
    if os.path.isfile(outfile):
        return outfile
    cand = _newest_sibling(outfile, infile)
    if cand:
        return cand
    tail = (proc.stderr or proc.stdout or "")[-400:]
    raise RuntimeError("GraXpert lieferte kein Ergebnis. Log-Ende:\n" + tail)


def run_starnet(infile, outfile=None, path=None, log=print):
    """StarNet++ headless: Sterne entfernen → starless-Bild. Gibt den Ergebnis-Pfad zurück."""
    exe = find_starnet(path)
    if not exe:
        raise RuntimeError("StarNet++ nicht gefunden")
    if outfile is None:
        b, e = os.path.splitext(infile)
        outfile = f"{b}_starless{e or '.tif'}"
    cmd = [exe, infile, outfile]
    log("  StarNet++: " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if os.path.isfile(outfile):
        return outfile
    cand = _newest_sibling(outfile, infile)
    if cand:
        return cand
    tail = (proc.stderr or proc.stdout or "")[-400:]
    raise RuntimeError("StarNet++ lieferte kein Ergebnis. Log-Ende:\n" + tail)


def _newest_sibling(expected, infile):
    """Falls das Tool einen leicht abweichenden Dateinamen schreibt: jüngste passende
    Bilddatei im selben Ordner finden, die neuer ist als die Eingabe."""
    d = os.path.dirname(expected) or "."
    if not os.path.isdir(d):
        return None
    try:
        in_mtime = os.path.getmtime(infile)
    except OSError:
        in_mtime = 0
    cands = []
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if (p != infile and os.path.splitext(f)[1].lower() in (".tif", ".tiff", ".fits", ".fit", ".png")
                and os.path.getmtime(p) >= in_mtime):
            cands.append(p)
    return max(cands, key=os.path.getmtime) if cands else None
