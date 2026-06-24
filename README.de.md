# StackForge ⚡

*[🇬🇧 English version](README.md)*

**Stacking mit einem Klick — Makro, Astro, Hybrid & Langzeitbelichtung.** Fotos rein, fertiges
Bild raus — in bester Qualität zum Weiterbearbeiten. Eigenständig, frei (MIT),
plattformübergreifend (Windows / macOS / Linux).

📖 **Ausführliche Anleitung:** [docs/GUIDE.de.md](docs/GUIDE.de.md) · *[🇬🇧 Guide](docs/GUIDE.en.md)*

![StackForge — Modul-Auswahl](assets/screenshot_welcome.png)
![StackForge — Astro](assets/screenshot_astro.png)

## Highlights

- **Ein‑Klick‑Automatik** — wählt brauchbare Fotos aus, richtet sie aus, verschmilzt sie zu
  einem durchgehend scharfen Bild und schärft schonend nach. **Anfänger‑** und **Profi‑Modus**.
- **Start‑Auswahl:** beim Öffnen wählst du das **Modul** (jederzeit über „◀ Module“ wechselbar).
- **Fokus‑Intelligenz** (Makro): verwackelte Fotos automatisch aussortieren, **Reihen‑Analyse**
  (Aufnahmeanalyse + Stack‑Optimizer + **Fokus‑Map**), **DOF‑/Focus‑Bracketing‑Assistent** mit
  **EXIF‑Auslesen**, **Stack‑Konfidenz‑Score** mit echten Metriken.
- **Komplett per Tastatur bedienbar** (⌘O Ordner, ⌘↩ Automatik, ⌘1–4 Module, F1 = Kürzel‑Übersicht …).
- **Vier Module, eine App:** 🔬 **Makro** (Fokus‑Stacking, mit Presets Produkte/Münzen/Food),
  🌌 **Astro** (Stern‑Stacking), 🌗 **Hybrid** (Mond‑/Sonnen‑**Mosaik** + **Fokus+Astro**:
  je Position erst entrauschen, dann fokus‑stacken) und 📷 **Langzeitbelichtung** (aus einer Serie
  **ohne ND‑Filter**: seidiges Wasser/Wolken, Lichtspuren, Störer entfernen — mit KI‑Effektvorschlag
  und **virtueller Belichtungszeit** (stufenloses Teil‑Mitteln)).
- **Eigene Engine** (OpenCV/NumPy) — keine externe Stacking‑Software nötig.
- **RAW** (ARW/NEF/CR2/DNG …) treu in 16‑bit entwickelt, **EXIF bleibt erhalten**.
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

## Läuft überall — KI ist optional

Die Automatik funktioniert **komplett ohne KI** (Einstellungen aus dem gemessenen Schärfeprofil).
**Kein Ollama, kein Server, kein Modell‑Download.** Optional ein OpenAI‑kompatibler Server
(llama.cpp / LM Studio / vLLM) **oder ein Anbieter mit API‑Schlüssel** (OpenAI / OpenRouter).
Die KI **berät & prüft** nur — sie bearbeitet nie Pixel. *„Die Software erklärt, warum sie
diese Einstellungen gewählt hat.“*

Profis können optional **Siril verbinden** (falls installiert) als alternative Astro‑Engine und
an **GraXpert / StarNet++** weitergeben — nichts davon ist Pflicht.

## Installation

```bash
python3 -m pip install -r requirements.txt
python3 focus_stack_gui.py
```

- **macOS:** `StackForge.app` doppelklicken (optional `exiftool` für EXIF‑Übernahme).
- **Windows:** `run.bat`  ·  **Linux:** `./run.sh`

## Erste Schritte

1. Programm öffnen → **Modul wählen** (Makro / Astro / Hybrid / Langzeit).
2. **🌱 Anfänger** (Standard): Ordner wählen (oder aufs Fenster ziehen) → **⚡ Loslegen**. Fertig.
3. **🛠️ Profi:** geführter Wizard mit allen Reglern, KI‑Server, externe Tools usw.

> Jede Einstellung hat ein **?** mit Klartext‑Erklärung. Im Zweifel reicht die Automatik.
> Sinnvolle Bildanzahl pro Modul steht direkt in der jeweiligen Gruppe — Details in der
> [Anleitung](docs/GUIDE.de.md).

## Externe Tools (optional)

Im **Setup‑Menü (⚙) → „Externe Tools"** trägst du Pfade zu **GraXpert**, **StarNet++** und
**Siril** ein (oder leer = automatisch suchen). Bei Astro/Langzeit/Hybrid kannst du das Ergebnis
dann **per Ein‑Klick** durch GraXpert (Gradient) oder StarNet++ (starless) schicken — inklusive
automatischem Reimport. Nichts davon ist Pflicht.

## Editor

![Editor](assets/editor.png)

## Sprachen

Deutsch & Englisch eingebaut (oben rechts umschalten, greift beim Neustart). Eigene Sprache:
`lang/de.json` kopieren, Werte übersetzen, z.B. als `lang/fr.json` speichern — erscheint
automatisch in der Sprachauswahl.

## Tastenkürzel

⌘O Ordner · ⌘↩ Automatik · ⌘⇧↩ Manuell · ⎋ Stop/zurück · ⌘1–4 Module · ⌘B Anfänger/Profi ·
⌘E Bearbeiten · ⌘⇧A Reihe analysieren · ⌘D DOF · **F1** = vollständige Übersicht.

## Tests

```bash
./run_tests.sh        # oder: python3 -m unittest discover -s tests
```

24 Engine‑Tests (Standardbibliothek, kein pytest nötig) decken Fokus‑Analyse, Langzeit, Astro,
Stacker, Mosaik, i18n‑Vollständigkeit und einen GUI‑Smoke‑Test ab.

## Lizenz

MIT (siehe `LICENSE`). Nur freie Bausteine: OpenCV, NumPy, rawpy, tifffile, psdtags,
PySide6 (LGPL). Astro‑Methoden inspiriert von [Siril](https://siril.org) (selbst neu
implementiert, kein GPL‑Code kopiert).
