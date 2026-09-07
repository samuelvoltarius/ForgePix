#!/usr/bin/env python3
"""
core/regeln.py — aus dem Messbericht wird ein Rat.

Stufe 2 des Aufbaus. Der Bericht (`core/messbericht.py`) sagt, wie das Bild IST; hier steht,
was daraus folgt. Bewusst als Regelwerk und nicht als Modell:

* **Deterministisch.** Dieselben Zahlen ergeben immer denselben Rat. Ein Modell, das mal so
  und mal anders antwortet, ist bei einer Empfehlung, der jemand folgt, das falsche Werkzeug.
* **Prüfbar.** Jede Regel ist ein Test. Ein Modell lässt sich nicht auf „hat es hier recht?"
  festnageln.
* **Läuft überall.** Millisekunden, kein Speicherbedarf, keine Installation.

Was Regeln NICHT können, bleibt dem Sprachmodell überlassen: freie Formulierungen („mach den
Nebel wärmer"), Ausdrücke schreiben, ein Vorschaubild beurteilen. Das ist die Arbeitsteilung —
gerechnet wird in Python, formuliert wird im Modell, entschieden wird hier.

**Jede Regel nennt ihren Grund und ihre Herkunft.** Wo eine Schwelle aus einer Messung dieser
Codebasis stammt, steht die Messung dabei. Wo sie Konvention ist, steht das auch. Eine Zahl
ohne Begründung ist in einem Regelwerk wertlos — niemand kann sie später prüfen oder ändern.
"""
import collections

from constants import log_print

# Dringlichkeit: was zuerst gelesen werden soll.
KRITISCH = "kritisch"     # das Ergebnis ist so nicht zu retten
WICHTIG = "wichtig"       # deutlich verbesserbar
HINWEIS = "hinweis"       # zur Kenntnis

Rat = collections.namedtuple("Rat", "stufe titel grund massnahme einstellung")


def _w(bericht, *pfad, standard=None):
    """Wert aus dem verschachtelten Bericht holen; None bleibt None."""
    k = bericht
    for p in pfad:
        if not isinstance(k, dict) or p not in k:
            return standard
        k = k[p]
    return standard if k is None else k


def pruefen(bericht):
    """Den Messbericht durchgehen und eine Liste von `Rat` zurückgeben.

    Fehlende Werte fuehren NICHT zu einem Rat. Eine Regel, die auf `None` anspringt, erfindet
    einen Befund aus einer Nicht-Messung — genau davor schuetzt der Bericht mit seinem
    konsequenten `None`.
    """
    raete = []

    # --- Signal ------------------------------------------------------------------
    snr = _w(bericht, "signal_zu_rauschen")
    if snr is not None and snr < 1.0:
        raete.append(Rat(
            KRITISCH, "Signal schwaecher als das Rauschen",
            "Das Objekt hebt sich um weniger als eine Rauscheinheit vom Himmel ab (%.2f). "
            "Aus so einem Stapel laesst sich keine Farbe herausarbeiten — jede Saettigung "
            "faerbt dann das Rauschen ein." % snr,
            "Mehr Gesamtbelichtung. Regler drehen hilft hier nicht.",
            None))
    elif snr is not None and snr < 5.0:
        raete.append(Rat(
            WICHTIG, "Wenig Signal",
            "Signal-Rausch-Verhaeltnis %.1f. Streckung und Saettigung heben ab hier das "
            "Rauschen sichtbar mit." % snr,
            "Mehr Aufnahmen sammeln; vorsichtig strecken.",
            None))

    # --- Hintergrund -------------------------------------------------------------
    grad = _w(bericht, "himmel", "gradient_prozent")
    if grad is not None and grad > 10.0:
        raete.append(Rat(
            WICHTIG, "Starker Helligkeitsverlauf im Hintergrund",
            "Der Himmel schwankt um %.0f %% ueber die Bildflaeche. Ursache ist meist "
            "Lichtverschmutzung, Mond oder ein fehlendes Flat. Beim Strecken wird daraus ein "
            "sichtbarer Verlauf: die Kurve ist nahe Null fast senkrecht und blaest kleine "
            "Unterschiede auf — an echten Daten stieg ein flacher Stack (0,0 %%) im fertigen "
            "JPG auf 35,6 %%." % grad,
            "Hintergrund-Entfernung einschalten.",
            "--bg-extract"))
    elif grad is not None and grad > 3.0:
        raete.append(Rat(
            HINWEIS, "Leichter Helligkeitsverlauf",
            "Der Himmel schwankt um %.0f %% ueber die Flaeche." % grad,
            "Hintergrund-Entfernung ist sinnvoll.",
            "--bg-extract"))

    # --- Farbe -------------------------------------------------------------------
    if _w(bericht, "farbe", "passt") is False:
        raete.append(Rat(
            WICHTIG, "Farbverhalten passt nicht zur Kamera",
            _w(bericht, "farbe", "urteil", standard=""),
            "Flat pruefen und den eingestellten Aufnahme-Filter mit dem tatsaechlichen "
            "vergleichen.",
            None))

    # --- Ausgebrannte Sterne -----------------------------------------------------
    clip = _w(bericht, "bild", "ausgebrannt_prozent")
    if clip is not None and clip > 0.5:
        raete.append(Rat(
            WICHTIG, "Viele ausgebrannte Pixel",
            "%.2f %% der Pixel stehen am oberen Anschlag. Dort ist die Sternfarbe verloren, "
            "und Photometrie waere unbrauchbar." % clip,
            "Sternlose Streckung nutzen: Sterne raus, Nebel strecken, Sterne linear zurueck. "
            "An echten Daten sank der Anteil damit von 0,573 %% auf 0,041 %% bei "
            "gleichzeitig 22 %% mehr Nebel.",
            "--astro-starless-stretch 0.35"))
    elif clip is not None and clip > 0.1:
        raete.append(Rat(
            HINWEIS, "Einzelne ausgebrannte Sternkerne",
            "%.2f %% der Pixel am oberen Anschlag." % clip,
            "Ausgefressene Kerne einfaerben holt die Farbe aus den Flanken zurueck.",
            "--astro-unclip-stars"))

    # --- Sternform ---------------------------------------------------------------
    rund = _w(bericht, "sterne", "rundheit")
    if rund is not None and rund > 1.6:
        raete.append(Rat(
            WICHTIG, "Sterne deutlich verzogen",
            "Achsenverhaeltnis %.2f. Ursache ist Nachfuehrung, Verkippung oder Koma — "
            "rechnerisch entzerren laesst sich das nicht." % rund,
            "Sternformen neu setzen (runde Profile mit gleichem Fluss). An echten Daten sank "
            "die Verformung von 0,79 auf 0,39, also auf den Wert derselben Aufnahme ohne "
            "Fehler. ACHTUNG: danach fuer Photometrie unbrauchbar.",
            "--astro-synthstar"))
    if _w(bericht, "sterne", "spur") is True:
        raete.append(Rat(
            WICHTIG, "Strichspur erkannt",
            "In der untersuchten Aufnahme wurde eine Spur gefunden (Satellit oder Flugzeug).",
            "Sigma-Clipping verwirft so etwas beim Stapeln — mit mindestens 5 Aufnahmen.",
            None))

    # --- Abtastung ---------------------------------------------------------------
    sampling = _w(bericht, "ausruestung", "sampling")
    if sampling == "unterabgetastet":
        raete.append(Rat(
            HINWEIS, "Unterabgetastet",
            "Die Sterne sind schmaler, als das Pixelraster aufloesen kann. Drizzle holt hier "
            "echte Aufloesung zurueck — aber NUR bei gedithertem Material.",
            "Dithering pruefen, dann Drizzle.",
            "--astro-drizzle 2 --astro-drizzle-true"))
    elif sampling == "ueberabgetastet":
        raete.append(Rat(
            HINWEIS, "Ueberabgetastet",
            "Die Sterne sind deutlich breiter als noetig. Binning verbessert den "
            "Rauschabstand, ohne Detail zu verlieren.",
            "2x-Binning erwaegen.",
            "--bin 2"))

    # --- Serie -------------------------------------------------------------------
    anzahl = _w(bericht, "serie", "anzahl")
    if anzahl is not None and anzahl < 10:
        raete.append(Rat(
            WICHTIG, "Wenige Aufnahmen",
            "%d Aufnahmen. Das Rauschen sinkt mit der Wurzel der Anzahl — von 8 auf 32 "
            "Aufnahmen halbiert es sich." % anzahl,
            "Mehr sammeln. Ausreisser-Verwurf braucht ausserdem mindestens 5 Aufnahmen.",
            None))
    if _w(bericht, "serie", "gemischt") is True:
        zeiten = _w(bericht, "serie", "zeiten_s", standard=[])
        raete.append(Rat(
            HINWEIS, "Gemischte Belichtungszeiten",
            "In der Serie stecken %s. Ohne Umrechnung haelt das Sigma-Clipping die kurzen "
            "Aufnahmen fuer Ausreisser und verschwendet sein Verwurfsbudget auf sie."
            % "/".join("%g s" % t for t in zeiten),
            "Wird automatisch umgerechnet und gewichtet — gemessen sank der Rest einer "
            "Satellitenspur dadurch von 0,042 auf 0,016.",
            None))

    reihenfolge = {KRITISCH: 0, WICHTIG: 1, HINWEIS: 2}
    raete.sort(key=lambda r: reihenfolge.get(r.stufe, 9))
    return raete


def text(raete, bericht=None):
    """Die Raete als lesbaren Block. Leer heisst: nichts zu beanstanden."""
    if not raete:
        return "Keine Auffaelligkeiten — die gemessenen Werte geben keinen Anlass zu einem Rat."
    zeichen = {KRITISCH: "!!", WICHTIG: "! ", HINWEIS: "  "}
    z = []
    for r in raete:
        z.append("%s %s" % (zeichen.get(r.stufe, "  "), r.titel))
        z.append("     %s" % r.grund)
        z.append("     -> %s" % r.massnahme)
        if r.einstellung:
            z.append("        %s" % r.einstellung)
        z.append("")
    return "\n".join(z).rstrip()


def einstellungen(raete):
    """Nur die konkreten Schalter, in der Reihenfolge der Dringlichkeit.

    Damit laesst sich der DAU-Modus fuettern: was das Regelwerk empfiehlt, kann die
    Oberflaeche vorschlagen oder gleich setzen.
    """
    raus = []
    for r in raete:
        if r.einstellung and r.einstellung not in raus:
            raus.append(r.einstellung)
    return raus
