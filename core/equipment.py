#!/usr/bin/env python3
"""
equipment.py — aus der Ausrüstung eine EMPFEHLUNG rechnen, nicht nur Daten verwalten.

Der Kern ist die Abbildungsskala: wie viele Bogensekunden Himmel fallen auf ein Pixel?

    Skala ["/px] = 206.265 × Pixelgröße [µm] / Brennweite [mm]

Daraus folgt die wichtigste Entscheidung im ganzen Astro-Ablauf, und ForgePix traf sie
bisher blind, obwohl es Binning UND Drizzle mitbringt:

  * ÜBERABGETASTET (Skala deutlich kleiner als die halbe FWHM): das Seeing verschmiert den
    Stern über viele Pixel. Jedes einzelne bekommt wenig Signal, das Rauschen bleibt.
    → BINNING bringt Signal-Rausch-Verhältnis, ohne echtes Detail zu kosten.

  * UNTERABGETASTET (Skala größer als die halbe FWHM): der Stern ist kleiner als ein Pixel,
    Detail geht schlicht verloren und Sterne werden eckig.
    → DRIZZLE kann Auflösung zurückholen — aber NUR mit Dithering zwischen den Aufnahmen.

  * PASSEND: nichts tun.

Das Besondere: ForgePix muss das Seeing nicht schätzen. `astro_quality` MISST die FWHM in
Pixeln an den echten Aufnahmen. Zusammen mit der Skala aus dem FITS-Header (FOCALLEN und
XPIXSZ stehen dort) ergibt sich eine belastbare Aussage statt einer Faustregel.

Kriterium (Nyquist, in der Astrofotografie übliche Auslegung): sinnvoll ist eine Skala
zwischen FWHM/3 und FWHM/2. Darunter überabgetastet, darüber unterabgetastet.
"""

# Umrechnungskonstante: 206265 Bogensekunden pro Radiant, µm/mm kürzt sich zu 1/1000
BOGENSEK_PRO_RAD = 206.265


def abbildungsskala(brennweite_mm, pixelgroesse_um, binning=1):
    """Bogensekunden pro Pixel. Gibt None, wenn die Angaben unbrauchbar sind."""
    try:
        f = float(brennweite_mm)
        p = float(pixelgroesse_um) * max(1, int(binning or 1))
    except (TypeError, ValueError):
        return None
    if f <= 0 or p <= 0:
        return None
    return BOGENSEK_PRO_RAD * p / f


def oeffnungsverhaeltnis(brennweite_mm, oeffnung_mm):
    """f/Zahl aus Brennweite und ÖFFNUNGSDURCHMESSER. None, wenn unbrauchbar.

    Mit Plausibilitätsprüfung: Amateurgerät liegt zwischen etwa f/1.4 und f/20. Alles
    außerhalb deutet auf ein falsch belegtes Header-Feld hin (der Seestar S30 schreibt in
    APERTURE eine 5.0, die kein Durchmesser ist) — dann lieber nichts sagen als Unsinn.
    """
    try:
        f, d = float(brennweite_mm), float(oeffnung_mm)
    except (TypeError, ValueError):
        return None
    if d <= 0 or f <= 0:
        return None
    verh = f / d
    return verh if 1.0 <= verh <= 25.0 else None


class Korrektor:
    """Reducer, Flattener oder Barlow im Strahlengang.

    Ein Reducer verkürzt die Brennweite (Faktor < 1) und macht die Optik damit schneller;
    eine Barlow verlängert sie (Faktor > 1). Ein reiner Flattener lässt die Brennweite
    unverändert (Faktor 1.0) und begradigt nur das Bildfeld.

    Warum das in die Rechnung MUSS: die Brennweite bestimmt die Abbildungsskala und damit,
    ob Binning oder Drizzle sinnvoll ist. Und das Öffnungsverhältnis entscheidet mit, ob ein
    Schmalbandfilter noch sauber arbeitet — bei sehr schnellen Systemen wandert die
    Durchlasskurve zu kürzeren Wellenlängen, der Filter trifft die Linie dann schlechter.
    """

    def __init__(self, schluessel, name, faktor, hinweis=""):
        self.schluessel = schluessel
        self.name = name
        self.faktor = float(faktor)
        self.hinweis = hinweis

    def __repr__(self):
        return "<Korrektor %s x%.2f>" % (self.schluessel, self.faktor)


KORREKTOREN = [
    Korrektor("keiner", "Kein Korrektor", 1.0, "Brennweite unverändert."),
    Korrektor("flattener", "Flattener (Bildfeldebnung)", 1.0,
              "Begradigt das Bildfeld gegen verzogene Ecksterne, ohne die Brennweite zu ändern."),
    Korrektor("red_090", "Reducer 0.90×", 0.90, ""),
    Korrektor("red_080", "Reducer 0.80×", 0.80, ""),
    Korrektor("red_079", "Reducer/Flattener 0.79×", 0.79, "Verbreitet bei Refraktoren."),
    Korrektor("red_075", "Reducer 0.75×", 0.75, ""),
    Korrektor("red_067", "Reducer 0.67×", 0.67,
              "Verbreitet an RC- und SC-Teleskopen (z. B. GSO/TS 8\" RC)."),
    Korrektor("red_063", "Reducer 0.63×", 0.63, "Klassisch an Schmidt-Cassegrains."),
    Korrektor("barlow_2", "Barlow 2×", 2.0, "Verdoppelt die Brennweite — für Planeten."),
]

NACH_KORREKTOR = {k.schluessel: k for k in KORREKTOREN}


# Ein paar gängige Teleskope als Startpunkt. Die Liste ist bewusst kurz: entscheidend sind
# nur Öffnung und Brennweite, und die kann man immer von Hand eintragen.
TELESKOPE = [
    ("manuell", "Eigene Werte eintragen", None, None),
    ("rc8", "8\" Ritchey-Chrétien f/8 (GSO/TS 203/1624)", 203.0, 1624.0),
    ("rc6", "6\" Ritchey-Chrétien f/9 (GSO/TS 154/1370)", 154.0, 1370.0),
    ("newt200f5", "8\" Newton f/5 (200/1000)", 200.0, 1000.0),
    ("newt150f5", "6\" Newton f/5 (150/750)", 150.0, 750.0),
    ("apo80f6", "80 mm APO f/6 (80/480)", 80.0, 480.0),
    ("apo72f6", "72 mm APO f/5.9 (72/420)", 72.0, 420.0),
    ("sct8", "8\" Schmidt-Cassegrain f/10 (203/2032)", 203.0, 2032.0),
    ("seestar_s30", "Seestar S30 (30/150)", 30.0, 150.0),
    ("seestar_s50", "Seestar S50 (50/250)", 50.0, 250.0),
]

NACH_TELESKOP = {t[0]: t for t in TELESKOPE}


def wirksame_brennweite(brennweite_mm, korrektor=None):
    """Brennweite nach Reducer/Barlow. `korrektor` ist ein Schlüssel oder ein Faktor."""
    try:
        f = float(brennweite_mm)
    except (TypeError, ValueError):
        return None
    if korrektor in (None, "", "keiner"):
        return f
    k = NACH_KORREKTOR.get(korrektor)
    if k is not None:
        return f * k.faktor
    try:                                    # auch ein roher Faktor ist erlaubt
        return f * float(korrektor)
    except (TypeError, ValueError):
        return f


def filter_warnung(f_zahl, filt):
    """Warnt, wenn ein Schmalbandfilter für die Optik zu schnell ist.

    Bei sehr schnellen Systemen treffen die Strahlen den Interferenzfilter schräg; die
    Durchlasskurve wandert zu kürzeren Wellenlängen und trifft die Emissionslinie schlechter.
    Je schmaler der Filter, desto empfindlicher. Die Herstellerangaben sind uneinheitlich —
    darum eine vorsichtige Faustregel und kein Absolutwert.
    """
    if not f_zahl or filt is None or not getattr(filt, "breite_nm", None):
        return ""
    breite = float(filt.breite_nm)
    if breite <= 3.5 and f_zahl < 4.0:
        return ("Achtung: %s an f/%.1f — bei sehr schmalen Filtern und schnellen Optiken kann "
                "die Durchlasskurve wandern und die Linie schlechter treffen. Viele 3-nm-Filter "
                "sind für f/4 und langsamer gerechnet." % (filt.name, f_zahl))
    if breite <= 6.0 and f_zahl < 3.0:
        return ("Hinweis: %s an f/%.1f ist sehr schnell — auf Randabfall im OIII-Kanal achten."
                % (filt.name, f_zahl))
    return ""


def aus_header(header):
    """Ausrüstungsdaten aus einem FITS-Header lesen (dict-artig). Gibt ein Dict zurück.

    Die Felder heißen bei ASIAIR, N.I.N.A. und Seestar gleich — geprüft an echten Dateien:
    FOCALLEN, XPIXSZ, XBINNING, INSTRUME, TELESCOP, GAIN, CCD-TEMP, BAYERPAT, FILTER.
    """
    def z(*namen):
        for n in namen:
            if n in header:
                try:
                    return float(header[n])
                except (TypeError, ValueError):
                    pass
        return None

    def t(*namen):
        for n in namen:
            if n in header:
                w = str(header[n]).strip()
                if w:
                    return w
        return None

    return {
        "kamera": t("INSTRUME"),
        "teleskop": t("TELESCOP"),
        "brennweite_mm": z("FOCALLEN"),
        # NUR APTDIA: das ist der genormte Öffnungsdurchmesser in mm. "APERTURE" ist
        # mehrdeutig — der Seestar S30 schreibt dort 5.0 mit dem Kommentar "Name of field of
        # view aperture", also KEIN Durchmesser. Als solcher gelesen kam f/30 heraus statt f/5.
        "oeffnung_mm": z("APTDIA"),
        "pixelgroesse_um": z("XPIXSZ", "PIXSIZE1"),
        "binning": int(z("XBINNING") or 1),
        "gain": z("GAIN"),
        "temperatur_c": z("CCD-TEMP"),
        "belichtung_s": z("EXPTIME", "EXPOSURE"),
        "bayer": t("BAYERPAT"),
        "filter": t("FILTER"),
    }


def sampling_urteil(skala_arcsec, fwhm_px):
    """Über- oder unterabgetastet? Gibt (kennzeichen, satz, empfehlung) zurück.

    `fwhm_px` ist die GEMESSENE Halbwertsbreite der Sterne in Pixeln (aus astro_quality).
    Daraus ergibt sich die tatsächliche Auflösung am Himmel: fwhm_arcsec = fwhm_px × skala.
    Sinnvoll abgetastet ist eine Skala zwischen fwhm_arcsec/3 und fwhm_arcsec/2.
    """
    if not fwhm_px or fwhm_px <= 0:
        return "unbekannt", "Abtastung nicht bestimmbar (keine Sterne vermessen).", None
    fwhm_px = float(fwhm_px)
    # Das Kriterium haengt AUSSCHLIESSLICH an der FWHM in Pixeln: die Forderung
    # "Skala zwischen fwhm_arcsec/3 und fwhm_arcsec/2" ist mit fwhm_arcsec = fwhm_px x Skala
    # gleichbedeutend mit "fwhm_px zwischen 2 und 3". Die Bogensekunden kuerzen sich heraus.
    # Sie stehen im Text nur als Einordnung, sie entscheiden nichts — das hier offen zu sagen
    # ist ehrlicher, als eine Rechnung vorzufuehren, die am Ergebnis nichts aendert.
    if skala_arcsec:
        kontext = ("Sterne messen %.1f px (= %.2f″ bei %.2f″/Pixel). "
                   % (fwhm_px, fwhm_px * float(skala_arcsec), float(skala_arcsec)))
    else:
        kontext = "Sterne messen %.1f px. " % fwhm_px
    kontext += "Gut abgetastet sind 2–3 px pro Sternhalbwertsbreite."
    if fwhm_px < 2.0:
        return ("unterabgetastet",
                kontext + " Hier ist es weniger — Detail geht verloren, Sterne werden eckig.",
                "drizzle")
    if fwhm_px > 3.5:
        return ("ueberabgetastet",
                kontext + " Hier ist es deutlich mehr — das Signal verteilt sich auf zu viele "
                "Pixel, ohne mehr Detail zu tragen.",
                "binning")
    if fwhm_px < 2.3:
        return ("grenzwertig",
                kontext + " Hier liegt es knapp an der unteren Grenze.", "drizzle_knapp")
    return "passend", kontext + " Das passt.", None


def empfehlung_text(kennzeichen, empfehlung, gedithert=None):
    """Klartext-Rat zum Urteil. `gedithert` sagt, ob zwischen den Aufnahmen gedithert wurde."""
    if empfehlung == "drizzle_knapp":
        return ("Knapp an der Grenze: Drizzle (--astro-drizzle 2) kann etwas Auflösung "
                "zurückholen, wenn gedithert wurde. Der Gewinn ist hier aber klein — kein Muss.")
    if empfehlung == "drizzle":
        if gedithert is False:
            return ("Drizzle würde hier Auflösung zurückholen — es braucht dafür aber Dithering "
                    "zwischen den Aufnahmen, und danach sieht es hier nicht aus. Ohne Dithering "
                    "bringt Drizzle nichts außer einem größeren Bild.")
        return ("Drizzle (--astro-drizzle 2) kann hier echte Auflösung zurückholen, "
                "vorausgesetzt es wurde gedithert.")
    if empfehlung == "binning":
        return ("Binning 2× bringt hier Signal-Rausch-Verhältnis und rundere Sterne, ohne echtes "
                "Detail zu kosten — das Seeing gibt mehr Auflösung ohnehin nicht her.")
    if kennzeichen == "passend":
        return "Weder Binning noch Drizzle nötig."
    return ""


def bericht(daten, fwhm_px=None, gedithert=None):
    """Mehrzeiliger Klartextbericht über die Ausrüstung und was daraus folgt."""
    zeilen = []
    kam, tel = daten.get("kamera"), daten.get("teleskop")
    if kam:
        zeilen.append("Kamera: %s" % kam)
    if tel:
        zeilen.append("Teleskop/Montierung: %s" % tel)
    fl, px, bin_ = daten.get("brennweite_mm"), daten.get("pixelgroesse_um"), daten.get("binning", 1)
    skala = abbildungsskala(fl, px, bin_)
    if fl and px:
        zeilen.append("Brennweite %.0f mm, Pixel %.2f µm%s → %.2f″/Pixel"
                      % (fl, px, (" (Binning %d×)" % bin_) if bin_ and bin_ > 1 else "", skala))
    f_zahl = oeffnungsverhaeltnis(fl, daten.get("oeffnung_mm"))
    if f_zahl:
        zeilen.append("Öffnungsverhältnis f/%.1f" % f_zahl)
    if skala and fwhm_px:
        kennz, satz, empf = sampling_urteil(skala, fwhm_px)
        zeilen.append(satz)
        rat = empfehlung_text(kennz, empf, gedithert)
        if rat:
            zeilen.append(rat)
    return zeilen
