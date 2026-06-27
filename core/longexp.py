#!/usr/bin/env python3
"""
longexp.py — Langzeitbelichtungs-Modul für ForgePix.

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

MODES = ("smooth", "trails", "comet", "declutter", "bright")
# Modus -> Kombinationsmethode in astro.stack (bright/comet werden hier separat gerechnet)
_METHOD = {"smooth": "average", "trails": "max", "declutter": "median"}


def _gap_fill_dilate(f, k=3):
    """Spuren-Lücken (durch Schreibpausen zwischen Frames) überbrücken: leichtes Aufweiten der
    hellen Strukturen vor dem Lighten-Stack → aus „Perlen an der Schnur" werden durchgehende Spuren."""
    return cv2.dilate(f, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))


def _auto_sky_mask(proc, out_shape, sample=12, log=print):
    """Himmel/Vordergrund AUTOMATISCH trennen (Sequator-Stil, ohne festen Höhen-Split): nutzt die
    Physik der Serie — bei nicht nachgeführten Nachtlandschaften BEWEGT sich der Himmel (Sterne/Wolken
    driften), der VORDERGRUND steht still. Pro Pixel die zeitliche Streuung über die Serie messen →
    hohe Streuung = Himmel, niedrige = statischer Vordergrund. Gibt eine weiche Vordergrund-Maske
    (1 = scharf einfrieren, 0 = langzeitbelichten) in out_shape zurück, oder None, wenn keine klare
    Trennung erkennbar ist (z. B. nachgeführt → Sterne stehen still)."""
    idx = np.linspace(0, len(proc) - 1, min(sample, len(proc))).astype(int)
    grays = []
    for i in idx:
        f = cv2.imread(proc[int(i)], cv2.IMREAD_REDUCED_GRAYSCALE_4)
        if f is None:
            g = astro._read_float(proc[int(i)])
            f = (cv2.cvtColor(g, cv2.COLOR_BGR2GRAY) if g.ndim == 3 else g)
            f = cv2.resize(f, (f.shape[1] // 4, f.shape[0] // 4))
            f = (np.clip(f, 0, 1) * 255).astype(np.uint8)
        grays.append(f.astype(np.float32))
    if len(grays) < 3:
        return None
    hh = min(g.shape[0] for g in grays); ww = min(g.shape[1] for g in grays)
    stk = np.stack([g[:hh, :ww] for g in grays])
    var = stk.std(axis=0)                                    # zeitliche Streuung je Pixel
    var = cv2.GaussianBlur(var, (0, 0), 2.0)
    med = float(np.median(var)); mad = float(np.median(np.abs(var - med))) * 1.4826 + 1e-6
    sky = (var > med + 1.5 * mad).astype(np.uint8)           # bewegte Pixel = Himmel-Kandidat
    sky = cv2.morphologyEx(sky, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    sky = cv2.morphologyEx(sky, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    frac0 = float(sky.mean())
    if frac0 < 0.05 or frac0 > 0.95:                         # keine klare Trennung (z. B. nachgeführt)
        log(f"    Auto-Sky: keine klare Himmel/Vordergrund-Trennung ({frac0*100:.0f}% bewegt) — übersprungen")
        return None

    # --- räumlicher Constraint (H4): der Himmel ist EINE zusammenhängende Fläche und liegt OBEN ---
    # Reine Varianzschwelle erzeugt False-Positives in bewegtem Vordergrund (windige Bäume, Wasser,
    # Gras). Plausibilitäts-Kopplung dagegen:
    #   1) Horizont schätzen: unterste Zeile, in der die Himmel-Kandidaten noch dominieren (von oben
    #      kumulierte Zeilenbelegung). Unterhalb wird Himmel verworfen.
    #   2) Nur die GRÖSSTE zusammenhängende Himmel-Komponente behalten (zusammenhängend & oben) →
    #      einzelne flackernde Vordergrund-Inseln fallen weg.
    hh_, ww_ = sky.shape
    row_frac = sky.mean(axis=1)                              # Anteil Himmel je Zeile (oben→unten)
    cum = np.cumsum(row_frac) / (np.arange(1, hh_ + 1))      # mittlere Belegung bis Zeile y
    above = np.where(cum >= 0.5 * max(row_frac.max(), 1e-6))[0]
    horizon = int(above[-1]) if len(above) else hh_ - 1      # tiefste „himmel-dominierte" Zeile
    horizon = int(np.clip(horizon + int(0.05 * hh_), int(0.1 * hh_), hh_ - 1))  # etwas Spielraum
    constrained = sky.copy()
    constrained[horizon + 1:, :] = 0                         # unter dem Horizont kein Himmel

    n, lbl, stats, _c = cv2.connectedComponentsWithStats(constrained, connectivity=8)
    if n <= 1:
        log("    Auto-Sky: keine zusammenhängende Himmel-Fläche oberhalb des Horizonts — übersprungen")
        return None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))  # größte Komponente (ohne Hintergrund)
    sky_c = (lbl == largest).astype(np.float32)
    sky_c = cv2.morphologyEx(sky_c, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    frac = float(sky_c.mean())
    if frac < 0.05 or frac > 0.95:
        log(f"    Auto-Sky: räumlich plausible Himmelsfläche zu klein/groß ({frac*100:.0f}%) — übersprungen")
        return None
    fg = 1.0 - cv2.GaussianBlur(sky_c, (0, 0), 3.0)         # Vordergrund = unbewegt + unter Horizont
    fg = cv2.resize(fg, (out_shape[1], out_shape[0]))
    fg = np.clip(fg, 0, 1)
    log(f"    Auto-Sky: Himmel {frac*100:.0f}% (zusammenhängend, Horizont bei {int(horizon/hh_*100)}%) "
        f"/ Vordergrund {(1-frac)*100:.0f}% — räumlich plausibilisiert")
    return fg[..., None]


def stack_stars_point(paths, work_dir=None, align="auto", sigma_clip=False, log=print):
    """Punkt-Stern-Stacking mit Feldrotations-Ausgleich (Sequators Königsdisziplin) — gibt float32
    [0..1] (BGR) zurück.

    Anders als der „trails"-Modus (Maximum → Strichspuren) richtet dies jeden Frame an den STERNEN
    der Referenz aus und MITTELT dann → die Sterne bleiben PUNKTFÖRMIG und das Rauschen sinkt mit √N
    (echter SNR-Gewinn statt nur Lichtsammeln). Für nicht nachgeführte Nachtaufnahmen vom Stativ.

    Ablauf je Frame:
      1) Sternzentren detektieren (astro._star_centroids, sub-pixel; ORB als Fallback).
      2) Ein AFFINES Partial-Modell (Translation + Rotation + Skala) gegen die Referenz schätzen —
         deckt die FELDROTATION ab, die bei nicht nachgeführten Serien um den Himmelspol auftritt
         (für übliche Brennweiten reicht eine globale Affine; estimateAffinePartial2D + RANSAC).
      3) Frame warpen und in einen Akkumulator mitteln (sigma_clip=True → Kappa-Sigma statt Mittel,
         verwirft Flugzeuge/Satelliten/Hotpixel).

    Frames, deren Stern-Ausrichtung nicht sicher gelingt, werden VERWORFEN (sonst verschmieren sie
    den Stack), nicht roh dazugemittelt. Die Referenz ist der mittlere Frame.
    align: 'auto' = Stern-Transform mit ORB-Fallback (Standard); 'none' = keine Ausrichtung (nur
    mitteln, z. B. wenn schon nachgeführt)."""
    if not paths:
        raise RuntimeError("keine Aufnahmen fürs Stern-Stacking")
    ref = astro._read_float(paths[len(paths) // 2])
    H, W = ref.shape[:2]
    refg = astro._gray(ref)
    log(f"  Punkt-Stern-Stack aus {len(paths)} Aufnahmen (Feldrotation wird ausgeglichen) …")

    if not sigma_clip:
        acc = np.zeros_like(ref, np.float32)
        cnt = 0
        used_M = 0
        for i, p in enumerate(paths):
            f = astro._read_float(p)
            if f.shape[:2] != (H, W):
                f = cv2.resize(f, (W, H))
            if align == "none" or i == len(paths) // 2:
                aligned = f
            else:
                M = _star_affine(refg, astro._gray(f))
                if M is None:
                    log(f"    Frame {i + 1}: keine sichere Stern-Ausrichtung → verworfen")
                    continue
                aligned = cv2.warpAffine(f, M, (W, H), flags=cv2.INTER_LANCZOS4,
                                         borderMode=cv2.BORDER_REFLECT)
                used_M += 1
            acc += aligned
            cnt += 1
            log(f"    Stern-Stack {i + 1}/{len(paths)} (gemittelt)")
        if cnt == 0:
            raise RuntimeError("Punkt-Stern-Stack: kein Frame ausrichtbar")
        result = acc / cnt
        log(f"    Punkt-Stern-Stack: {cnt} Frames gemittelt ({used_M} per Feldrotation ausgerichtet)")
        return np.clip(result, 0, 1)

    # sigma_clip: ausgerichtete Frames als Temp-TIFF ablegen, dann astro.stack(method='sigma').
    work_dir = work_dir or os.path.dirname(paths[0])
    adir = os.path.join(work_dir, "_star_aligned")
    os.makedirs(adir, exist_ok=True)
    proc, used_M = [], 0
    for i, p in enumerate(paths):
        f = astro._read_float(p)
        if f.shape[:2] != (H, W):
            f = cv2.resize(f, (W, H))
        if align != "none" and i != len(paths) // 2:
            M = _star_affine(refg, astro._gray(f))
            if M is None:
                log(f"    Frame {i + 1}: keine sichere Stern-Ausrichtung → verworfen")
                continue
            f = cv2.warpAffine(f, M, (W, H), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
            used_M += 1
        op = os.path.join(adir, f"s_{i:04d}.tif")
        cv2.imwrite(op, np.clip(f * 65535, 0, 65535).astype(np.uint16),
                    [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
        proc.append(op)
    if not proc:
        import shutil
        shutil.rmtree(adir, ignore_errors=True)
        raise RuntimeError("Punkt-Stern-Stack: kein Frame ausrichtbar")
    result = astro.stack(proc, method="sigma", normalize=False, log=log)
    import shutil
    shutil.rmtree(adir, ignore_errors=True)
    log(f"    Punkt-Stern-Stack: {len(proc)} Frames per Sigma-Clipping kombiniert "
        f"({used_M} per Feldrotation ausgerichtet)")
    return np.clip(result, 0, 1)


def _star_affine(refg, img_g):
    """Affine Partial-Transform (Translation + Rotation + Skala) aus den Sternpositionen schätzen,
    die die Feldrotation nicht nachgeführter Serien abdeckt. Nutzt astro._estimate_star_transform
    (Stern-Centroids + Offset-Voting + RANSAC) und fällt auf ORB (astro._estimate_rotation) zurück.
    Gibt eine 2x3-Matrix (img → ref) oder None, wenn keine sichere Ausrichtung möglich ist."""
    M = astro._estimate_star_transform(refg, img_g)
    if M is None:
        M = astro._estimate_rotation(refg, img_g, detector="ORB", min_inliers=12)
    return M


def combine(paths, mode="smooth", align="none", strength=1.0, work_dir=None, detector="ORB",
            transform="rigid", gap_fill=False, comet_decay=0.9, sigma_clip=False,
            freeze_below=None, freeze_auto=False, log=print):
    """Serie zu einer Langzeitbelichtung verrechnen. Gibt float32 [0..1] (BGR) zurück.

    strength = „virtuelle Belichtungszeit" (0..1): gewichtetes Teil-Mitteln zwischen einem
    scharfen Einzelbild (0 = kurze Belichtung, Bewegung eingefroren) und der vollen Kombination
    (1 = längste Belichtung, maximale Glättung/Spuren). Dazwischen stufenlos."""
    if not paths:
        raise RuntimeError("keine Aufnahmen für die Langzeitbelichtung")
    if mode not in MODES:
        mode = "smooth"
    strength = float(max(0.0, min(1.0, strength)))
    work_dir = work_dir or os.path.dirname(paths[0])

    # 1) Ausrichten (optional). Stativ -> 'none'. Sonst Shift (Phasenkorrelation) oder Feature.
    if align == "feature":
        import stacker
        imgs = [cv2.imread(p, cv2.IMREAD_UNCHANGED) for p in paths]
        imgs = [im for im in imgs if im is not None]
        if not imgs:
            raise RuntimeError("keine lesbaren Aufnahmen für die Ausrichtung")
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
        # auf das 99.95%-Perzentil normieren statt auf max: EIN heißer Pixel (max) würde sonst das
        # ganze Bild dunkel drücken. Perzentil ist hotpixel-robust.
        norm = float(np.percentile(acc, 99.95))
        result = np.clip(acc / max(1e-6, norm), 0, 1)
    elif mode == "comet":
        # abklingendes Lighten: ältere Spuren werden dunkler → heller Kopf, verblassender Schweif
        result = None
        for i, p in enumerate(proc):
            f = astro._read_float(p)
            if gap_fill:
                f = _gap_fill_dilate(f)
            result = f if result is None else np.maximum(result * comet_decay, f)
            log(f"    Komet {i + 1}/{len(proc)}")
    elif mode == "trails" and gap_fill:
        # Lighten mit Lückenfüllung: jedes Frame leicht aufgeweitet, dann Maximum
        result = None
        for i, p in enumerate(proc):
            f = _gap_fill_dilate(astro._read_float(p))
            result = f if result is None else np.maximum(result, f)
            log(f"    Spur+Lückenfüllung {i + 1}/{len(proc)}")
    else:
        # smooth/trails/declutter -> astro.stack (average/max/median), ohne Helligkeits-Normierung.
        # sigma_clip: glättende Modi (smooth/declutter) per Sigma-Clipping statt rohem Mittel/Median
        # → Ausreißer (vorbeifliegende Vögel, Satelliten, Hotpixel, Funkeln) sauber verworfen.
        method = _METHOD[mode]
        if sigma_clip and mode in ("smooth", "declutter"):
            method = "sigma"
        result = astro.stack(proc, method=method, normalize=False, log=log)

    # 2b) Vordergrund einfrieren (Sequator-Stil): Himmel langzeitbelichten, Landschaft scharf aus
    #     einem Einzelbild — gegen Verwischen am Boden. freeze_auto = Himmel/Vordergrund AUTOMATISCH
    #     trennen (über die Sternbewegung); freeze_below = fester Höhen-Anteil (0..1) als Fallback.
    sky_m = None
    if freeze_auto:
        sharp = astro._read_float(proc[len(proc) // 2])
        if sharp.shape != result.shape:
            sharp = cv2.resize(sharp, (result.shape[1], result.shape[0]))
        sky_m = _auto_sky_mask(proc, result.shape[:2], log=log)
        if sky_m is not None:
            result = result * (1.0 - sky_m) + sharp * sky_m
    if sky_m is None and freeze_below and 0.0 < freeze_below < 1.0:
        sharp = astro._read_float(proc[len(proc) // 2])
        if sharp.shape != result.shape:
            sharp = cv2.resize(sharp, (result.shape[1], result.shape[0]))
        h = result.shape[0]
        y0 = int(round((1.0 - freeze_below) * h))
        feather = max(4, int(0.04 * h))
        ramp = np.ones(h, np.float32)
        ramp[:max(0, y0 - feather)] = 0.0
        lo, hi = max(0, y0 - feather), min(h, y0 + feather)
        if hi > lo:
            ramp[lo:hi] = np.linspace(0.0, 1.0, hi - lo)
        ramp[y0 + feather:] = 1.0
        m = ramp[:, None, None]                      # 0 oben (Langzeit), 1 unten (scharf)
        log(f"    Vordergrund eingefroren: unterste {int(freeze_below*100)} % scharf aus Einzelbild")
        result = result * (1.0 - m) + sharp * m

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
