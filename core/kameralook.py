#!/usr/bin/env python3
"""
core/kameralook.py — RAW so aussehen lassen wie das Bild der Kamera (wie Camera Raw ab Werk).

Gemessen am 23.11.2026 an 19 RAWs von 18 Herstellern: die „treue“ Entwicklung (LibRaw, sRGB,
ohne automatische Helligkeit) war im Median nur 0,58 so hell wie das Vorschaubild, das die
Kamera selbst in die RAW-Datei legt — dunkel und flau. Camera Raw und Lightroom gleichen ihr
Ergebnis an den Kamera-Look an (Profil „Adobe Farbe“ + Grundbelichtung). Hier geschieht das
ohne fremde, geschlossene Kameraprofile, für jeden Hersteller gleich:

1. Die Helligkeitsverteilung der Entwicklung wird an die des Kamera-Vorschaubilds angeglichen
   (Quantil-Abbildung, streng steigend) — Belichtung UND Tonkurve der Kamera in einem Schritt.
2. Die Kurve wirkt auf jeden Kanal, wie in Kamera-JPEGs — helle Farben laufen so weich aus.
   Was danach noch über Weiß läge, wird nicht abgeschnitten, sondern zum Weiß hin entsättigt.
3. Die Sättigung wird an die der Vorschau angeglichen, begrenzt auf 0,7 … 1,4, und in den
   Lichtern weniger angehoben als in den Mitten.

Die Vorschau ist oft anders beschnitten (Nikon Z 6II: in der Kamera entzerrt) — Verteilungen
sind dagegen unempfindlich. Wo das Kamera-JPEG ausbrennt, das RAW aber noch Zeichnung hat,
läuft statt der Nachahmung eine weiche Schulter bis Weiß (erste Fassung übernahm das Ausbrennen:
Phase One 26 %, Samsung 25 % weiße Pixel statt 6 % bzw. 0 %). Ohne brauchbare Vorschau (Sigma
fp-DNG: keine) gibt es einen klaren Rückfall: weiche Filmkurve mit Median 0,40, gemeldet. Kein Qt.
"""
import numpy as np

try:
    from constants import log_print
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)

_LUMA = np.array([0.0722, 0.7152, 0.2126], np.float32)       # BGR, Rec. 709


def vorschau(pfad):
    """Das eingebettete Kamerabild als BGR uint8 oder None."""
    import cv2
    import rawpy
    try:
        with rawpy.imread(pfad) as r:
            th = r.extract_thumb()
    except Exception:
        return None
    if th.format == rawpy.ThumbFormat.JPEG:
        bild = cv2.imdecode(np.frombuffer(th.data, np.uint8), cv2.IMREAD_COLOR)
    elif th.format == rawpy.ThumbFormat.BITMAP:
        bild = cv2.cvtColor(np.asarray(th.data), cv2.COLOR_RGB2BGR)
    else:
        return None
    if bild is None or min(bild.shape[:2]) < 120:
        return None
    return bild


def _schulter(x, y, grenze=0.97, ansatz=0.85, m_max=4.0):
    """Kamera-JPEGs brennen Lichter aus, die das RAW noch hat. Erreicht die Referenz `grenze`,
    wird ab `ansatz` nicht mehr nachgeahmt: eine weiche Schulter läuft bis zum hellsten RAW-Wert
    nach 1,0. Ihre Anfangssteigung ist auf `m_max` begrenzt — eine Schulter, die die volle
    Steigung mitnimmt, ist nach wenigen Prozent satt, und die obersten 10 % des RAW lagen dann in
    0,0003 Helligkeit (gemessen am Verlauf, test_kameralook). Ohne Ausbrennen: unverändert."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    oben = np.nonzero(y >= grenze)[0]
    xmax = max(1.0, float(x[-1]) + 1e-6)
    if len(oben) == 0 or oben[0] < 4:
        return np.concatenate([[0.0], x, [xmax]]), np.concatenate([[0.0], y, [1.0]]), None
    k = max(int(np.searchsorted(y, ansatz)), 3)
    k = min(k, int(oben[0]) - 2)
    x0, y0 = float(x[k]), float(y[k])
    steigung = max((y[k] - y[k - 3]) / max(x[k] - x[k - 3], 1e-9), 1e-3)
    xs = np.linspace(x0, xmax, 256)[1:]
    # rationale Schulter: nähert sich 1,0 und erreicht es bei xmax
    spanne, rest = xmax - x0, 1.0 - y0
    u = (xs - x0) / spanne
    m = min(steigung * spanne / max(rest, 1e-6), m_max)  # Anfangssteigung in Einheiten
    ys = y0 + rest * (m * u) / (1.0 + (m - 1.0) * u) if m > 1 else y0 + rest * u
    x_neu = np.concatenate([[0.0], x[:k + 1], xs])
    y_neu = np.concatenate([[0.0], y[:k + 1], ys])
    return x_neu, y_neu, x0


def _hell(b):
    return b @ _LUMA


def _saettigung(b, hell):
    return float(np.median(np.abs(b - hell[..., None]).max(axis=-1) / (hell + 1e-3)))


def angleichen(bgr, ref_bgr8=None, log=log_print, quantile=512):
    """`bgr` (uint16/uint8/float 0..1, sRGB) an `ref_bgr8` angleichen. Gibt (Bild wie Eingabetyp,
    Bericht). Ohne Referenz: Rückfall auf Median 0,40."""
    import cv2
    typ = bgr.dtype
    skala = 65535.0 if typ == np.uint16 else (255.0 if typ == np.uint8 else 1.0)
    f = bgr.astype(np.float32) / skala
    h, w = f.shape[:2]
    klein = cv2.resize(f, (max(1, w * 512 // max(h, w)), max(1, h * 512 // max(h, w))), interpolation=cv2.INTER_AREA)
    y_klein = _hell(klein)
    bericht = {}
    if ref_bgr8 is not None:
        r = cv2.resize(ref_bgr8, (klein.shape[1], klein.shape[0]), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        y_ref = _hell(r)
        q = np.linspace(0.0, 1.0, quantile)
        x = np.quantile(y_klein, q)
        y = np.quantile(y_ref, q)
        x = np.maximum.accumulate(x + np.arange(quantile) * 1e-7)      # streng steigend
        y = np.maximum.accumulate(y)
        x, y, schulter = _schulter(x, y)
        if schulter is not None:
            bericht["schulter_ab"] = round(schulter, 3)
        bericht["art"] = "Kamera-Vorschau"
        ziel_satt = _saettigung(r, y_ref)
    else:
        # 1 − e^(−a·x), weich bis Weiß. `a` wird gesucht, bis der Median des ERGEBNISSES 0,40 ist:
        # die Kurve wirkt je Kanal, und bei bunten Bildern lag der Median sonst bei 0,45.
        x = np.linspace(0.0, 1.0, 1024)
        unten, oben_a = 1e-3, 400.0
        for _ in range(40):
            a = (unten * oben_a) ** 0.5
            y = (1.0 - np.exp(-a * x)) / (1.0 - np.exp(-a))
            if float(np.median(_hell(np.interp(klein, x, y)))) < 0.40:
                unten = a
            else:
                oben_a = a
        bericht["art"] = "Rückfall: keine Kamera-Vorschau, Median auf 0,40 (weiche Filmkurve)"
        ziel_satt = None
        log("Kamera-Look: keine brauchbare Vorschau in der RAW-Datei — Belichtung auf Median 0,40")
    # Kurve je Kanal, wie Kamera-JPEGs sie anlegen: helle Farben laufen von selbst weich aus.
    # (Erste Fassung: Kurve nur auf die Helligkeit, Kanäle im Verhältnis skaliert — bei dunklen,
    # bunten Bildern lief dabei ein Kanal an den Anschlag: Sigma fp 52 %, Samsung 25 % der Pixel.)
    aus = np.interp(f.reshape(-1), x, y).astype(np.float32).reshape(f.shape)
    Y2 = _hell(aus)
    # Sättigung angleichen, Lichter geschützt (je heller, desto weniger Anhebung)
    if ziel_satt is not None:
        klein_aus = cv2.resize(aus, (klein.shape[1], klein.shape[0]), interpolation=cv2.INTER_AREA)
        ist = _saettigung(klein_aus, _hell(klein_aus))
        s = float(np.clip(ziel_satt / max(ist, 1e-4), 0.7, 1.4))
        if s > 1.0:
            s_px = 1.0 + (s - 1.0) * (1.0 - np.clip(Y2, 0, 1) ** 2)[..., None]
        else:
            s_px = s
        aus = Y2[..., None] + (aus - Y2[..., None]) * s_px
        bericht["saettigung"] = round(s, 3)
    # was danach noch über Weiß liegt: zum Weiß hin entsättigen statt abschneiden
    hoch = aus.max(axis=-1, keepdims=True)
    ueber = hoch > 1.0
    if ueber.any():
        Yc = np.clip(_hell(aus), 0, 1)[..., None]
        t = np.where(ueber, (1.0 - Yc) / np.maximum(hoch - Yc, 1e-6), 1.0)
        aus = Yc + (aus - Yc) * t
        bericht["entsaettigt_%"] = round(100.0 * float(ueber.mean()), 3)
    aus = np.clip(aus, 0.0, 1.0)                       # nach dem Entsättigen nur noch Rundung
    bericht["helligkeit_vorher"] = round(float(np.median(y_klein)), 4)
    # gemessen am Ergebnis, nicht an der Kurve (die wirkt je Kanal und weicht davon ab)
    bericht["helligkeit_nachher"] = round(float(np.median(_hell(
        cv2.resize(aus, (klein.shape[1], klein.shape[0]), interpolation=cv2.INTER_AREA)))), 4)
    log("Kamera-Look (%s): Median-Helligkeit %.3f → %.3f%s" % (
        bericht["art"], bericht["helligkeit_vorher"], bericht["helligkeit_nachher"],
        ", Sättigung ×%.2f" % bericht["saettigung"] if "saettigung" in bericht else ""))
    if typ == np.uint16:
        return (aus * 65535.0 + 0.5).astype(np.uint16), bericht
    if typ == np.uint8:
        return (aus * 255.0 + 0.5).astype(np.uint8), bericht
    return aus.astype(np.float32), bericht
