# PixInsight gegen ForgePix — Prozess für Prozess

*[🇬🇧 English version](PIXINSIGHT.md)*

## Woher die Liste stammt

Die offizielle Dokumentation unter `pixinsight.com/doc/` antwortet auf direkte Abrufe mit
**HTTP 403**. Ein früherer Anlauf hat darum eine Liste geliefert, die auf 404-Fehlerseiten
beruhte — also auf gar nichts.

Diese Liste hier kommt aus dem **Quelltext**: die PixInsight Class Library (PCL) ist offen, und
jeder Prozess liegt dort als `…Process.cpp` in `src/modules/processes/`. Ausgezählt wurden vier
öffentliche Spiegel des Repositories; die Vereinigung ergibt **91 Prozesse**, jeder mit Datei
belegt.

**Was dabei fehlt, und das ist wichtig:** die PCL enthält nur die OFFENEN Module. Einige der
bekanntesten PixInsight-Prozesse sind geschlossen und tauchen dort nicht auf — `Deconvolution`,
`MultiscaleLinearTransform`, `MultiscaleMedianTransform`, `ATrousWaveletTransform`, `TGVDenoise`,
`ACDNR`, `SCNR`, `StarMask`, `RangeSelection`, `StarAlignment`, `DynamicAlignment`. Sie stehen
unten in einem eigenen Abschnitt und sind dort als **aus Kenntnis, nicht aus einer Quelle**
gekennzeichnet.

Zeichen: ✅ vorhanden · 🟡 teilweise · ❌ nicht vorhanden · ➖ für ForgePix nicht sinnvoll

---

## Kalibrieren und Stapeln

| PixInsight | ForgePix | |
|---|---|---|
| ImageCalibration | `astro.calibrate` (Dark/Flat/Bias), Dark-Skalierung mit Bias-Sockel | ✅ |
| ImageIntegration | `astro.stack` — sigma, winsor, linearfit, average, median, max; SNR-Gewichtung; gemischte Belichtungszeiten | ✅ |
| DrizzleIntegration | `astro.drizzle_stack` (echtes Drizzle mit pixfrac) | ✅ |
| LocalNormalization | `astro.local_normalize` (örtliche Hintergrundfläche) | ✅ |
| CosmeticCorrection | `astro.cosmetic_correct` + `sensor.defektkarte` (ohne Darks aus den Lights) | ✅ |
| DefectMap | `sensor.karte_laden` / `sensor.defekte_ersetzen` | ✅ |
| Debayer | `astro.detect_bayer` + Demosaic-Pfad | ✅ |
| SubframeSelector | `astro_quality.select_subs` (FWHM, Sternzahl, Rundheit, Wolken, Spuren) | ✅ |
| CometAlignment | `komet.stack_auf_kern` — findet den Kern **selbst**, PixInsight verlangt Anklicken | ✅ |
| HDRComposition | `hdr.py` (Exposure Fusion, Deghosting, Tonemapping) | ✅ |
| Superbias | ❌ — Bias-Master durch Hauptkomponenten glätten | ❌ |
| SplitCFA / MergeCFA / CFA2RGB | ❌ — CFA-Ebenen einzeln bearbeiten | ❌ |
| StarGenerator | ➖ synthetische Sternfelder (nur in ForgePix-Tests) | ➖ |

## Registrieren

| PixInsight | ForgePix | |
|---|---|---|
| StarAlignment *(geschlossen)* | `astro.register_and_cache` — Dreiecksabgleich, Rotation, Cluster-Brücke für Dither-Sprünge, beste Referenz automatisch | ✅ |
| DynamicAlignment *(geschlossen)* | `astro._tps_refine` (Thin-Plate-Spline für Restverzeichnung) | ✅ |
| ChannelMatch | 🟡 über dieselbe Registrierung, kein eigener Prozess | 🟡 |
| Geometry (Crop, Resample, Rotation, IntegerResample, DynamicCrop, FastRotation) | 🟡 `stacker.crop`, `crop_to_overlap`, `astro.bin_image` — kein freies Geometrie-Werkzeug | 🟡 |

## Hintergrund und Farbe

| PixInsight | ForgePix | |
|---|---|---|
| BackgroundNeutralization | `astro.neutralize_background` | ✅ |
| ColorCalibration | `astro.color_balance` | ✅ |
| PhotometricColorCalibration | `photometric.run_pcc` — Siril-SPCC, astroquery-Gaia, **eigener lokaler Gaia-Auszug (offline)**, Lite | ✅ |
| LinearFit | `astro.linear_match` (robust, mit Ausreißer-Verwurf) | ✅ |
| SCNR *(geschlossen)* | `astro.remove_green_cast` | ✅ |
| Gaia | `gaia_lokal` — eigener Katalogauszug mit Zellenindex, rund 100× schneller als eine Serverabfrage | ✅ |
| APASS | ❌ — zweiter Photometriekatalog | ❌ |
| DynamicBackgroundExtraction *(Skript/geschlossen)* | `astro.background_extract` (RBF, **kanalweise**, Subtraktion oder Division) | ✅ |
| ColorSaturation | 🟡 als Regler in den Streckungen, keine Kurve über den Farbton | 🟡 |
| ColorManagement (ICC, RGBWorkingSpace, ColorManagementSetup) | ➖ ForgePix arbeitet in sRGB | ➖ |

## Strecken und Tonwerte

| PixInsight | ForgePix | |
|---|---|---|
| HistogramTransformation | `astro.mtf_stretch` (MTF, definierter Schwarzpunkt) | ✅ |
| ScreenTransferFunction | `astro.autostretch` | ✅ |
| ArcsinhStretch | `astro.autostretch` (asinh) | ✅ |
| CurvesTransformation | `develop.py` (PCHIP-Tonwertkurven) | ✅ |
| AutoHistogram | `astro.autostretch` | ✅ |
| MaskedStretch | 🟡 `astro.stretch_starless` verfolgt dasselbe Ziel (Sterne klein halten) auf anderem Weg | 🟡 |
| AdaptiveStretch | 🟡 `astro.ghs_stretch` (Generalised Hyperbolic) | 🟡 |
| ExponentialTransformation | 🟡 `astro.ddp` (Okano) ist verwandt, nicht dasselbe | 🟡 |
| LocalHistogramEqualization | `astro.local_contrast` (CLAHE, **nur auf der Helligkeit**) | ✅ |
| Binarize / Invert / Rescale | ➖ Einzeiler, kein eigener Prozess nötig | ➖ |
| — | `astro.stretch_preserve_color` — Kanalverhältnisse bleiben. **Hat PixInsight so nicht** | ⭐ |
| — | `astro.ddp` mit gemessenem 2,2-fachem Nebelkontrast bei gleicher Ausbrennung | ⭐ |

## Rauschen und Schärfe

| PixInsight | ForgePix | |
|---|---|---|
| MultiscaleLinearTransform / ATrousWaveletTransform *(geschlossen)* | `wavelet.py` (à-trous, Multi-Skalen) | ✅ |
| TGVDenoise *(geschlossen)* | `astro.tv_denoise` (Total Variation, kantenerhaltend) | ✅ |
| ACDNR *(geschlossen)* | 🟡 über `tv_denoise` + Masken abgedeckt, kein eigener Prozess | 🟡 |
| GREYCstoration | 🟡 dasselbe wie oben | 🟡 |
| Deconvolution *(geschlossen)* | `astro.deconvolve` (Richardson-Lucy, PSF aus dem Bild, TV-Regularisierung, Sternschutz) | ✅ |
| RestorationFilter | 🟡 Wiener/Constrained Least Squares — über die Dekonvolution abgedeckt | 🟡 |
| UnsharpMask | `develop.py`, `wavelet.py`, optional in `astro.ddp` | ✅ |
| Convolution | 🟡 intern vorhanden, nicht als Werkzeug | 🟡 |
| MorphologicalTransformation | 🟡 `astro.reduce_stars` nutzt sie gezielt für Sterne | 🟡 |
| LarsonSekanina | ❌ — Rotationsgradient für Kometen- und Sonnendetails | ❌ |
| FourierTransform / InverseFourierTransform | ❌ | ❌ |

## Sterne

| PixInsight | ForgePix | |
|---|---|---|
| StarNet | `starless.py` (extern, optional) + `astro.remove_stars` (klassisch, ohne KI) | ✅ |
| StarMask *(geschlossen)* | `masken.sterne` — mit Mindestfläche und Rundheitsfilter | ✅ |
| DynamicPSF | `astro.estimate_psf` (empirisch aus vielen Sternen) | ✅ |
| — | `astro.synthstar` — Sternformen durch runde Moffat-Profile ersetzen. **Hat PixInsight so nicht** (Siril schon) | ⭐ |
| — | `astro.unclip_stars` — Farbe ausgefressener Kerne aus den Flanken | ⭐ |
| — | `astro.reduce_stars` — Sterne verkleinern | ⭐ |

## Masken

| PixInsight | ForgePix | |
|---|---|---|
| StarMask *(geschlossen)* | `masken.sterne` | ✅ |
| RangeSelection *(geschlossen)* | `masken.helligkeit` | ✅ |
| — | `masken.hintergrund`, `masken.nebel` — fertige Masken für die zwei Fälle, um die es wirklich geht | ⭐ |
| Maskenlogik allgemein (jeder Prozess durch jede Maske) | 🟡 `masken.anwenden` gibt es, aber nur die Astro-Schritte sind daran angebunden | 🟡 |

## Messen

| PixInsight | ForgePix | |
|---|---|---|
| AberrationInspector | `sensor.feldkarte` / `feld_urteil` — **trennt Bildfeldkrümmung von Sensorverkippung** | ✅ |
| Statistics | 🟡 in `astro_quality` enthalten, kein eigenes Werkzeug | 🟡 |
| FITSHeader | 🟡 nur lesend (`equipment.aus_header`, `filters.aus_header`) | 🟡 |
| Blink | ❌ — Aufnahmen schnell durchblättern | ❌ |
| StarMonitor | ❌ — Sternqualität während der Aufnahme verfolgen | ❌ |
| FluxCalibration | ❌ — absolute Flusskalibrierung | ❌ |
| — | `photometrie.lichtkurve` + AAVSO-Export + Periodensuche. **Hat PixInsight so nicht** (dort über Skripte) | ⭐ |
| — | `equipment.py` — Abbildungsskala, Sampling-Urteil, Reducer, Dithering-Erkennung, eigene Geräte | ⭐ |
| — | `filters.py` — 20 Filter mit belegten Bandbreiten, Palette-Plausibilität | ⭐ |
| — | `livestack.py` — inkrementelles Stapeln während der Aufnahme | ⭐ |

## Sonstiges

| PixInsight | ForgePix | |
|---|---|---|
| **PixelMath** | ❌ — **die grösste echte Lücke.** Beliebige Ausdrücke über Bilder, das Universalwerkzeug schlechthin | ❌ |
| CloneStamp | 🟡 Retusche-Pinsel in der Oberfläche (aus einer anderen Aufnahme, nicht aus demselben Bild) | 🟡 |
| GradientsMergeMosaic | 🟡 `mosaic.py` (Panorama, nicht auf Himmelsmosaike ausgelegt) | 🟡 |
| GradientsHdr / GradientsHdrComposition | ❌ | ❌ |
| Annotation / FindingChart | ❌ — Objektnamen ins Bild schreiben, Aufsuchkarte | ❌ |
| EphemerisGenerator / B3E | ❌ — Bahnrechnung, Blackbody-Extrapolation | ❌ |
| INDICCDFrame / INDIDeviceController / INDIMount | ❌ — **Gerätesteuerung.** Eigenes Vorhaben; N.I.N.A. hat eine HTTP-API, Seestar geht über ASCOM Alpaca | ❌ |
| NetworkService / Preferences / ReadoutOptions / FilterManager | ➖ | ➖ |
| ChannelCombination / ChannelExtraction / LRGBCombination | 🟡 `astro._extract_ha_oiii` und die vier Paletten decken den Dual-Band-Fall ab, es fehlt das allgemeine Werkzeug | 🟡 |
| CreateAlphaChannels / ExtractAlphaChannels / NewImage / SampleFormatConversion / ImageIdentifier | ➖ | ➖ |
| NoiseGenerator / SimplexNoise | ➖ | ➖ |
| ICCProfileTransformation / AssignICCProfile | ➖ | ➖ |
| AssistedColorCalibration | ➖ durch PCC abgedeckt | ➖ |

---

## Was ForgePix hat und PixInsight nicht

Der Vergleich läuft in beide Richtungen. Diese Punkte gibt es dort nicht oder nur über Skripte:

- **Farberhaltende Streckung** (`stretch_preserve_color`): nur die Helligkeit läuft durch die
  Kurve. An echten Dual-Band-Daten stieg die Sättigung von 0,075 auf 0,510.
- **Starless-Streckung mit linearer Rückgabe der Sterne**: Nebel +22 %, ausgebrannte Pixel
  14× weniger.
- **Kometenkern wird selbst gefunden** — PixInsight und Siril verlangen zwei Klicks.
- **`synthstar`** — Sternformen neu setzen (Siril hat es, PixInsight nicht).
- **Sensordiagnose ohne Kalibrierframes**: Defektkarte aus den Lights, Feldkarte, die Krümmung
  von Verkippung trennt.
- **Ausrüstungsrechnung**: Abbildungsskala, Sampling-Urteil, Reducer, Dithering-Erkennung.
- **Filterdatenbank** mit belegten Bandbreiten und der ehrlichen Warnung, wenn eine Palette
  physikalisch nicht geht (SHO ohne SII).
- **Inkrementelles Live-Stacking** mit gesichertem Zwischenstand.
- **Lichtkurven und AAVSO-Export** unmittelbar aus derselben Serie.
- **Lokaler Gaia-Auszug** für Farbkalibrierung ohne Internet.
- **Alles in einer Oberfläche, die für Anfänger gebaut ist** — ein Klartext-Bildstil statt
  fünfzig Prozessfenster.

## Die drei ehrlichen Lücken

1. **PixelMath.** Ein Ausdrucksrechner über Bilder ist das Werkzeug, mit dem sich in PixInsight
   alles bauen lässt, was kein eigener Prozess ist. Das fehlt hier vollständig.
2. **Allgemeine Maskenlogik.** Die Bausteine stehen (`core/masken.py`), aber nur die
   Astro-Schritte sind daran angebunden. In PixInsight lässt sich JEDER Prozess durch JEDE Maske
   anwenden.
3. **Gerätesteuerung.** INDI/ASCOM ist ein eigenes Vorhaben. Der pragmatische Weg bleibt, die
   AUSGABE der Geräte zu verwerten — der Beobachtungsmodus auf deren Ausgabeordner ist da.

Dazu die kleineren: Superbias, APASS, LarsonSekanina, Fourier-Werkzeuge, Blink, Annotation,
FluxCalibration, CFA-Ebenen einzeln.
