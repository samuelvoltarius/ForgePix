#!/usr/bin/env python3
"""
tools_engine.py — OPTIONALE Anbindung an externe Astro-Tools (GraXpert, StarNet++).

ForgePix bleibt eigenständig. Wer GraXpert und/oder StarNet++ installiert hat, kann das
fertige (32-bit-lineare) Ergebnis mit EINEM Klick durchschicken statt es von Hand zu öffnen:
  • GraXpert   — Hintergrund-/Gradienten-Entfernung (KI), per Kommandozeile.
  • StarNet++   — Sterne entfernen (starless) bzw. Sternmaske, per Kommandozeile.

Kein fremder Code wird kopiert — die Programme werden nur aufgerufen → ForgePix bleibt MIT.
Ist ein Tool nicht installiert, fällt die GUI auf „im Dateimanager zeigen“ zurück.
"""
import os
import shutil
import subprocess
from constants import imread, imwrite, log_print


def _ensure_uncompressed_tif(infile):
    """GraXpert/StarNet (tifffile-basiert) können LZW-komprimierte TIFFs NICHT lesen
    (`requires imagecodecs`). cv2 schreibt TIFFs per Default LZW-komprimiert → vor dem Aufruf
    bei Bedarf unkomprimiert umschreiben (cv2 liest LZW). Gibt einen sicher lesbaren Pfad zurück."""
    if os.path.splitext(infile)[1].lower() not in (".tif", ".tiff"):
        return infile
    try:
        import tifffile
        with tifffile.TiffFile(infile) as tf:
            comp = tf.pages[0].compression
        if int(getattr(comp, "value", comp)) in (1,):           # 1 = keine Kompression
            return infile
    except Exception:
        pass
    try:
        import cv2
        img = imread(infile, cv2.IMREAD_UNCHANGED)
        if img is None:
            return infile
        safe = os.path.splitext(infile)[0] + "_uc.tif"
        imwrite(safe, img, [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
        return safe
    except Exception:
        return infile


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
    `StarNetv2CLI` o.ä. mit. Sucht auch in gängigen Installations-/Siril-Ordnern."""
    cands = [explicit] if explicit else []
    cands += [shutil.which("starnet++"), shutil.which("StarNetv2CLI"),
              shutil.which("starnet2"), shutil.which("StarNet++"),
              "/usr/local/bin/starnet++", "/Applications/StarNet/StarNetv2CLI"]
    # Häufige Installationsorte (auch der von Siril mitgelieferte/verlinkte StarNet-Ordner)
    for d in ("~/siril/starnet", "~/Documents/starnet", "~/StarNet", "~/starnet",
              "/Applications/Siril.app/Contents/Resources/starnet"):
        for name in ("starnet++", "StarNetv2CLI", "starnet2"):
            cands.append(os.path.join(os.path.expanduser(d), name))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def run_graxpert(infile, outfile=None, op="background-extraction", path=None, log=log_print):
    """GraXpert headless auf eine Datei anwenden. Gibt den Ergebnis-Pfad zurück.
    op: 'background-extraction' (Standard) | 'denoising'."""
    exe = find_graxpert(path)
    if not exe:
        raise RuntimeError("GraXpert nicht gefunden")
    if outfile is None:
        b, e = os.path.splitext(infile)
        outfile = f"{b}_graxpert{e or '.tif'}"
    if os.path.isfile(outfile):                             # Stale-Output-Falle: alte Ausgabe eines
        try:                                                # früheren Laufs würde sonst als frisches
            os.remove(outfile)                              # Ergebnis durchgehen
        except OSError:
            pass
    infile = _ensure_uncompressed_tif(infile)               # gegen LZW-Lesefehler in GraXpert
    cmd = [exe, "-cli", "-cmd", op, infile, "-output", outfile, "-gpu", "true"]  # GPU (CoreML/CUDA)
    log("  GraXpert: " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    except subprocess.TimeoutExpired:
        raise RuntimeError("GraXpert: Zeitüberschreitung (30 min)")
    if proc.returncode != 0:                                # Fehl-Exit nicht stillschweigend schlucken
        tail = (proc.stderr or proc.stdout or "")[-400:]
        raise RuntimeError(f"GraXpert-Fehler (Exit {proc.returncode}). Log-Ende:\n" + tail)
    # GraXpert hängt je nach Version ein Suffix an — flexibel nach dem Ergebnis suchen
    if os.path.isfile(outfile):
        return outfile
    cand = _newest_sibling(outfile, infile)
    if cand:
        return cand
    tail = (proc.stderr or proc.stdout or "")[-400:]
    raise RuntimeError("GraXpert lieferte kein Ergebnis. Log-Ende:\n" + tail)


def run_starnet(infile, outfile=None, path=None, log=log_print):
    """StarNet++ headless: Sterne entfernen → starless-Bild. Gibt den Ergebnis-Pfad zurück.

    Wichtig: StarNet++ akzeptiert nur 16-bit-TIF und braucht seine Gewichte/Bibliotheken im
    eigenen Ordner → wir rufen es mit cwd=Programmordner und absoluten Pfaden auf."""
    exe = find_starnet(path)
    if not exe:
        raise RuntimeError("StarNet++ nicht gefunden")
    exe = os.path.abspath(exe)
    infile = os.path.abspath(_ensure_uncompressed_tif(infile))   # gegen LZW-Lesefehler
    if outfile is None:
        b, e = os.path.splitext(infile)
        outfile = f"{b}_starless{e or '.tif'}"
    outfile = os.path.abspath(outfile)
    if os.path.isfile(outfile):               # Stale-Output-Falle (siehe run_graxpert)
        try:
            os.remove(outfile)
        except OSError:
            pass
    workdir = os.path.dirname(exe)            # Gewichte + dylibs liegen hier
    cmd = [exe, infile, outfile]
    log("  StarNet++: " + " ".join(cmd) + f"  (cwd={workdir})")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800, cwd=workdir)
    except subprocess.TimeoutExpired:
        raise RuntimeError("StarNet++: Zeitüberschreitung (30 min)")
    if proc.returncode != 0:                  # Fehl-Exit nicht stillschweigend schlucken
        tail = (proc.stderr or proc.stdout or "")[-400:]
        raise RuntimeError(f"StarNet++-Fehler (Exit {proc.returncode}). Log-Ende:\n" + tail)
    if os.path.isfile(outfile):
        return outfile
    cand = _newest_sibling(outfile, infile)
    if cand:
        return cand
    tail = (proc.stderr or proc.stdout or "")[-400:]
    raise RuntimeError("StarNet++ lieferte kein Ergebnis. Log-Ende:\n" + tail)


def run_graxpert_enhance(infile, outfile=None, path=None, denoise=True, log=log_print):
    """One-Click-„Veredeln" mit GraXpert: erst Hintergrund-/Gradienten-Extraktion, dann
    (optional) KI-Entrauschung — der übliche Schritt nach dem Stacken. Gibt den End-Pfad zurück.
    Wirft RuntimeError, wenn GraXpert nicht gefunden wird (GUI zeigt dann einen Hinweis)."""
    if not find_graxpert(path):
        raise RuntimeError("GraXpert nicht gefunden")
    b, e = os.path.splitext(infile)
    e = e or ".tif"
    bg = run_graxpert(infile, f"{b}_graxpert{e}", op="background-extraction", path=path, log=log)
    if not denoise:
        return bg
    try:
        return run_graxpert(bg, f"{b}_veredelt{e}", op="denoising", path=path, log=log)
    except Exception as ex:                      # Entrauschen optional — Gradient-Ergebnis behalten
        log(f"  Entrauschen übersprungen ({ex}) — Hintergrund-Ergebnis bleibt.")
        return bg


# Kurz-Infos für den „nicht installiert"-Hinweis in der GUI (frei + offizielle Quelle).
TOOL_INFO = {
    "graxpert": ("GraXpert", "https://www.graxpert.com",
                 "kostenlos & quelloffen — Hintergrund-/Gradienten-Entfernung und KI-Entrauschung"),
    "starnet":  ("StarNet++", "https://www.starnetastro.com",
                 "kostenlos — entfernt Sterne (starless) für getrennte Nebel-/Stern-Bearbeitung"),
}


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
        if p == infile or os.path.splitext(f)[1].lower() not in (".tif", ".tiff", ".fits", ".fit", ".png"):
            continue
        try:                                   # Datei kann zwischen listdir und getmtime verschwinden
            m = os.path.getmtime(p)
        except OSError:
            continue
        if m >= in_mtime:
            cands.append((m, p))
    return max(cands)[1] if cands else None
