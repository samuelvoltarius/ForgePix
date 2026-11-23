# 07 — Plate-Solver: was ForgePix nutzt und was es fertig gibt

Stand 23.11.2026.

## Was ForgePix heute nutzt (am Code geprüft)

| Solver | wo | blind? | Bemerkung |
|---|---|---|---|
| **Eigener Solver** | `core/astrometry.py` | **nein** — braucht RA/Dec und Bildmaßstab als Hinweis (aus FITS-Kopf oder Montierung) | Dreiecksvergleich gegen den lokalen Gaia-Katalog, freie Drehung und Spiegelung, unabhängige Prüfsterne. Wird von Zentrieren, Farbkalibrierung und „Himmelsposition bestimmen“ benutzt. Offline, ohne fremde Programme. |
| Siril | `photometric._solve_wcs_siril` | mit Hinweis | Rückfall, wenn installiert |
| **ASTAP** | `core/astap.py` | **ja** (`-fov 0 -r 180`) | seit 23.11.: blind für die Farbkalibrierung ohne RA/Dec, Rückfall beim Zentrieren; Lösung aus `.wcs` gelesen (vorher fälschlich `.fit`); auch im Windows-Programmordner gesucht. Gegen Nachbau geprüft, **nicht** gegen echtes ASTAP |
| astrometry.net `solve-field` | `photometric._find_solver` | **ja** | Rückfall, wenn lokal installiert |
| nova.astrometry.net (online) | `photometric._solve_wcs_astrometry` | **ja** | braucht API-Schlüssel (`--astrometry-key`), lädt das Bild hoch |

Zentrieren am Teleskop nutzt zuerst den eigenen Solver (Hinweis aus der Montierung, schnell,
ohne Netz) und erst, wenn der scheitert, ASTAP mit demselben Hinweis.

## Fertige Projekte — Recherche vom 23.11.2026

Selbst nachgeprüft: tetra3 = Apache-2.0 (LICENSE.txt), ASTAP-Seite nennt „full blind solving“
und „Introduced multi-threading for blind solving“ (2026.10.30). Alles andere **laut Recherche,
nicht selbst nachgelesen**. Kein Solver wurde ausgeführt.

| Projekt | Code-Lizenz | Daten/Gewichte | blind | Systeme | Weg für ForgePix |
|---|---|---|---|---|---|
| **ASTAP** | MPL-2.0 (SourceForge-Seite) | Gaia-DR3-Auszüge (D05/D20/D50/D80 für 0,15–6°), Lizenz nicht gefunden | **ja**, `-fov 0 -r 180` | Windows, Linux (auch ARM), macOS | **als Programm aufrufen**, Nutzer lädt Programm + Datenbank selbst — schon als Rückfall angebunden, blind noch nicht |
| astrometry.net `solve-field` | GPL-3 | Index-Dateien, Lizenz nicht gefunden | ja | Linux, macOS; Windows nur über WSL/Cygwin | als Programm aufrufen (schon als Rückfall angebunden) |
| nova.astrometry.net | — | — | ja | online | schon angebunden; Bilder sind dort **standardmäßig öffentlich** → nur auf ausdrücklichen Wunsch |
| tetra3 (ESA) / cedar-solve | Apache-2.0 | mitgelieferte Datenbank ohne eigene Lizenzangabe | ja | reines Python | **mitlieferbar**, aber für Weitfeld (Standard 10–30°); für Deep-Sky < 3° müsste eine Tycho-Datenbank selbst gebaut werden; cedar-solve pinnt `numpy<2` (passt nicht zu Python 3.14) |
| twirl | MIT | fragt Gaia online | nein | Python | kein Gewinn gegenüber dem eigenen Solver |
| `astrometry` (PyPI) | GPL-3 | lädt Indizes | ja | Linux, macOS | nicht mitliefern (GPL) |
| StarNet2 CLI 2.6.2 | geschlossen, Lizenz nicht gefunden („free“, „All rights reserved“) | im Paket | — | Windows (ONNX/DirectML), Linux, macOS (auch Apple Silicon) | **als Programm aufrufen**, Nutzer lädt es selbst; hat `--machine-progress` (JSON-Zeilen) — passt zu unseren Markern. Werkzeug „StarNet++“ im Arbeitsplatz ist dafür da |
| StarNet v1 (GitHub) | MIT | **CC BY-NC-SA 4.0** | — | TensorFlow | nicht nutzbar |

## Empfehlung

1. [x] **Blind lösen über ASTAP** (23.11.2026 eingebaut, an echtem ASTAP ungeprüft): ASTAP ist frei, auf allen drei Systemen da,
   kann blind und ist schon als Rückfall angebunden. Fehlt: der Blind-Aufruf
   (`-fov 0 -r 180`), die Suche des Windows-CLI (`astap_cli.exe`) — seit 23.11. drin — und ein
   Hinweis in der Einrichtung, welche Datenbank zum Bildfeld passt (Seestar 1,2°×2,1° → D50/D80).
2. Der eigene Solver bleibt für Zentrieren und Farbkalibrierung (schnell, offline, mit Hinweis).
3. tetra3 nur, wenn Weitfeld (Kamera-Objektiv, Polausrichtung) dazukommt.
4. [~] StarNet2: Aufruf mit `-i/-o`, wenn die Datei `starnet2…` heißt (23.11.2026, laut Recherche,
   ungeprüft). Offen: `--machine-progress` lesen, an echtem StarNet2 prüfen.
