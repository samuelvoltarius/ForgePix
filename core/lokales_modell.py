#!/usr/bin/env python3
"""
core/lokales_modell.py — Stufe 4: ein Sprachmodell auf dem eigenen Rechner, ohne Internet.

Stufe 3 (`core/berater.py`) redet über eine OpenAI-kompatible Schnittstelle mit einem Modell.
**Woher dieses Modell kommt, ist ihr egal** — und genau das ist die Lösung für Stufe 4.

**Warum ForgePix kein Modell mitliefert.** Das Programm ist rund 30 MB groß. Ein brauchbares
kleines Sprachmodell liegt bei 300 bis 900 MB, also beim Zehn- bis Dreißigfachen. Jeder, der
ForgePix zum Stapeln von Bildern herunterlädt, zahlte das mit — auch die grosse Mehrheit, die
nie einen freien Wunsch eintippt. Ein Modell ist etwas, das man **anbietet**, nicht etwas, das
man jemandem in den Download legt.

**Warum hier nichts nachgebaut wird.** Auf dem Rechner läuft entweder schon ein Server oder
nicht. Ollama, llama.cpp (`llama-server`), LM Studio und vLLM sprechen alle dieselbe
OpenAI-kompatible Sprache und horchen auf bekannten Ports. Dieses Modul sucht sie, statt eine
eigene Inferenz mitzuschleppen — im Sinne der Projektregel, so wenig fremde Software wie möglich
zu verlangen. Gefunden wird auch, was der Benutzer aus ganz anderen Gründen installiert hat.

**Herunterladen passiert NUR auf ausdrückliche Anforderung.** `modell_holen` lädt Daten aus dem
Internet und wird nie von selbst aufgerufen — nicht beim Start, nicht beim Suchen, nicht als
stiller Rückfall.

Was hier NICHT behauptet wird: dass ein 0,5-B-Modell die Aufgabe gut löst. Das ist ungemessen.
Der Berater prüft ohnehin jeden Vorschlag gegen seinen Katalog, ein schwaches Modell kann also
nichts kaputtmachen — es kann nur nichts Brauchbares beitragen. Ob es das tut, muss gemessen
werden, sobald ein Modell da ist.
"""
import json
import os
import shutil
import subprocess
import sys

from constants import log_print

# Die üblichen Verdächtigen. Reihenfolge = Suchreihenfolge.
#   (Name, Basis-URL, wie man es bekommt)
BEKANNTE_SERVER = [
    ("Ollama", "http://localhost:11434/v1", "ollama.com"),
    ("llama.cpp (llama-server)", "http://localhost:8080/v1", "github.com/ggml-org/llama.cpp"),
    ("LM Studio", "http://localhost:1234/v1", "lmstudio.ai"),
    ("vLLM", "http://localhost:8000/v1", "docs.vllm.ai"),
]

# Kleine Modelle, die für die Aufgabe des Beraters in Frage kommen: aus einem Messbericht und
# einem Wunsch Schalter aus einem festen Katalog wählen. Das ist eine Textaufgabe, keine
# Bildaufgabe — es braucht KEIN Vision-Modell.
#
# Die Größen stammen aus der Ollama-Bibliothek und sind der Download, nicht der Arbeitsspeicher.
# Ob eines davon die Aufgabe gut löst, ist NICHT gemessen; die Liste ist ein Vorschlag, kein
# Versprechen.
EMPFOHLEN = [
    ("qwen2.5:1.5b-instruct", "~1,0 GB", "kleinstes, das noch verlässlich JSON liefert"),
    ("qwen2.5:3b-instruct", "~1,9 GB", "spürbar besser bei Begründungen"),
    ("llama3.2:3b", "~2,0 GB", "Alternative, gleiche Größenordnung"),
]


def _antwortet(url, timeout=2.0):
    """Nennt ein Server unter dieser Adresse Modelle? Gibt die Liste oder None."""
    try:
        import requests
    except ImportError:
        return None
    try:
        r = requests.get("%s/models" % url.rstrip("/"), timeout=timeout)
        if r.status_code != 200:
            return None
        ids = [str(m.get("id")) for m in r.json().get("data", []) if m.get("id")]
        return ids
    except Exception:
        return None


def server_suchen(zusaetzlich=None, log=log_print, timeout=2.0):
    """Einen laufenden, OpenAI-kompatiblen Server auf diesem Rechner finden.

    Returns:
        dict mit `name`, `url`, `modelle` — oder None, wenn keiner antwortet.

    Bewusst kurze Zeitüberschreitung: das hier läuft womöglich beim Öffnen eines Dialogs, und
    eine Oberfläche, die zwei Sekunden je Port steht, ist kaputt.
    """
    kandidaten = list(BEKANNTE_SERVER)
    if zusaetzlich:
        kandidaten.insert(0, ("Eigene Adresse", zusaetzlich, ""))
    for name, url, _woher in kandidaten:
        ids = _antwortet(url, timeout=timeout)
        if ids is not None:
            log("  Lokale KI gefunden: %s unter %s (%d Modell(e))" % (name, url, len(ids)))
            return {"name": name, "url": url, "modelle": ids}
    return None


def ollama_pfad():
    """Der Pfad zum ollama-Programm, oder None. Sucht auch dort, wo es sich unter Windows
    installiert, ohne im PATH zu landen."""
    p = shutil.which("ollama")
    if p:
        return p
    kandidaten = []
    if sys.platform == "win32":
        for umgebung in ("LOCALAPPDATA", "PROGRAMFILES"):
            wurzel = os.environ.get(umgebung)
            if wurzel:
                kandidaten.append(os.path.join(wurzel, "Programs", "Ollama", "ollama.exe"))
                kandidaten.append(os.path.join(wurzel, "Ollama", "ollama.exe"))
    else:
        kandidaten += ["/usr/local/bin/ollama", "/usr/bin/ollama",
                       os.path.expanduser("~/.local/bin/ollama")]
    for k in kandidaten:
        if os.path.isfile(k):
            return k
    return None


def ollama_starten(log=log_print, timeout=20):
    """`ollama serve` starten, falls installiert und noch nicht laufend.

    Returns:
        Die Basis-URL, wenn danach ein Server antwortet, sonst None.
    """
    ids = _antwortet(BEKANNTE_SERVER[0][1])
    if ids is not None:
        return BEKANNTE_SERVER[0][1]
    exe = ollama_pfad()
    if not exe:
        return None
    try:
        # Ohne Fenster und ohne an unserem Ein-/Ausgang zu haengen: der Server soll den Lauf
        # ueberleben und ihn nicht blockieren.
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                  "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([exe, "serve"], **kwargs)
    except Exception as e:
        log("  Ollama liess sich nicht starten: %s" % e)
        return None
    import time
    frist = time.time() + timeout
    while time.time() < frist:
        if _antwortet(BEKANNTE_SERVER[0][1], timeout=1.0) is not None:
            log("  Ollama gestartet.")
            return BEKANNTE_SERVER[0][1]
        time.sleep(0.5)
    log("  Ollama gestartet, antwortet aber nicht innerhalb von %d s." % timeout)
    return None


def ollama_modelle(log=log_print):
    """Welche Modelle liegen schon lokal? Liste von (name, groesse_bytes)."""
    exe = ollama_pfad()
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "list"], capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace")
    except Exception as e:
        log("  `ollama list` fehlgeschlagen: %s" % e)
        return []
    aus = []
    for zeile in (r.stdout or "").splitlines()[1:]:      # Kopfzeile ueberspringen
        teile = zeile.split()
        if len(teile) >= 3:
            aus.append((teile[0], " ".join(teile[2:4])))
    return aus


def modell_holen(name, fortschritt=None, log=log_print, timeout=3600):
    """Ein Modell herunterladen (`ollama pull`).

    **Laedt Daten aus dem Internet.** Wird nur auf ausdrueckliche Anforderung aufgerufen — nie
    beim Start, nie beim Suchen, nie als stiller Rueckfall.

    Args:
        fortschritt: optionale Funktion, die jede Ausgabezeile bekommt.

    Returns:
        (ok, meldung)
    """
    exe = ollama_pfad()
    if not exe:
        return False, ("Ollama ist auf diesem Rechner nicht installiert. Ohne einen lokalen "
                       "Server kann ForgePix kein Modell holen — siehe ollama.com.")
    try:
        p = subprocess.Popen([exe, "pull", name], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                             errors="replace", bufsize=1)
    except Exception as e:
        return False, "Der Download liess sich nicht starten: %s" % e
    letzte = ""
    try:
        for zeile in p.stdout:
            letzte = zeile.strip()
            if fortschritt:
                fortschritt(letzte)
        p.wait(timeout=timeout)
    except Exception as e:
        p.kill()
        return False, "Der Download brach ab: %s" % e
    if p.returncode != 0:
        return False, "Der Download schlug fehl: %s" % (letzte or "kein Grund genannt")
    return True, "%s ist geladen." % name


def bericht(log=log_print):
    """Was ist auf diesem Rechner an lokaler KI vorhanden? Als lesbarer Block.

    Sagt ausdruecklich, was FEHLT und wie man es bekaeme — eine Auskunft "keine KI gefunden"
    ohne den naechsten Schritt hilft niemandem weiter.
    """
    z = []
    gefunden = server_suchen(log=lambda *a: None)
    if gefunden:
        z.append("Lokale KI laeuft: %s unter %s" % (gefunden["name"], gefunden["url"]))
        if gefunden["modelle"]:
            z.append("  Modelle: " + ", ".join(gefunden["modelle"][:6]))
        else:
            z.append("  Der Server nennt kein Modell — es muss noch eines geladen werden.")
        return "\n".join(z)

    z.append("Es laeuft kein lokaler KI-Server.")
    exe = ollama_pfad()
    if exe:
        z.append("  Ollama ist installiert (%s), aber nicht gestartet." % exe)
        vorhanden = ollama_modelle(log=lambda *a: None)
        if vorhanden:
            z.append("  Bereits geladen: " + ", ".join("%s (%s)" % m for m in vorhanden[:6]))
        else:
            z.append("  Es ist noch kein Modell geladen.")
    else:
        z.append("  Ollama ist nicht installiert (ollama.com). Auch llama.cpp, LM Studio oder "
                 "vLLM gehen — ForgePix findet jeden davon von selbst.")
    z.append("  Vorschlaege: " + "; ".join("%s (%s, %s)" % e for e in EMPFOHLEN))
    z.append("  Die Bearbeitung laeuft ohne KI vollstaendig weiter. Das Sprachmodell "
             "uebersetzt nur freie Wuensche in Einstellungen.")
    return "\n".join(z)


if __name__ == "__main__":
    from constants import force_utf8_stdio
    force_utf8_stdio()
    print(bericht())
