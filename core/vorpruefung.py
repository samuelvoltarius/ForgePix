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
import os

from constants import log_print
from regeln import HINWEIS, KRITISCH, Rat, WICHTIG

# Kameras auf azimutaler Montierung: das Bildfeld dreht sich im Lauf der Nacht. Erkannt wird am
# Kameranamen aus INSTRUME, weil die Montierung selbst nicht im Header steht.
AZIMUTAL = ("seestar", "dwarf", "vespera", "stellina", "hestia", "origin")

_FELDER = ("INSTRUME", "EXPTIME", "EXPOSURE", "FILTER", "CCD-TEMP", "DATE-OBS", "IMAGETYP",
           "FRAME", "GAIN", "XPIXSZ", "FOCALLEN")


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
    aus = []
    for p in stichprobe:
        try:
            h = fits.getheader(p)
        except Exception:
            continue
        aus.append({k: h[k] for k in _FELDER if k in h})
    if len(stichprobe) < len(fits_pfade):
        log("    Vorpruefung: %d von %d Aufnahmen als Stichprobe gelesen"
            % (len(stichprobe), len(fits_pfade)))
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
    temperaturen, naechte = [], collections.Counter()
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
        c = _zahl(h.get("CCD-TEMP"))
        if c is not None:
            temperaturen.append(c)
        d = str(h.get("DATE-OBS", ""))[:10]
        if d:
            naechte[d] += 1
    return {
        "anzahl": int(gesamt if gesamt is not None else len(koepfe)),
        "gelesen": len(koepfe),
        "kameras": dict(kameras),
        "filter": dict(filter_),
        "belichtungen_s": dict(zeiten),
        "temperatur_c": ((min(temperaturen), max(temperaturen)) if temperaturen else None),
        "naechte": sorted(naechte),
        "gesamt_minuten": (sum(t * n for t, n in zeiten.items()) / 60.0
                           * (float(gesamt) / max(1, len(koepfe)) if gesamt else 1.0)
                           if zeiten else None),
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
    if u.get("naechte"):
        n = u["naechte"]
        z.append("Naechte         %s" % (n[0] if len(n) == 1 else "%s bis %s (%d)"
                                         % (n[0], n[-1], len(n))))
    return "\n".join(z)
