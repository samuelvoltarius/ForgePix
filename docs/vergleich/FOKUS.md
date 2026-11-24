# Fokus-Stacking — gemessen

Stand 24.11.2026. Wiederholbar mit
`python docs/vergleich/fokus_vergleich.py <fokusreihe> <neuer-ordner> [referenz.jpg]`.

## Kennzahlen

* **Schärfe-Ausbeute** je 64-px-Kachel: Schärfe des Ergebnisses ÷ Schärfe der schärfsten
  Einzelaufnahme an derselben Stelle. 1,0 = so scharf wie das beste Einzelbild. Nur Kacheln mit
  Struktur zählen. **Unter 0,8** ist der Fokus dort verpasst. **Über 1,3** ist nicht besser,
  sondern Überzeichnung: Halos, Säume, verstärktes Rauschen.
* **Ähnlichkeit zur Referenz** (SSIM der Helligkeit nach Ausrichtung).

## Platine (focus-stack, 7 Bilder, Referenz `expected.jpg`)

| Methode | Ausbeute | Fokus verpasst | überzeichnet | SSIM zur Referenz | Zeit |
|---|---|---|---|---|---|
| focus-stack (Referenz) | 1,273 | 2,6 % | 46,9 % | — | — |
| pyramid | 1,188 | **0 %** | 22,2 % | 0,900 | 7,1 s |
| pyramid-consistent | 1,176 | **0 %** | 16,3 % | **0,908** | 7,3 s |
| halofix | 1,154 | **0 %** | 17,9 % | 0,905 | 8,2 s |
| depthmap | 1,155 | **0 %** | 19,5 % | 0,868 | 6,9 s |
| wavelet | 1,096 | **0 %** | **11,4 %** | 0,906 | 7,9 s |
| average | 1,074 | 0,7 % | 14,8 % | 0,857 | 6,9 s |
| average **vorher** (lineare Gewichte) | 0,326 | 100 % | 0 % | 0,865 | |

**Ergebnis:** Alle Methoden außer `average` treffen überall den Fokus. Sie überzeichnen dabei
deutlich weniger als focus-stack (11–22 % gegen 47 % der Stellen).

## Fehler gefunden: `average` war ein Weichzeichner

Die Gewichte stiegen linear mit der Schärfe. Ist ein Bild an einer Stelle dreimal so scharf wie
sechs andere, bekommt es so nur ein Drittel Gewicht. Gewicht ∝ Schärfe⁵ behebt das. Gewählt aus
1, 2, 4, 5, 6, 8, 16 an beiden Reihen:

* Ab Potenz 8 schaltet es hart um und überzeichnet 16–24 % der Stellen.
* Bei Potenz 4 verpasst es noch 12–31 %.

Test: `tests/test_fokus_average.py`, mit Gegenprobe. Linear fällt der Test, wie er soll.

## Messfallen, die zugeschnappt sind

* **Zugeschnittenes Ergebnis:** Das Ergebnis des Stapelns ist zugeschnitten (1721×1041 aus
  2048×1536). Die erste Fassung des Messskripts stauchte die Einzelbilder auf diese Größe.
  Danach verglich sie falsche Stellen (Korrelation 0,5) und meldete für alle Methoden Unsinn,
  gleichzeitig 45 % „verpasst“ und 34 % „überzeichnet“. Jetzt wird über SIFT-Merkmale und eine
  Homographie ausgerichtet; die Referenz liegt danach mit Korrelation 0,99 auf dem Ergebnis.
* **Zu leichter Test:** Der erste künstliche Testfall war zu leicht (Unschärfe σ 3, kein Rauschen).
  Dort reichte schon die lineare Gewichtung, und die Gegenprobe fiel nicht.

## Offen

* **Zweite Reihe** (`focus-stack_depthmap`, 10 Bilder, ohne Referenz): 3–7 der Einzelbilder
  lassen sich in der Messung nicht sicher auf das Ergebnis legen (Korrelation unter 0,6). Ihre
  Zahlen sind darum nicht belastbar und stehen hier nicht.
* **Vergleich mit Helicon und Zerene:** fehlt, beide sind nicht auf dem Testrechner.
* **Eigene Reihen:** Messung an einer eigenen, längeren Reihe (Insekt, Münze).
