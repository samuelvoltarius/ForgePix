# Changelog

Alle nennenswerten Änderungen an ForgePix. Format orientiert an
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/).

## [1.16.5] – 2026-06-26
### Behoben (Astro-Farbe)
- **Grünstich entfernt (SCNR):** Astro-Vorschau begrenzt Grün auf den Schnitt von Rot/Blau — in
  Deep-Sky ist Grün praktisch nie echtes Signal (kommt von OSC-Bayer/Lichtverschmutzung). Entfernt
  zugleich grüne Hot-Pixel-/Stern-Sprenkel. Subtraktiv/treu, läuft VOR dem Strecken. +1 Test (49).
  (Reste wie schwache Amp-Glow-/Satelliten-Spur brauchen Dark-Frames — Kalibrierung.)

## [1.16.4] – 2026-06-26
### Behoben (Astro-Qualität — beim Verifikations-Lauf gefunden)
- **Standard-Ausrichtung war `shift` (nur Translation):** Bei realen Datensätzen mit Feldrotation
  führte das zu **länglichen, farbig getrennten Sternen** und einem flachen Bild (am IC 5146 / ASI294
  nachgewiesen). Standard ist jetzt **`rotate` (Translation + Feldrotation)** — korrigiert auch
  gedrehte Felder, funktioniert ebenso bei reiner Nachführung. Sterne werden rund.
- **Hot-/Cold-Pixel-Korrektur standardmäßig an:** entfernt die farbigen Einzelpixel-Punkte
  (Bayer-/Sensor-Hotpixel), die vorher als Farbsprenkel sichtbar waren.
- Astro-Screenshot = realer IC 5146 (Kokonnebel) mit runden Sternen.

## [1.16.3] – 2026-06-26
### Behoben (CI)
- **tests.yml:** `psdtags` fehlte unter den CI-Abhängigkeiten → der neue Ebenen-TIFF-Regressionstest
  brach in GitHub Actions (lokal grün). psdtags ergänzt; Test überspringt zusätzlich sauber, falls
  psdtags fehlt. CI wieder grün.

## [1.16.2] – 2026-06-26 — Beta-Stabilisierung
### Behoben (beim Verifikations-Lauf gefunden)
- **Photoshop-Ebenen blieben bei EXIF-Übernahme erhalten:** Die eingebaute EXIF-Übernahme schrieb
  TIFFs neu und hätte dabei ein **Ebenen-TIFF flachgemacht** (Photoshop-ImageSourceData verloren).
  Solche Dateien werden jetzt erkannt (Tag 37724) und beim EXIF-Schreiben übersprungen — Ebenen
  bleiben erhalten. Regressionstest ergänzt (48 Tests).
### Geändert (Doku)
- **README EXIF-Bullet präzisiert** (DE/EN): „EXIF/Provenienz wird übernommen, wo möglich — JPEG mit
  EXIF, TIFF mit Kern-Provenienz, vollständige TIFF-Metadaten optional via exiftool" statt pauschal
  „EXIF bleibt erhalten".
### Verifiziert (echte Daten, lokal auf macOS)
- Makro-Stack (JPG-Serie) + Ghost-Map · Export JPG/16-bit-TIFF/Photoshop-Ebenen-TIFF + EXIF-Übernahme
  · Seestar-FITS M 42 (GRBG, Feldrotation, Farbe) · ASI294MC-FITS IC 5146 (RGGB-Auto-Erkennung,
  Translation, Farbe) · Sony-ARW-Entwicklung (16-bit + EXIF) · Streamed-Ghost-Map. KI-Pfad end-to-end
  über Spark (Qwen3.6-27B). Offen: native Win/macOS-Starttests (nur CI-Build); Stern-Farbfransen bei
  OSC = Feinschliff.

## [1.16.1] – 2026-06-26
### Hinzugefügt (Astro-Aufbereitung: einstellbar + KI)
- **Drei Astro-Regler für das Vorschau-Bild — Auto (KI) oder manuell:** **Aufhellung** (5–30),
  **Sättigung** (1.0–1.6) und **Farbkalibrierung** (0–1). Standard = „Aufbereitung automatisch
  (KI / Standard)": die KI erkennt jetzt auch den **Farbstich** und schlägt die Farbkalibrierung
  vor (zusätzlich zu Aufhellung/Sättigung). Haken entfernen → alles selbst einstellen
  (GUI-Regler bzw. CLI `--astro-bright/--astro-saturation/--astro-color`). Werte werden gemerkt.
- `astro.color_balance(strength)` ist jetzt **blendbar** (0 = aus … 1 = voll). Wirkt nur aufs
  Vorschau-JPG; lineare Exports bleiben faithful.
- +1 Test (47). Ordner-Hinweis: Build-Artefakte sind bereits per `.gitignore` ausgeschlossen.

## [1.16.0] – 2026-06-26
### Hinzugefügt / Geändert (Astro-Farbe & -Qualität)
- **Debayering von OSC-FITS:** Farbkameras (Seestar, ZWO ASI …) liefern Bayer-Rohdaten als 2D-FITS
  — die wurden bisher als Graustufen gelesen (graues Ergebnis). Jetzt wird debayert → **echte Farbe**.
- **Bayer-Muster-Auto-Erkennung:** `BAYERPAT` wird aus dem Header gelesen; fehlt er, wird das Muster
  **selbst erkannt** (probiert alle 4, wählt das mit den geringsten Farb-Artefakten). Verifiziert:
  GRBG (Seestar) und RGGB (ASI294MC) korrekt aus den Rohdaten erkannt.
- **Farbkalibrierung fürs Vorschau-Bild:** Hintergrund pro Kanal neutralisieren + Sterne neutral
  abgleichen → gegen den Rotstich von OSC/LP-Filter, echte Nebelfarben (blaue Reflexion, rotes Ha).
  Die linearen Exports (16/32-bit, FITS) bleiben faithful für GraXpert/StarNet/PixInsight.
- **Highlight-/Kern-Schutz beim Strecken:** helle Bereiche werden sanfter gestreckt (Kern bleibt
  strukturiert statt weißem Klecks) + leichter Farb-Boost.
- **KI schlägt Aufhellung fürs fertige Astro-Bild vor** (Stärke/Sättigung/Kern-Schutz), mit der
  ausdrücklichen Vorgabe, den Kern NICHT weiter aufzuhellen — nur das schwache Signal.
- +3 Tests (46 gesamt). Echter M 42-Stack (Seestar, Feldrotation, Spark-KI) als 03_astro.png.

## [1.15.1] – 2026-06-26
### Behoben (kritisch)
- **Ergebnis-Anzeige stürzte ab:** Seit der Modularisierung (v1.10.1) fehlte in `ui/result_view.py`
  der Import von `IMG_EXTS` — `_find_result`/`_show_result` warf nach **jedem** Lauf einen
  `NameError`, das Ergebnis wurde nicht angezeigt. Import ergänzt. Neuer Regressionstest deckt
  den kompletten Anzeige-Pfad ab; pyflakes-Scan bestätigt: keine weiteren fehlenden Importe.
### Geändert
- **Echter Astro-Screenshot:** `03_astro.png` zeigt jetzt einen realen ForgePix-Stack von **M 42
  (Orion)** aus 49 Seestar-Subs (Feldrotation + Sigma-Rejection), inkl. KI-Sub-Bewertung.

## [1.15.0] – 2026-06-26
### Hinzugefügt
- **EXIF auch in 16-bit-TIFF — ohne exiftool:** TIFF-Ausgaben bekommen jetzt die Kern-Provenienz
  (Kamera/Modell/Datum als Baseline-Tags + lesbare Zusammenfassung mit Brennweite/Blende/ISO/
  Belichtung in der Bildbeschreibung) eingebaut via `tifffile` — **pixelidentisch** (Lesen/Schreiben
  über tifffile, kein BGR/RGB-Swap). Die vollständige EXIF-Unter-IFD je Einzeltag bleibt der
  exiftool-Kür vorbehalten (wird automatisch bevorzugt, wenn vorhanden).
- **Geister-Karte auch bei großen/gestreamten Stacks:** Neue speicherschonende
  `disagreement_map_streamed()` (lädt EIN Frame nach dem anderen, Online-Varianz nach Welford,
  downscaled + ausgerichtet). Damit gibt es Ghost-Map/KI-Retusche-Hinweis jetzt auch im
  RAM-schonenden Großstack-Pfad (vorher dort nicht verfügbar).
- +2 Tests (42 gesamt).

## [1.14.3] – 2026-06-26
### Hinzugefügt (selbst-enthaltend)
- **EXIF-Übernahme ohne exiftool — mitgeliefert:** Kamera/Objektiv/Brennweite/Blende/ISO/Belichtung
  werden jetzt **eingebaut** auf die **JPEG-Ausgaben** übertragen (via `piexif`; Quelle JPEG/TIFF
  direkt oder RAW über die Kernfelder). Damit braucht der Installer **keine** Zusatz-Installation
  mehr für die EXIF-Übernahme. exiftool wird weiter automatisch **bevorzugt**, wenn vorhanden, und
  bleibt die Kür für vollständige Metadaten auf 16-bit-TIFF.
- `piexif` als Abhängigkeit (requirements + CI + Installer-Bundle). +1 Test (40 gesamt).

## [1.14.2] – 2026-06-26
### Hinzugefügt / Geändert
- **EXIF-Lesen ohne exiftool:** Brennweite/Blende/ISO/Belichtung (für DOF-Rechner, KI-Kontext,
  Modul-Erkennung) werden jetzt **eingebaut** via `ExifRead` (pure-Python, JPEG **und** RAW)
  gelesen — exiftool wird dafür **nicht mehr** gebraucht. exiftool bleibt nur noch für das
  **Übertragen** der vollständigen Metadaten auf die Ausgabedateien nötig (klar so dokumentiert).
  exiftool wird weiter bevorzugt, wenn vorhanden; sonst greift automatisch der Fallback.
- `ExifRead` als Abhängigkeit (requirements + CI + Installer-Bundle). +2 Tests (39 gesamt).
### Repo
- GitHub-Themen (Topics) gesetzt: focus-stacking, astrophotography, computational-photography u. a.
  (Repo-Beschreibung steht bereits korrekt auf „ForgePix (Beta) …").

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
