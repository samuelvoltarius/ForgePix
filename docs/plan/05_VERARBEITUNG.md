# 05 — Verarbeitung: PixInsight, Siril, GraXpert, SetiAstro, RC-Astro, Makro

Stand 22.11.2026. Ausführlich in [../LUECKEN.de.md](../LUECKEN.de.md) und
[../CAPABILITY_STATUS.md](../CAPABILITY_STATUS.md).

Die Funktionsliste der anderen Programme ist **aus Kenntnis**, nicht heute nachgeschlagen.
Kein Bildqualitätsvergleich gegen sie ist gerechnet.

## Neu: der Arbeitsplatz (Menü „Bearbeitung → Arbeitsplatz …“, Strg+Umschalt+W)

Ein Bild offen, jedes Werkzeug darauf, wie in PixInsight und Siril:

* **39 Werkzeuge** in sechs Gruppen, durchsuchbar auch mit PixInsight-/Siril-/RC-Astro-Namen
  (`core/prozesse.py`). Jedes nennt sein Vorbild — als Wegweiser, nicht als Gleichwertigkeit.
* **Jede Maske auf jedes Werkzeug** (Sterne, Hintergrund, Nebel, Helligkeitsbereich; umkehren,
  weicher Rand; anzeigbar). Nur Werkzeuge, die die Bildgröße ändern, lehnen Masken ab.
* **Rückgängig / Wiederholen** über alle Schritte; ältere Zwischenstände werden nachgerechnet
  statt gespeichert (ein 24-MP-Bild in Float32 sind 288 MB).
* **Verlauf als Rezept** speichern und auf ein anderes Bild anwenden; im gespeicherten FITS steht
  der Verlauf als HISTORY.
* **Bildschirm-Streckung (STF)**: streckt nur die Anzeige, nie die Daten. Pixelwerte unter dem
  Mauszeiger, Statistik je Kanal nach jedem Schritt.
* Die eigenen KI-Modelle stehen dabei, **ausdrücklich experimentell** und nur nach Zusage.

Gemessen am 22.11.2026: alle 39 Werkzeuge an einem echten Stapel (8 Seestar-Aufnahmen IC 5146,
1884×1047) gelaufen; Rückgängig/Wiederholen und das Nachspielen eines Rezepts ergeben bitgleich
dasselbe Bild. Zwei Fehler dabei gefunden und behoben (siehe 04_FEHLER).

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
| RC-Astro NoiseX / BlurX / StarX, GraXpert-AI | KI: Entrauschen / Schärfen / Sterne / Hintergrund (eigene Modelle, experimentell, **nicht gleichwertig**) |

## Was noch fehlt (Reihenfolge-Vorschlag)

1. [ ] Mehrere Bilder im Arbeitsplatz: PixelMath, ChannelCombination/LRGB, Kontinuum abziehen
       (heute nur als eigene Dialoge außerhalb).
2. [ ] Vorschau-Ausschnitt: Werkzeug erst auf einem Ausschnitt probieren (PixInsight Previews).
3. [ ] Kurven-Werkzeug mit Punkten (CurvesTransformation) und STF von Hand.
4. [ ] MaskedStretch, ACDNR, HDRMultiscaleTransform, GradientsHDR.
5. [ ] SPCC ohne Siril (Gaia-Spektren × Sensor-QE × Filterkurve).
6. [ ] Himmelsmosaik (WCS-bewusst); Plate-Solve ohne Hinweis (Blindsuche).
7. [ ] GraXpert, StarNet und Cosmic Clarity als Werkzeuge im Arbeitsplatz (heute im Werkzeug-Menü).
8. [ ] KI-Werkzeuge gegen GraXpert / Cosmic Clarity an denselben Daten messen.
9. [ ] RC-Astro-Niveau: braucht neues Training mit echten Paaren — eigenes Vorhaben, Ergebnis offen.

## Makro / Fotobearbeitung

1. [ ] Fokusschiene + Kamera steuern (siehe 01_AUFNAHME, Punkt 10).
2. [ ] Ebenen und Rückgängig im Camera-Raw-Editor (der Arbeitsplatz hat es, der Editor nicht).
3. [ ] Reparaturpinsel aus demselben Bild (Staub).
4. [ ] Farbmanagement durchgängig (Bausteine in `develop.py`, nicht angeschlossen).
5. [ ] Filmischer Tonwert und parametrische Masken in den Editor.
