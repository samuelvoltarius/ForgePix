# Changelog

Alle nennenswerten Änderungen an ForgePix. Format orientiert an
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/).

## [1.14.1] – 2026-06-26
### Geändert (Ehrlichkeit/Claim-Check + Beta)
- **Claim-Check der Doku:** Abhängigkeiten klar markiert — **EXIF-Übernahme/„Aus Foto lesen"
  brauchen `exiftool`** (sonst übersprungen), **FITS** braucht `astropy` (optional, im Installer
  enthalten). Photoshop-Ebenen-TIFF und FITS wurden real verifiziert (geschrieben + zurückgelesen).
  GraXpert/StarNet++/Siril bleiben klar als optional + Auto-Erkennung + Datei-Fallback beschrieben.
- **Datenschutz-Hinweis** zur KI jetzt einheitlich: in **Setup** (schon da), **README** und **beiden
  Guides** — es gehen nur Vorschau-Frames, Schärfeprofil, EXIF-Eckdaten, optional Fokus-/Geister-Karte
  und der Wunsch an die KI; **keine** Originaldateien, **keine** Standortdaten. Lokaler Server = nichts
  verlässt den Rechner.
- **Beta-Kennzeichnung:** README-Lead + „Beta" im „Über"-Dialog. Positionierung: „automatisches
  Fokus-Stacking und Computational Photography für Makro, Astro und Langzeitserien — lokal nutzbar,
  KI optional".

## [1.14.0] – 2026-06-26
### Hinzugefügt (KI-Hinweise, optional)
- **Geister-Karte an die KI:** Nach dem Stacken bekommt die Post-Stack-KI (Feinschliff) optional
  die **Geister-Karte** mit und nennt konkrete **Retusche-Stellen** („wo ist Ghosting?"). Die
  Karte wird dafür intern erzeugt, auch ohne `--ghost-map`. Erscheint als „KI-Retusche-Hinweis"
  im Log; ohne KI-Server passiert nichts.
- **Astro-Sub-Auswahl in Klartext:** Bei Astro fasst die KI (falls Server da) in 1–3 Sätzen
  zusammen, **welche Subs warum** rausfliegen (Wolken/Guiding/FWHM/Spuren) — rein textbasiert,
  datensparsam. Neue reine Funktion `astro_quality.subs_summary_text()`.
- +2 Tests (37 gesamt).

## [1.13.0] – 2026-06-26
### Hinzugefügt (KI-Kontext + Transparenz)
- **Reicherer KI-Vorschlag:** Der KI-Settings-Vorschlag bekommt jetzt zusätzlich **EXIF-Eckdaten**
  (Brennweite/Blende/Belichtung/ISO/Objektiv) und – bei Makro – die **Fokus-Herkunfts-Karte als
  Bild** mit. So kann die KI Fokus-Lücken erkennen und „mehr Aufnahmen nötig?" beurteilen.
- **Freitext-Wunsch:** Neues Feld „Wunsch (optional)" im KI-Bereich (z. B. „seidiges Wasser,
  Personen scharf"). Wird beim KI-Vorschlag **wörtlich berücksichtigt** (CLI: `--wish`).
- **Transparenz:** Setup zeigt klar, **was** an die KI geht (einige Vorschau-Frames, Schärfeprofil,
  EXIF-Eckdaten, dein Wunsch) — **keine** Originaldateien, **keine** Standortdaten.
- Erweiterungspunkt `suggest_settings(context=…)` + `build_ai_context()`; +3 Tests (35 gesamt).
### Dokumentation
- **Anfänger- vs. Profi-Vergleichstabelle** (wer kann was, wie, warum, wann sinnvoll) in beiden
  Guides (DE/EN).

## [1.12.0] – 2026-06-26
### Hinzugefügt (einfacher)
- **Null-Klick im Anfänger-Modus:** Ordner aufs Fenster ziehen startet **sofort die Automatik** —
  rein → fertig, ganz ohne Knopf. (Profi-Modus: weiterhin erst Reihen-Analyse.)
- **Modul automatisch erraten:** Beim Ablegen eines Ordners (von der Modul-Auswahl) rät ForgePix
  das passende Modul aus Dateitypen, Dateinamen und einer kurzen EXIF-Stichprobe — FITS/„light/
  dark/flat" → Astro, sehr lange Belichtung bei hoher ISO → Astro, lange Belichtung → Langzeit,
  sonst Makro. Wird vorgewählt + im Log/Status begründet; der Nutzer kann jederzeit umschalten.
  Neue Engine-Funktion `focus_analysis.guess_module()` (+3 Tests, 32 gesamt).

## [1.11.0] – 2026-06-26
### Geändert (Tempo)
- **Mehrkern-Verarbeitung:** RAW-Entwicklung und Schärfe-Analyse laufen jetzt über **alle
  CPU-Kerne** (ThreadPool; rawpy/OpenCV geben den GIL frei). Reihenfolge bleibt exakt erhalten.
  Auf Mehrkern-Maschinen deutlich schneller — bei RAW-Serien am stärksten.
- **Schärfe-Cache:** Analyse-Ergebnisse werden pro Datei (Schlüssel = Pfad + Änderungszeit)
  zwischengespeichert. Erneute Läufe/„Weiter wo du warst" überspringen die Neuberechnung
  (im Test ~19× schneller beim 2. Lauf, identische Ergebnisse).
- **Embedded-JPEG fürs Culling:** Für die reine Schärfe-Analyse wird – wenn groß genug – das
  eingebettete Kamera-JPEG des RAW genutzt statt voll zu entwickeln (sicherer Fallback auf
  volle Entwicklung). Die Stack-Qualität bleibt unberührt (Entwicklung fürs Ergebnis unverändert).
- Neuer geteilter `parallel.py`-Helfer (`pmap`/`cpu_workers`) + 3 Tests (29 gesamt).

## [1.10.1] – 2026-06-26
### Behoben
- **Absturz beim Beenden vermeidbar gemacht:** Der Update-Check lief als `QThread` und konnte beim
  schnellen Beenden kurz nach dem Start einen `qFatal`/Abort auslösen (Thread beim Aufräumen noch
  aktiv). Läuft jetzt als reiner Python-Daemon-Thread → das kann nicht mehr passieren.
### Geändert (interne Modularisierung 2/n — keine Verhaltensänderung)
- **`ui/main_window.py` von ~2340 auf ~1940 Zeilen** verschlankt. Weitere zusammenhängende Teile
  ausgelagert: `ui/settings_io.py` (Einstellungen laden/speichern), `ui/export.py`
  (Schnell-Export + Export-Dialog), `ui/result_view.py` (Ergebnis-/Vorschau-Anzeige, Ansicht-
  Umschalter, Entscheidungs-Panel). Funktion und Oberfläche unverändert (26 Tests grün,
  Rendering offscreen geprüft).

## [1.10.0] – 2026-06-26
### Geändert (interne Modularisierung — keine Verhaltensänderung)
- **`ui/main_window.py` von ~2640 auf ~2340 Zeilen verschlankt.** Zusammenhängende Teile in
  eigene Module ausgelagert: `ui/theme.py` (Qt-Stylesheet), `ui/workers.py`
  (Hintergrund-Threads + Versionsvergleich), `ui/welcome.py` (Startbildschirm & „Über"-Dialog
  als Mixin), `ui/appinfo.py` (geteilte Pfad-/Namens-Konstanten). Erleichtert künftige Arbeit;
  Funktion und Oberfläche unverändert (26 Tests grün, identisches Rendering).

## [1.9.5] – 2026-06-26
### Hinzugefügt
- **Auto-Update-Hinweis:** Beim Start prüft ForgePix einmal leise die GitHub-Releases und zeigt
  auf dem Startbildschirm einen dezenten Hinweis „Neue Version verfügbar → herunterladen", wenn
  eine neuere Version vorliegt. Vollständig **abschaltbar** (Setup → „Beim Start auf Updates
  prüfen"), läuft im Hintergrund-Thread und bleibt bei Offline/Fehler still. Es werden keine
  Daten gesendet (reiner Lese-Aufruf der öffentlichen Releases-API).

## [1.9.4] – 2026-06-25
### Hinzugefügt
- **„Weiter wo du warst"** auf dem Startbildschirm: Ein Chip lädt den zuletzt verwendeten Ordner
  samt Modul mit einem Klick wieder — erscheint nur, wenn der Ordner noch existiert.

## [1.9.3] – 2026-06-25
### Hinzugefügt
- **Klickbare Befunde** im Entscheidungs-Panel: Ein Befund springt per Klick zur passenden
  Ansicht/Werkzeug — „Ghosting" → Geister-Karte, „Halos" → Retusche, „Fokus/Abdeckung" →
  Fokus-Map. Der Link erscheint nur, wenn das Ziel verfügbar ist. Aus Diagnose wird ein Klick
  zur Lösung.

## [1.9.2] – 2026-06-25
### Hinzugefügt
- **Schnell-Export-Chips** im Entscheidungs-Panel: 📷 Instagram · 🌐 Web · 🖨 Druck als
  Ein-Klick direkt neben dem Ergebnis — exportiert das fertige Bild sofort ins gewählte Format
  (ohne Dialog) und öffnet den Ordner. Der ausführliche Export-Dialog (⌘E) bleibt für
  Mehrfach-Ziele/Ebenen/16-bit. Chips sind aktiv, sobald ein Ergebnis vorliegt.

## [1.9.1] – 2026-06-25
### Hinzugefügt
- **„Warum diese Einstellungen?"** im Entscheidungs-Panel: Die Begründung der Automatik/KI
  (Motiv, Vorschlag, Begründung) wird live aus dem Lauf-Log mitgeschnitten und rechts neben dem
  Ergebnis angezeigt — die Software erklärt sichtbar, *warum* sie so entschieden hat.

## [1.9.0] – 2026-06-25
### Hinzugefügt
- **3-Spalten-Layout (Lightroom-Stil):** links Einstellungen · Mitte großes Bild mit
  **Ansicht-Umschalter** (Ergebnis / Fokus-Map / Geister-Karte) + Aktionen + Filmstreifen ·
  rechts **Entscheidungs-Panel** (Stack-Konfidenz-Score, „X von Y verwendet", Befunde,
  nächste Schritte) und Log.
- **Code-Signing-Gerüst:** macOS-Build signiert ad-hoc; echte Developer-ID-Signierung +
  Notarisierung schalten sich automatisch ein, sobald die Apple-Secrets gesetzt sind
  (Anleitung: docs/SIGNING.md).

## [1.8.1] – 2026-06-25
### Behoben (aus Audit)
- **KI-Vorschlag-Knopf** startete im gebündelten Binary eine zweite GUI statt der Pipeline —
  jetzt frozen-sicher (gemeinsamer `_start_pipeline`-Helfer für alle Subprozess-Starts).
- **FITS** war in jedem Installer tot: `astropy` fehlte im Build — jetzt in build.yml + tests.yml.
- **macOS-Dock-Icon** (pyobjc) im Mac-Build ergänzt.
- **Einstellungs-Migration** von „StackForge" → „ForgePix" (alte Nutzer behalten Pfade/Modus/Fenster).
- Tote `SHINESTACKER`-Referenz + verwaiste `StackForge.iconset` entfernt; FITS-Test ergänzt (26 Tests).

## [1.8.0] – 2026-06-25
### Hinzugefügt
- **Fertige Installer für macOS · Windows · Linux** (PyInstaller via GitHub Actions, automatisch ans
  Release gehängt) — kein Python mehr nötig. Download auf der Releases-Seite.
- Gebündeltes Binary dient als GUI **und** (über `--cli`) als Pipeline-Backend.
### Behoben
- cv2-Rekursionsfehler im gebündelten Binary (Pfad-Verschmutzung im frozen-Modus).

## [1.7.0] – 2026-06-25
### Geändert
- **Umbenannt von „StackForge" zu „ForgePix"** — der alte Name war auf GitHub/PyPI mehrfach belegt.
  ForgePix ist auf PyPI und GitHub verifiziert frei. App, Icons, Bundle, Repo, Docs durchgängig umgestellt.
- Ordner aufgeräumt: veraltete Screenshots entfernt, Asset-Dateien umbenannt.

## [1.6.0] – 2026-06-25
### Geändert (foto-zentriertes Layout)
- **Bild groß oben, Log klein unten** — das Ergebnis bekommt die Hauptfläche, der Log ist Nebensache.
- **Echte Statuszeile** statt grünem Strich: Bereit · Ordner geladen · Läuft · Analysiere · Stacke · Fertig
  (farbcodiert, aus dem Live-Log abgeleitet).
- **Größerer Header:** Logo + „ForgePix" + Untertitel „Computational Photography Suite".
- **README:** „Warum ForgePix?"-Bullets geschärft + **Bilderstrecke** (Input → Analyse → Fokus-Map →
  Ergebnis) mit echten Fotos; Screenshots auf das neue Layout aktualisiert.

## [1.5.0] – 2026-06-25
### Geändert (UX-Politur)
- **Startbildschirm:** hochwertigere Karten — große Icons, Titel, Kategorie und Beispiele
  (z. B. „Produkte · Münzen · Insekten · Food“) + Empfehlungs-Pill. **Einstellungen & „Was ist das?“**
  schon am Start (Sprache/Anfänger-Profi/KI).
- **Hauptfenster:** deutlich **größere Bildfläche** (~⅔), leeres Ergebnis als klare Drag-&-Drop-Zone,
  viele Buttons in ein **„🛠 Werkzeuge“-Menü** aufgeräumt (nur Vorher/Nachher · Bearbeiten · Export sichtbar).
- **Editor:** größeres **Histogramm** und größere **Bildfläche**.
- **README** komplett aufpoliert: „Warum ForgePix?“-Sektion + Screenshot-Galerie (6 Ansichten).
- **Schieberegler** gethemt (v1.4.1).

## [1.4.1] – 2026-06-25
### Behoben
- **Schieberegler durchgängig gethemt** (grüner Verlauf + heller Griff statt Qt-Standard-Blau) —
  betraf v. a. den Camera-Raw-Editor („Bearbeiten").
- Letzte lila Canvas-Reste (Vergleichs-/Kurven-Hintergrund) auf Anthrazit umgestellt.

## [1.4.0] – 2026-06-25
### Geändert
- **Startbildschirm neu gestaltet:** Logo + Tagline, aufgeräumte Modul-Karten mit Emoji,
  Kurzbeschreibung und grünem Empfehlungs-Pill (Bildanzahl), zentriert mit fester Maximalbreite.

## [1.3.0] – 2026-06-25
### Hinzugefügt
- **Export-Dialog:** Auswahl der Ziele (Web-JPG/Instagram/WhatsApp/Web/4K/Druck-16-bit-TIFF),
  Ausgabe-Schärfung, JPG-Qualität, **Photoshop-Ebenen-Datei** und 16-bit-TIFF. Sichtbarer
  „📦 Export"-Knopf + ⌘E.
- Erstes öffentliches Release auf GitHub inkl. CI (GitHub Actions) und Tests-Badge.
### Geändert
- Welcome-Screen klarer („Schritt 1: Wähle ein Modul" + 3-Schritt-Ablauf).
- App-Launcher portabel (relatives Projektverzeichnis).

## [1.2.0] – 2026-06-25
### Hinzugefügt
- **Foto-Tastatursteuerung:** Leertaste (Vorher/Nachher), ← → (Bild wechseln), A/S/E/G/F/R,
  ⌘E (Export). **Drag&Drop:** Ordner aufs Fenster → übernehmen + im Profi-Makro Analyse starten.
### Geändert
- **Theme** auf Anthrazit + Chili-Grün (GreenChili-Marke) statt Lila.
- Messwert-Begründungen beim Aussortieren („Schärfewert 41 % vom Serien-Median").

## [1.1.0] – 2026-06-25
### Hinzugefügt
- **Tastenkürzel** (⌘O/⌘↩/⌘1–4/F1 …) + Hilfe-Dialog.
- **Test-Suite** (24 unittest-Tests, `./run_tests.sh`), inkl. i18n-Vollständigkeitstest.
### Behoben
- None-/Leer-Guards (Astro/Langzeit), Timeout-Handling (GraXpert/StarNet/Siril),
  Analyse im Hintergrund-Thread (GUI blockiert nicht mehr).

## [1.0.0] – 2026-06-24
### Hinzugefügt
- Vier Module: **Makro/Fokus-Stacking, Astro, Hybrid, Langzeitbelichtung** mit Start-Auswahl.
- **Fokus-Intelligenz:** Verwackelt-Filter, Reihen-Analyse, Stack-Optimizer, DOF-/Bracketing-
  Assistent mit EXIF-Auslesen, Stack-Konfidenz-Score, Fokus-Map.
- Astro: Kalibrierung, Translation/Feldrotation, Hot-Pixel, Drizzle, Sub-Bewertung, FITS,
  GraXpert/StarNet/Siril per Ein-Klick.
- Camera-Raw-Editor, Retusche, Export-Voreinstellungen, Batch/Watch, DE/EN, optionale KI.
