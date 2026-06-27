#!/usr/bin/env python3
"""
starless.py — Starless-Workflow (Sterne trennen, Nebel bearbeiten, zusammenfügen).

Der „Profi-Weg" für Astro, voll automatisiert. KERN-REGEL: Bearbeitungs-Filter wirken NIEMALS auf
die Sterne — die werden zuerst getrennt, bleiben unangetastet und kommen erst am Schluss zurück.

  1. Strecken + Palette (HOO/SHO/… oder Breitband) — StarNet braucht ein gestrecktes Bild.
  2. StarNet++ — Sterne entfernen → sternenloses Nebelbild + UNBEARBEITETE Sternebene.
  3. GraXpert — Hintergrund/Gradient + KI-Entrauschen, NUR auf dem sternenlosen Nebel
     (auf den Sternen würde das sie weichzeichnen/aufblähen → nie).
  4. Nebel verstärken/Farben — lokaler Kontrast + Sättigung, ebenfalls nur sternenlos.
  5. Zusammenfügen — die unbearbeiteten Sterne per Screen-Blend zurück: 1−(1−Nebel)·(1−Sterne).

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


def _boost_nebula(neb, lift=3.5, contrast=0.6, saturation=1.25, core_lo=0.62):
    """Sternenlosen Nebel **kernschonend** verstärken: schwache/mittlere Bereiche werden per
    asinh-Lift kräftig angehoben, der bereits helle Kern bleibt UNVERÄNDERT (sonst brennt er aus).
    Danach lokaler Kontrast (Unsharp) für Struktur + dezente Sättigung. Geht nur, weil keine Sterne
    drin sind (die würden sonst aufblähen)."""
    lum = neb.mean(axis=2, keepdims=True)
    boosted = np.arcsinh(neb * lift) / np.arcsinh(lift)         # hebt schwach/mittel deutlich an
    core = np.clip((lum[..., 0] - core_lo) / (1.0 - core_lo), 0, 1)   # 1 im hellen Kern
    core = cv2.GaussianBlur(core, (0, 0), 4)[..., None]         # weicher Übergang
    out = neb * core + boosted * (1.0 - core)                  # Kern unverändert, Rest gehoben
    blur = cv2.GaussianBlur(out, (0, 0), 8)
    out = np.clip(out + (out - blur) * contrast, 0, 1)         # lokaler Kontrast
    lum2 = out.mean(axis=2, keepdims=True)
    return np.clip(lum2 + (out - lum2) * saturation, 0, 1)


def run(linear_path, palette, work_dir, broadband=False, graxpert_path=None, starnet_path=None,
        boost=True, strength=6.0, saturation=1.05, ai_sharpen=True, cosmicclarity_path=None,
        ai_aberration=False, siril_path=None, log=print):
    """Vollen Starless-Workflow ausführen. Gibt den Pfad zum fertigen JPG zurück.

    linear_path : 32-bit-lineares Stack-Ergebnis (TIFF/FITS).
    palette     : 'hoo'/'sho'/'foraxx'/'bicolor' oder None/'broadband' für Breitband.
    Schritte mit fehlendem Tool werden übersprungen (GraXpert optional; ohne StarNet entfällt
    die Stern-Trennung — dann nur Strecken)."""
    os.makedirs(work_dir, exist_ok=True)
    pal = None if (broadband or not palette) else palette
    import tifffile

    # 1. Strecken + Palette (StarNet braucht ein gestrecktes Bild). NOCH KEINE Bearbeitungs-Filter.
    log(f"  1/5 Strecken + Palette ({pal or 'Breitband'}) …")
    bgr = astro._read_float(linear_path)
    stretched = astro.autostretch(_palette_view(bgr, pal), strength=strength, saturation=saturation)
    # Hintergrund EXAKT farbneutral ziehen — der Stretch bläst sonst winzige Kanal-Differenzen zum
    # Blau-/Grünstich auf (wie in der Haupt-Pipeline). Muss VOR StarNet passieren, damit die
    # Sternebene aus dem neutralen Bild kommt.
    stretched = astro.neutralize_background(astro.remove_green_cast(stretched))
    # Optional: KI-Stern-/Aberrationskorrektur (Siril AberrationRemover, headless) VOR StarNet —
    # rundet verzogene Rand-Sterne. Wirkt auf Sterne (ist eine STERN-Korrektur, kein Nebel-Filter).
    if ai_aberration:
        try:
            import siril_pyscript
            if siril_pyscript.available("AberrationRemover.py", siril_path):
                log("  1b/5 Siril AberrationRemover: Sternformen korrigieren …")
                stretched = siril_pyscript.aberration_remover(stretched, strength=0.6, siril_path=siril_path)
        except Exception as e:
            log(f"      AberrationRemover übersprungen ({e})")

    # ohne StarNet: hier ist Schluss (nur gestrecktes Bild) — der Starless-Weg braucht StarNet.
    if not tools_engine.find_starnet(starnet_path):
        out = os.path.join(work_dir, "result_stretched.jpg")
        cv2.imwrite(out, np.clip(stretched * 255, 0, 255).astype(np.uint8),
                    [int(cv2.IMWRITE_JPEG_QUALITY), 94])
        log("      StarNet++ nicht gefunden — Sterntrennung entfällt (nur gestreckt).")
        return out

    # 2. StarNet: Sterne entfernen → sternenloses Bild + UNBEARBEITETE Sternebene.
    #    Ab hier wirken ALLE Filter (GraXpert, Boost, Farbe) NUR auf den sternenlosen Nebel —
    #    die Sterne (`stars`) bleiben bis zum Schluss komplett unangetastet.
    log("  2/5 StarNet++: Sterne entfernen …")
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
    stretched_rgb = np.clip(cv2.cvtColor(stretched.astype(np.float32), cv2.COLOR_BGR2RGB), 0, 1)
    stars = np.clip(stretched_rgb - starless_rgb, 0, 1)      # PRISTINE Sternebene — nie bearbeitet

    # 3. GraXpert (Hintergrund + KI-Entrauschen) — AUSSCHLIESSLICH auf dem sternenlosen Nebel.
    #    Auf den Sternen würde Denoise/Background sie weichzeichnen/aufblähen → niemals.
    if tools_engine.find_graxpert(graxpert_path):
        try:
            log("  3/5 GraXpert (Hintergrund + Entrauschen) — nur sternenlos …")
            sl_tif = os.path.join(work_dir, "starless_for_graxpert.tif")
            tifffile.imwrite(sl_tif, (np.clip(starless_rgb, 0, 1) * 65535).astype(np.uint16),
                             photometric="rgb")
            gx_out = tools_engine.run_graxpert_enhance(sl_tif, path=graxpert_path, denoise=True, log=log)
            g = tifffile.imread(gx_out).astype(np.float32)
            g = g / 65535.0 if g.max() > 1.5 else g
            if g.ndim == 2:
                g = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
            if g.shape[:2] != starless_rgb.shape[:2]:
                g = cv2.resize(g, (starless_rgb.shape[1], starless_rgb.shape[0]))
            starless_rgb = np.clip(g, 0, 1)
        except Exception as e:
            log(f"      GraXpert übersprungen ({e})")

    # 3b. KI-Schärfung (Cosmic Clarity = freie BlurXTerminator-Alternative) — NUR sternenlos,
    #     Modus „Non-Stellar Only" (Nebel-Dekonvolution). Auf Sternen würde Schärfung sie verziehen.
    if ai_sharpen:
        try:
            import cosmicclarity_engine
            if cosmicclarity_engine.available(cosmicclarity_path):
                log("  3b/5 Cosmic Clarity: KI-Schärfung (sternenlos, Non-Stellar) …")
                sl_bgr = cv2.cvtColor(starless_rgb.astype(np.float32), cv2.COLOR_RGB2BGR)
                sl_bgr = cosmicclarity_engine.sharpen(sl_bgr, mode="Non-Stellar Only",
                                                      path=cosmicclarity_path, log=log)
                starless_rgb = np.clip(cv2.cvtColor(sl_bgr.astype(np.float32), cv2.COLOR_BGR2RGB), 0, 1)
        except Exception as e:
            log(f"      Cosmic Clarity übersprungen ({e})")

    # 4. Nebel-Farben/Boost — ebenfalls nur sternenlos.
    log("  4/5 Nebel verstärken/Farben (sternenlos) …")
    nebula = _boost_nebula(starless_rgb) if boost else starless_rgb

    # Ebenen cachen (16-bit), damit Nebel-/Stern-Stärke SPÄTER ohne neues StarNet einstellbar sind.
    import tifffile as _tf
    def _save16(name, rgb):
        _tf.imwrite(os.path.join(work_dir, name),
                    (np.clip(rgb, 0, 1) * 65535).astype(np.uint16), photometric="rgb")
    _save16("layer_starless.tif", starless_rgb)   # roh (ohne Boost) — für „dezenter"
    _save16("layer_nebula.tif", nebula)           # mit Boost
    _save16("layer_stars.tif", stars)             # Sternebene

    # 5. Zusammenfügen mit Standard-Stärken
    log("  5/5 Sterne zurück (Screen-Blend) …")
    out = recombine(work_dir, neb_amt=1.0, star_amt=1.0, log=log)
    log(f"  ✓ Starless-Workflow fertig: {os.path.basename(out)}")
    return out


def recombine(work_dir, neb_amt=1.0, star_amt=1.0, log=print):
    """Aus den gecachten Ebenen (layer_starless/nebula/stars) das Endbild SOFORT neu mischen —
    ohne StarNet erneut laufen zu lassen. So sind Nebel-Boost und Stern-Stärke einstellbar:

    neb_amt  : 0 = flacher (sternenloser) Nebel ohne Boost · 1 = voller Boost (Standard).
    star_amt : 0 = keine Sterne · 1 = volle Sterne (Standard) · >1 = kräftiger.
    Gibt den Pfad zum result_starless.jpg zurück."""
    import tifffile
    sl = tifffile.imread(os.path.join(work_dir, "layer_starless.tif")).astype(np.float32) / 65535.0
    neb = tifffile.imread(os.path.join(work_dir, "layer_nebula.tif")).astype(np.float32) / 65535.0
    stars = tifffile.imread(os.path.join(work_dir, "layer_stars.tif")).astype(np.float32) / 65535.0
    nebula = np.clip(sl * (1.0 - neb_amt) + neb * neb_amt, 0, 1)          # Boost ein-/ausblenden
    st = np.clip(stars * float(star_amt), 0, 1)                           # Stern-Stärke
    final = 1.0 - (1.0 - nebula) * (1.0 - st)                            # Screen → Sterne zurück
    final_bgr = cv2.cvtColor(np.clip(final, 0, 1).astype(np.float32), cv2.COLOR_RGB2BGR)
    out = os.path.join(work_dir, "result_starless.jpg")
    cv2.imwrite(out, np.clip(final_bgr * 255, 0, 255).astype(np.uint8),
                [int(cv2.IMWRITE_JPEG_QUALITY), 94])
    return out
