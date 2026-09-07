#!/usr/bin/env python3
"""
core/vorpruefung.py — was man VOR dem Stapeln schon weiß.

Das Regelwerk (`core/regeln.py`) urteilt über den fertigen Stapel. Das ist richtig für alles,
was man erst am Ergebnis sieht — Helligkeitsverlauf, Sternform, Farbverhalten. Für einen guten
Teil der Befunde ist es aber zu spät: **dass nur vier Aufnahmen da sind, dass zwei verschiedene
Kameras im Ordner liegen oder dass Ha und L gemischt wurden, steht in den Kopfdaten.** Das
zwanzig Minuten nach dem Start zu erfahren, ist eine vermeidbare Enttäuschung.

Diese Prüfung liest nur Kopfdaten. Sie öffnet kein einziges Bild, dauert Sekunden und ändert
nichts — sie sagt nur, was sie sieht.

Zwei Befunde sind hier wichtiger als alle anderen, weil sie **still** danebengehen:

* **Mehrere Kameras in einer Serie.** Verschiedene Sensoren haben verschiedene Pixelmaßstäbe und
  damit verschieden breite Sterne. Der Stapel läuft durch, das Ergebnis sieht aus wie ein Bild,
  und die Sterne sind Matsch. Nichts daran meldet sich.
* **Azimutale Montierung mit `--astro-align shift`.** Der Seestar dreht sein Bildfeld im Lauf
  der Nacht. Mit reiner Verschiebung ausgerichtet fielen an einer echten Serie (IC 434, 224 Subs,
  bis −27,6° Drehung) 98 % der Aufnahmen weg, und die behaltenen waren verschmiert — gemessen:
  FWHM 4,63 px statt 2,63 px, Exzentrizität 2,31 statt 1,32.

Die Ausgabe hat dieselbe Form wie beim Regelwerk (`regeln.Rat`), damit beides gleich aussieht.
"""
import collections
import math
import os

from constants import log_print
from regeln import HINWEIS, KRITISCH, Rat, WICHTIG

# Kameras auf azimutaler Montierung: das Bildfeld dreht sich im Lauf der Nacht. Erkannt wird am
# Kameranamen aus INSTRUME, weil die Montierung selbst nicht im Header steht.
AZIMUTAL = ("seestar", "dwarf", "vespera", "stellina", "hestia", "origin")

_FELDER = ("INSTRUME", "EXPTIME", "EXPOSURE", "FILTER", "CCD-TEMP", "DATE-OBS", "IMAGETYP",
           "FRAME", "GAIN", "XPIXSZ", "FOCALLEN", "RA", "DEC", "CRVAL1", "CRVAL2",
           "OBJCTRA", "OBJCTDEC", "TOTALEXP", "STACKCNT", "NAXIS1", "NAXIS2")


def _richtung(h):
    """Wohin das Teleskop zeigte, als Gradzahlen — oder None, wenn es nicht dasteht."""
    def z(*namen):
        for n in namen:
            if n in h:
                try:
                    return float(h[n])
                except (TypeError, ValueError):
                    pass
        return None
    ra, dec = z("RA", "CRVAL1", "OBJCTRA"), z("DEC", "CRVAL2", "OBJCTDEC")
    return None if ra is None or dec is None else (ra, dec)


def _winkelabstand(a, b):
    """Echter Winkelabstand zweier Himmelsrichtungen in Grad (RA/DEC).

    Nicht einfach die Differenz der Zahlen: bei RA zaehlt der Kosinus der Deklination, und der
    Uebergang von 359,9 auf 0,1 Grad sind 0,2 Grad und nicht 359,8.
    """
    ra1, de1 = math.radians(a[0]), math.radians(a[1])
    ra2, de2 = math.radians(b[0]), math.radians(b[1])
    d = (math.sin((de2 - de1) / 2) ** 2
         + math.cos(de1) * math.cos(de2) * math.sin((ra2 - ra1) / 2) ** 2)
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(max(0.0, d)))))


def _felder_bilden(richtungen, toleranz_grad=0.5):
    """Richtungen zu Feldern zusammenfassen. Gibt je Richtung die Nummer ihres Feldes.

    Warum ueberhaupt: in Alfreds Bestand liegen im Ordner `whirl` Aufnahmen von fuenf
    verschiedenen Zielen — RA/DEC springen zwischen (202,5 | 47,2), (210,8 | 54,3),
    (184,7 | 47,3), (112,3 | 20,9) und (189,1 | 26,0). Ohne Richtung im Schluessel landeten
    sie in EINER Serie; beim Stapeln fielen dann 76 % der Aufnahmen als "nicht ausrichtbar"
    heraus. Sie sind aber nicht schlecht, sie zeigen etwas anderes.

    Warum kein Raster: eine Rasterung nach `round(ra / 0,5)` zerschneidet ein Feld genau dann,
    wenn es auf einer Zellgrenze liegt. Genau passiert: RA 210,75 und 210,80 landeten in den
    Zellen 421 und 422 — aus 84 zusammengehoerenden Aufnahmen wurden 55 und 29. Hier wird
    stattdessen nach Abstand zusammengefasst.

    0,5 Grad Toleranz: Dithering und Nachfuehrfehler bewegen sich im Bogenminutenbereich, ein
    Mosaik-Feld oder ein neues Ziel dagegen um Grad. Fehlt die Angabe, bleibt das Feld None und
    es wird wie zuvor gruppiert.
    """
    mitten = []
    zuordnung = []
    for r in richtungen:
        if r is None:
            zuordnung.append(None)
            continue
        for i, m in enumerate(mitten):
            if _winkelabstand(r, m) <= toleranz_grad:
                zuordnung.append(i)
                break
        else:
            mitten.append(r)
            zuordnung.append(len(mitten) - 1)
    return zuordnung, mitten


def kopfdaten(paths, max_dateien=400, log=log_print):
    """Die Kopfdaten der Lights einsammeln. Liest nur Header, keine Bilddaten.

    Bei sehr vielen Aufnahmen wird gleichmäßig ausgedünnt: für die Frage „sind hier zwei
    Kameras drin" genügt eine Stichprobe über die ganze Serie, und 2000 Header zu lesen kostet
    Minuten, die niemand für eine Vorprüfung ausgeben will.
    """
    fits_pfade = [p for p in (paths or [])
                  if os.path.splitext(str(p))[1].lower() in (".fit", ".fits", ".fts")]
    if not fits_pfade:
        return []
    schritt = max(1, len(fits_pfade) // max_dateien)
    stichprobe = fits_pfade[::schritt]
    try:
        from astropy.io import fits
    except ImportError:
        return []
    aus, unlesbar = [], 0
    for p in stichprobe:
        try:
            h = fits.getheader(p)
        except Exception:
            unlesbar += 1
            continue
        aus.append({k: h[k] for k in _FELDER if k in h})
    if len(stichprobe) < len(fits_pfade):
        log("    Vorpruefung: %d von %d Aufnahmen als Stichprobe gelesen"
            % (len(stichprobe), len(fits_pfade)))
    # Unlesbare Kopfdaten melden. Ohne diese Zeile faellt die ganze Vorpruefung stillschweigend
    # aus, wenn keine Datei lesbar ist — und niemand erfaehrt, warum nichts dasteht. Genau die
    # Sorte Fehler, die dieses Projekt schon mehrfach teuer bezahlt hat.
    if unlesbar:
        log("    Vorpruefung: %d von %d Kopfdaten nicht lesbar%s"
            % (unlesbar, len(stichprobe),
               " — die Vorpruefung entfaellt." if not aus else "."))
    return aus


def _zahl(x):
    try:
        v = float(x)
        return v if v == v else None      # NaN raus
    except (TypeError, ValueError):
        return None


def uebersicht(koepfe, gesamt=None):
    """Was steht in den Kopfdaten? Reine Beschreibung, kein Urteil."""
    kameras = collections.Counter()
    filter_ = collections.Counter()
    zeiten = collections.Counter()
    temperaturen, naechte, richtungen = [], collections.Counter(), []
    verstaerkungen = collections.Counter()
    gesamt_s, subs = 0.0, 0
    groessen = collections.Counter()
    zeitpunkte = []
    for h in koepfe:
        k = str(h.get("INSTRUME", "")).strip()
        if k:
            kameras[k] += 1
        f = str(h.get("FILTER", "")).strip()
        if f:
            filter_[f] += 1
        t = _zahl(h.get("EXPTIME", h.get("EXPOSURE")))
        if t is not None:
            zeiten[round(t, 1)] += 1
        # Fertige Stapel tragen ihre wahre Gesamtbelichtung im Header. Ohne diese Felder
        # meldete ForgePix fuer sechs zusammengefasste M-42-Ergebnisse "3 Minuten" statt 199.
        gt = _zahl(h.get("TOTALEXP"))
        gesamt_s += gt if gt is not None else (t or 0.0)
        sc = _zahl(h.get("STACKCNT"))
        if sc is not None:
            subs += int(sc)
        c = _zahl(h.get("CCD-TEMP"))
        if c is not None:
            temperaturen.append(c)
        g = _zahl(h.get("GAIN"))
        if g is not None:
            verstaerkungen[round(g)] += 1
        d = str(h.get("DATE-OBS", ""))[:10]
        if d:
            naechte[d] += 1
        # Die Uhrzeit mitfuehren: die Gesamtbelichtung sagt nicht, ueber welchen ZEITRAUM
        # aufgenommen wurde. Fuer Kometen ist genau das die entscheidende Groesse — der Kern
        # muss sich messbar bewegt haben. An echten Daten: 3,5 Minuten Belichtung, aber
        # 4 Minuten 23 Sekunden Zeitraum.
        voll = str(h.get("DATE-OBS", "")).strip()
        if len(voll) >= 19:
            zeitpunkte.append(voll[:19])
        r = _richtung(h)
        if r is not None:
            richtungen.append(r)
        b, ho = h.get("NAXIS1"), h.get("NAXIS2")
        if b and ho:
            groessen[(int(b), int(ho))] += 1
    # Wie weit liegen die Ausrichtungen auseinander? Ein Wert, keine Liste — es geht nur um die
    # Frage, ob hier ein Feld aufgenommen wurde oder mehrere.
    spanne_grad = None
    if len(richtungen) >= 2:
        mitte = (sum(x for x, _y in richtungen) / len(richtungen),
                 sum(y for _x, y in richtungen) / len(richtungen))
        spanne_grad = max(_winkelabstand(r, mitte) for r in richtungen) * 2.0
    zeitraum_min = None
    if len(zeitpunkte) >= 2:
        try:
            from datetime import datetime
            werte = sorted(datetime.fromisoformat(z) for z in zeitpunkte)
            zeitraum_min = (werte[-1] - werte[0]).total_seconds() / 60.0
        except (ValueError, TypeError):
            zeitraum_min = None
    return {
        "anzahl": int(gesamt if gesamt is not None else len(koepfe)),
        "gelesen": len(koepfe),
        "kameras": dict(kameras),
        "filter": dict(filter_),
        "belichtungen_s": dict(zeiten),
        "temperatur_c": ((min(temperaturen), max(temperaturen)) if temperaturen else None),
        "verstaerkungen": dict(verstaerkungen),
        "naechte": sorted(naechte),
        "richtungsspanne_grad": spanne_grad,
        "gesamt_minuten": ((gesamt_s / 60.0)
                           * (float(gesamt) / max(1, len(koepfe)) if gesamt else 1.0)
                           if gesamt_s > 0 else None),
        "enthaltene_subs": (subs if subs else None),
        "bildgroessen": dict(groessen),
        "zeitraum_minuten": zeitraum_min,
    }


def pruefen(uebersicht_, *, align_mode=None, hat_dark=None, hat_flat=None):
    """Aus der Übersicht Befunde machen. Fehlende Angaben lösen NICHTS aus."""
    raete = []
    u = uebersicht_ or {}

    kameras = u.get("kameras") or {}
    if len(kameras) > 1:
        raete.append(Rat(
            KRITISCH, "Mehrere Kameras in einer Serie",
            "In den Aufnahmen stecken %s. Verschiedene Sensoren haben verschiedene "
            "Pixelmassstaebe und damit verschieden breite Sterne. Der Stapel laeuft durch, das "
            "Ergebnis sieht aus wie ein Bild, und die Sterne sind Matsch — nichts daran meldet "
            "sich von selbst."
            % ", ".join("%s (%dx)" % (k, n) for k, n in sorted(kameras.items())),
            "Die Aufnahmen nach Kamera trennen und getrennt stapeln.",
            None))

    # Die Verstaerkung bestimmt, wieviele Elektronen ein ADU-Schritt bedeutet. Zwei Werte in
    # einer Serie heissen: dieselbe Himmelshelligkeit steht in den Aufnahmen als verschiedene
    # Zahl, und ein Dark passt nur zu einem Teil. An echten Daten gesehen (M51, 340 Aufnahmen):
    # eine Nacht mit Gain 120, vier Naechte mit Gain 130 — und niemand sagte es.
    verstaerkungen = u.get("verstaerkungen") or {}
    if len(verstaerkungen) > 1:
        raete.append(Rat(
            WICHTIG, "Mehrere Verstaerkungen in einer Serie",
            "In den Aufnahmen stecken die Gain-Werte %s. Die Verstaerkung bestimmt, wieviele "
            "Elektronen hinter einem Zahlenschritt stehen: derselbe Himmel ergibt dann "
            "verschiedene Werte, Darks passen nur zu einem Teil, und die Ausreisser-Erkennung "
            "vergleicht Aufnahmen mit verschiedenem Rauschverhalten miteinander."
            % ", ".join("%s (%dx)" % (g, n) for g, n in sorted(verstaerkungen.items())),
            "Getrennt stapeln, oder die Abweichler weglassen.",
            None))

    spanne = u.get("richtungsspanne_grad")
    if spanne is not None and spanne > 1.0:
        raete.append(Rat(
            KRITISCH, "Mehrere Himmelsausschnitte in einer Serie",
            "Die Aufnahmen zeigen nicht dasselbe Feld — die Ausrichtungen liegen bis zu "
            "%.1f Grad auseinander. Beim Stapeln fallen die Aufnahmen des zweiten Ziels als "
            "'nicht ausrichtbar' heraus, ohne dass jemand erfaehrt, dass es sie gab. An einem "
            "echten Ordner gemessen: fuenf verschiedene Ziele in einem Verzeichnis, 76 %% der "
            "Aufnahmen einer Serie weggeworfen." % spanne,
            "Nach Objekt trennen und getrennt stapeln. Fuer ein Mosaik ist der Mosaik-Modus "
            "zustaendig, nicht der Astro-Stapel.",
            None))

    groessen = u.get("bildgroessen") or {}
    if len(groessen) > 1:
        raete.append(Rat(
            KRITISCH, "Verschiedene Bildgroessen in einer Serie",
            "In den Aufnahmen stecken %s. Der Seestar schreibt zum Beispiel neben dem "
            "normalen Ergebnis auch ein groesseres — zusammenstapeln laesst sich das nicht."
            % ", ".join("%dx%d (%dx)" % (b, h, n) for (b, h), n in sorted(groessen.items())),
            "Nach Bildgroesse trennen und getrennt stapeln.",
            None))

    filter_ = u.get("filter") or {}
    if len(filter_) > 1:
        raete.append(Rat(
            WICHTIG, "Mehrere Filter in einer Serie",
            "In den Aufnahmen stecken %s. Verschiedene Filter zeigen verschiedene "
            "Wellenlaengen; sie zusammenzumitteln verwischt genau die Information, wegen der "
            "gefiltert wurde."
            % ", ".join("%s (%dx)" % (k, n) for k, n in sorted(filter_.items())),
            "Nach Filter trennen und die Kanaele erst danach zusammensetzen.",
            None))

    anzahl = u.get("anzahl")
    if anzahl is not None and anzahl < 5:
        raete.append(Rat(
            KRITISCH, "Zu wenige Aufnahmen fuer Ausreisser-Verwurf",
            "%d Aufnahmen. Sigma-Clipping braucht mindestens 5, sonst ist die Statistik zu "
            "duenn — Satellitenspuren und kosmische Treffer bleiben stehen." % anzahl,
            "Mehr Aufnahmen sammeln.",
            None))
    elif anzahl is not None and anzahl < 10:
        raete.append(Rat(
            WICHTIG, "Wenige Aufnahmen",
            "%d Aufnahmen. Das Rauschen sinkt mit der Wurzel der Anzahl — von 8 auf 32 "
            "Aufnahmen halbiert es sich." % anzahl,
            "Mehr sammeln.",
            None))

    # Azimutale Montierung: das Bildfeld dreht sich. Nur melden, wenn ausdruecklich reine
    # Verschiebung eingestellt ist — im Standard (rotate) ist alles in Ordnung.
    if align_mode == "shift":
        dreher = [k for k in kameras if any(a in k.lower() for a in AZIMUTAL)]
        if dreher:
            raete.append(Rat(
                WICHTIG, "Azimutale Montierung mit reiner Verschiebung",
                "%s dreht das Bildfeld im Lauf der Nacht. Mit '--astro-align shift' wird nur "
                "verschoben. An einer echten Serie gemessen (IC 434, 224 Subs, bis -27,6 Grad "
                "Drehung) fielen dabei 98 %% der Aufnahmen weg, und die behaltenen waren "
                "verschmiert: FWHM 4,63 px statt 2,63 px, Exzentrizitaet 2,31 statt 1,32."
                % ", ".join(dreher),
                "'--astro-align rotate' verwenden (das ist der Standard).",
                "--astro-align rotate"))

    zeiten = u.get("belichtungen_s") or {}
    if len(zeiten) > 1:
        raete.append(Rat(
            HINWEIS, "Gemischte Belichtungszeiten",
            "In der Serie stecken %s." % "/".join("%g s" % t for t in sorted(zeiten)),
            "Wird automatisch umgerechnet und gewichtet.",
            None))

    spanne = u.get("temperatur_c")
    if spanne and (spanne[1] - spanne[0]) > 5.0:
        raete.append(Rat(
            HINWEIS, "Grosse Temperaturspanne",
            "Die Sensortemperatur schwankt von %.1f auf %.1f Grad. Das Dunkelstrom-Rauschen "
            "verdoppelt sich etwa alle 6 Grad; ein Dark passt dann nicht zu allen Aufnahmen."
            % spanne,
            "Darks bei der tatsaechlichen Temperatur aufnehmen, oder die Skalierung nutzen.",
            None))

    if hat_dark is False and hat_flat is False:
        raete.append(Rat(
            HINWEIS, "Keine Kalibrierbilder",
            "Weder Dark noch Flat gefunden. Ohne Flat bleiben Vignettierung und Staub im "
            "Bild, ohne Dark das Muster warmer Pixel.",
            "Darks und Flats aufnehmen — sie bringen mehr als jede Nachbearbeitung.",
            None))

    reihenfolge = {KRITISCH: 0, WICHTIG: 1, HINWEIS: 2}
    raete.sort(key=lambda r: reihenfolge.get(r.stufe, 9))
    return raete


def text(u):
    """Die Übersicht als kurzer Block."""
    if not u:
        return ""
    z = []
    if u.get("anzahl"):
        s = "%d Aufnahmen" % u["anzahl"]
        if u.get("enthaltene_subs"):
            s += " (fertige Stapel aus %d Einzelaufnahmen)" % u["enthaltene_subs"]
        if u.get("gesamt_minuten"):
            s += ", %.0f Minuten gesamt" % u["gesamt_minuten"]
        z.append("Serie           " + s)
    if u.get("kameras"):
        z.append("Kamera          " + ", ".join(sorted(u["kameras"])))
    if u.get("filter"):
        z.append("Filter          " + ", ".join(sorted(u["filter"])))
    if u.get("belichtungen_s"):
        z.append("Belichtung      " + "/".join("%g s" % t for t in sorted(u["belichtungen_s"])))
    if u.get("temperatur_c"):
        z.append("Temperatur      %.1f bis %.1f Grad" % u["temperatur_c"])
    if u.get("verstaerkungen"):
        z.append("Verstaerkung    " + ", ".join("Gain %g (%dx)" % (g, n) for g, n
                                                in sorted(u["verstaerkungen"].items())))
    if u.get("bildgroessen"):
        z.append("Bildgroesse     " + ", ".join("%dx%d" % g for g in sorted(u["bildgroessen"])))
    if u.get("richtungsspanne_grad") is not None:
        z.append("Himmelsfeld     Ausrichtungen bis %.2f Grad auseinander"
                 % u["richtungsspanne_grad"])
    if u.get("zeitraum_minuten") is not None:
        z.append("Zeitraum        %.0f Minuten von der ersten bis zur letzten Aufnahme"
                 % u["zeitraum_minuten"])
    if u.get("naechte"):
        n = u["naechte"]
        z.append("Naechte         %s" % (n[0] if len(n) == 1 else "%s bis %s (%d)"
                                         % (n[0], n[-1], len(n))))
    return "\n".join(z)
