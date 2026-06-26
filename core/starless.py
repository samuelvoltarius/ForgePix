#!/usr/bin/env python3
"""
starless.py — Starless-Workflow (Sterne trennen, Nebel bearbeiten, zusammenfügen).

Der „Profi-Weg" für Astro, voll automatisiert: aus dem fertigen (linearen) Stack wird mit
externen Tools ein besseres Bild gemacht:

  1. GraXpert  — Gradient/Hintergrund entfernen (auf dem LINEAREN Bild, vor dem Strecken).
  2. Strecken + Palette (HOO/SHO/… oder Breitband) — unsere eigene Aufbereitung.
  3. StarNet++ — Sterne entfernen → „sternenloses" Nebelbild.
  4. Nebel verstärken — lokaler Kontrast + dezente Sättigung (OHNE Sterne aufzublähen,
     weil sie ja raus sind).
  5. Zusammenfügen — Sterne per Screen-Blend zurück: Ergebnis = 1−(1−Nebel)·(1−Sterne).

Kein fremder Code wird kopiert — GraXpert/StarNet werden nur aufgerufen (ForgePix bleibt MIT).
Fehlt ein Tool, wird der jeweilige Schritt übersprungen (mit Hinweis im Log).
"""
import os
import numpy as np
import cv2

import astro
import tools_engine


def available(starnet_path=None):
    """Starless-Workflow ist nur mit StarNet++ sinnvoll (Sterne trennen)."""
    return tools_engine.find_starnet(starnet_path) is not None


def _palette_view(bgr, palette):
    """Lineares BGR → Anzeige-Farbbild nach Palette (vor dem Strecken)."""
    if palette == "hoo":
        return astro.dualband_hoo(bgr)
    if palette == "sho":
        return astro.dualband_sho(bgr)
    if palette == "foraxx":
        return astro.dualband_foraxx(bgr)
    if palette == "bicolor":
        return astro.dualband_bicolor(bgr)
    # Breitband: Farbkalibrierung + Grünstich-Entfernung
    return astro.remove_green_cast(astro.color_balance(bgr, 1.0))


def _boost_nebula(neb, contrast=0.5, saturation=1.15):
    """Sternenlosen Nebel verstärken: sanfter lokaler Kontrast (Unsharp groß) + dezente Sättigung.
    Geht nur, weil keine Sterne drin sind (sonst würden die aufblähen)."""
    blur = cv2.GaussianBlur(neb, (0, 0), 8)
    out = np.clip(neb + (neb - blur) * contrast, 0, 1)
    lum = out.mean(axis=2, keepdims=True)
    return np.clip(lum + (out - lum) * saturation, 0, 1)


def run(linear_path, palette, work_dir, broadband=False, graxpert_path=None, starnet_path=None,
        boost=True, strength=6.0, saturation=1.05, log=print):
    """Vollen Starless-Workflow ausführen. Gibt den Pfad zum fertigen JPG zurück.

    linear_path : 32-bit-lineares Stack-Ergebnis (TIFF/FITS).
    palette     : 'hoo'/'sho'/'foraxx'/'bicolor' oder None/'broadband' für Breitband.
    Schritte mit fehlendem Tool werden übersprungen (GraXpert optional; ohne StarNet entfällt
    die Stern-Trennung — dann nur Strecken)."""
    os.makedirs(work_dir, exist_ok=True)
    pal = None if (broadband or not palette) else palette

    # 1. GraXpert: Gradient/Hintergrund auf dem linearen Bild (optional)
    cur = linear_path
    if tools_engine.find_graxpert(graxpert_path):
        try:
            log("  1/5 GraXpert: Gradient/Hintergrund entfernen …")
            cur = tools_engine.run_graxpert(cur, op="background-extraction",
                                            path=graxpert_path, log=log)
        except Exception as e:
            log(f"      GraXpert übersprungen ({e})")

    # 2. Palette + Strecken (unsere Aufbereitung)
    log(f"  2/5 Strecken + Palette ({pal or 'Breitband'}) …")
    bgr = astro._read_float(cur)
    stretched = astro.autostretch(_palette_view(bgr, pal), strength=strength, saturation=saturation)

    # ohne StarNet: hier ist Schluss (nur gestrecktes Bild)
    if not tools_engine.find_starnet(starnet_path):
        out = os.path.join(work_dir, "result_stretched.jpg")
        cv2.imwrite(out, np.clip(stretched * 255, 0, 255).astype(np.uint8),
                    [int(cv2.IMWRITE_JPEG_QUALITY), 94])
        log("      StarNet++ nicht gefunden — Sterntrennung entfällt (nur gestreckt).")
        return out

    # 3. StarNet: Sterne entfernen (braucht 16-bit-TIFF)
    log("  3/5 StarNet++: Sterne entfernen …")
    import tifffile
    in16 = os.path.join(work_dir, "starnet_in.tif")
    rgb16 = (np.clip(cv2.cvtColor(stretched.astype(np.float32), cv2.COLOR_BGR2RGB), 0, 1)
             * 65535).astype(np.uint16)
    tifffile.imwrite(in16, rgb16, photometric="rgb")
    starless_path = tools_engine.run_starnet(in16, path=starnet_path, log=log)
    sl = tifffile.imread(starless_path).astype(np.float32) / 65535.0
    if sl.ndim == 2:
        sl = cv2.cvtColor(sl, cv2.COLOR_GRAY2RGB)
    if sl.shape[:2] != stretched.shape[:2]:
        sl = cv2.resize(sl, (stretched.shape[1], stretched.shape[0]))
    starless_rgb = np.clip(sl, 0, 1)

    # 4. Sterne isolieren + Nebel verstärken
    log("  4/5 Nebel verstärken (sternenlos) …")
    stretched_rgb = np.clip(cv2.cvtColor(stretched.astype(np.float32), cv2.COLOR_BGR2RGB), 0, 1)
    stars = np.clip(stretched_rgb - starless_rgb, 0, 1)
    nebula = _boost_nebula(starless_rgb) if boost else starless_rgb

    # 5. Zusammenfügen (Screen-Blend bringt Sterne ohne Ausbrennen zurück)
    log("  5/5 Sterne zurück (Screen-Blend) …")
    final = 1.0 - (1.0 - nebula) * (1.0 - stars)
    final_bgr = cv2.cvtColor(np.clip(final, 0, 1).astype(np.float32), cv2.COLOR_RGB2BGR)

    out = os.path.join(work_dir, "result_starless.jpg")
    cv2.imwrite(out, np.clip(final_bgr * 255, 0, 255).astype(np.uint8),
                [int(cv2.IMWRITE_JPEG_QUALITY), 94])
    # Nebenprodukte mitspeichern (sternenlos + Sternebene) — nützlich fürs Weiterbearbeiten
    cv2.imwrite(os.path.join(work_dir, "result_starless_nebula.jpg"),
                np.clip(cv2.cvtColor(nebula.astype(np.float32), cv2.COLOR_RGB2BGR) * 255, 0, 255).astype(np.uint8),
                [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    log(f"  ✓ Starless-Workflow fertig: {os.path.basename(out)}")
    return out
