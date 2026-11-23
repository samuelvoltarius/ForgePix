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
| Zeit | 51 s | **5 s** |

## Was daraus folgt

* **ForgePix rauscht 29 % weniger.** Das kommt nicht von weicherer Interpolation (die vermutete
  Erklärung war falsch: Siril glättet beim Verschieben stärker, 16 % gegen 3 %). Es kommt vor allem
  aus der Farbrekonstruktion — die Einzelbilder sind schon vor dem Stapeln 22 % ruhiger — und zum
  kleineren Teil aus dem Stapeln selbst (1,15 gegen 1,26).
* **Siril hat 2 % schärfere Sterne.** Passt zu einer schärferen Farbrekonstruktion, die mehr
  Rauschen mitnimmt. Welche Rekonstruktion ForgePix für Seestar-Daten nimmt, ist der nächste Punkt.
* **Siril ist 10× schneller.** ForgePix: 18 s Ausrichten, 30 s Stapeln.
* **Messfalle, die zugeschnappt ist:** Das erste Vergleichsskript hatte keinen Startschutz
  (`if __name__ == "__main__"`). Unter Windows führt jeder Hilfsprozess des Ausrichtens ein
  ungeschütztes Skript noch einmal aus — 8 Läufe gleichzeitig, gemessen 778 s statt 48 s. Die
  Qualitätszahlen waren in allen 8 Läufen gleich, nur die Zeit war falsch.

Offen: dasselbe an einer ASI294MC-Pro- und einer ASI533MC-Pro-Serie (äquatorial, ohne Rotation),
und mit Kalibrierbildern, sobald welche vorliegen (`docs/ASTRO_DATEN.md`: bisher keine).
