#!/usr/bin/env python3
"""
core/prozesse.py — der Arbeitsplatz: jedes Werkzeug auf ein offenes Bild, mit Maske und Verlauf.

So arbeitet man in PixInsight und Siril: ein Bild ist offen, ein Prozess nach dem anderen wird
darauf angewendet, jeder lässt sich durch eine Maske begrenzen und zurücknehmen, und die Kette
lässt sich auf ein anderes Bild übertragen. ForgePix hatte die Rechnungen, aber verstreut über
Automatik, Menüs und Kommandozeile. Hier steht jede einmal, mit:

* `vorbild` — wie der Prozess in PixInsight / Siril / RC-Astro / GraXpert heißt, damit man ihn
  wiederfindet. Das ist ein Wegweiser, keine Behauptung gleicher Ergebnisse.
* Parametern mit Spanne. Ein Wert außerhalb ist ein Fehler, nicht still beschnitten.
* `experimentell` für die eigenen KI-Modelle — die laufen nur nach ausdrücklicher Zusage.

Der Verlauf (`Arbeitsbild`) hält das Original und die Schritte. Zwischenstände werden nur für
die letzten Schritte im Speicher gehalten; ältere werden aus dem Original nachgerechnet — ein
24-MP-Farbbild in Float32 sind 288 MB, dreißig davon passen in keinen Rechner. Kein Qt.
"""
import json
import os
import tempfile

import numpy as np

try:
    from constants import log_print
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)

REZEPT_FORMAT = "forgepix-arbeitsplatz/1"


class Param:
    def __init__(self, name, label, standard, von=None, bis=None, wahl=None, ganz=False,
                 bild=False, text=False, pflicht=True):
        self.name, self.label, self.standard = name, label, standard
        self.von, self.bis, self.wahl, self.ganz = von, bis, wahl, ganz
        self.bild, self.text, self.pflicht = bild, text, pflicht

    @property
    def art(self):
        if self.bild:
            return "bild"
        if self.text:
            return "text"
        if self.wahl is not None:
            return "wahl"
        if isinstance(self.standard, bool):
            return "schalter"
        return "ganz" if self.ganz else "zahl"

    def pruefen(self, wert):
        if self.art == "bild":
            wert = (wert or "").strip() or None
            if wert is None and self.pflicht:
                raise ValueError("%s: bitte ein Bild wählen." % self.label)
            if wert is not None and not os.path.isfile(wert):
                raise ValueError("%s: Datei nicht gefunden: %s" % (self.label, wert))
            return wert
        if self.art == "text":
            wert = str(wert if wert is not None else "").strip()
            if not wert and self.pflicht:
                raise ValueError("%s darf nicht leer sein." % self.label)
            return wert
        if self.art == "wahl":
            if wert not in self.wahl:
                raise ValueError("%s: %r ist keine der Möglichkeiten %s" % (self.label, wert, self.wahl))
            return wert
        if self.art == "schalter":
            return bool(wert)
        if wert is None or (isinstance(wert, str) and not wert.strip()):
            if self.pflicht:
                raise ValueError("%s: bitte einen Wert angeben." % self.label)
            return None
        wert = int(wert) if self.ganz else float(wert)
        if (self.von is not None and wert < self.von) or (self.bis is not None and wert > self.bis):
            raise ValueError("%s: %g liegt außerhalb %g … %g" % (self.label, wert, self.von, self.bis))
        return wert


class Prozess:
    def __init__(self, id, name, gruppe, vorbild, beschreibung, params, fn, aendert_groesse=False,
                 experimentell=False, extern=None):
        self.id, self.name, self.gruppe = id, name, gruppe
        self.vorbild, self.beschreibung = vorbild, beschreibung
        self.params, self.fn = list(params), fn
        self.aendert_groesse, self.experimentell = aendert_groesse, experimentell
        self.extern = extern              # None oder Funktion: Pfad des Programms oder None

    def verfuegbar(self):
        """(ja/nein, Hinweis). Externe Programme werden gesucht, nie installiert."""
        if self.extern is None:
            return True, ""
        try:
            pfad = self.extern()
        except Exception as e:                       # Suche ist nur ein Hinweis
            return False, "Suche nach dem Programm scheiterte: %s" % e
        if not pfad:
            import zusatzprogramme
            url = zusatzprogramme.link(self.id) if self.id in {p[0] for p in zusatzprogramme.PROGRAMME} else None
            return False, ("Das Programm ist nicht installiert (oder in den Einstellungen nicht eingetragen)."
                           + (" Herunterladen: %s" % url if url else ""))
        return True, pfad

    def werte(self, gegeben=None):
        gegeben = dict(gegeben or {})
        unbekannt = set(gegeben) - {p.name for p in self.params}
        if unbekannt:
            raise ValueError("%s kennt diese Einstellungen nicht: %s" % (self.name, ", ".join(sorted(unbekannt))))
        return {p.name: p.pruefen(gegeben.get(p.name, p.standard)) for p in self.params}


# ------------------------------------------------------------------ kleine neue Prozesse ----
def _lum(b):
    return b.mean(axis=2) if b.ndim == 3 else b


def invertieren(b):
    return 1.0 - b


def neu_skalieren(b):
    lo, hi = float(np.min(b)), float(np.max(b))
    if hi <= lo:
        raise ValueError("Das Bild ist einfarbig — nichts zu skalieren.")
    return (b - lo) / (hi - lo)


def exponent(b, exponent=0.8):
    return np.power(np.clip(b, 0, None), exponent)


def saettigung(b, faktor=1.3):
    if b.ndim != 3:
        raise ValueError("Sättigung braucht ein Farbbild.")
    l = _lum(b)[..., None]
    return l + (b - l) * faktor


def unscharf_maskieren(b, sigma=2.0, menge=0.6):
    import cv2
    weich = cv2.GaussianBlur(b, (0, 0), sigma)
    return b + menge * (b - weich)


def falten(b, sigma=1.5):
    import cv2
    return cv2.GaussianBlur(b, (0, 0), sigma)


def morphologie(b, art="Erosion", groesse=3):
    import cv2
    if groesse % 2 == 0:
        raise ValueError("Größe muss ungerade sein, nicht %d" % groesse)
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (groesse, groesse))
    if art == "Erosion":
        return cv2.erode(b, kern)
    if art == "Dilatation":
        return cv2.dilate(b, kern)
    if art == "Öffnen":
        return cv2.morphologyEx(b, cv2.MORPH_OPEN, kern)
    return cv2.medianBlur(b, groesse) if groesse <= 5 else cv2.morphologyEx(b, cv2.MORPH_CLOSE, kern)


def zuschneiden(b, oben=0.0, unten=0.0, links=0.0, rechts=0.0):
    h, w = b.shape[:2]
    y0, y1 = int(round(h * oben / 100)), h - int(round(h * unten / 100))
    x0, x1 = int(round(w * links / 100)), w - int(round(w * rechts / 100))
    if y1 - y0 < 8 or x1 - x0 < 8:
        raise ValueError("Nach dem Zuschnitt bliebe fast nichts übrig.")
    return b[y0:y1, x0:x1].copy()


def drehen(b, winkel="90° rechts"):
    if winkel == "90° rechts":
        return np.ascontiguousarray(np.rot90(b, -1))
    if winkel == "90° links":
        return np.ascontiguousarray(np.rot90(b, 1))
    return np.ascontiguousarray(np.rot90(b, 2))


def spiegeln(b, richtung="waagerecht"):
    return np.ascontiguousarray(b[:, ::-1] if richtung == "waagerecht" else b[::-1])


def neu_abtasten(b, faktor=0.5):
    import cv2
    h, w = b.shape[:2]
    neu = (max(1, int(round(w * faktor))), max(1, int(round(h * faktor))))
    return cv2.resize(b, neu, interpolation=cv2.INTER_AREA if faktor < 1 else cv2.INTER_LANCZOS4)


def _starless(b, empfindlichkeit=5.0):
    import astro
    ohne, _ = astro.remove_stars(b, sensitivity=empfindlichkeit, log=lambda *a: None)
    return ohne


def _ki(modell):
    def lauf(b, staerke=0.5):
        import ai_restore
        return ai_restore.restore(b, modell, strength=staerke, allow_experimental=True,
                                  log=lambda *a: None)
    return lauf


def _astro(name, **fest):
    def lauf(bild, /, **werte):           # bild nur positional: GHS hat selbst ein „b“
        import astro
        return getattr(astro, name)(bild, **fest, **werte)
    return lauf


def _modul(modul, name, **fest):
    def lauf(bild, /, **werte):
        m = __import__(modul)
        ergebnis = getattr(m, name)(bild, **fest, **werte)
        return ergebnis[0] if isinstance(ergebnis, tuple) else ergebnis
    return lauf


# ------------------------------------------------------------------ mehrere Bilder -----------
def ausrichten_an(referenz, bild, log=log_print, toleranz=0.05):
    """`bild` über die Sterne auf `referenz` legen (Translation + Drehung, wie StarAlignment).

    Geprüft wird der Maßstab der gefundenen Abbildung: weicht er um mehr als `toleranz` von 1 ab,
    ist es eine andere Optik oder ein falscher Treffer — dann Fehler statt eines verzerrten
    Bildes (CLAUDE.md: Kameras mischen liefert sonst „ok“ mit Maßstab 0,58)."""
    import astro
    import cv2
    ref_g, img_g = _grau(referenz).astype(np.float32), _grau(bild).astype(np.float32)
    if ref_g.shape == img_g.shape and np.array_equal(ref_g, img_g):
        return bild
    m = astro._estimate_star_transform(ref_g, img_g)
    if m is None:
        m = astro._estimate_star_transform_robust(ref_g, img_g)
    if m is None or not np.isfinite(m).all():
        raise ValueError("Das zweite Bild ließ sich nicht über die Sterne ausrichten — "
                         "zeigt es dasselbe Sternfeld?")
    massstab = float(np.sqrt(abs(np.linalg.det(np.asarray(m, np.float64)[:, :2]))))
    if abs(massstab - 1.0) > toleranz:
        raise ValueError("Ausrichten ergab Maßstab %.3f statt 1 — andere Optik oder falscher "
                         "Treffer; nicht übernommen." % massstab)
    h, w = ref_g.shape
    kanaele = [bild[..., k] for k in range(bild.shape[2])] if bild.ndim == 3 else [bild]
    gelegt = [cv2.warpAffine(k.astype(np.float32), np.asarray(m, np.float32), (w, h),
                             flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                             borderValue=float("nan")) for k in kanaele]
    aus = np.dstack(gelegt) if bild.ndim == 3 else gelegt[0]
    leer = ~np.isfinite(aus if aus.ndim == 2 else aus[..., 0])
    if leer.any():
        log("Ausrichten: %.2f %% des Bildes ohne Daten (Rand) — dort mit dem Median gefüllt" % (100 * leer.mean()))
        aus = np.where(np.isfinite(aus), aus, np.nanmedian(aus))
    log("Ausrichten: Maßstab %.4f, Verschiebung %.1f / %.1f px" % (massstab, m[0][2], m[1][2]))
    return aus.astype(np.float32)


def _zweitbild(pfad, form, referenz=None, ausrichten=False, log=log_print):
    """Ein weiteres Bild laden. Ohne `ausrichten` muss es schon ausgerichtet und gleich groß
    sein — nichts wird still skaliert."""
    import astro
    b = np.asarray(astro._read_float(pfad), np.float32)
    if ausrichten:
        return ausrichten_an(referenz, b, log=log)
    if b.shape[:2] != tuple(form[:2]):
        raise ValueError("%s hat %d×%d Pixel, das offene Bild %d×%d. Erst ausrichten oder "
                         "gleich zuschneiden." % (os.path.basename(pfad), b.shape[0], b.shape[1],
                                                  form[0], form[1]))
    return b


def _grau(b):
    return b.mean(axis=2) if b.ndim == 3 else b


def pixelmath_formel(a, formel="A", B=None, C=None, ausrichten=True, log=log_print):
    """PixelMath über das offene Bild (A) und bis zu zwei weitere (B, C)."""
    import pixelmath
    bilder = {"A": a}
    for name, pfad in (("B", B), ("C", C)):
        if pfad:
            b = _zweitbild(pfad, a.shape, a, ausrichten, log)
            if b.ndim == 2 and a.ndim == 3:
                b = np.repeat(b[..., None], 3, axis=2)
            bilder[name] = b
    return pixelmath.evaluate(formel, bilder)


def lrgb(a, L=None, gewicht=1.0, ausrichten=True, log=log_print):
    """Helligkeit des Farbbilds durch eine (Mono-)Luminanz ersetzen, Farbverhältnisse bleiben.
    Gedacht nach dem Strecken, wie LRGBCombination in PixInsight üblich benutzt wird."""
    l_neu = _grau(_zweitbild(L, a.shape, a, ausrichten, log))
    l_alt = _grau(a)
    gueltig = np.abs(l_alt) > 1e-6
    faktor = np.where(gueltig, l_neu / np.where(gueltig, l_alt, 1.0), 1.0)
    neu = a * faktor[..., None]
    neu[~gueltig] = l_neu[~gueltig][:, None]          # ohne Farbe: grau mit neuer Helligkeit
    return a + float(gewicht) * (neu - a)


def kontinuum(a, breitband=None, faktor=1.0, auto=True, ausrichten=True, log=log_print):
    """Kontinuum abziehen: Schmalband − k·(Breitband − Hintergrund). Mit `auto` wird k so
    geschätzt, dass die Sterne verschwinden (Median des Verhältnisses über die hellsten 0,5 %
    des Breitbands) — und das gewählte k gemeldet."""
    b = _grau(_zweitbild(breitband, a.shape, a, ausrichten, log))
    b0 = b - float(np.median(b))
    if auto:
        hell = b0 > np.percentile(b0, 99.5)
        n = _grau(a) - float(np.median(_grau(a)))
        if hell.sum() < 10:
            raise ValueError("Zu wenige helle Sterne im Breitbandbild, um k zu schätzen — k von Hand setzen.")
        faktor = float(np.median(n[hell] / np.maximum(b0[hell], 1e-9)))
        log("Kontinuum: k = %.4f aus %d Sternpixeln geschätzt" % (faktor, int(hell.sum())))
    return a - faktor * (b0[..., None] if a.ndim == 3 else b0)


def kanal_ersetzen(a, kanal="Rot", quelle=None, ausrichten=True, log=log_print):
    """Einen Farbkanal durch ein (Mono-)Bild ersetzen — so entsteht RGB, HOO oder SHO Schritt
    für Schritt aus einzelnen Aufnahmen."""
    b = _grau(_zweitbild(quelle, a.shape, a, ausrichten, log))
    aus = a.copy()
    aus[..., {"Blau": 0, "Grün": 1, "Rot": 2}[kanal]] = b
    return aus


# ------------------------------------------------------------------ Kurven, MaskedStretch ---
def kurven_punkte(text):
    """'0,0; 0.3,0.2; 1,1' -> [(0,0), (0.3,0.2), (1,1)]; streng steigende x in 0..1."""
    punkte = []
    for teil in str(text).replace(chr(10), ";").split(";"):
        teil = teil.strip()
        if not teil:
            continue
        try:
            x, y = (float(z) for z in teil.split(","))
        except ValueError:
            raise ValueError("Kurvenpunkt %r: erwartet x,y" % teil) from None
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError("Kurvenpunkt %r liegt außerhalb 0…1" % teil)
        punkte.append((x, y))
    punkte.sort()
    if len(punkte) < 2 or any(b[0] <= a[0] for a, b in zip(punkte, punkte[1:])):
        raise ValueError("Eine Kurve braucht mindestens zwei Punkte mit verschiedenen x.")
    return punkte


def kurven(a, punkte="0,0; 1,1", kanal="Helligkeit"):
    """Tonwertkurve (PCHIP, überschwingt nicht). Werte außerhalb 0…1 bleiben unverändert —
    die Kurve ist nur dort definiert, und beschneiden wäre eine stille Änderung."""
    from scipy.interpolate import PchipInterpolator
    xs, ys = zip(*kurven_punkte(punkte))
    f = PchipInterpolator(xs, ys)

    def auf(v):
        v = np.asarray(v, np.float32)
        aus = v.copy()
        innen = (v >= 0) & (v <= 1)
        aus[innen] = f(v[innen])
        return aus
    if kanal == "RGB":
        return auf(a)
    if kanal in ("Rot", "Grün", "Blau"):
        aus = a.copy()
        i = {"Blau": 0, "Grün": 1, "Rot": 2}[kanal]
        aus[..., i] = auf(a[..., i])
        return aus
    l = _grau(a)
    l2 = auf(l)
    gueltig = np.abs(l) > 1e-6
    faktor = np.where(gueltig, l2 / np.where(gueltig, l, 1.0), 1.0)[..., None]
    aus = a * faktor
    aus[~gueltig] = a[~gueltig] + (l2 - l)[~gueltig][:, None]
    return aus


def _mtf(x, m):
    return (m - 1.0) * x / ((2.0 * m - 1.0) * x - m)


def masked_stretch(a, ziel=0.125, durchgaenge=30, log=log_print):
    """In vielen kleinen Schritten strecken, jeder durch das Bild selbst maskiert: helle
    Stellen (Sterne, Kerne) bekommen kaum etwas ab, der dunkle Himmel fast alles. So bleiben
    Sterne klein. Vorbild: PixInsight MaskedStretch (nach dessen Beschreibung nachgebaut).

    Vorher wird das unterste 0,1 % der Helligkeit zum Schwarzpunkt und das Bild auf 0…1
    gebracht; was darunter liegt, wird 0 — der Anteil wird gemeldet."""
    l = _grau(a)
    lo = float(np.percentile(l, 0.1))
    spanne = float(np.max(a) - lo)
    if spanne <= 0:
        raise ValueError("Das Bild ist einfarbig — nichts zu strecken.")
    cur = (a - lo) / spanne
    unter = float(np.mean(cur < 0))
    if unter:
        log("MaskedStretch: %.2f %% der Werte lagen unter dem Schwarzpunkt und werden 0" % (100 * unter))
    cur = np.clip(cur, 0, 1).astype(np.float32)
    for i in range(int(durchgaenge)):
        x = float(np.median(_grau(cur)))
        y = x + (ziel - x) / (durchgaenge - i)
        if x <= 0 or y <= x:
            break
        m = x * (y - 1.0) / (2.0 * x * y - x - y)
        gestreckt = _mtf(cur, m)
        maske = np.clip(_grau(cur), 0, 1)[..., None]
        cur = cur * maske + gestreckt * (1.0 - maske)
    log("MaskedStretch: Hintergrund-Median %.4f (Ziel %.4f)" % (float(np.median(_grau(cur))), ziel))
    return cur


# ------------------------------------------------------------------ externe Programme -------
def _graxpert_finden():
    import graxpert_engine
    return graxpert_engine.find_cli()


def _cosmic_finden():
    import cosmicclarity_engine
    return cosmicclarity_engine.find_cli()


def graxpert(a, art="Hintergrund", glaettung=0.2, log=log_print):
    """GraXpert selbst rechnen lassen (über FITS, verlustfrei linear). GraXpert nimmt nur Werte
    ab 0 — negative werden dafür auf 0 gesetzt, und das wird gemeldet."""
    import graxpert_engine
    negativ = float(np.mean(a < 0))
    if negativ:
        log("GraXpert: %.2f %% negative Werte werden für GraXpert auf 0 gesetzt" % (100 * negativ))
    befehl = "background-extraction" if art == "Hintergrund" else "denoising"
    with tempfile.TemporaryDirectory() as d:
        return graxpert_engine.run(a, d, command=befehl, smoothing=glaettung, log=log)


def cosmic_schaerfen(a, art="Nur Nebel", log=log_print):
    import cosmicclarity_engine
    modus = {"Nur Nebel": "Non-Stellar Only", "Nur Sterne": "Stellar Only", "Beides": "Both"}[art]
    return cosmicclarity_engine.sharpen(np.clip(a, 0, 1), mode=modus, log=log)


# ------------------------------------------------------------------ Runde 3: ACDNR, HDR --------
def _mad(x):
    x = np.asarray(x, np.float32)
    return float(np.median(np.abs(x - np.median(x))) * 1.4826)


def acdnr(a, staerke_l=0.5, staerke_c=1.0, radius=2.0, schutz=0.7):
    """Helligkeit und Farbe getrennt entrauschen (Vorbild: PixInsight ACDNR, nach dessen
    Beschreibung): Farbrauschen kräftig weichzeichnen, Helligkeit kantenerhaltend glätten, helle
    Stellen (Sterne, Kerne) je nach `schutz` schonen."""
    import cv2
    L = _grau(a).astype(np.float32)
    C = a - L[..., None]
    rauschen = max(_mad(L), 1e-6)
    Lf = cv2.bilateralFilter(L, d=0, sigmaColor=3.0 * rauschen, sigmaSpace=float(radius))
    Cf = cv2.GaussianBlur(C, (0, 0), 2.0 * float(radius))
    lo, hi = np.percentile(L, [1.0, 99.5])
    hell = np.clip((L - lo) / max(float(hi - lo), 1e-9), 0, 1)
    w = 1.0 - float(schutz) * hell
    L2 = L + float(staerke_l) * w * (Lf - L)
    C2 = C + float(staerke_c) * w[..., None] * (Cf - C)
    return L2[..., None] + C2


def _helligkeit_ersetzen(a, L_alt, L_neu):
    """Farbbild mit neuer Helligkeit, Farbverhältnisse bleiben."""
    gueltig = np.abs(L_alt) > 1e-6
    faktor = np.where(gueltig, L_neu / np.where(gueltig, L_alt, 1.0), 1.0)[..., None]
    aus = a * faktor
    aus[~gueltig] = a[~gueltig] + (L_neu - L_alt)[~gueltig][:, None]
    return aus


def hdr_multiskala(a, ebenen=6, staerke=0.7):
    """Dynamik zusammendrücken über Wavelet-Ebenen (Vorbild: PixInsight HDRMultiscaleTransform,
    nach Beschreibung): die groben Ebenen — der helle Kern einer Galaxie, eines Nebels — werden
    flacher, die feinen Strukturen darin bleiben. Gedacht nach dem Strecken."""
    import wavelet
    L = _grau(a).astype(np.float32)
    details, rest = wavelet.atrous(L, levels=int(ebenen))
    mittel = float(np.mean(rest))
    flacher = mittel + (rest - mittel) * (1.0 - float(staerke))
    L2 = flacher + np.sum(details, axis=0)
    return _helligkeit_ersetzen(a, L, L2.astype(np.float32))


def _poisson_neumann(div):
    """∇²I = div mit Neumann-Rand über die Kosinus-Transformation lösen."""
    from scipy.fft import dctn, idctn
    h, w = div.shape
    d = dctn(div, type=2, norm="ortho")
    ky = 2.0 * np.cos(np.pi * np.arange(h) / h) - 2.0
    kx = 2.0 * np.cos(np.pi * np.arange(w) / w) - 2.0
    nenner = ky[:, None] + kx[None, :]
    nenner[0, 0] = 1.0
    d = d / nenner
    d[0, 0] = 0.0
    return idctn(d, type=2, norm="ortho")


def gradienten_hdr(a, staerke=0.85, schwelle=0.1):
    """Kontrast im Gradientenbereich zusammendrücken (Vorbild: PixInsight GradientsHDRCompression;
    Verfahren nach Fattal u. a. 2002, einskalig): große Helligkeitssprünge werden gedämpft,
    kleine bleiben, das Bild wird aus den Gradienten neu zusammengesetzt. staerke = 1 lässt das
    Bild unverändert (bis auf die Helligkeitsspanne)."""
    L = _grau(a).astype(np.float64)
    lo = float(L.min())
    H = np.log(L - lo + 1e-4)
    gx = np.zeros_like(H); gy = np.zeros_like(H)
    gx[:, :-1] = H[:, 1:] - H[:, :-1]
    gy[:-1, :] = H[1:, :] - H[:-1, :]
    betrag = np.hypot(gx, gy)
    alpha = max(float(schwelle) * float(betrag.mean()), 1e-12)
    phi = np.where(betrag > 0, (np.maximum(betrag, 1e-12) / alpha) ** (float(staerke) - 1.0), 1.0)
    Gx, Gy = gx * phi, gy * phi
    div = np.zeros_like(H)
    div[:, 0] = Gx[:, 0]; div[:, 1:] = Gx[:, 1:] - Gx[:, :-1]
    div[0, :] += Gy[0, :]; div[1:, :] += Gy[1:, :] - Gy[:-1, :]
    I = _poisson_neumann(div)
    # Spanne am dunklen Ende (0,1 %) und am HELLSTEN Wert festmachen — mit 99,9 % liefen helle
    # Sterne am echten Stapel bis 1,73 hinaus (gemessen 23.11.2026)
    q_alt = np.percentile(H, [0.1, 100.0]); q_neu = np.percentile(I, [0.1, 100.0])
    I = q_alt[0] + (I - q_neu[0]) * (q_alt[1] - q_alt[0]) / max(q_neu[1] - q_neu[0], 1e-12)
    L2 = np.exp(I) + lo - 1e-4
    return _helligkeit_ersetzen(a, L.astype(np.float32), L2.astype(np.float32))


def _starnet_finden():
    import tools_engine
    return tools_engine.find_starnet()


def starnet(a, log=log_print):
    """StarNet++ selbst rechnen lassen. StarNet nimmt nur 16-bit-TIFF eines GESTRECKTEN Bildes —
    darum hier nur nach dem Strecken; Werte außerhalb 0…1 werden dafür begrenzt (gemeldet)."""
    import tifffile
    import tools_engine
    draussen = float(np.mean((a < 0) | (a > 1)))
    if draussen:
        log("StarNet: %.2f %% der Werte außerhalb 0…1 werden für StarNet begrenzt" % (100 * draussen))
    with tempfile.TemporaryDirectory() as d:
        ein = os.path.join(d, "starnet_in.tif")
        tifffile.imwrite(ein, (np.clip(a[..., ::-1], 0, 1) * 65535).astype(np.uint16), photometric="rgb")
        aus = tools_engine.run_starnet(ein, os.path.join(d, "starnet_out.tif"), log=log)
        b = tifffile.imread(aus).astype(np.float32)
    b = b / (65535.0 if b.max() > 1.5 else 1.0)
    return b[..., ::-1] if b.ndim == 3 else np.repeat(b[..., None], 3, axis=2)


# ------------------------------------------------------------------ Farbkalibrierung -----------
KATALOG_PFAD = None          # None = der lokale Gaia-Katalog des Nutzers; Tests setzen einen eigenen


def farbkalibrierung(a, ra=None, dec=None, skala=None, log=log_print):
    """Photometrische Farbkalibrierung gegen Gaia-Farben (wie PixInsights PCC, G2V-Weißpunkt) —
    ganz ohne Siril: eigener Plate-Solve gegen den lokalen Gaia-Katalog, dann `pcc_echt`.

    Braucht RA/Dec (Grad) und Bildmaßstab (″/px) als Hinweis — bei ASIAIR-, N.I.N.A.- und
    Seestar-FITS füllt der Arbeitsplatz sie aus dem Kopf vor. Kein SPCC: ohne hinterlegte
    Sensor- und Filterkurven ist es eine empirische Kalibrierung (siehe pcc_echt)."""
    import gaia_lokal
    import pcc_echt
    import photometric
    pfad = KATALOG_PFAD or gaia_lokal.standard_pfad()
    if not os.path.exists(pfad):
        raise ValueError("Kein lokaler Sternkatalog — Menü „Sternkatalog verwalten …“, Feld laden.")
    kat = gaia_lokal.Katalog.laden(pfad, log=log)
    wcs = None
    if ra is not None and dec is not None and skala is not None:
        wcs = photometric._solve_wcs_nativ(a, {"ra": float(ra), "dec": float(dec),
                                               "pixelscale_arcsec": float(skala)}, kat, log)
    if wcs is None:
        import astap
        if not astap.finden():
            raise ValueError("Die Himmelsposition ließ sich nicht bestimmen. RA/Dec/Maßstab eintragen "
                             "— oder ASTAP installieren, dann geht es auch blind: %s" % astap.DOWNLOAD)
        hinweise = ({"ra": float(ra), "dec": float(dec), "pixelscale_arcsec": skala}
                    if ra is not None and dec is not None else None)
        try:
            wcs = astap.loesen(a, hinweise, log=log)
        except astap.AstapFehler as e:
            raise ValueError(str(e)) from e
    h0, w0 = a.shape[:2]
    m_ra, m_dec = (float(v) for v in wcs.pixel_to_world_values(w0 / 2.0, h0 / 2.0))
    ok, n, satz = gaia_lokal.abdeckung(kat, m_ra, m_dec, 0.6)
    if not ok:
        raise ValueError("Der lokale Katalog deckt dieses Feld nicht ab (%s)." % satz)
    h, w = a.shape[:2]
    mitte = wcs.pixel_to_world_values(w / 2.0, h / 2.0)
    treffer = kat.kegelsuche(float(mitte[0]), float(mitte[1]), 0.6, max_mag=16.0)
    x, y = wcs.world_to_pixel_values(np.asarray(treffer["ra"]), np.asarray(treffer["dec"]))
    farbe = np.asarray(treffer["bp_rp"], float)
    drin = (x > 20) & (x < w - 20) & (y > 20) & (y < h - 20) & np.isfinite(farbe)
    aus, bericht = pcc_echt.farbkalibrieren(a, list(zip(x[drin], y[drin])), farbe[drin], log=log)
    log("Farbkalibrierung: %d Sterne, Weißpunkt BP-RP %.2f (sonnenähnlich), Streuung %.3f/%.3f"
        % (bericht["sterne"], bericht["bezugsfarbe"], bericht["streuung_b"], bericht["streuung_r"]))
    return aus


_STILL = {"log": lambda *a: None}

PROZESSE = [
    # --- Hintergrund und Farbe ----------------------------------------------------------
    Prozess("hintergrund", "Hintergrund ausgleichen", "Hintergrund und Farbe",
            "PixInsight: DynamicBackgroundExtraction/ABE · Siril: Background Extraction · GraXpert (klassisch)",
            "Verlauf aus Lichtverschmutzung und Vignette über Stützstellen (RBF) schätzen und entfernen.",
            [Param("strength", "Stärke", 0.12, 0.0, 1.0), Param("grid", "Stützstellen je Seite", 12, 4, 40, ganz=True),
             Param("korrektur", "Art", "sub", wahl=["sub", "div"])],
            _astro("background_extract", **_STILL)),
    Prozess("farbkalibrierung", "Farbkalibrierung (Gaia-Farben)", "Hintergrund und Farbe",
            "PixInsight: PhotometricColorCalibration · Siril: PCC (ohne Siril, eigener Plate-Solve)",
            "Kanäle so skalieren, dass ein sonnenähnlicher Stern weiß ist — gemessen an den "
            "bekannten Gaia-Farben der Sterne im Bild. Braucht den lokalen Sternkatalog; ohne "
            "RA/Dec löst ASTAP blind, falls installiert.",
            [Param("ra", "RA der Bildmitte (°)", None, 0.0, 360.0, pflicht=False),
             Param("dec", "Dec der Bildmitte (°)", None, -90.0, 90.0, pflicht=False),
             Param("skala", "Bildmaßstab (″/px)", None, 0.05, 60.0, pflicht=False)], farbkalibrierung),
    Prozess("hintergrund_neutral", "Hintergrund neutralisieren", "Hintergrund und Farbe",
            "PixInsight: BackgroundNeutralization · Siril: Background Neutralization",
            "Himmelshintergrund je Kanal auf denselben Wert ziehen.",
            [Param("pct", "Perzentil des Himmels", 25.0, 1.0, 60.0)], _astro("neutralize_background")),
    Prozess("farbe", "Farbe abgleichen", "Hintergrund und Farbe",
            "PixInsight: ColorCalibration · Siril: Color Calibration",
            "Hintergrund neutral, helle Sterne im Mittel weiß. Keine photometrische Kalibrierung.",
            [Param("strength", "Stärke", 1.0, 0.0, 1.0)], _astro("color_balance")),
    Prozess("scnr", "Grünstich entfernen", "Hintergrund und Farbe",
            "PixInsight: SCNR · Siril: Remove Green Noise",
            "Grün auf den Mittelwert von Rot und Blau begrenzen (Average Neutral).",
            [Param("amount", "Stärke", 1.0, 0.0, 1.0)], _astro("remove_green_cast")),
    Prozess("saettigung", "Sättigung", "Hintergrund und Farbe",
            "PixInsight: ColorSaturation · Siril: Saturation",
            "Farbabstand zur Helligkeit vergrößern (1 = unverändert).",
            [Param("faktor", "Faktor", 1.3, 0.0, 4.0)], saettigung),
    # --- Strecken -------------------------------------------------------------------------
    Prozess("mtf", "Strecken (MTF / Auto-STF)", "Strecken",
            "PixInsight: HistogramTransformation + AutoSTF · Siril: Histogram Transformation / Autostretch",
            "Schwarzpunkt aus Median und MAD, Mittelton so, dass der Himmel auf den Zielwert kommt.",
            [Param("target_bg", "Ziel-Hintergrund", 0.25, 0.05, 0.6), Param("shadow", "Schwarzpunkt (MAD)", -2.8, -6.0, 0.0)],
            _astro("mtf_stretch")),
    Prozess("ghs", "Strecken (GHS)", "Strecken",
            "Siril: Generalised Hyperbolic Stretch · PixInsight: GHS-Skript",
            "Schwaches Signal kräftig anheben, helle Kerne schonen.",
            [Param("D", "Stärke D", 2.5, 0.0, 10.0), Param("b", "Form b", -0.5, -5.0, 15.0),
             Param("SP", "Symmetriepunkt", 0.18, 0.0, 1.0)], _astro("ghs_stretch")),
    Prozess("asinh", "Strecken (asinh)", "Strecken",
            "PixInsight: ArcsinhStretch · Siril: Asinh Transformation",
            "Farberhaltende asinh-Kurve.",
            [Param("strength", "Stärke", 6.0, 0.5, 40.0)], lambda b, strength: _astro("autostretch")(b, strength=strength).astype(np.float32)),
    Prozess("ddp", "Strecken (DDP)", "Strecken", "Siril/Okano: Digital Development Processing",
            "Klassische Filmkurve mit lokalem Kontrast.", [Param("staerke", "Stärke", 1.0, 0.1, 4.0)], _astro("ddp")),
    Prozess("exponent", "Exponent", "Strecken", "PixInsight: ExponentialTransformation (Potenz)",
            "Jedes Pixel hoch Exponent (unter 1 hellt auf).", [Param("exponent", "Exponent", 0.8, 0.1, 5.0)], exponent),
    Prozess("lokaler_kontrast", "Lokaler Kontrast", "Strecken",
            "PixInsight: LocalHistogramEqualization · Siril: CLAHE",
            "Kontrast je Bildbereich (nur Helligkeit).",
            [Param("staerke", "Stärke", 1.5, 0.1, 6.0), Param("kacheln", "Kacheln", 8, 2, 32, ganz=True)],
            _astro("local_contrast")),
    Prozess("invertieren", "Invertieren", "Strecken", "PixInsight: Invert · Siril: Negative",
            "1 − Wert.", [], invertieren),
    Prozess("skalieren", "Auf 0…1 skalieren", "Strecken", "PixInsight: Rescale",
            "Kleinster Wert → 0, größter → 1.", [], neu_skalieren),
    # --- Rauschen und Schärfe ---------------------------------------------------------------
    Prozess("tv", "Entrauschen (TV)", "Rauschen und Schärfe",
            "PixInsight: TGVDenoise · Siril: Denoise", "Kantenerhaltend glätten.",
            [Param("staerke", "Stärke", 0.3, 0.0, 2.0), Param("iterationen", "Durchgänge", 5, 1, 50, ganz=True)],
            _astro("tv_denoise")),
    Prozess("wavelet_nr", "Entrauschen (Wavelet)", "Rauschen und Schärfe",
            "PixInsight: MultiscaleLinearTransform (Rauschen) · Siril: Wavelets",
            "Rauschen je Skala mit k·σ dämpfen.",
            [Param("strength", "Stärke", 1.0, 0.0, 4.0), Param("levels", "Skalen", 4, 1, 8, ganz=True)],
            _modul("wavelet", "wavelet_denoise")),
    Prozess("wavelet_schaerfen", "Schärfen (Wavelet)", "Rauschen und Schärfe",
            "PixInsight: ATrousWaveletTransform · Siril/RegiStax: Wavelets",
            "Feine Skalen verstärken.", [Param("denoise", "Rauschschutz", 0.0, 0.0, 2.0)],
            _modul("wavelet", "wavelet_sharpen")),
    Prozess("dekonvolution", "Dekonvolution", "Rauschen und Schärfe",
            "PixInsight: Deconvolution · Siril: Deconvolution · RC-Astro BlurXTerminator (klassischer Ersatz, nicht gleichwertig)",
            "Richardson-Lucy mit PSF aus den Sternen, Sternschutz und Entringen.",
            [Param("iterations", "Durchgänge", 15, 1, 200, ganz=True), Param("regularize", "Glättung", 0.0, 0.0, 1.0),
             Param("tiled_psf", "PSF je Bildbereich", False)], _astro("deconvolve", **_STILL)),
    Prozess("unscharf", "Unscharf maskieren", "Rauschen und Schärfe", "PixInsight: UnsharpMask · Siril: Unsharp Mask",
            "Bild minus weichgezeichnete Kopie dazugeben.",
            [Param("sigma", "Radius", 2.0, 0.3, 50.0), Param("menge", "Menge", 0.6, 0.0, 5.0)], unscharf_maskieren),
    Prozess("falten", "Weichzeichnen", "Rauschen und Schärfe", "PixInsight: Convolution · Siril: Gaussian Blur",
            "Gauß-Faltung.", [Param("sigma", "Radius", 1.5, 0.3, 50.0)], falten),
    Prozess("streifen", "Periodische Streifen entfernen", "Rauschen und Schärfe",
            "PixInsight: FFT-Werkzeuge · Siril: (Fourier)", "Fourier-Kerbfilter gegen regelmäßige Muster.",
            [Param("staerke", "Stärke", 1.0, 0.0, 1.0)], _modul("klassiker", "periodisch_entfernen", **_STILL)),
    Prozess("banding", "Banding entfernen", "Rauschen und Schärfe",
            "PixInsight: CanonBandingReduction · Siril: Banding Reduction", "Zeilen- oder Spaltenmuster.",
            [Param("strength", "Stärke", 1.0, 0.0, 2.0), Param("vertical", "Spalten statt Zeilen", False)],
            _astro("fix_banding")),
    Prozess("kosmetik", "Hotpixel entfernen", "Rauschen und Schärfe",
            "PixInsight: CosmeticCorrection · Siril: Cosmetic Correction", "Isolierte Ausreißer ersetzen.",
            [Param("strength", "Empfindlichkeit (σ)", 3.0, 1.0, 10.0)], _astro("cosmetic_correct")),
    # --- Sterne -----------------------------------------------------------------------------
    Prozess("sterne_kleiner", "Sterne verkleinern", "Sterne",
            "PixInsight: StarReduction-Skripte · RC-Astro StarXTerminator/BlurX (Sternanteil) · Siril",
            "Sterne verkleinern, Nebel schonen.",
            [Param("strength", "Stärke", 0.5, 0.0, 1.0), Param("size", "Größe", 5, 1, 25, ganz=True)],
            _astro("reduce_stars")),
    Prozess("sterne_entfernen", "Sterne entfernen (klassisch)", "Sterne",
            "RC-Astro StarXTerminator · StarNet (klassischer Ersatz, große Halos bleiben teils)",
            "Sternloses Nebelbild.", [Param("empfindlichkeit", "Empfindlichkeit", 5.0, 1.0, 20.0)], _starless),
    Prozess("synthstar", "Sternformen erneuern", "Sterne", "Siril: Synthstar",
            "Sterne durch runde Moffat-Profile ersetzen (Ansicht — keine Messdaten mehr).",
            [Param("groesse", "Größe", 1.0, 0.3, 3.0)], _astro("synthstar", **_STILL)),
    Prozess("unclip", "Ausgebrannte Sternkerne färben", "Sterne", "Siril: Unclip Stars",
            "Farbe aus den intakten Flanken zurückholen.", [Param("thresh", "Sättigungsgrenze", 0.92, 0.5, 1.0)],
            _astro("unclip_stars", **_STILL)),
    Prozess("morphologie", "Morphologie", "Sterne", "PixInsight: MorphologicalTransformation",
            "Erosion, Dilatation, Öffnen oder Median.",
            [Param("art", "Art", "Erosion", wahl=["Erosion", "Dilatation", "Öffnen", "Median"]),
             Param("groesse", "Größe (ungerade)", 3, 3, 15, ganz=True)], morphologie),
    # --- Geometrie --------------------------------------------------------------------------
    Prozess("zuschneiden", "Zuschneiden", "Geometrie", "PixInsight: DynamicCrop / Crop · Siril: Crop",
            "Ränder in Prozent abschneiden.",
            [Param(n, l, 0.0, 0.0, 45.0) for n, l in (("oben", "oben %"), ("unten", "unten %"),
                                                      ("links", "links %"), ("rechts", "rechts %"))],
            zuschneiden, aendert_groesse=True),
    Prozess("drehen", "Drehen", "Geometrie", "PixInsight: FastRotation · Siril: Rotate",
            "Um 90° oder 180°.", [Param("winkel", "Winkel", "90° rechts", wahl=["90° rechts", "90° links", "180°"])],
            drehen, aendert_groesse=True),
    Prozess("spiegeln", "Spiegeln", "Geometrie", "PixInsight: FastRotation (Mirror) · Siril: Mirror",
            "Waagerecht oder senkrecht.", [Param("richtung", "Richtung", "waagerecht", wahl=["waagerecht", "senkrecht"])],
            spiegeln, aendert_groesse=True),
    Prozess("abtasten", "Größe ändern", "Geometrie", "PixInsight: Resample · Siril: Resample",
            "Mit Faktor vergrößern oder verkleinern.", [Param("faktor", "Faktor", 0.5, 0.1, 4.0)],
            neu_abtasten, aendert_groesse=True),
    Prozess("binning", "Binning", "Geometrie", "PixInsight: IntegerResample · Siril: Binning",
            "Blöcke mitteln: weniger Pixel, mehr Signal je Pixel.", [Param("factor", "Faktor", 2, 2, 4, ganz=True)],
            _astro("bin_image"), aendert_groesse=True),
    # --- Komet ------------------------------------------------------------------------------
    Prozess("larson", "Kometenstrukturen (Larson-Sekanina)", "Komet", "PixInsight: LarsonSekanina",
            "Rotationsgradient — nur zum Ansehen.", [Param("winkel", "Winkel (°)", 15.0, 1.0, 90.0)],
            _modul("klassiker", "larson_sekanina")),
    # --- mehrere Bilder ---------------------------------------------------------------------
    Prozess("pixelmath", "PixelMath", "Mehrere Bilder", "PixInsight: PixelMath · Siril: PixelMath",
            "Formel über das offene Bild A und bis zu zwei weitere (B, C). Beispiele: 0.8*A+0.2*B, "
            "rgb(B, C, A), max(A, B).",
            [Param("formel", "Formel", "A", text=True), Param("B", "Bild B", None, bild=True, pflicht=False),
             Param("C", "Bild C", None, bild=True, pflicht=False), Param("ausrichten", "über die Sterne ausrichten", True)], pixelmath_formel),
    Prozess("lrgb", "Luminanz einsetzen (LRGB)", "Mehrere Bilder",
            "PixInsight: LRGBCombination · Siril: RGB Composition mit L",
            "Helligkeit durch eine Mono-Luminanz ersetzen, Farbe bleibt. Nach dem Strecken anwenden.",
            [Param("L", "Luminanz-Bild", None, bild=True), Param("gewicht", "Gewicht", 1.0, 0.0, 1.0), Param("ausrichten", "über die Sterne ausrichten", True)], lrgb),
    Prozess("kontinuum", "Kontinuum abziehen", "Mehrere Bilder",
            "SetiAstro: Continuum Subtraction · PixInsight: PixelMath-Rezept",
            "Schmalband − k·Breitband: Sterne und Kontinuum raus, reines Linienlicht bleibt.",
            [Param("breitband", "Breitband-Bild (z. B. Rot)", None, bild=True),
             Param("auto", "k aus den Sternen schätzen", True), Param("faktor", "k (von Hand)", 1.0, 0.0, 5.0), Param("ausrichten", "über die Sterne ausrichten", True)],
            kontinuum),
    Prozess("kanal", "Kanal ersetzen", "Mehrere Bilder",
            "PixInsight: ChannelCombination · Siril: RGB Composition",
            "Einen Farbkanal durch eine Mono-Aufnahme ersetzen (RGB, HOO, SHO Schritt für Schritt).",
            [Param("kanal", "Kanal", "Rot", wahl=["Rot", "Grün", "Blau"]), Param("quelle", "Mono-Bild", None, bild=True), Param("ausrichten", "über die Sterne ausrichten", True)],
            kanal_ersetzen),
    # --- Kurven und MaskedStretch ----------------------------------------------------------
    Prozess("kurven", "Kurven", "Strecken", "PixInsight: CurvesTransformation · Siril: Curves",
            "Tonwertkurve über Punkte (PCHIP). Werte außerhalb 0…1 bleiben unverändert.",
            [Param("punkte", "Punkte x,y; x,y", "0,0; 0.25,0.35; 1,1", text=True),
             Param("kanal", "Kanal", "Helligkeit", wahl=["Helligkeit", "RGB", "Rot", "Grün", "Blau"])], kurven),
    Prozess("masked_stretch", "Strecken (MaskedStretch)", "Strecken", "PixInsight: MaskedStretch",
            "Viele kleine Schritte, jeder durch das Bild selbst maskiert — Sterne bleiben klein.",
            [Param("ziel", "Ziel-Hintergrund", 0.125, 0.02, 0.5), Param("durchgaenge", "Durchgänge", 30, 2, 200, ganz=True)],
            masked_stretch),
    # --- externe Programme -----------------------------------------------------------------
    Prozess("graxpert", "GraXpert", "Externe Programme", "GraXpert (das Programm selbst, KI)",
            "Hintergrund oder Entrauschen mit GraXperts eigener KI. GraXpert muss installiert sein.",
            [Param("art", "Aufgabe", "Hintergrund", wahl=["Hintergrund", "Entrauschen"]),
             Param("glaettung", "Glättung (Hintergrund)", 0.2, 0.0, 1.0)], graxpert, extern=_graxpert_finden),
    Prozess("cosmic", "Cosmic Clarity: Schärfen", "Externe Programme", "SetiAstro Cosmic Clarity (das Programm selbst, KI)",
            "KI-Schärfung. Cosmic Clarity muss installiert sein.",
            [Param("art", "Was schärfen", "Nur Nebel", wahl=["Nur Nebel", "Nur Sterne", "Beides"])],
            cosmic_schaerfen, extern=_cosmic_finden),
    Prozess("acdnr", "Entrauschen (Helligkeit/Farbe getrennt)", "Rauschen und Schärfe",
            "PixInsight: ACDNR · Siril: Denoise (Chroma)",
            "Farbrauschen kräftig, Helligkeit kantenerhaltend glätten; helle Stellen werden geschont.",
            [Param("staerke_l", "Stärke Helligkeit", 0.5, 0.0, 1.0), Param("staerke_c", "Stärke Farbe", 1.0, 0.0, 1.0),
             Param("radius", "Radius", 2.0, 0.5, 10.0), Param("schutz", "Schutz heller Stellen", 0.7, 0.0, 1.0)], acdnr),
    Prozess("hdrmt", "Dynamik zusammendrücken (Wavelet)", "Strecken", "PixInsight: HDRMultiscaleTransform",
            "Helle Kerne flacher, die Strukturen darin bleiben sichtbar.",
            [Param("ebenen", "Ebenen", 6, 2, 9, ganz=True), Param("staerke", "Stärke", 0.7, 0.0, 1.0)], hdr_multiskala),
    Prozess("gradienten_hdr", "Dynamik zusammendrücken (Gradienten)", "Strecken",
            "PixInsight: GradientsHDRCompression (Fattal 2002, einskalig)",
            "Große Helligkeitssprünge dämpfen, kleine behalten; 1 = unverändert.",
            [Param("staerke", "Stärke (1 = aus)", 0.85, 0.3, 1.0), Param("schwelle", "Schwelle", 0.1, 0.01, 1.0)],
            gradienten_hdr),
    Prozess("starnet", "StarNet++", "Externe Programme", "StarNet++ (das Programm selbst, KI)",
            "Sterne entfernen mit StarNets eigener KI — nur am gestreckten Bild. StarNet muss installiert sein.",
            [], starnet, extern=_starnet_finden),
    # --- eigene KI (experimentell) ----------------------------------------------------------
    Prozess("ki_entrauschen", "KI: Entrauschen", "Eigene KI (experimentell)",
            "RC-Astro NoiseXTerminator · GraXpert Denoise · Cosmic Clarity Denoise (eigenes Modell, nicht gleichwertig)",
            "Gemessen: −26 % Rauschen bei Stärke 0,5, Sternfluss < 0,6 % verändert.",
            [Param("staerke", "Stärke", 0.5, 0.0, 1.0)], _ki("forgepix-denoise-mono-v2"), experimentell=True),
    Prozess("ki_schaerfen", "KI: Schärfen", "Eigene KI (experimentell)",
            "RC-Astro BlurXTerminator (eigenes Modell, nicht gleichwertig)",
            "Laut Messung schlechter als die klassische Dekonvolution.",
            [Param("staerke", "Stärke", 0.5, 0.0, 1.0)], _ki("forgepix-deblur-mono-v2"), experimentell=True),
    Prozess("ki_sterne", "KI: Sterne entfernen", "Eigene KI (experimentell)",
            "RC-Astro StarXTerminator · StarNet (eigenes Modell, nicht gleichwertig)",
            "Laut Messung schlechter als der klassische Weg.",
            [Param("staerke", "Stärke", 1.0, 0.0, 1.0)], _ki("forgepix-starless-mono-v2"), experimentell=True),
    Prozess("ki_hintergrund", "KI: Hintergrund", "Eigene KI (experimentell)",
            "GraXpert AI Background (eigenes Modell, nicht gleichwertig)",
            "Laut Messung schlechter als der klassische Weg.",
            [Param("staerke", "Stärke", 1.0, 0.0, 1.0)], _ki("forgepix-background-mono-v2"), experimentell=True),
]
NACH_ID = {p.id: p for p in PROZESSE}

# Die Gruppen in der Reihenfolge eines üblichen Ablaufs — so bleibt die Liste übersichtlich und
# zeigt nebenbei, was wann kommt: erst zuschneiden und am linearen Bild arbeiten, dann strecken,
# dann am gestreckten Bild feilen, kombinieren, zuletzt die Sonderfälle.
GRUPPEN = ["Geometrie", "Hintergrund und Farbe", "Rauschen und Schärfe", "Strecken", "Sterne",
           "Mehrere Bilder", "Komet", "Externe Programme", "Eigene KI (experimentell)"]
assert set(GRUPPEN) == {p.gruppe for p in PROZESSE}, "Gruppe ohne Platz in der Reihenfolge"

# Wann ein Werkzeug hingehört. „linear“ = vor dem Strecken (Messwerte), „gestreckt“ = danach,
# „streckt“ = macht aus linear gestreckt, „beides“ = egal. None = nicht bekannt.
PHASE = {
    "zuschneiden": "beides", "drehen": "beides", "spiegeln": "beides", "abtasten": "beides",
    "binning": "linear",
    "hintergrund": "linear", "hintergrund_neutral": "linear", "farbe": "linear", "scnr": "beides",
    "farbkalibrierung": "linear",
    "saettigung": "gestreckt",
    "tv": "beides", "wavelet_nr": "beides", "wavelet_schaerfen": "gestreckt", "dekonvolution": "linear",
    "unscharf": "gestreckt", "falten": "beides", "streifen": "linear", "banding": "linear",
    "kosmetik": "linear",
    "mtf": "streckt", "ghs": "streckt", "asinh": "streckt", "ddp": "streckt", "masked_stretch": "streckt",
    "exponent": "gestreckt", "kurven": "gestreckt", "lokaler_kontrast": "gestreckt",
    "invertieren": "beides", "skalieren": "beides",
    "sterne_kleiner": "gestreckt", "sterne_entfernen": "beides", "synthstar": "gestreckt",
    "unclip": "linear", "morphologie": "gestreckt",
    "pixelmath": "beides", "lrgb": "gestreckt", "kontinuum": "linear", "kanal": "linear",
    "larson": "gestreckt",
    "graxpert": "linear", "cosmic": None, "starnet": "gestreckt",
    "acdnr": "beides", "hdrmt": "gestreckt", "gradienten_hdr": "gestreckt",
    "ki_entrauschen": "linear", "ki_schaerfen": "linear", "ki_sterne": "linear", "ki_hintergrund": "linear",
}
assert set(PHASE) == set(NACH_ID), "Werkzeug ohne Phase: %s" % (set(NACH_ID) ^ set(PHASE))
PHASE_TEXT = {"linear": "vor dem Strecken (lineares Bild)", "gestreckt": "nach dem Strecken",
              "streckt": "streckt das lineare Bild", "beides": "vor oder nach dem Strecken",
              None: "unbekannt, ob vor oder nach dem Strecken"}
MASKEN = ("keine", "Sterne", "Hintergrund", "Nebel", "Helligkeit")


def maske_bauen(bild, art="keine", von=0.2, bis=1.0, umkehren=False, weich=0.0):
    """Maske aus dem Bild selbst. None = keine Maske."""
    import masken
    if art == "keine":
        return None
    if art == "Sterne":
        m = masken.sterne(bild)
    elif art == "Hintergrund":
        m = masken.hintergrund(bild)
    elif art == "Nebel":
        m = masken.nebel(bild)
    elif art == "Helligkeit":
        if not 0.0 <= von < bis <= 1.0:
            raise ValueError("Helligkeitsmaske: 0 ≤ von < bis ≤ 1 verlangt, nicht %g … %g" % (von, bis))
        m = masken.helligkeit(bild, von, bis)
    else:
        raise ValueError("Unbekannte Maske %r; bekannt: %s" % (art, ", ".join(MASKEN)))
    if weich:
        m = masken.weichzeichnen(m, float(weich))
    return masken.invertieren(m) if umkehren else m


def anwenden(bild, prozess_id, werte=None, maske=None, experimentell_erlaubt=False, log=log_print):
    """Einen Prozess anwenden. Mit Maske wirkt er nur dort (1 = voll, 0 = gar nicht)."""
    if prozess_id not in NACH_ID:
        raise ValueError("Unbekannter Prozess %r" % prozess_id)
    p = NACH_ID[prozess_id]
    if p.experimentell and not experimentell_erlaubt:
        raise ValueError("%s ist ein experimentelles Modell und braucht die ausdrückliche Zusage." % p.name)
    da, hinweis = p.verfuegbar()
    if not da:
        raise ValueError("%s: %s" % (p.name, hinweis))
    w = p.werte(werte)
    a = np.asarray(bild, np.float32)
    if not np.isfinite(a).all():
        raise ValueError("Das Bild enthält ungültige Werte (NaN/unendlich).")
    import inspect
    if "log" in inspect.signature(p.fn).parameters:
        w = dict(w, log=log)
    ergebnis = np.asarray(p.fn(a.copy(), **w), np.float32)
    if not np.isfinite(ergebnis).all():
        raise ValueError("%s hat ungültige Werte erzeugt — Ergebnis verworfen." % p.name)
    if ergebnis.ndim == 2 and a.ndim == 3:
        ergebnis = np.repeat(ergebnis[..., None], 3, axis=2)
    if maske is not None:
        if p.aendert_groesse:
            raise ValueError("%s ändert die Bildgröße und lässt sich nicht maskieren." % p.name)
        import masken
        ergebnis = masken.anwenden(a, maske, ergebnis)
    return ergebnis


def statistik(bild):
    """Je Kanal: Mittel, Median, MAD-Streuung, kleinster/größter Wert, Anteil ≤0 und ≥1."""
    a = np.asarray(bild, np.float32)
    kanaele = [a[..., k] for k in range(a.shape[2])] if a.ndim == 3 else [a]
    namen = ("Blau", "Grün", "Rot") if len(kanaele) == 3 else ("Grau",)
    aus = []
    for name, k in zip(namen, kanaele):
        med = float(np.median(k))
        aus.append({"kanal": name, "mittel": float(k.mean()), "median": med,
                    "mad": float(np.median(np.abs(k - med)) * 1.4826),
                    "min": float(k.min()), "max": float(k.max()),
                    "unter_0": float(np.mean(k <= 0)), "ueber_1": float(np.mean(k >= 1))})
    return aus


class Arbeitsbild:
    """Original + Schritte, mit Rückgängig und Wiederholen.

    `behalten` Zwischenstände bleiben im Speicher; ältere werden aus dem nächstälteren
    behaltenen Stand nachgerechnet (das Original ist immer da)."""

    def __init__(self, bild, quelle=None, behalten=6, log=log_print):
        a = np.asarray(bild, np.float32)
        # Die Astro-Rechnungen erwarten drei Kanäle. Ein Graubild wird dreifach gelegt und beim
        # Speichern wieder einkanalig, solange alle Kanäle gleich geblieben sind.
        self.grau = a.ndim == 2
        if self.grau:
            a = np.repeat(a[..., None], 3, axis=2)
        self.original = a.copy()
        self.quelle, self.behalten, self.log = quelle, int(behalten), log
        self.schritte = []                 # [{id, werte, maske}], bis self.stand gültig
        self.stand = 0
        self._staende = {0: self.original}

    @property
    def bild(self):
        return self._stand_holen(self.stand)

    def _stand_holen(self, n):
        if n in self._staende:
            return self._staende[n]
        basis = max(k for k in self._staende if k <= n)
        bild = self._staende[basis]
        for i in range(basis, n):
            self.log("Nachrechnen: Schritt %d (%s)" % (i + 1, NACH_ID[self.schritte[i]["id"]].name))
            bild = self._schritt(bild, self.schritte[i])
        self._merken(n, bild)
        return bild

    def _schritt(self, bild, schritt):
        log = self.log
        maske = None
        if schritt.get("maske"):
            maske = maske_bauen(bild, **schritt["maske"])
        return anwenden(bild, schritt["id"], schritt["werte"], maske,
                        experimentell_erlaubt=schritt.get("experimentell", False), log=log)

    def _merken(self, n, bild):
        self._staende[n] = bild
        alte = sorted(k for k in self._staende if k != 0)
        for k in alte[:-self.behalten] if self.behalten > 0 else alte:
            del self._staende[k]

    def anwenden(self, prozess_id, werte=None, maske=None, experimentell_erlaubt=False):
        """maske: None oder dict für `maske_bauen` (art, von, bis, umkehren, weich) — gespeichert
        wird die BESCHREIBUNG, damit das Rezept auf ein anderes Bild passt."""
        p = NACH_ID[prozess_id]
        schritt = {"id": prozess_id, "werte": p.werte(werte),
                   "maske": dict(maske) if maske and maske.get("art", "keine") != "keine" else None,
                   "experimentell": bool(experimentell_erlaubt and p.experimentell)}
        neu = self._schritt(self.bild, schritt)
        del self.schritte[self.stand:]                       # Wiederholen-Zweig verfällt
        for k in [k for k in self._staende if k > self.stand]:
            del self._staende[k]
        self.schritte.append(schritt)
        self.stand += 1
        self._merken(self.stand, neu)
        return neu

    @property
    def kann_zurueck(self):
        return self.stand > 0

    @property
    def kann_vor(self):
        return self.stand < len(self.schritte)

    def rueckgaengig(self):
        if not self.kann_zurueck:
            raise ValueError("Nichts zum Rückgängigmachen.")
        self.stand -= 1
        return self.bild

    def wiederholen(self):
        if not self.kann_vor:
            raise ValueError("Nichts zum Wiederholen.")
        self.stand += 1
        return self.bild

    def zum_speichern(self):
        """Das aktuelle Bild; ein Graubild kommt einkanalig zurück, wenn es grau geblieben ist."""
        b = self.bild
        if self.grau and np.array_equal(b[..., 0], b[..., 1]) and np.array_equal(b[..., 0], b[..., 2]):
            return b[..., 0]
        return b

    def rezept(self):
        return {"format": REZEPT_FORMAT, "schritte": [dict(s) for s in self.schritte[:self.stand]]}

    @staticmethod
    def nachspielen(bild, rezept, log=log_print):
        if rezept.get("format") != REZEPT_FORMAT:
            raise ValueError("Kein Arbeitsplatz-Rezept (Format %r)" % rezept.get("format"))
        a = Arbeitsbild(bild, behalten=1, log=log)
        for s in rezept["schritte"]:
            a.anwenden(s["id"], s["werte"], s.get("maske"), experimentell_erlaubt=s.get("experimentell", False))
        return a.bild


def rezept_speichern(rezept, pfad):
    with open(pfad, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rezept, fh, ensure_ascii=False, indent=2)
    return pfad


def rezept_laden(pfad):
    with open(pfad, encoding="utf-8") as fh:
        return json.load(fh)


def bild_laden(pfad):
    """Float32 BGR (oder grau). FITS behält Messwerte; der FITS-Kopf wird mitgeliefert."""
    import astro
    kopf = None
    if pfad.lower().endswith((".fit", ".fits", ".fts")):
        from astropy.io import fits
        kopf = fits.getheader(pfad)
    return astro._read_float(pfad), kopf


def bild_speichern(pfad, bild, kopf=None, schritte=None):
    """Als 32-bit-TIFF oder FITS. Der Verlauf steht im FITS-Kopf als HISTORY."""
    a = np.asarray(bild, np.float32)
    if pfad.lower().endswith((".fit", ".fits", ".fts")):
        from astropy.io import fits
        h = fits.Header()
        verworfen = []
        if kopf is not None:
            for k, v in kopf.items():
                if k not in ("SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "NAXIS3", "EXTEND",
                             "BZERO", "BSCALE", "CHECKSUM", "DATASUM", "BAYERPAT", "XBAYROFF",
                             "YBAYROFF", "") and not k.startswith(("COMMENT", "HISTORY")):
                    try:
                        h[k] = v
                    except (ValueError, KeyError):
                        verworfen.append(k)
        if verworfen:                                  # benannt, nicht still
            h.add_history("Nicht uebernommene Kopfkarten: " + ", ".join(verworfen))
        for s in schritte or []:
            h.add_history("ForgePix Arbeitsplatz: %s %s%s" % (
                s["id"], json.dumps(s["werte"], ensure_ascii=True),
                " Maske %s" % s["maske"]["art"] if s.get("maske") else ""))
        daten = np.ascontiguousarray(a[..., ::-1].transpose(2, 0, 1)) if a.ndim == 3 else a
        fits.PrimaryHDU(daten, header=h).writeto(pfad, overwrite=False)
    else:
        import tifffile
        if a.ndim == 3:
            tifffile.imwrite(pfad, a[..., ::-1], photometric="rgb")
        else:
            tifffile.imwrite(pfad, a, photometric="minisblack")
    return pfad
