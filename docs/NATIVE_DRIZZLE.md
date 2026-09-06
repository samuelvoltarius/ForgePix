# Native Drizzle-Rekonstruktion

ForgePix rekonstruiert lineare Mono-, RGB- und unterstützte Bayer-FITS aus ihren
Originalmessungen. Der eigene Quadrat-Drop-Kern berechnet die Flächenüberlappung
mit dem Ausgaberaster einschließlich Subpixelverschiebung und affiner Abbildung.
Die Ausführung benötigt kein Siril oder PixInsight. Das Verfahren folgt
[Fruchter und Hook](https://arxiv.org/abs/astro-ph/9808087).

## Benutzung

1. Eine zusammengehörige Serie linearer Aufnahmen gleicher Bildgröße auswählen.
   Passende Darks und Flats konfigurieren; die normale Aufnahmequalitätsauswahl
   eingeschaltet lassen. Die Quelldateien bleiben erhalten.
2. Die echte Drizzle-Rekonstruktion aktivieren. Für eine Farbkamera zunächst
   **Originalgröße (1×)** verwenden. Auch dabei werden die einzelnen gemessenen
   Bayer-Farben unmittelbar in das gemeinsame RGB-Raster integriert.
3. **2×** vergrößert beide Bildachsen und benötigt wesentlich mehr unterschiedliche
   Ditherpositionen. Viele Aufnahmen mit gleicher Sensorposition ersetzen Dithering
   nicht. Ein größeres Raster allein belegt keinen Gewinn an Auflösung.
4. Mit `pixfrac=0.7` beginnen und anschließend Abdeckungsbericht und Masken prüfen.
   Kleinere Drops können mehr Lücken hinterlassen. Bei unzureichender Farbabdeckung
   mehr verschiedene Ditherpositionen aufnehmen oder den normalen Stack verwenden.

Die Empfehlung für CFA bei 1× entspricht der
[Siril-Dokumentation](https://siril.readthedocs.io/en/stable/preprocessing/drizzle.html):
Rot und Blau werden jeweils nur an einem Viertel der Bayer-Sensorpositionen gemessen.
Eine feste Mindestanzahl von Aufnahmen garantiert daher keine vollständige Abdeckung.

CLI-Beispiel, aus dem Projektverzeichnis mit eingerichtetem Python ausgeführt:

```powershell
python focus_stack_gui.py --cli --astro --input "F:\Astro\Lights" --work "F:\Astro\Drizzle-01" --astro-drizzle 1 --astro-drizzle-true --astro-pixfrac 0.7 --astro-align rotate --fits-out
```

`--astro-drizzle-true` aktiviert die Rekonstruktion auch bei 1×. Ohne diesen Schalter
ist eine Vergrößerung mit `--astro-drizzle 2` eine interpolierte Skalierung.
Die CLI bietet 1×/2×; die Kern-API unterstützt Skalierungen von 1 bis 4.

## Eingaben und Grenzen

- Für CFA originale FITS mit `BAYERPAT=RGGB`, `BGGR`, `GRBG` oder `GBRG` verwenden.
  Ganzzahlige `XBAYROFF`/`YBAYROFF` werden berücksichtigt. Dark/Flat-Kalibrierung
  erfolgt auf dem ursprünglichen Sensorraster mit zweidimensionalen Mastern.
  Nur eine Arbeitskopie für die Registrierung wird debayert; die integrierten
  Messungen behalten ihre ursprüngliche Farbzuordnung.
- CFA-TIFF, unbekannte Bayer-Muster und gemischte CFA-/Mono-/RGB-Serien sind nicht
  unterstützt. Kosmetikkorrektur und Banding-Korrektur bei CFA ausschalten;
  diese Kombinationen werden abgewiesen, da die Korrekturen nicht CFA-gerecht sind.
- Lineare Mono-/RGB-FITS und TIFF sind möglich. JPG, 8-Bit-TIFF und als gestreckt
  markierte FITS/TIFF werden abgewiesen. Bei TIFF ohne Linearitätsangabe muss der
  Anwender sicherstellen, dass die Werte linear sind.
- Bildform, Transformation, Gewichte und Parameter werden geprüft; Größenfehler
  werden nicht durch Resize kaschiert. `pixfrac` liegt zwischen Float32-Epsilon
  (etwa `1.1920929e-7`) und 1. Null bedeutet hier keinen unterstützten Punkt-Kern.
- Die Integration ist ein **gewichtetes Mittel ohne Sigma-/Ausreißer- oder
  Cosmic-Ray-Rejection**. Eine gewählte normale Stack-Rejection gilt dabei nicht;
  die vorgelagerte Qualitätsauswahl ganzer Aufnahmen bleibt wirksam.
- Es gibt keine Belichtungsnormalisierung. Bekannte Belichtungszeiten mit mehr
  als 1 % Unterschied werden abgewiesen; fehlende Metadaten ersetzen keine Prüfung.
  WCS-Verzerrungskorrektur und TPS werden nicht unterstützt.
- Nicht maskenfähige Nachbearbeitung, etwa Hintergrundextraktion oder Entrauschung,
  wird in dieser Pipeline bei unvollständiger Abdeckung abgewiesen.

## Koordinaten, Werte und Gewichte

`astro.drizzle_stack(..., transforms=..., return_info=True)` akzeptiert pro Aufnahme
eine endliche reelle **2×3-Matrix `M=[A|t]` vom Eingabebild zum Referenzbild**.
Koordinaten `(x,y)` bezeichnen Pixelzentren; das erste Zentrum liegt bei `(0,0)`.
Für Ausgabeskalierung `s` gilt einschließlich des halben Pixelversatzes:

```text
q = s * (A @ [x, y] + t + [0.5, 0.5]) - [0.5, 0.5]
```

Ein Eingabe-Drop hat Kantenlänge `pixfrac` in Eingabepixeln. Seine vier Ecken werden
affin abgebildet und mit den Ausgabepixeln geschnitten. Für Überlappungsanteil
`a_ij = Schnittfläche / transformierte Dropfläche`, Eingabegewicht `w_i`, Messwert
`d_i` und Jacobi-Determinante `J_i = abs(det(A_i))` wird kanalweise gerechnet:

```text
W_j = sum(a_ij * w_i)
F_j = sum(a_ij * w_i * d_i / J_i)
I_j = F_j / W_j, falls W_j > 0
```

Die Summen sind Float64; Bild und exportierte Gewichte sind Float32. Negative und
HDR-Werte bleiben erhalten. Die Werte beziehen sich auf die **Flächenhelligkeit
pro Referenzpixel**, nicht auf Zählwerte pro kleinerem Ausgabepixel. Eine
Apertursumme benötigt den Flächenfaktor `1/s²`, nach Software-Binning um Faktor
`b` entsprechend `(b/s)²`. Ausgangseinheiten sind die linearen Werte des nativen
Readers: Integer-FITS werden normiert, Float-FITS behalten ihre Zahlenwerte.
Es wird keine neue physikalische Einheit aus unbekannten Metadaten abgeleitet.

Gewichte sind Summen gewichteter Überlappungsanteile, keine Belichtungsanzahl,
keine Anzahl unabhängiger Messungen und keine automatisch bestimmte inverse
Varianz. Abgeschnittene Dropteile außerhalb des Rasters fehlen entsprechend.
Eine normierte Rekonstruktion bei lückenhafter Abtastung garantiert keine exakte
Aperturphotometrie. Die Bedeutung korrelierter Fehler erläutert
[STScI: Weight Maps and Correlated Noise](https://hst-docs.stsci.edu/drizzpac/chapter-3-description-of-the-drizzle-algorithm/3-3-weight-maps-and-correlated-noise).

## Export und Abdeckung

Für weitere Berechnungen das lineare Float32-TIFF oder das optionale Float32-FITS
verwenden. Der separate 16-Bit-Kompatibilitätsexport kann Werte beschneiden.
Die folgenden Begleitdateien zusammen mit dem wissenschaftlichen Bild aufbewahren:

| Datei | Bedeutung |
| --- | --- |
| `coverage.tif` | Binäre Maske: alle Ausgabekanäle haben Gewicht größer null. |
| `coverage_channels.tif` | Binäre Abdeckung jedes einzelnen Kanals, RGB bei Farbausgabe. |
| `drizzle_weights.tif` | Float32-Gewichte je Kanal, RGB bei Farbausgabe. |
| `drizzle_report.json` | Verwendete Quellen, Matrizen, Skalierung, Pixfrac, Abdeckung und Grenzen. |
| `processing_report.json` | Pipelineablauf einschließlich Qualitätsauswahl und tatsächlichem Integrationsverfahren. |

`coverage_fraction` ist der Anteil vollständig kanalweise belegter Ausgabepixel,
nicht deren geometrischer Füllgrad oder eine Belichtungsquote. Fehlende Werte
bleiben null mit Gewicht null; sie werden weder interpoliert noch aufgefüllt und
dürfen nicht als gemessener Himmel ausgewertet werden. Unvollständige Abdeckung
erzeugt eine ausdrückliche Warnung im Log und im Drizzle-Bericht.

FITS-Header/TIFF-Metadaten verknüpfen Masken und Gewichte über `FPCOV`, `FPDRZCOV`
und `FPDRZWGT`; `FPPIXARE` enthält die Ausgabepixelfläche in Referenzpixeleinheiten.
Die API verwendet intern BGR, Farbbildexporte RGB. Vorhandene Eingabe-`FPCOV`-Masken
werden berücksichtigt. Der Export erzeugt keine neue WCS-Lösung; selbst vollständige
Abdeckung bedeutet im Bericht `coverage_complete_not_quality_validated`.

## Bisherige Nachweise und ihre Grenzen

- **22 gezielte Tests** in [test_drizzle.py](../tests/test_drizzle.py): Fluss und
  Fläche, signierte/HDR-Werte, Teilüberlappung, Rotation/affine Abbildung, Masken,
  CFA-Phasen und Kalibrierung, Float-Export, ungültige Eingaben und Abbruch.
- **80 unabhängige affine Zufallsfälle** gegen einen separat konstruierten
  Polygon-Flächenvergleich bestanden. Maximale relative Abweichung: Gewichte
  `2.74e-14`, gewichtete Flusssumme `1.87e-14`. Für den zusätzlichen Fall mit
  minimalem Pixfrac lag die größte absolute Gewichtsabweichung bei `1.69e-9`.
  Dies prüft die Rekonstruktionsgeometrie, keine reale Sternphotometrie.
- **Reale M27-Serie:** 34 originale ASIAIR-FITS der ASI294MC Pro, je 300 s,
  4144×2822 Pixel; normale Qualitätsauswahl integrierte 31 Aufnahmen bei 1×.
  Der CLI-Lauf samt Exportprüfung benötigte **114.047 s**, ohne anfängliches Kopieren.
  Gemeinsame RGB-Abdeckung: **99.9759 %**. Float-FITS und Float-TIFF waren identisch;
  Masken/Gewichte konsistent, Original-Hashes und Änderungszeiten unverändert.
  Ohne Kalibrierungsframes bleiben unter anderem Verstärkerglühen und Hotpixel
  sichtbar; der historische Filter ist unbekannt. Der tatsächliche Speicherpeak
  wurde nicht gemessen. Bericht: `forgepix-drizzle-m27-1x-full-01/drizzle-e2e-report.json`.
- Dieser M27-Lauf verwendete einen Entwicklungsstand **vor den letzten
  Eingabeprüfungen und der Stabilitätskorrektur für winzige affine Drops**.
  Er ist ausdrücklich kein Nachweis für den finalen Commit; dessen eigener
  vollständiger Lauf muss separat dokumentiert werden.
- Der ältere 3-Aufnahmen-Diagnoselauf bei 2× und ausgeschalteter Qualitätsauswahl
  hatte **0 % gemeinsame RGB-Abdeckung**. Sein Rechenabschluss bestätigt weder
  brauchbare Farbrekonstruktion noch zuverlässige astronomische Registrierung.
- **Korrektur nach unabhängiger Sternprüfung:** Auch die 31-Aufnahmen-Läufe oben
  und auf `d61eff4` sind kein Nachweis korrekter Ausrichtung. Ab Aufnahme 21 enthält
  M27 einen Meridianumschlag von ungefähr 179,85°. Der ausdrücklich gewählte
  Shift-Modus wurde durch feste Sensorpunkte zu falschen Identitätsmatrizen
  verleitet. Die Daten-/Exportprüfungen bleiben gültig; die damaligen Bilder sind
  keine qualifizierten Integrationen. Die Float-Sternsuche und der Rotationspfad
  werden deshalb separat korrigiert und erneut mit Sternrestfehlern geprüft.
  Der Prüflauf unterstützt nun `--align rotate|shift` und verwendet standardmäßig
  den Rotationsmodus wie die Oberfläche.
- Der affine Kern verwendet jetzt ein analytisches Green-Randintegral mit
  exakter Ausschluss-/Enthaltungsprüfung. Im synthetischen 512×768-CFA-Vergleich
  (drei gepaarte Läufe) ist er bei 1× **10,22-mal**, bei 2× **13,44-mal** schneller;
  Float32-Bilder und Abdeckung bleiben identisch. 30.000 zusätzliche Polygonfälle
  stimmen mit dem früheren Clipper bis auf `4,45e-16` absolute Fläche überein.
  Das ist keine gemessene Beschleunigung einer vollständigen realen Serie.

Der reproduzierbare FITS-Prüflauf liegt in
[validate_drizzle_real.py](../tests/validate_drizzle_real.py); er benötigt Original-FITS
und einen neuen Ausgabeordner. Diese Nachweise belegen keine allgemeine
Bildqualitätssteigerung und keine RC-Freigabe.
