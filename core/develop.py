#!/usr/bin/env python3
"""
develop.py — RAW-Entwicklungs-/Editor-Primitive (RawTherapee/darktable-Niveau, treu/nicht-generativ).

Enthält die hochwertigen Bausteine, die ForgePix' Editor bisher fehlten:
  • highlight_reconstruct — ausgebrannte Lichter rekonstruieren (Kanal-Verhältnis-Füllung +
    Entsättigen-zu-Weiß gegen magenta Lichter)
  • tone_curve_lut / apply_lut — Tonwertkurve (PCHIP-Punkt-Kurve, ohne Überschwingen)
  • fast_denoise — kantenerhaltendes Entrauschen (Non-Local-Means, Luma/Chroma)
  • gradient_mask / radial_mask / refine_mask — lokale Anpassungs-Masken (Smoothstep + Guided Filter)

Schärfung (Wavelet/Unsharp) liegt in wavelet.py. Reine OpenCV/NumPy(/scipy)-Abhängigkeiten.
"""
import numpy as np
import cv2


def _as_float(img):
    if img.dtype == np.uint16:
        return img.astype(np.float32) / 65535.0, np.uint16, 65535.0
    if img.dtype == np.uint8:
        return img.astype(np.float32) / 255.0, np.uint8, 255.0
    return img.astype(np.float32), np.float32, 1.0


def highlight_reconstruct(img, thresh=0.92, sigma=8.0):
    """Ausgebrannte Lichter rekonstruieren. Für teil-geclippte Pixel werden geclippte Kanäle aus
    dem maskierten Weichzeichner der ungeclippten Nachbarn desselben Kanals gefüllt (LCh-artig);
    voll ausgebrannte Pixel werden zu **neutralem Weiß** gezogen (gegen den magenta Lichter-Stich,
    den rohes Clipping erzeugt). Treu, kein Erfinden von Struktur."""
    f, dtype, maxv = _as_float(img)
    if f.ndim != 3:
        return img
    out = f.copy()
    for c in range(3):
        ch = f[..., c]
        clipped = ch >= thresh
        if not clipped.any():
            continue
        valid = (~clipped).astype(np.float32)
        num = cv2.GaussianBlur(ch * valid, (0, 0), sigma)
        den = cv2.GaussianBlur(valid, (0, 0), sigma) + 1e-6
        filled = num / den
        out[..., c] = np.where(clipped, np.maximum(ch, filled), ch)
    anyclip = (f >= thresh).any(axis=2)
    if anyclip.any():
        mx = out.max(axis=2, keepdims=True)
        neutral = np.maximum(out, mx * 0.92)                  # Kanäle Richtung Pixel-Maximum → weiß
        m = anyclip[..., None]
        out = np.where(m, neutral, out)
    out = np.clip(out, 0, 1)
    return (out * maxv).astype(dtype) if dtype != np.float32 else out


def tone_curve_lut(points, bits=16):
    """Monotone PCHIP-Punkt-Kurve → LUT (kein Überschwingen, anders als natürlicher Spline).
    points: Liste (x,y) in [0,1], (0,0)/(1,1) werden ergänzt."""
    try:
        from scipy.interpolate import PchipInterpolator
        pts = dict(points)
        pts.setdefault(0.0, 0.0); pts.setdefault(1.0, 1.0)
        xs = np.array(sorted(pts)); ys = np.array([pts[x] for x in xs])
        spl = PchipInterpolator(xs, ys)
        n = 1 << bits
        grid = np.linspace(0, 1, n)
        return np.clip(spl(grid), 0, 1).astype(np.float32)
    except Exception:
        n = 1 << bits
        return np.linspace(0, 1, n, dtype=np.float32)


def apply_lut(img, lut01):
    """LUT (float [0,1], Länge 2^bits) auf das Bild anwenden — auf der Luminanz, Farbe erhalten."""
    f, dtype, maxv = _as_float(img)
    n = len(lut01)
    if f.ndim == 3:
        y = 0.114 * f[..., 0] + 0.587 * f[..., 1] + 0.299 * f[..., 2]
        idx = np.clip(y * (n - 1), 0, n - 1).astype(np.int32)
        gain = np.where(y > 1e-4, lut01[idx] / np.maximum(y, 1e-4), 1.0)[..., None]
        out = np.clip(f * gain, 0, 1)
    else:
        idx = np.clip(f * (n - 1), 0, n - 1).astype(np.int32)
        out = lut01[idx]
    return (out * maxv).astype(dtype) if dtype != np.float32 else out


def fast_denoise(img, luma=7.0, chroma=10.0):
    """Kantenerhaltendes Entrauschen (Non-Local-Means, getrennt Luma/Chroma). Schnell genug für
    die Vorschau. Für stärkstes Entrauschen multiskalig → wavelet.wavelet_denoise."""
    f, dtype, maxv = _as_float(img)
    u8 = (np.clip(f, 0, 1) * 255).astype(np.uint8)
    if u8.ndim == 3:
        d = cv2.fastNlMeansDenoisingColored(u8, None, float(luma), float(chroma), 7, 21)
    else:
        d = cv2.fastNlMeansDenoising(u8, None, float(luma), 7, 21)
    out = d.astype(np.float32) / 255.0
    return (out * maxv).astype(dtype) if dtype != np.float32 else out


def local_contrast(img, amount=0.5, scales=4, protect=0.2):
    """Lokaler Kontrast-Equalizer (darktable/RawTherapee-Stil): hebt den Kontrast je Detailgröße
    getrennt an — über mehrere Skalen (Laplace-Pyramide auf der Luminanz). Anders als globaler
    Kontrast oder ein einzelnes Unsharp arbeitet das gleichmäßig über grobe UND feine Strukturen
    und bleibt dabei halo-arm (große Radien werden sanfter angehoben).

      amount  = Stärke (0..~1.5)
      scales  = Anzahl Detailskalen (mehr = auch gröbere Strukturen)
      protect = Schutz von Lichtern/Tiefen 0..0.5 (gegen Clipping/Verstärkung von Rauschen im Dunkeln)

    Treu/nicht-generativ — nur Tonwert/lokaler Kontrast, keine erfundenen Inhalte."""
    f, dtype, maxv = _as_float(img)
    if f.ndim == 3:
        lab = cv2.cvtColor(np.clip(f, 0, 1).astype(np.float32), cv2.COLOR_BGR2LAB)
        L = lab[..., 0] / 100.0
    else:
        L = np.clip(f, 0, 1).astype(np.float32)
    base = L.copy()
    out = L.copy()
    sigma = 2.0
    for s in range(int(max(1, scales))):                 # Detailbänder via Difference-of-Gaussians
        blur = cv2.GaussianBlur(base, (0, 0), sigma)
        detail = base - blur                              # Detail dieser Skala
        gain = amount * (0.6 ** s)                        # gröbere Skalen sanfter (halo-arm)
        out = out + gain * detail
        base = blur
        sigma *= 2.0
    if protect and protect > 0:                           # Lichter/Tiefen schützen (Glocken-Gewicht um 0.5)
        wmid = 1.0 - np.abs(L - 0.5) * 2.0
        wmid = np.clip(wmid, protect, 1.0)
        out = L + (out - L) * wmid
    out = np.clip(out, 0, 1)
    if f.ndim == 3:
        lab[..., 0] = out * 100.0
        res = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    else:
        res = out
    res = np.clip(res, 0, 1)
    return (res * maxv).astype(dtype) if dtype != np.float32 else res


def capture_sharpen(img, sigma=0.7, iterations=12, protect=0.9):
    """Capture-Sharpening per Richardson-Lucy-Dekonvolution (wie RawTherapee „Capture Sharpening"):
    macht die Aufnahme-Unschärfe (Demosaicing + AA-Filter + leichtes Seeing) rückgängig — holt ECHTE
    Auflösung zurück, nicht nur Kantenkontrast wie Unsharp-Mask. Gauß-PSF (sigma in Pixeln), auf der
    Luminanz, mit weichem Lichter-Schutz (protect) gegen Überschwinger an hellen Kanten. Treu."""
    f, dtype, maxv = _as_float(img)
    if iterations < 1 or sigma <= 0:
        return img
    k = cv2.getGaussianKernel(int(max(3, round(sigma * 6)) | 1), sigma)
    psf = (k @ k.T).astype(np.float32); psf /= psf.sum()
    psf_m = psf[::-1, ::-1].copy()
    lum = (cv2.cvtColor(np.clip(f, 0, 1).astype(np.float32), cv2.COLOR_BGR2GRAY)
           if f.ndim == 3 else np.clip(f, 0, 1).astype(np.float32))
    obs = np.clip(lum, 1e-4, None)
    est = obs.copy()
    for _ in range(int(iterations)):
        conv = cv2.filter2D(est, -1, psf, borderType=cv2.BORDER_REFLECT)
        est = est * cv2.filter2D(obs / np.maximum(conv, 1e-6), -1, psf_m, borderType=cv2.BORDER_REFLECT)
        est = np.clip(est, 0, None)
    ratio = np.clip(est / np.maximum(lum, 1e-4), 0.3, 3.0)
    out = f.astype(np.float32) * ratio[..., None] if f.ndim == 3 else f.astype(np.float32) * ratio
    if protect is not None and protect < 1.0:               # Lichter weich schützen
        hi = cv2.GaussianBlur(np.clip((lum - protect) / max(1e-3, 1 - protect), 0, 1), (0, 0), 2.0)
        m = hi[..., None] if out.ndim == 3 else hi
        out = out * (1 - m) + f.astype(np.float32) * m
    out = np.clip(out, 0, 1)
    return (out * maxv).astype(dtype) if dtype != np.float32 else out


def dehaze(img, strength=1.0, omega=0.9, patch=15):
    """Dunst-/Schleier-Entfernung über den **Dark-Channel-Prior** (He et al. 2009 — wie RawTherapee/
    darktable „Haze removal"): in dunstfreien Außenbereichen ist in jedem Patch mindestens ein
    Farbkanal sehr dunkel; Dunst hebt dieses Minimum an. Daraus werden Atmosphärenlicht und
    Transmission geschätzt, die Transmission wird (Guided Filter, falls verfügbar) kantentreu
    verfeinert, dann das dunstfreie Bild rekonstruiert. strength 0..1 blendet zum Original. Treu."""
    f, dtype, maxv = _as_float(img)
    if f.ndim != 3 or strength <= 0:
        return img
    f = np.clip(f, 0, 1).astype(np.float32)
    dark = cv2.erode(f.min(axis=2), cv2.getStructuringElement(cv2.MORPH_RECT, (patch, patch)))
    flat = dark.ravel()
    n = max(1, int(flat.size * 0.001))
    idx = np.argpartition(flat, -n)[-n:]                    # hellste 0.1% des Dark Channels
    g = cv2.cvtColor((f * 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).ravel()
    A = f.reshape(-1, 3)[idx][np.argmax(g[idx])]            # Atmosphärenlicht
    A = np.clip(A, 1e-3, 1.0)
    t = 1.0 - omega * cv2.erode((f / A).min(axis=2),
                                cv2.getStructuringElement(cv2.MORPH_RECT, (patch, patch)))
    try:                                                    # Transmission kantentreu verfeinern
        t = cv2.ximgproc.guidedFilter(cv2.cvtColor((f * 255).astype(np.uint8), cv2.COLOR_BGR2GRAY),
                                      t.astype(np.float32), 40, 1e-3)
    except Exception:
        t = cv2.GaussianBlur(t, (0, 0), 8)
    t = np.clip(t, 0.1, 1.0)[..., None]
    out = (f - A) / t + A
    out = np.clip(out, 0, 1)
    s = float(min(1.0, max(0.0, strength)))
    out = f * (1 - s) + out * s
    return (np.clip(out, 0, 1) * maxv).astype(dtype) if dtype != np.float32 else np.clip(out, 0, 1)


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 + 1e-12), 0, 1)
    return t * t * (3 - 2 * t)


def gradient_mask(shape, cx, cy, angle_deg, feather=0.3):
    """Verlaufs-Maske (0..1): linearer Übergang senkrecht zur Achse durch (cx,cy). feather in
    Anteil der Bilddiagonale."""
    h, w = shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    a = np.deg2rad(angle_deg)
    d = (xs - cx) * np.cos(a) + (ys - cy) * np.sin(a)
    fw = feather * np.hypot(h, w)
    return _smoothstep(-fw / 2, fw / 2, d).astype(np.float32)


def radial_mask(shape, cx, cy, rx, ry, feather=0.3):
    """Radial-/Ellipsen-Maske (1 innen, 0 außen) mit weichem Rand."""
    h, w = shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((xs - cx) / max(rx, 1e-6)) ** 2 + ((ys - cy) / max(ry, 1e-6)) ** 2)
    return (1.0 - _smoothstep(1.0 - feather, 1.0, r)).astype(np.float32)


def refine_mask(mask, guide_img, radius=16, eps=1e-3):
    """Maske kanten-treu an die Bildkanten anschmiegen (Guided Filter), falls verfügbar."""
    try:
        g = cv2.cvtColor(guide_img, cv2.COLOR_BGR2GRAY) if guide_img.ndim == 3 else guide_img
        g = g.astype(np.float32) / (65535.0 if g.dtype == np.uint16 else 255.0) \
            if g.dtype != np.float32 else g
        return cv2.ximgproc.guidedFilter(g, mask.astype(np.float32), radius, eps)
    except Exception:
        return cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 3.0)


def _lensfun_auto(f, exif_path, log=print):
    """Automatische Objektivkorrektur über die lensfun-Datenbank (Vignette + Verzeichnung + TCA),
    anhand der Kamera-/Objektiv-Angaben aus den EXIF-Daten. Nur aktiv, wenn lensfunpy installiert
    UND Kamera/Objektiv in der Datenbank gefunden werden. Gibt (korrigiert, True) oder (f, False)."""
    try:
        import lensfunpy
        import subprocess
        import json
        meta = json.loads(subprocess.run(
            ["exiftool", "-j", "-n", "-Make", "-Model", "-LensModel", "-FocalLength",
             "-FNumber", "-FocusDistance", exif_path], capture_output=True, text=True).stdout)[0]
        db = lensfunpy.Database()
        cams = db.find_cameras(meta.get("Make", ""), meta.get("Model", ""))
        lenses = db.find_lenses(cams[0], None, meta.get("LensModel", "")) if cams else []
        if not cams or not lenses:
            log("    Objektivkorrektur: Kamera/Objektiv nicht in lensfun-DB → manuelle Parameter")
            return f, False
        h, w = f.shape[:2]
        mod = lensfunpy.Modifier(lenses[0], cams[0].crop_factor, w, h)
        mod.initialize(float(meta.get("FocalLength", 0) or 50),
                       float(meta.get("FNumber", 0) or 8),
                       float(meta.get("FocusDistance", 0) or 1000))
        out = f.copy()
        try:
            mod.apply_color_modification(out)            # Vignette
        except Exception:
            pass
        coords = mod.apply_geometry_distortion()         # Verzeichnung (+TCA, falls Profil)
        if coords is not None:
            out = cv2.remap(out, coords, None, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
        log(f"    Objektivkorrektur (lensfun): {lenses[0].model}")
        return np.clip(out, 0, 1), True
    except Exception as e:
        log(f"    lensfun nicht verfügbar/anwendbar ({e}) → manuelle Parameter")
        return f, False


def lens_correct(img, vignette=0.0, distortion=0.0, ca=0.0, auto=False, exif_path=None, log=print):
    """Objektivkorrekturen (RawTherapee/darktable-Niveau). Zwei Wege:

      • auto=True + exif_path: automatisch aus der **lensfun-Datenbank** (wenn lensfunpy installiert
        und das Objektiv bekannt ist) — Vignette, Verzeichnung und Farbquerfehler nach Profil.
      • manuelle Parameter (immer verfügbar, ohne Datenbank):
          - vignette   : Randabdunklung ausgleichen (>0 hellt die Ecken auf, ~r²-Modell)
          - distortion : Verzeichnung (k1; <0 korrigiert Tonnen-, >0 Kissenverzeichnung)
          - ca         : Farbquerfehler (laterale CA; R/B radial gegen G skalieren)

    Treu/nicht-generativ — nur geometrische/Helligkeits-Korrektur, kein Erfinden von Inhalten."""
    f, dt, mx = _as_float(img)
    used_auto = False
    if auto and exif_path:
        f, used_auto = _lensfun_auto(f, exif_path, log=log)
    if not used_auto and (abs(distortion) > 1e-4 or abs(ca) > 1e-4 or abs(vignette) > 1e-4):
        h, w = f.shape[:2]
        cx, cy = w / 2.0, h / 2.0
        nr2 = cx * cx + cy * cy
        xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        ux, uy = xs - cx, ys - cy
        r2 = (ux * ux + uy * uy) / nr2                    # normierter Radius² (0 Mitte … 1 Ecke)
        if abs(distortion) > 1e-4:
            fac = 1.0 + float(distortion) * r2
            f = cv2.remap(f, cx + ux * fac, cy + uy * fac, cv2.INTER_LANCZOS4,
                          borderMode=cv2.BORDER_REFLECT)
        if abs(ca) > 1e-4 and f.ndim == 3:
            for ch, sgn in ((2, 1.0), (0, -1.0)):         # R nach außen, B nach innen (oder umgekehrt)
                fac = 1.0 + sgn * float(ca) * r2
                f[..., ch] = cv2.remap(f[..., ch], cx + ux * fac, cy + uy * fac,
                                       cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
        if abs(vignette) > 1e-4:
            gain = 1.0 + float(vignette) * r2             # Ecken aufhellen
            f = f * (gain[..., None] if f.ndim == 3 else gain)
        log(f"    Objektivkorrektur (manuell): vignette={vignette}, distortion={distortion}, ca={ca}")
    out = np.clip(f, 0, 1)
    if dt == np.uint16:
        return (out * 65535.0).astype(np.uint16)
    if dt == np.uint8:
        return (out * 255.0).astype(np.uint8)
    return out


# ===========================================================================
# R1 — Farb-Management (lineare Pipeline: Kamera → Arbeitsraum → Anzeige)
# ===========================================================================
#
# Alle Matrizen sind 3×3 und arbeiten auf LINEAREM (nicht gamma-kodiertem) RGB
# als Spaltenvektor:  out = M @ rgb.  Zeilen-Konvention: M[i] · [R,G,B].
# Primärfarben/Weißpunkt D65 (sRGB/Rec.2020) bzw. D50 (ProPhoto/ACES-Standard).
#
# Quellen: sRGB & Rec.709 (IEC 61966-2-1), Rec.2020 (ITU-R BT.2020),
# ProPhoto/ROMM (ANSI/I3A IT10.7666). Werte als Konstanten hinterlegt, damit
# ForgePix ohne colour-science-Abhängigkeit auskommt.

# RGB→XYZ (lineares RGB → CIE XYZ), Zeilen = X,Y,Z-Beiträge je Kanal
_RGB2XYZ = {
    # sRGB / Rec.709, D65
    "srgb": np.array([
        [0.4123908, 0.3575843, 0.1804808],
        [0.2126390, 0.7151687, 0.0721923],
        [0.0193308, 0.1191948, 0.9505322],
    ], dtype=np.float64),
    # Rec.2020, D65
    "rec2020": np.array([
        [0.6369580, 0.1446169, 0.1688810],
        [0.2627002, 0.6779981, 0.0593017],
        [0.0000000, 0.0280727, 1.0609851],
    ], dtype=np.float64),
    # ProPhoto / ROMM RGB, D50
    "prophoto": np.array([
        [0.7976749, 0.1351917, 0.0313534],
        [0.2880402, 0.7118741, 0.0000857],
        [0.0000000, 0.0000000, 0.8252100],
    ], dtype=np.float64),
}

# Bradford-Chromatic-Adaptation D50<->D65 (ProPhoto ist D50, sRGB/Rec2020 D65).
# D65→D50 (für XYZ unter D65 → XYZ unter D50, vor ProPhoto-Konversion).
_CAT_D65_D50 = np.array([
    [1.0478112, 0.0228866, -0.0501270],
    [0.0295424, 0.9904844, -0.0170491],
    [-0.0092345, 0.0150436, 0.7521316],
], dtype=np.float64)
_CAT_D50_D65 = np.linalg.inv(_CAT_D65_D50)


def _working_rgb2xyz(working):
    w = (working or "rec2020").lower()
    if w not in _RGB2XYZ:
        raise ValueError(f"unbekannter Arbeitsraum: {working!r} "
                         f"(erlaubt: {sorted(_RGB2XYZ)})")
    return _RGB2XYZ[w], w


def camera_to_working(linear_rgb, cam_xyz_matrix, working="rec2020"):
    """Lineares Kamera-/Sensor-RGB in einen großen linearen ARBEITSFARBRAUM bringen.

    rawpy liefert `raw.rgb_xyz_matrix` (4×3) — die Matrix, die *XYZ → Kamera-RGB*
    abbildet (die ersten 3 Zeilen sind die RGB-Kanäle, eine evtl. 4. Zeile ist ein
    möglicher Emerald-/CYGM-Kanal und wird ignoriert). Wir invertieren sie zu
    *Kamera-RGB → XYZ* und transformieren dann XYZ → Arbeitsraum (Rec.2020 /
    ProPhoto / sRGB), bei ProPhoto inkl. Bradford-Adaption D65→D50.

      linear_rgb     : (...,3) LINEARES Kamera-RGB (float, szenenbezogen, R,G,B-Reihenfolge)
      cam_xyz_matrix : (3,3) oder (4,3) rawpy-XYZ→Kamera-Matrix
      working        : "rec2020" | "prophoto" | "srgb"

    Rückgabe: (...,3) lineares RGB im Arbeitsraum (float64), nicht geclippt
    (szenenbezogen darf >1 sein). Reine Matrixmultiplikation, treu/nicht-generativ."""
    M_cam = np.asarray(cam_xyz_matrix, dtype=np.float64)
    if M_cam.shape[0] == 4:                       # rawpy: 4. Zeile ist optionaler 4. Kanal
        M_cam = M_cam[:3]
    if M_cam.shape != (3, 3):
        raise ValueError("cam_xyz_matrix muss (3,3) oder (4,3) sein")
    cam2xyz = np.linalg.inv(M_cam)                # Kamera-RGB → XYZ (D65)
    rgb2xyz, w = _working_rgb2xyz(working)
    xyz2working = np.linalg.inv(rgb2xyz)          # XYZ → Arbeitsraum-RGB
    if w == "prophoto":                           # XYZ D65 → D50 vor ProPhoto
        cam2xyz = _CAT_D65_D50 @ cam2xyz
    M = xyz2working @ cam2xyz                      # Kamera-RGB → Arbeitsraum-RGB
    arr = np.asarray(linear_rgb, dtype=np.float64)
    return arr @ M.T


def _linear_to_gamma(lin, gamma):
    """Lineares [0,1]-RGB → anzeige-/gamma-kodiertes RGB."""
    lin = np.clip(lin, 0.0, 1.0)
    g = (gamma or "srgb").lower()
    if g == "srgb":
        a = 0.055
        return np.where(lin <= 0.0031308, lin * 12.92,
                        (1 + a) * np.power(lin, 1 / 2.4) - a)
    if g == "rec709":
        return np.where(lin < 0.018, lin * 4.5,
                        1.099 * np.power(lin, 0.45) - 0.099)
    if g in ("linear", "none", None):
        return lin
    try:                                          # numerisches Gamma, z.B. 2.2
        return np.power(lin, 1.0 / float(g))
    except (TypeError, ValueError):
        return lin


def working_to_display(img_working, working="rec2020", gamma="srgb"):
    """Lineares ARBEITSRAUM-RGB zurück nach sRGB-DISPLAY (gamma-kodiert) bringen.

    Kehrt camera_to_working um: Arbeitsraum-RGB → XYZ → sRGB-Primärfarben (linear)
    → Gamma-Kodierung. Bei ProPhoto-Quelle wird XYZ D50→D65 zurück-adaptiert.

      img_working : (...,3) LINEARES RGB im Arbeitsraum (float)
      working     : Arbeitsraum der Eingabe ("rec2020" | "prophoto" | "srgb")
      gamma       : Ausgabe-Transferfunktion: "srgb" | "rec709" | "linear" | Zahl (z.B. 2.2)

    Rückgabe: (...,3) anzeigefertiges sRGB in [0,1] (float64). Treu/nicht-generativ."""
    rgb2xyz, w = _working_rgb2xyz(working)
    working2xyz = rgb2xyz                          # Arbeitsraum-RGB → XYZ
    if w == "prophoto":                            # XYZ D50 → D65 für sRGB
        working2xyz = _CAT_D50_D65 @ working2xyz
    xyz2srgb = np.linalg.inv(_RGB2XYZ["srgb"])     # XYZ(D65) → sRGB linear
    M = xyz2srgb @ working2xyz
    arr = np.asarray(img_working, dtype=np.float64)
    lin = arr @ M.T
    return _linear_to_gamma(lin, gamma)


# ===========================================================================
# R2 — Szenenbezogenes Tonemapping (filmic / sigmoid, ratio-preserving)
# ===========================================================================

def filmic_tonemap(linear_bgr, contrast=1.0, pivot=0.18, latitude=0.6,
                   white=8.0, black=0.0, sat_preserve=1.0):
    """Szenenbezogenes Tonemapping (darktable-„filmic"/-„sigmoid"-Stil): bildet die
    LINEARE Szenen-Luminanz mit einer S-förmigen (sigmoiden) Kurve auf die Anzeige
    ab und komprimiert die Lichter SANFT, statt sie hart zu clippen.

    Hue/Sättigung werden ERHALTEN (ratio-preserving): nicht die Kanäle einzeln
    durch die Kurve geschickt (das verschiebt den Farbton), sondern nur die
    Luminanz gemappt und alle Kanäle mit demselben Verhältnis (out_L/in_L)
    skaliert. Über `sat_preserve` < 1 kann optional zu Weiß entsättigt werden.

      linear_bgr   : (...,3) LINEARES BGR (float, szenenbezogen; darf >1 sein) oder uint8/16
      contrast     : Steilheit der Sigmoid-Kurve (>1 kontrastreicher)
      pivot        : mittlerer Grauwert der Szene (Linear, ~0.18) → bleibt mittig
      latitude     : linearer Mittenbereich um den Pivot (0..1, größer = weniger S-Krümmung)
      white        : Szenen-Luminanz (relativ zum Pivot), die auf Display-Weiß (1.0) fällt
      black        : Szenen-Luminanz, die auf Display-Schwarz (0.0) fällt
      sat_preserve : 1.0 = volle Sättigung erhalten; <1 entsättigt Lichter Richtung Weiß

    Rückgabe: dtype/Range wie Eingabe (uint8/16 → geclippt; float → [0,1]).
    Treu/nicht-generativ — nur Tonwertabbildung."""
    f, dtype, maxv = _as_float(linear_bgr)
    if f.ndim != 3:
        # Graustufen: Luminanz == Wert
        L = np.clip(f, 0.0, None).astype(np.float64)
        out = _filmic_curve(L, contrast, pivot, latitude, white, black)
        out = np.clip(out, 0, 1).astype(np.float32)
        return (out * maxv).astype(dtype) if dtype != np.float32 else out
    x = f.astype(np.float64)
    x = np.clip(x, 0.0, None)                       # szenenbezogen: keine negativen Werte
    # Rec.709-Luminanz auf LINEAREM RGB (BGR-Reihenfolge)
    L = 0.0722 * x[..., 0] + 0.7152 * x[..., 1] + 0.2126 * x[..., 2]
    L = np.maximum(L, 1e-8)
    Lout = _filmic_curve(L, contrast, pivot, latitude, white, black)
    ratio = (Lout / L)[..., None]                  # ratio-preserving: Hue/Sat bleiben
    out = x * ratio
    # Lichter HUE-ERHALTEND begrenzen: wenn ein Kanal > 1 läuft, das GANZE Pixel herunterskalieren
    # (RGB-Verhältnisse bleiben → Farbton bleibt), statt per-Kanal hart zu clippen (das verschöbe
    # den Farbton in gesättigten Lichtern — der klassische Filmic-Fehler).
    m = out.max(axis=2, keepdims=True)
    out = np.where(m > 1.0, out / np.maximum(m, 1e-6), out)
    if sat_preserve < 1.0:                          # Lichter optional zu Weiß entsättigen
        # desat steigt mit der Display-Luminanz (helle Bereiche bleichen aus)
        desat = (1.0 - sat_preserve) * np.clip(Lout, 0, 1)[..., None]
        out = out * (1 - desat) + np.clip(Lout, 0, 1)[..., None] * desat
    out = np.clip(out, 0, 1).astype(np.float32)
    return (out * maxv).astype(dtype) if dtype != np.float32 else out


def _filmic_curve(L, contrast, pivot, latitude, white, black):
    """Sigmoid-Tonwertkurve im LOG-Belichtungsraum (szenenlinear → Display [0,1]).
    Glatt, monoton, komprimiert beide Enden sanft. L > 0 erwartet.

    `white` ist die Szenen-Luminanz (relativ zum Pivot ~0.18), die auf Display-Weiß
    fällt; daraus folgt der EV-Bereich. `black` (≈0) verschiebt das Fußende leicht.
    `latitude` streckt den linearen Mittelteil (flachere S-Krümmung), `contrast`
    erhöht die Steilheit."""
    pivot = max(float(pivot), 1e-6)
    eps = 1e-8
    # Log2-Belichtung relativ zum Pivot (Pivot → 0 EV)
    ev = np.log2(np.maximum(L, eps) / pivot)
    white_ev = np.log2(max(float(white), 1.0 + 1e-3))   # EV über Pivot bis Display-Weiß
    span = max(white_ev, 1e-3)
    xn = ev / span                                  # Pivot bei 0, Display-Weiß ~ +1
    k = max(float(contrast), 1e-3) * 2.0
    lat = np.clip(float(latitude), 0.0, 0.99)
    # Sigmoid um 0 (Pivot → 0.5 Display), latitude streckt den linearen Mittelteil
    s = 1.0 / (1.0 + np.exp(-k * xn / (1.0 - lat * 0.9)))
    # optionaler Schwarz-Versatz (hebt/senkt den Fußpunkt minimal)
    if black:
        s = s + float(black) * (1.0 - s)
    return np.clip(s, 0.0, 1.0)


# ===========================================================================
# R4 — Bessere Rauschreduktion (Luma/Chroma getrennt, 16-bit-treu, ISO-skaliert)
# ===========================================================================

def _wavelet_denoise_channel(ch, thresh):
    """Einfaches kantenerhaltendes Wavelet-Soft-Thresholding (à trous / stationär)
    auf EINEM float-Kanal. Mehrere Skalen via Difference-of-Gaussians; feine
    Detailbänder werden soft-thresholded (Rauschen sitzt in den feinen Bändern).
    Rein NumPy/OpenCV, kein pywt nötig."""
    base = ch.astype(np.float32)
    out = np.zeros_like(base)
    sigma = 1.0
    cur = base.copy()
    for s in range(4):                              # 4 Detailbänder
        blur = cv2.GaussianBlur(cur, (0, 0), sigma)
        detail = cur - blur
        t = thresh * (0.5 ** s)                     # feinste Skala am stärksten entrauscht
        # Soft-Thresholding (schrumpft kleine Koeffizienten → Rauschen weg, Kanten bleiben)
        detail = np.sign(detail) * np.maximum(np.abs(detail) - t, 0.0)
        out += detail
        cur = blur
        sigma *= 2.0
    out += cur                                      # gröbste Approximation unangetastet
    return out


def denoise_chroma_luma(img, luma=1.0, chroma=1.0, iso=None):
    """Wavelet-/kantenerhaltendes Entrauschen, GETRENNT auf Luma und Chroma, in
    FLOAT gerechnet (16-bit bleibt erhalten — anders als fast_denoise, das auf
    uint8 zwingt). Chroma kann stärker entrauscht werden als Luma (Farbrauschen ist
    grobkörniger), ohne Detailverlust in der Helligkeit.

      img    : (...,3) BGR uint8/uint16/float oder Graustufen
      luma   : Luma-Stärke (0 = aus, 1 = normal, höher = stärker)
      chroma : Chroma-Stärke (0 = aus; meist 1–3× luma sinnvoll)
      iso    : optionaler ISO-Wert → grobe Heuristik, die den Threshold skaliert
               (höheres ISO ⇒ mehr Rauschen ⇒ stärker entrauschen)

    Rückgabe: dtype/Range wie Eingabe (16-bit-treu). Treu/nicht-generativ."""
    f, dtype, maxv = _as_float(img)
    # ISO-Heuristik: Basisrauschen ~ sqrt(ISO/100); auf einen Threshold-Faktor mappen
    iso_fac = 1.0
    if iso is not None and iso > 0:
        iso_fac = float(np.sqrt(max(iso, 100.0) / 100.0))
    base_t = 0.02 * iso_fac                          # Basis-Schwelle im [0,1]-Float-Raum
    if f.ndim != 3:
        if luma <= 0:
            return img
        out = _wavelet_denoise_channel(np.clip(f, 0, 1), base_t * luma)
        out = np.clip(out, 0, 1).astype(np.float32)
        return (out * maxv).astype(dtype) if dtype != np.float32 else out
    lab = cv2.cvtColor(np.clip(f, 0, 1).astype(np.float32), cv2.COLOR_BGR2LAB)
    L = lab[..., 0] / 100.0                          # L: 0..100 → 0..1
    a = lab[..., 1]                                  # a,b: ~ -128..127
    b = lab[..., 2]
    if luma > 0:
        L = _wavelet_denoise_channel(L, base_t * luma)
    if chroma > 0:                                   # Chroma stärker, in nativer a/b-Skala
        ct = base_t * chroma * 128.0
        a = _wavelet_denoise_channel(a, ct)
        b = _wavelet_denoise_channel(b, ct)
    lab[..., 0] = np.clip(L, 0, 1) * 100.0
    lab[..., 1] = a
    lab[..., 2] = b
    out = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    out = np.clip(out, 0, 1).astype(np.float32)
    return (out * maxv).astype(dtype) if dtype != np.float32 else out


# ===========================================================================
# R5 — Parametrische Masken (Auswahl nach Luminanz / Farbton / Sättigung)
# ===========================================================================

def parametric_mask(img, by="luminance", lo=0.0, hi=1.0, feather=0.1):
    """Weiche parametrische Auswahl-Maske (0..1) nach Bild-EIGENSCHAFT — andockbar an
    jedes Editor-Modul und kombinierbar (Multiplikation) mit den geometrischen Masken
    (gradient_mask/radial_mask).

      by      : "luminance" | "hue" | "saturation"
                - luminance : Helligkeit (Rec.709), 0..1
                - hue       : Farbton 0..1 (entspricht 0..360°); Auswahl ist zyklisch
                - saturation: HSV-Sättigung 0..1
      lo, hi  : Auswahlbereich [lo,hi] der jeweiligen Eigenschaft (in [0,1])
      feather : weicher Rand als Anteil (Smoothstep-Übergang außerhalb [lo,hi];
                bei "hue" als zyklische Glockenkurve um die Bereichsmitte)

    Smoothstep/Glockenkurve → keine harten Kanten. Rückgabe: float32-Maske 0..1,
    gleiche H×W wie das Bild. Treu/nicht-generativ."""
    f, _, _ = _as_float(img)
    fc = np.clip(f, 0, 1).astype(np.float32)
    by = (by or "luminance").lower()
    fw = max(float(feather), 1e-4)

    if by == "luminance":
        if fc.ndim == 3:
            v = 0.0722 * fc[..., 0] + 0.7152 * fc[..., 1] + 0.2126 * fc[..., 2]
        else:
            v = fc
        return _band_mask(v, lo, hi, fw)

    if fc.ndim != 3:
        raise ValueError(f"by={by!r} braucht ein Farbbild (3 Kanäle)")
    hsv = cv2.cvtColor(fc, cv2.COLOR_BGR2HSV)        # H:0..360, S:0..1, V:0..1
    if by == "saturation":
        return _band_mask(hsv[..., 1], lo, hi, fw)
    if by == "hue":
        h = hsv[..., 0] / 360.0                      # → 0..1
        return _hue_band_mask(h, lo, hi, fw)
    raise ValueError(f"unbekanntes by={by!r} (luminance|hue|saturation)")


def _band_mask(v, lo, hi, fw):
    """Glatte Bandpass-Maske: 1 innerhalb [lo,hi], weicher Smoothstep-Abfall über
    `fw` außerhalb beider Grenzen."""
    lo = float(lo); hi = float(hi)
    if hi < lo:
        lo, hi = hi, lo
    rise = _smoothstep(lo - fw, lo, v)               # Anstieg an der Unterkante
    fall = 1.0 - _smoothstep(hi, hi + fw, v)         # Abfall an der Oberkante
    return np.clip(rise * fall, 0, 1).astype(np.float32)


def _hue_band_mask(h, lo, hi, fw):
    """Zyklische Farbton-Bandmaske (0..1 Farbkreis). Distanz zur Bereichsmitte wird
    zyklisch (wrap-around bei 1.0) gemessen, dann Smoothstep-Abfall."""
    lo = float(lo) % 1.0
    hi = float(hi) % 1.0
    # zyklische Mitte und Halbbreite des Auswahlbereichs
    if hi >= lo:
        center = (lo + hi) / 2.0
        half = (hi - lo) / 2.0
    else:                                            # Bereich über 1.0 hinweg (z.B. Rot)
        center = ((lo + hi + 1.0) / 2.0) % 1.0
        half = ((hi + 1.0) - lo) / 2.0
    d = np.abs(h - center)
    d = np.minimum(d, 1.0 - d)                        # zyklische Distanz
    return np.clip(1.0 - _smoothstep(half, half + fw, d), 0, 1).astype(np.float32)
