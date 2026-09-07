# Arbeitsanweisung für Claude in diesem Projekt

ForgePix ist ein Bildbearbeitungswerkzeug für Astrofotografie und Fokus-Stacking.
Python 3.14, PySide6, OpenCV, numpy. MIT-Lizenz, öffentliches Repository.

## Das Wichtigste zuerst

**Ein Befund ist erst echt, wenn du ihn ausgeführt hast. Code ist kein Beweis.**

Dieses Projekt hat eine lange Reihe von Fehlern hervorgebracht, die alle dieselbe Form hatten:
*es lief durch, es sah plausibel aus, und es war falsch.* Kein Absturz, keine Warnung, keine rote
Zeile. Ein paar davon, damit die Form erkennbar wird:

* Die Ausrichtung des Trainingsmaterials konnte nur Verschiebung, keine Drehung. An den
  Seestar-Serien (azimutale Montierung, also Bildfeldrotation) warf sie **98 % der Aufnahmen weg**
  und verschmierte den Rest. Das Protokoll meldete „239 Subs → 24 Kacheln" und las sich wie ein
  Erfolg.
* Das Regelwerk empfahl `--astro-bg-extract`. Diese Option gibt es nicht, sie heißt
  `--bg-extract`. Es war die am häufigsten ausgelöste Regel — mit gemessener Begründung und
  allem.
* Die Oberfläche schickte `gpt-4o-mini` an lokale Server, weil das Modellfeld leer war. 404, und
  die KI-Funktion tat kommentarlos nichts.
* Ein `MagicMock` auf einer QObject-Klasse ließ `unittest discover` mitten im Lauf abstürzen —
  **ohne Zusammenfassung und ohne das Wort FAILED**. Wer nur danach schaute, hielt den Lauf für
  bestanden. 27 von 692 Tests waren gelaufen.

Am 07.09.2026 kamen an einem Tag sieben weitere Formen desselben Musters dazu — alle gefunden,
indem echte Daten durch die tatsächlichen Programmwege geschickt wurden, keine einzige durch
Lesen des Codes:

| Was | Wirkung | Wie es sich meldete |
|---|---|---|
| Zwei Kameras in einem Ordner | Stapel aus zwei Sensoren, matschige Sterne | gar nicht |
| Zwei Ziele in einem Ordner | 76 % der Aufnahmen „nicht ausrichtbar" | eine Zeile im Protokoll |
| Gebinnt + ungebinnt gemischt | 57 von 59 Aufnahmen weg | dieselbe Zeile |
| Platzhalter (FWHM 99, Exz. 9) im Median | die Sub-Bewertung schaltete sich selbst ab | gar nicht |
| `--export`/`--web-jpg` im Astro-Modus | Optionen ohne jede Wirkung | gar nicht |
| `--astro-banding-vertical` | nirgends gelesen | gar nicht |
| Photometrie mit festen Koordinaten | 3 von 20 Messpunkten, Rest womöglich am Nachbarstern | „nicht messbar" |

**Zwei Lehren daraus, die im Code stehen sollten:**

* **Ein Platzhalter für „nicht gemessen" darf nie in eine Statistik.** FWHM 99,0 und
  Exzentrizität 9,0 heißen „keine Sterne gefunden". Im Median machten sie die Schwellen
  unerreichbar, und die schlechten Aufnahmen fielen nur noch zufällig heraus — weil 9,0 über der
  Elongationsgrenze 1,7 liegt.
* **Eine Prüfung darf ihre Toleranz nicht aus der geprüften Größe ableiten.** Meine erste
  Kometen-Bahnprüfung erlaubte einen Rest von `0,2 × Wanderung`. Eine Unsinns-Bahn erzeugt eine
  riesige Wanderung — und hebt damit ihre eigene Schwelle an. 387,5 px Rest gegen 395 px
  Toleranz: durchgelassen.

Zwei mechanische Prüfungen haben sich als Test bewährt und sollten bleiben:
`test_banding_richtung.test_jede_option_wird_irgendwo_gelesen` (jede argparse-Option muss
irgendwo gelesen werden) und `test_regeln.TestSchalterExistieren` (jeder Schalter, den eine Regel
empfiehlt, muss in der `--help` stehen).

Daraus folgt die Arbeitsweise:

1. **Erst messen, dann urteilen.** Zahlen an echten Daten, nicht Plausibilität am Code.
2. **Ist ein Test rot, prüfe zuerst den Test.** Er kann selbst falsch sein.
3. **Nach jeder Aktion mit Nebenwirkung den echten Zustand zurücklesen**, bevor „hat geklappt"
   gesagt wird.
4. **Gegenprobe machen.** Ein Test, der immer grün ist, prüft nichts. Wo eine Prüfung wichtig
   ist, baue absichtlich den Fehler ein und sieh nach, ob sie fällt.
5. **Fehlende Abhängigkeiten sind keine Codefehler.** Erst installieren, dann urteilen.

## Was NICHT passieren darf

* **Kein `git push` ohne ausdrückliche Freigabe.** Das Repository ist öffentlich; Alfred will
  Änderungen erst selbst sehen. Lokale Commits sind erwünscht.
* **Keine stillen Fehler.** Lieber eine Meldung zu viel als ein `except: pass`. Wo etwas
  verworfen wird, muss dastehen, was und warum.
* **Keine erfundenen Standardwerte.** Wenn ein Wert fehlt, ist er `None` — nicht `0.0`. Eine Null
  liest sich wie eine Messung.
* **Nichts still beschneiden.** Wer einen Wert außerhalb der Spanne liefert, hat den Parameter
  nicht verstanden; das soll sichtbar bleiben.

## Ablauf

```bash
python -m unittest discover -s tests -q
```

Die Suite ist die Abnahme (Stand: 848 Tests). Sie muss vor jedem Commit grün sein.
Nach einem Lauf **die Zusammenfassungszeile lesen**, nicht nur nach „FAILED" suchen — siehe oben,
warum.

Ein echter Durchlauf an echten Daten:

```bash
python core/focus_cull_stack.py --input <ordner> --astro
```

Jede Verhaltensänderung kommt in **beide** CHANGELOGs (`CHANGELOG.de.md` und `CHANGELOG.md`),
mit den gemessenen Zahlen. Commit-Nachrichten auf Deutsch, knapp, mit
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Aufbau

```
core/     Rechnende Module. Kein Qt.
ui/       PySide6-Oberfläche. Ruft core über einen Unterprozess auf.
tests/    unittest. Ein Test je Erkenntnis, mit der Begründung im Docstring.
training/ Trainingsmaterial aus eigenen Aufnahmen bauen.
docs/     Untersuchungen, Vergleiche, Bestandsaufnahmen.
```

Wichtige Module:

| Datei | wofür |
|---|---|
| `core/focus_cull_stack.py` | die Pipeline und die Kommandozeile; hier hängt alles zusammen |
| `core/astro.py` | Stapeln, Ausrichten, Strecken, Sterne — der größte Brocken |
| `core/messbericht.py` | **Stufe 1**: misst das lineare Bild. Zahlen, keine Meinung |
| `core/regeln.py` | **Stufe 2**: macht aus den Zahlen einen Rat. Deterministisch, offline |
| `core/berater.py` | **Stufe 3**: freie Wünsche ans Sprachmodell, mit hartem Katalog |
| `core/equipment.py` | Kameras, Teleskope, Filter; Kamera-Erkennung aus dem Header |
| `core/livestack.py` | inkrementelles Stapeln während der Aufnahme |
| `ui/main_window.py` | das Hauptfenster; Anfänger- und Profi-Modus |

## Die drei Stufen

Die Arbeitsteilung ist bewusst so geschnitten und soll so bleiben:

    Stufe 1  messbericht.py   misst.        Zahlen, keine Meinung.
    Stufe 2  regeln.py        entscheidet.  Deterministisch, prüfbar, offline.
    Stufe 3  berater.py       formuliert.   Freie Wünsche in Einstellungen übersetzen.

**Das Regelwerk ist die Autorität, nicht das Sprachmodell.** Ein Modell, das mal so und mal
anders antwortet, ist bei einer Empfehlung, der jemand folgt, das falsche Werkzeug. Am laufenden
Modell gemessen: es widersprach einer Zahl, die wörtlich in seinem Prompt stand — flüssig
formuliert und mit Fachbegriff. Darum steht über jeder Modellantwort, dass sie nicht gemessen
ist.

## Die Oberfläche

Zwei Modi. Im **Anfänger-Modus** soll jemand nur wählen müssen, welche Kamera, welche Filter und
wie das Bild am Schluss aussehen soll. Alles andere entscheidet das Programm — und sagt hinterher
im Vorschlagsbalken, was es gemessen hat und was daraus folgt.

Zwischen Oberfläche und Pipeline laufen **maschinenlesbare Marker** über die Standardausgabe
(`PREVIEW:`, `PHASE:`, `RESULT:`, `RAT:`, `WUNSCH:`). Neue Verständigung bitte auch so und nicht
über deutsche Log-Formulierungen: die ändern sich bei der nächsten Übersetzung.

## Fallen, die schon zugeschnappt sind

* **Heredocs zerlegen `\n` und `\\`.** Beim Schreiben von Python über `python - <<'EOF'` werden
  Zeichenketten mit Escapes zerrissen. Nimm das Write-Werkzeug oder baue das Zeichen über
  `chr(92)` zusammen.
* **`%` in argparse-Hilfetexten** muss `%%` heißen, sonst stirbt `--help` komplett.
* **`patch.object` mit `MagicMock` auf einer QObject-Klasse** stürzt unter PySide6 ab. Nimm eine
  echte leere Funktion (`tests/gui_support.py`).
* **`if punkte:` auf einem numpy-Array** wirft `ValueError` — und hinter einem `except: pass`
  merkt es niemand.
* **Die GUI deutet jede Zeile mit „Vorschlag:" als Begründung.** Wer eine solche Zeile ausgibt,
  landet ungewollt dort.
* **Zeilenenden**: Git wandelt beim Einchecken; Dateien mit `newline="\n"` schreiben.

## Alfreds Ausrüstung

ASI294MC Pro (IMX294, 4,63 µm), ASI533MC Pro, Seestar S30 (IMX662, 2,90 µm; **azimutal, also
Bildfeldrotation**). Rohdaten unter `D:\astro`, `Y:\Backup\astro`, `F:\backup_usb_h\ASIAIR` —
Bestandsaufnahme in [docs/ASTRO_DATEN.md](docs/ASTRO_DATEN.md).

Der ASI294MC Pro braucht **keine Bias-Frames und keine Dark-Skalierung** (Dark-Flats statt
Bias). Er ist **nicht** dasselbe wie der ASI294MM Pro — anderer Sensor (IMX492), halbe
Pixelgröße. Die Kamera-Erkennung schweigt bei Mehrdeutigkeit lieber, als sich zu vertun.
