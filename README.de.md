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

*(Kurzfassung — die [vollständige Anleitung](docs/GUIDE.de.md) hat jede Option.)*

- **Ein‑Klick‑Automatik** (Anfänger & Profi) — wählt brauchbare Fotos, richtet aus, verschmilzt zu
  einem durchgehend scharfen Bild, schärft schonend. Im Anfänger‑Modus einfach **Ordner aufs Fenster
  ziehen**: ForgePix errät das Modul (Dateitypen / Namen / EXIF‑Stichprobe) und startet. Rein → fertig.
- **Vier Module, eine App:** 🔬 **Makro** (Fokus‑Stacking, Presets Produkte/Münzen/Food),
  🌌 **Astro** (Stern‑Stacking), 🌗 **Hybrid** (Mond‑/Sonnen‑**Mosaik** + **Fokus+Astro**) und
  📷 **Langzeitbelichtung** (ohne ND‑Filter — seidiges Wasser/Wolken, Lichtspuren, **virtuelle Belichtungszeit**).
- **Eigene Engine** (OpenCV/NumPy) — keine externe Stacking‑Software. Große Stacks werden gebündelt
  gestreamt (speicherschonend); RAW‑Entwicklung & Schärfe‑Analyse laufen über **alle CPU‑Kerne** (gecacht).
- **Fokus‑Werkzeuge** (Makro): Reihen‑ & **Fokus‑Map**‑Analyse, **DOF‑/Bracketing‑Assistent** mit
  EXIF‑Auslesen, **Stack‑Konfidenz‑Score** und ein **Entscheidungs‑Panel** mit klickbaren Befunden
  und einer **„Warum diese Einstellungen?"**‑Begründung.
- **Astro:** automatisch erkannte **Kalibrierung** (Darks/Flats/Bias), Stern‑Ausrichtung (Translation
  oder Feldrotation) plus **TPS‑Feinregistrierung** (Feldkrümmung), Hot‑/Cold‑Pixel‑Korrektur,
  **Sigma‑/Winsor‑/Linear‑Fit‑Rejection**, **Drizzle‑lite *und* echtes Drizzle** (pixfrac‑Drop),
  **Binning**, **Multi‑Session**‑Stacking, **asinh‑/MTF‑/GHS**‑Streckung, **echte photometrische
  Farbkalibrierung (PCC/SPCC)** via Siril (Gaia DR3) oder eigenem astroquery‑Pfad (Lite‑Fallback läuft
  immer), erklärbare Sub‑Bewertung, **32‑bit‑Linear + FITS**‑Export, **Live‑Vorschau** beim Stacken und
  **GraXpert/StarNet++ automatisch**. Dual‑Band (Hα/OIII) mit **HOO / synth. SHO / Foraxx / Bicolor**.
- **Fokus‑Verschmelzung:** Laplace‑**Pyramide**, **Tiefenkarte**, gewichteter **Mittelwert** (Method A),
  à‑trous‑**Wavelet** und **halofix** (Dual‑Output‑Halo‑Retusche) — mit Helicon‑**Radius/Smoothing**.
- **HDR & Langzeit:** Exposure Fusion **oder Radiance‑Tonemapping**; Deghosting; Komet/Spuren‑Lückenfüllung;
  **Sigma‑Clipping** und **Vordergrund einfrieren** (Sequator‑Stil).
- **Eingebaute Editoren:** Camera‑Raw (Belichtung, **Tonwertkurve**, **HSL pro Farbe**,
  **Objektivkorrekturen** — lensfun‑Auto oder manuell Vignette/Verzeichnung/CA, Zuschneiden/Drehen,
  Histogramm, Masken‑Pinsel) und ein **Retusche**‑Pinsel über Halos/**Ghosting**.
- **RAW** treu in 16‑bit entwickelt (DHT/DCB/VNG/AHD, AMaZE falls verfügbar); EXIF/Provenienz übernommen.
- **Export & Workflow:** Vorher/Nachher‑Regler, Filmstreifen, **Geister‑Karte/Deghost**, Export‑Presets
  (Instagram/WhatsApp/Web/4K/Druck), **Batch** & **Watch‑Ordner**, Schnell‑Export‑Chips, letzter Ordner.
- **Komplett per Tastatur bedienbar**, **Deutsch & Englisch**, **KI strikt optional** (lokal oder API).

## Läuft überall — KI ist optional

Die Automatik funktioniert **komplett ohne KI** (Einstellungen aus dem gemessenen Schärfeprofil).
**Kein Ollama, kein Server, kein Modell‑Download.** Optional ein OpenAI‑kompatibler Server
(llama.cpp / LM Studio / vLLM) **oder ein Anbieter mit API‑Schlüssel** (OpenAI / OpenRouter).
Die KI **berät & prüft** nur — sie bearbeitet nie Pixel. *„Die Software erklärt, warum sie
diese Einstellungen gewählt hat.“* Du kannst einen **Freitext-Wunsch** angeben (z. B. „seidiges
Wasser, Personen scharf"); der Vorschlag bekommt zusätzlich **EXIF-Eckdaten** + die **Fokus-Map**.
Das Setup zeigt genau, was gesendet wird — einige Vorschau-Frames, das Schärfeprofil, EXIF-Eckdaten
und dein Wunsch; keine Originaldateien, keine Standortdaten.

Profis können optional **Siril verbinden** (falls installiert) — als alternative Astro‑Engine UND für
die **echte photometrische Farbkalibrierung** (Plate‑Solve + Gaia‑DR3‑SPCC) — und an
**GraXpert / StarNet++** weitergeben. Nichts davon ist Pflicht: ohne Siril/Netz fällt PCC auf den
eingebauten stern‑basierten Abgleich zurück.

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

Engine‑Tests (Standardbibliothek, kein pytest nötig) decken Fokus‑Analyse, Langzeit, Astro
(Registrierung, Paletten, Binning, Kalibrierung), Stacker, Mosaik, Export, Parallel‑Helfer,
Modul‑Erkennung, KI‑Kontext, i18n‑Vollständigkeit (inkl. Wächter gegen unverpackte Strings) und
einen GUI‑Smoke‑Test ab.

## Lizenz

MIT (siehe `LICENSE`). Nur freie Bausteine: OpenCV, NumPy, rawpy, tifffile, psdtags,
PySide6 (LGPL). Astro‑Methoden inspiriert von [Siril](https://siril.org) (selbst neu
implementiert, kein GPL‑Code kopiert).
