#!/usr/bin/env python3
"""
hdr.py — HDR aus Belichtungsreihen (AEB) per Exposure Fusion (Mertens).

Kein Tonemapping-Gefrickel: Die Mertens-Fusion verrechnet eine Belichtungsreihe (z. B. −1/0/+1 EV)
direkt zu EINEM gut durchgezeichneten Bild — Lichter aus den dunkleren, Schatten aus den helleren
Aufnahmen. Robust und natürlich, ganz ohne bekannte Belichtungszeiten. Optional MTB-Ausrichtung für
freihändige Reihen. Reine OpenCV/NumPy-Abhängigkeiten (MIT-kompatibel).

Wichtig: HDR (Belichtungsreihe) ≠ Fokus-Stacking (Schärfereihe) — zwei verschiedene Dinge.
"""
import numpy as np
import cv2


def _to8(img):
    """Nach 8-bit BGR (Mertens erwartet 8-bit-Bilder)."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.dtype == np.uint16:
        return (img / 256).astype(np.uint8)
    if img.dtype != np.uint8:
        return np.clip(img, 0, 255).astype(np.uint8)
    return img


def read_exposure_times(paths):
    """Echte Belichtungszeiten (Sekunden) aus dem EXIF lesen. Gibt ein float32-Array zurück, wenn
    für JEDES Bild eine Zeit gefunden wurde, sonst None (dann muss geschätzt werden). Korrekte
    Belichtungsverhältnisse sind für die Debevec-CRF-Kalibrierung entscheidend — geratene Zeiten
    lassen die Response-Kurven pro Farbkanal divergieren → Farbflecken in dunklen Bereichen."""
    if not paths:
        return None
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
    except Exception:
        return None
    times = []
    for p in paths:
        try:
            ex = Image.open(p)._getexif() or {}
            d = {TAGS.get(k, k): v for k, v in ex.items()}
            t = d.get("ExposureTime")
            if t is None:
                return None
            times.append(float(t))
        except Exception:
            return None
    if len(times) != len(paths) or any(t <= 0 for t in times):
        return None
    return np.asarray(times, np.float32)


def _denoise_chroma(bgr, strength=7):
    """Farbrauschen (grün-magenta Flecken) entfernen, Luminanz/Detail erhalten: nur die a/b-Kanäle
    im Lab-Raum glätten, der L-Kanal bleibt scharf. Genau das Mittel gegen die Chroma-Blobs, die
    Debevec+Tonemapping in verrauschten Nacht-Schatten erzeugt."""
    img = _to8(bgr)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L, a, b = cv2.split(lab)
    a = cv2.bilateralFilter(a, 0, strength, 9)
    b = cv2.bilateralFilter(b, 0, strength, 9)
    return cv2.cvtColor(cv2.merge([L, a, b]), cv2.COLOR_LAB2BGR)


def merge_exposures(images, align=True, deghost="off", flow=False, log=print):
    """Eine Belichtungsreihe (Liste BGR-Bilder mit unterschiedlicher Belichtung) zu einem
    durchgezeichneten 8-bit-Bild verschmelzen (Mertens Exposure Fusion).
    align=True richtet freihändige Reihen vorher rigide aus.
    deghost: 'off' | 'auto' | 'aggressive' — entfernt **Bewegungsgeister** (Blätter, Personen,
             Autos): in Bewegungszonen wird nur das best-belichtete Referenzbild genommen statt
             der Fusion (verhindert Doppelbilder bewegter Objekte).
    flow=True: statt in Bewegungszonen hart aufs Referenzbild umzuschalten, werden die anderen
             Belichtungen per optischem Fluss (Farnebäck) AUF die Referenz gewarpt und neu fusioniert
             → der HDR-Vorteil (Schatten/Lichter aus mehreren Belichtungen) bleibt auch in bewegten
             Zonen erhalten, statt dort auf eine einzelne Belichtung zu degradieren."""
    if not images:
        raise ValueError("keine Bilder")
    imgs = [_to8(im) for im in images]
    if len(imgs) == 1:
        return imgs[0]
    h, w = imgs[0].shape[:2]
    imgs = [cv2.resize(im, (w, h)) if im.shape[:2] != (h, w) else im for im in imgs]
    if align:
        # 1) Feature-basiert (rigide) — fängt Verschiebung UND Drehung der Freihand-Reihe ab.
        #    Belichtungsunterschiede stören ORB kaum (Matching auf normierten Graustufen).
        try:
            import stacker
            imgs = stacker.align_images(imgs, mode="rigid", log=lambda *a: None)
            log("    HDR: Belichtungen ausgerichtet (rigide)")
        except Exception as e:
            # 2) Fallback: MTB (nur Verschiebung, belichtungs-invariant)
            try:
                cv2.createAlignMTB().process(imgs, imgs)
                log(f"    HDR: rigide Ausrichtung fehlgeschlagen ({e}) → MTB")
            except Exception as e2:
                log(f"    HDR: Ausrichtung übersprungen ({e2})")
    # flow=True: bewegte Belichtungen vor der Fusion auf die Referenz warpen → Geister verschwinden,
    # ohne dass in Bewegungszonen auf eine einzelne Belichtung degradiert wird (HDR bleibt erhalten).
    if flow and deghost != "off" and len(imgs) >= 2:
        imgs = _flow_align_exposures(imgs, log=log)
    fused = cv2.createMergeMertens().process(imgs)      # float 0..1
    out = np.clip(fused * 255.0, 0, 255).astype(np.uint8)
    log(f"    HDR: {len(imgs)} Belichtungen verschmolzen (Exposure Fusion)")
    if deghost != "off" and not flow and len(imgs) >= 2:
        out = _deghost(imgs, out, aggressive=(deghost == "aggressive"), log=log)
    return out


def merge_radiance(images, times=None, tonemap="reinhard", log=print):
    """Echtes HDR über eine Radiance-Map (Debevec-CRF) + Tonemapping — **alternativer dramatischer
    Look** mit lokalem Kontrast (Exposure Fusion bleibt der Standard, halo-frei). Belichtungszeiten
    werden aus der mittleren Helligkeit geschätzt, wenn keine angegeben.
    tonemap: reinhard|mantiuk|drago|local. 'local' = lokal-adaptives Durand-Tonemapping (siehe
    tonemap_local) — komprimiert den globalen Kontrast, erhält feines lokales Detail."""
    imgs = [_to8(im) for im in images]
    if len(imgs) < 2:
        return imgs[0]
    h, w = imgs[0].shape[:2]
    imgs = [cv2.resize(im, (w, h)) if im.shape[:2] != (h, w) else im for im in imgs]
    if times is None:
        meds = [float(np.median(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY))) + 1.0 for im in imgs]
        base = float(np.median(meds))
        times = np.array([m / base for m in meds], np.float32)
        src = " (Belichtungszeiten geschätzt — ohne EXIF)"
    else:
        src = " (echte EXIF-Belichtungszeiten)"
    times = np.clip(np.asarray(times, np.float32), 1e-3, None)
    try:
        resp = cv2.createCalibrateDebevec().process(imgs, times)
        rad = cv2.createMergeDebevec().process(imgs, times, resp)
    except cv2.error:
        rad = cv2.createMergeDebevec().process(imgs, times)
    if tonemap == "local":
        # Durand-2002 lokal-adaptives Tonemapping direkt auf der linearen Radiance-Map.
        out = tonemap_local(rad, strength=1.0, log=log)
        out = _denoise_chroma(out)
        log(f"    HDR: Radiance-Map + lokales Tonemapping (Durand){src}")
        return out
    tm = {"mantiuk": cv2.createTonemapMantiuk(2.2, 0.85, 1.2),
          "drago": cv2.createTonemapDrago(1.0, 0.7),
          }.get(tonemap, cv2.createTonemapReinhard(1.5, 0, 0, 0))
    ldr = tm.process(rad)
    out = np.clip(np.nan_to_num(ldr) * 255.0, 0, 255).astype(np.uint8)
    out = _denoise_chroma(out)                          # grün-magenta Chroma-Flecken killen
    log(f"    HDR: Radiance-Map + Tonemapping ({tonemap}){src}")
    return out


def tonemap_local(hdr_or_bgr, strength=1.0, base_contrast=3.5, log=print):
    """Lokal-adaptives Tonemapping nach Durand & Dorsey 2002 (Fast Bilateral Filtering) — reiner
    OpenCV/NumPy-Weg, ohne ML. Liefert „Details-Enhancer"-Niveau (Photomatix-artig): der globale
    Kontrast wird komprimiert, das lokale Detail bleibt voll erhalten.

    Prinzip: Auf der LOG-Luminanz eine kantenerhaltende Bilateral-Zerlegung in
      • BASE  = grobe, großräumige Beleuchtung (Bilateralfilter)
      • DETAIL = Log-Luminanz − Base (feine Textur, lokaler Kontrast)
    Nur die BASE wird im Kontrast gestaucht (Faktor < 1), das DETAIL wird unangetastet (bzw. leicht
    betont) wieder aufaddiert → der riesige HDR-Dynamikumfang passt in 8 bit, ohne dass lokale
    Details verflachen. Die Farbe (Chrominanz) wird aus dem Verhältnis zur Original-Luminanz
    rekonstruiert (kein Farbstich).

    Eingabe: lineare Radiance-Map (float32, beliebiger Wertebereich, z. B. aus MergeDebevec) ODER
    ein gewöhnliches 8-/16-bit-BGR-Bild. Ausgabe immer 8-bit BGR.
    strength 0..~1.5 skaliert die Stärke der Kompression (1.0 = Standard, höher = flacher/dramatischer).
    base_contrast = Ziel-Kontrastumfang der Base in Log-Stops (kleiner = stärker komprimiert)."""
    img = np.asarray(hdr_or_bgr)
    if img.ndim == 2:
        img = cv2.cvtColor(img.astype(np.float32), cv2.COLOR_GRAY2BGR)
    f = img.astype(np.float32)
    # In lineare Radiance bringen: 8/16-bit → [0..1]; echte Radiance-Map bleibt linear.
    if img.dtype == np.uint8:
        f = f / 255.0
    elif img.dtype == np.uint16:
        f = f / 65535.0
    f = np.nan_to_num(f, nan=0.0, posinf=0.0, neginf=0.0)
    f = np.clip(f, 0.0, None)
    # Luminanz (BT.601 auf BGR) als Tonemapping-Träger; Farbe später aus dem Verhältnis zurück.
    lum = 0.114 * f[..., 0] + 0.587 * f[..., 1] + 0.299 * f[..., 2]
    eps = 1e-6
    lum = np.maximum(lum, eps)
    log_lum = np.log10(lum)
    # Bilateral-Zerlegung der Log-Luminanz. sigma_space an die Bildgröße gekoppelt (≈2 % der kurzen
    # Kante, Durand-Empfehlung), sigma_color an die Streuung der Log-Werte.
    h, w = log_lum.shape[:2]
    sigma_space = max(4.0, min(h, w) * 0.02)
    d = int(max(5, round(sigma_space * 1.5))) | 1
    spread = float(log_lum.max() - log_lum.min()) + eps
    sigma_color = max(0.1, 0.4 * spread)
    base = cv2.bilateralFilter(log_lum.astype(np.float32), d, sigma_color, sigma_space)
    detail = log_lum - base
    # Base-Kontrast in einen festen Log-Umfang stauchen (Durand: compressionfactor).
    base_min, base_max = float(base.min()), float(base.max())
    base_range = (base_max - base_min) + eps
    target_range = base_contrast / max(0.2, strength)   # strength↑ → kleinerer Zielumfang = flacher
    gamma = float(min(1.0, target_range / base_range))  # nie aufspreizen, nur komprimieren
    # Absolutskala so wählen, dass die hellsten Werte auf ~0 (Log) = 1.0 (linear) liegen.
    new_log = (base - base_max) * gamma + detail
    out_lum = np.power(10.0, new_log)                    # zurück in linearen Raum, Weiß ≈ 1.0
    out_lum = np.clip(out_lum, 0.0, None)
    # Farbe erhalten: jeden Kanal mit dem Luminanz-Verhältnis skalieren (Durand-Farbrekonstruktion).
    ratio = (out_lum / lum)[..., None]
    out = f * ratio
    # Dezenter Gamma fürs Display (lineare Radiance → sRGB-artig) und robuste 99.5%-Normierung.
    norm = float(np.percentile(out, 99.5)) + eps
    out = np.clip(out / norm, 0.0, 1.0)
    out = np.power(out, 1.0 / 2.2)
    log(f"    HDR: lokales Tonemapping (Durand) — Base-Kompression γ={gamma:.2f}, σ_space={sigma_space:.0f}px")
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def _grad_mag(g):
    """Gradientenbetrag (Sobel) einer Graustufe — der STRUKTUR-Raum fürs Deghosting. Unempfindlicher
    gegen reine Helligkeitsunterschiede der Belichtungen als Roh-RGB; reagiert auf echte Bewegung
    (verschobene Kanten/Objekte)."""
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


def _deghost(imgs, fused, aggressive=False, log=print):
    """In Bewegungszonen die Fusion durch das best-belichtete Referenzbild ersetzen.
    Referenz = Frame mit den meisten gut belichteten Pixeln.

    Verbessert: Die Bewegung wird im **Gradienten-/Strukturraum** statt im Roh-RGB gemessen (robust
    gegen reine Belichtungsunterschiede) und der Schwellwert wird **adaptiv aus der Statistik der
    Abweichung** bestimmt (Median + κ·MAD) statt fix — passt sich an Szene/Rauschen an. Maske
    gefeathert. `aggressive` senkt den κ-Faktor (mehr wird als Bewegung erkannt)."""
    grays = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in imgs]
    well = [float(((g > 13) & (g < 242)).mean()) for g in grays]
    ri = int(np.argmax(well))
    ref = imgs[ri].astype(np.float32)
    refg = grays[ri].astype(np.float32) + 1e-3
    ref_grad = _grad_mag(refg)
    kappa = (2.5 if aggressive else 4.0)                        # adaptiver MAD-Faktor
    motion = np.zeros(fused.shape[:2], np.float32)
    for i, im in enumerate(imgs):
        if i == ri:
            continue
        g = grays[i].astype(np.float32) + 1e-3
        gain = float(np.median(refg)) / float(np.median(g))     # Helligkeit an Referenz angleichen
        matched = np.clip(g * gain, 0, 255)
        # Differenz im Strukturraum: Gradient des angeglichenen Frames vs. Referenz.
        dev = np.abs(_grad_mag(matched) - ref_grad)
        med = float(np.median(dev))
        mad = float(np.median(np.abs(dev - med))) * 1.4826 + 1e-6
        thr = med + kappa * mad                                 # adaptive Schwelle (Otsu/MAD-Stil)
        motion = np.maximum(motion, (dev > thr).astype(np.float32))
    motion = cv2.morphologyEx(motion, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    motion = cv2.morphologyEx(motion, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    motion = cv2.GaussianBlur(motion, (0, 0), 4.0)[..., None]
    frac = float(motion.mean())
    log(f"    HDR: Deghosting (Gradientenraum, adaptiv) — {frac*100:.1f}% Bewegungszone → Referenzbild")
    res = fused.astype(np.float32) * (1 - motion) + ref * motion
    return np.clip(res, 0, 255).astype(np.uint8)


def _flow_align_exposures(imgs, log=print):
    """Alle Belichtungen per dichtem optischem Fluss (Farnebäck) auf die best-belichtete Referenz
    warpen (HDR-Deghosting OHNE Verlust des Mehrbelichtungs-Vorteils). Der Fluss wird auf den
    helligkeits-angeglichenen Graustufen geschätzt (sonst „sieht" der Fluss nur den Belichtungs-
    unterschied), dann wird das FARB-Bild mit remap auf die Referenz gezogen. Gibt eine neue
    Liste 8-bit-BGR zurück (Referenz unverändert), die anschließend regulär fusioniert wird."""
    grays = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in imgs]
    well = [float(((g > 13) & (g < 242)).mean()) for g in grays]
    ri = int(np.argmax(well))
    refg = grays[ri].astype(np.float32) + 1e-3
    h, w = refg.shape
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    out = []
    warped_cnt = 0
    for i, im in enumerate(imgs):
        if i == ri:
            out.append(im)
            continue
        g = grays[i].astype(np.float32) + 1e-3
        gain = float(np.median(refg)) / float(np.median(g))     # Helligkeit angleichen für den Fluss
        matched = np.clip(g * gain, 0, 255).astype(np.uint8)
        flow = cv2.calcOpticalFlowFarneback(
            np.clip(refg, 0, 255).astype(np.uint8), matched, None,
            0.5, 3, 21, 3, 5, 1.2, 0)                            # Referenz→Frame-Fluss
        mapx = (gx + flow[..., 0]).astype(np.float32)
        mapy = (gy + flow[..., 1]).astype(np.float32)
        warped = cv2.remap(im, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        out.append(warped)
        warped_cnt += 1
    log(f"    HDR: {warped_cnt} Belichtung(en) per optischem Fluss auf die Referenz gewarpt (Flow-Deghosting)")
    return out


def apply_look(bgr, preset="natural"):
    """Treuer Tonlook für HDR/Exposure-Fusion (die von Natur aus flach wirkt). Kein Erfinden von
    Inhalten — nur klassische Tonwert-/Kontrastbearbeitung im LAB-Raum:
      • Schwarzpunkt anheben (Tiefe)  • Kontrast-S-Kurve (Sigmoid, pinnt 0/1)
      • Clarity (lokaler Kontrast via großem Unsharp auf L)  • Sättigung
      • „dramatisch" zusätzlich CLAHE (adaptiver lokaler Kontrast).
    presets: neutral (aus), natural (Standard, dezent), vivid (kräftig), dramatic (stark)."""
    P = {
        "neutral":  dict(black=0.00, contrast=0.0, clarity=0.00, sat=1.00, clahe=0.0),
        "natural":  dict(black=0.015, contrast=3.0, clarity=0.18, sat=1.08, clahe=0.0),
        "vivid":    dict(black=0.030, contrast=4.5, clarity=0.32, sat=1.20, clahe=0.0),
        "dramatic": dict(black=0.045, contrast=5.5, clarity=0.45, sat=1.28, clahe=2.0),
    }
    p = P.get(preset, P["natural"])
    if preset == "neutral":
        return bgr
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0] / 255.0
    if p["black"] > 0:                                   # Schwarzpunkt → etwas Tiefe
        L = np.clip((L - p["black"]) / (1.0 - p["black"]), 0, 1)
    k = p["contrast"]
    if k > 0:                                            # Sigmoid-S-Kurve, pinnt 0 und 1
        s = lambda x: 1.0 / (1.0 + np.exp(-k * (x - 0.5)))
        s0, s1 = s(0.0), s(1.0)
        L = (s(L) - s0) / (s1 - s0)
    if p["clarity"] > 0:                                 # lokaler Kontrast (großer Radius = Halo-arm)
        sigma = max(3.0, min(L.shape[:2]) / 50.0)
        blur = cv2.GaussianBlur(L, (0, 0), sigma)
        L = np.clip(L + p["clarity"] * (L - blur), 0, 1)
    Lb = np.clip(L * 255.0, 0, 255).astype(np.uint8)
    if p["clahe"] > 0:
        Lb = cv2.createCLAHE(clipLimit=p["clahe"], tileGridSize=(8, 8)).apply(Lb)
    lab[..., 0] = Lb.astype(np.float32)
    if p["sat"] != 1.0:                                  # Sättigung über a/b-Kanäle
        lab[..., 1] = np.clip(128 + (lab[..., 1] - 128) * p["sat"], 0, 255)
        lab[..., 2] = np.clip(128 + (lab[..., 2] - 128) * p["sat"], 0, 255)
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def _exposure_time(path):
    """Belichtungszeit (Sekunden) aus EXIF, oder None."""
    try:
        import subprocess
        import json
        out = subprocess.run(["exiftool", "-j", "-n", "-ExposureTime", path],
                             capture_output=True, text=True).stdout
        return float(json.loads(out)[0].get("ExposureTime"))
    except Exception:
        return None


def split_brackets(paths, size=0, log=print):
    """Eine Dateiliste in einzelne Belichtungsreihen aufteilen.
    size>0: feste Gruppengröße (z. B. 3 für klassisches AEB).
    size=0: automatisch — neue Reihe, sobald die Belichtungszeit deutlich zurückspringt
            (Reihe startet wieder bei der kürzesten/dunkelsten Belichtung). Klappt EXIF nicht,
            wird die gesamte Liste als EINE Reihe behandelt."""
    if size and size > 0:
        groups = [paths[i:i + size] for i in range(0, len(paths), size)]
        return [g for g in groups if len(g) >= 2]
    evs = [_exposure_time(p) for p in paths]
    if any(e is None or e <= 0 for e in evs):
        return [paths]                                   # EXIF unklar → eine Reihe
    groups, cur = [], [paths[0]]
    for i in range(1, len(paths)):
        # deutlicher Sprung nach unten (lange → kurze Belichtung) = neue Reihe beginnt
        if evs[i] < evs[i - 1] * 0.5:
            groups.append(cur)
            cur = [paths[i]]
        else:
            cur.append(paths[i])
    groups.append(cur)
    groups = [g for g in groups if len(g) >= 2]
    log(f"    HDR: {len(groups)} Belichtungsreihe(n) erkannt")
    return groups or [paths]
