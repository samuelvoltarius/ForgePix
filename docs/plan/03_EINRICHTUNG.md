# 03 — Ersteinrichtung und Plattformen (Windows, macOS, Linux)

Stand 22.11.2026.

## Warum es auf dem anderen Rechner nicht lief (am Code gefunden)

* `run.sh` startete fest `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
  Das gibt es nur auf einem Mac mit genau diesem Python von python.org — unter **Linux und
  auf jedem anderen Mac** startete ForgePix gar nicht.
* `ForgePix.app` nahm denselben Pfad und fiel sonst auf irgendein `python3` zurück, ohne
  Pakete zu prüfen.
* `run.bat` rief `python` auf, ohne je ein Paket zu installieren.
* Ein Start ohne PySide6/OpenCV endete in einem ImportError aus dem Programminnern.

Welcher dieser Punkte es auf dem anderen Rechner war, ist **nicht bekannt** — bitte nachtragen
(System, Fehlermeldung).

## Jetzt

* `einrichten.py` (nur Standardbibliothek): prüft die Python-Version (3.10–3.14), legt `.venv`
  im Programmordner an, installiert `requirements.txt`, bei Fehlschlag Paket für Paket mit
  Namen des fehlenden, prüft dass die Oberfläche wirklich startet (Linux: nennt den
  apt/dnf/pacman-Befehl für die Qt-Systembibliotheken) und meldet optionale Programme
  (Siril, GraXpert, StarNet++, ASTAP) — installiert sie nie selbst.
* `run.sh` / `run.bat` / `ForgePix.app`: suchen ein Python, rufen beim ersten Start und nach
  jeder Änderung an requirements.txt `einrichten.py` auf, starten dann aus `.venv`.
  `ForgePix.app` ruft `run.sh`; aus dem Finder gestartet wird Homebrew/python.org mitgesucht.
* `python3 einrichten.py --pruefen` prüft nur.
* Die fertigen Pakete (Releases) brauchen das alles nicht — Python ist dort eingebaut.

## Geprüft

| System | wie |
|---|---|
| Windows 11, Python 3.14 | `einrichten.py --pruefen` gegen die vorhandene Umgebung: alles da außer astroquery/lensfunpy (optional), Siril und GraXpert gefunden. Frische Einrichtung in eine leere Umgebung: alle Pakete installiert (u. a. PySide6 6.12, OpenCV 5.1, numpy 2.5.5), Oberfläche startet; die ganze Testsuite in dieser frischen Umgebung: 1174 Tests OK (15 übersprungen). |
| macOS | **ungeprüft** — kein Mac in dieser Sitzung. Die Tests laufen in der CI auch auf macOS. |
| Linux | **ungeprüft** — die Tests laufen in der CI auf Ubuntu; die Qt-Bibliotheks-Meldung ist nicht an einem echten Linux-Desktop ausgelöst worden. |

## Offen

* Auf einem echten Mac und einem echten Linux `./run.sh` von Null starten und die Ausgabe
  hier eintragen.
* Raspberry Pi (ARM): gibt es für alle Pakete Räder? (PySide6, onnxruntime, rawpy)
