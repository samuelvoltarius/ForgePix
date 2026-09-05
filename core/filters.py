#!/usr/bin/env python3
"""
filters.py — Filterkunde für ForgePix: welcher Filter lässt was durch, und was folgt daraus.

Warum das eine eigene Datei ist: die Bildverarbeitung muss wissen, WELCHE Emissionslinien
überhaupt im Bild sein können. Ein Dual-Band-Filter lässt Hα und OIII durch — mehr nicht.
Eine „SHO"-Palette daraus ist synthetisch, weil SII gar nicht ankommt. Ohne dieses Wissen
rechnet die Pipeline blind, und der Nutzer muss es selbst wissen.

BELEGTE WELLENLÄNGEN (Emissionslinien, nm):
  Hα   656.3    Wasserstoff — die stärkste Linie in Emissionsnebeln
  OIII 500.7    zweifach ionisierter Sauerstoff — planetarische Nebel, Supernovaüberreste
  SII  671.6    ionisierter Schwefel — Regionen mit starkem Sternwind
  Hβ   486.1    Wasserstoff, blau
Dual-Band-Filter liegen üblicherweise zwischen 3 nm und 10 nm Halbwertsbreite; schmaler gibt
mehr Kontrast, braucht aber längere Belichtung und verträgt schnelle Optiken schlechter.

ZUM ENTMISCHUNGSFAKTOR — ehrliche Einordnung:
Das Übersprechen bei einer OSC-Kamera entsteht im BAYER-Filter des Sensors (der Grün-Kanal hat
bei 656 nm noch Empfindlichkeit), nicht in der Filterbandbreite. Ein schmalerer Filter senkt
dieses Übersprechen also NICHT. Was er senkt, ist der durchgelassene Kontinuum-Anteil
(Sternlicht und Himmelshintergrund zwischen den Linien), und der verwässert die Trennung
zusätzlich. Die Werte unten sind deshalb erfahrungsbasierte STARTWERTE, keine gemessene
Physik — und bewusst überschreibbar.
"""

import re

# Emissionslinien in nm, wie in der Astrofotografie üblich gerundet
LINIEN = {"Ha": 656.3, "OIII": 500.7, "SII": 671.6, "Hb": 486.1}


class Filter:
    """Ein Aufnahmefilter: was er durchlässt und was die Pipeline daraus ableiten darf."""

    def __init__(self, schluessel, name, art, linien=(), breite_nm=None, unmix=0.20,
                 hinweis=""):
        self.schluessel = schluessel      # kurzer Bezeichner für CLI/Einstellungen
        self.name = name                  # Klartext für die Oberfläche
        self.art = art                    # breitband | lichtverschmutzung | dualband |
        #                                   multiband | schmalband
        self.linien = tuple(linien)       # welche Emissionslinien ankommen (leer = Kontinuum)
        self.breite_nm = breite_nm        # Halbwertsbreite, None bei Breitband
        self.unmix = float(unmix)         # Startwert für die Hα/OIII-Entmischung
        self.hinweis = hinweis

    @property
    def ist_dualband(self):
        """Trägt der Filter die zwei Linien, aus denen HOO gebaut wird?"""
        return "Ha" in self.linien and "OIII" in self.linien

    @property
    def hat_sii(self):
        """Echtes SII vorhanden? Nur dann ist eine SHO-Palette KEINE Erfindung."""
        return "SII" in self.linien

    def __repr__(self):
        return "<Filter %s %snm %s>" % (self.schluessel, self.breite_nm or "-", self.linien)


# Reihenfolge = Reihenfolge in der Oberfläche (vom Häufigsten zum Speziellen).
#
# QUELLENLAGE — was BELEGT ist und was nicht:
# Belegt (Herstellerangaben/Fachhändler, Stand 09/2026):
#   SVBONY SV220        7 nm Hα & OIII (auch als 3-nm-Ausführung)
#   SVBONY SV260        Breitband gegen Lichtverschmutzung, fünf Durchlassbänder 300–1000 nm
#   Optolong L-eXtreme  7 nm Hα, 7 nm OIII
#   Optolong L-Ultimate 3 nm Hα, 3 nm OIII
#   Antlia ALP-T        5 nm bzw. 3 nm Hα & OIII (dazu eine SII/OIII-Ausführung mit 3 nm)
#   ZWO Duo-Band        Hα 15 nm, OIII 35 nm  — deutlich breiter als die übrigen
# NICHT belegt: die genauen Bandbreiten von Optolong L-Pro und L-eNhance. Sie stehen darum
# ohne Zahl in der Liste und erben die Werte ihrer Klasse. Lieber ein grober Eintrag als eine
# erfundene Zahl — der Faktor ist ohnehin überschreibbar.
FILTER = [
    # --- kein Schmalband -------------------------------------------------------------
    Filter("keiner", "Kein Filter / nur Schutzglas", "breitband", (), None, 0.20,
           "Volles Spektrum. Unter Stadthimmel wird der Hintergrund schnell hell."),
    Filter("uvir", "UV/IR-Sperrfilter (IRCUT)", "breitband", (), None, 0.20,
           "Standard bei Farbkameras: schneidet UV und Infrarot ab, damit die Sterne scharf "
           "bleiben. Gegen Lichtverschmutzung hilft er nicht."),
    Filter("lp", "Lichtverschmutzung allgemein (CLS/UHC/LPR)", "lichtverschmutzung", (), None,
           0.20, "Dämpft typische Straßenlampen-Linien. Breitbandig — Sternfarben bleiben "
           "weitgehend erhalten, der Nebelkontrast steigt nur mäßig."),
    Filter("sv260", "SVBONY SV260 (Lichtverschmutzung)", "lichtverschmutzung", (), None, 0.20,
           "Breitband mit fünf Durchlassbändern von 300 bis über 1000 nm. Für Galaxien und "
           "Sternhaufen, nicht für Nebel-Schmalband."),
    Filter("lpro", "Optolong L-Pro (Lichtverschmutzung)", "lichtverschmutzung", (), None, 0.20,
           "Multi-Bandpass für aufgehellten Himmel, hält die Sternfarben. Genaue Bandbreiten "
           "vom Hersteller nicht veröffentlicht."),

    # --- Dual-Band (Hα + OIII), nach Bandbreite ---------------------------------------
    Filter("zwo_duo", "ZWO Duo-Band (Hα 15 nm / OIII 35 nm)", "dualband", ("Ha", "OIII"), 35.0,
           0.28, "Deutlich breiter als die übrigen Dual-Band-Filter — mehr Signal und "
           "gutmütig an schnellen Optiken, dafür die unschärfste Farbtrennung. Der OIII-Kanal "
           "nimmt viel Kontinuum mit."),
    Filter("lenhance", "Optolong L-eNhance (Tri-Band)", "multiband", ("Ha", "OIII", "Hb"), None,
           0.24, "Lässt zusätzlich Hβ durch, breiter als das L-eXtreme. Genaue Bandbreiten "
           "vom Hersteller nicht veröffentlicht."),
    Filter("dual12", "Dual-Band breit, 10–12 nm (allgemein)", "dualband", ("Ha", "OIII"), 12.0,
           0.22, "Verträgt schnelle Optiken und kurze Belichtungen, lässt aber mehr Kontinuum "
           "durch — die Trennung von Hα und OIII wird dadurch unschärfer."),
    Filter("dual7", "Dual-Band 7 nm (SVBONY SV220, Optolong L-eXtreme)", "dualband",
           ("Ha", "OIII"), 7.0, 0.14,
           "Guter Mittelweg: deutlich weniger Himmelshintergrund als 10–12 nm, noch gutmütig "
           "bei f/5 und langsamer."),
    Filter("dual5", "Dual-Band 5 nm (Antlia ALP-T 5 nm)", "dualband", ("Ha", "OIII"), 5.0, 0.11,
           "Hoher Kontrast, braucht dunkle Nächte und längere Einzelbelichtungen. Für f/3.6 "
           "und langsamer gerechnet."),
    Filter("dual3", "Dual-Band 3 nm (Antlia ALP-T 3 nm, Optolong L-Ultimate, SV220 3 nm)",
           "dualband", ("Ha", "OIII"), 3.0, 0.08,
           "Maximaler Kontrast auch bei Mond. Braucht lange Belichtungen; an sehr schnellen "
           "Optiken (f/2–f/3) kann die Durchlasskurve wandern."),
    Filter("dual_sii_oiii", "Dual-Band SII + OIII 3 nm (Antlia)", "dualband", ("SII", "OIII"),
           3.0, 0.08, "Die Ergänzung zum Hα/OIII-Filter: damit wird eine SHO-Palette ECHT, "
           "weil SII wirklich gemessen wird. Zwei Nächte, zwei Filter."),

    # --- Multi-Band -------------------------------------------------------------------
    Filter("quad", "Multi-Band / Quad-Band (allgemein)", "multiband",
           ("Ha", "OIII", "Hb", "SII"), 10.0, 0.20,
           "Lässt zusätzlich Hβ und SII durch. Mehr Signal, aber die Farbtrennung wird "
           "unsauberer als bei reinem Dual-Band."),

    # --- Einzellinien (Mono-Kameras / Filterrad) ---------------------------------------
    Filter("ha", "Schmalband Hα (Mono)", "schmalband", ("Ha",), 7.0, 0.0,
           "Einzellinie — keine Farbtrennung nötig, das Ergebnis ist ein Graustufenkanal."),
    Filter("oiii", "Schmalband OIII (Mono)", "schmalband", ("OIII",), 7.0, 0.0,
           "Einzellinie, Graustufenkanal."),
    Filter("sii", "Schmalband SII (Mono)", "schmalband", ("SII",), 7.0, 0.0,
           "Einzellinie, Graustufenkanal."),

    # --- Farbfilter für Mono-Kameras (LRGB) -------------------------------------------
    Filter("l", "Luminanz L (Mono)", "breitband", (), None, 0.20,
           "Der Helligkeitskanal einer LRGB-Aufnahme — trägt das Detail, ohne Farbe."),
    Filter("r", "Rot R (Mono)", "breitband", (), None, 0.20, "Farbkanal einer LRGB-Aufnahme."),
    Filter("g", "Grün G (Mono)", "breitband", (), None, 0.20, "Farbkanal einer LRGB-Aufnahme."),
    Filter("b", "Blau B (Mono)", "breitband", (), None, 0.20, "Farbkanal einer LRGB-Aufnahme."),
]

NACH_SCHLUESSEL = {f.schluessel: f for f in FILTER}


def hole(schluessel):
    """Filter über seinen Schlüssel holen; unbekannt -> None."""
    return NACH_SCHLUESSEL.get(str(schluessel or "").strip().lower())


def aus_header(wert):
    """Filter aus dem FITS-Schlüsselwort FILTER erraten (ASIAIR/N.I.N.A./Seestar schreiben es).

    Gibt den erkannten Filter zurück oder None. Bewusst konservativ: lieber None als eine
    falsche Annahme — davon hängt ab, ob SII als echt oder als synthetisch gilt.
    Echte Beispiele aus dem Bestand: "IRCUT", "LP" (Seestar S30), leer (ASIAIR ohne Filterrad).
    """
    t = str(wert or "").strip().lower()
    if not t:
        return None

    # 1) Markenmodelle zuerst — sie sind eindeutig und schlagen jede Heuristik
    marken = [
        ("l-ultimate", "dual3"), ("lultimate", "dual3"),
        ("l-extreme", "dual7"), ("lextreme", "dual7"), ("l-xtreme", "dual7"),
        ("l-enhance", "lenhance"), ("lenhance", "lenhance"),
        ("l-pro", "lpro"), ("lpro", "lpro"),
        ("sv260", "sv260"),
        ("duo-band", "zwo_duo"), ("duoband", "zwo_duo"),
    ]
    for muster, schl in marken:
        if muster in t:
            return hole(schl)

    # 2) Einzellinien und Farbkanäle (Mono-Filterrad schreibt oft nur "Ha", "R", "L")
    if t in ("l", "lum", "luminanz", "luminance"):
        return hole("l")
    if t in ("r", "red", "rot"):
        return hole("r")
    if t in ("g", "green", "gruen", "grün"):
        return hole("g")
    if t in ("b", "blue", "blau"):
        return hole("b")
    if t in ("ha", "h-alpha", "halpha", "h_alpha", "h-a"):
        return hole("ha")

    # 3) Sperr-/Lichtverschmutzungsfilter
    if any(k in t for k in ("ircut", "ir-cut", "uvir", "uv/ir", "uv-ir")):
        return hole("uvir")

    # 4) Klassen mit Bandbreite im Namen: "ALP-T 3nm", "SV220 7nm", "Dual 12nm"
    m = re.search(r"(\d+(?:\.\d+)?)\s*nm", t)
    schmal = any(k in t for k in ("dual", "duo", "extreme", "enhance", "alp", "sv220", "band",
                                  "sii", "oiii", "o3", "ha"))
    if m and schmal:
        nm = float(m.group(1))
        if "sii" in t and ("oiii" in t or "o3" in t):
            return hole("dual_sii_oiii")
        for schl, grenze in (("dual3", 4.0), ("dual5", 6.0), ("dual7", 8.5),
                             ("dual12", 20.0), ("zwo_duo", 99.0)):
            if nm <= grenze:
                return hole(schl)

    # 5) Linien ohne Bandbreitenangabe
    if "sii" in t or t == "s2":
        return hole("sii")
    if "oiii" in t or t == "o3":
        return hole("oiii")
    if "quad" in t or "triband" in t or "tri-band" in t or "l-quad" in t:
        return hole("quad")
    if any(k in t for k in ("alp-t", "sv220", "dual", "duo")):
        return hole("dual7")
    if any(k in t for k in ("cls", "uhc", "lpr")) or t == "lp":
        return hole("lp")
    return None


def beschreibung(f):
    """Ein Satz für die Oberfläche: was der Filter durchlässt und was daraus folgt."""
    if f is None:
        return "Filter unbekannt — ForgePix behandelt die Aufnahme als Breitband."
    teile = [f.name]
    if f.linien:
        teile.append("lässt durch: " + ", ".join("%s (%.1f nm)" % (l, LINIEN[l]) for l in f.linien))
    if f.breite_nm:
        teile.append("%g nm Halbwertsbreite" % f.breite_nm)
    satz = " — ".join(teile)
    return satz + ("." if not f.hinweis else ". " + f.hinweis)


def palette_ehrlich(f, palette):
    """Prüft, ob eine Palette zu diesem Filter überhaupt ECHT sein kann.

    Gibt (ok, hinweis) zurück. SHO/Foraxx brauchen SII; ein Dual-Band-Filter lässt kein SII
    durch, die Palette ist dann synthetisch (SII wird aus Hα erzeugt). Das ist erlaubt und
    sieht gut aus, sollte dem Nutzer aber gesagt werden statt verschwiegen zu werden.
    """
    if f is None:
        return True, ""
    if palette in ("sho", "foraxx") and not f.hat_sii:
        return False, ("%s lässt kein SII durch — die %s-Palette wird daher synthetisch aus Hα "
                       "erzeugt (sieht gut aus, ist aber keine SII-Messung)."
                       % (f.name, palette.upper()))
    if palette in ("hoo", "bicolor") and not f.ist_dualband and f.art != "multiband":
        return False, ("%s trägt nicht sowohl Hα als auch OIII — eine HOO-Trennung hat hier "
                       "keine physikalische Grundlage." % f.name)
    return True, ""
