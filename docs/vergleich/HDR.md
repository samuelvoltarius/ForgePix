# HDR aus Belichtungsreihen — gemessen

Stand 24.11.2026. Wiederholbar mit
`python docs/vergleich/hdr_vergleich.py <ordner-mit-raw-reihen> [anzahl]`.

Daten: 462 Sony-A7-III-ARW in 154 Reihen zu −1/0/+1 EV (Innenraum mit hellen Fenstern und
Lampen). Es sind Alfreds Aufnahmen, nur lokal verwendet. Im Ordner liegen auch die
Photomatix-Ergebnisse. Das sind zusammengeführte lineare DNGs, kein fertiges Bild, darum dienen
sie hier nur zum Anschauen.

## Kennzahlen

Gemessen wird gegen das Kamerabild der **normalen** Belichtung:
* Helligkeit (Median-Verhältnis),
* ausgebrannte und fast schwarze Fläche,
* „Zeichnung“ in den Bereichen, die in der normalen Aufnahme ausgebrannt bzw. abgesoffen sind.
  Gemessen wird sie relativ zur Belichtung, die dort die meiste Information hat.

## Ergebnis (Median über 8 Reihen)

| Weg | Helligkeit | ausgebrannt | fast schwarz | Zeichnung Lichter | Zeichnung Schatten |
|---|---|---|---|---|---|
| Kamera, normale Belichtung | 1,00 | 0,51 % | 0,29 % | 0,33 | 0,53 |
| **bisher** (8 bit neutral, Fusion, „natural“) | **0,44** | 0,25 % | **14,0 %** | 1,75 | **0,43** |
| **jetzt** (16 bit neutral, Fusion, an Kamera angeglichen) | **1,00** | **0,10 %** | 0,58 % | 0,71 | **1,14** |
| jetzt + „natural“ | 0,86 | 1,70 % | 4,3 % | 0,61 | 0,76 |
| jede Belichtung im Kamera-Look, dann Fusion | 0,94 | 1,62 % | 5,4 % | 0,44 | 0,82 |

**Das alte HDR war schlechter als das einzelne Foto.** Es war halb so hell, hatte 14 % fast
schwarze Fläche und in den Schatten weniger Zeichnung als die normale Aufnahme. Jetzt ist es so
hell wie die Kamera und brennt fünfmal weniger aus. In Lichtern und Schatten zeigt es etwa doppelt
so viel Zeichnung wie das Einzelbild. Über die Kommandozeile ohne Einstellungen gemessen:
Helligkeit 0,999 / 1,006 und fast schwarz 0,27 % (Kamera 0,20 %).

## Fehler gefunden und behoben

* **Reihenerkennung:** Aus 462 Aufnahmen wurde *eine* Reihe.
  * PIL liest aus ARW keine Belichtungszeit. Dann galt still „alles eine Reihe“.
  * Selbst mit Zeiten griff die alte Regel nicht: „neue Reihe, wenn die Zeit um mehr als die Hälfte
    fällt“. Der Rücksprung von +1 auf 0 EV ist genau Faktor 2.
  * Jetzt liest `exifread` (schon Pflicht-Abhängigkeit) die Zeiten. ForgePix sucht das
    wiederkehrende Belichtungsmuster und findet 154 Reihen zu 3. Ohne Muster kommt eine klare
    Meldung.
* **Bezugsbild:** Als „normale“ Belichtung galt das mittlere Bild *nach Dateiname*. Bei Sony
  (0/−1/+1) war das die −1-EV-Aufnahme, und von ihr kamen Dateiname und EXIF. Jetzt wird nach
  Belichtungszeit sortiert, ohne EXIF nach gemessener Helligkeit.
* **Unlesbare Bilder** einer Reihe werden genannt.

## Offen

* Geister (bewegte Personen, Blätter) sind nicht gemessen.
* Die Wege „radiance“ und „local“ sind nicht gemessen.
* Photomatix lässt sich nicht als fertiges Bild vergleichen: Im Ordner liegen nur seine linearen
  DNGs.
