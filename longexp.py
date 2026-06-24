#!/usr/bin/env python3
"""
longexp.py — Langzeitbelichtungs-Modul für StackForge.

Aus mehreren „normalen“ Aufnahmen (Serie/Burst vom Stativ) eine Langzeitbelichtung rechnen —
ohne ND-Filter. Vier fotografische Modi:

  • smooth   — Mitteln: Wasser/Wolken werden seidig glatt (klassischer Wasserfall-Look).
  • trails   — Aufhellen (Lighten/Max): Lichtspuren von Autos, Sternen-Strichspuren, Feuerwerk.
  • declutter— Median: bewegte Störer (Passanten, Autos) verschwinden, statische Szene bleibt.
  • bright   — Additiv: sammelt Licht ein (dunkle Nachtszene aufhellen), normalisiert.

Ausrichtung optional (Stativ = aus; leichtes Verwackeln = Shift/Feature). Reine OpenCV/NumPy,
speicherschonend über die Platte (greift auf astro.py zurück). KI ist nur Berater (Heuristik
schlägt den passenden Modus vor) — verändert nie Pixel.
"""
import os
import numpy as np
import cv2
import astro

MODES = ("smooth", "trails", "declutter", "bright")
# Modus -> Kombinationsmethode in astro.stack (bright wird hier separat additiv gerechnet)
_METHOD = {"smooth": "average", "trails": "max", "declutter": "median"}


def combine(paths, mode="smooth", align="none", strength=1.0, work_dir=None, detector="ORB",
            transform="rigid", log=print):
    """Serie zu einer Langzeitbelichtung verrechnen. Gibt float32 [0..1] (BGR) zurück.

    strength = „virtuelle Belichtungszeit" (0..1): gewichtetes Teil-Mitteln zwischen einem
    scharfen Einzelbild (0 = kurze Belichtung, Bewegung eingefroren) und der vollen Kombination
    (1 = längste Belichtung, maximale Glättung/Spuren). Dazwischen stufenlos."""
    if mode not in MODES:
        mode = "smooth"
    strength = float(max(0.0, min(1.0, strength)))
    work_dir = work_dir or os.path.dirname(paths[0])

    # 1) Ausrichten (optional). Stativ -> 'none'. Sonst Shift (Phasenkorrelation) oder Feature.
    if align == "feature":
        import stacker
        imgs = [cv2.imread(p, cv2.IMREAD_UNCHANGED) for p in paths]
        imgs = [im for im in imgs if im is not None]
        h, w = imgs[len(imgs) // 2].shape[:2]
        imgs = [cv2.resize(im, (w, h)) if im.shape[:2] != (h, w) else im for im in imgs]
        imgs = stacker.align_images(imgs, mode=transform, detector=detector)
        adir = os.path.join(work_dir, "_le_aligned")
        os.makedirs(adir, exist_ok=True)
        proc = []
        for i, im in enumerate(imgs):
            op = os.path.join(adir, f"a_{i:04d}.tif")
            cv2.imwrite(op, im, [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
            proc.append(op)
    elif align == "shift":
        adir = os.path.join(work_dir, "_le_aligned")
        proc = astro.register_and_cache(paths, adir, do_register=True, log=lambda *a: None)
    else:
        proc = list(paths)

    # 2) Kombinieren
    log(f"  Langzeitbelichtung ({mode}) aus {len(proc)} Aufnahmen …")
    if mode == "bright":
        acc = None
        for i, p in enumerate(proc):
            f = astro._read_float(p)
            acc = f if acc is None else acc + f
            log(f"    additiv {i + 1}/{len(proc)}")
        result = acc / max(1.0, float(acc.max()))   # auf 0..1 normieren (Licht einsammeln)
    else:
        # smooth/trails/declutter -> astro.stack (average/max/median), ohne Helligkeits-Normierung
        result = astro.stack(proc, method=_METHOD[mode], normalize=False, log=log)

    # 3) Virtuelle Belichtungszeit: gewichtetes Teil-Mitteln mit einem scharfen Referenzbild
    if strength < 0.999:
        ref = astro._read_float(proc[len(proc) // 2])
        if ref.shape != result.shape:
            ref = cv2.resize(ref, (result.shape[1], result.shape[0]))
        log(f"    virtuelle Belichtung {int(strength*100)} % (Teil-Mitteln)")
        result = ref * (1.0 - strength) + result * strength

    # Temp-Ausrichtung aufräumen
    if align in ("shift", "feature"):
        import shutil
        shutil.rmtree(os.path.join(work_dir, "_le_aligned"), ignore_errors=True)
    return np.clip(result, 0, 1)


def suggest_mode(paths, max_side=900, sample=8):
    """Heuristischer Modus-Vorschlag aus der Bewegungsanalyse der Serie (kein ML).
    Misst, WO und WIE sich die Frames unterscheiden -> passender Langzeit-Modus + Begründung."""
    idx = np.linspace(0, len(paths) - 1, min(sample, len(paths))).astype(int)
    grays, colors = [], []
    for i in idx:
        im = cv2.imread(paths[int(i)], cv2.IMREAD_REDUCED_COLOR_2)
        if im is None:
            im = cv2.imread(paths[int(i)])
        if im is None:
            continue
        s = max(im.shape[:2])
        if s > max_side:
            f = max_side / s
            im = cv2.resize(im, (int(im.shape[1] * f), int(im.shape[0] * f)))
        colors.append(im.astype(np.float32))
        grays.append(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32))
    if len(grays) < 2:
        return {"mode": "smooth", "align": "none",
                "rationale": "Zu wenige Frames analysierbar — Standard „smooth“ (Mitteln)."}
    stk = np.stack(grays)
    motion = np.abs(stk - stk.mean(axis=0))                  # Abweichung je Pixel über die Zeit
    thresh = motion.mean() + 2 * motion.std() + 1e-6
    moving = motion.max(axis=0) > thresh                     # (H,W) Pro-Pixel-Bewegungsmaske
    moving_frac = float(moving.mean())                       # Anteil bewegter Bildfläche
    mean_bright = float(stk.mean()) / 255.0
    # In bewegten Zonen: sind die Bewegungen hell (Lichter) oder dunkel?
    cstk = np.stack(colors)
    bright_motion = float(cstk.max(axis=0)[moving].mean() - cstk.mean(axis=0)[moving].mean()) \
        if moving.any() else 0.0

    align = "none"  # Annahme Stativ; bei Verwacklung kann der/die Nutzer:in auf „shift“ stellen
    if mean_bright < 0.28 and bright_motion > 18:
        mode = "trails"
        rationale = ("Dunkle Szene mit hellen, wandernden Lichtern erkannt "
                     f"(Helligkeit {mean_bright:.2f}). → „trails“ (Aufhellen) für "
                     "Lichtspuren/Startrails/Feuerwerk.")
    elif 0.02 < moving_frac < 0.25:
        mode = "declutter"
        rationale = (f"Nur kleine, einzelne bewegte Bereiche ({moving_frac*100:.0f} % der Fläche) "
                     "→ „declutter“ (Median) entfernt vorbeilaufende Störer, Szene bleibt scharf.")
    elif mean_bright < 0.22:
        mode = "bright"
        rationale = (f"Insgesamt sehr dunkel (Helligkeit {mean_bright:.2f}) ohne klare Lichtspuren "
                     "→ „bright“ (additiv) sammelt Licht ein.")
    else:
        mode = "smooth"
        rationale = (f"Großflächige, gleichmäßige Bewegung ({moving_frac*100:.0f} % der Fläche) "
                     "→ „smooth“ (Mitteln) für seidiges Wasser/weiche Wolken.")
    return {"mode": mode, "align": align, "moving_frac": round(moving_frac, 3),
            "mean_bright": round(mean_bright, 3), "rationale": rationale}
