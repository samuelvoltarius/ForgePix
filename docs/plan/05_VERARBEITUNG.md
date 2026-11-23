# 05 — Verarbeitung: PixInsight, Siril, GraXpert, SetiAstro, RC-Astro, Makro

Stand 22.11.2026. Ausführlich in [../LUECKEN.de.md](../LUECKEN.de.md) und
[../CAPABILITY_STATUS.md](../CAPABILITY_STATUS.md).

Die Funktionsliste der anderen Programme ist **aus Kenntnis**, nicht heute nachgeschlagen.
Kein Bildqualitätsvergleich gegen sie ist gerechnet.

## Neu: der Arbeitsplatz (Menü „Bearbeitung → Arbeitsplatz …“, Strg+Umschalt+W)

Ein Bild offen, jedes Werkzeug darauf, wie in PixInsight und Siril:

* **49 Werkzeuge** (Stand 23.11.2026, abends) in **neun nummerierten Gruppen in der Reihenfolge eines
  üblichen Ablaufs** (1 Geometrie → 2 Hintergrund und Farbe → 3 Rauschen und Schärfe → 4 Strecken
  → 5 Sterne → 6 Mehrere Bilder → 7 Komet → 8 Externe Programme → 9 Eigene KI), durchsuchbar auch
  mit PixInsight-/Siril-/RC-Astro-Namen (`core/prozesse.py`). Jedes nennt sein Vorbild — als
  Wegweiser, nicht als Gleichwertigkeit — und **wann es hingehört** (vor dem Strecken, danach,
  oder egal). Nicht installierte Programme stehen grau mit Hinweis da.
* **Am Ausschnitt probieren**: rechnet nur die Bildmitte und zeigt vorher | nachher, ohne etwas
  zu übernehmen (wie die Previews in PixInsight).
* **Kurven** mit ziehbarem Editor; **Werkzeuge über mehrere Bilder** (PixelMath mit A/B/C, LRGB,
  Kontinuum abziehen mit geschätztem k, Kanal ersetzen) mit Dateifeld je zweitem Bild.
* **Jede Maske auf jedes Werkzeug** (Sterne, Hintergrund, Nebel, Helligkeitsbereich; umkehren,
  weicher Rand; anzeigbar). Nur Werkzeuge, die die Bildgröße ändern, lehnen Masken ab.
* **Rückgängig / Wiederholen** über alle Schritte; ältere Zwischenstände werden nachgerechnet
  statt gespeichert (ein 24-MP-Bild in Float32 sind 288 MB).
* **Verlauf als Rezept** speichern und auf ein anderes Bild anwenden; im gespeicherten FITS steht
  der Verlauf als HISTORY.
* **Bildschirm-Streckung (STF)**: streckt nur die Anzeige, nie die Daten. Pixelwerte unter dem
  Mauszeiger, Statistik je Kanal nach jedem Schritt.
* Die eigenen KI-Modelle stehen dabei, **ausdrücklich experimentell** und nur nach Zusage.

Gemessen am 22.11.2026: alle damals 37 Werkzeuge an einem echten Stapel (8 Seestar-Aufnahmen
IC 5146, 1884×1047) gelaufen — in Changelog und Commit stand irrtümlich 39, berichtigt am
23.11. Rückgängig/Wiederholen und das Nachspielen eines Rezepts ergeben bitgleich dasselbe Bild.
Zwei Fehler dabei gefunden und behoben (siehe 04_FEHLER). Am 23.11. die acht neuen an einem
frisch gerechneten Stapel derselben Aufnahmen: alle gelaufen, GraXpert echt in 6 s.

### Zuordnung

| Vorbild | im Arbeitsplatz |
|---|---|
| PixInsight DBE/ABE · Siril Background Extraction · GraXpert (klassisch) | Hintergrund ausgleichen |
| BackgroundNeutralization, ColorCalibration, SCNR, ColorSaturation | Hintergrund neutralisieren, Farbe abgleichen, Grünstich entfernen, Sättigung |
| HistogramTransformation/AutoSTF, GHS, ArcsinhStretch, DDP, ExponentialTransformation, LocalHistogramEqualization/CLAHE, Invert, Rescale | Strecken (MTF, GHS, asinh, DDP), Exponent, Lokaler Kontrast, Invertieren, Skalieren |
| TGVDenoise, MultiscaleLinearTransform, ATrousWaveletTransform, Deconvolution, UnsharpMask, Convolution, FFT, CanonBandingReduction, CosmeticCorrection | Entrauschen (TV/Wavelet), Schärfen (Wavelet), Dekonvolution, Unscharf maskieren, Weichzeichnen, Streifen, Banding, Hotpixel |
| Sterne verkleinern · StarXTerminator/StarNet · Siril Synthstar/Unclip · MorphologicalTransformation | Sterne verkleinern, Sterne entfernen (klassisch), Sternformen erneuern, Sternkerne färben, Morphologie |
| DynamicCrop, FastRotation, Resample, IntegerResample | Zuschneiden, Drehen, Spiegeln, Größe ändern, Binning |
| LarsonSekanina | Kometenstrukturen |
| PixelMath, LRGBCombination, ChannelCombination · SetiAstro Continuum Subtraction | PixelMath, Luminanz einsetzen, Kanal ersetzen, Kontinuum abziehen |
| CurvesTransformation, MaskedStretch | Kurven, Strecken (MaskedStretch) |
| GraXpert, Cosmic Clarity (die Programme selbst) | GraXpert, Cosmic Clarity: Schärfen |
| RC-Astro NoiseX / BlurX / StarX, GraXpert-AI | KI: Entrauschen / Schärfen / Sterne / Hintergrund (eigene Modelle, experimentell, **nicht gleichwertig**) |

## Was noch fehlt (Reihenfolge-Vorschlag)

1. [x] Mehrere Bilder im Arbeitsplatz: PixelMath, LRGB, Kanal ersetzen, Kontinuum (23.11.), mit
       Ausrichten über die Sterne (wie StarAlignment) und Maßstabsprüfung: eine echte Seestar-
       Aufnahme auf den Stapel gelegt, Übereinstimmung 0,07 → 0,955; 8 % anderer Maßstab wird
       abgelehnt (Gegenprobe ohne Prüfung: still übernommen).
2. [x] Am Ausschnitt probieren (23.11.). Offen: Ausschnitt selbst wählen statt Bildmitte.
3. [x] Kurven mit Punkten und Editor (23.11.). Offen: STF von Hand, Kurve über Sättigung/Farbton.
4. [x] MaskedStretch, ACDNR, HDRMultiscaleTransform, GradientsHDR (23.11., nach Beschreibung
       nachgebaut, nicht gegen PixInsight verglichen). Gegenproben: beide HDR-Werkzeuge lassen das
       Bild bei Stärke „aus“ exakt unverändert; ACDNR senkt das Farbrauschen im Hintergrund eines
       echten Stapels um 33 %.
5. [~] Farbkalibrierung ohne Siril (23.11.): photometrisch gegen Gaia BP-RP mit G2V-Weißpunkt
       (wie PixInsights PCC) im Arbeitsplatz, eigener Plate-Solve. Am künstlichen Himmel: ein
       eingebauter Kanalfehler (B×0,7, R×1,4) auf 0,2 % zurückgerechnet. **Echter SPCC** (Gaia-
       Spektren × Sensor-QE × Filterkurve) bleibt offen. An echten Daten ungeprüft (Gaia-Archiv
       am 23.11. in Wartung).
6. [x] Himmelsmosaik aus gelösten Bildern (23.11., Menü „Astro-Werkzeuge“): gemeinsames
       TAN-Raster, Umrechnung über die WCS, Hintergründe angeglichen, weiche Ränder. Am künstlichen
       Himmel: Versatz 0,03 erkannt, gedrehtes Panel sitzt. Offen: Plate-Solve ohne Hinweis.
7. [x] GraXpert, Cosmic Clarity und StarNet++ im Arbeitsplatz (23.11.; GraXpert echt gelaufen,
       Cosmic Clarity und StarNet hier nicht installiert, daher nicht echt geprüft).
8. [ ] KI-Werkzeuge gegen GraXpert / Cosmic Clarity an denselben Daten messen.
9. [ ] RC-Astro-Niveau: braucht neues Training mit echten Paaren — eigenes Vorhaben, Ergebnis offen.
       Freie Ausgangsmodelle: siehe 06_KI (NAFNet MIT, auf eigenen Aufnahmen nachtrainieren).

## Makro / Fotobearbeitung

1. [ ] Fokusschiene + Kamera steuern (siehe 01_AUFNAHME, Punkt 10).
2. [ ] Ebenen und Rückgängig im Camera-Raw-Editor (der Arbeitsplatz hat es, der Editor nicht).
3. [ ] Reparaturpinsel aus demselben Bild (Staub).
4. [ ] Farbmanagement durchgängig (Bausteine in `develop.py`, nicht angeschlossen).
5. [ ] Filmischer Tonwert und parametrische Masken in den Editor.
