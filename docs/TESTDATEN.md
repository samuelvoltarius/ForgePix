# Testdaten für die Qualitätsprüfung

Stand 23.11.2026. Holen mit:

```bash
python3 testdaten_holen.py            # alles (rund 0,9 GB) nach testdata/
python3 testdaten_holen.py --nur raw  # nur einen Teil: raw, makro, langzeit, beispiele
```

`testdata/` steht in `.gitignore` — die Dateien kommen nie ins Repository. Nur frei nutzbare
Quellen; die Lizenz steht je Ordner in `LIZENZ.txt`.

| Ordner | Inhalt | Quelle und Lizenz |
|---|---|---|
| `testdata/raw/<Hersteller>/` | je eine RAW-Datei von 18 Herstellern: Canon (CR3, CR2), Nikon Z 6II, Sony A7R V, Fujifilm X-T4 (X-Trans), OM System OM-5 II, Olympus E-M1 III, Panasonic G9, Pentax K-1 II, Leica Q2, Hasselblad X2D (.fff), Phase One IQ4 (.iiq), Sigma fp, iPhone 12 Pro, Pixel 8 Pro, DJI, GoPro HERO5 (.gpr), Samsung | [raw.pixls.us](https://raw.pixls.us/), CC0 |
| `testdata/makro/focus-stack_pcb/` | Fokusreihe einer Platine, 7 Bilder + `expected.jpg` (Referenz-Ergebnis) | [focus-stack](https://github.com/PetteriAimonen/focus-stack), MIT |
| `testdata/makro/focus-stack_depthmap/` | Fokusreihe, 10 Bilder | ebenda |
| `testdata/samples/ForgePix-Samples/` | Makro-Fokusreihe, Landschafts-RAW, Astro (Seestar M 42, ASI294 IC 5146) | eigene ForgePix-Beispieldaten |
| `testdata/langzeit/` | Wasserfall-Video, 570 Bilder, 30 fps → Langzeitbelichtung aus Einzelbildern | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Sahalie_Falls_during_Winter_jm1101.webm), CC0 |

Dazu auf Alfreds Rechner (nicht weitergeben, private Aufnahmen): `D:\astro` (Astro),
`Y:\Backup\fell` (Sony A7 III, Belichtungsreihen für HDR), `D:\Kartenbackup\_Fotos_2026-10-22`
(Sony A7 V). Andere Ordner unter `Y:\Backup` enthalten Kunden- und Privatfotos und werden
nicht für Tests benutzt.

## Erste Messung: RAW aller Hersteller (23.11.2026)

`develop_raw_to_bgr` (rawpy 0.27.1 / LibRaw 0.22.1) über die 18 Dateien plus Sony A7 V und A7 III,
verglichen mit dem Vorschaubild, das die Kamera selbst in die RAW-Datei legt:

* **19 von 20 entwickelt**, darunter A7 V, Hasselblad .fff, Phase One .iiq, X-Trans .raf.
  **GoPro .gpr nicht** — LibRaw ist ohne GPR gebaut; jetzt mit klarer Meldung und Link zu GoPros
  freiem Umwandler (gpr_tools, MIT/Apache).
* **Fehler gefunden:** .fff, .iiq, .rwl, .nrw u. a. fehlten in der Endungsliste — solche Dateien
  wurden in einem Ordner gar nicht als Bilder erkannt. Behoben (Test `test_raw_formate`).
* Ausrichtung und Seitenverhältnis: 19 von 19 passen zur Kamera-Vorschau.
* Farbe gegenüber der Kamera-Vorschau: B/G im Median 1,00 (0,91 … 1,15), R/G 0,99 (0,86 … 1,11).
* **Helligkeit: im Median nur 0,58 der Kamera-Vorschau (0,45 … 0,93).** Die Entwicklung ist
  „treu“ (ohne automatische Helligkeit, ohne Kamera-Tonkurve) und wirkt neben dem Kamerabild
  dunkel und flau — an der Nikon Z 6II sichtbar verglichen. Offen, ob die Vorgabe ein
  kamera-ähnliches Aussehen bekommen soll (siehe 08_QUALITAET); das ändert die Bilder in jedem
  Ablauf und ist darum eine eigene Entscheidung.
