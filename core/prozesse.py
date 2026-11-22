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

import numpy as np

try:
    from constants import log_print
except ImportError:
    def log_print(*a, **k):
        print(*a, **k)

REZEPT_FORMAT = "forgepix-arbeitsplatz/1"


class Param:
    def __init__(self, name, label, standard, von=None, bis=None, wahl=None, ganz=False):
        self.name, self.label, self.standard = name, label, standard
        self.von, self.bis, self.wahl, self.ganz = von, bis, wahl, ganz

    @property
    def art(self):
        if self.wahl is not None:
            return "wahl"
        if isinstance(self.standard, bool):
            return "schalter"
        return "ganz" if self.ganz else "zahl"

    def pruefen(self, wert):
        if self.art == "wahl":
            if wert not in self.wahl:
                raise ValueError("%s: %r ist keine der Möglichkeiten %s" % (self.label, wert, self.wahl))
            return wert
        if self.art == "schalter":
            return bool(wert)
        wert = int(wert) if self.ganz else float(wert)
        if (self.von is not None and wert < self.von) or (self.bis is not None and wert > self.bis):
            raise ValueError("%s: %g liegt außerhalb %g … %g" % (self.label, wert, self.von, self.bis))
        return wert


class Prozess:
    def __init__(self, id, name, gruppe, vorbild, beschreibung, params, fn, aendert_groesse=False,
                 experimentell=False):
        self.id, self.name, self.gruppe = id, name, gruppe
        self.vorbild, self.beschreibung = vorbild, beschreibung
        self.params, self.fn = list(params), fn
        self.aendert_groesse, self.experimentell = aendert_groesse, experimentell

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


_STILL = {"log": lambda *a: None}

PROZESSE = [
    # --- Hintergrund und Farbe ----------------------------------------------------------
    Prozess("hintergrund", "Hintergrund ausgleichen", "Hintergrund und Farbe",
            "PixInsight: DynamicBackgroundExtraction/ABE · Siril: Background Extraction · GraXpert (klassisch)",
            "Verlauf aus Lichtverschmutzung und Vignette über Stützstellen (RBF) schätzen und entfernen.",
            [Param("strength", "Stärke", 0.12, 0.0, 1.0), Param("grid", "Stützstellen je Seite", 12, 4, 40, ganz=True),
             Param("korrektur", "Art", "sub", wahl=["sub", "div"])],
            _astro("background_extract", **_STILL)),
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
GRUPPEN = list(dict.fromkeys(p.gruppe for p in PROZESSE))
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


def anwenden(bild, prozess_id, werte=None, maske=None, experimentell_erlaubt=False):
    """Einen Prozess anwenden. Mit Maske wirkt er nur dort (1 = voll, 0 = gar nicht)."""
    if prozess_id not in NACH_ID:
        raise ValueError("Unbekannter Prozess %r" % prozess_id)
    p = NACH_ID[prozess_id]
    if p.experimentell and not experimentell_erlaubt:
        raise ValueError("%s ist ein experimentelles Modell und braucht die ausdrückliche Zusage." % p.name)
    w = p.werte(werte)
    a = np.asarray(bild, np.float32)
    if not np.isfinite(a).all():
        raise ValueError("Das Bild enthält ungültige Werte (NaN/unendlich).")
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

    @staticmethod
    def _schritt(bild, schritt):
        maske = None
        if schritt.get("maske"):
            maske = maske_bauen(bild, **schritt["maske"])
        return anwenden(bild, schritt["id"], schritt["werte"], maske,
                        experimentell_erlaubt=schritt.get("experimentell", False))

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
