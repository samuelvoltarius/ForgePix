#!/usr/bin/env python3
"""
astro_quality.py — Sub-Bewertung für Astro (klassische Bildverarbeitung, erklärbar).

Misst pro Light-Frame: Sternzahl, FWHM (Schärfe), Elongation (Guidingfehler),
Hintergrund (Wolken/Mond/Lichtverschmutzung), Satellitenspuren. Daraus ein Score +
menschenlesbare Begründungen → schlechte Subs werden aussortiert.

Kein KI-Modell, kein GPU — nur OpenCV/NumPy. Genau die Probleme, die sich klassisch
gut lösen lassen (Satelliten, Wolken, Guiding, FWHM, Sternklassifikation).
"""
import os
import numpy as np
import cv2

from constants import RAW_EXTS, imread, log_print, require_astropy


def _read_gray(path, max_side=1600):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fit", ".fits", ".fts"):
        fits = require_astropy("FITS-Subs bewerten")
        try:
            d = np.asarray(fits.getdata(path)).astype(np.float32)
        except Exception:
            # Eine abgeschnittene Datei faellt erst beim ZUGRIFF auf die Bilddaten um, nicht
            # beim Oeffnen — astropy meldet vorher hoechstens eine Warnung. Der Fehler kommt
            # dann als `TypeError: buffer is too small for requested array` aus dem Innersten
            # von numpy, ohne den Dateinamen. `analyze_frame` erwartet hier None und meldet
            # die Aufnahme dann sauber als "nicht lesbar" — eine kaputte Datei unter 300 darf
            # keinen zweistuendigen Lauf kosten.
            return None
        if d.ndim == 3:
            d = d[0] if d.shape[0] in (3, 4) else d.mean(axis=2)
        mx = float(np.nanmax(d)) or 1.0
        g = np.nan_to_num(d / mx * 255.0)
    elif ext in RAW_EXTS:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(output_bps=8, use_camera_wb=True, no_auto_bright=True, half_size=True)
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    else:
        # ANYDEPTH: 16-bit-TIFF/PNG in voller Tiefe laden (IMREAD_GRAYSCALE allein stutzt sofort
        # auf 8 bit — der uint16-Zweig unten war dadurch unerreichbar) und sauber wandeln.
        g = imread(path, cv2.IMREAD_GRAYSCALE | cv2.IMREAD_ANYDEPTH)
    if g is None:
        return None
    if g.dtype == np.uint16:
        g = (g / 256).astype(np.uint8)
    s = max(g.shape)
    if s > max_side:
        f = max_side / s
        g = cv2.resize(g, (int(g.shape[1] * f), int(g.shape[0] * f)), interpolation=cv2.INTER_AREA)
    return g.astype(np.float32)


def detect_stars(gray, max_stars=120):
    """Sterne als helle Blobs finden; pro Stern Größe (FWHM) und Elongation via
    Pixel-Kovarianz (echte Hauptachsen, erkennt auch diagonales Trailing)."""
    bg = float(np.median(gray))
    sigma = float(np.std(gray)) + 1e-6
    mask = (gray > bg + 5 * sigma).astype(np.uint8)
    n, labels, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    order = np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1  # größte zuerst
    # ERST nach Fläche filtern, DANN Top-N nehmen — sonst verbrauchen große Nebel-/Wolken-Blobs
    # das max_stars-Budget und echte Sterne fallen heraus.
    order = [i for i in order if 3 <= int(stats[i, cv2.CC_STAT_AREA]) <= 800]
    stars = []
    for i in order[:max_stars]:
        area = int(stats[i, cv2.CC_STAT_AREA])
        ys, xs = np.where(labels == i)
        if len(xs) < 3:
            continue
        cov = np.cov(np.vstack([xs.astype(np.float32), ys.astype(np.float32)]))
        ev = np.linalg.eigvalsh(cov) if cov.ndim == 2 else np.array([area, area])
        ev = np.clip(ev, 1e-3, None)
        major, minor = float(ev.max()), float(ev.min())
        fwhm = 2.3548 * np.sqrt((major + minor) / 2.0)   # näherungsweise FWHM
        ecc = np.sqrt(major / minor)                      # 1.0 = rund, >1.5 = länglich
        stars.append((fwhm, ecc, area))
    return stars, bg


# Gerichtete Strukturelemente fuer das Oeffnen: nur laengliche Strukturen sollen uebrig
# bleiben. Sterne sind rund und kompakt und fallen dabei weg — sonst beherrschen sie die
# Hough-Abstimmung, weil es Tausende davon gibt und nur eine Spur.
_SPUR_KERNE = None


def _spur_kerne():
    global _SPUR_KERNE
    if _SPUR_KERNE is None:
        kerne = []
        for winkel in range(0, 180, 15):
            k = np.zeros((25, 25), np.uint8)
            k[12, :] = 1
            M = cv2.getRotationMatrix2D((12.0, 12.0), winkel, 1.0)
            kk = (cv2.warpAffine(k.astype(np.float32), M, (25, 25)) > 0.3).astype(np.uint8)
            if int(kk.sum()) >= 15:
                kerne.append(kk)
        _SPUR_KERNE = kerne
    return _SPUR_KERNE


def detect_trail(gray):
    """Satelliten-/Flugzeugspur: lange duenne Linie im Bild (Hough).

    **Warum hier nicht `np.std` steht.** Die alte Fassung nahm `np.std` ueber das GANZE Bild
    als Rauschmass. Das ist keine Rauschmessung: die Sterne gehen voll ein. An der einen
    M51-Aufnahme mit einer echten Satellitenspur gemessen (20230528-025013):

        Hintergrund                9,801
        robustes Sigma (MAD)       0,278
        np.std ueber alles         1,548     <- 5,6-mal zu gross
        np.std ohne die hellsten 0,47 % der Pixel   0,253   <- das echte Rauschen

    Also machen **0,47 % der Pixel — die Sterne — die ganze Ueberhoehung aus**; das hellste
    Pixel liegt 883 Sigma ueber dem Hintergrund. `bg + 4*std` ist damit faktisch viermal die
    Streuung der Sternhelligkeiten statt viermal das Rauschen:

        Ueberschuss der Spur       2,42      = 8,7 robuste Sigma
        Schwelle bg + 4*std       15,99      -> die Spur bei 12,09 liegt DARUNTER

    Eine Spur mit 8,7 Sigma fiel durch, und zwar umso sicherer, je mehr helle Sterne im Feld
    stehen. Ueber alle 340 M51-Aufnahmen gemessen fand die alte Fassung **0**, die neue **1** —
    genau die eine, die wirklich eine hat, ohne einen einzigen Fehlalarm.

    Der zweite Teil ist das gerichtete Oeffnen. Ohne es stehen Tausende Sterne in der Maske und
    beherrschen die Hough-Abstimmung; eine einzelne duenne Linie geht darin unter.
    """
    g = np.asarray(gray, np.float32)
    bg = float(np.median(g))
    sigma = float(np.median(np.abs(g - bg)) * 1.4826) + 1e-6
    maske = ((g > bg + 4.0 * sigma) * 255).astype(np.uint8)
    lang = np.zeros_like(maske)
    for kk in _spur_kerne():
        lang = np.maximum(lang, cv2.morphologyEx(maske, cv2.MORPH_OPEN, kk))
    lines = cv2.HoughLinesP(lang, 1, np.pi / 360.0, threshold=40,
                            minLineLength=int(0.25 * max(g.shape)), maxLineGap=20)
    return lines is not None and len(lines) > 0


def analyze_frame(path):
    g = _read_gray(path)
    if g is None:
        return {"name": os.path.basename(path), "ok": False, "reasons": ["nicht lesbar"]}
    stars, bg = detect_stars(g)
    n = len(stars)
    fwhm = float(np.median([s[0] for s in stars])) if stars else 99.0
    ecc = float(np.median([s[1] for s in stars])) if stars else 9.0
    trail = detect_trail(g)
    return {"name": os.path.basename(path), "path": path, "stars": n,
            "fwhm": fwhm, "ecc": ecc, "bg": bg / 255.0, "trail": trail,
            "ok": True, "reasons": []}


def subs_summary_text(frames):
    """Kompakte, neutrale Text-Zusammenfassung der Sub-Bewertung (für KI-Erklärung oder Log).
    Erwartet die frames-Liste aus select_subs (Dicts mit name/stars/fwhm/ecc/bg/keep/reasons)."""
    ok = [f for f in frames if f.get("ok")]
    kept = [f for f in ok if f.get("keep")]
    dropped = [f for f in ok if not f.get("keep")]
    lines = [f"{len(ok)} bewertbare Subs: {len(kept)} behalten, {len(dropped)} aussortiert."]
    if ok:
        import numpy as _np
        lines.append(f"Median: FWHM {_np.median([f['fwhm'] for f in ok]):.1f}, "
                     f"Sterne {_np.median([f['stars'] for f in ok]):.0f}.")
    for f in dropped:
        r = "; ".join(f.get("reasons", [])) or "Grenzwerte überschritten"
        lines.append(f"- {f['name']}: {r}")
    return "\n".join(lines)


def select_subs(paths, fwhm_factor=1.5, ecc_max=1.7, star_frac=0.5, bg_factor=1.6, log=log_print):
    """Alle Frames bewerten und schlechte aussortieren — mit Begründung je Frame.
    Schwellen relativ zum Median der Serie (robust gegen unterschiedliche Setups)."""
    frames = [analyze_frame(p) for p in paths]
    good = [f for f in frames if f["ok"]]
    if not good:
        return frames, [f["path"] for f in frames if f.get("path")]
    # Die Vergleichswerte NUR aus Aufnahmen bilden, in denen ueberhaupt Sterne gefunden wurden.
    #
    # `analyze_frame` setzt fuer eine sternlose Aufnahme die Platzhalter FWHM 99,0 und
    # Exzentrizitaet 9,0 — das heisst "nicht gemessen", nicht "sehr unscharf". Gingen diese
    # Werte in den Median ein, schalteten sich genau die Pruefungen ab, die gebraucht werden:
    # bei 6 bewoelkten von 8 Aufnahmen wurde der Sternzahl-Median 0 (Bedingung `med_stars > 0`
    # nie erfuellt) und der FWHM-Median 99,0 (`99 > 1,5*99` nie erfuellt). Die bewoelkten
    # Aufnahmen fielen dann nur noch durch die Exzentrizitaet heraus — also durch Zufall, weil
    # der Platzhalter 9,0 ueber der Schwelle 1,7 liegt. Waere er 1,0, waeren alle sechs im
    # Stapel gelandet.
    mit_sternen = [f for f in good if f["stars"] > 0]
    bezug = mit_sternen or good
    med_stars = float(np.median([f["stars"] for f in bezug]))
    med_fwhm = float(np.median([f["fwhm"] for f in bezug]))
    med_bg = float(np.median([f["bg"] for f in good]))
    kept = []
    for f in frames:
        if not f["ok"]:
            # NICHT ueberspringen, ohne es zu sagen. Vorher fielen unlesbare Aufnahmen
            # spurlos heraus: bei 8 Dateien, davon 3 unlesbar, meldete das Protokoll
            # "5/5 Subs behalten" — der Benutzer erfuhr nie, dass drei fehlten.
            log("  %s: %s ✗" % (f["name"], "; ".join(f.get("reasons") or ["nicht lesbar"])))
            continue
        r = f["reasons"]
        if f["trail"]:
            r.append("Satelliten-/Flugzeugspur")
        if f["stars"] == 0:
            # Der ehrliche Grund. Vorher stand hier "laengliche Sterne (Elongation 9,00) —
            # Guidingfehler" fuer eine Aufnahme, die ueberhaupt keine Sterne hat.
            r.append("keine Sterne gefunden — bewoelkt, beschlagen oder fehlbelichtet")
        else:
            if med_stars > 0 and f["stars"] < star_frac * med_stars:
                r.append(f"wenige Sterne ({f['stars']} vs. Median {med_stars:.0f}) — "
                         f"Wolken/Dunst?")
            if f["fwhm"] > fwhm_factor * med_fwhm:
                r.append(f"unscharf (FWHM {f['fwhm']:.1f} vs. {med_fwhm:.1f})")
            if f["ecc"] > ecc_max:
                r.append(f"längliche Sterne (Elongation {f['ecc']:.2f}) — Guidingfehler")
        if f["bg"] > bg_factor * med_bg:
            r.append("heller Hintergrund — Wolken/Mond/Lichtverschmutzung")
        f["keep"] = len(r) == 0
        log(f"  {f['name']}: Sterne={f['stars']} FWHM={f['fwhm']:.1f} "
            f"Elong={f['ecc']:.2f} BG={f['bg']:.3f} {'✓' if f['keep'] else '✗ ' + '; '.join(r)}")
        if f["keep"]:
            kept.append(f["path"])
    # Bezugsgroesse ist die Zahl der UEBERGEBENEN Aufnahmen, nicht die der lesbaren.
    unlesbar = len(frames) - len(good)
    log("  -> %d/%d Subs behalten%s"
        % (len(kept), len(frames),
           (" (%d davon nicht lesbar)" % unlesbar) if unlesbar else ""))
    return frames, kept


def best_reference(frames):
    """Index des BESTEN Subs als Registrier-Referenz — statt einfach des mittleren.

    Die Referenz bestimmt, worauf alle anderen Frames gefittet werden. Ein mittelmaessiger
    Referenz-Sub (dicke, leicht laengliche Sterne) liefert schlechtere Passungen fuer die
    ganze Serie; die Sub-Bewertung sortiert nur die AUSREISSER aus, nicht das Mittelmass.
    Siril macht das in seiner Zwei-Pass-Registrierung genauso.

    `frames` ist die Liste aus select_subs(). Bewertet werden nur behaltene Subs, nach
    Sternzahl (viel = gut), FWHM (klein = gut) und Elongation (rund = gut) — jeweils relativ
    zum Median der Serie, damit die Zahl vom Setup unabhaengig bleibt.
    Rueckgabe: Pfad des besten Subs, oder None wenn nichts bewertbar ist.
    """
    good = [f for f in frames if f.get("keep") and f.get("path")]
    if not good:
        return None
    med_fwhm = float(np.median([f["fwhm"] for f in good])) or 1.0
    med_stars = float(np.median([f["stars"] for f in good])) or 1.0

    def guete(f):
        fwhm = max(float(f.get("fwhm", med_fwhm)), 1e-6) / max(med_fwhm, 1e-6)
        ecc = max(float(f.get("ecc", 1.0)), 1.0)
        sterne = max(float(f.get("stars", 0)), 0.0) / max(med_stars, 1e-6)
        return sterne / (fwhm * ecc)

    return max(good, key=guete)["path"]
