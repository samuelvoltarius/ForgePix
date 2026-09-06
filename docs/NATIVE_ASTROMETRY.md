# Native lokale Astrometrie

`core/astrometry.py` sucht geometrische Sternzuordnungen zwischen einem linearen
Bild und einem kleinen lokalen Gaia-Katalog. Das Ergebnis ist ein geprüfter
ICRS-TAN-WCS. Es werden weder Bilder hochgeladen noch ein fremder Plate-Solver
gestartet. Der Solver selbst lädt auch keinen Katalog herunter.

## API und Einheiten

```python
from astrometry import solve, solve_positions, solution_header, write_solution_fits

hints = {"ra": 300.18, "dec": 22.795, "focal": 1151., "pixelsize": 4.63}
result = solve(linear_bgr, local_catalog, hints, cancel=cancel_event, log=log)
header = solution_header(result, source_fits_header)
write_solution_fits(linear_bgr, "separate-solved.fits", result, header=source_fits_header)
```

`solve_positions(xy, shape, katalog, hints, *, cancel=None, log=...)` akzeptiert
nach Helligkeit geordnete Sternzentren. `shape` ist `(Höhe, Breite)`, `xy` ist
`(x, y)` mit **nullbasierten Pixelzentren**. `solve` ermittelt diese Zentren mit
dem vorhandenen nativen Float-Sterndetektor; Mono sowie BGR sind zulässig,
negative und HDR-Messwerte werden nicht abgeschnitten. Ein Roh-CFA-Mosaik muss
vorher korrekt entwickelt werden; aus einem nackten Array lässt sich seine
Bayer-Natur nicht zuverlässig erkennen. Der Datei-/GUI-Adapter muss dies prüfen.

RA und DEC sind Grad im ICRS-System. Die Priorität für den Maßstab lautet:

1. `pixelscale_arcsec`: Bogensekunden pro tatsächlich vorliegendem Bildpixel.
2. `fov_width_deg`: Bildfeldbreite in Grad.
3. `focal` in mm und `pixelsize` in µm: **effektive** Brennweite einschließlich
   Reducer/Barlow und effektive Pixelgröße einschließlich Binning.

Die Feldbreite muss 0,02–5 Grad betragen, die Höhe höchstens 5 Grad. Die Suche
fragt einen Kegel mit 0,9 Bildfelddiagonalen Radius um den Hint ab. Der gefundene
Bildmittelpunkt muss innerhalb von 0,35 Diagonalen liegen. Je lineare Achse sind
70–130 % des vorgegebenen Maßstabs zulässig, maximal 8 % Anisotropie.

`SolveResult` enthält `.wcs`, `.report`, `.matched_pixels` und `.matched_radec`.
`.report` ist JSON-fähig; die Korrespondenzarrays enthalten zunächst Fit-Sterne,
danach unabhängig geprüfte Sterne. `.to_header()` enthält nur neue WCS-/Prüfkarten.
`solution_header(result, header=None)` erhält wissenschaftliche Metadaten und
ersetzt Struktur-, Skalierungs-, alte WCS-/SIP-/Verzerrungs- und Prüfsummenkarten.
Astropy erzeugt die Struktur und ggf. Integer-Skalierung beim Schreiben aus den
tatsächlichen Pixeln neu. Die Funktion kopiert keine referenzierten Dateien.

`write_solution_fits` erzeugt einen separaten FITS-Export; vorhandene Ziele werden
standardmäßig abgewiesen. BGR wird zu RGB-FITS-Ebenen, Mono bleibt zweidimensional.
Float32/Float64 und Integer-Messwerte bleiben erhalten. Für eine reine WCS-Ergänzung
einer vorhandenen FITS-Datei soll der Datei-Adapter deren ursprüngliches Datenarray
mit `solution_header` schreiben, sodass auch die originale Ebenenordnung erhalten
bleibt. Coverage-/Weight-Begleiter müssen durch diesen Adapter samt Prüfsummen in
das neue Ausgabeverzeichnis übernommen werden. Originaldateien bleiben erhalten.

## Geometrie und feste Qualitätsgrenzen

Ähnliche Dreiecke werden anhand sortierter Seitenverhältnisse erkannt. Die
gegenüberliegenden Seiten bestimmen die eindeutige Reihenfolge der Ecksterne;
fast gleichschenklige und nahezu kollineare Dreiecke werden vermieden. Rotation
ist frei, beide Paritäten sind erlaubt. Ein Meridian-Flip ist eine normale
180-Grad-Rotation. Für den WCS werden Katalogrichtungen gnomonisch um den Hint
projiziert und eine affine Abbildung aus den Pixelzentren angepasst.

Vor der Suche werden doppelte Bildpositionen entfernt. Jeder dritte Stern der
Helligkeitsreihenfolge wird fest zurückgehalten. Diese Sterne werden weder zur
Mustersuche noch zum Fit oder zur Auswahl des besten Modells benutzt. Es gibt
genau eine abschließende Prüfung; ein Fehler führt zur Ablehnung und nicht zur
Suche eines anderen Modells anhand dieser Prüfsterne.

- Mindestens 24 getrennte Bildsterne und 24 lokale Katalogsterne.
- Höchstens 240 Bildsterne, 2.000 helle Katalogsterne, 48 Bild- und 160
  Katalog-Mustersterne; höchstens 4.000 Hypothesen und 30 Sekunden Hypothesensuche.
- Eindeutige 1:1-Zuordnungen, keine mehrfach verwendeten Katalogreferenzen;
  nahe mehrdeutige Nachbarn werden ausgeschlossen.
- Fit: mindestens 12 Sterne und 30 % des Fit-Satzes; radialer RMS ≤0,8 Pixel,
  konvexe Sternhülle ≥12 % des Bildfelds und mindestens drei Quadranten.
- Unabhängige Prüfung: mindestens 8 Sterne und 45 % des Prüfsatzes; radialer
  RMS ≤0,8 Pixel, einzelne Zuordnungen <2 Pixel, Hülle ≥8 %, drei Quadranten.
- Eine zusätzliche Binomialprüfung fordert eine Zufallstreffer-Tailwahrscheinlichkeit
  ≤1e-10 unter der **Annahme gleichmäßig verteilter, unverbundener Detektionen**.
  Diese Modellannahme ist kein allgemeiner statistischer Echtheitsbeweis.

`parity` ist das Vorzeichen der CD-Determinante für Pixel-x/y nach Ost/Nord.
`positive_y_position_angle_deg` bezeichnet die Richtung der positiven Pixel-y-Achse
am Bildmittelpunkt, von Himmelsnord nach Osten gemessen. Die Darstellung einer GUI
mit nach unten wachsendem y ist davon getrennt.

## Grenzen und Nachweise

Der GUI-Einstieg liegt unter **Sternkatalog → Himmelsposition bestimmen**.
**Sternkatalog verwalten** lädt oder erstellt einen lokalen Gaia-Auszug. Ein neuer
Stack kann Koordinaten verloren haben: fehlende Angaben werden ausdrücklich
angezeigt und nicht aus dem heutigen Equipmentprofil ergänzt. Vorhandene
FITS-Koordinaten und ein vorhandener WCS-Maßstab lassen sich übernehmen.

`astrometry_file.solve_file` verarbeitet einen linearen FITS-Stack mit einem
primären Bild-HDU. Der neue Dateistand erhält die ursprünglichen Pixelwerte und
Datentypen exakt, einschließlich Float64 und unsigned Integer, sowie Einheiten,
Bilddomäne, Belichtungs- und KI-Metadaten. Alte WCS/Verzerrungskarten werden
ersetzt. Abdeckungs-/Gewichtsdateien werden kopiert; fehlende oder unvollständige
bekannte Abdeckung wird für diesen ersten Dateiweg abgewiesen. Roh-CFA muss
zuerst entwickelt werden. Originale und Katalog werden vor und nach Verarbeitung
über Prüfsummen kontrolliert. Der neue Ergebnisordner wird erst nach bestandener
Pixel- und Dateiprüfung freigegeben; Fehler und Abbruch ändern kein Original.

`astrometry_report.json` enthält Quellen, Katalogherkunft, ursprüngliche
Verarbeitungsberichte, Suchhinweise und Prüfresiduen. Projekte sichern und
exportieren ihn zusammen mit FITS und Abdeckung. Die Datei-/GUI-Tests
in `tests/test_astrometry_file.py` prüfen reale Sternbilder, Datentypen,
Einheiten, unsigned FITS-Skalierung, Dateiänderungen, Abbruch und Projekt-Export.

Der gleiche native Dateiweg ist für lokale Automatisierung verfügbar:

```text
ForgePix --solve --input linear.fits --catalogue gaia.npz --ra 300.17904 --dec 22.795087 --scale 0.8297 --output-root results
```

RA/DEC sind Grad, der Maßstab Bogensekunden pro Pixel. Der Ergebnisordner muss
existieren. Ctrl+C fordert einen sicheren Abbruch an. Die Beispielwerte stammen
aus historischen M27-FITS und sind keine allgemeine Equipment-Voreinstellung.

Dies ist ein **hintbasierter lokaler Solver**, keine blinde Ganzhimmelsuche.
Der TAN-Tangentialpunkt ist im ersten Modell fest auf den Hint gesetzt. Große
Felder weit neben diesem Hint und optische Verzerrungen können die Residualgrenzen
verletzen; dafür gibt es noch keine SIP-/Polynomkorrektur. Dichte Felder, stark
abweichende Sternhelligkeiten im Schmalband, gesättigte/ausgedehnte Quellen oder
eine unvollständige Katalogauswahl können zu einer sicheren Ablehnung führen.

Gaia-DR3-Koordinaten beziehen sich auf ICRS zur Referenzepoche J2016.0. Es erfolgt
keine Eigenbewegungs-, Parallaxen- oder Beobachtungsepochen-Korrektur. Die im
Katalog explizit vorhandenen Herkunftsfelder werden im Report übernommen; bei
alten Dateien bleibt die Epoche unbekannt. Kleine interne Residuen sind kein
Nachweis absoluter astrometrischer Genauigkeit. Diese Positionslösung führt keine
PCC, SPCC oder spektrale Farbkalibrierung aus.

`tests/test_astrometry.py` prüft gegen unabhängig mit Astropy erzeugte Himmelsfelder:
Rotation/180-Grad-Flip/beide Paritäten, RA-Nullpunkt und Polnähe, Fehler bei falschen
Hints/Zufallsfeldern/zu wenigen Sternen, absichtlich verfälschte Prüfsterne,
fehlende Referenzen, echte Float-Sternbilder und verlustfreie FITS-Metadaten-/WCS-
Roundtrips. Reale FITS-Nachweise werden separat mit Quell-/Katalog-/Code-Prüfsummen
gespeichert und sind keine allgemeine Kameraqualifikation.

Erster realer Nachweis vom 6. September 2026: ein vollständiger, bereits korrekt
registrierter M27-Stack mit 4144×2822 Pixeln aus ASIAIR/ASI294MC-Aufnahmen wurde
mit einem eigens geladenen Gaia-DR3-Feldauszug (16.123 Sterne, Radius 1,05 Grad,
G<15,5) gelöst. 154 Fit-Sterne und 78 von 80 unabhängigen Prüfsternen bestätigten
die Lösung, Prüf-RMS 0,427 Pixel, alle vier Quadranten. Geometriesuche/Fit dauerten
0,688 Sekunden; Lesen/Export/Prüfsummen im Nachweis zusammen 2,50 Sekunden, ohne
Katalogdownload. Der gelöste Export enthält exakt dieselben wissenschaftlichen
Pixel. Der Vergleich mit dem vorhandenen ASIAIR-TAN-SIP-WCS der tatsächlich
gewählten Referenzaufnahme 0017 ergab an 25 zusätzlichen Rasterpunkten 1,80″
Medianabweichung und 2,47″ Maximum. Dieser alte WCS wurde nicht zum Fit benutzt.
Die Restabweichung bleibt sichtbar; der Befund ersetzt keine absolute oder
kamerübergreifende Qualifikation. Die historischen Header-Hints dieses Datensatzes
waren 1151 mm und 4,63 µm; das aktuelle Equipmentprofil wird dadurch nicht geändert.

Primärquellen: [Astropy WCS-Pixelkonventionen](https://docs.astropy.org/en/stable/wcs/wcsapi.html),
[Astropy TAN-Projektion](https://docs.astropy.org/en/stable/wcs/supported_projections.html),
[ESA Gaia-DR3-Inhalt und Referenzepoche](https://www.cosmos.esa.int/web/gaia/dr3).
