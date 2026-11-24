# 08 — Alles gut, nicht nur alles da: die Qualitätsprüfung

Stand 23.11.2026. Vorgabe von Alfred: **eine All-in-one-App, die alles kann — und zwar gut, nicht
nur alles etwas.** Dazu: **für alles freie Modelle nutzen, soweit es geht; wo wir es selbst nicht
nachbauen können, einen Download zu dem Projekt verlinken**, das die Leute selbst holen.

## Leitlinie

1. **Gut heißt gemessen.** Jedes Modul wird an echten Daten gegen sein Vorbild gemessen (gleiche
   Eingabe, gleiche Kennzahl), bevor es „gut“ heißt. Vorhandensein ist kein Qualitätsbeweis.
2. **Eigenes zuerst, frei lizenziert.** Wo wir es selbst bauen können: selbst bauen. Freie Modelle
   (MIT/Apache/BSD, siehe 06_KI) nur nach eigener Lizenzprüfung der Gewichte.
3. **Sonst verlinken, nie mitliefern.** Programme mit nicht-kommerziellen oder fehlenden
   Weitergaberechten (GraXpert-Modelle, StarNet, Cosmic Clarity, ASTAP-Datenbanken) ruft ForgePix
   nur auf; das Fenster „Zusatzprogramme“ zeigt, was fehlt, und verlinkt die offizielle Seite.

## Was zu prüfen ist (Reihenfolge-Vorschlag)

| Bereich | Vorbild | Kennzahl | Daten | Stand |
|---|---|---|---|---|
| Astro-Stapeln (Kalibrieren, Ausrichten, Integration) | Siril, PixInsight WBPP | Sternform (FWHM, Exzentrizität), Rauschen im Hintergrund, SNR, Abdeckung | D:\astro (Seestar, ASI294, ASI533) | **gegen Siril gemessen** (IC 5146, [../vergleich/SIRIL.md](../vergleich/SIRIL.md)): 29 % weniger Rauschen, 2 % breitere Sterne, 4× langsamer (war 10×); ASI294/533 offen |
| Automatik / Anfänger-Modus | — | richtige Moduswahl, sinnvolle Standardwerte, keine stillen Fehler | gemischte Ordner | offen |
| Fokus-Stacking (Makro) | Helicon Focus, Zerene Stacker | Schärfe je Region, Halos, Geister an Kanten | Makro-Fokusreihen (Beispieldaten-Download) | **gemessen** ([../vergleich/FOKUS.md](../vergleich/FOKUS.md)): Fokus überall getroffen, weniger Überzeichnung als focus-stack; Helicon/Zerene nicht da |
| Langzeitbelichtung aus Einzelbildern | Sequator, StarStaX, Photoshop-Mittelwert | Rauschen, Bewegungsunschärfe, Geister | Serien normaler Kameras | **gemessen** ([../vergleich/LANGZEIT.md](../vergleich/LANGZEIT.md)): exakt; aus der Hand jetzt 0,62/0,63 der Einzelbild-Schärfe (vorher 0,77/0,22) |
| RAW-Konverter | darktable, RawTherapee, Lightroom | Farbtreue (ΔE an Farbkarte), Rauschen, Details, Lichterrekonstruktion | RAW-Dateien mehrerer Kameras | Farbmanagement nicht durchgängig (05) |
| PixInsight-Werkzeuge (Arbeitsplatz) | PixInsight | je Werkzeug gleiches Bild, Differenzbild, Kennzahl | eigener Stapel | 50 Werkzeuge gebaut, kein Vergleich gegen PixInsight |
| KI (Entrauschen, Schärfen, Sterne, Hintergrund) | RC-Astro, GraXpert, Cosmic Clarity | Rauschen, Sternfluss, Artefakte | eigener Stapel | eigenes Entrauschen gemessen, Rest schlechter als klassisch |

## Testdaten (23.11.2026 besorgt)

Siehe [../TESTDATEN.md](../TESTDATEN.md): RAW von 18 Herstellern (CC0), zwei freie Fokusreihen
(eine mit Referenz-Ergebnis), ein CC0-Wasserfall-Video für Langzeit, die eigenen Beispieldaten.
Holen mit `python3 testdaten_holen.py`.

### Ergebnisse bisher

| Bereich | Ergebnis | Folge |
|---|---|---|
| RAW-Lesen | 19/20 Dateien von 18 Herstellern + A7 V/A7 III; GoPro .gpr nicht | Endungsliste ergänzt (Hasselblad/Phase One wurden nicht erkannt), GPR-Meldung mit Link |
| RAW-Aussehen | vorher: Helligkeit im Median **0,58** der Kamera-Vorschau. Mit „Wie die Kamera“ (`core/kameralook.py`, jetzt Vorgabe): **0,989** (0,81 … 1,28), echtes Weiß-Clipping wie neutral, Farbe im Mittel ±5 % | erledigt; Ausreißer Leica Q2 1,28 und Phase One 0,81 offen |
| Astro gegen Siril | Rauschen 4,3·10⁻⁵ gegen 6,0·10⁻⁵, HFR 2,056 gegen 2,011 px, 21 s (war 51 s) gegen 5 s | Stapeln in Streifen: 30 s → 10 s, bitgenau gleich; Farbrekonstruktion und Ausrichten als Nächstes |
| Camera-Raw-Editor | Rauschminderung, Color Grading, Vignette, Körnung, Perspektive ergänzt; je Regler eine gemessene Wirkung (`tests/test_camera_raw_editor.py`) | stille Fehler bei Dunst/Schärfe behoben |
| Fokus-Stacking | Platine: alle Methoden 0 % verpasster Fokus (focus-stack 2,6 %), 11–22 % überzeichnet (focus-stack 47 %) | `average` war ein Weichzeichner (0,33, 100 % verpasst) → behoben (1,07, 0,7 %) |
| HDR | altes HDR schlechter als das Einzelbild (Helligkeit 0,44, 14 % fast schwarz); jetzt 1,00, ausgebrannt 0,10 % (Kamera 0,51 %), Zeichnung Lichter/Schatten 0,71/1,14 (Kamera 0,33/0,53) | Reihenerkennung (462 → 1 Reihe) behoben; Geister offen ([../vergleich/HDR.md](../vergleich/HDR.md)) |
| Langzeit | Mittel/Median exakt; Freihand-Video: neue Ausrichtung „perspective“ hält beide Felsen bei 0,6 (Stern-Ausrichtung ließ einen bei 0,22) | Moduswahl (declutter beim Wasserfall) offen |

## Camera Raw: was zu „vollständig“ fehlt (Stand 23.11.2026)

Durchgeprüft am 23.11.2026: „im Editor“ heißt, der Regler steht im Fenster Bearbeiten →
Camera-Raw (`ui/components.AdjustDialog`) und seine Wirkung ist in `tests/test_camera_raw_editor.py`
oder `tests/test_engines.py` an einem Bild gemessen. „RAW-Teil“ heißt: beim Entwickeln im
Hauptfenster einstellbar, nicht im Editor.

| Funktion (Lightroom/Camera Raw) | ForgePix | Stand |
|---|---|---|
| Aussehen ab Werk („Adobe Farbe“) | Kamera-Look aus der eingebetteten Vorschau | gemessen, 0,989 der Kamera |
| Weißabgleich, Belichtung, Tonwerte (Lichter/Schatten/Weiß/Schwarz) | Temperatur/Tönung + Tonwert-Regler | im Editor |
| Lichter-Rekonstruktion | `highlight_reconstruct` | RAW-Teil |
| Gradationskurve | ziehbare Kurve | im Editor |
| Klarheit, Dunst entfernen, Capture-Schärfung | `local_contrast`, `dehaze`, `capture_sharpen` | im Editor; Fehler werden jetzt angezeigt statt verschluckt |
| Rauschminderung Luminanz/Farbe | `denoise_chroma_luma` | **neu im Editor**; Luminanz 50: Rauschen 0,030 → 0,014, Kante bleibt |
| Farbmischer HSL | 8 Farbbänder × Farbton/Sättigung/Luminanz | im Editor (stand vorher fälschlich als fehlend hier) |
| Color Grading (Schatten/Mitten/Lichter, Balance) | `color_grade` | **neu im Editor**; Helligkeit bleibt (Abweichung < 0,01) |
| Effekt-Vignette, Körnung | `vignette_effect`, `add_grain` | **neu im Editor**; Korn in Vorschau = Korn im Vollbild (±15 %) |
| Perspektive senkrecht/waagerecht, Drehen, Beschneiden | `perspective` + Geometrie | **neu im Editor**; automatisches Upright fehlt |
| Objektivkorrektur (Profil, Vignette, Verzeichnung, CA) | lensfun + manuell | RAW-Teil |
| Masken: Pinsel, Auto-Maske | im Editor | im Editor |
| Verlaufs-/Radialfilter, Bereichsmasken | `gradient_mask`, `radial_mask`, `parametric_mask` | nur Baustein, nicht im Editor |
| Kamera-Kalibrierung an Farbkarte (ΔE) | Fuji X-T4-Datei mit ColorChecker liegt in `testdata/raw` | fehlt, als Nächstes messbar |
| Reparieren / Stempel | Retusche holt nur scharfe Stellen aus einem Quellfoto (Fokus-Stacking) | fehlt |
| KI-Masken (Motiv, Himmel) | — | fehlt; nur mit freiem Modell (06_KI) |
| Verlauf/Schnappschüsse, Einstellungen auf viele Bilder übertragen | im Arbeitsplatz (Rezepte), nicht im RAW-Teil | teilweise |
| Durchgängiges Farbmanagement (ICC in der Ausgabe) | Arbeitsfarbraum-Funktionen da | nicht durchgängig (05) |

## Was dafür gebraucht wird

* **Daten**: je Bereich ein echter Datensatz (Makro-Reihe, Langzeit-Serie, RAW-Dateien mit
  Farbkarte). Für Astro ist D:\astro da; für Makro/Langzeit/RAW bitte Ordner nennen.
* **Vergleichsprogramme**: Siril und GraXpert sind auf dem Testrechner; PixInsight,
  Helicon/Zerene, darktable nicht — ohne sie bleibt der Vergleich einseitig (nur Kennzahlen).
