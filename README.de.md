# ForgePix ⚡

### [forgepix.app](https://forgepix.app) · Focus • Astro • Long Exposure

*[🇬🇧 English version](README.md)*

![tests](https://github.com/samuelvoltarius/ForgePix/actions/workflows/tests.yml/badge.svg)
[![release](https://img.shields.io/github/v/release/samuelvoltarius/ForgePix?include_prereleases)](https://github.com/samuelvoltarius/ForgePix/releases)
[![license: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **ForgePix Beta** — automatisches Fokus‑Stacking und Computational Photography für **Makro,
> Astro und Langzeitserien**. **Lokal nutzbar, KI optional.** Nutzbar und getestet, aber jung —
> rechne mit gelegentlichen Ecken und [melde Fehler](https://github.com/samuelvoltarius/ForgePix/issues).

**Focus Stacking + Astro + Langzeitbelichtung.** Fotos rein, fertiges Bild raus — in bester
Qualität zum Weiterbearbeiten. Eigenständig, frei (MIT), plattformübergreifend
(Windows / macOS / Linux).

## Warum ForgePix?

> - ✓ **Analysiert Fokusreihen**
> - ✓ **Entfernt Ausschuss automatisch**
> - ✓ **Berechnet optimale Bildanzahl**
> - ✓ **Long Exposure ohne ND-Filter**
> - ✓ **Astro + Makro in einer App**
> - ✓ **Funktioniert ohne KI** (komplett lokal, kein Server)

## So funktioniert's

Aus einer unscharfen Fokusreihe wird ein durchgehend scharfes Bild — und du siehst bei jedem Schritt, *was* passiert:

| 1 · Input (Reihe) | 2 · Analyse | 3 · Fokus-Map | 4 · Ergebnis |
|---|---|---|---|
| ![Input](assets/shots/p1_input.jpg) | ![Analyse](assets/shots/p2_analyse.png) | ![Fokus-Map](assets/shots/05_focusmap.png) | ![Ergebnis](assets/shots/p4_result.jpg) |
| *9 Aufnahmen, jede nur teil­scharf* | *verwackelte raus, optimale Bildanzahl* | *welcher Bereich aus welchem Foto* | *durchgehend scharf, zum Weiterbearbeiten* |

📖 **Ausführliche Anleitung:** [docs/GUIDE.de.md](docs/GUIDE.de.md) · *[🇬🇧 Guide](docs/GUIDE.en.md)*

| Startbildschirm | Makro-Modul |
|---|---|
| ![Start](assets/shots/01_start.png) | ![Makro](assets/shots/02_makro.png) |
| **Camera‑Raw-Editor** | **Astro-Modul** |
| ![Editor](assets/shots/04_editor.png) | ![Astro](assets/shots/03_astro.png) |

## Highlights

- **Ein‑Klick‑Automatik** — wählt brauchbare Fotos aus, richtet sie aus, verschmilzt sie zu
  einem durchgehend scharfen Bild und schärft schonend nach. **Anfänger‑** und **Profi‑Modus**.
- **Null‑Klick im Anfänger‑Modus:** einfach einen **Ordner aufs Fenster ziehen** — ForgePix errät
  das passende Modul (aus Dateitypen / Namen / einer kurzen EXIF‑Stichprobe) und startet die
  Automatik. Rein → fertig.
- **Start‑Auswahl:** beim Öffnen wählst du das **Modul** (jederzeit über „◀ Module“ wechselbar).
- **Fokus‑Intelligenz** (Makro): verwackelte Fotos automatisch aussortieren, **Reihen‑Analyse**
  (Aufnahmeanalyse + Stack‑Optimizer + **Fokus‑Map**), **DOF‑/Focus‑Bracketing‑Assistent** mit
  **EXIF‑Auslesen**, **Stack‑Konfidenz‑Score** mit echten Metriken.
- **Entscheidungs‑Panel** neben dem Ergebnis: Konfidenz‑Score, „X von Y verwendet", **klickbare
  Befunde** (ein Befund springt direkt zur passenden Ansicht — Ghosting → Geister‑Karte, Halos →
  Retusche, Fokus‑Lücken → Fokus‑Map) und eine **„Warum diese Einstellungen?"**‑Begründung der Automatik.
- **Schnell‑Export‑Chips** (📷 Instagram · 🌐 Web · 🖨 Druck) für Ein‑Klick‑Export direkt neben dem
  Ergebnis; **„Weiter wo du warst"** auf dem Startbildschirm öffnet den letzten Ordner + Modul.
- **Update‑Hinweis:** beim Start wird leise die GitHub‑Release‑Version geprüft und ein dezenter
  Hinweis „neue Version verfügbar" gezeigt, wenn es eine gibt — komplett optional (Setup), keine Daten gesendet.
- **Komplett per Tastatur bedienbar** (⌘O Ordner, ⌘↩ Automatik, ⌘1–4 Module, F1 = Kürzel‑Übersicht …).
- **Vier Module, eine App:** 🔬 **Makro** (Fokus‑Stacking, mit Presets Produkte/Münzen/Food),
  🌌 **Astro** (Stern‑Stacking), 🌗 **Hybrid** (Mond‑/Sonnen‑**Mosaik** + **Fokus+Astro**:
  je Position erst entrauschen, dann fokus‑stacken) und 📷 **Langzeitbelichtung** (aus einer Serie
  **ohne ND‑Filter**: seidiges Wasser/Wolken, Lichtspuren, Störer entfernen — mit KI‑Effektvorschlag
  und **virtueller Belichtungszeit** (stufenloses Teil‑Mitteln)).
- **Eigene Engine** (OpenCV/NumPy) — keine externe Stacking‑Software nötig.
- **RAW** (ARW/NEF/CR2/DNG …) treu in 16‑bit entwickelt; **EXIF/Provenienz wird eingebaut
  übernommen**: JPEG mit EXIF, TIFF mit Kern‑Provenienz, vollständige TIFF‑Metadaten optional via exiftool.
- **Eingebauter Camera‑Raw‑Editor:** Belichtung/Kontrast/Weißabgleich, **Tonwertkurve**,
  **HSL pro Farbe**, Klarheit, **Zuschneiden/Drehen**, Histogramm.
- **Retusche‑Editor:** scharfe Stellen aus Einzelfotos über Halos/**Ghosting** pinseln, mit Radierer.
- **Geister‑Karte + Deghost**, **Vorher/Nachher‑Schieberegler**, **Filmstreifen**,
  **Export‑Voreinstellungen** (Instagram/WhatsApp/Web/4K/Druck), **Batch** & **Watch‑Ordner**.
- **Astro:** Kalibrierung (Darks/Flats/Bias), Stern‑Ausrichtung (**Translation oder Feldrotation**
  für Alt‑Az), **Hot‑/Cold‑Pixel‑Korrektur**, **Drizzle‑lite** (2× feineres Sampling),
  **Sigma/Winsor‑Rejection** (entfernt Satelliten/Hot‑Pixel), Hintergrund‑Extraktion,
  **erklärbare Sub‑Bewertung** (FWHM, Sternzahl, Elongation/Guiding, Wolken, Spuren — schlechte Subs
  fliegen raus *mit Begründung*), 32‑bit‑Linear‑Export + **FITS**. **GraXpert & StarNet++ per Ein‑Klick**
  (falls installiert: automatisch ausführen + reimportieren; sonst Datei‑Übergabe).
- **Große Stacks** werden gebündelt gestreamt (speicherschonend).
- **Schnell:** RAW‑Entwicklung und Schärfe‑Analyse laufen über **alle CPU‑Kerne**; Schärfe‑Werte
  werden pro Datei **gecacht** (Re‑Runs sind sofort) und fürs Culling das eingebettete Kamera‑JPEG
  genutzt — große RAW‑Serien werden deutlich schneller analysiert.

## Läuft überall — KI ist optional

Die Automatik funktioniert **komplett ohne KI** (Einstellungen aus dem gemessenen Schärfeprofil).
**Kein Ollama, kein Server, kein Modell‑Download.** Optional ein OpenAI‑kompatibler Server
(llama.cpp / LM Studio / vLLM) **oder ein Anbieter mit API‑Schlüssel** (OpenAI / OpenRouter).
Die KI **berät & prüft** nur — sie bearbeitet nie Pixel. *„Die Software erklärt, warum sie
diese Einstellungen gewählt hat.“* Du kannst einen **Freitext-Wunsch** angeben (z. B. „seidiges
Wasser, Personen scharf"); der Vorschlag bekommt zusätzlich **EXIF-Eckdaten** + die **Fokus-Map**.
Das Setup zeigt genau, was gesendet wird — einige Vorschau-Frames, das Schärfeprofil, EXIF-Eckdaten
und dein Wunsch; keine Originaldateien, keine Standortdaten.

Profis können optional **Siril verbinden** (falls installiert) als alternative Astro‑Engine und
an **GraXpert / StarNet++** weitergeben — nichts davon ist Pflicht.

## Download (fertige Pakete)

Vorgebaute Pakete für **macOS · Windows · Linux** gibt es auf der
[**Releases-Seite**](https://github.com/samuelvoltarius/ForgePix/releases) (kein Python nötig):

- **macOS:** `ForgePix-macOS.zip` → entpacken, `ForgePix.app` öffnen.
- **Windows:** `ForgePix-Windows.zip` → entpacken, `ForgePix.exe` starten.
- **Linux:** `ForgePix-Linux.tar.gz` → entpacken, `./ForgePix/ForgePix` starten.

> Erststart unter macOS/Windows: ggf. Rechtsklick → „Öffnen" (App ist noch nicht notarisiert —
> [Signierung aktivieren](docs/SIGNING.md)).

## Aus dem Quellcode

```bash
python3 -m pip install -r requirements.txt
python3 focus_stack_gui.py
```

- **macOS:** `ForgePix.app` doppelklicken (optional `exiftool` für EXIF‑Übernahme).
- **Windows:** `run.bat`  ·  **Linux:** `./run.sh`

## Erste Schritte

1. Programm öffnen → **Modul wählen** (Makro / Astro / Hybrid / Langzeit).
2. **🌱 Anfänger** (Standard): Ordner wählen (oder aufs Fenster ziehen) → **⚡ Loslegen**. Fertig.
3. **🛠️ Profi:** geführter Wizard mit allen Reglern, KI‑Server, externe Tools usw.

> Jede Einstellung hat ein **?** mit Klartext‑Erklärung. Im Zweifel reicht die Automatik.
> Sinnvolle Bildanzahl pro Modul steht direkt in der jeweiligen Gruppe — Details in der
> [Anleitung](docs/GUIDE.de.md).

## Beispieldaten zum Ausprobieren

Kuratierte Test‑Datensätze (gute **und** absichtlich schlechte Aufnahmen) als
[**Sample‑Download**](https://github.com/samuelvoltarius/ForgePix/releases/tag/samples-v1):
Astro‑Subs (M 42 / IC 5146, Bayer‑FITS), ein Landschafts‑RAW und eine Makro‑Fokusreihe — einfach
den jeweiligen Ordner aufs Fenster ziehen.

## Externe Tools (optional)

Im **Setup‑Menü (⚙) → „Externe Tools"** trägst du Pfade zu **GraXpert**, **StarNet++** und
**Siril** ein (oder leer = automatisch suchen). Bei Astro/Langzeit/Hybrid kannst du das Ergebnis
dann **per Ein‑Klick** durch GraXpert (Gradient) oder StarNet++ (starless) schicken — inklusive
automatischem Reimport. Nichts davon ist Pflicht.


## Sprachen

Deutsch & Englisch eingebaut (oben rechts umschalten, greift beim Neustart). Eigene Sprache:
`lang/de.json` kopieren, Werte übersetzen, z.B. als `lang/fr.json` speichern — erscheint
automatisch in der Sprachauswahl.

## Tastenkürzel

**Foto-Tasten** (wie in Lightroom): **Leertaste** Vorher/Nachher · **← →** Bild wechseln ·
**A** Analyse · **S** Stack · **E** Editor · **G** Geister-Karte · **F** Fokus-Map · **R** Retusche.
**Befehle:** ⌘O Ordner · ⌘↩ Automatik · ⌘E Export · ⎋ Stop/zurück · ⌘1–4 Module · ⌘B Anfänger/Profi ·
⌘D DOF · **F1** = vollständige Übersicht. *Ordner aufs Fenster ziehen startet die Analyse.*

## Tests

```bash
./run_tests.sh        # oder: python3 -m unittest discover -s tests
```

48 Engine‑Tests (Standardbibliothek, kein pytest nötig) decken Fokus‑Analyse, Langzeit, Astro,
Stacker, Mosaik, Export, Parallel‑Helfer, Modul‑Erkennung, KI‑Kontext, i18n‑Vollständigkeit und
einen GUI‑Smoke‑Test ab.

## Lizenz

MIT (siehe `LICENSE`). Nur freie Bausteine: OpenCV, NumPy, rawpy, tifffile, psdtags,
PySide6 (LGPL). Astro‑Methoden inspiriert von [Siril](https://siril.org) (selbst neu
implementiert, kein GPL‑Code kopiert).
