#!/usr/bin/env python3
"""
focus_cull_stack.py — Fokus-Stacking-Pipeline mit OpenCV-Culling (+ optionalem VLM-QC).

Ablauf:
  1. Bilder einlesen (JPG/TIFF/PNG, RAW via rawpy)
  2. Schaerfe pro Frame als MAX lokale Schaerfe messen (Laplace-Varianz pro Kachel)
     -> verwackelte Frames (nirgends scharf) raus, gueltige Schaerfeebenen bleiben
  3. Near-Duplicates entfernen (sehr aehnlicher + schwaecherer Frame)
  4. (optional) VLM-QC der grenzwertigen Frames gegen ein OpenAI-kompatibles vLLM
  5. Survivors an ShineStacker (AlignFrames+BalanceFrames -> FocusStack/PyramidStack)
  6. Report (JSON + Konsole)

ShineStacker greift NICHT auf Schaerfe-Culling zu — es alignt/balanciert intern.
Dieses Skript entscheidet nur, WELCHE Frames in den Stack gehen.
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np

from constants import RAW_EXTS, STD_EXTS, FITS_EXTS


def list_images(folder):
    out = []
    for n in sorted(os.listdir(folder)):
        ext = os.path.splitext(n)[1].lower()
        if ext in RAW_EXTS or ext in STD_EXTS or ext in FITS_EXTS:
            out.append(os.path.join(folder, n))
    return out


def load_gray(path, max_side=1600):
    """Graustufenbild (downscaled) fuer die Schaerfe-Analyse. RAW via rawpy."""
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS:
        import rawpy
        gray = None
        # Schnellpfad: eingebettetes Kamera-JPEG (reicht fürs Schärfe-Culling, viel schneller).
        # Nur wenn groß genug, sonst voller Entwicklungs-Fallback.
        try:
            with rawpy.imread(path) as raw:
                th = raw.extract_thumb()
            if getattr(th, "format", None) == rawpy.ThumbFormat.JPEG:
                tg = cv2.imdecode(np.frombuffer(th.data, np.uint8), cv2.IMREAD_GRAYSCALE)
                if tg is not None and max(tg.shape) >= 1024:
                    gray = tg
        except Exception:
            gray = None
        if gray is None:
            with rawpy.imread(path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, output_bps=8, half_size=True)
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    else:
        gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise RuntimeError(f"Konnte Bild nicht lesen: {path}")
    h, w = gray.shape[:2]
    s = max(h, w)
    if s > max_side:
        f = max_side / s
        gray = cv2.resize(gray, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    return gray


def develop_raw_to_bgr(path, wb="camera", auto_bright=False, bps=16, half=False,
                       demosaic="auto", reconstruct_highlights=False, lens=None):
    """RAW treu entwickeln (rawpy) und als BGR-Array zurückgeben (cv2-Konvention).
    Nicht-generativ: nur Demosaicing/WB/Gamma, keine erfundenen Inhalte.
    demosaic: 'auto'(=AHD) | 'dht' | 'dcb' | 'vng' | 'ahd' (AMaZE braucht GPL-LibRaw-Build).
    reconstruct_highlights: ausgebrannte Lichter rekonstruieren (Kanal-Verhältnis + Entsättigen).
    lens: optionales Dict mit Objektivkorrekturen {auto, vignette, distortion, ca}."""
    import rawpy
    with rawpy.imread(path) as raw:
        kw = dict(output_bps=bps, no_auto_bright=not auto_bright, half_size=half,
                  output_color=rawpy.ColorSpace.sRGB)
        if wb == "camera":
            kw["use_camera_wb"] = True
        elif wb == "auto":
            kw["use_auto_wb"] = True
        algo = {"dht": "DHT", "dcb": "DCB", "vng": "VNG", "ahd": "AHD",
                "amaze": "AMAZE"}.get(str(demosaic).lower())
        if algo:
            try:
                kw["demosaic_algorithm"] = getattr(rawpy.DemosaicAlgorithm, algo)
            except Exception:
                pass                                          # nicht verfügbar (GPL-Build) → Default
        try:
            rgb = raw.postprocess(**kw)
        except Exception:                                     # Demosaic nicht unterstützt → Default
            kw.pop("demosaic_algorithm", None)
            rgb = raw.postprocess(**kw)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if reconstruct_highlights:
        import develop
        bgr = develop.highlight_reconstruct(bgr)
    if lens and (lens.get("auto") or any(abs(lens.get(k, 0.0)) > 1e-4
                                         for k in ("vignette", "distortion", "ca"))):
        import develop
        bgr = develop.lens_correct(bgr, vignette=lens.get("vignette", 0.0),
                                   distortion=lens.get("distortion", 0.0), ca=lens.get("ca", 0.0),
                                   auto=lens.get("auto", False), exif_path=path)
    return bgr


def develop_all(paths, dev_dir, args):
    """RAWs zu 16-bit TIFF entwickeln, Nicht-RAW unverändert kopieren.
    Schreibt TIFF per cv2.imwrite (BGR), damit ShineStacker es farbtreu liest."""
    if os.path.isdir(dev_dir):
        shutil.rmtree(dev_dir)
    os.makedirs(dev_dir)
    from parallel import pmap

    # Index-Präfix erhält die Aufnahmereihenfolge (Nachbar-Logik des Cullings hängt davon ab).
    # Über alle Kerne entwickeln (rawpy/cv2 geben den GIL frei); pmap erhält die Reihenfolge.
    def _one(item):
        i, p = item
        ext = os.path.splitext(p)[1].lower()
        name = os.path.basename(p)
        if ext in RAW_EXTS:
            outp = os.path.join(dev_dir, f"{i:04d}_" + os.path.splitext(name)[0] + ".tif")
            print(f"  RAW entwickeln: {name} -> {os.path.basename(outp)}")
            bgr = develop_raw_to_bgr(p, args.raw_wb, args.raw_auto_bright,
                                     args.raw_bps, args.raw_half,
                                     demosaic=getattr(args, "raw_demosaic", "auto"),
                                     reconstruct_highlights=getattr(args, "raw_highlights", False),
                                     lens={"auto": getattr(args, "lens_auto", False),
                                           "vignette": getattr(args, "lens_vignette", 0.0),
                                           "distortion": getattr(args, "lens_distortion", 0.0),
                                           "ca": getattr(args, "lens_ca", 0.0)})
            cv2.imwrite(outp, bgr, [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
            return outp
        dst = os.path.join(dev_dir, f"{i:04d}_" + name)
        shutil.copy2(p, dst)
        return dst

    return pmap(_one, list(enumerate(paths)), memory_heavy=True)


def peak_local_sharpness(gray, grid=8, pct=95):
    """Max/Perzentil der Laplace-Varianz ueber ein Kachelraster.
    Hoch = irgendeine Region ist knackscharf (gueltige Fokusebene).
    Niedrig ueberall = verwackelt / global unscharf."""
    h, w = gray.shape
    th, tw = max(1, h // grid), max(1, w // grid)
    vals = []
    for y in range(0, h - th + 1, th):
        for x in range(0, w - tw + 1, tw):
            tile = gray[y:y + th, x:x + tw]
            vals.append(cv2.Laplacian(tile, cv2.CV_64F).var())
    vals = np.array(vals) if vals else np.array([0.0])
    return float(np.percentile(vals, pct)), float(vals.mean())


def dup_distance(a, b, size=64):
    """Normalisierte MSE zwischen zwei (downscaled) Graubildern. Klein = sehr aehnlich."""
    ra = cv2.resize(a, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    rb = cv2.resize(b, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    ra -= ra.mean(); rb -= rb.mean()
    denom = (np.linalg.norm(ra) * np.linalg.norm(rb)) + 1e-6
    corr = float((ra * rb).sum() / denom)  # 1.0 = identisch
    return 1.0 - corr


@dataclass
class Frame:
    path: str
    name: str
    peak_sharp: float = 0.0
    mean_sharp: float = 0.0
    keep: bool = True
    reasons: list = field(default_factory=list)
    vlm_verdict: str = ""


def analyze(paths, max_side):
    from parallel import pmap

    def _one(p):
        g = load_gray(p, max_side=max_side)
        peak, mean = peak_local_sharpness(g)
        frame = Frame(path=p, name=os.path.basename(p), peak_sharp=peak, mean_sharp=mean)
        return frame, cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA)

    results = pmap(_one, paths)  # geordnet -> Aufnahmereihenfolge bleibt
    frames = [r[0] for r in results]
    grays = [r[1] for r in results]
    return frames, grays


def cull(frames, grays, dip_ratio, abs_min, dedup, dup_thresh):
    """Konservatives Culling fuer Fokus-Stacks.

    Ein Fokus-Sweep hat NATUERLICH ein Schaerfegefaelle (Enden global weicher).
    Darum nicht gegen den Median werfen, sondern nur:
      - lokaler Einbruch: ein Frame, der deutlich unschaerfer ist als BEIDE
        Nachbarn -> wurde angestossen / Bewegungsunschaerfe (Sweep-Enden bleiben)
      - absoluter Boden: praktisch strukturloser Frame (Deckel drauf o.ae.)
    Near-Duplicate-Erkennung ist fuer Stacks gefaehrlich (Nachbarframes sind
    per Design fast identisch) -> nur optional via dedup=True.
    """
    peaks = [f.peak_sharp for f in frames]
    med = float(np.median(peaks)) if peaks else 0.0
    n = len(frames)
    for i, f in enumerate(frames):
        if f.peak_sharp < abs_min:
            f.keep = False
            f.reasons.append(f"strukturlos (peak {f.peak_sharp:.0f} < {abs_min})")
            continue
        # lokaler Einbruch nur fuer innere Frames mit zwei Nachbarn
        if 0 < i < n - 1:
            lo = min(frames[i - 1].peak_sharp, frames[i + 1].peak_sharp)
            if lo > 0 and f.peak_sharp < dip_ratio * lo:
                f.keep = False
                f.reasons.append(
                    f"verwackelt: lokaler Einbruch (peak {f.peak_sharp:.0f} < "
                    f"{dip_ratio:.0%} der Nachbarn {lo:.0f})")
    if dedup:  # optional, mit Vorsicht
        kept_idx = [i for i, f in enumerate(frames) if f.keep]
        for a in range(len(kept_idx)):
            i = kept_idx[a]
            if not frames[i].keep:
                continue
            for b in range(a + 1, len(kept_idx)):
                j = kept_idx[b]
                if not frames[j].keep:
                    continue
                if dup_distance(grays[i], grays[j]) < dup_thresh:
                    weaker = i if frames[i].peak_sharp <= frames[j].peak_sharp else j
                    other = j if weaker == i else i
                    frames[weaker].keep = False
                    frames[weaker].reasons.append(f"near-duplicate zu {frames[other].name}")
    return med


def _vlm_chat(endpoint, model, messages, max_tokens=300, api_key=None, timeout=180):
    """Zentraler Chat-Aufruf an einen OpenAI-kompatiblen Endpoint.
    Mit API-Key (OpenAI/OpenRouter/…) -> Authorization-Header, KEIN Reasoning-Param
    (Cloud-APIs lehnen unbekannte Felder ab). Ohne Key (lokal) -> enable_thinking:false
    für lokale Qwen-Reasoner."""
    try:
        import requests
    except ImportError:
        raise RuntimeError("Für den KI-Server wird das Paket 'requests' benötigt "
                           "(pip install requests). Die Automatik läuft auch ohne KI weiter.")
    headers = {"Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    r = requests.post(f"{endpoint.rstrip('/')}/chat/completions",
                      json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def vlm_qc(frames, endpoint, model, only_borderline=True, median=0.0, api_key=None):
    """Optionaler semantischer QC-Pass gegen ein OpenAI-kompatibles Modell.
    Beurteilt NICHT die Pixel-Schaerfe, sondern Motiv-Bewegung/Wind/grobe Probleme."""
    prompt = ("Du pruefst ein Foto aus einer Focus-Stacking-Serie (z.B. eine Blume). "
              "Beurteile NICHT die Schaerfe. Pruefe nur: Hat sich das Motiv bewegt "
              "(Wind/Verschiebung), gibt es Doppelkonturen, oder ein grobes Problem, "
              "das diesen Frame fuer den Stack unbrauchbar macht? "
              "Antworte als JSON: {\"usable\": true|false, \"reason\": \"kurz\"}.")
    for f in frames:
        if not f.keep:
            continue
        if only_borderline and median > 0 and f.peak_sharp > 1.5 * median:
            continue  # klar scharfe Frames nicht erst fragen
        # Heruntergerechnetes JPG senden (NICHT das volle RAW/TIFF — sonst Token-Limit/Timeout)
        data_url = _encode_jpeg_dataurl(f.path)
        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}}]}]
        try:
            txt = _vlm_chat(endpoint, model, messages, max_tokens=200, api_key=api_key, timeout=120)
            f.vlm_verdict = txt.strip()
            try:
                start = txt.find("{"); verdict = json.loads(txt[start:txt.rfind("}") + 1])
                if verdict.get("usable") is False:
                    f.keep = False
                    f.reasons.append(f"VLM: {verdict.get('reason', 'unbrauchbar')}")
            except Exception:
                pass  # nicht-parsebare Antwort -> Frame im Zweifel behalten
        except Exception as e:
            f.vlm_verdict = f"VLM-Fehler: {e}"
            print(f"  ! VLM-QC fehlgeschlagen fuer {f.name}: {e}", file=sys.stderr)


def _encode_jpeg_dataurl(path, max_side=768):
    """Bild herunterskaliert als JPEG-data-URL (Token sparen)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8, half_size=True)
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    else:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    s = max(h, w)
    if s > max_side:
        f = max_side / s
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def suggest_settings(frames, endpoint, model, api_key=None, context=None):
    """KI beurteilt repraesentative Frames + Schaerfeprofil und schlaegt
    Pipeline-Settings vor. Gibt dict zurueck (Defaults bei Fehlern).

    context (optional, alles datensparsam): {exif, coverage, quality, wish,
    focusmap_path}. Texte gehen in den Prompt, focusmap_path als zusaetzliches Bild."""
    n = len(frames)
    # repraesentative Frames: schaerfster, weichster, erster, letzter, Mitte
    order = sorted(range(n), key=lambda i: frames[i].peak_sharp)
    sel = sorted(set([0, n - 1, n // 2, order[0], order[-1]]))[:5]
    profile = ", ".join(f"#{i + 1}:{frames[i].peak_sharp:.0f}" for i in range(n))
    prompt = (
        "Du hilfst bei einer Focus-Stacking-Pipeline. Es wurden " + str(n) +
        " Fotos einer Serie aufgenommen. OpenCV hat pro Frame die maximale lokale "
        "Schaerfe (Laplace-Varianz, hoeher=schaerfer) gemessen. Schaerfeprofil in "
        "Aufnahme-Reihenfolge: [" + profile + "]. "
        "Ich zeige dir einige repraesentative Frames. Beurteile: Motivtyp, ist es ein "
        "sauberer Fokus-Sweep, gibt es Ausreisser/Verwackler, Hinweise auf Wind/Bewegung. "
        "Schlage dann Pipeline-Settings vor. Bedeutung:\n"
        "- dip_ratio (0.0-0.8): innerer Frame wird verworfen, wenn Schaerfe < ratio*min(Nachbarn). "
        "Hoeher=strenger. Bei sauberem Sweep 0.3-0.45, bei vielen Wacklern hoeher.\n"
        "- abs_min (0-100): Frame raus, wenn Schaerfe darunter (strukturlos). Meist 10-20.\n"
        "- dedup (bool): nur true, wenn echte Doppelaufnahmen vermutet werden (bei Stacks meist false).\n"
        "- vlm_qc (bool): true nur wenn Wind/Bewegung wahrscheinlich (Outdoor-Pflanze o.ae.).\n"
        "Stacker-Parameter (eigene Engine):\n"
        "- transform: 'rigid' (Stativ/Makroschlitten, Standard) oder 'homography' (Freihand/Perspektive).\n"
        "- detector: 'ORB' (schnell, Standard) oder 'SIFT' (robuster bei wenig Textur, langsamer).\n"
        "- sharpen (0-50): leichtes Nachschaerfen des Ergebnisses in %, 0=aus. Makro oft 10-25.\n"
        "- reverse (bool): true, wenn der Sweep hinten->vorne fotografiert wurde.\n"
        "Wenn die Fokus-Abdeckung Luecken hat oder mehr Aufnahmen sinnvoll waeren, sage es in der "
        "Begruendung. Beachte einen etwaigen Nutzer-Wunsch woertlich. "
        "Antworte AUSSCHLIESSLICH als JSON: "
        '{"dip_ratio":0.4,"abs_min":15,"dedup":false,"vlm_qc":false,'
        '"transform":"rigid","detector":"ORB","sharpen":0,"reverse":false,'
        '"subject":"...","rationale":"kurze Begruendung auf Deutsch"}'
    )
    # Zusatz-Kontext (alles optional, datensparsam): EXIF / Abdeckung / Metriken / Nutzer-Wunsch
    ctx = context or {}
    extra = []
    if ctx.get("exif"):
        extra.append("Kamera/Objektiv (EXIF): " + str(ctx["exif"]))
    if ctx.get("coverage"):
        extra.append("Fokus-Abdeckung: " + str(ctx["coverage"]))
    if ctx.get("quality"):
        extra.append("Qualitaets-Metriken: " + str(ctx["quality"]))
    if ctx.get("wish"):
        extra.append("Nutzer-Wunsch (woertlich beachten): " + str(ctx["wish"]))
    if extra:
        prompt += "\n\nZusaetzlicher Kontext:\n- " + "\n- ".join(extra)

    content = [{"type": "text", "text": prompt}]
    for i in sel:
        content.append({"type": "text", "text": f"Frame #{i + 1} (Schaerfe {frames[i].peak_sharp:.0f}):"})
        content.append({"type": "image_url", "image_url": {"url": _encode_jpeg_dataurl(frames[i].path)}})
    fmp = ctx.get("focusmap_path")
    if fmp and os.path.exists(fmp):
        content.append({"type": "text", "text": "Fokus-Herkunfts-Karte (welcher Frame liefert wo Schaerfe):"})
        content.append({"type": "image_url", "image_url": {"url": _encode_jpeg_dataurl(fmp)}})
    txt = _vlm_chat(endpoint, model, [{"role": "user", "content": content}],
                    max_tokens=500, api_key=api_key)
    s = txt.find("{"); e = txt.rfind("}")
    out = {"dip_ratio": 0.4, "abs_min": 15.0, "dedup": False,
           "vlm_qc": False, "transform": "rigid", "detector": "ORB", "sharpen": 0.0,
           "reverse": False, "subject": "", "rationale": "(keine Antwort geparst)"}
    if s >= 0 and e > s:
        try:
            out.update(json.loads(txt[s:e + 1]))
        except Exception as ex:
            out["rationale"] = f"JSON-Parse-Fehler: {ex}; roh: {txt[:200]}"
    out["n_frames"] = n
    return out


def build_ai_context(paths, args, focusmap=True):
    """Datensparsamen Zusatz-Kontext für die KI-Settings-Anfrage zusammenstellen (alles optional).
    EXIF (Brennweite/Blende/Belichtung/ISO/Objektiv) + Nutzer-Wunsch + optional Fokus-Map-Bild."""
    ctx = {}
    wish = getattr(args, "wish", None)
    if wish and str(wish).strip():
        ctx["wish"] = str(wish).strip()
    if not paths:
        return ctx
    try:
        from focus_analysis import read_exif_optics, _exif_expo_iso
        opt = read_exif_optics(paths[0]) or {}
        expo, iso = _exif_expo_iso(paths[:1])
        bits = []
        if opt.get("focal_mm"):
            bits.append(f"{opt['focal_mm']:.0f}mm")
        if opt.get("f_number"):
            bits.append(f"f/{opt['f_number']:.1f}")
        if expo is not None:
            bits.append(f"{expo:g}s")
        if iso is not None:
            bits.append(f"ISO {int(iso)}")
        if opt.get("lens"):
            bits.append(str(opt["lens"]))
        elif opt.get("model"):
            bits.append(str(opt["model"]))
        if bits:
            ctx["exif"] = ", ".join(bits)
    except Exception:
        pass
    if focusmap and len(paths) >= 3:
        try:
            import tempfile
            from focus_analysis import focus_map
            fm = focus_map(paths)
            if fm is not None:
                p = os.path.join(tempfile.gettempdir(), "forgepix_ai_focusmap.png")
                cv2.imwrite(p, fm)
                ctx["focusmap_path"] = p
        except Exception:
            pass
    return ctx


def heuristic_settings(frames):
    """Settings deterministisch aus dem Schärfeprofil bestimmen — OHNE KI/Server.
    Damit läuft die Automatik auf jedem Rechner ohne Modell/Download."""
    n = len(frames)
    peaks = [f.peak_sharp for f in frames]
    med = float(np.median(peaks)) if peaks else 0.0
    return {
        "dip_ratio": 0.4,
        "abs_min": float(min(40.0, max(8.0, med * 0.05))),
        "dedup": False,
        "bunch": 12 if n > 24 else 0,
        "vlm_qc": False,
        "algo": "pyramid", "transform": "rigid", "detector": "ORB",
        "balance_channel": "LUMI", "balance_map": "LINEAR",
        "sharpen": 12.0, "reverse": False,
        "subject": "(heuristisch)",
        "rationale": f"Aus dem Schärfeprofil bestimmt (ohne KI): {n} Fotos, "
                     f"Median-Schärfe {med:.0f}.",
        "n_frames": n,
    }


def apply_suggestion_to_args(args, sug):
    """Übernimmt einen KI-Vorschlag in das args-Objekt (Auto-Modus)."""
    # nur Parameter der eigenen Engine (ShineStacker-only entfernt)
    mapping = {
        "dip_ratio": "dip_ratio", "abs_min": "abs_min", "dedup": "dedup",
        "transform": "transform", "detector": "detector",
        "sharpen": "sharpen", "reverse": "reverse",
    }
    for key, attr in mapping.items():
        if sug.get(key) is not None and hasattr(args, attr):
            cur = getattr(args, attr)
            try:
                setattr(args, attr, type(cur)(sug[key]) if isinstance(cur, (int, float))
                        and not isinstance(cur, bool) else sug[key])
            except (TypeError, ValueError):
                setattr(args, attr, sug[key])
    args.vlm_qc = bool(sug.get("vlm_qc"))  # KI entscheidet, ob Wind/Bewegungs-QC läuft


def copy_exif(src, targets):
    """EXIF/Metadaten (Kamera/Objektiv/Datum) vom Original auf die Ergebnisse übertragen.
    Bevorzugt exiftool (volle Abdeckung, alle Formate). Ohne exiftool: eingebauter
    pure-Python-Fallback via piexif (JPEG-Ausgaben; Quelle JPEG/TIFF direkt oder RAW via ExifRead).
    So ist die EXIF-Übernahme im Installer enthalten — keine Zusatz-Installation nötig."""
    if not src or not os.path.isfile(src):
        return
    tg = [t for t in targets if t and os.path.isfile(t)]
    if not tg:
        return
    if shutil.which("exiftool"):
        try:
            subprocess.run(["exiftool", "-overwrite_original", "-TagsFromFile", src, "-all:all",
                            "-CommonIFD0", "-ICC_Profile", *tg],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            print(f"  EXIF übernommen von {os.path.basename(src)} -> {len(tg)} Datei(en)")
            return
        except Exception as e:
            print(f"  exiftool-Übernahme fehlgeschlagen ({e}) — versuche eingebauten Weg", file=sys.stderr)
    _copy_exif_piexif(src, tg)


def _copy_exif_piexif(src, targets):
    """Eingebaute EXIF-Übernahme ohne exiftool (piexif). Schreibt in JPEG-Ausgaben; Quelle JPEG/TIFF
    direkt, RAW über die Kernfelder aus ExifRead. Nicht-JPEG-Ziele werden (mangels robuster
    Schreibunterstützung) übersprungen."""
    try:
        import piexif
    except Exception:
        print("  EXIF-Übernahme übersprungen (weder exiftool noch piexif verfügbar)", file=sys.stderr)
        return
    try:
        exif_bytes = _piexif_bytes_from(src, piexif)
    except Exception as e:
        print(f"  EXIF-Übernahme übersprungen (Quelle nicht lesbar: {e})", file=sys.stderr)
        return
    jpgs = [t for t in targets if os.path.splitext(t)[1].lower() in (".jpg", ".jpeg")]
    tiffs = [t for t in targets if os.path.splitext(t)[1].lower() in (".tif", ".tiff")]
    done = 0
    if exif_bytes:
        for t in jpgs:
            try:
                piexif.insert(exif_bytes, t)
                done += 1
            except Exception:
                pass
    done += _embed_tiff_meta(src, tiffs)
    other = len(targets) - len(jpgs) - len(tiffs)
    msg = f"  EXIF (eingebaut) übernommen -> {done} Datei(en)"
    if other:
        msg += f"; {other} sonstige übersprungen"
    print(msg)


def _embed_tiff_meta(src, tiffs):
    """Kern-EXIF in TIFF-Ausgaben schreiben (Make/Model/DateTime als Baseline-Tags + lesbare
    Zusammenfassung in ImageDescription). piexif kann kein TIFF -> tifffile. Voll-EXIF-IFD bleibt
    exiftool vorbehalten; die wichtigen Provenienz-Daten sind so aber auch ohne exiftool drin."""
    if not tiffs:
        return 0
    try:
        import tifffile
        import focus_analysis as fa
    except Exception:
        return 0
    opt = fa.read_exif_optics(src) or {}
    expo, iso = fa._exif_expo_iso([src])
    make, dt = _exif_make_datetime(src)
    model = opt.get("model")

    def ascii_(s):  # TIFF-Strings müssen 7-bit-ASCII sein
        return str(s).encode("ascii", "ignore").decode().strip() if s else ""

    parts = []
    if model:
        parts.append(ascii_(model))
    if opt.get("focal_mm"):
        parts.append(f"{opt['focal_mm']:.0f}mm")
    if opt.get("f_number"):
        parts.append(f"f/{opt['f_number']:.1f}")
    if iso:
        parts.append(f"ISO{int(iso)}")
    if expo:
        parts.append(f"{expo:g}s" if expo >= 1 else f"1/{round(1 / expo)}s")
    if opt.get("lens"):
        parts.append(ascii_(opt["lens"]))
    desc = " | ".join(p for p in parts if p)
    extra = []
    if ascii_(make):
        extra.append((271, "s", 0, ascii_(make), True))
    if ascii_(model):
        extra.append((272, "s", 0, ascii_(model), True))
    if ascii_(dt):
        extra.append((306, "s", 0, ascii_(dt), True))
    if desc:
        extra.append((270, "s", 0, desc, True))
    if not extra:
        return 0
    done = 0
    for t in tiffs:
        try:
            # Ebenen-TIFFs (Photoshop ImageSourceData, Tag 37724) NICHT neu schreiben — das würde
            # die Ebenen plattmachen. Solche Dateien beim eingebauten EXIF-Weg überspringen.
            with tifffile.TiffFile(t) as tf:
                if any(tg.code == 37724 for tg in tf.pages[0].tags):
                    print(f"  EXIF (eingebaut): Ebenen-TIFF {os.path.basename(t)} übersprungen "
                          f"(Ebenen bleiben erhalten; volle EXIF via exiftool)")
                    continue
            # tifffile zum Lesen UND Schreiben -> kein BGR/RGB-Swap, Pixel bleiben bit-identisch
            data = tifffile.imread(t)
            # metadata=None -> tifffile belegt ImageDescription (270) nicht selbst, Platz für unsere
            tifffile.imwrite(t, data, metadata=None, extratags=extra)
            done += 1
        except Exception:
            pass
    return done


def _exif_make_datetime(src):
    """Hersteller + Aufnahmedatum via ExifRead (für TIFF-Provenienz). (None, None) bei Fehlen."""
    try:
        import exifread
        with open(src, "rb") as f:
            t = exifread.process_file(f, details=False)
        make = str(t.get("Image Make")) if t.get("Image Make") else None
        dt = (t.get("EXIF DateTimeOriginal") or t.get("Image DateTime"))
        return make, (str(dt) if dt else None)
    except Exception:
        return None, None


def _piexif_bytes_from(src, piexif):
    """piexif-EXIF-Bytes aus der Quelle bauen: JPEG/TIFF direkt laden, RAW aus ExifRead-Kernfeldern."""
    ext = os.path.splitext(src)[1].lower()
    if ext in (".jpg", ".jpeg", ".tif", ".tiff"):
        try:
            return piexif.dump(piexif.load(src))
        except Exception:
            pass
    # RAW (oder Fallback): Kernfelder via ExifRead -> minimaler EXIF-Block
    from fractions import Fraction
    import focus_analysis as fa
    opt = fa.read_exif_optics(src) or {}
    expo, iso = fa._exif_expo_iso([src])

    def ratio(x):
        if x is None:
            return None
        fr = Fraction(float(x)).limit_denominator(10000)
        return (fr.numerator, fr.denominator)

    zeroth, exif = {}, {}
    if opt.get("model"):
        zeroth[piexif.ImageIFD.Model] = str(opt["model"]).encode("utf-8", "ignore")
    zeroth[piexif.ImageIFD.Software] = b"ForgePix"
    if opt.get("focal_mm"):
        exif[piexif.ExifIFD.FocalLength] = ratio(opt["focal_mm"])
    if opt.get("f_number"):
        exif[piexif.ExifIFD.FNumber] = ratio(opt["f_number"])
    if iso:
        exif[piexif.ExifIFD.ISOSpeedRatings] = int(iso)
    if expo:
        exif[piexif.ExifIFD.ExposureTime] = ratio(expo)
    if opt.get("lens"):
        exif[piexif.ExifIFD.LensModel] = str(opt["lens"]).encode("utf-8", "ignore")
    if not zeroth and not exif:
        return None
    return piexif.dump({"0th": zeroth, "Exif": exif, "1st": {}, "thumbnail": None, "GPS": {}})


def copy_exif_to_dirs(src, *dirs):
    """EXIF vom Original auf alle Bild-Ausgaben in mehreren Ordnern übertragen."""
    files = []
    for d in dirs:
        if d and os.path.isdir(d):
            files += [os.path.join(d, f) for f in os.listdir(d)
                      if os.path.splitext(f)[1].lower() in (".jpg", ".jpeg", ".tif", ".tiff", ".png")]
    copy_exif(src, files)


def export_web_jpg(stack_dir, export_dir):
    """Aus dem (ggf. 16-bit) Stack ein teilbares 8-bit sRGB JPG schreiben."""
    if not os.path.isdir(stack_dir):
        return
    os.makedirs(export_dir, exist_ok=True)
    for f in os.listdir(stack_dir):
        ext = os.path.splitext(f)[1].lower()
        if ext not in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
            continue
        img = cv2.imread(os.path.join(stack_dir, f), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        if img.dtype != "uint8":
            img = (img / 256).astype("uint8") if img.max() > 255 else img.astype("uint8")
        out = os.path.join(export_dir, os.path.splitext(f)[0] + ".jpg")
        cv2.imwrite(out, img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        print(f"  Web-JPG: {out}")


def ai_enhance_params(result_bgr, endpoint, model, api_key=None, ghostmap_path=None):
    """KI beurteilt das fertige Bild und schlägt TREUE Nachbearbeitung vor.
    Optional: Geister-Karte (ghostmap_path) mitgeben -> KI nennt Bewegungsartefakte/Retusche-Stellen."""
    img = result_bgr
    if img.dtype != np.uint8:
        img = (img / 256).astype(np.uint8) if img.max() > 255 else img.astype(np.uint8)
    h, w = img.shape[:2]
    if max(h, w) > 1024:
        f = 1024 / max(h, w)
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    b64 = base64.b64encode(buf.tobytes()).decode()
    has_ghost = bool(ghostmap_path and os.path.exists(ghostmap_path))
    prompt = ("Du beurteilst ein fertig gestacktes Foto und empfiehlst TREUE, nicht-generative "
              "Nachbearbeitung (es werden keine Inhalte erfunden). Wie viel Schärfen, Klarheit "
              "(Mikrokontrast) und Entrauschen ist sinnvoll, ohne dass es künstlich/überzogen "
              "wirkt? Werte 0-50. Bei rauschfreiem, schon scharfem Bild ruhig niedrig. ")
    if has_ghost:
        prompt += ("Ich zeige dir zusätzlich eine GEISTER-KARTE: helle Bereiche = Bewegungs-/"
                   "Stacking-Artefakte (Ghosting). Nenne in 'ghost_advice' kurz und konkret, WO "
                   "(z. B. linker Flügel, untere Bildmitte) retuschiert werden sollte, oder "
                   "schreibe 'keine auffälligen Artefakte'. ")
    prompt += ('Antworte NUR als JSON: {"sharpen":0-50,"sharpen_radius":0.5-3,'
               '"clarity":0-50,"denoise":0-50,"rationale":"kurz"'
               + (',"ghost_advice":"kurz"' if has_ghost else '') + '}')
    content = [{"type": "text", "text": prompt},
               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]
    if has_ghost:
        content.append({"type": "text", "text": "Geister-Karte (helle Bereiche = Artefakte):"})
        content.append({"type": "image_url", "image_url": {"url": _encode_jpeg_dataurl(ghostmap_path)}})
    messages = [{"role": "user", "content": content}]
    out = {"sharpen": 12.0, "sharpen_radius": 1.0, "clarity": 8.0, "denoise": 0.0,
           "rationale": "(Standard)"}
    try:
        txt = _vlm_chat(endpoint, model, messages, max_tokens=300, api_key=api_key)
        s, e = txt.find("{"), txt.rfind("}")
        if s >= 0 and e > s:
            out.update(json.loads(txt[s:e + 1]))
    except Exception as ex:
        out["rationale"] = f"KI-Anfrage fehlgeschlagen: {ex}"
    return out


def ai_astro_stretch_params(view_bgr, endpoint, model, api_key=None):
    """KI beurteilt das (vor-gestreckte) Astro-Bild und schlägt Aufhellung vor — TREU.
    Wichtig: der helle Kern/Sterne sollen NICHT weiter aufgehellt werden, nur das schwache
    Signal (Nebel/Hintergrund). Gibt {strength, saturation, protect_core, rationale}."""
    img = np.clip(view_bgr * 255, 0, 255).astype(np.uint8) if view_bgr.dtype != np.uint8 else view_bgr
    h, w = img.shape[:2]
    if max(h, w) > 1024:
        f = 1024 / max(h, w)
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    b64 = base64.b64encode(buf.tobytes()).decode()
    prompt = ("Du beurteilst ein gestapeltes Astrofoto (Deep-Sky, Farbkamera). Beurteile Aufhellung "
              "UND Farbe. WICHTIG: der helle Kern und helle Sterne duerfen NICHT weiter aufgehellt "
              "werden (kein Ausbleichen) — nur das schwache Signal anheben. "
              "Hat das Bild einen Farbstich (z. B. rot/gruen durch Lichtverschmutzung/OSC) oder ist "
              "der Hintergrund schon neutral? color 0.0-1.0 = wie stark farb-kalibriert werden soll "
              "(0=Farben sind ok, 1=starker Stich, voll neutralisieren). "
              "strength 5-30 (hoeher=heller, hebt Schwaches), saturation 1.0-1.6 (Farb-Saettigung), "
              "protect_core true/false (Kern-Schutz, meist true). "
              'Antworte NUR als JSON: {"strength":14,"saturation":1.3,"color":1.0,'
              '"protect_core":true,"rationale":"kurz"}')
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    out = {"strength": 14.0, "saturation": 1.3, "color": 1.0, "protect_core": True,
           "rationale": "(Standard)"}
    txt = _vlm_chat(endpoint, model, messages, max_tokens=250, api_key=api_key)
    s, e = txt.find("{"), txt.rfind("}")
    if s >= 0 and e > s:
        try:
            out.update(json.loads(txt[s:e + 1]))
        except Exception:
            pass
    # Zurückhaltend deckeln — kein Neon-Comic. Strength bis 12, Sättigung bis 1.25.
    out["strength"] = float(max(3.0, min(12.0, out.get("strength", 6.0))))
    out["saturation"] = float(max(1.0, min(1.25, out.get("saturation", 1.05))))
    out["color"] = float(max(0.0, min(1.0, out.get("color", 1.0))))
    out["protect_core"] = bool(out.get("protect_core", True))
    return out


def apply_ai_enhance(result, args, ghostmap_path=None):
    """Treuer Feinschliff (Entrauschen -> Klarheit -> Schärfen). Mit KI falls Server da,
    sonst fester schonender Standard — funktioniert also auch ganz ohne KI.
    ghostmap_path: optionale Geister-Karte -> KI nennt Bewegungsartefakte/Retusche-Stellen."""
    import stacker
    if getattr(args, "vlm_endpoint", None):
        p = ai_enhance_params(result, args.vlm_endpoint, args.vlm_model,
                              getattr(args, 'vlm_key', None), ghostmap_path=ghostmap_path)
    else:
        p = {"sharpen": 12.0, "sharpen_radius": 1.0, "clarity": 8.0, "denoise": 0.0,
             "rationale": "fester Standard (ohne KI)"}
    print(f"  Feinschliff (treu): schärfen={p.get('sharpen')} klarheit={p.get('clarity')} "
          f"entrauschen={p.get('denoise')} — {p.get('rationale', '')}")
    if p.get("ghost_advice"):
        print(f"  KI-Retusche-Hinweis (Ghosting): {p['ghost_advice']}")
    result = stacker.denoise(result, float(p.get("denoise", 0)))
    result = stacker.local_contrast(result, float(p.get("clarity", 0)))
    result = stacker.unsharp_mask(result, float(p.get("sharpen", 0)),
                                  float(p.get("sharpen_radius", 1.0)))
    return result


# Ziel: (Langseite px [0=Originalgröße], Ausgabe-Schärfung %)
EXPORT_TARGETS = {
    "instagram": (1080, 80), "whatsapp": (1600, 70), "web": (2048, 60),
    "4k": (3840, 45), "print": (0, 30),
}


def export_targets(stack_dir, export_dir, targets, only=None):
    """Pro Ziel ein skaliertes + ausgabe-geschärftes Bild schreiben (für Insta/WhatsApp/…).
    „print" bleibt verlustarm: volle Auflösung, 16-bit-TIFF, mildere Schärfung.
    only=<Dateiname> exportiert NUR diese eine Datei (sonst alle Bilder im stack_dir)."""
    import stacker
    if not os.path.isdir(stack_dir):
        return
    os.makedirs(export_dir, exist_ok=True)
    files = [only] if only else os.listdir(stack_dir)
    for f in files:
        if os.path.splitext(f)[1].lower() not in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
            continue
        src = cv2.imread(os.path.join(stack_dir, f), cv2.IMREAD_UNCHANGED)
        if src is None:
            continue
        base = os.path.splitext(f)[0]
        for t in targets:
            if t not in EXPORT_TARGETS:
                continue
            longside, sharp = EXPORT_TARGETS[t]
            if t == "print":
                # Verlustarm: Originaltiefe (16-bit falls vorhanden) behalten, sanfte Schärfung
                out = stacker.unsharp_mask(src, min(sharp, 12), 1.0)
                p = os.path.join(export_dir, f"{base}_print.tif")
                cv2.imwrite(p, out, [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
                continue
            img = src
            if img.dtype != np.uint8:
                img = (img / 256).astype(np.uint8) if img.max() > 255 else img.astype(np.uint8)
            out = img
            h, w = img.shape[:2]
            if longside and max(h, w) > longside:
                s = longside / max(h, w)
                out = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
            out = stacker.unsharp_mask(out, sharp, 0.8)  # Ausgabe-Schärfung
            p = os.path.join(export_dir, f"{base}_{t}.jpg")
            cv2.imwrite(p, out, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            print(f"  Export [{t}]: {p}")


def run_own_engine(selected_dir, work_dir, args):
    """Eigene Engine (stacker.py) — ohne ShineStacker: ausrichten -> Laplace-Stack -> schreiben."""
    import stacker
    paths = list_images(selected_dir)
    if args.reverse:
        paths = paths[::-1]
    # Speicherbedarf schätzen -> bei großen Stacks gebündelt streamen.
    # Erstes LESBARES Bild als Stichprobe (korrupte/nicht dekodierbare überspringen).
    sample = None
    for p in paths:
        sample = cv2.imread(p, cv2.IMREAD_UNCHANGED)
        if sample is not None:
            break
    if sample is None:
        print("  Kein lesbares Bild im Stack — abgebrochen.", file=sys.stderr)
        return None
    per = sample.shape[0] * sample.shape[1] * (sample.shape[2] if sample.ndim == 3 else 1) * sample.itemsize
    budget = int(getattr(args, "ram_budget_gb", 3) * (1024 ** 3))
    gm_path = None  # Geister-Karte (für Anzeige + KI-Retusche-Hinweis)

    # Ausrichtungs-Modus: 'subject' (auf Motiv) wenn explizit gewählt ODER in der Automatik ein
    # deutlich bewegtes Motiv erkannt wird (Wind-Schwanken). Sonst normale (rigide/Perspektive).
    if getattr(args, "moving_subject", False):
        align_mode = "subject"
    elif getattr(args, "align_sequential", False):
        align_mode = "sequential"
    else:
        align_mode = args.transform
    if align_mode not in ("subject", "sequential") and getattr(args, "auto", False) and not args.no_align:
        span = stacker.subject_motion_span(paths)        # 0..1 (Anteil der Bildbreite)
        if span is not None and span > 0.02:             # >2 % der Bildbreite = bewegtes Motiv
            align_mode = "subject"
            print(f"  🌬️  Bewegtes Motiv erkannt (Motiv wandert ~{span*100:.0f}% der Bildbreite).")
            print("      → Richte auf das MOTIV aus statt aufs ganze Bild und verwerfe zu weit "
                  "verschobene Aufnahmen. Tipp für perfekte Ergebnisse: Stativ + windstill.")
    args._subject_aligned = (align_mode == "subject")    # nach Auto-Erkennung setzen
    need = int(per * len(paths) * 2.5)  # Frames + Pyramiden grob
    if need > budget and len(paths) > 4:
        chunk = max(3, budget // int(per * 3))
        print(f"  Großer Stack ({need // 1024**2} MB geschätzt) -> gebündelt (je {chunk} Frames)")
        pv_path = os.path.join(work_dir, "_live_preview.jpg")

        def _macro_preview(img, k):
            try:
                m = float(img.max()) or 1.0
                small = cv2.resize(img / m, (0, 0), fx=0.4, fy=0.4)
                cv2.imwrite(pv_path, np.clip(small * 255, 0, 255).astype(np.uint8),
                            [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                print(f"PREVIEW:{pv_path}"); sys.stdout.flush()
            except Exception:
                pass
        result = stacker.focus_stack_streamed(paths, align_mode=align_mode,
                                              detector=args.detector, chunk=chunk,
                                              do_align=not args.no_align,
                                              method=getattr(args, "focus_method", "pyramid"),
                                              tree=(getattr(args, "merge", "flat") == "tree"),
                                              preview_cb=_macro_preview)
        imgs = None  # nicht alle im RAM
        # Geister-Karte speicherschonend (ein Frame nach dem anderen) — auch für großen Stack
        if len(paths) >= 3:
            try:
                dmap = stacker.disagreement_map_streamed(
                    paths, align_mode=align_mode, detector=args.detector,
                    do_align=not args.no_align, log=(print if getattr(args, "ghost_map", False)
                                                     else (lambda *a: None)))
                if dmap is not None:
                    gm_path = os.path.join(work_dir, "ghostmap.jpg")
                    cv2.imwrite(gm_path, stacker.ghost_overlay_from_map(result, dmap),
                                [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                    if getattr(args, "ghost_map", False):
                        print(f"  Geister-Karte: {gm_path}")
            except Exception as e:
                print(f"  (Geister-Karte im Großstack übersprungen: {e})", file=sys.stderr)
    else:
        print(f"  Lade {len(paths)} Frames …")
        imgs = [cv2.imread(p, cv2.IMREAD_UNCHANGED) for p in paths]
        imgs = [im for im in imgs if im is not None]
        if len({im.shape for im in imgs}) > 1:
            h, w = imgs[len(imgs) // 2].shape[:2]
            imgs = [cv2.resize(im, (w, h)) if im.shape[:2] != (h, w) else im for im in imgs]
        if not args.no_align:
            print("  Ausrichten …")
            if getattr(args, "focus_breathing", False):   # F2: Focus-Breathing (geglätteter Scale-Verlauf)
                imgs = stacker.align_images_breathing(imgs, detector=args.detector, log=lambda *a: None)
            imgs = stacker.align_images(imgs, mode=align_mode, detector=args.detector)
            imgs = stacker.crop_to_overlap(imgs)        # schwarze Warp-Ränder/Striche entfernen
        _fm = getattr(args, "focus_method", "pyramid")
        _frad = getattr(args, "focus_radius", -1.0)
        _fsm = getattr(args, "focus_smoothing", -1.0)
        _reg = getattr(args, "focus_regularize", False)
        _dm_kw = {} if _frad < 0 else {"radius": _frad}
        if _fsm >= 0:
            _dm_kw["smoothing"] = _fsm
        if _reg:                                          # F4: kantenerhaltende Tiefenkarten-Regularisierung
            _dm_kw["regularize"] = True
        _avg_kw = {} if _frad < 0 else {"radius": int(round(_frad))}
        if _fsm >= 0:
            _avg_kw["smoothing"] = _fsm
        _merge1 = {"depthmap": lambda g: stacker.focus_stack_depthmap(g, log=lambda *a: None, **_dm_kw),
                   "average": lambda g: stacker.focus_stack_average(g, log=lambda *a: None, **_avg_kw),
                   "halofix": lambda g: stacker.focus_stack_halofix(g, log=lambda *a: None),
                   "pyramid-consistent": lambda g: stacker.focus_stack_pyramid_consistent(g, log=lambda *a: None),
                   "wavelet": lambda g: stacker.focus_stack_wavelet(g, log=lambda *a: None)}.get(
            _fm, lambda g: stacker.focus_stack(g, deghost=getattr(args, "deghost", False),
                                               log=lambda *a: None))
        if getattr(args, "merge", "flat") == "tree":
            print(f"  Verschmelzen (Baum-Merge, {_fm}) …")
            result = stacker.merge_tree(imgs, _merge1)
        else:
            print(f"  Verschmelzen ({_fm}) …")
            result = _merge1(imgs)
        if getattr(args, "ghost_map", False) and len(imgs) >= 3:
            gm = stacker.ghost_overlay(result, imgs)
            gm_path = os.path.join(work_dir, "ghostmap.jpg")
            cv2.imwrite(gm_path, gm, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            print(f"  Geister-Karte: {gm_path}")
        elif len(imgs) >= 3:
            # Geister-Karte intern erzeugen (für KI-Retusche-Hinweis), auch ohne --ghost-map
            try:
                gm = stacker.ghost_overlay(result, imgs)
                gm_path = os.path.join(work_dir, "ghostmap.jpg")
                cv2.imwrite(gm_path, gm, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            except Exception:
                gm_path = None
    if getattr(args, "denoise", 0) and args.denoise > 0:
        result = stacker.denoise(result, args.denoise)
    if args.sharpen > 0:
        result = stacker.unsharp_mask(result, args.sharpen, args.sharpen_radius)
    if getattr(args, "ai_enhance", False):
        result = apply_ai_enhance(result, args, ghostmap_path=gm_path)

    stack_dir = os.path.join(work_dir, "stack")
    if os.path.isdir(stack_dir):
        shutil.rmtree(stack_dir)
    os.makedirs(stack_dir)
    base = os.path.splitext(os.path.basename(paths[0]))[0]
    ext = ".tif" if result.dtype == np.uint16 else ".jpg"
    out = os.path.join(stack_dir, f"{args.prefix}{base}_stk{ext}")
    if ext == ".jpg":
        cv2.imwrite(out, result, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    else:
        cv2.imwrite(out, result, [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
    print(f"  geschrieben: {out}")

    if getattr(args, "multilayer", False):
        ml_dir = os.path.join(work_dir, "multilayer")
        os.makedirs(ml_dir, exist_ok=True)
        # Photoshop-Ebenen-TIFF: Ergebnis oben + jedes ausgerichtete Foto als Layer
        named = [("Stack (Ergebnis)", result)]
        if imgs is not None:
            named += [(f"Foto {i + 1}", im) for i, im in enumerate(imgs)]
        else:
            print("  (Ebenen-Datei: bei sehr großen Stacks nur das Ergebnis als Ebene)")
        out_ml = os.path.join(ml_dir, f"{args.prefix}{base}_stk.tif")
        try:
            stacker.write_layered_tiff(out_ml, named, flat_bgr=result)
            print(f"  Photoshop-Ebenen-Datei: {out_ml}")
        except Exception as e:
            print(f"  Mehrschicht-Datei fehlgeschlagen ({e})", file=sys.stderr)

    if getattr(args, "web_jpg", False):
        export_web_jpg(stack_dir, os.path.join(work_dir, "export"))
    if getattr(args, "export", None):
        export_targets(stack_dir, os.path.join(work_dir, "export"), args.export)
    return stack_dir


def main():
    ap = argparse.ArgumentParser(description="ForgePix — Fokus-Stacking (eigene Engine)")
    ap.add_argument("--input", required=True, help="Ordner mit den Aufnahmen")
    ap.add_argument("--work", help="Arbeits-/Projektordner (Default: <input>/../stack_work)")
    ap.add_argument("--dip-ratio", type=float, default=0.4,
                    help="Inneren Frame verwerfen, wenn peak < ratio*min(Nachbarn) (Default 0.4)")
    ap.add_argument("--abs-min", type=float, default=15.0,
                    help="Frame verwerfen, wenn peak < abs-min (strukturlos, Default 15)")
    ap.add_argument("--dedup", action="store_true",
                    help="Near-Duplicate-Culling aktivieren (VORSICHT bei Stacks)")
    ap.add_argument("--dup-thresh", type=float, default=0.004,
                    help="Near-Duplicate-Schwelle (kleiner = strenger, Default 0.004)")
    ap.add_argument("--reject-blurry", action="store_true",
                    help="Verwackelte/global unscharfe Frames automatisch aussortieren")
    ap.add_argument("--blurry-rel", type=float, default=0.45,
                    help="Verwackelt-Schwelle: Frame raus, wenn schärfste Kachel < rel*Serien-Median (Default 0.45)")
    ap.add_argument("--max-side", type=int, default=1600,
                    help="Analyse-Downscale Langseite px (Default 1600)")
    ap.add_argument("--prefix", default="stack_", help="Output-Prefix")
    # --- eigene Stacking-Engine ---
    ap.add_argument("--ram-budget-gb", type=float, default=3.0,
                    help="RAM-Budget für Frames; darüber wird gebündelt gestreamt (Default 3)")
    # --- Astro-Modus (Sterne) ---
    ap.add_argument("--astro", action="store_true",
                    help="Astro-Stacking statt Fokus-Stacking (Sterne: Rauschen mitteln)")
    ap.add_argument("--mosaic", action="store_true",
                    help="Hybrid: überlappende Kacheln zu einem Mosaik zusammensetzen (Mond/Sonne)")
    ap.add_argument("--mosaic-mode", choices=["panorama", "scans"], default="panorama",
                    help="Mosaik-Modus (panorama=mit Rotation, scans=planar)")
    ap.add_argument("--hybrid-fa", action="store_true",
                    help="Hybrid: Fokus+Astro — je Fokus-Position Shots astro-stacken (Rauschen), "
                         "dann fokus-stacken (Schärfentiefe)")
    ap.add_argument("--hybrid-group", type=int, default=5,
                    help="Fokus+Astro: Shots je Position, falls keine Unterordner vorhanden")
    ap.add_argument("--lucky", action="store_true",
                    help="Lucky-Imaging: Sonne/Mond/Planeten aus einem VIDEO stapeln — die "
                         "schärfsten Frames auswählen, ausrichten, mitteln, schärfen (AutoStakkert-Prinzip)")
    ap.add_argument("--lucky-keep", type=float, default=30,
                    help="Anteil der schärfsten Frames in %% (Standard 30)")
    ap.add_argument("--lucky-sharpen", type=float, default=60,
                    help="Nachschärfen des Lucky-Ergebnisses in %% (0 = aus)")
    ap.add_argument("--lucky-drizzle", type=float, choices=[1.0, 1.5, 3.0], default=1.0,
                    help="Lucky: Drizzle/Super-Resolution (1.5×/3×) — Sub-Pixel-Jitter füllt ein feineres "
                         "Gitter (AutoStakkert-Prinzip). Braucht echten Jitter (statisches Stativ)")
    ap.add_argument("--lucky-refine", type=int, default=0,
                    help="Lucky: zusätzliche MAP-Pässe gegen das geschärfte Ergebnis (iterative Referenz) — 0/1")
    ap.add_argument("--lucky-adaptive-ap", action="store_true",
                    help="Lucky: adaptive Alignment-Punkt-Dichte/-Größe (mehr/feinere APs in Detailzonen)")
    ap.add_argument("--hdr", action="store_true",
                    help="HDR aus Belichtungsreihen (AEB) per Exposure Fusion (Mertens) — "
                         "durchgezeichnete Lichter + Schatten. NICHT Fokus-Stacking!")
    ap.add_argument("--hdr-bracket", type=int, default=0,
                    help="Feste Gruppengröße der Belichtungsreihe (z. B. 3); 0 = automatisch erkennen")
    ap.add_argument("--hdr-look", choices=["neutral", "natural", "vivid", "dramatic"],
                    default="natural",
                    help="Tonlook fürs HDR (Exposure Fusion ist flach): neutral=aus, "
                         "natural=dezenter Pop (Standard), vivid=kräftig, dramatic=starker lokaler Kontrast")
    ap.add_argument("--hdr-deghost", choices=["off", "auto", "aggressive"], default="off",
                    help="HDR-Deghosting: in Bewegungszonen (Blätter/Personen/Autos) nur das "
                         "best-belichtete Referenzbild statt der Fusion — gegen Doppelbilder")
    ap.add_argument("--hdr-method", choices=["fusion", "radiance"], default="fusion",
                    help="fusion=Exposure Fusion (Standard, halo-frei); radiance=Radiance-Map + "
                         "Tonemapping (dramatischer lokaler Kontrast)")
    ap.add_argument("--hdr-deghost-flow", action="store_true",
                    help="HDR-Deghosting per Optical-Flow (Belichtungen aufeinander warpen statt nur "
                         "maskieren — HDR-Vorteil bleibt in Bewegungszonen erhalten)")
    ap.add_argument("--hdr-tonemap", choices=["reinhard", "mantiuk", "drago", "local"], default="reinhard",
                    help="Tonemapping-Operator für --hdr-method radiance")
    ap.add_argument("--longexp", action="store_true",
                    help="Langzeitbelichtung aus einer Serie (Wasser/Wolken/Lichtspuren) ohne ND-Filter")
    ap.add_argument("--longexp-gapfill", action="store_true",
                    help="Langzeit/Spuren: Lücken in Strichspuren ueberbruecken (gegen gestrichelte "
                         "Spuren durch Schreibpausen zwischen den Frames)")
    ap.add_argument("--longexp-sigma", action="store_true",
                    help="Langzeit (smooth/declutter): Sigma-Clipping statt rohem Mittel/Median — "
                         "verwirft Ausreisser (Voegel, Satelliten, Hotpixel, Funkeln) sauber")
    ap.add_argument("--longexp-freeze", type=float, default=None, metavar="ANTEIL",
                    help="Vordergrund einfrieren (Sequator-Stil): unterste ANTEIL (0..1) der "
                         "Bildhoehe scharf aus einem Einzelbild, nur der Himmel wird langzeitbelichtet")
    ap.add_argument("--longexp-freeze-auto", action="store_true",
                    help="Vordergrund einfrieren mit AUTOMATISCHER Himmel/Vordergrund-Trennung "
                         "(ueber die Sternbewegung) statt festem Hoehen-Anteil")
    ap.add_argument("--longexp-mode",
                    choices=["smooth", "trails", "comet", "declutter", "bright", "stars"],
                    default="smooth",
                    help="smooth=Mitteln (Wasser), trails=Aufhellen (Lichtspuren), "
                         "declutter=Median (Störer weg), bright=additiv (dunkel aufhellen)")
    ap.add_argument("--longexp-align", choices=["none", "shift", "feature"], default="none",
                    help="Ausrichten: none=Stativ, shift=leichtes Verwackeln, feature=Freihand")
    ap.add_argument("--longexp-strength", type=int, default=100,
                    help="Virtuelle Belichtungszeit 0–100 %% (gewichtetes Teil-Mitteln; "
                         "100=volle Glättung/Spuren, 0=Einzelbild eingefroren)")
    ap.add_argument("--astro-method", choices=["sigma", "winsor", "linearfit", "average", "median", "max"],
                    default="sigma", help="Astro-Stacking-Methode (Default sigma=Kappa-Sigma)")
    ap.add_argument("--astro-kappa", type=float, default=2.5, help="Kappa für Sigma-Clipping")
    ap.add_argument("--astro-local-norm", action="store_true",
                    help="Astro: lokale Normalisierung (örtlicher Hintergrundabgleich pro Frame VOR "
                         "der Rejection) — gegen Gradienten & Mehrfach-Sessions")
    ap.add_argument("--astro-stretch-mode", choices=["asinh", "mtf", "ghs"], default="mtf",
                    help="Astro-Streckung: asinh (Standard), mtf (MTF/Histogramm, reversibel, "
                         "definierter Schwarzpunkt — PixInsight-AutoSTF-Stil) oder ghs "
                         "(Generalised Hyperbolic Stretch, voll parametrisch)")
    ap.add_argument("--astro-ghs-d", type=float, default=2.5,
                    help="GHS-Intensität D (höher = aggressiver; nur bei --astro-stretch-mode ghs)")
    ap.add_argument("--astro-ghs-b", type=float, default=-0.5,
                    help="GHS-Charakter b (stärker negativ = härterer Knick; nur bei ghs)")
    ap.add_argument("--astro-ghs-sp", type=float, default=0.18,
                    help="GHS-Symmetriepunkt SP 0..1 (Pivot-Helligkeit; nur bei ghs)")
    ap.add_argument("--no-register", action="store_true", help="Astro: keine Stern-Ausrichtung")
    ap.add_argument("--astro-align", choices=["shift", "rotate"], default="shift",
                    help="Astro-Ausrichtung: shift=Translation (Nachführung), "
                         "rotate=Translation+Feldrotation (Alt-Az-Montierung)")
    ap.add_argument("--astro-cosmetic", action="store_true",
                    help="Astro: Hot-/Cold-Pixel vor dem Stacken entfernen (kosmetische Korrektur)")
    ap.add_argument("--astro-drizzle", type=int, choices=[1, 2], default=1,
                    help="Astro: 2 = doppelt hochskaliert integrieren (feineres Sampling, „Drizzle-lite“)")
    ap.add_argument("--astro-drizzle-true", action="store_true",
                    help="Astro: ECHTES Drizzle (flusserhaltendes Droppen mit pixfrac statt nur "
                         "Hochskalieren) — braucht --astro-drizzle 2 und gediterte Subs")
    ap.add_argument("--astro-pixfrac", type=float, default=0.7,
                    help="Drop-Größe fürs echte Drizzle 0.1..1 (kleiner = schärfer, braucht mehr Frames)")
    ap.add_argument("--astro-pcc", action="store_true",
                    help="Breitband: photometrischer Farbabgleich (PCC-lite) — neutralisiert die "
                         "mittlere Farbe vieler ungesättigter Sterne (robuster als Quantil-Weißpunkt; "
                         "kein Online-Katalog)")
    ap.add_argument("--astro-tps", action="store_true",
                    help="TPS-Feinregistrierung: korrigiert nach der globalen Ausrichtung die lokale "
                         "Restverzeichnung (Feldkrümmung bei Weitwinkel/Refraktor) per Thin-Plate-Spline")
    ap.add_argument("--astro-weight", action="store_true",
                    help="Astro-Integration: Frames nach SNR gewichten (1/σ_bg²) — dünne/verrauschte "
                         "Subs zählen weniger (bessere Gesamt-SNR bei gemischter Transparenz)")
    ap.add_argument("--astro-deconv-regularize", type=float, default=0.0,
                    help="Dekonvolution: TV-/Wavelet-Regularisierung pro Iteration (0=aus, ~0.01–0.1) "
                         "— dämpft Rausch-/Ring-Verstärkung")
    ap.add_argument("--astro-starless-classic", action="store_true",
                    help="Astro: zusätzlich ein klassisch sternloses Nebelbild erzeugen (morphologisch, "
                         "ohne StarNet) — für getrennte Nebel-Bearbeitung")
    ap.add_argument("--astro-pcc-backend", choices=["auto", "siril", "gaia", "lite"], default="auto",
                    help="PCC-Backend: auto=Siril-SPCC→eigener Gaia-Pfad→Lite (Fallback-Kette); "
                         "siril=nur Siril-SPCC (Gaia DR3); gaia=eigener astroquery-Gaia-Pfad; "
                         "lite=stern-basiert ohne Katalog (immer offline). Nur mit --astro-pcc.")
    ap.add_argument("--astro-oscsensor", default=None,
                    help="OSC-Sensorname EXAKT wie in Sirils SPCC-Liste (z. B. 'Sony IMX294') — "
                         "verbessert die Siril-SPCC-Genauigkeit. Optional.")
    ap.add_argument("--astro-narrowband", action="store_true",
                    help="Siril-SPCC im Schmalband-Modus (Dual-Band Ha/OIII). Standard aus, da die "
                         "Filter-Wellenlängen exakt stimmen müssen.")
    ap.add_argument("--astrometry-key", default=None,
                    help="Astrometry.net-API-Key (nova.astrometry.net) für blindes Online-Plate-Solving "
                         "im Gaia-PCC-Pfad, wenn kein Siril/lokaler Solver da ist. Alternativ Env-Var "
                         "ASTROMETRY_API_KEY. Wird nicht gespeichert/geloggt.")
    ap.add_argument("--astro-stretch", action=argparse.BooleanOptionalAction, default=True,
                    help="Astro: Anzeige-JPG strecken (Standard AN — sonst ist das JPG schwarz, weil "
                         "lineare Astro-Daten dunkel sind). --no-astro-stretch für rohes lineares JPG. "
                         "Das Ergebnis-TIFF bleibt immer linear.")
    ap.add_argument("--astro-bright", type=float, default=-1.0,
                    help="Astro-Aufhellung 5–30 (-1 = Auto/KI). Höher = schwaches Signal stärker anheben")
    ap.add_argument("--astro-saturation", type=float, default=-1.0,
                    help="Astro-Farbsättigung 1.0–1.6 (-1 = Auto/KI)")
    ap.add_argument("--astro-color", type=float, default=-1.0,
                    help="Astro-Farbkalibrierung 0.0–1.0 (-1 = Auto/KI). 0 = aus, 1 = voll neutralisieren")
    ap.add_argument("--dualband", action="store_true",
                    help="Dual-Band/Schmalband-Filter (Ha+OIII): KEINE Grün-Entfernung — OIII (teal) bleibt erhalten")
    ap.add_argument("--palette", choices=["hoo", "sho", "foraxx", "bicolor"], default="hoo",
                    help="Dual-Band-Palette: hoo (rot+teal, datentreu), sho (Hubble gold+blau, SII aus "
                         "Ha SYNTHETISIERT), foraxx (dynamisch: reines Ha rot, gemischt gold) oder "
                         "bicolor (Cannistra: synth. Grün aus Ha+OIII, natürlicher)")
    ap.add_argument("--bg-extract", action="store_true",
                    help="Astro: Hintergrund/Gradient entfernen (Lichtverschmutzung)")
    ap.add_argument("--astro-deconv", action="store_true",
                    help="Astro: Dekonvolution (Richardson-Lucy, PSF aus Sternen geschätzt) — schärft "
                         "Seeing/Optik-Verschmierung zurück, mit Stern-Schutz gegen Ringe")
    ap.add_argument("--astro-deconv-iter", type=int, default=15,
                    help="Dekonvolution: Anzahl Richardson-Lucy-Iterationen (mehr = schärfer, aber "
                         "mehr Rauschen/Ringe; 10–25 sinnvoll)")
    ap.add_argument("--astro-deconv-protect", type=float, default=0.85,
                    help="Dekonvolution: Stern-Schutz-Schwelle 0..1 (hellere Bereiche werden weich "
                         "geschützt; niedriger = mehr Schutz)")
    ap.add_argument("--astro-denoise", type=float, default=0.0,
                    help="Astro: Multi-Skalen-Wavelet-Rauschreduktion auf den LINEAREN Daten vor dem "
                         "Strecken (0=aus, 0.5–1.5 sinnvoll) — gegen Hintergrundrauschen, das der Stretch "
                         "sonst hochzieht")
    ap.add_argument("--fits-out", action="store_true",
                    help="Astro: Ergebnis zusätzlich als 32-bit-FITS speichern (PixInsight/Siril)")
    ap.add_argument("--no-astro-qc", action="store_true",
                    help="Astro: Sub-Bewertung/Aussortieren abschalten (alle Frames nehmen)")
    ap.add_argument("--bin", dest="astro_bin", type=int, choices=[1, 2, 3], default=1,
                    help="Astro: Software-Binning (2/3) — höheres SNR, rundere Sterne, halbe Auflösung")
    ap.add_argument("--also", nargs="*", default=None,
                    help="Astro: weitere Session-/Nacht-Ordner zum SELBEN Stack hinzufügen (mehr Integration)")
    ap.add_argument("--no-auto-calib", action="store_true",
                    help="Astro: Dark-/Flat-/Bias-Unterordner NICHT automatisch erkennen/anwenden")
    ap.add_argument("--astro-engine", choices=["own", "siril"], default="own",
                    help="Astro-Engine: own (eigene, Standard) oder siril (optional, falls installiert)")
    ap.add_argument("--siril-path", default=None,
                    help="Pfad zu siril-cli (sonst automatisch gesucht)")
    ap.add_argument("--dark", help="Astro: Master-Dark (Datei) oder Ordner mit Dark-Frames")
    ap.add_argument("--flat", help="Astro: Master-Flat (Datei) oder Ordner mit Flat-Frames")
    ap.add_argument("--bias", help="Astro: Master-Bias (Datei) oder Ordner mit Bias-Frames")
    ap.add_argument("--no-align", action="store_true", help="Frame-Ausrichtung überspringen")
    ap.add_argument("--transform", choices=["rigid", "homography"], default="rigid",
                    help="Ausrichtungs-Transform (rigid=Stativ/Makro, homography=Perspektive)")
    ap.add_argument("--moving-subject", action="store_true",
                    help="Auf das MOTIV ausrichten statt aufs ganze Bild — gegen Geister bei "
                         "bewegtem Motiv (Wind-Schwanken etc.); verschobene Frames werden verworfen")
    ap.add_argument("--focus-radius", type=float, default=-1.0,
                    help="Fokus (depthmap/average): Struktur-/Fenstergröße des Schärfemaßes "
                         "(Helicon-Radius; größer = ruhiger, weniger Feindetail). -1 = Standard")
    ap.add_argument("--focus-smoothing", type=float, default=-1.0,
                    help="Fokus (depthmap/average): Weichheit der Übergänge zwischen Quellbildern "
                         "(Helicon-Smoothing; Feathering gegen harte Nähte). -1/0 = aus")
    ap.add_argument("--focus-breathing", action="store_true",
                    help="Fokus: Focus-Breathing korrigieren (Vergroesserungsdrift ueber den Stack als "
                         "geglaetteter Scale-Verlauf) — gegen Stacking-Mush bei tiefen High-Mag-Stacks")
    ap.add_argument("--focus-regularize", action="store_true",
                    help="Fokus (depthmap): Tiefenkarte kantenerhaltend regularisieren (gegen Mottling)")
    ap.add_argument("--focus-method",
                    choices=["pyramid", "depthmap", "average", "halofix", "pyramid-consistent", "wavelet"],
                    default="pyramid",
                    help="Verschmelzungs-Methode: pyramid=Laplace-Pyramide (Standard, scharf, "
                         "gut für feine/weiche Strukturen wie Blüten); depthmap=Tiefenkarten-Auswahl "
                         "(für harte Tiefenkanten: Insekten, Münzen, Platinen); halofix=Dual-Output-"
                         "Halo-Retusche (DMap-Basis + PMax-Detail, Schärfe ohne Halos); "
                         "wavelet=à-trous-Detailfusion")
    ap.add_argument("--align-sequential", action="store_true",
                    help="Paarweise/sequenzielle Ausrichtung (jedes Frame auf den Nachbarn, "
                         "aufkumuliert) statt aufs globale Referenzbild — robuster bei großem "
                         "Fokusbereich / Stativ-Reihen")
    ap.add_argument("--merge", choices=["flat", "tree"], default="flat",
                    help="Verschmelzungs-Reihenfolge: flat=alle auf einmal (Standard); "
                         "tree=hierarchisch paarweise (1+2,3+4,… gutmütiger bei vielen Frames)")
    ap.add_argument("--detector", choices=["ORB", "SIFT", "AKAZE"], default="ORB",
                    help="Feature-Detektor fürs Alignment (SIFT robuster, langsamer)")
    ap.add_argument("--sharpen", type=float, default=0.0,
                    help="Nachschärfen des Ergebnisses in %% (0 = aus)")
    ap.add_argument("--sharpen-radius", type=float, default=1.0, help="Schärfungs-Radius")
    ap.add_argument("--denoise", type=float, default=0.0, help="Rauschreduktion des Ergebnisses (0 = aus)")
    ap.add_argument("--reverse", action="store_true",
                    help="Aufnahme-Reihenfolge umkehren (Sweep hinten→vorne)")
    ap.add_argument("--multilayer", action="store_true",
                    help="Mehrschicht-TIFF (Stack + Frames als Ebenen) fürs Retouching erzeugen")
    ap.add_argument("--web-jpg", action="store_true",
                    help="Zusätzlich ein teilbares 8-bit-JPG in <work>/export/ schreiben")
    ap.add_argument("--ai-enhance", action="store_true",
                    help="Treuer KI-Feinschliff (Schärfen/Klarheit/Entrauschen, KI-empfohlen)")
    ap.add_argument("--ghost-map", action="store_true",
                    help="Geister-Karte schreiben (zeigt Bewegungs-/Ghosting-Zonen)")
    ap.add_argument("--deghost", action="store_true",
                    help="In Bewegungszonen Median statt Mischung (reduziert Doppelkonturen)")
    ap.add_argument("--export", type=lambda s: [x.strip().lower() for x in s.split(",") if x.strip()],
                    default=None,
                    help="Export-Ziele (skaliert+geschärft), z.B. instagram,whatsapp,web,4k,print")
    # --- RAW-Entwicklung ---
    ap.add_argument("--no-raw-develop", action="store_true",
                    help="RAWs NICHT vorab entwickeln (direkt an ShineStacker geben)")
    ap.add_argument("--raw-wb", choices=["camera", "auto", "daylight"], default="camera",
                    help="Weißabgleich der RAW-Entwicklung (Default camera)")
    ap.add_argument("--raw-demosaic", choices=["auto", "dht", "dcb", "vng", "ahd", "amaze"],
                    default="auto",
                    help="Demosaic-Algorithmus: auto/ahd (Standard), dht (hohe Qualität, frei), "
                         "dcb (wenig Falschfarbe), vng (weich), amaze (braucht GPL-LibRaw, sonst Fallback).")
    ap.add_argument("--raw-highlights", action="store_true",
                    help="Ausgebrannte Lichter rekonstruieren (Kanal-Verhältnis + Entsättigen-zu-Weiß)")
    ap.add_argument("--lens-auto", action="store_true",
                    help="Objektivkorrektur automatisch aus der lensfun-Datenbank (wenn lensfunpy "
                         "installiert und Objektiv bekannt): Vignette, Verzeichnung, Farbquerfehler")
    ap.add_argument("--lens-vignette", type=float, default=0.0,
                    help="Manuelle Vignetten-Korrektur (>0 hellt die Ecken auf, ~0.1..0.5)")
    ap.add_argument("--lens-distortion", type=float, default=0.0,
                    help="Manuelle Verzeichnungs-Korrektur k1 (<0 Tonnen-, >0 Kissenverzeichnung)")
    ap.add_argument("--lens-ca", type=float, default=0.0,
                    help="Manuelle Farbquerfehler-Korrektur (laterale CA, ~0.001..0.01)")
    ap.add_argument("--raw-auto-bright", action="store_true",
                    help="Auto-Helligkeit aktivieren (Default aus = treu)")
    ap.add_argument("--raw-bps", type=int, choices=[8, 16], default=16,
                    help="Bit-Tiefe der entwickelten TIFFs (Default 16)")
    ap.add_argument("--raw-half", action="store_true",
                    help="RAW in halber Auflösung entwickeln (schneller)")
    ap.add_argument("--vlm-endpoint", help="OpenAI-kompat. Basis-URL, z.B. http://100.86.70.71:8000/v1")
    ap.add_argument("--vlm-model", default="Qwen/Qwen3.6-27B-FP8",
                    help="Vision-Modell-ID (vLLM /v1/models), Default Qwen/Qwen3.6-27B-FP8")
    ap.add_argument("--vlm-key", default=None,
                    help="API-Schlüssel (OpenAI/OpenRouter/…); leer bei lokalem Server")
    ap.add_argument("--vlm-qc", action="store_true",
                    help="Per-Frame Wind/Bewegungs-QC durchs VLM (braucht --vlm-endpoint)")
    ap.add_argument("--auto", action="store_true",
                    help="Automatik: KI bestimmt alle Settings, max. Qualität (16-bit + Ebenen-TIFF)")
    ap.add_argument("--no-stack", action="store_true", help="nur cullen, nicht stacken")
    ap.add_argument("--suggest", action="store_true",
                    help="vLLM schlaegt Settings vor; gibt NUR JSON auf stdout aus")
    ap.add_argument("--wish", default=None,
                    help="Freitext-Wunsch an die KI (z.B. 'seidiges Wasser, Personen scharf')")
    ap.add_argument("--batch", action="store_true",
                    help="Jeder Unterordner des Eingabe-Ordners = eigener Stack")
    ap.add_argument("--watch", action="store_true",
                    help="Eingabe-Ordner beobachten und bei neuem stabilen Bestand stacken")
    ap.add_argument("--watch-settle", type=int, default=5,
                    help="Sekunden ohne Änderung, bevor gestackt wird (Default 5)")
    args = ap.parse_args()

    if args.suggest:
        if not args.vlm_endpoint:
            print('{"error":"--suggest braucht --vlm-endpoint"}'); sys.exit(2)
        input_dir = os.path.abspath(args.input)
        paths = list_images(input_dir)
        if not paths:
            print('{"error":"keine Bilder gefunden"}'); sys.exit(1)
        print(f"Analysiere {len(paths)} Bilder + frage vLLM …", file=sys.stderr)
        frames, _ = analyze(paths, args.max_side)
        try:
            ctx = build_ai_context(paths, args)
            sug = suggest_settings(frames, args.vlm_endpoint, args.vlm_model,
                                   getattr(args, 'vlm_key', None), context=ctx)
        except Exception as e:
            print(json.dumps({"error": str(e)})); sys.exit(1)
        print(json.dumps(sug, ensure_ascii=False))  # nur JSON auf stdout
        return

    input_dir = os.path.abspath(args.input)
    work_dir = os.path.abspath(args.work) if args.work else \
        os.path.join(os.path.dirname(input_dir), "stack_work")
    os.makedirs(work_dir, exist_ok=True)

    # Lucky-Imaging: Eingabe ist eine Video-Datei (oder ein Ordner mit Videos), kein Bild-Ordner.
    if getattr(args, "lucky", False):
        out = run_lucky(input_dir, work_dir, args)
        if out:
            print(f"\nFertig. Ergebnis in: {out}")
        return

    # Automatik erkennt selbst, ob der Ordner mehrere Serien (Unterordner) enthält.
    # NICHT bei Hybrid Fokus+Astro: dort sind Unterordner die Fokus-Positionen (kein Batch!).
    if (getattr(args, "auto", False) and not args.batch and not args.watch
            and not getattr(args, "hybrid_fa", False) and not list_images(input_dir)):
        if any(os.path.isdir(os.path.join(input_dir, d)) and list_images(os.path.join(input_dir, d))
               for d in os.listdir(input_dir)):
            args.batch = True
            print("== Automatik: mehrere Serien (Unterordner) erkannt -> Batch ==")

    if getattr(args, "batch", False):
        subs = [os.path.join(input_dir, d) for d in sorted(os.listdir(input_dir))
                if os.path.isdir(os.path.join(input_dir, d))]
        subs = [s for s in subs if list_images(s)]
        if not subs:
            print(f"Keine Unterordner mit Bildern in {input_dir}", file=sys.stderr); sys.exit(1)
        print(f"== BATCH: {len(subs)} Stacks ==")
        for s in subs:
            name = os.path.basename(s)
            print(f"\n######## Stack: {name} ########")
            try:
                process(args, s, os.path.join(work_dir, name))
            except Exception as e:
                print(f"Fehler bei {name}: {e}", file=sys.stderr)
        print(f"\n== BATCH fertig: {len(subs)} Stacks in {work_dir} ==")
    elif getattr(args, "watch", False):
        watch_loop(args, input_dir, work_dir)
    else:
        process(args, input_dir, work_dir)


def _autodetect_calibration(input_dir):
    """Dark-/Flat-/Bias-Unterordner automatisch finden (gängige Namen), damit der Nutzer sie nicht
    von Hand setzen muss. Sucht im Eingabe-Ordner UND im übergeordneten Ordner. Gibt (dark, flat,
    bias) als Ordnerpfade oder None zurück."""
    names = {"dark": ("dark", "darks"), "flat": ("flat", "flats", "flatfield"),
             "bias": ("bias", "biases", "offset", "offsets")}
    found = {"dark": None, "flat": None, "bias": None}
    roots = [input_dir, os.path.dirname(os.path.abspath(input_dir))]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for d in sorted(os.listdir(root)):
            full = os.path.join(root, d)
            if not os.path.isdir(full):
                continue
            low = d.lower()
            for key, keys in names.items():
                if found[key] is None and low in keys and list_images(full):
                    found[key] = full
    return found["dark"], found["flat"], found["bias"]


def _gather_session_paths(input_dir, args):
    """Light-Frames aus dem Haupt-Ordner plus optionalen weiteren Sessions/Nächten (args.also)
    zu EINEM Stack zusammenführen (mehr Integration = besseres Ergebnis)."""
    paths = list_images(input_dir)
    extra = getattr(args, "also", None) or []
    for d in extra:
        if d and os.path.isdir(d):
            more = list_images(d)
            if more:
                print(f"  + Session {os.path.basename(d.rstrip('/'))}: {len(more)} Frames")
                paths += more
    return paths


def run_astro(input_dir, work_dir, args):
    """Astro-Stacking: Kalibrierung -> Registrierung -> Rejection-Stacking -> Stretch."""
    import astro
    paths = _gather_session_paths(input_dir, args)
    if len(paths) < 2:
        print("Zu wenige Bilder für Astro.", file=sys.stderr); return None
    print(f"== Astro-Modus: {len(paths)} Frames, Methode={args.astro_method} ==")
    # Kalibrier-Frames automatisch finden, wenn nicht explizit gesetzt
    if not getattr(args, "no_auto_calib", False):
        ad, af, ab = _autodetect_calibration(input_dir)
        for attr, val, label in (("dark", ad, "Dark"), ("flat", af, "Flat"), ("bias", ab, "Bias")):
            if val and not getattr(args, attr, None):
                setattr(args, attr, val)
                print(f"  Kalibrierung automatisch erkannt: {label}-Ordner „{os.path.basename(val)}“")

    def load_master(spec, name):
        if not spec:
            return None
        if os.path.isdir(spec):
            ims = list_images(spec)
            if not ims:
                return None
            print(f"  Master-{name} aus {len(ims)} Frames")
            return astro._master(ims)
        print(f"  Master-{name}: {os.path.basename(spec)}")
        return astro._master(spec)

    # Sub-Qualität bewerten + schlechte aussortieren (FWHM/Sterne/Guiding/Wolken/Spuren)
    if not getattr(args, "no_astro_qc", False):
        import astro_quality
        print("  Sub-Bewertung (erklärbar, klassisch) …")
        _frames, kept = astro_quality.select_subs(paths)
        # Optional: KI fasst in Klartext zusammen, welche Subs warum rausfliegen (nur Text, datensparsam)
        if getattr(args, "vlm_endpoint", None):
            try:
                summary = astro_quality.subs_summary_text(_frames)
                prompt = ("Du erklärst einem Astrofotografen die automatische Sub-Auswahl (Light-Frames) "
                          "in 1-3 kurzen, freundlichen Sätzen auf Deutsch. Nenne die Hauptgründe "
                          "(Wolken/Dunst=wenige Sterne, Guidingfehler=längliche Sterne, unscharf=FWHM, "
                          "Spuren). Keine Zahlen-Wiederholung, nur Klartext. Daten:\n" + summary)
                txt = _vlm_chat(args.vlm_endpoint, args.vlm_model,
                                [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                                max_tokens=200, api_key=getattr(args, 'vlm_key', None))
                if txt.strip():
                    print("  KI-Erklärung Sub-Auswahl: " + txt.strip())
            except Exception as e:
                print(f"  (KI-Erklärung übersprungen: {e})", file=sys.stderr)
        if len(kept) >= 2:
            paths = kept
        else:
            print("  (zu wenige gute Subs erkannt — nutze alle)")

    # --- Engine: eigene oder optional Siril ---
    if getattr(args, "astro_engine", "own") == "siril":
        import siril_engine
        if not siril_engine.available(getattr(args, "siril_path", None)):
            print("  Siril nicht gefunden — nutze eigene Engine", file=sys.stderr)
        else:
            print("  == Astro-Engine: Siril (extern) ==")
            try:
                tif = siril_engine.run_siril_astro(
                    paths, work_dir, kappa=args.astro_kappa,
                    dark=getattr(args, "dark", None), flat=getattr(args, "flat", None),
                    bias=getattr(args, "bias", None), siril_path=getattr(args, "siril_path", None))
                sr = cv2.imread(tif, cv2.IMREAD_UNCHANGED)
                if sr is None:
                    raise RuntimeError("Siril-Ergebnis nicht lesbar")
                result = sr.astype(np.float32) / (65535.0 if sr.dtype == np.uint16 else 255.0)
                if result.ndim == 2:
                    result = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
                return _astro_write(result, work_dir, paths, args, astro)
            except Exception as e:
                print(f"  Siril fehlgeschlagen ({e}) — nutze eigene Engine", file=sys.stderr)

    dark = load_master(getattr(args, "dark", None), "Dark")
    flat = load_master(getattr(args, "flat", None), "Flat")

    reg_dir = os.path.join(work_dir, "registered")
    if os.path.isdir(reg_dir):
        shutil.rmtree(reg_dir)
    align_mode = getattr(args, "astro_align", "shift")
    drizzle = getattr(args, "astro_drizzle", 1)
    cosmetic = getattr(args, "astro_cosmetic", False)
    extras = [f"Ausrichtung={align_mode}"]
    if cosmetic:
        extras.append("Hot-Pixel-Korrektur")
    if drizzle > 1:
        extras.append(f"Drizzle {drizzle}×")
    drizzle_true = getattr(args, "astro_drizzle_true", False) and drizzle > 1
    if drizzle_true:
        extras.append(f"echtes Drizzle (pixfrac {getattr(args, 'astro_pixfrac', 0.7)})")
    print(f"  Registrieren … ({', '.join(extras)})")
    pv_path = os.path.join(work_dir, "_live_preview.jpg")

    def _preview_cb(img01, i, n):
        try:
            v = astro.autostretch(img01, strength=6.0, saturation=1.05)
            small = cv2.resize(v, (0, 0), fx=0.4, fy=0.4)
            cv2.imwrite(pv_path, np.clip(small * 255, 0, 255).astype(np.uint8),
                        [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            print(f"PREVIEW:{pv_path}")
            sys.stdout.flush()
        except Exception:
            pass

    if drizzle_true:
        # Echtes Drizzle integriert Registrierung + flusserhaltendes Droppen in EINEM Schritt
        # (kein separates Resampling/Stacken) → behält die Sub-Pixel-Dither-Diversität.
        print(f"  Drizzle-Integration ({drizzle}×, pixfrac={getattr(args, 'astro_pixfrac', 0.7)}) …")
        result = astro.drizzle_stack(paths, scale=drizzle,
                                     pixfrac=getattr(args, "astro_pixfrac", 0.7),
                                     dark=dark, flat=flat, cosmetic=cosmetic,
                                     detector=getattr(args, "detector", "ORB"))
    else:
        aligned = astro.register_and_cache(paths, reg_dir, dark, flat,
                                           do_register=not args.no_register,
                                           align_mode=align_mode, cosmetic=cosmetic,
                                           drizzle=drizzle, detector=getattr(args, "detector", "ORB"),
                                           tps=getattr(args, "astro_tps", False))
        print(f"  Stacken ({args.astro_method}, kappa={args.astro_kappa}) …")
        result = astro.stack(aligned, method=args.astro_method, kappa=args.astro_kappa, normalize=True,
                             local_norm=getattr(args, "astro_local_norm", False),
                             weight=getattr(args, "astro_weight", False), preview_cb=_preview_cb)
    binf = int(getattr(args, "astro_bin", 1) or 1)
    if binf > 1:
        result = astro.bin_image(result, binf)
        print(f"  {binf}×-Binning → {result.shape[1]}×{result.shape[0]} (besseres SNR, rundere Sterne)")
    out = _astro_write(result, work_dir, paths, args, astro)
    shutil.rmtree(reg_dir, ignore_errors=True)
    return out


def _detect_dualband(paths):
    """Dual-Band/Schmalband-Filter aus dem FITS-Header (FILTER-Keyword) erkennen, falls vorhanden.
    Greift nur, wenn der Aufnahme-Filter in den Metadaten steht (viele Setups schreiben ihn NICHT)."""
    try:
        from astropy.io import fits
    except Exception:
        return False
    nb = ("dual", "duo", "extreme", "enhance", "oiii", "o3", "ha+", "ha/", "sho", "hoo",
          "triband", "tri-band", "narrowband", "schmalband", "alp-t", "alpt", "multi-narrow")
    for p in paths[:1]:
        if os.path.splitext(p)[1].lower() not in (".fit", ".fits", ".fts"):
            return False
        try:
            filt = str(fits.getheader(p).get("FILTER", "")).lower()
        except Exception:
            return False
        if filt and any(k in filt for k in nb):
            print(f"  Dual-Band/Schmalband-Filter erkannt (FILTER={filt}) — Grün-Entfernung aus")
            return True
    return False


def _dualband_view(result, palette, astro):
    """Dual-Band-Vorschau nach gewählter Palette: hoo (rot+teal), sho (gold+blau),
    foraxx (dynamisch) oder bicolor (synth. Grün, Cannistra). Default hoo."""
    if palette == "sho":
        return astro.dualband_sho(result)
    if palette == "foraxx":
        return astro.dualband_foraxx(result)
    if palette == "bicolor":
        return astro.dualband_bicolor(result)
    return astro.dualband_hoo(result)


def _astro_write(result, work_dir, paths, args, astro):
    """Astro-Ergebnis schreiben: optional Hintergrund-Extraktion, dann 16-bit-Linear +
    32-bit-Linear (GraXpert/StarNet/PixInsight) + gestreckte Vorschau-JPG."""
    if getattr(args, "bg_extract", False):
        print("  Hintergrund/Gradient entfernen …")
        result = astro.background_extract(result)
    if getattr(args, "astro_deconv", False):
        print("  Dekonvolution (Richardson-Lucy, PSF aus Sternen) …")
        result = astro.deconvolve(result, iterations=getattr(args, "astro_deconv_iter", 15),
                                  star_protect=getattr(args, "astro_deconv_protect", 0.85),
                                  regularize=getattr(args, "astro_deconv_regularize", 0.0))
    _dn = float(getattr(args, "astro_denoise", 0.0) or 0.0)
    if _dn > 0:
        # Luminanz-Rauschreduktion auf den LINEAREN Daten (vor dem Strecken — PixInsight-MMT-Prinzip):
        # Multi-Skalen-Soft-Threshold; sonst zieht der Stretch das Hintergrundrauschen ungebremst hoch.
        print(f"  Rauschreduktion (Multi-Skalen-Wavelet, Stärke {_dn:.2f}) …")
        import wavelet
        result = wavelet.wavelet_denoise(result.astype(np.float32), strength=_dn)
    stack_dir = os.path.join(work_dir, "stack")
    if os.path.isdir(stack_dir):
        shutil.rmtree(stack_dir)
    os.makedirs(stack_dir)
    base = os.path.splitext(os.path.basename(paths[0]))[0]
    lin = np.clip(result * 65535, 0, 65535).astype(np.uint16)
    cv2.imwrite(os.path.join(stack_dir, f"{args.prefix}{base}_astro_linear.tif"),
                lin, [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
    if getattr(args, "astro_starless_classic", False):     # A6: klassisch sternloses Nebelbild
        try:
            print("  Klassisches Star-Removal (morphologisch) …")
            starless, _smask = astro.remove_stars(result)
            sv = astro.autostretch(astro.remove_green_cast(astro.color_balance(starless, 1.0)))
            cv2.imwrite(os.path.join(stack_dir, f"{args.prefix}{base}_starless_classic.jpg"),
                        np.clip(sv * 255, 0, 255).astype(np.uint8), [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        except Exception as e:
            print(f"  (Star-Removal übersprungen: {e})", file=sys.stderr)
    try:
        import tifffile
        out32 = os.path.join(stack_dir, f"{args.prefix}{base}_astro_linear_32bit.tif")
        tifffile.imwrite(out32, cv2.cvtColor(result.astype(np.float32), cv2.COLOR_BGR2RGB),
                         photometric="rgb")
        print(f"  32-bit Linear (GraXpert/StarNet++/PixInsight): {out32}")
    except Exception as e:
        print(f"  32-bit-Export übersprungen ({e})", file=sys.stderr)
    if getattr(args, "fits_out", False):
        try:
            from astropy.io import fits
            rgb = cv2.cvtColor(result.astype(np.float32), cv2.COLOR_BGR2RGB)
            data = np.moveaxis(rgb, -1, 0)            # (H,W,C) -> (C,H,W) FITS-Konvention
            outf = os.path.join(stack_dir, f"{args.prefix}{base}_astro_linear.fits")
            hdu = fits.PrimaryHDU(data.astype(np.float32))
            hdu.header["BSCALE"] = 1.0
            hdu.writeto(outf, overwrite=True)
            print(f"  FITS (32-bit linear): {outf}")
        except Exception as e:
            print(f"  FITS-Export übersprungen ({e})", file=sys.stderr)
    # Aufbereitung NUR fürs Vorschau-Bild (lineare Exports oben bleiben faithful für PixInsight).
    # Drei Regler: Farbkalibrierung · Aufhellung · Sättigung. Reihenfolge: manuell (CLI/GUI) hat
    # Vorrang, sonst schlägt die KI vor (wenn Server da), sonst Standardwerte.
    dualband = bool(getattr(args, "dualband", False)) or _detect_dualband(paths)
    man_color = float(getattr(args, "astro_color", -1.0))
    man_bright = float(getattr(args, "astro_bright", -1.0))
    man_sat = float(getattr(args, "astro_saturation", -1.0))
    color_s = man_color if man_color >= 0 else 1.0
    strength = man_bright if man_bright > 0 else 6.0
    sat = man_sat if man_sat > 0 else 1.05
    protect = True

    def _broadband(res):
        # Breitband-Farbe: optional echtes PCC (Siril-SPCC/Gaia/Lite-Fallback) statt einfachem
        # Farbabgleich, + SCNR. PCC arbeitet auf den LINEAREN Daten (richtig vor dem Strecken).
        if getattr(args, "astro_pcc", False):
            try:
                import photometric
                hints = photometric.fits_hints(paths[0]) if paths else {}
                akey = getattr(args, "astrometry_key", None) or os.environ.get("ASTROMETRY_API_KEY")
                cal = photometric.run_pcc(res, hints=hints,
                                          prefer=getattr(args, "astro_pcc_backend", "auto"),
                                          oscsensor=getattr(args, "astro_oscsensor", None) or None,
                                          narrowband=getattr(args, "astro_narrowband", False),
                                          siril_path=getattr(args, "siril_path", None),
                                          astrometry_key=(akey or None))
            except Exception as e:
                print(f"  PCC fehlgeschlagen ({e}) → Standard-Farbabgleich", file=sys.stderr)
                cal = astro.color_balance(res, color_s)
        else:
            cal = astro.color_balance(res, color_s)
        return astro.remove_green_cast(cal)

    if args.astro_stretch:
        if getattr(args, "vlm_endpoint", None):
            try:
                preview = astro.autostretch(astro.color_balance(result, color_s))
                p = ai_astro_stretch_params(preview, args.vlm_endpoint, args.vlm_model,
                                            getattr(args, "vlm_key", None))
                if man_color < 0:
                    color_s = p["color"]
                if man_bright <= 0:
                    strength = p["strength"]
                if man_sat <= 0:
                    sat = p["saturation"]
                protect = p["protect_core"]
                print(f"  KI-Aufbereitung: Farbkalibrierung {color_s:.2f}, Aufhellung {strength:.0f}, "
                      f"Sättigung {sat:.2f}, Kern-Schutz {'an' if protect else 'aus'} — "
                      f"{p.get('rationale', '')}")
            except Exception as e:
                print(f"  (KI-Aufbereitung übersprungen: {e})", file=sys.stderr)
        # Dual-Band: Hα/OIII trennen → HOO (rot+teal), SHO (gold+blau) oder Foraxx (dynamisch).
        # Breitband: Farbkalibrierung (optional PCC-lite, stern-photometrisch) + SCNR.
        def _broadband(res):
            cal = (astro.photometric_balance(res, color_s) if getattr(args, "astro_pcc", False)
                   else astro.color_balance(res, color_s))
            return astro.remove_green_cast(cal)
        if dualband:
            base_view = _dualband_view(result, getattr(args, "palette", "hoo"), astro)
        else:
            base_view = _broadband(result)
        _sm = getattr(args, "astro_stretch_mode", "asinh")
        if _sm == "mtf":
            view = astro.mtf_stretch(base_view, saturation=sat)
        elif _sm == "ghs":
            view = astro.ghs_stretch(base_view, D=getattr(args, "astro_ghs_d", 2.5),
                                     b=getattr(args, "astro_ghs_b", -0.5),
                                     SP=getattr(args, "astro_ghs_sp", 0.18), saturation=sat)
        else:
            view = astro.autostretch(base_view, strength=strength, saturation=sat, protect_core=protect)
    else:
        if dualband:
            view = _dualband_view(result, getattr(args, "palette", "hoo"), astro)
        else:
            view = _broadband(result)
    out_view = os.path.join(stack_dir, f"{args.prefix}{base}_astro.jpg")
    cv2.imwrite(out_view, np.clip(view * 255, 0, 255).astype(np.uint8),
                [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    print(f"  geschrieben: {out_view} (+ lineares 16-bit TIFF)")
    copy_exif_to_dirs(paths[len(paths) // 2], stack_dir)  # Kamera/Objektiv/Datum übernehmen
    return stack_dir


def _hybrid_groups(input_dir, group_size):
    """Fokus-Positionen finden. Bevorzugt: je Unterordner = eine Position (mehrere Shots
    fürs Entrauschen). Sonst: alle Bilder im Ordner in Blöcke à group_size aufteilen."""
    subs = sorted(d for d in os.listdir(input_dir)
                  if os.path.isdir(os.path.join(input_dir, d)))
    groups = []
    for d in subs:
        ims = list_images(os.path.join(input_dir, d))
        if ims:
            groups.append((d, ims))
    if groups:
        return groups
    flat = list_images(input_dir)
    g = max(1, int(group_size))
    return [(f"pos{ i//g :02d}", flat[i:i + g]) for i in range(0, len(flat), g)]


def run_hybrid_focus_astro(input_dir, work_dir, args):
    """Hybrid Fokus+Astro: pro Fokus-Position mehrere Shots astro-stacken (Rauschen senken),
    danach die entrauschten Positionen fokus-stacken (Schärfentiefe). Zwei Algorithmen
    hintereinander — z.B. lichtschwache Makro-/Lunar-/Solar-Serien."""
    import astro
    groups = _hybrid_groups(input_dir, getattr(args, "hybrid_group", 5))
    if len(groups) < 2:
        print("Hybrid Fokus+Astro: <2 Fokus-Positionen gefunden. Lege je Position einen "
              "Unterordner an (mehrere Shots darin) oder erhöhe --hybrid-group.",
              file=sys.stderr)
        return None
    # Bei wenigen Shots je Position verwirft Sigma-Clipping zu viel -> average ist robuster
    method = getattr(args, "astro_method", "average")
    min_shots = min(len(ims) for _n, ims in groups)
    if method in ("sigma", "winsor") and min_shots < 8:
        print(f"  (nur {min_shots} Shot(s)/Position → average statt {method})")
        method = "average"
    print(f"== Hybrid Fokus+Astro: {len(groups)} Positionen, je Astro-Stack ({method}) ==")
    denoised_dir = os.path.join(work_dir, "denoised")
    if os.path.isdir(denoised_dir):
        shutil.rmtree(denoised_dir)
    os.makedirs(denoised_dir)
    for gi, (name, ims) in enumerate(groups):
        print(f"  Position {gi + 1}/{len(groups)} ({name}): {len(ims)} Shot(s) entrauschen …")
        if len(ims) == 1:
            den = astro._read_float(ims[0])
        else:
            reg_dir = os.path.join(work_dir, f"_reg_{gi:02d}")
            aligned = astro.register_and_cache(ims, reg_dir,
                                               do_register=not args.no_register,
                                               log=lambda *a: None)
            den = astro.stack(aligned, method=method, kappa=args.astro_kappa,
                              normalize=False, log=lambda *a: None)
            shutil.rmtree(reg_dir, ignore_errors=True)
        op = os.path.join(denoised_dir, f"pos_{gi:03d}.tif")
        cv2.imwrite(op, np.clip(den * 65535, 0, 65535).astype(np.uint16),
                    [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
    print("  -> Fokus-Stacking der entrauschten Positionen …")
    args.no_raw_develop = True  # bereits entwickelte TIFFs
    out = run_own_engine(denoised_dir, work_dir, args)
    shutil.rmtree(denoised_dir, ignore_errors=True)
    # EXIF vom ersten Original übernehmen
    first = groups[0][1][len(groups[0][1]) // 2]
    copy_exif_to_dirs(first, out, os.path.join(work_dir, "export"), os.path.join(work_dir, "multilayer"))
    return out


def run_longexp(input_dir, work_dir, args):
    """Langzeitbelichtung aus einer Serie rechnen (ohne ND-Filter)."""
    import longexp
    paths = list_images(input_dir)
    if len(paths) < 2:
        print("Zu wenige Aufnahmen für Langzeitbelichtung (mind. 2).", file=sys.stderr)
        return None
    orig_first = paths[len(paths) // 2]
    mode = args.longexp_mode
    # KI/Heuristik: Modus + Ausrichtung vorschlagen (nur Beratung). Im Auto übernehmen, sonst anzeigen.
    eff_align = args.longexp_align
    try:
        sug = longexp.suggest_mode(paths)
        print(f"  Vorschlag: Modus „{sug['mode']}“ — {sug['rationale']}")
        if getattr(args, "auto", False):
            mode = sug["mode"]
            eff_align = sug.get("align", eff_align)          # Schwenk/Drift-Ausrichtung mit übernehmen
        elif args.longexp_align == "none" and sug.get("align", "none") != "none":
            # User hat „nicht ausrichten“ gelassen, aber die Heuristik sieht Kamerabewegung → übernehmen
            # (sonst verschmiert die ganze Szene — genau der Stativ-Fehlannahme-Fall).
            eff_align = sug["align"]
            print(f"    → Ausrichtung automatisch auf „{eff_align}“ gesetzt (Kamerabewegung erkannt)")
    except Exception as e:
        print(f"  (Modus-Vorschlag übersprungen: {e})", file=sys.stderr)
    strength = max(0, min(100, getattr(args, "longexp_strength", 100))) / 100.0
    print(f"== Langzeitbelichtung: {len(paths)} Aufnahmen, Modus={mode}, "
          f"Ausrichten={eff_align}, virtuelle Belichtung={int(strength*100)} % ==")
    if mode == "stars":
        # H1: Punkt-Stern-Stacking mit Feldrotations-Ausgleich (Sequator-Stil) — Sterne werden NICHT
        # zu Strichspuren, sondern punktförmig gestackt (Rauschgewinn √N).
        result = longexp.stack_stars_point(paths, work_dir=work_dir, align="auto",
                                           sigma_clip=getattr(args, "longexp_sigma", False))
    else:
        result = longexp.combine(paths, mode=mode, align=eff_align, strength=strength,
                                 work_dir=work_dir, detector=args.detector, transform=args.transform,
                                 gap_fill=getattr(args, "longexp_gapfill", False),
                                 sigma_clip=getattr(args, "longexp_sigma", False),
                                 freeze_below=getattr(args, "longexp_freeze", None),
                                 freeze_auto=getattr(args, "longexp_freeze_auto", False))

    stack_dir = os.path.join(work_dir, "stack")
    if os.path.isdir(stack_dir):
        shutil.rmtree(stack_dir)
    os.makedirs(stack_dir)
    base = os.path.splitext(os.path.basename(orig_first))[0]
    out = os.path.join(stack_dir, f"{args.prefix}{base}_langzeit_{mode}.tif")
    cv2.imwrite(out, np.clip(result * 65535, 0, 65535).astype(np.uint16),
                [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
    out_jpg = os.path.join(stack_dir, f"{args.prefix}{base}_langzeit_{mode}.jpg")
    cv2.imwrite(out_jpg, np.clip(result * 255, 0, 255).astype(np.uint8),
                [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    print(f"  geschrieben: {out_jpg} (+ 16-bit TIFF)")
    if getattr(args, "web_jpg", False):
        export_web_jpg(stack_dir, os.path.join(work_dir, "export"))
    if getattr(args, "export", None):
        export_targets(stack_dir, os.path.join(work_dir, "export"), args.export)
    copy_exif(orig_first, [out, out_jpg])
    return stack_dir


def run_mosaic(input_dir, work_dir, args):
    """Hybrid: überlappende Kacheln zu einem Mosaik zusammensetzen."""
    import mosaic
    paths = list_images(input_dir)
    if len(paths) < 2:
        print("Zu wenige Kacheln fürs Mosaik.", file=sys.stderr); return None
    print(f"== Hybrid: Mosaik aus {len(paths)} Kacheln ({args.mosaic_mode}) ==")
    pano, _ = mosaic.stitch(paths, mode=args.mosaic_mode)
    stack_dir = os.path.join(work_dir, "stack")
    if os.path.isdir(stack_dir):
        shutil.rmtree(stack_dir)
    os.makedirs(stack_dir)
    base = os.path.splitext(os.path.basename(paths[0]))[0]
    out = os.path.join(stack_dir, f"{args.prefix}{base}_mosaik.jpg")
    cv2.imwrite(out, pano, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    print(f"  geschrieben: {out} ({pano.shape[1]}x{pano.shape[0]})")
    if getattr(args, "web_jpg", False):
        export_web_jpg(stack_dir, os.path.join(work_dir, "export"))
    if getattr(args, "export", None):
        export_targets(stack_dir, os.path.join(work_dir, "export"), args.export)
    copy_exif_to_dirs(paths[len(paths) // 2], stack_dir, os.path.join(work_dir, "export"))
    return stack_dir


VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".ser"}


def run_lucky(input_path, work_dir, args):
    """Lucky-Imaging-Stack aus Video(s): Sonne/Mond/Planeten — schärfste Frames stapeln.
    `input_path` darf eine Video-Datei ODER ein Ordner mit Videos sein."""
    import lucky
    if os.path.isfile(input_path) and os.path.splitext(input_path)[1].lower() in VIDEO_EXTS:
        vids = [input_path]
    elif os.path.isdir(input_path):
        vids = sorted(os.path.join(input_path, f) for f in os.listdir(input_path)
                      if os.path.splitext(f)[1].lower() in VIDEO_EXTS)
    else:
        vids = []
    if not vids:
        print("Keine Video-Datei für Lucky-Imaging gefunden (mp4/avi/mov …).", file=sys.stderr)
        return None
    stack_dir = os.path.join(work_dir, "stack")
    if os.path.isdir(stack_dir):
        shutil.rmtree(stack_dir)
    os.makedirs(stack_dir)
    pv = os.path.join(work_dir, "_live_preview.jpg")

    def _pv(img, k):
        try:
            cv2.imwrite(pv, cv2.resize(img, (0, 0), fx=0.6, fy=0.6),
                        [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            print(f"PREVIEW:{pv}"); sys.stdout.flush()
        except Exception:
            pass

    made = []
    for v in vids:
        print(f"== Lucky-Imaging: {os.path.basename(v)} ==")
        base = os.path.splitext(os.path.basename(v))[0]
        # 1) IMMER: das schärfste Einzelbild herausziehen (zuverlässig, schlägt den Stack bei
        #    strukturarmen/niedrig aufgelösten Zielen wie einer glatten Sonnenscheibe).
        try:
            sc, _ = lucky.grade_video(v, max_frames=2000, log=_pv and (lambda *a: None) or print)
            cap0 = cv2.VideoCapture(v); cap0.set(cv2.CAP_PROP_POS_FRAMES, sc[0][1])
            ok0, bf = cap0.read(); cap0.release()
            if ok0 and bf is not None:
                bf_jpg = os.path.join(stack_dir, f"{args.prefix}{base}_bestframe.jpg")
                cv2.imwrite(bf_jpg, bf, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                made.append(bf_jpg)
                print(f"  schärfstes Einzelbild: {bf_jpg}")
        except Exception as e:
            print(f"  (Bestframe übersprungen: {e})", file=sys.stderr)
        # 2) Multi-Point-(MAP)-Stack — glänzt bei DETAILREICHEN Zielen (Mond-Krater, Jupiter-Bänder);
        #    bei glatten/komprimierten Scheiben kann das Einzelbild schärfer sein. Beide ausgeben.
        try:
            # Schärfung passiert JETZT in lucky_stack_map selbst (AutoStakkert/RegiStax-Prinzip:
            # Stack mittelt das Rauschen weg, Wavelet-Schärfung holt die Auflösung zurück) — kein
            # doppeltes Schärfen mehr. lucky-sharpen 0..100 → interner Faktor (60 ≈ 1.0).
            res = lucky.lucky_stack_map(v, keep_global=0.6,
                                        keep_local=getattr(args, "lucky_keep", 40) / 100.0,
                                        sharpen=getattr(args, "lucky_sharpen", 60) / 60.0,
                                        drizzle=getattr(args, "lucky_drizzle", 1.0),
                                        refine_passes=getattr(args, "lucky_refine", 0),
                                        adaptive_ap=getattr(args, "lucky_adaptive_ap", False),
                                        preview_cb=_pv)
        except Exception as e:
            print(f"  MAP-Stack übersprungen: {e}", file=sys.stderr)
            res = None
        if res is not None:
            out_jpg = os.path.join(stack_dir, f"{args.prefix}{base}_map.jpg")
            cv2.imwrite(out_jpg, res, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            cv2.imwrite(os.path.join(stack_dir, f"{args.prefix}{base}_map.tif"), res,
                        [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
            made.append(out_jpg)
            print(f"  Multi-Point-Stack: {out_jpg}")
        print("  Tipp: Bei detailreichen Zielen (Mond/Planeten) gewinnt meist der MAP-Stack, "
              "bei glatten Scheiben das Einzelbild — vergleiche beide.")
    if not made:
        return None
    if getattr(args, "web_jpg", False):
        export_web_jpg(stack_dir, os.path.join(work_dir, "export"))
    return stack_dir


def run_hdr(input_dir, work_dir, args):
    """HDR aus Belichtungsreihen (AEB) per Exposure Fusion (Mertens). Erkennt mehrere Reihen
    in einem Ordner automatisch (oder feste Gruppengröße via --hdr-bracket)."""
    import hdr
    import constants
    paths = list_images(input_dir)
    if len(paths) < 2:
        print("Zu wenige Aufnahmen für HDR (mind. 2 Belichtungen).", file=sys.stderr)
        return None

    def load(p):                                         # RAW treu entwickeln, sonst einlesen
        if os.path.splitext(p)[1].lower() in constants.RAW_EXTS:
            return develop_raw_to_bgr(p, wb=getattr(args, "raw_wb", "camera"), bps=8)
        return cv2.imread(p, cv2.IMREAD_UNCHANGED)

    groups = hdr.split_brackets(paths, size=getattr(args, "hdr_bracket", 0))
    print(f"== HDR-Modus: {len(paths)} Aufnahmen → {len(groups)} Belichtungsreihe(n) ==")
    stack_dir = os.path.join(work_dir, "stack")
    if os.path.isdir(stack_dir):
        shutil.rmtree(stack_dir)
    os.makedirs(stack_dir)
    made = []
    for gi, grp in enumerate(groups):
        print(f"  Reihe {gi + 1}/{len(groups)} ({len(grp)} Belichtungen) …")
        imgs = [im for im in (load(p) for p in grp) if im is not None]
        if len(imgs) < 2:
            print("    (übersprungen — zu wenige lesbare Bilder)")
            continue
        _tm = getattr(args, "hdr_tonemap", "reinhard")
        if _tm == "local":
            # H2: lokales Durand-Tonemapping auf die SAUBERE Exposure-Fusion anwenden (nicht auf die
            # Radiance-Map — die rauscht in tiefen Schatten und tonemapping verstärkt Farb-Flecken;
            # auf echten Nacht-Reihen verifiziert: Fusion+Durand bleibt farbsauber).
            result = hdr.merge_exposures(imgs, align=not getattr(args, "no_align", False),
                                         deghost=getattr(args, "hdr_deghost", "off"),
                                         flow=getattr(args, "hdr_deghost_flow", False))
            result = hdr.tonemap_local(result, strength=1.0)
        elif getattr(args, "hdr_method", "fusion") == "radiance":
            times = hdr.read_exposure_times(grp)        # echte EXIF-Zeiten → korrekte CRF-Kalibrierung
            result = hdr.merge_radiance(imgs, times=times, tonemap=_tm)
        else:
            result = hdr.merge_exposures(imgs, align=not getattr(args, "no_align", False),
                                         deghost=getattr(args, "hdr_deghost", "off"),
                                         flow=getattr(args, "hdr_deghost_flow", False))
        result = hdr.apply_look(result, getattr(args, "hdr_look", "natural"))
        base = os.path.splitext(os.path.basename(grp[len(grp) // 2]))[0]
        out_jpg = os.path.join(stack_dir, f"{args.prefix}{base}_hdr.jpg")
        cv2.imwrite(out_jpg, result, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        out_tif = os.path.join(stack_dir, f"{args.prefix}{base}_hdr.tif")
        cv2.imwrite(out_tif, result, [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
        copy_exif(grp[len(grp) // 2], [out_jpg, out_tif])
        made.append(out_jpg)
        print(f"    geschrieben: {out_jpg}")
    if not made:
        print("  (kein HDR erzeugt)", file=sys.stderr)
        return None
    if getattr(args, "web_jpg", False):
        export_web_jpg(stack_dir, os.path.join(work_dir, "export"))
    return stack_dir


def process(args, input_dir, work_dir):
    """Ein kompletter Durchlauf: analysieren -> cullen -> (VLM-QC) -> stacken."""
    if getattr(args, "hdr", False):
        out = run_hdr(input_dir, work_dir, args)
        if out:
            print(f"\nFertig. Ergebnis in: {out}")
        return out
    if getattr(args, "longexp", False):
        out = run_longexp(input_dir, work_dir, args)
        if out:
            print(f"\nFertig. Ergebnis in: {out}")
        return out
    if getattr(args, "hybrid_fa", False):
        out = run_hybrid_focus_astro(input_dir, work_dir, args)
        if out:
            print(f"\nFertig. Ergebnis in: {out}")
        return out
    if getattr(args, "mosaic", False):
        out = run_mosaic(input_dir, work_dir, args)
        if out:
            print(f"\nFertig. Ergebnis in: {out}")
        return out
    if getattr(args, "astro", False):
        out = run_astro(input_dir, work_dir, args)
        if out:
            print(f"\nFertig. Ergebnis in: {out}")
        return out
    paths = list_images(input_dir)
    if not paths:
        print(f"Keine Bilder in {input_dir}", file=sys.stderr); return None
    orig_first = paths[len(paths) // 2]  # Original (mittleres) für EXIF-Übernahme

    # RAW-Entwicklung -> 16-bit TIFF (treu), danach läuft alles auf den TIFFs
    raws = [p for p in paths if os.path.splitext(p)[1].lower() in RAW_EXTS]
    if raws and not args.no_raw_develop:
        dev_dir = os.path.join(work_dir, "developed")
        print(f"== RAW-Entwicklung: {len(raws)} RAW(s) -> {args.raw_bps}-bit TIFF "
              f"(WB={args.raw_wb}, auto-bright={'an' if args.raw_auto_bright else 'aus'}"
              f"{', halbe Auflösung' if args.raw_half else ''}) ==")
        develop_all(paths, dev_dir, args)
        input_dir = dev_dir
        paths = list_images(input_dir)

    print(f"== {len(paths)} Bilder analysieren ==")
    frames, grays = analyze(paths, args.max_side)

    # Auto-Modus: KI bestimmt alle Settings, Qualität wird erzwungen
    if getattr(args, "auto", False):
        args.multilayer = True   # immer Ebenen-TIFF fürs Weiterbearbeiten
        args.web_jpg = True      # immer ein teilbares JPG dazu
        args.ai_enhance = True   # Feinschliff (mit KI falls da, sonst fester Standard)
        args.reject_blurry = True  # verwackelte/unscharfe Frames automatisch raus
        sug = None
        if args.vlm_endpoint:
            print("== Automatik: KI bestimmt Einstellungen ==")
            try:
                ctx = build_ai_context([f.path for f in frames], args)
                sug = suggest_settings(frames, args.vlm_endpoint, args.vlm_model,
                                       getattr(args, 'vlm_key', None), context=ctx)
            except Exception as e:
                print(f"  KI nicht erreichbar ({e}) — nutze Heuristik", file=sys.stderr)
        if sug is None:
            print("== Automatik (ohne KI): Einstellungen aus dem Schärfeprofil ==")
            sug = heuristic_settings(frames)
        apply_suggestion_to_args(args, sug)
        show = {k: sug.get(k) for k in ("dip_ratio", "abs_min", "algo", "transform",
                                        "detector", "balance_channel", "sharpen",
                                        "bunch", "reverse", "vlm_qc")}
        print(f"  Motiv: {sug.get('subject', '?')}")
        print(f"  -> {json.dumps(show, ensure_ascii=False)}")
        print(f"  Begründung: {sug.get('rationale', '')}")

    median = cull(frames, grays, args.dip_ratio, args.abs_min, args.dedup, args.dup_thresh)

    # Verwackelte / global unscharfe Frames zusätzlich aussortieren (klassisch, erklärbar)
    if getattr(args, "reject_blurry", False):
        try:
            import focus_analysis as fa
            M = fa.sharpness_matrix([f.path for f in frames], grid=12, log=lambda *a: None)
            bad = dict((i, r) for i, _n, r in fa.detect_blurry(M, [f.path for f in frames],
                                                               rel=getattr(args, "blurry_rel", 0.45)))
            for i, f in enumerate(frames):
                if i in bad and f.keep:
                    f.keep = False
                    f.reasons.append(f"verwackelt: Schärfewert {int(bad[i]*100)}% (Median Serie 100%)")
            if bad:
                print(f"== Verwackelt-Filter: {len(bad)} Frame(s) aussortiert ==")
                for i in sorted(bad):
                    print(f"   ✗ Bild {i + 1} ({frames[i].name}) entfernt — "
                          f"Schärfewert {int(bad[i]*100)}% vom Serien-Median")
        except Exception as e:
            print(f"  (Verwackelt-Filter übersprungen: {e})", file=sys.stderr)

    if args.vlm_endpoint and getattr(args, "vlm_qc", False):
        print("== VLM-QC ==")
        vlm_qc(frames, args.vlm_endpoint, args.vlm_model, median=median, api_key=getattr(args,'vlm_key',None))

    print(f"\n{'Frame':<24}{'peak':>9}{'mean':>9}  keep  Grund")
    print("-" * 78)
    for f in frames:
        print(f"{f.name:<24}{f.peak_sharp:>9.0f}{f.mean_sharp:>9.0f}"
              f"  {'JA ' if f.keep else 'NEIN'}  {'; '.join(f.reasons)}")
    kept = [f for f in frames if f.keep]
    print(f"\n-> {len(kept)}/{len(frames)} Frames behalten (median peak {median:.0f})")

    # Survivors in selected/ kopieren
    selected_dir = os.path.join(work_dir, "selected")
    if os.path.isdir(selected_dir):
        shutil.rmtree(selected_dir)
    os.makedirs(selected_dir)
    for f in kept:
        shutil.copy2(f.path, os.path.join(selected_dir, f.name))

    report = {"input": input_dir, "work": work_dir, "median_peak": median,
              "kept": len(kept), "total": len(frames),
              "frames": [asdict(f) for f in frames]}
    with open(os.path.join(work_dir, "cull_report.json"), "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Report: {os.path.join(work_dir, 'cull_report.json')}")

    if args.no_stack:
        print("--no-stack: stoppe nach Selektion."); return None
    if len(kept) < 2:
        print("Zu wenige Frames zum Stacken.", file=sys.stderr); return None

    print("\n== Stacking ==")
    out = run_own_engine(selected_dir, work_dir, args)

    # EXIF vom Original auf alle Ausgaben übertragen
    out_files = []
    for d in (out, os.path.join(work_dir, "export"), os.path.join(work_dir, "multilayer")):
        if os.path.isdir(d):
            out_files += [os.path.join(d, f) for f in os.listdir(d)
                          if os.path.splitext(f)[1].lower() in (".jpg", ".jpeg", ".tif", ".tiff", ".png")]
    copy_exif(orig_first, out_files)

    # Qualitätsbewertung des fertigen Stacks (Schärfe / Halos / Ghosting)
    try:
        import focus_analysis as fa
        stack_imgs = [os.path.join(out, f) for f in os.listdir(out)
                      if os.path.splitext(f)[1].lower() in (".tif", ".tiff", ".jpg", ".jpeg", ".png")]
        if stack_imgs:
            res = cv2.imread(max(stack_imgs, key=os.path.getmtime), cv2.IMREAD_UNCHANGED)
            srcs = [cv2.imread(os.path.join(selected_dir, f.name), cv2.IMREAD_UNCHANGED) for f in kept[:12]]
            srcs = [s for s in srcs if s is not None]
            q = fa.stack_quality(res, srcs if len(srcs) >= 3 else None,
                                 subject_aligned=getattr(args, "_subject_aligned", False))
            # Fokus-Abdeckung der verwendeten Frames -> "Fokusbereich vollständig?"
            try:
                M = fa.sharpness_matrix([f.path for f in kept], grid=12, log=lambda *a: None)
                tp = M.max(axis=0); posv = tp[tp > 0]
                if posv.size:
                    ref = float(np.median(np.sort(posv)[-max(1, len(posv) // 4):]))
                    valid = tp > 0.15 * float(np.median(posv))
                    cov = float(((tp >= 0.25 * ref) & valid).sum() / max(1, valid.sum()))
                    q["focus_coverage"] = round(100 * cov, 1)
                    q["focus_complete"] = cov >= 0.92
                    q["findings"].insert(0, "Fokusbereich vollständig" if cov >= 0.92
                                         else f"Fokusbereich evtl. mit Lücken ({cov*100:.0f} % abgedeckt)")
                    if cov < 0.92:
                        q["score"] = max(0, q["score"] - 8)
            except Exception:
                pass
            print(f"\n== Stack-Konfidenz: {q['score']}/100 ==")
            for r in q["findings"]:
                print(f"   • {r}")
            with open(os.path.join(work_dir, "quality.json"), "w") as fh:
                json.dump(q, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  (Qualitätsbewertung übersprungen: {e})", file=sys.stderr)

    print(f"\nFertig. Ergebnis in: {out}")
    return out


def _folder_signature(folder):
    """Signatur des Bildbestands (Name+Größe) zum Erkennen von Änderungen."""
    sig = []
    for p in list_images(folder):
        try:
            sig.append((os.path.basename(p), os.path.getsize(p)))
        except OSError:
            pass
    return tuple(sorted(sig))


def watch_loop(args, input_dir, work_dir):
    """Beobachtet den Eingabe-Ordner. Sobald sich der Bildbestand 'settle' Sekunden
    nicht mehr ändert (Kopiervorgang fertig) und neu ist, wird gestackt."""
    import time
    import signal
    settle = max(2, int(getattr(args, "watch_settle", 5)))
    poll = 2
    # Sauberes Beenden: SIGTERM (GUI-Stop) NICHT mitten im Stacken hart killen
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *a: stop.__setitem__("flag", True))
    print(f"== WATCH-Modus == Ordner: {input_dir}")
    print(f"(stabil für {settle}s -> stacken; Strg-C, SIGTERM oder Stop zum Beenden)")
    last_done = None
    stable_sig, stable_since = None, 0.0
    while not stop["flag"]:
        sig = _folder_signature(input_dir)
        now = time.time()
        if sig != stable_sig:
            stable_sig, stable_since = sig, now  # Bestand ändert sich noch
        elif sig and sig != last_done and (now - stable_since) >= settle:
            print(f"\n>>> Neuer stabiler Bestand ({len(sig)} Bilder) erkannt — verarbeite …")
            try:
                process(args, input_dir, work_dir)  # läuft fertig, bevor erneut auf Stop geprüft wird
            except Exception as e:
                print(f"Fehler beim Verarbeiten: {e}", file=sys.stderr)
            last_done = sig
            print("\n... warte auf nächste Änderung im Ordner ...")
        time.sleep(poll)
    print("Watch-Modus beendet.")


if __name__ == "__main__":
    main()
