# ForgePix gegen Siril — Stapeln an denselben Aufnahmen

Stand 23.11.2026. Wiederholbar mit `python docs/vergleich/siril_vergleich.py <fits-ordner> <neuer-ordner>`.

## Aufbau

* **Daten:** IC 5146, Seestar S30, 28 × 30 s (`D:\astro\IC 5146_sub`), azimutal, also mit Bildfeldrotation.
* **Gleiche Einstellungen:** Sigma-Rejection 3/3, keine Normierung, **keine** Nachbearbeitung
  (Siril ohne `subsky` und ohne Grünentfernung). ForgePix: `register_and_cache(align_mode="rotate")`
  + `stack(method="sigma", kappa=3)`. Siril 1.4: `convert -debayer`, `register`, `stack rej 3 3 -nonorm`.
* **Eine Messung für beide** (im Skript): robustes Hintergrundrauschen; Sterngröße als
  Halbfluss-Radius (HFR) der 150 hellsten ungesättigten Einzelsterne.

## Ergebnis

| | ForgePix | Siril |
|---|---|---|
| Hintergrund | 0,01544 | 0,01542 |
| Rauschen im Stapel | **4,3·10⁻⁵** | 6,0·10⁻⁵ |
| Sterngröße HFR | 2,056 px | **2,011 px** |
| Rundheit | 1,169 | 1,165 |
| Rauschen je ausgerichtetem Einzelbild | 0,000198 | 0,000253 |
| Glättung durch das Ausrichten | 3 % | 16 % |
| Stapel-Wirkung (1,0 = reines Mittel) | **1,15** | 1,26 |
| Zeit | 51 s → **21 s** (24.11.) | **5 s** |

## Was daraus folgt

* **ForgePix rauscht 29 % weniger.** Das kommt nicht von weicherer Interpolation (die vermutete
  Erklärung war falsch: Siril glättet beim Verschieben stärker, 16 % gegen 3 %). Es kommt vor allem
  aus der Farbrekonstruktion — die Einzelbilder sind schon vor dem Stapeln 22 % ruhiger — und zum
  kleineren Teil aus dem Stapeln selbst (1,15 gegen 1,26).
* **Siril hat 2 % schärfere Sterne.** Passt zu einer schärferen Farbrekonstruktion, die mehr
  Rauschen mitnimmt. Welche Rekonstruktion ForgePix für Seestar-Daten nimmt, ist der nächste Punkt.
* **Siril war 10× schneller, jetzt gut 4×.** Das Sigma-Stapeln las jede Datei viermal komplett
  und rechnete jedes Mal das ganze Bild in Float64. Seit 24.11.2026 in Streifen, jede Datei
  einmal, die Streifen parallel: Stapeln 30 s → 10 s, Ergebnis bitgenau gleich
  (`tests/test_stapeln_streifen.py`). Übrig: Ausrichten und der Vorlauf der Normalisierung.
* **Messfalle, die zugeschnappt ist:** Das erste Vergleichsskript hatte keinen Startschutz
  (`if __name__ == "__main__"`). Unter Windows führt jeder Hilfsprozess des Ausrichtens ein
  ungeschütztes Skript noch einmal aus — 8 Läufe gleichzeitig, gemessen 778 s statt 48 s. Die
  Qualitätszahlen waren in allen 8 Läufen gleich, nur die Zeit war falsch.

## Zweite Kamera: ASI294MC Pro (24.11.2026)

NGC 6888, 40 × 120 s, äquatorial, ohne Kalibrierbilder (`Y:\Backup\astro\ASIAIR\Plan\NGC6888`).

| | ForgePix | Siril |
|---|---|---|
| Rauschen im Stapel | **1,58·10⁻⁵** | 2,26·10⁻⁵ |
| Sterngröße HFR | 3,064 px | **2,951 px** |
| Rundheit | **1,311** | 1,329 |
| Zeit | 72 s | **36 s** |

Das Muster ist dasselbe wie bei der Seestar-Serie: 30 % weniger Rauschen, 4 % breitere Sterne.

## Debayer: woher die breiteren Sterne kommen

ForgePix rekonstruiert die Farben aus den Rohdaten **bilinear** (`astro.debayer_float`). Das ist
das einfachste Verfahren, und es glättet. Als Versuch wurde das lineare Verfahren von Malvar,
He und Cutler (2004, nach den Filtern im Aufsatz; `debayer_mhc_versuch.py`) dagegengestellt. An
einem bekannten Bild ist es 2 dB genauer (30,6 gegen 28,5 dB).

| | bilinear | MHC | Siril |
|---|---|---|---|
| IC 5146: HFR / Rauschen | 2,056 / 4,3·10⁻⁵ | **1,890** / 7,2·10⁻⁵ | 2,011 / 6,0·10⁻⁵ |
| NGC 6888: HFR / Rauschen | 3,064 / 1,58·10⁻⁵ | **2,944** / 2,27·10⁻⁵ | 2,951 / 2,26·10⁻⁵ |
| **Rauschen bei gleicher Schärfe** IC 5146 (HFR 2,10) | 3,96·10⁻⁵ | **3,65·10⁻⁵** | 4,21·10⁻⁵ |
| **Rauschen bei gleicher Schärfe** NGC 6888 (HFR 3,15) | 1,37·10⁻⁵ | **1,35·10⁻⁵** | 1,37·10⁻⁵ |

* Bei gleicher Schärfe ist ForgePix nie schlechter als Siril, und MHC holt die meiste
  Information heraus.
* **MHC wird trotzdem noch nicht Standard.** An der ASI294-Serie (ohne Darks) erzeugt es 1488
  tiefschwarze Punkte, gegen 268 bei bilinear. Sie sitzen weder am Rand noch an hellen Sternen,
  vermutlich Hotpixel, deren Nachbarn die negativen Filteranteile schwarz machen.
* Ein einfacher Hotpixel-Filter auf den Rohdaten vor dem Debayern hilft nicht: Er greift auch
  Sternkerne an (HFR 3,097, schlechter als bilinear).
* **Nächster Schritt:** eine sternschonende Hotpixel-Erkennung auf den Rohdaten, danach MHC
  erneut messen.
* **Messfalle:**
  * Der erste Versuch tauschte die Funktion nur im Hauptprozess aus, nicht in den Hilfsprozessen
    des Ausrichtens. Die Zahlen blieben unverändert, und erst eine Zählmarke zeigte: 0 Aufrufe.
  * Ein abgelehnter Befehl hatte außerdem das Neuschreiben des Skripts verhindert.

Offen: ASI533MC-Pro-Serie; Messung mit Kalibrierbildern, sobald welche vorliegen
(`docs/ASTRO_DATEN.md`: bisher keine).
