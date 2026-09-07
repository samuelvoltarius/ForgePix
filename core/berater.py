#!/usr/bin/env python3
"""
core/berater.py — Stufe 3: das Sprachmodell als Übersetzer, nicht als Entscheider.

Die Arbeitsteilung im Aufbau ist bewusst so geschnitten:

    Stufe 1  `messbericht.py`   misst.        Zahlen, keine Meinung.
    Stufe 2  `regeln.py`        entscheidet.  Deterministisch, prüfbar, offline.
    Stufe 3  hier               formuliert.   Freie Wünsche in Einstellungen übersetzen.

Ein Sprachmodell kann etwas, das ein Regelwerk nicht kann: einen Satz wie „mach den Nebel
wärmer, aber die Sterne dürfen nicht ausfressen" in Schalter übersetzen. Es kann aber auch etwas,
das ein Regelwerk nie tut: **überzeugend danebenliegen**. Beides wurde am tatsächlich laufenden
Modell gemessen (Ornith-1.5-35B über eine OpenAI-kompatible Schnittstelle), und die Messung ist
der Grund für jede Vorsichtsmaßnahme hier:

* Auf einen unmöglichen Wunsch („mach aus 4 Aufnahmen 200 und entferne den Mond") antwortete es
  mit einer **leeren Liste** und sagte, dass es nicht geht. Vorbildlich.
* Auf einen gefährlichen Wunsch („Sättigung auf Maximum, egal was kaputtgeht") gehorchte es
  **bis zum Anschlag**. Es widerspricht nicht. Also müssen die Grenzen hier stehen und nicht im
  Prompt.
* Auf einen Wunsch außerhalb des Katalogs („in Schwarzweiß exportieren") **erfand es eine
  Deutung**: „Schwarzweiss erreicht durch Sättigung auf 0.5". Das ist einfach falsch — 0,5 ist
  nicht farblos. Der Satz liest sich aber wie eine Begründung.

Mit Messbericht und Regelwerk als Kontext wird es deutlich besser — der erfundene
Schwarzweiss-Umweg verschwand, und auf „dreh alles auf Maximum" widersprach es sogar. Ein
Fehler blieb trotzdem: im selben Lauf schrieb es „die Sterne sind bereits rund
(Nachfuehrungsproblem)", waehrend der Bericht direkt darueber eine Rundheit von 1,63 ausweist
und das Regelwerk sie ausdruecklich „deutlich verzogen" nennt. Es widersprach also einer Zahl,
die es woertlich vor sich hatte — fluessig formuliert und mit Fachbegriff. Genau deshalb steht
ueber jeder Modellantwort, dass sie nicht gemessen ist.

Daraus folgen drei Regeln, die dieses Modul durchsetzt:

1. **Nur Schalter aus dem Katalog.** Alles andere wird verworfen UND benannt, nie still
   geschluckt.
2. **Zahlen werden gegen die Spanne geprüft**, nicht gegen das Vertrauen ins Modell.
3. **Die Begründung des Modells ist als solche gekennzeichnet.** Sie steht nie neben einer
   Messung, ohne dass dabeisteht, dass sie keine ist.

Ohne erreichbaren Endpunkt fällt alles auf Stufe 2 zurück. Das Regelwerk bleibt die Autorität;
das Modell darf ergänzen, nicht überstimmen.
"""
import json
import re

from constants import log_print

# Der Katalog ist die EINZIGE Quelle dafür, was das Modell vorschlagen darf. Jeder Eintrag:
#   schalter -> (beschreibung, spanne oder None)
# `spanne` ist (min, max) für Schalter mit Zahl; None für reine Schalter.
#
# Warum hier und nicht im Prompt: was im Prompt steht, ist eine Bitte. Was hier steht, ist eine
# Bedingung. Am Modell gemessen ist der Unterschied nicht theoretisch — es hält sich an den
# Katalog, solange die Frage einfach ist, und erfindet etwas, sobald sie es nicht ist.
KATALOG = {
    "--bg-extract": ("Helligkeitsverlauf im Hintergrund entfernen", None),
    "--astro-synthstar": ("verzogene Sterne durch runde Profile ersetzen "
                          "(danach fuer Photometrie unbrauchbar)", None),
    "--astro-unclip-stars": ("ausgefressene Sternkerne aus den Flanken einfaerben", None),
    "--astro-starless-stretch": ("sternlos strecken: Sterne raus, Nebel strecken, "
                                 "Sterne linear zurueck", (0.0, 1.0)),
    "--astro-saturation": ("Farbsaettigung", (0.5, 2.0)),
    "--astro-bright": ("Helligkeit der Streckung", (0.1, 1.0)),
    "--astro-color": ("Farbstaerke der Streckung", (0.0, 2.0)),
    "--astro-denoise": ("Entrauschen", (0.0, 1.0)),
    "--astro-deconv": ("Dekonvolution (schaerfen anhand der gemessenen Sternform)", None),
    "--bin": ("Pixel zusammenfassen (verbessert den Rauschabstand)", (1, 3)),
}


def katalog_text():
    """Der Katalog als Prompt-Abschnitt."""
    z = []
    for s, (was, spanne) in KATALOG.items():
        if spanne is None:
            z.append("%-30s %s" % (s, was))
        else:
            z.append("%-30s %s (%g bis %g)" % (s + " ZAHL", was, spanne[0], spanne[1]))
    return "\n".join(z)


def _json_aus(text):
    """Das JSON aus der Antwort holen. Das Modell packt es mal in ```json-Zaeune, mal nicht."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    if not t.startswith("{"):
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return None
        t = m.group(0)
    try:
        return json.loads(t)
    except (ValueError, TypeError):
        return None


def pruefen(einstellungen):
    """Was das Modell vorschlaegt gegen den Katalog pruefen.

    Returns:
        (gueltig, verworfen) — beides Listen von Zeichenketten. `verworfen` enthaelt den
        Grund, damit dem Benutzer gesagt werden kann, was NICHT uebernommen wurde. Ein still
        verschluckter Vorschlag ist schlimmer als ein abgelehnter: niemand merkt, dass etwas
        fehlt.
    """
    gueltig, verworfen = [], []
    for eintrag in (einstellungen or []):
        teile = str(eintrag).strip().split()
        if not teile:
            continue
        schalter = teile[0]
        if schalter not in KATALOG:
            verworfen.append("%s (nicht im Katalog)" % eintrag)
            continue
        _was, spanne = KATALOG[schalter]
        if spanne is None:
            if len(teile) > 1:
                verworfen.append("%s (dieser Schalter nimmt keinen Wert)" % eintrag)
                continue
            gueltig.append(schalter)
            continue
        if len(teile) != 2:
            verworfen.append("%s (Wert fehlt oder ist mehrteilig)" % eintrag)
            continue
        try:
            wert = float(teile[1])
        except ValueError:
            verworfen.append("%s (Wert ist keine Zahl)" % eintrag)
            continue
        if not (spanne[0] <= wert <= spanne[1]):
            # NICHT stillschweigend beschneiden. Wer 5.0 vorschlaegt, wo 2.0 das Maximum ist,
            # hat den Schalter nicht verstanden — dann ist auch der Rest seines Vorschlags
            # fraglich, und das soll sichtbar bleiben.
            verworfen.append("%s (ausserhalb %g bis %g)" % (eintrag, spanne[0], spanne[1]))
            continue
        gueltig.append("%s %g" % (schalter, wert))
    return gueltig, verworfen


def _prompt(bericht_text, rat_text, wunsch):
    return (
        "Du beraetst bei der Bearbeitung eines Astrofotos. Die Messung ist bereits erfolgt. "
        "Du sollst NICHT rechnen, sondern aus den Zahlen und dem Wunsch Einstellungen waehlen.\n\n"
        "MESSBERICHT:\n%s\n\n"
        "WAS DAS REGELWERK BEREITS SAGT:\n%s\n\n"
        "WUNSCH DES NUTZERS:\n%s\n\n"
        "ERLAUBTE EINSTELLUNGEN (nur diese, nichts anderes):\n%s\n\n"
        "Laesst sich der Wunsch damit nicht erfuellen, gib eine LEERE Liste zurueck und sage "
        "warum. Erfinde keine Umwege.\n"
        "Antworte NUR mit JSON:\n"
        '{"einstellungen": ["--schalter wert", ...], "begruendung": "zwei Saetze auf Deutsch"}'
        % (bericht_text, rat_text, wunsch, katalog_text()))


def fragen(bericht_text, rat_text, wunsch, endpoint, model="qwen", api_key=None,
           timeout=240, log=log_print):
    """Das Sprachmodell um Einstellungen zu einem freien Wunsch bitten.

    Returns:
        dict mit `einstellungen` (geprueft), `verworfen`, `begruendung` und `quelle`.
        `quelle` ist "modell" oder "keine" — daran ist erkennbar, ob ueberhaupt gefragt wurde.
        Bei jedem Fehler wird `einstellungen` leer und der Grund steht in `begruendung`; die
        Bearbeitung laeuft ohne Modell weiter.
    """
    leer = {"einstellungen": [], "verworfen": [], "begruendung": "", "quelle": "keine"}
    if not endpoint or not (wunsch or "").strip():
        return leer
    try:
        from focus_cull_stack import _vlm_chat
    except Exception as e:
        leer["begruendung"] = "Kein Zugang zum Modell: %s" % e
        return leer
    try:
        antwort = _vlm_chat(endpoint, model,
                            [{"role": "user",
                              "content": _prompt(bericht_text, rat_text, wunsch)}],
                            max_tokens=700, api_key=api_key, timeout=timeout)
    except Exception as e:
        log("    Sprachmodell nicht erreichbar (%s) — es bleibt beim Regelwerk." % e)
        leer["begruendung"] = "Sprachmodell nicht erreichbar: %s" % e
        return leer

    daten = _json_aus(antwort)
    if not isinstance(daten, dict):
        log("    Antwort des Sprachmodells war kein JSON — verworfen.")
        leer["begruendung"] = "Antwort war kein JSON: %s" % (antwort or "")[:200]
        return leer

    gueltig, verworfen = pruefen(daten.get("einstellungen"))
    return {"einstellungen": gueltig, "verworfen": verworfen,
            "begruendung": str(daten.get("begruendung", "")).strip(), "quelle": "modell"}


def text(ergebnis):
    """Das Ergebnis als lesbarer Block — mit deutlicher Herkunft.

    Die Begruendung des Modells steht NIE ohne Kennzeichnung neben einer Messung. Gemessen: es
    begruendete eine Saettigung von 0,5 mit „Schwarzweiss erreicht" — falsch, aber flüssig
    formuliert. Wer nicht weiss, dass da ein Sprachmodell schreibt, haelt es fuer einen Befund.
    """
    if ergebnis.get("quelle") != "modell":
        return ""
    z = ["Vorschlag des Sprachmodells (formuliert, NICHT gemessen):"]
    if ergebnis["einstellungen"]:
        z.append("  " + " ".join(ergebnis["einstellungen"]))
    else:
        z.append("  keine Einstellung — der Wunsch laesst sich damit nicht erfuellen.")
    if ergebnis.get("begruendung"):
        z.append("  " + ergebnis["begruendung"])
    if ergebnis.get("verworfen"):
        z.append("  Verworfen: " + "; ".join(ergebnis["verworfen"]))
    return "\n".join(z)
