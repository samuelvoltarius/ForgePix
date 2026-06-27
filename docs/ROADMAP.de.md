# ForgePix Roadmap — auf Augenhöhe mit Profi-Tools

*[🇬🇧 English version](ROADMAP.md)*

Audit jedes ForgePix-Moduls gegen die führenden Profi-Tools, mit konkretem, priorisiertem Nachbau-Plan.
Recherchiert aus Helicon/Zerene/PetteriAimonen (Fokus), AutoStakkert/PlanetarySystemStacker
(Lucky-Imaging), Siril/PixInsight/APP/DSS (Astro), Photomatix/Sequator/Hugin (HDR/Spuren/Pano) und
RawTherapee/darktable (RAW-Entwicklung). Alle Empfehlungen sind in Python/OpenCV/NumPy umsetzbar
(+ astropy/scikit-image/pywt/lensfunpy), MIT-kompatibel.

## Die eine modulübergreifende Erkenntnis

**Lokale (nicht-rigide) Ausrichtung** ist die *eine* Technik, die Amateur- von Profi-Ergebnissen trennt —
und sie fehlt in ForgePix überall (wir richten nur global aus). Sie ist die Ursache für:
- Fokus-Stacking-Geister (Pyramide verdoppelt bei kleinster Fehlausrichtung / Focus-Breathing),
- die Lucky-Imaging-Weichheit (global kann das lokale Seeing nicht korrigieren),
- HDR-Geister und Astro-Feldverzeichnung.

Das Fundament ist also ein gemeinsames **`core/align_local.py`**: global ausrichten → lokal verfeinern
(ECC subpixel + gedeckelter dichter Optical-Flow / Patch-Korrelation). Das hebt mehrere Module auf einmal.

## Was delegiert bleibt (NICHT nachbauen)

KI-Modelle sind das Produkt ihrer Hersteller und nicht reproduzierbar: **GraXpert** (Gradient + Entrauschen),
**StarNet++** (Sterne entfernen), **BlurXTerminator** (Dekonvolution), **Topaz/DxO** (Entrauschen). ForgePix
bindet die freien schon ein und exportiert lineares 16/32-bit + FITS für saubere Übergabe. Das bleibt so.

---

## 1. Fokus-Stacking (vs Helicon, Zerene, PetteriAimonen/focus-stack)

**Jetzt:** Pyramide + Depth-Map; globale Ausrichtung (rigid/homography/subject/sequential); Baum-Merge;
Culling; Geister-/Fokus-Karten. **Schwäche:** keine lokale Ausrichtung; Pyramide geistert bei winziger
Fehlausrichtung; kein gewichteter Mittelwert; keine Halo-Retusche.

| Priorität | Bauen | Skizze |
|---|---|---|
| P0 | **ECC-Subpixel-Verfeinerung + Frame-Verwerfung** | `cv2.findTransformECC` mit ORB/RANSAC-Matrix vorbelegen (helligkeitsinvariant); Nachbar-Kette mit verketteten Transformationen; nach Korrelationskoeffizient verwerfen |
| P1 | **Lokale nicht-rigide Ausrichtung** | wo ECC-Residuum hoch: gedeckelter `DISOpticalFlow` + `cv2.remap` (grob→fein) — tötet Pyramiden-Geister & ungleichmäßiges Breathing |
| P2 | **Konsistenz-gewählter Wavelet-Merge** | je Frame komplexes/`pywt`-Wavelet → Betrags-Maximum → Mehrheits-Vote unter Nachbarn/Subbändern → Wavelet-Entrauschen (PetteriAimonen-Rezept; größter Rausch-/Geister-Gewinn ggü. naiver Pyramide) |
| P3 | **Method A (gewichteter Mittelwert)** | Schärfemaß (SML/Tenengrad) → normierte Gewichte → `Σ wᵢ·fᵢ/Σ wᵢ`; Radius + Smoothing freigeben. Rauscharmer Standard für kurze Stacks |
| P4 | **Farb-Neuzuweisung** | auf Luminanz verschmelzen, echtes RGB aus dem best passenden Quellframe holen (keine erfundenen Farben/Halos) |
| P5 | **Halo-Retusche + Slabbing** | Doppel-Ausgabe (Depth-Map-Basis + Pyramiden-Detail) auto-komponieren/Pinsel; 100+ Frames in Slabs → Slabs per Depth-Map vereinen |

---

## 2. Lucky Imaging — Sonne/Mond/Planeten (vs AutoStakkert, PlanetarySystemStacker)

**Jetzt:** naiv — global Phasenkorrelation + mitteln. **Gemessener Fehlschlag:** weicher als das beste
Einzelbild (Laplace-Var ~4 vs ~13), weil global das lokale Seeing nicht korrigiert. **Fix = Multi-Point (MAP).**

| Priorität | Bauen | Skizze |
|---|---|---|
| P0 | **Multi-Point-(MAP)-Pipeline** | global ausrichten → Mittelbild als Referenz; versetztes **AP-Raster** (nur APs mit Struktur: `min(mean|∂x|,mean|∂y|) > t`); **pro AP** lokale Qualität ranken → Top-K Frames *je Region*; pro AP Subpixel-Versatz (`matchTemplate` grob→fein + Parabel); je Patch mitteln; Hann-gewichtet blenden, Mittelbild füllt Lücken |
| P1 | **À-trous-Wavelet-Schärfung** (RegiStax-Stil) | B3-Spline `[1,4,6,4,1]/16` je Ebene dilatiert → 5–6 Detail-Layer mit Gain + Fein-Layer-Entrauschen. Ersetzt das einzelne Unsharp |
| P2 | optional | Multi-Skalen-AP-Raster; Drizzle 1,5×/2× (nur bei Unterabtastung) |

**Ehrliche Messlatte:** MAP-Stack-Schärfe **≥ bestes Einzelbild** UND Rauschen **≪** Einzelbild
(beides messen; Laplace-Var allein trügt — Wavelet-Schärfung bläht sie auf).

---

## 3. Astro Deep-Sky (vs Siril, PixInsight, APP, DSS)

**Jetzt:** Kalibrierung, Debayer, Stern-Offset-Voting-Registrierung, Sigma/Winsor-Stacking, SCNR, Dual-Band-
Paletten, asinh-Stretch, GraXpert/StarNet/Siril-Übergabe. **Schwäche:** nur globale Registrierung, keine
lokale Normalisierung, keine photometrische Farbkalibrierung, nur asinh.

| Priorität | Bauen | Skizze |
|---|---|---|
| P1 | **Lokale Normalisierung** (größter Integrations-Gewinn) | pro Frame grobes Gitter-Modell für Hintergrund+Skala (niedriggradiges Polynom/RBF, Stern-maskiert) *vor* der Rejection — fixt Gradienten & Mehrfach-Sessions |
| P2 | **GHS-Stretch** (generalisiert hyperbolisch) | analytische Familie `f(x;D,b,SP,LP,HP)` mit explizitem Tiefen-/Lichter-Schutz; aus Median+MAD seeden; reversibel. MTF als einfacher Modus |
| P3 | **Photometrische Farbkalibrierung (PCC)** | Plate-Solve → Gaia DR3 (`astroquery`) → Apertur-Photometrie (`photutils`) → Kanal-Skala; „an Siril SPCC delegieren" als Fallback |
| P4 | **Lokale/Verzeichnungs-Registrierung** | Dreiecks-/Asterismus-Matching + Thin-Plate-Spline-Warp auf Stern-Residuen (`RBFInterpolator(thin_plate_spline)` + `cv2.remap`); intensitätsgewichtete Schwerpunkte |
| P5 | **Linear-Fit-Clipping** + **echtes Drizzle** | Geraden-Fit-Rejection über normierte Subs; Gauß-Kernel-Drizzle für gedithertes/unterabgetastetes Material |

GraXpert/StarNet/Dekonvolution weiter delegieren.

---

## 4. HDR (vs Photomatix, Lightroom, SNS-HDR)

**Jetzt:** Mertens Exposure Fusion (richtiger Standard!), Bracket-Auto-Erkennung, rigide Ausrichtung,
Look-Presets. **Schwäche:** kein Deghosting, Feature-Ausrichtung versagt bei flachen Reihen.

| Priorität | Bauen | Skizze |
|---|---|---|
| P0 | **Deghosting** (größter Praxis-Gewinn) | Referenz = mittleres EV; andere belichtungs-angleichen; Pixel-Abweichung → Bewegungsmaske (Morph + Feather); in maskierten Zonen **nur** die Referenz, sonst Fusion. `deghost: off/auto/aggressive` |
| P1 | **MTB-Ausrichtung** | Ward Median-Threshold-Bitmap (belichtungsinvariant) für Translation; Feature-Ausrichtung als Fallback für Drehung/Freihand |
| P2 | optional | Radiance-Map + Tonemapping (Debevec → Reinhard/Mantiuk) als *alternativer dramatischer Look*, kein Ersatz |

---

## 5. Langzeit / Sternspuren (vs Sequator, StarStaX)

**Jetzt:** smooth/trails/declutter/bright. **Schwäche:** Spuren gestrichelt (keine Lückenfüllung),
Mittel-/Median-Entrauschen, keine Vordergrund-Trennung.

| Priorität | Bauen | Skizze |
|---|---|---|
| P0 | **Spuren-Lückenfüllung + Kometen-Modus** | gerichteter Max-Filter entlang der Spur vor dem Lighten-Stack (überbrückt Lücken); Komet = abklingendes Lighten `accum = max(accum·decay, frame)` |
| P1 | **Sigma-Clipping-Mittel** | Mittel/Median in smooth/declutter durch 3-Iter-k·σ-Rejection ersetzen (killt Flugzeuge/Satelliten/Hotpixel, behält Mittel-SNR) |
| P2 | **Vordergrund einfrieren** | Nutzer-Grenze; Himmel stern-ausgerichtet/Lighten, Vordergrund Sigma-Clip-gemittelt, weiche Naht |

---

## 6. Panorama (vs Hugin, PTGui)

**Jetzt:** Black-Box `cv2.Stitcher`. **Schwäche:** keine Kontrolle über Projektion/Belichtung/Nähte.

| Priorität | Bauen | Skizze |
|---|---|---|
| P0 | **Explizite `cv2.detail`-Pipeline** | Features→`BestOf2NearestMatcher`→`HomographyBasedEstimator`+`BundleAdjusterRay`→`waveCorrect`→**Projektion** (`PyRotationWarper`)→**Belichtungsausgleich** (`BlocksChannelsCompensator`)→**GraphCut-Nähte**→**MultiBandBlender**. Stitcher als `fast`-Fallback |

---

## 7. RAW-Entwicklung & Editor (vs RawTherapee, darktable)

**Jetzt:** rawpy-Entwicklung; Camera-Raw-Editor (Belichtung/Kontrast/WB/Klarheit/Farbe + Masken-Pinsel);
Unsharp + kantenerhaltend Entrauschen. **Schwäche:** fester Demosaic, keine Lichter-Rekonstruktion,
einfaches Entrauschen/Schärfen, kein Tonwertkurven-Editor, keine echten lokalen Anpassungen, keine
Objektivkorrekturen.

| Priorität | Bauen | Skizze |
|---|---|---|
| P1 | **Lichter-Rekonstruktion** | maskierte Kanal-Verhältnis-Füllung (`blur(wert·maske)/blur(maske)`) für teilgeclippte Pixel + Entsättigen-zu-Weiß für ausgebrannte Kerne (killt magenta Lichter) |
| P2 | **Wavelet-Schärfung** (geteilt mit Lucky/Astro) | `pywt` Multi-Skalen-Boost + Entrauschen je Skala (RegiStax-Modell); RL-Dekonvolution (`skimage.restoration.richardson_lucy`, σ 0,5–0,7, 15–30 Iter) als Capture-Schärfung |
| P3 | **Besseres Entrauschen** | `cv2.fastNlMeansDenoisingColored` (schnell) / `bm3d` (beste, gekachelt, nach Entwicklung); Luma/Chroma getrennt |
| P4 | **Tonwertkurven** | Punkt (PCHIP, kein Überschwingen) + parametrisch (Regionsregler); Kurve im perzeptuellen Raum (Lab L*/Arbeits-Gamma); LUT-Anwendung |
| P5 | **Lokale Anpassungen** | Verlaufs-/Radial-/Pinsel-Masken = Smoothstep-Alpha + `cv2.ximgproc.guidedFilter` Kanten-Verfeinerung; parametrisch (Luma/Farb-Bereich) als Gate |
| P6 | **Demosaic-Wahl + Objektivkorrekturen** | rawpy DHT/DCB/VNG freigeben (AMaZE braucht GPL-Build); `lensfunpy` für Verzeichnung/TCA/Vignettierung (Vignettierung vor Remap) |

---

## Vorgeschlagene Bau-Reihenfolge (modulübergreifend)

1. **`core/align_local.py`** (ECC + gedeckelter Optical-Flow) — entriegelt Fokus P0/P1 und speist Lucky.
2. **Lucky Multi-Point (MAP)** — der sichtbare, aktuell scheiternde Fall; beweisen, dass er das Einzelbild schlägt.
3. **`core/wavelet.py`** (à-trous + RegiStax-Schärfung) — geteilt von Lucky, Astro, Editor; großer sichtbarer Gewinn.
4. **Astro lokale Normalisierung + GHS-Stretch** — größter Astro-Qualitätssprung, reine Mathematik/numpy.
5. **HDR-Deghosting** + **Spuren-Lückenfüllung/Komet** + **Panorama `cv2.detail`** — die Praxis-Fehler beheben.
6. **Editor**: Lichter-Rekonstruktion → Wavelet-Schärfung → Entrauschen → Kurven → lokale Masken → Objektivkorrektur.
7. **Fokus**: Konsistenz-Wavelet-Merge → Method A → Farb-Neuzuweisung → Halo-Retusche.

Jeder Schritt wird **einzeln** ausgeliefert, mit ehrlicher Vorher/Nachher-Messung (Schärfe **und** Rauschen,
per Auge **und** Zahl) — *bevor* irgendeine Qualitätsbehauptung fällt.

---

*Quellen aus der Recherche, die diesen Plan ergab: AutoStakkert, PlanetarySystemStacker, Helicon-Focus-
Parameter, Zerene PMax/DMap, PetteriAimonen/focus-stack, astroalign, Siril (PCC/SPCC/GHS), PixInsight
StarAlignment, RawPedia/darktable-Handbücher, lensfun. Noch nichts ist terminiert — es ist die vereinbarte
Richtung, Modul für Modul.*
