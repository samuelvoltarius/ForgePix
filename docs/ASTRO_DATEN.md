# Astro-Rohdaten — Bestandsaufnahme

Erhoben am 07.09.2026 durch Auslesen **aller FITS-Header** an den drei Orten, nicht
durch Schaetzen aus Dateinamen. 6189 Header gelesen, **0 unlesbar**.

| Ort | Pfad | FITS |
|---|---|---|
| lokal | `D:\astro\` | 2164 |
| NAS | `Y:\Backup\astro\` | 3991 |
| lokal | `F:\backup_usb_h\ASIAIR\` | 34 |

**6189 Lights, 73 Objekte, rund 87 GB.**
**Kalibrierbilder: keine.** Fuer keine Kamera liegen Darks, Flats oder Bias vor —
das bestaetigt, was fuer die ASI294MC Pro schon bekannt war, gilt aber fuer alle.

## Die groessten Serien

| Objekt | Subs | GB | Kamera | Belichtung | Bildgroesse |
|---|---|---|---|---|---|
| NGC 5033 | 363 | 1.6 | Seestar S30 | 30 s x363 | 1080x1920 |
| M51 | 340 | 8.0 | ZWO ASI294MC Pro | 120 s x340 | 4144x2822 |
| whirl | 300 | 5.4 | ZWO ASI533MC Pro | 15 s x300 | 3008x3008 |
| FOV Cross | 267 | 1.6 | ZWO ASI294MC Pro | 60 s x267 | 2072x1410 |
| NGC 7635 | 248 | 1.1 | Seestar S30 | 30 s x248 | 1080x1920 |
| M101 | 228 | 5.3 | ZWO ASI294MC Pro | 120 s x228 | 4144x2822 |
| IC 434 | 227 | 1.0 | Seestar S30 | 30 s x227 | 1080x1920 |
| M 42 | 221 | 1.1 | Seestar S30 | 30 s x221 | 1080x1920 |
| NGC 7023 | 215 | 3.9 | ZWO ASI533MC Pro | 60 s x215 | 3008x3008 |
| Whirlpool Galaxy | 213 | 3.9 | ZWO ASI533MC Pro | 60 s x109, 10 s x95, 120 s x9 | 3008x3008 |
| M 42(8) | 202 | 3.7 | ZWO ASI533MC Pro | 5 s x202 | 3008x3008 |
| NGC7023 | 193 | 1.1 | ZWO ASI294MC Pro | 120 s x193 | 2072x1410 |
| M27 | 189 | 4.4 | ZWO ASI294MC Pro | 120 s x155, 300 s x34 | 4144x2822 |
| M 31 | 155 | 0.8 | Seestar S30 | 10 s x111, 30 s x44 | 1080x1920 |
| M 42(5) | 150 | 2.7 | ZWO ASI533MC Pro | 5 s x150 | 3008x3008 |
| Whirlpool Galaxy(1) | 142 | 2.6 | ZWO ASI533MC Pro | 10 s x141, 1 s x1 | 3008x3008 |
| NGC6888 | 139 | 3.2 | ZWO ASI294MC Pro | 120 s x139 | 4144x2822 |
| IC 443 | 129 | 0.6 | Seestar S30 | 30 s x129 | 1080x1920 |
| M 45 | 111 | 0.6 | Seestar S30 | 30 s x111 | 1080x1920 |
| SH2-114 | 106 | 2.5 | ZWO ASI294MC Pro | 180 s x106 | 4144x2822 |

## Was sich damit trainieren laesst

**Entrauschen (Noise2Noise): 5934 Subs in 53 brauchbaren Serien.**

Das Verfahren braucht keine sauberen Zielbilder — zwei unabhaengig verrauschte
Aufnahmen derselben Szene genuegen, solange das Rauschen mittelwertfrei und zwischen
beiden unabhaengig ist. Zwei Subs derselben Nacht erfuellen das. Als Faustregel sind
hier Serien mit mindestens 20 Aufnahmen derselben Kamera und Belichtung gezaehlt:

| Objekt | Belichtung | Subs | Kamera |
|---|---|---|---|
| NGC 5033 | 30 s | 363 | Seestar S30 |
| M51 | 120 s | 340 | ZWO ASI294MC Pro |
| whirl | 15 s | 300 | ZWO ASI533MC Pro |
| FOV Cross | 60 s | 267 | ZWO ASI294MC Pro |
| NGC 7635 | 30 s | 248 | Seestar S30 |
| M101 | 120 s | 228 | ZWO ASI294MC Pro |
| IC 434 | 30 s | 227 | Seestar S30 |
| M 42 | 30 s | 221 | Seestar S30 |
| NGC 7023 | 60 s | 215 | ZWO ASI533MC Pro |
| M 42(8) | 5 s | 202 | ZWO ASI533MC Pro |
| NGC7023 | 120 s | 193 | ZWO ASI294MC Pro |
| M27 | 120 s | 155 | ZWO ASI294MC Pro |
| M 42(5) | 5 s | 150 | ZWO ASI533MC Pro |
| Whirlpool Galaxy(1) | 10 s | 141 | ZWO ASI533MC Pro |
| NGC6888 | 120 s | 139 | ZWO ASI294MC Pro |

**Schaerfen: geht damit NICHT.** Ein tieferer Stack ist nicht schaerfer, sondern
derselbe Unschaerfegrad mit weniger Rauschen. In diesen Daten steckt keine schaerfere
Wahrheit. Der Weg dafuer ist ein anderer: eine fremde, scharfe Szene (HST aus dem
MAST-Archiv, oeffentlich) kuenstlich mit der EIGENEN gemessenen PSF verschmieren.
Dann ist das Paar physikalisch richtig, und der Schaerfer lernt genau die Unschaerfe
zu entfernen, die dieses Teleskop wirklich erzeugt.

**Sterne entfernen: nicht aus diesen Daten.** Es gibt darin keine verlaessliche
sternlose Wahrheit, und eine aus der eigenen Sternentfernung gewonnene Maske waere
nur so gut wie das Verfahren, das sie trainieren soll. Der saubere Weg ist umgekehrt:
Sterne mit bekannter PSF und bekannten Orten auf eine sternarme Szene RECHNEN — dann
ist die Wahrheit exakt und die Maske faellt als Nebenprodukt ab.

## Fallen, die beim Scan aufgefallen sind

* **Dasselbe Objekt unter mehreren Namen.** `M51`, `whirl`, `Whirlpool Galaxy` und
  `Whirlpool Galaxy(1)` sind dieselbe Galaxie, verteilt auf zwei Kameras. Wer nach
  Objektnamen gruppiert, zerreisst die Serie.
* **Gemischte Belichtungszeiten innerhalb einer Serie.** `Whirlpool Galaxy` hat
  10 s, 60 s und 120 s nebeneinander. Fuer Noise2Noise duerfen nur gleiche Zeiten
  gepaart werden, sonst unterscheidet sich das Signal und nicht nur das Rauschen.
* **Seestar-Serien sind kurz belichtet** (10-30 s) und entsprechend verrauscht. Genau
  das macht sie fuer einen Entrauscher wertvoll — es gibt viel zu lernen.

## Werkzeuge, die auf dem NAS liegen

* **ImPPG** (`Y:\Backup\astro\imppg-win64\`, GPL v3) — schaerft ueber
  nicht-blinde Lucy-Richardson-Dekonvolution mit GAUSS-Kern, Sigma von Hand,
  30-70 Iterationen empfohlen, dazu Unschaerfemaskierung und eine Ringing-Bremse.
  **Uebernehmen laesst sich der Code nicht** (GPL gegen MIT), das Verfahren aber sehr
  wohl: Lucy-Richardson ist von 1972/74 und frei. `astro.deconvolve` hat es bereits,
  mit der PSF aus den eigenen Sternen GEMESSEN statt als Gauss angenommen, dazu
  TV-Regularisierung und ortsabhaengige PSF - beides hat ImPPG nicht.

  Die 30-70 Iterationen sind an ECHTEN Daten nachgemessen und uebertragen sich NICHT:

  | Iterationen | Sternflaeche | Rauschen |
  |---|---|---|
  | roh | 99,0 px | 0,000068 |
  | 10 | 58,5 px (59 %) | x1,14 |
  | **15** | **53,0 px (54 %)** | **x1,16** |
  | 30 | 59,0 px (60 %) | x1,24 |
  | 50 | 63,0 px (64 %) | x1,33 |
  | 70 | 59,5 px (60 %) | x1,41 |

  Jenseits von 15 werden die Sterne wieder BREITER und das Rauschen steigt stetig.
  Der Grund ist der Anwendungsbereich: ImPPG zielt auf Sonne und Planeten - sehr hohes
  Signal, kein rauschbegrenzter Hintergrund. Deep-Sky ist rauschbegrenzt, da verstaerkt
  Lucy-Richardson das Rauschen schneller, als es Detail zurueckholt. Die Vorgabe von 15
  in `astro.deconvolve` ist damit belegt richtig.
* **AutoStakkert** (`astrostecker\`) — Planeten-/Mondstacking, anderer Zweck.
* **Astronomy Tools** (`.atn`) — Photoshop-Aktionen.

