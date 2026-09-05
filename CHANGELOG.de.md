# Changelog

*[🇬🇧 English version](CHANGELOG.md)*

Alle nennenswerten Änderungen an ForgePix. Format orientiert an
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/).

## [Unreleased]
### Live-Stacking: Korrektheit und Wiederherstellung

- Farbkanäle behalten beim Ausreißer-Verwerfen getrennte Gewichte; neutrale Pixel erhalten keinen künstlichen Farbstich.
- Stop/SIGINT exportiert das Ergebnis; temporär unlesbare Aufnahmen werden erneut versucht.
- Neue Dateien müssen über das Ruheintervall eine stabile Größe und Änderungszeit haben.
- Zustände speichern alle Verarbeitungsoptionen und werden atomar ersetzt. Alte Zustände ohne Formatversion werden aus den weiterhin vorhandenen Originalaufnahmen neu aufgebaut.
- Gemeinsame Kern-Abhängigkeiten für Installation, CI und Pakete; SciPy ist für die Mosaik-Optimierung enthalten, einfacher Zuschnitt benötigt es nicht.
- Regressionstests auf Windows, macOS und Linux; native Pakete müssen vor Veröffentlichung einen CLI-Funktionstest bestehen.

### Live-Stacking, Messphotometrie, lokaler Gaia-Katalog — und der belegte PixInsight-Vergleich

**Inkrementelles Live-Stacking** (`--live`, nur zusammen mit `--watch`). Der bisherige
Beobachtungsmodus stapelt bei JEDER neuen Aufnahme den ganzen Bestand neu: beim 200. Sub werden
200 Dateien gelesen, obwohl sich genau eine geändert hat. Jetzt werden laufende Summen
fortgeschrieben. An echten Subs gemessen: **Abweichung zum Stapeln am Ende 0,077 % der
Bildspanne, SNR 62,90 gegen 62,94**, und für ein Ergebnis nach jeder Aufnahme 2,8 s statt 7,5 s
(12 Subs — der Abstand wächst, weil das Neustapeln quadratisch zulegt: *n* gegen *n(n+1)/2*
Lesevorgänge). Der Zustand wird nach jedem Sub gesichert; ein Absturz um drei Uhr nachts kostet
nicht die halbe Nacht. Drei Entscheidungen stehen begründet im Code: Ausreisser-Verwurf erst ab
5 Frames (vorher ist die laufende Statistik zu dünn), das Gewicht je PIXEL statt je Frame (ein
Sub mit Satellitenspur soll nur an der Spur wegfallen), und ein Frame, der sich nicht ausrichten
lässt, kommt NICHT unverschoben in den Stapel — er würde die Sterne verdoppeln.

**Messphotometrie** (`--photometrie`, `core/photometrie.py`). Blenden-Photometrie mit
Ringhintergrund, differentiell gegen mehrere Vergleichssterne: veränderliche Sterne,
Bedeckungen, Exoplaneten-Transite. Gegen eine bekannte Wahrheit geprüft (40 Aufnahmen über 6 h,
3-h-Periode, 0,35 mag Amplitude, dazu eine Durchsicht-Schwankung und eine wandernde Bildlage):

| | Restabweichung |
|---|---|
| differentiell gegen drei Vergleichssterne | **0,058 mag** |
| dieselbe Reihe roh gemessen | 0,189 mag |

Der Faktor 3,3 *ist* der Grund für das Verfahren — die Durchsicht trifft alle Sterne gleich und
fällt heraus. Die Periode kam mit 2,95 h gegen 3,00 h heraus. Drei Stellen, an denen bewusst
nicht geschummelt wird: eine **tote Zeitachse** wird erkannt (die Test-TIFFs trugen kein
`DATE-OBS`, alle hatten dieselbe Schreibsekunde — die Lichtkurve sah völlig normal aus, die
Periodensuche lieferte 24,00 h statt 3,00 h), **ausgefressene Sterne** liefern einen systematisch
zu kleinen Fluss und werden aus der Meldedatei herausgehalten, und **ohne Katalogbezug** sind die
Werte instrumentell — das steht im Kopf der AAVSO-Datei UND im Bemerkungsfeld jeder Zeile.
Keine Oberfläche: die Wahl von Ziel- und Vergleichssternen ist eine Expertenentscheidung, und
das ehrlich zu sagen ist besser als eine Oberfläche, die rät.

**Lokaler Gaia-Katalog** (`core/gaia_lokal.py`, `--gaia-feld-laden`, PCC-Backend `lokal`).
Farbkalibrierung ohne Internet. Der Gaia-Katalog wird **nicht** mitgeliefert — Terabytes und
eigene Nutzungsbedingungen; stattdessen lädt man einmal mit Netz die Himmelsgegenden nach, die
man fotografiert. An 300 000 Sternen gemessen: **Abfrage 0,2 ms statt 22 ms** (Faktor rund 100),
Datei 22 Byte je Stern. Kein HEALPix, und zwar begründet: es bräuchte `healpy` oder
`astropy_healpix` und bringt bei dieser Grösse nichts — Deklinationsbänder mit 1/cos-skalierten
Zellen leisten dasselbe. Deckt der eigene Katalog ein Feld nicht ab, wird sauber abgebrochen
statt aus zehn Sternen eine Kanal-Skalierung zu raten, die aussieht wie gemessen.
*Ehrliche Einschränkung:* das Plate-Solving braucht weiterhin einen Solver; Siril und ASTAP lösen
offline, der Astrometry.net-Weg nicht.

**Der Test hat dabei genau den Fehler gefunden, der sonst nie auffällt:** die Zellenbreite wurde
aus der Deklination des EINZELNEN STERNS gerechnet statt aus seinem Band. Damit hatten zwei
Sterne im selben Band verschiedene Raster, und bei Deklination 78° gingen **sechs von 21 Sternen
verloren**, ohne dass irgendetwas fehlgeschlagen wäre. Dazu wurde die Rektaszensions-Spanne an
der polfernsten statt an der polnächsten Stelle des Kreises gerechnet. Jeder Test prüft jetzt
gegen die stumpfe Vollsuche auf exakte Gleichheit, an acht Feldern einschliesslich Pol,
Nullpunkt der Rektaszension und grossem Radius.

**PixInsight-Vergleich, Prozess für Prozess** ([docs/PIXINSIGHT.de.md](docs/PIXINSIGHT.de.md)).
Beim letzten Anlauf kam die Liste aus einem abgebrochenen Agenten, dessen elf heruntergeladene
Seiten allesamt 404-Fehlerseiten waren — das war eine unbelegte Behauptung. Diesmal aus dem
**Quelltext**: die PixInsight Class Library ist offen, jeder Prozess liegt dort als
`…Process.cpp`. Vier öffentliche Spiegel ausgezählt, Vereinigung **91 Prozesse**, jeder mit Datei
belegt. Die offizielle Dokumentation antwortet weiterhin mit HTTP 403 — auch das steht im
Dokument, ebenso dass die geschlossenen Module (Deconvolution, TGVDenoise, SCNR, StarMask,
StarAlignment …) dort nicht auftauchen und darum als *aus Kenntnis* gekennzeichnet sind.
Die drei echten Lücken, klar benannt: **PixelMath**, **allgemeine Maskenlogik** (die Bausteine
stehen, aber nur die Astro-Schritte sind angebunden) und **Gerätesteuerung**.

### Sternformen, Kometen, gemischte Belichtungen und ein Maskensystem

**Sternformen neu setzen** (`--astro-synthstar`). Koma am Bildrand, Sensorverkippung und
Nachführfehler verformen die STERNE, während der Nebel es kaum zeigt. Rechnerisch entzerren
lässt sich das nicht — die Sterne aber neu setzen: messen, entfernen, als runde Moffat-Profile
mit demselben Fluss zurückschreiben. An echten Daten (M27, ASI294MC Pro, 300 s, künstlicher
Nachführfehler von 7 px): **Verformung 0,790 → 0,388 bei einem Gesamtfluss von 1,0000** und
unangetastetem Nebel. Dieselbe Aufnahme ohne Nachführfehler misst 0,420 — das Ergebnis landet
also auf dem Niveau eines Bildes, das den Fehler nie hatte. Moffat statt Gauss, weil echte
Sterne durch das Seeing breitere Flanken haben; Gauss-Sterne wirken wie aufgeklebte Punkte.
*Ehrliche Grenze, auch im Hilfetext:* die Sternform wird dabei erfunden. Was auf dem Sensor
eine Linie war, wird ein runder Punkt — für Photometrie und Astrometrie ist das Ergebnis
unbrauchbar.

**Kometen-Stacking auf den Kern** (`--astro-komet`). Ein Komet wandert zwischen den Aufnahmen
vor den Sternen; sternausgerichtet wird er zum Streifen — genau das Objekt, wegen dem die Nacht
draussen verbracht wurde. Siril und die meisten anderen verlangen, den Kern in zwei Frames
**anzuklicken**. Hier findet ihn das Programm selbst: Median der sternausgerichteten Frames
abziehen, im Rest den hellsten *ausgedehnten* Fleck suchen (die Mindestfläche schliesst
Rauschspitzen aus — ein Komet ist diffus), und durch die Fundorte eine robuste Gerade legen.
Gegen eine bekannte Bahn geprüft: **Kern in 12 von 12 Frames gefunden, Rest zur Geraden 0,33 px,
grösster Fehler 1,30 px, Spitzenhelligkeit des Kerns Faktor 3,75.** Die Zeitachse kommt aus
`DATE-OBS`, wenn vorhanden — bei Wolkenpausen sind die Abstände ungleich. Fehlt der Zeitstempel,
wird das gemeldet statt stillschweigend die Bildnummer zu nehmen.

**Gemischte Belichtungszeiten.** Der offensichtliche Teil ist der Pegel; der wichtigere ist die
Ausreisser-Erkennung: ohne Zeitangabe vergleicht das Sigma-Clipping ein 60-s-Sub mit einem
300-s-Sub und hält das kurze für einen Ausreisser — es verschwendet sein Verwurfsbudget auf die
kurzen Subs und lässt dafür echte Störungen stehen. Gemessen (12 Subs, ein Satellit in einem
kurzen Sub):

| | SNR | Satellitenrest |
|---|---|---|
| sigma ohne Zeiten | 87,0 | 0,0423 |
| sigma mit Zeiten | 66,4 | 0,0161 |
| sigma mit Zeiten + Gewicht | **85,8** | **0,0161** |

Skalieren *allein* kostet also Rauschabstand — die hochgerechneten kurzen Subs bringen ihr
Rauschen mit. Deshalb schaltet die Pipeline bei erkannt gemischten Zeiten die SNR-Gewichtung
selbst mit, statt den Nutzer in die schlechtere Hälfte laufen zu lassen. Einheitliche Zeiten
ändern das Ergebnis Bit für Bit nicht.

*Gebaut, gemessen und wieder ausgebaut:* DeepSkyStackers „Entropy Weighted Average". Eine
Satellitenspur trägt die höchste örtliche Streuung überhaupt und bekommt damit das höchste
Gewicht. Auf derselben Serie stand die Spur danach bei **0,845 gegen einen Himmel von 0,036**
(Sigma mit Zeiten: 0,013 gegen 0,010, also praktisch weg), und die Himmelsstreuung stieg auf das
**414-fache**. Das Verfahren belädt zuverlässig genau die Störungen, die weggerechnet werden
sollen. Begründung steht im Code, ein Test hält fest, dass die Methode nicht zurückkommt.

**Maskensystem** (`core/masken.py`, `--astro-hintergrund-entrauschen`, `--astro-nebelkontrast`).
Das ist der eigentliche Unterschied zwischen einer Kette fester Werkzeuge und PixInsight: dort
lässt sich jeder Schritt nur dort anwenden, wo er hingehört. Entrauschen in den Hintergrund,
lokaler Kontrast in den Nebel. An echten Daten (10 Subs M27, gestapelt, gestreckt):

| | Himmelrauschen | Sternspitze |
|---|---|---|
| unbehandelt | 0,0252 | 0,948 |
| Entrauschen ohne Maske | 0,0155 | 0,919 |
| Entrauschen **mit** Maske | 0,0161 | **0,938** |
| lokaler Kontrast ohne Maske | 0,0640 | — |
| lokaler Kontrast **mit** Maske | **0,0255** | — |

Die Maske kostet fast nichts an Wirkung und verhindert den Schaden. *Ehrlich dazu:* der lokale
Kontrast hilft M27 auch maskiert nicht (im Nebel 0,0406 → 0,0343) — CLAHE komprimiert dort mehr,
als es hervorholt. Die Maske begrenzt in diesem Fall nur den Schaden.

**Drei Fehler, die erst durch dieses Messen sichtbar wurden:**
- **Die Sternerkennung rechnete mit `cv2.subtract`**, das negative Werte auf 0 abschneidet. Damit
  ist die halbe Rauschverteilung platt, MAD fällt auf 0 und die Schwelle rutscht auf ihren
  Notwert von 3/255. An einem echten Sub: **MAD 0,000 statt 10,378, Schwelle 3,0 statt 51,9,
  39,9 % der Pixel als Sternkandidat statt 4,0 %.** Auf linearen Subs fällt das nicht auf, auf
  gestreckten ist es verheerend.
- **Jeder Blob ab EINEM Pixel galt als Stern** (`area < 1` schloss nichts aus). Mit Mindestfläche
  4: linear 165 → 70 Blobs, gestreckt 8313 → 2079.
- **`synthstar` lief auf dem gestreckten Bild.** Dort deckte die Sternmaske 65 % ab, das
  Neusetzen kostete 27 % des Gesamtflusses und halbierte den Himmel. Jetzt auf den LINEAREN
  Daten (Maske 0,13 %, Gesamtfluss 1,0000) **und** mit Notbremse: über 10 % Maskendeckung bleibt
  das Bild unangetastet.

*Nebenbefund, mit behoben:* eine unbekannte Stacking-Methode fiel **still** in den Sigma-Zweig.
Über die Bibliotheks-Schnittstelle hätte ein Tippfehler klaglos etwas anderes gerechnet als
verlangt.

### Siril- und PixInsight-Gegenstücke — vier kleine Werkzeuge und zwei Nachbearbeitungsschritte

**`--astro-stretch-mode ddp` — Digital Development nach Okano.** Die Kurve `y = x/(x+k)` mit dem
Himmelspegel `k` als Wendepunkt: schwaches Signal wird kräftig angehoben, Helles komprimiert,
sodass Sterne keine weißen Klumpen werden. Der ehrliche Vergleich ist nicht der gegen das
Original, sondern der gegen eine Streckung, die **gleich viel ausbrennt** — bei 135 gegen 134
ausgebrannten Pixeln erreicht DDP den **2,2-fachen Nebelkontrast** einer Gamma-Kurve
(0,18 gegen 0,083). Eine Gamma-Kurve kam an diesen Kontrast überhaupt nicht heran: ihr Maximum
lag bei 0,098, danach fiel er wieder. Optional mit Unschärfemaskierung
(`--astro-ddp-schaerfe`), die im Original dazugehört.

**`--astro-unpurple` — Violettsaum um helle Sterne.** Die Optik bündelt Blau und Rot in einer
anderen Ebene als Grün, darum bleibt ein magentafarbener Hof stehen. Erkennungsmerkmal ist, dass
**beide** Kanäle über Grün liegen — das gibt es in echten astronomischen Objekten praktisch
nicht. Genau darauf prüft die Korrektur, statt einfach Magenta zu dämpfen: gemessen sinkt der
Magenta-Anteil von 0,0020 auf 0,0002, während ein roter Hα-Nebel im selben Bild **auf fünf
Nachkommastellen unverändert** bleibt. Der teuerste denkbare Fehlgriff wäre gewesen, Hα für
einen Farbfehler zu halten.

**`--dark-skalieren` — Master-Dark auf eine andere Belichtungszeit/Temperatur umrechnen.**
Die Falle steckt in der Physik: der Dunkelstrom wächst linear mit der Zeit (und verdoppelt sich
je rund 6 °C), der **Bias-Sockel aber nicht**. Wer das Dark einfach multipliziert, skaliert den
Sockel mit — gemessen ein Fehler von 0,020, während `bias + (dark − bias) · Faktor` die Wahrheit
**exakt** trifft. Ohne Bias-Frame wird der Sockel aus dem 1. Perzentil geschätzt, was an einem
realistischen Dark (die meisten Pixel fast ohne Dunkelstrom, dazu ein Schwanz heißer Pixel)
immer noch **35-mal näher** liegt als das naive Verdoppeln (0,0006 gegen 0,020). Die Grenze ist
mitdokumentiert und als Test festgehalten: bei über die Fläche gleichmäßigem Dunkelstrom greift
die Schätzung daneben, dort hilft nur ein echtes Bias-Frame.
Passen die Zeiten von Lights und Darks nicht zusammen, **warnt** die Pipeline jetzt auch ohne
diesen Schalter — umgerechnet wird aber nur auf ausdrückliche Anweisung, denn für den IMX294
(ASI294MC Pro) rät der Hersteller ausdrücklich davon ab.

**`astro.linear_match()` — ein Bild auf die lineare Skala eines anderen ziehen.** Für zwei
Nächte, zwei Filter, zwei Sessions mit unterschiedlichen Pegeln. Robuste Anpassung mit
iterativem Ausreißer-Verwurf, damit die Gerade dem Hintergrund und dem Nebel folgt und nicht ein
paar hellen Sternen: mittlere Abweichung 0,130 → 0,0005, mit Ausreißern im Bild ist die robuste
Variante 27-mal genauer als die einfache (0,0005 gegen 0,0144).

**Lokaler Kontrast und kantenerhaltendes Entrauschen** (Gegenstücke zu PixInsights
`LocalHistogramEqualization` und `TGVDenoise`). Beide Bausteine waren schon da, aber nicht
erreichbar: CLAHE steckte in `hdr.py` (dort in allen Voreinstellungen auf 0), der TV-Schritt nur
*innerhalb* der Dekonvolution gegen Ringing. Beide wirken jetzt **nur auf die Helligkeit**, sonst
kippen die Kanäle gegeneinander und es entstehen Farbflecken.
- **Dabei eine OpenCV-Falle gefunden:** `cv2.createCLAHE` **ignoriert den `clipLimit` bei
  16-bit-Eingabe**. Die Grenze wird als `clipLimit × Kachelfläche / Histogrammgröße` gerechnet;
  bei 65536 Klassen wird das kleiner als 1 und rundet auf null — es findet also gar keine
  Begrenzung statt, sondern volle Histogrammausgleichung samt hochgezogenem Rauschen. Gemessen
  lieferten `clipLimit` 1, 2, 4 und 8 **bitgleiche** Ergebnisse (Std 13337,7 bei allen vieren),
  in 8 bit dagegen 6,5 gegen 16,2. Jetzt wird in 8 bit ausgeglichen und das Ergebnis als *Faktor*
  auf die volle Genauigkeit angewandt. An einem echten Ergebnis (NGC7380): lokaler Kontrast
  0,183 → 0,194 / 0,209 / 0,241 / 0,274 — sauber gestuft, vorher waren alle Stufen identisch.
- **TV-Entrauschen:** Rauschen 0,1084 → 0,0960 (−11 %) bei nur −5 % lokalem Kontrast, es nimmt
  also mehr Rauschen als Detail.

In der Oberfläche sind Violettsaum und Dark-Skalierung unter „Erweitert" erreichbar; der
Bildstil setzt den Violettsaum mit (bei „Naturgetreu" aus, bei „Sterne betonen" voll — wer Sterne
betont, sieht den Saum am stärksten). 17 neue Tests (272 → 289, alle grün).

### Astro-Pass an echten Daten — Streckung, Filterkunde, Ausrüstung
Alles Folgende wurde an Alfreds eigenen Aufnahmen gemessen (ASI294MC Pro, 120 s, Gain 121,
−10 °C, SVBONY SV220 7 nm Dual-Band — ohne Darks und Flats, die es für diese Kamera nicht gibt).

**Der Kernbefund: zu helle Sterne und zu schwacher Nebel sind DASSELBE Problem.**
Der Weißpunkt einer Streckung wird immer von den hellsten Pixeln bestimmt — und das sind Sterne.
Das Nebelsignal lag nur 6 % über dem Himmel; nach der Normierung auf das 99,9-%-Quantil (= ein
Stern) blieb der Nebel bei 3,5 % des Wertebereichs liegen.
- **Starless-Streckung** (`--astro-starless-stretch`): Sterne raus, Nebel strecken (der jetzt
  selbst den Weißpunkt setzt), Sterne **linear** zurück. Gemessen: Nebel 0,513 → 0,628,
  ausgebrannte Pixel 0,573 % → 0,041 %.
  Wichtig: die Sternebene darf **nicht** mit derselben Kurve gestreckt werden — der erste Versuch
  tat das und hob die Wirkung auf (5,0 % der Pixel über 0,8, praktisch wie ganz ohne Starless).
- **Farberhaltende Streckung** (`--astro-color-stretch`): nur die Helligkeit läuft durch die
  Kurve, die Kanalverhältnisse bleiben. Eine kanalweise Streckung entsättigt massiv, weil der
  stärkste Kanal gegen Weiß läuft und alles zu Grau konvergiert — gemessen fiel die Sättigung
  von 0,257 auf 0,075, und der Sättigungsregler holte selbst auf 2,0 nur 0,108 zurück.
  Farberhaltend: **Sättigung 0,510, Cyan-Anteil 39 % → 55 %** bei gleicher Nebelhelligkeit.

**Weitere behobene Fehler:**
- **Die Hintergrund-Entfernung konnte farbige Verläufe nicht entfernen.** Sie schätzte EINE
  Graustufen-Fläche und zog sie von allen drei Kanälen gleich ab. An echten Dual-Band-Daten
  machte das den Rotkanal sogar **doppelt so schlecht** (11,6 % → 24,0 %), weil Rot viel
  niedriger liegt als Blau. Jetzt je Kanal: alle unter 0,2 %.
- **Der Gradient entstand erst beim Strecken.** Beide Linear-Exporte waren vollkommen flach
  (0,0 %), das fertige JPG hatte 35,6 %. Die vorhandene Nachkorrektur lief nur im Breitband-Zweig
  — im Dual-Band-Pfad passierte nach dem Strecken gar nichts. Jetzt für beide, und nach
  farberhaltender Streckung per **Division** statt Subtraktion (der Rest ist dort multiplikativ):
  47,4 % → 3,0 %.
- **Die Sternentsättigung entfärbte das ganze Bild.** Die feste 13×13-Hofaufweitung verschmolz in
  sternreichen Feldern zu einer Decke: 1,3 % echte Sternkerne → 33 % Maske → 65 % Wirkfläche, und
  die Sättigung fiel von 0,472 auf 0,257. Jetzt gedeckelt: 0,460 bei weiterhin neutralen Sternen.
- **`winsor` beschnitt Ausreißer praktisch nicht.** Es rechnete mit den Schwellen des ersten,
  unbereinigten Durchlaufs — ein Ausreißer bläht die Streuung selbst auf und landet innerhalb
  seiner eigenen Schwelle. Am Stack blieben 16,7 % eines kosmischen Treffers stehen, fast so viel
  wie beim simplen Mittelwert (19,6 %). Mit der iterativen Nachschätzung: 0,46 %.

**Neue Funktionen:**
- **Filterkunde** (`core/filters.py`, `--filter`): 20 Einträge mit durchgelassenen
  Emissionslinien, Halbwertsbreite und Entmischungs-Startwert. Belegte Herstellerangaben — SVBONY
  SV220 7 nm, Optolong L-eXtreme 7 nm / L-Ultimate 3 nm, Antlia ALP-T 3/5 nm, ZWO Duo-Band
  Hα 15 nm / OIII 35 nm. Erkennung aus dem FITS-Feld `FILTER`, inklusive Markennamen. Und die
  ehrliche Ansage: eine SHO-Palette aus Dual-Band-Daten ist synthetisch, weil SII gar nicht
  gemessen wurde.
- **Ausrüstungsrechnung** (`core/equipment.py`): Abbildungsskala aus Brennweite, Pixelgröße und
  Korrektor — und daraus die Entscheidung, die ForgePix bisher blind traf. Gut abgetastet sind
  2–3 px pro Sternhalbwertsbreite; darunter hilft Drizzle, darüber Binning. Das Seeing wird nicht
  geschätzt, sondern gemessen. Reducer/Flattener/Barlow, Teleskop- und Kamera-Vorgaben, und alles
  **selbst eintragbar** (eigener Eintrag mit gleichem Schlüssel ersetzt die Vorgabe).
- **Dithering-Erkennung**: die Bedingung, unter der Drizzle überhaupt etwas bringt. Stand vorher
  nur in Kommentaren.
- **Zeilen-Banding** (`--astro-banding`): Sensor-Ausleseversatz, den Dark/Flat/Bias nicht
  beseitigen. Gemessen Faktor 4–12 weniger, Gradient bleibt erhalten.
- **Ausgefressene Sternkerne einfärben** (`--astro-unclip-stars`): Farbe aus den intakten Flanken
  zurückholen. 12 von 16 farblosen Kernen → 0, Farbfehler −82 %, Helligkeit unverändert.
- **Sterne verkleinern** (`--astro-star-reduce`), **bestes Sub als Registrier-Referenz**,
  **zweite Verschmelzung und Slabs als Retusche-Pinselquellen** (`--alt-merge`, `--slabs`).

**Oberfläche:** die Astro-Werkzeuge sind angebunden — aber als **eine Auswahl in Klartext**
(Naturgetreu · Nebel betonen · Sterne betonen · Sensorfehler bereinigen), nicht als Reglerwand.
Die Einzelwerte erscheinen erst über „Erweitert". Fehlt ein externes Werkzeug, öffnet ein Knopf
die Download-Seite.

**Was NICHT eingebaut wurde, obwohl ausprobiert** — jeweils an Messungen gescheitert:
ein Glow-Master aus dem Median der unregistrierten Subs (entfernte 99 % des Glühens, fraß aber
den Nebel: 2,2 % Restamplitude), eine höhere Ghosting-Schwelle (machte den Detektor blind für
kleine Geister), eine sternfreie Normierung (65 % des Bildes brannten aus), automatisches
Slabbing (messbar wirkungslos — flach 59,6 gegen Slabs 58,9–59,1 bei Sollwert 60,0), und
Framing-Modi (die Ränder waren bereits sauber, Rauschen am Rand exakt wie in der Mitte).

**Ehrliche Grenze:** in den geprüften 14 Subs liegt Hα bei SNR 0,75 und OIII bei 0,72 — beide
unter 1, das Signal ist schwächer als das Rauschen. Es gibt echte OIII-Gebiete, aber sie ersaufen.
Mehr Farbe braucht mehr Belichtungszeit, nicht mehr Rechnung. Und ohne Darks/Flats bleiben
Restglühen und Vignettierung unkalibriert — das kann keine Nachbearbeitung ersetzen.

### Neue Funktionen — aus dem Vergleich mit Zerene, Helicon und Siril
- **Bestes Sub als Registrier-Referenz** statt des mittleren. Die Referenz bestimmt, worauf alle
  Frames gefittet werden; die Sub-Bewertung sortierte bisher nur Ausreißer aus, nicht das
  Mittelmaß. Die Daten (FWHM, Elongation, Sternzahl) lagen längst vor.
  Gemessen: bei gleichwertigen Subs ±0 %, bei schwachem mittleren Sub (48 statt 85 Sterne,
  Elongation 1,14 — besteht die Bewertung noch) **7 % kompaktere Sterne**.
- **Zeilen-Banding entfernen** (`--astro-banding`). Sensor-Ausleseversatz, den Dark/Flat/Bias
  NICHT beseitigen: er ist je Aufnahme anders und mittelt sich auch im Stack nicht weg.
  Gemessen gegen die bekannte Wahrheit: Banding um **Faktor 4–12** reduziert, der echte
  Gradient bleibt erhalten (links/rechts 0,0801/0,1510 → 0,0800/0,1508). Auch spaltenweise.
- **Zweite Verschmelzung als Pinselquelle** (`--alt-merge`). Der Standardgriff bei
  Zerene/Helicon: die Tiefenkarte hält Farben und glatte Flächen sauber, die Pyramide holt
  Detail an Haaren und Borsten — eine als Basis, die Stärken der anderen hineinpinseln. Läuft
  während des Stacks, nicht beim Öffnen des Dialogs: eine Verschmelzung dauert bei 24 MP ×
  16 Frames gemessen 30 s, das wäre ein Einfrieren der Oberfläche.
- **Slabbing** (`--slabs N`): Teilverschmelzungen über Gruppen benachbarter Aufnahmen, ebenfalls
  als Pinselquellen („Gruppe 2 (Aufnahmen 04-06)"). Das Endergebnis bleibt bewusst unverändert —
  nachgemessen bringt Gruppieren beim automatischen Verschmelzen keinen Vorteil (flach 59,6,
  Baum-Merge 58,7, Slabs zu 3/4/6: 59,0/58,9/59,1 bei Sollwert 60,0). Der Nutzen liegt im
  Übermalen, nicht im Zusammenrechnen.

### Behoben
- **Retusche-Quellen deckten nur den Anfang der Fokusreihe ab.** Es wurden die ERSTEN 16 Frames
  geladen — bei einer 150er-Serie liegen die alle in der vordersten Fokusebene, in der hinteren
  Hälfte des Motivs ließ sich nichts übermalen. Jetzt gleichmäßig über die Serie verteilt, bei
  unverändertem Speicherbedarf.

### Qualitäts-Pass — an synthetischer Wahrheit gemessen, nicht geschätzt
- **Die Stack-Note bewertete lückenhafte Fokusserien BESSER als lückenlose.** Gemessen an
  einer Fokusreihe aus einem bekannten scharfen Original: 9 Aufnahmen ohne Lücken bekamen
  85/100 bei 144 % der Originalschärfe, 3 Aufnahmen mit Lücken 92/100 bei nur 45 %. Ursache:
  der Lückenabzug war pauschal −8, während Ghosting −15 kostete — dabei ist die Fokuslücke
  der einzige dieser Mängel, den man nachträglich nicht beheben kann. Jetzt proportional zur
  fehlenden Abdeckung (`focus_analysis.focus_gap_penalty`), und der Text sagt, was zu tun ist.
  Nach dem Fix: 85 gegen 67 — Reihenfolge korrekt.
- **Die Ghosting-Heuristik behauptete Bewegung, wo keine war.** Gemessen überlappen die
  Wertebereiche: eine völlig statische Fokusreihe erreicht je nach Unschärfegrad 0,00–0,81 %
  Geisterfläche, eine Serie mit echter Bewegung 0,56–2,67 %. Eine Flächenschwelle kann das
  grundsätzlich nicht trennen (ein Versuch mit höherer Schwelle machte den Detektor für
  kleine Geister blind und wurde verworfen). Die Empfindlichkeit bleibt daher unverändert,
  aber der Befund benennt jetzt eine Möglichkeit statt einer Diagnose und verweist auf die
  Geister-Karte; der Abzug sinkt von 15 auf 8. Die Messwerte stehen als Kommentar im Code.
- **`winsor` beschnitt Ausreißer praktisch nicht.** Es rechnete mit den Schwellen des ersten,
  unbereinigten Durchlaufs — ein Ausreißer bläht die Streuung aber selbst auf und landet
  innerhalb seiner eigenen Schwelle. Nachgerechnet an 9× 0,06 + 1× 1,00: hi=0,859, Ergebnis
  133 % zu hell. Am Stack blieben 16,7 % eines kosmischen Treffers stehen — fast so viel wie
  beim simplen Mittelwert (19,6 %). `winsor` nutzt jetzt dieselbe iterative Schwellen-
  Nachschätzung wie `sigma`: 0,46 % Rest (Faktor 36).

### Windows-Portierungs-Pass — ForgePix war auf Windows praktisch unbenutzbar
ForgePix wurde auf einem Mac gebaut (Pfade und Konsole sind dort UTF-8). Unter Windows gilt
die Locale-Codepage (deutsch: cp1252). Jeder Befund unten wurde reproduziert, behoben und
gegengeprüft — nicht aus dem Code abgeleitet.

**Bilder wurden nicht geladen / Ergebnisse still verloren:**
- **`cv2.imread` gab bei JEDEM Nicht-ASCII-Pfad `None` zurück** — schon bei einem deutschen
  `Blüte_01.jpg` oder einem Nutzerordner `C:\Users\Jürgen\`. Die Pipeline lief mit null
  Bildern durch und meldete trotzdem Erfolg.
- **`cv2.imwrite` meldete `True`, schrieb aber KEINE Datei**, wenn der Zielpfad einen Umlaut
  enthielt. ForgePix sagte „Fertig", und das fertige Stack-Ergebnis war weg. Der gefährlichste
  der Befunde.
- Behebung: `constants.imread`/`imwrite` lesen und schreiben die Bytes selbst
  (`np.fromfile`/`imdecode` bzw. `imencode`/`tofile`); OpenCV dekodiert nur noch. Die `None`-
  bzw. `False`-Semantik der Originale bleibt erhalten. 75 Aufrufstellen umgestellt.

**Die Pipeline stürzte an ihrer eigenen Logausgabe ab:**
- Im Code stehen 1134 Zeichen, die cp1252 nicht kodieren kann (`→` 378×, `─` 462×, `σ`, `α` …).
  Jedes `print` damit warf `UnicodeEncodeError` und riss den Lauf ab. Gemessen: `--help`
  stürzte ab; der HDR-Lauf starb an seiner ersten Logzeile mit Exit-Code 1.
- Behebung: `constants.force_utf8_stdio()` in beiden Einstiegspunkten; der GUI-Kindprozess
  bekommt zusätzlich `PYTHONIOENCODING=utf-8` (greift auch im PyInstaller-Binary).
  `constants.log_print()` ersetzt `log=print` als Vorgabe in 62 Engine-Signaturen — eine
  Logzeile darf eine laufende Berechnung nie abbrechen.
- 15 `subprocess`-Aufrufe dekodierten die UTF-8-Ausgabe von Siril/GraXpert/exiftool mit der
  Locale-Codepage (`Frühling→` kam als `FrÃ¼hlingâ†'` an) → `encoding="utf-8"` gesetzt.

**Fremdtools wurden unter Windows nie gefunden:**
- Alle vier Sucher kannten nur macOS-Pfade (`/Applications`, `/usr/local/bin`). Belegt:
  Siril 1.4.2 lag unter `C:\Program Files\Siril\bin\siril-cli.exe` und `find_siril()` lieferte
  `None`. Windows-Installer tragen sich üblicherweise nicht in den PATH ein.
- Neu: `siril_engine._windows_cands()` (Program Files, Program Files (x86),
  `%LOCALAPPDATA%\Programs`, `%ProgramData%`) für Siril, GraXpert, StarNet++ (inkl. der
  v2.5-Namen) und Cosmic Clarity. Auf macOS/Linux ändert sich nichts.
- `graxpert_engine.find_cli()` hatte eine ZWEITE, abweichende Kandidatenliste und delegiert
  jetzt an `tools_engine.find_graxpert()` — wer eine pflegte, reparierte nur die Hälfte.

**Ehrlichkeit gegenüber dem Nutzer:**
- **Ein Lauf ohne Ergebnis endete mit Exit-Code 0** → die GUI zeigte grün „Fertig ✓" und
  meldete „Stack fertig 🎉", obwohl alle Frames aussortiert waren und nichts entstand.
  Jetzt Exit-Code 1; `--no-stack` bleibt ein gewollter Erfolg. Der Batch-Modus zählt die
  tatsächlich erzeugten Stacks („3/5" statt „5").
- **Fehlendes astropy warf eine 20-zeilige Traceback-Wand.** `constants.require_astropy()`
  nennt jetzt Grund, Lösung (`pip install astropy`) und Entwarnung (JPG/TIFF/PNG/RAW laufen
  weiter). Vier bisher ungeschützte Stellen abgesichert — darunter das GraXpert-Backend, das
  astropy brauchte, ohne dass das irgendwo dokumentiert war.
- `constants.ForgePixFehler` trennt erwartete, behebbare Fehler (eine Klartextzeile) von
  echten Programmfehlern (voller Traceback für Bugreports). Strg-C endet mit „Abgebrochen.".

**Tests:** neue Datei `tests/test_windows_gaps.py` (16 Tests). Zwei der sechs roten Tests waren
Testfehler, keine Codefehler: die i18n-Tests lasen UTF-8-Quellen ohne `encoding=`, die
FITS-Tests meldeten das fehlende OPTIONALE astropy als Fehlschlag statt zu überspringen.
Vorher 165 Tests / 6 Fehler → jetzt 181 Tests / 0 Fehler (6 übersprungen: optionale Deps).

## [1.27.1] – 2026-07-22
### Großer Aufräum-/Korrektheits-Pass — 4 Review- + 3 Fix-Agenten über die ganze Codebasis
Kein neues Feature, dafür ~70 verifizierte Befunde gefixt (Bugs > Leaks > toter Code > Duplikate).
Alle 165 Tests grün; GUI + Pipeline gegeneinander verifiziert.

**Pipeline-Bugs (die stillen, gemeinen):**
- **Echtes PCC/SPCC lief im Standard-Pfad NIE:** eine doppelte `_broadband`-Definition in
  `_astro_write` überschrieb den Siril/Gaia-Pfad mit dem Lite-Fallback — die ganze
  dreistufige Kette (Siril-SPCC → Gaia → Lite) war nur mit `--no-astro-stretch` erreichbar. Gefixt.
- **Bias-Master wurde angenommen, gemeldet — und nie verrechnet** (eigene Engine). Jetzt: ohne
  Dark wird Licht−Bias kalibriert, Flat wird bias-korrigiert; mit Dark kein Doppelabzug.
- **Drizzle-lite skalierte nur die Translation,** nicht den Bildinhalt → Frames lagen unskaliert
  im 2×-Canvas. Jetzt wird die volle Matrix skaliert (wie im True-Drizzle-Pfad).
- **FITS-Normierung aufs frame-eigene Maximum** (Hotpixel/Satellit verschob die Helligkeit ganzer
  Subs) → feste Skala, ein gemeinsamer Helper (`siril_engine.fits_scale01`) für astro/siril/GraXpert.
- **Wavelet-Fokus-Stacking hatte bei Farbbildern null Effekt** (Fusion wurde verworfen) und clippte
  16-bit auf 255 → Luma-Übertrag + dtype-korrektes Clipping.
- **Mosaik-Belichtungsausgleich war ein No-Op** (Kompensation auf verworfener Kopie) → wirkt jetzt.
- **Highlight-Rekonstruktion** entsättigte teil-geclippte Pixel statt sie aus den intakten Kanälen
  zu füllen (`.any` → `.all`).
- Doppel-Schärfen im `--auto`-Modus, Dedup-Culling gegen bereits entfernte Frames, Median-Stack
  ignorierte die lokale Normalisierung, `align_mode`/`detector` waren No-Op-Parameter (jetzt
  verdrahtet, inkl. Dreiecks-Matching als Fallback), Sub-Bewertung: Nebel-Blobs fraßen das
  Sternzähl-Budget, ein korruptes Bild brach die ganze Analyse ab, Lucky: Top-N-Frames doppelt
  gezählt + ~5 GB RAM-Spitze beim Mittelbild, HDR fehlte in drei Modus-Checks der GUI.

**GUI:**
- GraXpert/StarNet/Starless liefen **synchron im GUI-Thread** (Beachball bis 30 min) → jetzt
  Hintergrund-Thread mit Live-Log.
- API-Schlüssel wurden im Klartext ins Log geechot → maskiert. SSH-Passwort nicht mehr per
  `sshpass -p` in der Prozessliste sichtbar (`sshpass -e`).
- `/tmp` hart kodiert (alle Vorschauen unter Windows kaputt) → `tempfile.gettempdir()`;
  Explorer-`/select` unter Windows gefixt; zerhackte Umlaute im Live-Log (UTF-8-Chunk-Puffer);
  Zusatz-Sessions klebten bis zum App-Neustart an jedem Astro-Lauf; Vorschau-/Thumbnail-Cache
  wird jetzt wirklich genutzt (statt jedes Mal neu zu rechnen); Ctrl+5 + Kürzel-Hilfe für HDR.
- ~30 hartkodierte Dialog-Strings durch `tr()` ersetzt + 32 neue EN-Übersetzungen.

**Aufräumen:**
- Toter Code raus (u. a. ShineStacker-Relikte, ungenutzte Engine-Finder, `fast_denoise`,
  `refine_mask`); Duplikate konsolidiert: `to_uint8()`/`luma()` (Rec.709 statt 601/709-Mix!)
  in `constants.py`, `write_tiff16`/`read_fits_bgr`/`find_siril` in `siril_engine`,
  `app_settings()`/`save_image()`/`_is_makro()` in der GUI.
- Extern-Tools: Stale-Output-Falle (alter Lauf galt als Ergebnis) + returncode-Prüfung;
  Tempdir-Leaks (Siril-Brücke, SPCC) mit try/finally; Cosmic Clarity wischt nicht mehr fremde
  Dateien aus input/output; exiftool als EIN Batch-Aufruf statt Prozess pro Datei.
- Ehrlichkeits-Korrektur: **AutoBGE/Statistical_Stretch** aus der Siril-Brücke entfernt — sie
  waren in 1.27.0 beworben, aber nie von der App aus aufrufbar (nur AberrationRemover ist verdrahtet).

**Zweite Runde (die vorher zurückgestellten Umbauten):**
- **Eine Klarheit-Implementierung:** Vorschau (GUI) und finale Pipeline nutzten zwei verschiedene
  „Klarheit"-Algorithmen → gleicher Reglerwert, anderes Ergebnis. Jetzt überall der multiskalige,
  halo-arme Equalizer; belegt: Preview ≡ Endergebnis (max. Abweichung 1/255 = Quantisierung).
- **Ein Decode statt drei:** die Kachel-Schärfematrix wird direkt in `analyze` mitgerechnet —
  Verwackelt-Filter und Fokus-Abdeckung dekodieren die Serie nicht mehr erneut (identisches
  Culling an synthetischer Serie belegt).
- **Astro-Stacking-IO:** registrierte 16-bit-TIFFs werden beim Median/Linearfit-Stacking per
  memmap **zeilenweise** gelesen (vorher: pro Band jede Datei komplett dekodiert — bei 100 Frames
  × 20 Bändern 2000 Voll-Reads); Normalisierungs-Median + SNR-Sigma in EINEM Vorab-Pass
  (vorher zwei); Ergebnis bit-identisch verifiziert.
- **Registrierung ~120× schnelleres Offset-Voting** (KD-Baum statt O(n²)-Python-Schleife,
  30/30 Testfälle identisch zur alten Semantik; Fallback ohne scipy vorhanden).
- **Maschinenlesbare Status-Marker:** die Pipeline meldet jetzt `PHASE:`/`RESULT:`/`RATIONALE:`
  (wie das bewährte `PREVIEW:`) — Statuszeile, Ergebnis-Erkennung und „Warum?"-Panel der GUI
  hängen nicht mehr an deutschen Log-Formulierungen (alte Schlüsselwort-Erkennung bleibt als
  Fallback für ältere Pipeline-Versionen).

## [1.27.0] – 2026-06-28
### Siril-Python-Brücke, KI-Super-Resolution, optionaler Remote-GPU — alles lokal-first
- **Siril-Python-Brücke** (`core/siril_pyscript.py`): treibt Sirils mitgelieferte Python-Skripte
  **headless** (load → pyscript → save). Eingebaut: **AberrationRemover** (KI-Sternform-Korrektur,
  optional vor StarNet), **AutoBGE** (Background), **Statistical_Stretch**. SCUNet/DeepSNR sind
  reine GUI → ehrlich nicht headless.
- **KI-Super-Resolution** (`--upscale`, `core/superres.py`): Real-ESRGAN 2× (BSD-3, ONNX) über
  onnxruntime (CoreML/CUDA/CPU) — rein lokal, kein externes Programm, modulübergreifend (Fokus/
  Panorama …). Graceful, wenn onnxruntime/Modell fehlen. Schärfe 20→134 ohne Artefakte.
- **GraXpert: optionaler Remote-GPU-Host** (z. B. DGX Spark) per `FORGEPIX_GRAXPERT_REMOTE` —
  NUR wenn konfiguriert; Default und Fallback sind IMMER lokal (nicht jeder hat einen Spark).
- **Cosmic-Clarity-Schärfung** etwas milder (weniger plastisch, VLLM-Feedback).
- Ehrlich offen: GraXpert-CUDA auf der Spark-ARM braucht ein onnxruntime-gpu-Build (pip-CPU-only);
  lokaler Mac-Weg (CoreML) ist der schnelle Default.

## [1.26.0] – 2026-06-27
### Profi-KI-Tool-Kette (StarNet → GraXpert → Cosmic Clarity), korrekte Reihenfolge, Robustheit
Externe KI-Tools als optionale Backends voll eingebunden (ForgePix bleibt MIT — Tools werden nur
aufgerufen, nicht gebündelt). Kern-Regel: **Bearbeitungs-Filter wirken NIE auf die Sterne.**
- **Starless-Workflow neu geordnet:** Strecken → **StarNet** (Sterne raus, unbearbeitete Sternebene) →
  **GraXpert** (Hintergrund + KI-Entrauschen) → **Cosmic Clarity** (KI-Schärfung, freie BlurXTerminator-
  Alternative, MIT) — alle drei NUR auf dem sternenlosen Nebel — → Nebel-Boost → Sterne unbearbeitet
  zurück. Hintergrund wird farbneutral gezogen (kein Blau-/Grünstich). VLLM am echten IC5146: **Note 1–2**.
- **GraXpert** läuft jetzt mit GPU (CoreML/CUDA) und macht standardmäßig Background-Extraction **+**
  Denoising; als Astro-Backend wählbar (`--astro-bg-backend graxpert`).
- **Cosmic Clarity** neu integriert (`core/cosmicclarity_engine.py`, AppleSilicon-CLI/MPS) +
  GUI-Tool-Pfad.
- **Siril**-Engine nutzt jetzt zusätzlich `subsky` (Background) + `rmgreen` (SCNR), nicht nur Stack.
- **Panorama:** `--no-autocrop` wirkt jetzt auch hier (Mosaik cropte vorher immer).
- **Robustheit:** je 10 Läufe pro Modul mit variierenden Einstellungen — Fokus/Panorama/HDR/Langzeit/
  Astro 10/10, RAW 9/10 — keine Abstürze, keine schwarzen/verfärbten Ergebnisse.

## [1.25.1] – 2026-06-27
### An ECHTEM Material verifiziert (eigene Aufnahmen) + objektiv per VLLM bewertet — Default-Bugs gefixt
Jedes Modul mit echten eigenen Aufnahmen getestet und das Ergebnis von einem Vision-Modell (statt „per
Auge") benoten lassen; dabei mehrere Defekte im **Standard-Pfad** gefunden und behoben.
- **Astro – Standardausgabe war SCHWARZ:** `--astro-stretch` war standardmäßig AUS, `color_balance`
  clippte den Himmel hart auf 0, und der Default-Stretch (`asinh`) normierte auf die hellen Sterne.
  Jetzt: Stretch standardmäßig AN, neutraler Hintergrund-Sockel, Default **MTF**; asinh/ghs holen das
  schwache Signal über einen Sky-Anker heraus (alle drei Modi funktionieren). VLLM: schwarz → **gut (2-)**.
- **Astro – Blau-/Grünstich:** der aggressive Stretch blies winzige Kanal-Differenzen zum Farbstich auf →
  exakte Hintergrund-Neutralisierung vor dem Stretch + SCNR/Neutralisierung danach. Hintergrund farbneutral.
- **Astro – Gradienten-Entfernung:** verwirft Stützpunkte jetzt residuenbasiert (2D-Trend) statt global.
- **HDR – Fusion-Blaustich/Flachheit:** Auto-Weißabgleich + mehr Biss (VLLM 4 → 2). Radiance-Pfad nutzt
  echte EXIF-Belichtungszeiten + Chroma-Denoise; lokales Durand-Tonemapping überbelichtet nicht mehr.
- **Langzeit:** `suggest_mode` erkennt Kameraschwenk (Phasenkorrelation) und richtet automatisch aus.
- **Panorama:** Auto-Zuschnitt auf das größte randvolle Rechteck (keine schwarzen Zacken; VLLM 4 → 1).
- **Fokus-Stacking:** Ausrichtungs-Ränder werden automatisch weggeschnitten (`--no-autocrop` für vollen Rahmen).
- **GUI:** Astro-Stretch-Default jetzt MTF (farbneutral), klarere Labels.

## [1.25.0] – 2026-06-27
### Alle restlichen tiefen Lücken gebaut — 6 parallele Modul-Agenten + Integration
Der komplette `DEEP_GAPS.md`-Backlog als echte Engine-Algorithmen umgesetzt (ein Subagent je Modul,
dann Verifikation + Fixes + CLI/GUI-Verdrahtung). Reines OpenCV/NumPy/scipy. +55 Tests (161 gesamt, grün).
- **Fokus:** Focus-Breathing-Korrektur (`--focus-breathing`), cross-scale-konsistenter Pyramiden-Merge
  (`--focus-method pyramid-consistent`), kantenerhaltende Tiefenkarten-Regularisierung (`--focus-regularize`),
  Fenster-Energie-Selektor + Schärfster-Frame-Deghost.
- **Astro:** Dreiecks-/Asterismus-Stern-Matching (rotations-/spiegel-invariant), Per-Frame-SNR-Gewichtung +
  iteratives Sigma (`--astro-weight`), regularisierte+Deringing+Tiled-PSF-Dekonvolution
  (`--astro-deconv-regularize`), klassisches morphologisches Star-Removal (`--astro-starless-classic`).
- **Lucky:** Drizzle/Super-Resolution 1.5×/3× (`--lucky-drizzle`), iterativ verfeinerte Referenz
  (`--lucky-refine`), adaptive Alignment-Punkt-Dichte (`--lucky-adaptive-ap`).
- **HDR/Langzeit:** Punkt-Stern-Stacking mit Feldrotations-Ausgleich (`--longexp-mode stars`), lokales
  Durand-Tonemapping (`--hdr-tonemap local`), Gradient/adaptives + Optical-Flow-Deghosting
  (`--hdr-deghost-flow`), räumlich beschränkte Sky-Maske.
- **Panorama:** eigener scipy-Bündelausgleich mit Linsen-Verzeichnungs-Selbstkalibrierung (a/b/c),
  photometrische Vignette+Belichtungs-Optimierung, manuelle N-Bild-Kontrollpunkte, Include/Exclude-Masken.
- **RAW:** echtes Farb-Management (Kamera-Matrix → Rec2020/ProPhoto/sRGB-Arbeitsraum + Bradford),
  szenenbezogenes filmic-Tonemapping (hue-erhaltend), getrenntes Luma/Chroma-Denoise (16-bit-treu),
  parametrische Masken (nach Luminanz/Hue/Sättigung).
- Ehrlich nicht machbar: Jupiter-Derotation (Ephemeriden), AMaZE/RCD-Demosaic (GPL-LibRaw), ML-Tools.
  Panorama-Verzeichnungs-BA und RAW-Farb-Management sind engine-fertig; die Default-Verdrahtung des
  Farb-Managements in die Haupt-Pipeline ist ein Folgeschritt.

## [1.24.0] – 2026-06-27
### Tiefe Lücken geschlossen — Algorithmus-Fixes aus dem Profi-Tool-Audit (`docs/DEEP_GAPS.md`)
Ein Modul-für-Modul-**Algorithmus**-Audit (keine Feature-Häkchen) fand substanzielle Lücken; die Quick-Wins:
- **Fokus — ECC-Subpixel war toter Code:** `align_local.ecc_refine` (helligkeitsinvariant) war gebaut, aber
  nie aufgerufen — der Pfad nutzte nur ORB→Affine (schwach an defokussierten Stack-Enden). Jetzt als
  Verfeinerungsstufe verdrahtet (defokussierter Restfehler −39%).
- **Astro — Luminanz-Rauschreduktion** (`--astro-denoise`): es gab KEINE Luminanz-NR (nur Chroma-Blur) →
  der Stretch zog Hintergrundrauschen hoch. Multi-Skalen-Wavelet-NR auf den linearen Daten (−42% Bg-Rauschen
  auf IC5146, Nebel erhalten).
- **Astro — RBF-Hintergrund-Extraktion** (DBE/GraXpert-Prinzip): der alte Tiefpass folgte dem Nebel und fraß
  ihn; jetzt Thin-Plate-Spline-Fläche durch robuste Sky-Stützpunkte (Nebel-Stützpunkte sigma-geclippt).
  Gradient-Rest 0.0000 vs 0.0035.
- **Lucky — Quality-Metrik + robustes Patch-Mittel:** helligkeitsnormierte, vorgeglättete Schärfe (war
  rausch²-getrieben); pro AP **Sigma-Clip** + Korrelations-Konfidenz (ein Fehl-Match zieht den Punkt nicht mehr).
  Plus die frühere **Feature-Homographie-Auto-Ausrichtung** gegen Streifen bei Schwenks.
- **Panorama — `WAVE_CORRECT_AUTO`** statt hartem HORIZ (echter Bug bei Multi-Row/Gitter-Mosaiken).
- **RAW — Dehaze + Capture-Sharpening:** Dark-Channel-Prior-Dehaze und RL-Capture-Sharpening (holt echte
  Auflösung) als Editor-Regler — die RL-Engine lag vorher nur im Astro-Pfad.
- **Langzeit — hotpixel-robuster `bright`:** Normierung aufs 99.95%-Perzentil statt max.
- `docs/DEEP_GAPS.md` dokumentiert jede Lücke ehrlich, inkl. der großen Brocken als eigene Projekte (RAW-
  Farb-Management, Lucky-Drizzle, Panorama-Verzeichnungs/Photometrie-BA, echtes Punkt-Stern-Stacking, ML-Tools).
- +5 Tests (106 gesamt, grün).

## [1.23.0] – 2026-06-27
### Die letzten Vergleichs-Lücken geschlossen — Dekonvolution, Sky-Maske, Lucky-Fix, Kontrollpunkte
Die restlichen 🟡/❌ aus der Profi-Tool-Scorecard, gebaut und getestet:
- **Astro — Dekonvolution** (`--astro-deconv`): Richardson-Lucy mit aus den Sternen geschätzter PSF,
  auf dem linearen Master, mit weichem Stern-Schutz gegen Ringe. Die eine fehlende Astro-*Technik* —
  an IC5146 verifiziert (engere Sterne, kein Overshoot).
- **Langzeit — automatische Himmel-Maske** (`--longexp-freeze-auto`): trennt Himmel (bewegte Sterne)
  vom statischen Vordergrund über die zeitliche Pixel-Streuung statt festem Höhen-Split (Sequator-Stil).
- **Fokus — Paint-from-Frame-Retusche:** der Retusche-Editor malte schon aus einem gewählten Quell-Frame;
  der Fallback richtet diese Frames jetzt on-the-fly aufs Ergebnis aus → funktioniert auch ohne Ebenen-Datei.
- **Lucky-Imaging — der echte Fix:** der MAP-Stack war zu weich, weil er nie geschärft hat. Jetzt
  Wavelet-Schärfung INNERHALB `lucky_stack_map` (AutoStakkert/RegiStax-Prinzip: Stack mittelt Rauschen,
  Schärfung holt die Auflösung zurück), weniger Frames je Punkt. Bei realistischem Rauschen schlägt
  MAP+Schärfung jetzt das beste Einzelbild (gegen synthetisches Seeing mit Ground-Truth validiert).
  *(Ehrlich: braucht eine echte Teleskop-Aufnahme — statisches Ziel + Seeing; ein Schwenk-Flythrough ist
  kein Lucky-Szenario.)*
- **RAW — lokaler Kontrast-Equalizer:** der „Klarheit"-Regler nutzt jetzt einen multiskaligen (halo-armen)
  lokalen Kontrast-Equalizer (darktable/RawTherapee-Modul) statt Einzel-Radius-Unsharp.
- **Panorama — manuelle Kontrollpunkte:** `mosaic.stitch_from_points` + ein `ControlPointDialog`
  (Werkzeuge-Menü), um zwei Kacheln von Hand zusammenzusetzen, wenn die Automatik versagt (Homographie
  aus ≥4 Nutzer-Punktpaaren, gefederte Blende). Erstversion für ein Paar; voller N-Bild-Hugin-Optimierer offen.
- +6 Engine-Tests (104 gesamt, grün).

## [1.22.1] – 2026-06-27
### Astrometry.net-Online-Plate-Solving für PCC (eigener Key)
- Der Gaia-PCC-Pfad kann jetzt über die **nova.astrometry.net-Online-API** blind plate-solven, wenn kein
  Siril/lokaler Solver da ist — Solver-Reihenfolge **Siril → Astrometry.net → ASTAP/solve-field**.
- **Dein eigener API-Key**, zur Laufzeit eingegeben — **nie hardcodiert oder committet**: GUI-Feld unter
  *Setup → Externe Tools* (passwort-maskiert, nur in den lokalen App-Einstellungen gespeichert),
  `--astrometry-key` oder Env-Var `ASTROMETRY_API_KEY`. Lädt die Luminanz hoch, pollt den Job, lädt die
  WCS-Datei (mit dem nötigen `Referer`-Header) und macht dann das Gaia-DR3-Matching wie gehabt.

## [1.22.0] – 2026-06-27
### Echte photometrische Farbkalibrierung (PCC/SPCC) mit dreistufigem Fallback
PCC wurde von der stern-basierten Lite-Version auf **echte Katalog-Photometrie** aufgewertet
(`core/photometric.py`), mit sauberem Abstieg, sodass es nie hart scheitert:
1. **Siril-SPCC** (bevorzugt): steuert ein installiertes Siril headless — Plate-Solve +
   Spektrophotometrische Farbkalibrierung gegen den **Gaia-DR3**-Katalog. Keine weiteren Python-Abhängigkeiten.
2. **Eigener Gaia-Pfad** (MIT): Plate-Solve (nutzt Sirils Solver, sonst ASTAP / astrometry.net) →
   Gaia-DR3-Kegelsuche via `astroquery` → Katalogsterne über WCS den Bildsternen zuordnen → Kanal-Abgleich.
3. **PCC-lite** (immer verfügbar): stern-basierter neutraler Weißabgleich aus dem Bild selbst — kein
   Katalog, kein Netz.
- `--astro-pcc-backend {auto,siril,gaia,lite}`, `--astro-oscsensor`, `--astro-narrowband`; GUI-Combo +
  Sensorfeld + Schmalband-Schalter; an echten IC5146-Subs verifiziert (Plate-Solve + WCS bestätigt; die
  Katalog-Abfrage braucht Netz/Gaia-Zugang, den die Sandbox blockierte — die Kette fällt dort auf Lite zurück).
- Hinweis: KI/LLMs werden für die Photometrie bewusst **nicht** genutzt — PCC ist eine Messung
  (Sternfarben gegen Katalog), kein Ermessen.
- `astroquery`/`scipy`/`lensfunpy` als optionale Abhängigkeiten dokumentiert. +4 Tests (97 gesamt, grün).

## [1.21.0] – 2026-06-27
### Profi-Tool-Lücken-Welle — alle restlichen 🟡/❌ aus dem Vergleich eingebaut
Schließt die letzten Teil- und offenen Punkte aus dem Profi-Tool-Vergleich (Helicon/Zerene,
Siril/PixInsight/APP, Photomatix/Lightroom, Sequator/StarStaX, Hugin/PTGui, RawTherapee/darktable).
Reines OpenCV/NumPy(/scipy).
- **GraXpert/StarNet laufen jetzt automatisch:** LZW-TIFF-Bug behoben (cv2 schreibt TIFFs per Default
  LZW-komprimiert, was GraXpert/StarNet via `tifffile` nicht lesen können) — Eingaben werden transparent
  unkomprimiert umgeschrieben, der Starless-/Gradienten-Schritt greift jetzt von selbst.
- **Astro — volles GHS-Strecken** (`--astro-stretch-mode ghs`, `--astro-ghs-d/-b/-sp`): voll parametrischer
  Generalised Hyperbolic Stretch (Intensität D, Charakter b, Symmetriepunkt SP), numerisch integriert →
  garantiert monoton, bildet [0,1]→[0,1].
- **Astro — Linear-Fit-Clipping** (`--astro-method linearfit`): PixInsight-artiger Geraden-Fit je Pixel +
  Residuen-Verwerfung — besser als Sigma-Clipping bei wenigen Subs.
- **Astro — TPS-Feinregistrierung** (`--astro-tps`): Thin-Plate-Spline gegen Restverzeichnung
  (Feldkrümmung bei Weitwinkel/Refraktor) → runde Sterne über das ganze Feld.
- **Astro — echtes Drizzle** (`--astro-drizzle-true`, `--astro-pixfrac`): echte Variable-Pixel Linear
  Reconstruction (inverser Punktkernel mit pixfrac, Fluss+Gewicht) → Auflösungsrückgewinnung aus
  geditherten Subs statt nur Hochskalieren.
- **Astro — photometrischer Farbabgleich** (`--astro-pcc`): stern-basierter neutraler Weißabgleich aus
  vielen ungesättigten Sternen (PCC-lite, kein Online-Katalog nötig).
- **HDR — Radiance-Tonemapping** (`--hdr-method radiance`, `--hdr-tonemap reinhard|mantiuk|drago`):
  Debevec-Radiance-Map + Tonemapping als dramatische Alternative zur Exposure Fusion.
- **Langzeit — Sigma-Clipping** (`--longexp-sigma`) und **Vordergrund einfrieren** (`--longexp-freeze`,
  Sequator-Stil: Himmel langzeitbelichtet, Boden scharf aus einem Einzelbild).
- **Fokus — Helicon-Regler Radius/Smoothing** (`--focus-radius`, `--focus-smoothing`) für depthmap/average
  und **Halo-Retusche** (`--focus-method halofix`): Dual-Output — PMax-Schärfe auf die Pixel-Hülle der
  Quellen begrenzt → Schärfe ohne Halo-Über/Unterschwinger.
- **RAW — Objektivkorrekturen** (`--lens-auto` via lensfun wenn installiert, sonst
  `--lens-vignette/-distortion/-ca`) und AMaZE-Demosaic-Versuch mit sauberem Fallback.
- Alles in CLI + GUI + i18n verdrahtet; +9 Engine-Tests (93 gesamt, grün).

## [1.20.0] – 2026-07-13
### Profi-Tool-Welle — jedes Modul aufgewertet (recherchiert gegen Helicon/Zerene, AutoStakkert/PSS, Siril/PixInsight, Photomatix/Sequator/Hugin, RawTherapee/darktable)
Die modulübergreifende Erkenntnis — **lokale (nicht-rigide) Ausrichtung** — plus die wirkungsvollste
Technik je Profi-Tool, in reinem OpenCV/NumPy. Siehe `docs/ROADMAP.de.md`.
- **Fundament lokale Ausrichtung (`core/align_local.py`):** ECC-Subpixel (helligkeitsinvariant) +
  gedeckelter dichter Optical-Flow — gemeinsamer Baustein.
- **Lucky Imaging — echtes Multi-Point (MAP):** AP-Raster, pro Region beste Frames + Subpixel-Versatz,
  nahtloser Hann-Blend (`lucky_stack_map`). Speichert immer auch das schärfste Einzelbild. (Ehrlich:
  bei strukturarmen/niedrig aufgelösten Scheiben kann das Einzelbild gewinnen; MAP glänzt bei
  detailreichen Mond-/Planeten-Zielen.)
- **Wavelet-Schärfung (`core/wavelet.py`):** à-trous Multi-Skalen-Boost + Entrauschen (RegiStax-Stil),
  farbtreu. Geteilt von Lucky/Astro/Editor.
- **Astro:** lokale Normalisierung vor der Rejection (`--astro-local-norm`) + MTF-/Histogramm-Stretch
  (`--astro-stretch-mode mtf`, PixInsight-AutoSTF-Stil, reversibel).
- **HDR:** Deghosting (`--hdr-deghost`, bewegungsmaskierte Referenz-Fusion).
- **Langzeit:** Kometen-Modus + Strichspuren-Lückenfüllung (`--longexp-gapfill`).
- **Panorama:** explizite `cv2.detail`-Pipeline (Projektion, Belichtungsausgleich, GraphCut-Nähte,
  MultiBand-Blending) statt Black-Box-Stitcher, mit Rückfall.
- **RAW-Editor (`core/develop.py`):** Lichter-Rekonstruktion (`--raw-highlights`), Demosaic-Wahl
  (`--raw-demosaic`), Tonwertkurven (PCHIP), NLM-Entrauschen, lokale Anpassungs-Masken.
- **Fokus-Stacking:** Method A + Wavelet-Merge mit Konsistenz-Vote + Farb-Neuzuweisung
  (`--focus-method average|wavelet`).
- Alles in CLI + GUI verdrahtet, zweisprachig, +13 Tests (83 grün).

## [1.19.3] – 2026-07-12
### Fokus-Map liest sich besser (nur scharfe Bereiche färben)
- Die Fokus-Herkunfts-Karte zeigte in **strukturlosen/unscharfen Flächen** (z. B. Bokeh-Hintergrund)
  buntes **Zufallsrauschen** — dort gibt es keinen echten „schärfsten" Frame. Jetzt werden solche
  Flächen **neutral-grau** gelassen (Konfidenz aus der absoluten Kachel-Schärfe); gefärbt wird nur,
  wo wirklich **scharfe Kanten/Details** liegen. Die Form des Motivs ist sofort lesbar.
  (`focus_analysis.focus_map(mask_flat=True)`, Standard an)

## [1.19.2] – 2026-07-11
### Camera-Raw-Editor überall + HDR korrekt
- **„Bearbeiten" (Camera-Raw) funktioniert jetzt überall:** ist immer aktiv und öffnet ohne Lauf-
  Ergebnis einen Datei-Dialog für **jedes beliebige Bild — auch RAW** (wird treu entwickelt). HDR-
  Ergebnisse landen wie alle anderen im `stack/`-Ordner und sind damit direkt im Editor bearbeitbar.
- **HDR-Modus korrekt eingestuft:** `is_hdr` wird nicht mehr fälschlich als „Makro" behandelt —
  Fokus-Map und Retusche (beides fürs Fokus-Stacking) tauchen im HDR-Modus nicht mehr auf.

## [1.19.1] – 2026-07-11
### HDR-Looks (Presets gegen den flachen Fusion-Look)
- Exposure Fusion (Mertens) wirkt von Natur aus **flach** — neue **Tonlook-Presets** geben Pop, treu
  (nur Tonwerte, keine erfundenen Inhalte): `--hdr-look {neutral,natural,vivid,dramatic}` bzw.
  GUI-Auswahl „Look" im HDR-Modus. **Standard = `natural`** (dezenter Kontrast/Pop), damit HDRs nicht
  mehr flach rauskommen. `vivid` kräftiger, `dramatic` mit starkem lokalem Kontrast (CLAHE, Wolken/
  Struktur), `neutral` lässt das reine Fusion-Ergebnis. Umgesetzt im LAB-Raum: Schwarzpunkt,
  Kontrast-S-Kurve (Sigmoid), Clarity (lokaler Kontrast), Sättigung. (`hdr.apply_look`)

## [1.19.0] – 2026-07-10
### Neu — 📸 HDR-Modul (Exposure Fusion) + robustere Fokus-Ausrichtung
- **HDR aus Belichtungsreihen (`core/hdr.py`, Modus „📸 HDR"/`--hdr`):** Verrechnet AEB-Reihen
  (z. B. −1/0/+1 EV) per **Mertens Exposure Fusion** zu einem durchgezeichneten Bild — Lichter aus
  den dunkleren, Schatten aus den helleren Aufnahmen, ohne Tonemapping-Artefakte und ohne bekannte
  Belichtungszeiten. **Mehrere Reihen** in einem Ordner werden automatisch erkannt (`--hdr-bracket`
  für feste Gruppengröße) und einzeln verrechnet. **Freihand-Reihen werden vor der Fusion
  feature-basiert (rigide) ausgerichtet** → kein Ghosting. Klarstellung in der UI: HDR ≠ Fokus-Stacking.
- **Paarweise/sequenzielle Ausrichtung (`--align-sequential`, GUI „Paarweise ausrichten"):** Richtet
  jedes Frame an seinem **direkten Nachbarn** aus (2→1, 3→2, …) und kettet die Transformationen auf —
  statt alle auf ein globales Referenzbild. Benachbarte Frames sind fast identisch → sehr robuste
  Schätzung. Macht bei tiefen Stativ-Reihen mit großem Fokusbereich den Unterschied zwischen „hält"
  und „bricht".
- **Hierarchischer Baum-Merge (`--merge tree`, GUI „Baum-Merge"):** Verschmilzt paarweise
  (1+2, 3+4, …) und die Ergebnisse weiter — bei vielen Frames oft sauberer als alles flach auf einmal.

## [1.18.8] – 2026-07-09
### Makro: bewegtes Motiv + Depth-Map-Methode
- **Bewegtes Motiv (Motiv-Ausrichtung):** Neue Option „Bewegtes Motiv (auf das Motiv ausrichten)"
  (Ausrichtung-Gruppe) bzw. `--moving-subject`. Bei Motiven, die während der Schärfereihe leicht
  wandern (Blüte im Wind, Insekt), werden die Fotos **am Motiv** ausgerichtet statt am ganzen Bild;
  Aufnahmen, in denen sich das Motiv zu weit bewegt hat, werden **verworfen** — gegen Doppelkonturen.
  Die **Automatik erkennt** bewegte Motive selbst (Schwerpunkt-Wanderung der Farbsättigung) und
  schaltet die Motiv-Ausrichtung mit Anfänger-Klartext-Hinweis (Stativ/windstill) automatisch ein.
  Die Konfidenz-Anzeige wertet die (gewollt) verschobene, unscharfe Hintergrund-Zone nicht mehr
  fälschlich als Ghosting.
- **Depth-Map-Verschmelzung (Helicon „DMap"-Stil):** Neue Auswahl „Verschmelzungs-Methode" bzw.
  `--focus-method {pyramid,depthmap}`. `depthmap` wählt pro Bildpunkt das **schärfste Foto**
  (potenzgewichtet, lochfrei) — stark bei **harten Tiefenkanten** (Insekten, Münzen, Platinen).
  Standard bleibt die **Laplace-Pyramide**, die bei feinen/weichen Strukturen (Blüten, Fell) in
  Tests klar schärfer ist; die Methode ist ehrlich beschriftet, damit man je Motiv das Richtige wählt.

## [1.18.7] – 2026-07-08
### Starless-Workflow: Nebel + Sterne live einstellbar
- StarNet läuft **einmal**, danach lassen sich **Nebel-Boost** und **Stern-Stärke** über zwei Regler
  (Astro-Bereich: „Starless: Nebel / Sterne") **sofort** nachregeln — die Vorschau aktualisiert in
  ~30 ms, ohne dass StarNet neu rechnet (die Ebenen werden gecacht). So bekommt man Sterne dezenter
  oder kräftiger, Nebel flacher oder voller — alles sichtbar im Vorschaubild. (Klarstellung: das
  Endbild enthält selbstverständlich die Sterne; nur die separate `*_nebula`-Datei ist sternenlos.)

## [1.18.6] – 2026-07-07
### Starless-Workflow: kräftigerer, kernschonender Nebel-Boost
- Der Nebel-Boost im Starless-Workflow hebt jetzt **schwache/mittlere Nebelbereiche deutlich an**
  (asinh-Lift), lässt aber den **bereits hellen Kern unverändert** (Kern-Maske) — so brennt z. B.
  der M42-Trapez-Kern nicht weiter aus, während die äußeren Hα-Schwingen sichtbar mehr Struktur
  zeigen. Plus lokaler Kontrast + dezente Sättigung.

## [1.18.5] – 2026-07-06
### Neu — ⭐ Starless-Workflow (StarNet++ Anbindung)
Voll automatisierter „Profi-Weg" für Astro: **Sterne trennen → Nebel verstärken (lokaler Kontrast +
dezente Sättigung) → Sterne per Screen-Blend sauber zurück** (`1−(1−Nebel)·(1−Sterne)`). Davor läuft
GraXpert (Gradient) auf dem Linearbild, danach unsere Palette/Streckung. Holt deutlich mehr
Nebelstruktur raus, ohne Sterne aufzublähen. (`core/starless.py`.)
- **Modus-abhängig, immer erklärt:** Im **Anfänger-Modus** macht „✨ Veredeln" den vollen Workflow
  automatisch (wenn StarNet da ist). Im **Profi-Modus** bleibt „Veredeln" schlank (nur GraXpert) und
  der volle Workflow liegt unter **Werkzeuge → Starless-Workflow**; einzelne Schritte (nur StarNet /
  nur GraXpert) ebenfalls dort. Jeder Schritt wird im Log erklärt.
- **StarNet++ Auto-Erkennung** schon in v1.18.4 erweitert. **macOS-Hinweis** (Guide + bei fehlendem
  Tool): unsignierte StarNet-Binärdatei einmal mit `xattr -dr com.apple.quarantine <ordner>` entsperren.

## [1.18.4] – 2026-07-05
### Astro: Feinschliff nach Feedback
- **Weicherer Auto-Stretch:** Schwarzpunkt von Median+0.5·MAD auf **0.25·MAD** gesenkt und Kern-Schutz
  früher (ab 80 % statt 85 %). Zeigt **mehr von schwachen Nebel-Außenbereichen**, ohne das Rauschen
  hochzuziehen; der helle Kern bleibt geschützt (keine weitere Überstrahlung). Sterne bleiben gleich.
- **Paletten umbenannt & neu sortiert** (verständlicher, sinnvolle Default-Reihenfolge):
  **HOO — naturgetreu (Dual-Band)** · **Bicolor — warm/natürlich** · **Foraxx — dynamisch** ·
  **SHO Gold — synthetischer Hubble-Look**.
### Externe Tools
- **StarNet++ Auto-Erkennung erweitert:** sucht jetzt auch in `~/siril/starnet`, `~/Documents/starnet`,
  `~/StarNet` und im Siril-App-Ordner. (Hinweis: macOS kann die unsignierte StarNet-Binärdatei
  quarantänen — einmalig `xattr -dr com.apple.quarantine <ordner>` nötig.)
- **Siril liest OSC jetzt farbig:** beim Konvertieren wird **CFA automatisch debayert** (`-debayer`,
  wenn BAYERPAT im Header) — vorher kam aus dem Siril-Pfad nur Graustufen.

## [1.18.3] – 2026-07-04
### Aufgeräumt (Code)
- **Tote Imports entfernt** (pyflakes): ~18 ungenutzte Imports in main_window.py/components.py
  (u. a. hashlib, subprocess, ungenutzte Qt-Klassen, nicht genutzte components-Re-Importe),
  eine ungenutzte Variable (`peaks`) und ein f-string ohne Platzhalter. Keine Funktionsänderung.
- README-Screenshots auf den aktuellen v1.18.2-Stand gebracht (übersetzte UI, ausklappbares Astro).

## [1.18.2] – 2026-07-03
### UI aufgeräumt + Style konsolidiert (Stabilisierung)
- **Astro-Panel entrümpelt:** selten gebrauchte Optionen (Engine, Bias, FITS, Hot-/Cold-Pixel,
  Drizzle, Binning) sitzen jetzt in einem **ausklappbaren „Erweitert"-Abschnitt** (standardmäßig
  eingeklappt). Häufiges (Methode, Kappa, Ausrichten, Dark/Flat, Auto-Kalibrierung, Filter, Palette,
  Sessions) bleibt direkt sichtbar. Neue wiederverwendbare `CollapsibleSection`.
- **Layout-Bug behoben:** zwei Astro-Elemente lagen auf derselben Grid-Zeile (überlappten) — getrennt.
- **Style konsolidiert:** wiederkehrende Inline-Stile (grüne Abschnitts-Überschriften, graue Hinweise)
  durch zentrale THEME-Regeln (`QLabel#sectionHeader`, `QLabel#hint`) ersetzt — weniger Magie-Strings,
  einheitlicheres Aussehen.
- Keine Funktionsänderung, keine neuen Features.

## [1.18.1] – 2026-07-02
### Stabilisierung (Übersetzungen + Doku)
- **Englisches UI war zur Hälfte deutsch — behoben.** Rund 90 sichtbare Strings standen nicht in
  `tr()` (u. a. der **komplette Bearbeiten-/Retusche-Dialog** in components.py, wo `tr` nicht mal
  importiert war) und erschienen im englischen UI auf Deutsch. Alle gewrappt + englische
  Übersetzungen ergänzt (en.json deutlich gewachsen). DE bleibt unverändert (Schlüssel = deutscher Text).
- **i18n-Test verschärft:** neuer Regressions-Schutz, der rohe deutsche UI-Strings (in QLabel/
  QPushButton/QCheckBox/QGroupBox/setToolTip/setWindowTitle/setPlaceholderText/_row) erkennt, die
  nicht in `tr()` stehen — damit die Lücke nicht zurückkommt.
- **Handbuch (DE):** Der Dual-Band/Schmalband-Block stand fälschlich im **Makro**-Kapitel; jetzt
  korrekt im **Astro**-Abschnitt (wie in der EN-Anleitung).
- Keine neuen Features — bewusste Stabilisierungsrunde.

## [1.18.0] – 2026-07-01
### Schneller
- **Parallele Registrierung:** die Ausricht-Schleife nutzt jetzt alle Kerne (OpenCV gibt den GIL
  frei) statt seriell zu laufen — deutlich schneller bei vielen Frames.
- **Palette sofort umschalten:** ein Dual-Band-Palettenwechsel (HOO/SHO/Foraxx/Bicolor) färbt das
  fertige 32-bit-Linearbild **in Millisekunden neu ein**, statt den ganzen Stack neu zu rechnen.

### Besser (Ergebnis)
- **Weit geditherte Frames zurückholen:** Frames, die sich nicht an die Referenz ausrichten lassen,
  werden über eine **Cluster-Brücke** (Sub-Referenz → ORB-Brücke → Verkettung) gerettet — JEDER
  zurückgeholte Frame wird verifiziert (Sterne müssen sauber auf die Referenz fallen), sonst bleibt
  er außen vor. (Im Test: 15 → 17 von 20 Frames, ohne Verschmieren.)
- **Kalibrierung automatisch erkennen:** dark-/flat-/bias-Unterordner werden im Aufnahme-Ordner
  (und darüber) gefunden und angewendet — entfernt Amp-Glow/Vignette ohne Handarbeit.
- **Binning (2×/3×):** fasst Pixel zusammen → höheres SNR, rundere/kleinere Sterne (gut bei
  überabgetasteten Daten).
- **Mehrere Nächte/Sessions kombinieren:** „➕ Weitere Nacht/Session" führt mehrere Aufnahme-Ordner
  desselben Objekts zu EINEM Stack zusammen (mehr Integration = besseres Ergebnis).

### Einfacher
- **Live-Vorschau:** während des Stackens (Astro & Makro/Fokus) zeigt ForgePix laufend ein
  Zwischenergebnis, statt erst am Ende.

### CLI
- Neu: `--bin {1,2,3}`, `--also <ordner…>` (weitere Sessions), `--no-auto-calib`.

### Tests
- +3 Tests (Binning, Kalibrier-Auto-Erkennung). 62 grün.

## [1.17.0] – 2026-06-30
### Neu — One-Click „✨ Veredeln" (GraXpert-Anbindung)
- **Veredeln-Button in der Ergebnis-Leiste (Astro/Langzeit/Hybrid):** schickt das fertige
  32-bit-Linearbild mit EINEM Klick durch **GraXpert** — erst Gradienten-/Hintergrund-Extraktion,
  dann KI-Entrauschung — und reimportiert das Ergebnis automatisch. Der übliche Schritt nach dem
  Stacken, ohne Tool-Wechsel. (`tools_engine.run_graxpert_enhance`.)
- **Freundlicher Hinweis statt Fehler, wenn ein Tool fehlt:** ist GraXpert (oder StarNet) nicht
  installiert, erklärt ForgePix in einem Dialog, was das Tool macht und wo es das **kostenlos** gibt
  (graxpert.com / starnetastro.com), und bietet an, das fertige Linearbild im Dateimanager zu zeigen.
  Pfade unter **Setup → Externe Tools** (oder Auto-Erkennung). Gilt auch für die Einzel-Aufrufe
  GraXpert/StarNet im Werkzeuge-Menü.
- Hinweis: RC-Astro (BlurXTerminator/StarX/NoiseX) sind proprietäre KI-Modelle und lassen sich nicht
  nachbauen — ForgePix bindet die freien Tools GraXpert/StarNet ein.

### Tests
- +2 Tests für die Tool-Anbindung (Hinweis-Infos, sauberer Abbruch ohne GraXpert). 59 grün.

## [1.16.19] – 2026-06-29
### Behoben (Astro: türkise Sterne neutralisiert, Farben ruhiger)
- **Sterne leuchteten knallig cyan/türkis.** In Schmalband ist Sternfarbe ein Artefakt (durchs
  Dual-Band-Filter kommen nur Hα-Rot + OIII-Cyan → türkise Sternkugeln). Die Stern-Entsättigung
  erfasste bisher nur die hellsten Kerne (Helligkeits-Gate zu hoch) und ließ den farbigen **Glow/Hof**
  stehen. Jetzt: niedrigeres Gate (auch mittelhelle Sterne) **plus Aufweiten der Maske auf die
  Sternhöfe** → Sterne werden neutral/weiß, der Nebel behält seine Farbe.
- **Sättigung-Default 1.1 → 1.05** (CLI/GUI/KI) — ruhigere, natürlichere Farben.

## [1.16.18] – 2026-06-28
### Behoben (Astro: echte Bearbeitung statt „Comic" — Sterne rund, Rauschen runter)
Gründliche Diagnose an echten IC-5146-Daten (Dual-Band, ASI294MC Pro) hat zwei ernste Fehler
aufgedeckt und behoben:

- **Sterne waren tropfenförmig (mit Geist) — Registrierungs-Bug.** `cv2.phaseCorrelate` rastete
  bei Astro-Frames auf dem **festen Fixed-Pattern** (Hotpixel/Amp-Glow) ein und verfehlte die über
  die Nacht **gewanderten Sterne** komplett (Residuum bis ~27 px → verschmierte Sterne). Ersetzt
  durch **stern-basiertes Offset-Voting** (robust gegen Hotpixel) + RANSAC-Feinausrichtung; ORB als
  Fallback für große Dither-Sprünge. Sterndetektion von Otsu (fand nur ~5 Sterne) auf eine
  **rauschadaptive MAD-Schwelle** (100–200 Sterne) umgestellt. Residuum jetzt **<1 px = runde
  Sterne**. Frames, die sich nicht sicher ausrichten lassen (z. B. weit weggedithert, kaum
  Überlappung), werden **übersprungen statt verschmiert reingemittelt**.
- **Ergebnis viel zu knallig/verrauscht — Stretch-Defaults entschärft.** Schwarzpunkt liegt jetzt
  am **robusten Himmelshintergrund** (Median + 0.5·MAD) statt bei festen 0,08 % → Hintergrund wird
  dunkel, Rauschen wird nicht hochgezogen. **Chroma-Entrauschung** (Farbe glätten, Luminanz scharf)
  killt den bunten Grieß. Default-Stretch von 14 → **6**, Sättigung 1.3 → **1.1**; KI-Vorschlag
  ebenso gedeckelt (Strength ≤12, Sättigung ≤1.25). GUI-Regler-Defaults angepasst.

### Tests
- +2 Registrierungs-Regressionstests (Drift trotz fester Hotpixel finden; MAD-Sterndetektion). 57 grün.

## [1.16.17] – 2026-06-27
### Tests & Doku (Dual-Band-Paletten nachgezogen)
- **Tests für alle Paletten:** Bisher war nur HOO testabgedeckt. Jetzt auch **SHO** (Hα→gold),
  **Foraxx** (reines Hα bleibt rot) und **Bicolor** (synthetisches Grün vorhanden) — 55 Tests grün.
- **Handbuch (DE/EN) aktualisiert:** Der Astro-Abschnitt beschrieb nur HOO. Jetzt sind **Filter-Auswahl
  (SVBony SV220 / L-eXtreme, Auto-Erkennung)** und alle **vier Paletten** (HOO · SHO · Foraxx · Bicolor)
  dokumentiert.

## [1.16.16] – 2026-06-27
### Hinzugefügt (Dual-Band: Bicolor-Palette)
- **Vierte Palette „Bicolor" (Cannistra-Technik):** Aus den zwei vorhandenen Schmalband-Kanälen
  (Hα, OIII) wird der fehlende **synthetisch errechnet** — hier das **Grün** als G = max(OIII, 0.5·Hα).
  Ergebnis: natürlicheres, wärmeres Bernstein/Gold, **weniger Magenta** und neutralere Sterne als
  reines HOO. Auswahl jetzt: **HOO · SHO (gold) · SHO Foraxx · Bicolor** — GUI-Dropdown + CLI
  `--palette hoo|sho|foraxx|bicolor`. Wie immer: SII bleibt außen vor (nur Hα+OIII vorhanden).

## [1.16.15] – 2026-06-26
### Hinzugefügt (Dual-Band: Foraxx-Palette)
- **Dritte Palette „SHO Foraxx" (dynamisch):** Recherchiert (thecoldestnights.com / Foraxx-Methode)
  und eingebaut — der Grün-Kanal wird je nach Hα·OIII-Stärke gemischt: G = f·Hα + (1−f)·OIII mit
  f = (Hα·OIII)^(1−Hα·OIII). Dadurch **reines Hα → rot, Hα+OIII gemischt → gold, reines OIII → blau**
  (nuancierter als das flache SHO; rein-Hα-Ziele bleiben korrekt rot statt erzwungenem Gold).
  Auswahl jetzt: **HOO · SHO (gold) · SHO Foraxx (dynamisch)** — GUI-Dropdown + CLI `--palette
  hoo|sho|foraxx`. SII bleibt synthetisch (kein echtes SII in Dual-Band).

## [1.16.14] – 2026-06-26
### Hinzugefügt (Dual-Band-Palette: synthetisches SHO)
- **SHO/Hubble-Palette aus Dual-Band (gefaktes SII):** Neue Palette-Auswahl bei Dual-Band —
  **HOO** (rot+teal, datentreu) oder **SHO synthetisch** (Hubble gold+blau). Da Dual-Band **kein
  echtes SII** enthält, wird SII aus Hα **synthetisiert** (gängige Narrowband-Praxis): Rot=SII(≈Hα),
  Grün=0.8·Hα+0.2·OIII, Blau=OIII → Hα-Bereiche werden gold, OIII blau. Klar als „synthetisch,
  nicht wissenschaftlich" gekennzeichnet. GUI-Palette-Dropdown + CLI `--palette hoo|sho`. Sterne
  bleiben entsättigt, Nebel farbig.

## [1.16.13] – 2026-06-26
### Geändert (Astro: Filter einstellbar)
- **Filter-Auswahl im Astro-Modul** statt einfachem Häkchen: Dropdown **„Kein Filter / Breitband"**
  vs. **„Dual-Band Ha+OIII (z. B. SVBony SV220, L-eXtreme)"**. Wird zusätzlich automatisch aus dem
  FITS-Header erkannt. Dual-Band → HOO-Verarbeitung (rot+teal), Breitband → Farbkalibrierung+SCNR.
  Einstellung wird gemerkt.

## [1.16.12] – 2026-06-26
### Hinzugefügt / Geändert (Astro-Qualität)
- **Stern-basierte Registrierung:** Bei „Translation + Feldrotation" werden jetzt echte
  **Sternzentren** erkannt und gematcht (RANSAC-Affine), statt allgemeiner Bildmerkmale (ORB bleibt
  Fallback) — genauere Ausrichtung.
- **Stern-Entsättigung in HOO:** kleine, kontrastreiche Punkte (Sterne = Kontinuum) werden neutral
  gezogen → kein rot/teal-Farbsaum mehr (Bayer-R/B-Versatz + chromatische Aberration); **ausgedehnte
  Nebel behalten ihre Farbe** (lokale-Kontrast-Maske, nicht nur Helligkeit).
- Zusammen mit der sauberen Hα/OIII-Trennung: rote Nebel, neutraler Hintergrund, neutrale Sterne.

## [1.16.11] – 2026-06-26
### Geändert (Dual-Band: sauberere Linien-Trennung)
- **HOO trennt Hα und OIII jetzt sauber in zwei Signale:** Hα aus dem **Rot**-Kanal, OIII aus dem
  **Blau**-Kanal (statt `max(G,B)` — Grün ist beim OSC am stärksten Hα-kontaminiert). Zusätzlich
  Hintergrund pro Kanal abziehen + **leichte lineare Entmischung** (Hα −= k·OIII, OIII −= k·Hα)
  gegen Restkreuztalk. Ergebnis: reineres Rot/Teal, neutraler Hintergrund — klar zwei Töne.

## [1.16.10] – 2026-06-26
### Hinzugefügt (Dual-Band-Farbe — HOO)
- **Dual-Band wird jetzt als HOO verarbeitet:** Bei Dual-Band/Schmalband (Ha+OIII) werden die
  Linien **getrennt** — Hα (rot, Rot-Kanal) und OIII (teal, Grün+Blau) — **einzeln normalisiert**
  (damit das oft schwächere OIII sichtbar wird) und neu kombiniert (Rot=Hα, Grün+Blau=OIII). Ergebnis:
  rote Hα-Nebel **und** tealfarbene OIII-Bereiche statt rot-dominiert; Sterne bekommen natürliche
  (teal/weiß) Farben, Hintergrund neutral. Greift automatisch im Dual-Band-Modus (Schalter oder
  Header-Erkennung). +1 Test (52).
### Hinweis
- Hα-dominierte Ziele (z. B. IC 5146 Kokon) bleiben überwiegend rot — das ist astrophysikalisch
  korrekt (wenig OIII). Teal wird bei OIII-reichen Zielen (Cirrus, planetarische Nebel) deutlich.
- Sternform: rotate-Ausrichtung macht Sterne rund; ein Restversatz bleibt registrierungsbedingt
  (eine stern-basierte Registrierung als künftiger Schritt würde sie weiter schärfen).

## [1.16.9] – 2026-06-26
### Hinzugefügt
- **Masken-Pinsel im Editor (Helligkeit/Klarheit lokal):** Zusätzlich zur Auto-Maske lässt sich
  die Anpassung jetzt **von Hand malen** — **+ Aufnehmen** (wirkt dort) bzw. **− Schützen** (nimmt
  es dort weg), weicher Rand, einstellbare Pinselgröße, „Maske löschen". Start ist die Auto-Maske
  (falls aktiv), sonst leer. Funktioniert für **Astro & Makro**. **Tastensteuerung:** B Pinsel
  ein/aus · A/S Aufnehmen/Schützen · [ ] Pinselgröße · Backspace Maske löschen. +1 Test (51).

## [1.16.8] – 2026-06-26
### Geändert (Aufräumen — Projektstruktur)
- **Engine-Module nach `core/` verschoben:** Der Projekt-Root enthält jetzt nur noch die
  Start-Datei `focus_stack_gui.py` (+ `ui/`, `core/`, `assets/`, `docs/`, `lang/`, `tests/`) statt
  13 lose `.py`-Dateien — übersichtlicher, weniger erschlagend. Kein Verhaltenswechsel: Engine
  (astro/stacker/focus_*/longexp/mosaic/parallel/siril/tools/constants/i18n) liegt in `core/`,
  per Pfad eingebunden (`--paths core` im Build, hidden-imports unverändert). i18n findet `lang/`
  weiterhin (Quelle + Bundle), `SCRIPT` zeigt auf `core/`. 50 Tests grün, App + Pipeline + i18n
  in Source-Mode verifiziert.

## [1.16.7] – 2026-06-26
### Hinzugefügt
- **Auto-Maske im Editor (lokale Helligkeit, ohne Malen):** Neue Option „🎯 Auto-Maske: nur Motiv
  aufhellen" — Belichtung/Klarheit/Tonwerte wirken nur auf die **mittleren Helligkeiten** (Nebel/
  Motiv), während **heller Kern/Sterne und dunkler Hintergrund geschützt** bleiben (weiche
  Luminanz-Maske). Funktioniert für **Astro UND Makro**, ein Klick — ideal für Anfänger. +1 Test (50).
- **Dual-Band-Filter wird auch automatisch erkannt:** Steht der Filtername im FITS-Header
  (Dual/Duo/Extreme/Enhance/OIII/SHO/HOO …), wird die Grün-Entfernung automatisch ausgeschaltet
  (OIII bleibt). Sonst greift der manuelle Schalter. Also: erkannt, WENN in den Metadaten — sonst
  einstellbar.

## [1.16.6] – 2026-06-26
### Behoben/Hinzugefügt (Dual-Band-Korrektheit)
- **Grün-Entfernung nicht mehr erzwungen — neue Option „Dual-Band/Schmalband-Filter (Ha+OIII)":**
  Mit Dual-Band-Filter ist Grün echtes **OIII-Signal** (landet beim OSC-Sensor teils im Grün-Kanal);
  die automatische SCNR-Grün-Entfernung hätte es zerstört (→ „nur rot"). Ist der Schalter an, wird
  KEINE Grün-Entfernung gemacht, OIII (Teal) bleibt erhalten. Ohne Filter/Breitband bleibt SCNR aktiv
  (entfernt Grünstich + grüne Hotpixel). CLI: `--dualband`. Persistiert, +i18n.
  Hinweis: Für ernsthafte Dual-Band-/Narrowband-Bearbeitung (HOO/SHO-Palette) ist der **lineare
  32-bit/FITS-Export → PixInsight/Siril/GraXpert** der richtige Weg — der bleibt unangetastet.

## [1.16.5] – 2026-06-26
### Behoben (Astro-Farbe)
- **Grünstich entfernt (SCNR):** Astro-Vorschau begrenzt Grün auf den Schnitt von Rot/Blau — in
  Deep-Sky ist Grün praktisch nie echtes Signal (kommt von OSC-Bayer/Lichtverschmutzung). Entfernt
  zugleich grüne Hot-Pixel-/Stern-Sprenkel. Subtraktiv/treu, läuft VOR dem Strecken. +1 Test (49).
  (Reste wie schwache Amp-Glow-/Satelliten-Spur brauchen Dark-Frames — Kalibrierung.)

## [1.16.4] – 2026-06-26
### Behoben (Astro-Qualität — beim Verifikations-Lauf gefunden)
- **Standard-Ausrichtung war `shift` (nur Translation):** Bei realen Datensätzen mit Feldrotation
  führte das zu **länglichen, farbig getrennten Sternen** und einem flachen Bild (am IC 5146 / ASI294
  nachgewiesen). Standard ist jetzt **`rotate` (Translation + Feldrotation)** — korrigiert auch
  gedrehte Felder, funktioniert ebenso bei reiner Nachführung. Sterne werden rund.
- **Hot-/Cold-Pixel-Korrektur standardmäßig an:** entfernt die farbigen Einzelpixel-Punkte
  (Bayer-/Sensor-Hotpixel), die vorher als Farbsprenkel sichtbar waren.
- Astro-Screenshot = realer IC 5146 (Kokonnebel) mit runden Sternen.

## [1.16.3] – 2026-06-26
### Behoben (CI)
- **tests.yml:** `psdtags` fehlte unter den CI-Abhängigkeiten → der neue Ebenen-TIFF-Regressionstest
  brach in GitHub Actions (lokal grün). psdtags ergänzt; Test überspringt zusätzlich sauber, falls
  psdtags fehlt. CI wieder grün.

## [1.16.2] – 2026-06-26 — Beta-Stabilisierung
### Behoben (beim Verifikations-Lauf gefunden)
- **Photoshop-Ebenen blieben bei EXIF-Übernahme erhalten:** Die eingebaute EXIF-Übernahme schrieb
  TIFFs neu und hätte dabei ein **Ebenen-TIFF flachgemacht** (Photoshop-ImageSourceData verloren).
  Solche Dateien werden jetzt erkannt (Tag 37724) und beim EXIF-Schreiben übersprungen — Ebenen
  bleiben erhalten. Regressionstest ergänzt (48 Tests).
### Geändert (Doku)
- **README EXIF-Bullet präzisiert** (DE/EN): „EXIF/Provenienz wird übernommen, wo möglich — JPEG mit
  EXIF, TIFF mit Kern-Provenienz, vollständige TIFF-Metadaten optional via exiftool" statt pauschal
  „EXIF bleibt erhalten".
### Verifiziert (echte Daten, lokal auf macOS)
- Makro-Stack (JPG-Serie) + Ghost-Map · Export JPG/16-bit-TIFF/Photoshop-Ebenen-TIFF + EXIF-Übernahme
  · Seestar-FITS M 42 (GRBG, Feldrotation, Farbe) · ASI294MC-FITS IC 5146 (RGGB-Auto-Erkennung,
  Translation, Farbe) · Sony-ARW-Entwicklung (16-bit + EXIF) · Streamed-Ghost-Map. KI-Pfad end-to-end
  über Spark (Qwen3.6-27B). Offen: native Win/macOS-Starttests (nur CI-Build); Stern-Farbfransen bei
  OSC = Feinschliff.

## [1.16.1] – 2026-06-26
### Hinzugefügt (Astro-Aufbereitung: einstellbar + KI)
- **Drei Astro-Regler für das Vorschau-Bild — Auto (KI) oder manuell:** **Aufhellung** (5–30),
  **Sättigung** (1.0–1.6) und **Farbkalibrierung** (0–1). Standard = „Aufbereitung automatisch
  (KI / Standard)": die KI erkennt jetzt auch den **Farbstich** und schlägt die Farbkalibrierung
  vor (zusätzlich zu Aufhellung/Sättigung). Haken entfernen → alles selbst einstellen
  (GUI-Regler bzw. CLI `--astro-bright/--astro-saturation/--astro-color`). Werte werden gemerkt.
- `astro.color_balance(strength)` ist jetzt **blendbar** (0 = aus … 1 = voll). Wirkt nur aufs
  Vorschau-JPG; lineare Exports bleiben faithful.
- +1 Test (47). Ordner-Hinweis: Build-Artefakte sind bereits per `.gitignore` ausgeschlossen.

## [1.16.0] – 2026-06-26
### Hinzugefügt / Geändert (Astro-Farbe & -Qualität)
- **Debayering von OSC-FITS:** Farbkameras (Seestar, ZWO ASI …) liefern Bayer-Rohdaten als 2D-FITS
  — die wurden bisher als Graustufen gelesen (graues Ergebnis). Jetzt wird debayert → **echte Farbe**.
- **Bayer-Muster-Auto-Erkennung:** `BAYERPAT` wird aus dem Header gelesen; fehlt er, wird das Muster
  **selbst erkannt** (probiert alle 4, wählt das mit den geringsten Farb-Artefakten). Verifiziert:
  GRBG (Seestar) und RGGB (ASI294MC) korrekt aus den Rohdaten erkannt.
- **Farbkalibrierung fürs Vorschau-Bild:** Hintergrund pro Kanal neutralisieren + Sterne neutral
  abgleichen → gegen den Rotstich von OSC/LP-Filter, echte Nebelfarben (blaue Reflexion, rotes Ha).
  Die linearen Exports (16/32-bit, FITS) bleiben faithful für GraXpert/StarNet/PixInsight.
- **Highlight-/Kern-Schutz beim Strecken:** helle Bereiche werden sanfter gestreckt (Kern bleibt
  strukturiert statt weißem Klecks) + leichter Farb-Boost.
- **KI schlägt Aufhellung fürs fertige Astro-Bild vor** (Stärke/Sättigung/Kern-Schutz), mit der
  ausdrücklichen Vorgabe, den Kern NICHT weiter aufzuhellen — nur das schwache Signal.
- +3 Tests (46 gesamt). Echter M 42-Stack (Seestar, Feldrotation, Spark-KI) als 03_astro.png.

## [1.15.1] – 2026-06-26
### Behoben (kritisch)
- **Ergebnis-Anzeige stürzte ab:** Seit der Modularisierung (v1.10.1) fehlte in `ui/result_view.py`
  der Import von `IMG_EXTS` — `_find_result`/`_show_result` warf nach **jedem** Lauf einen
  `NameError`, das Ergebnis wurde nicht angezeigt. Import ergänzt. Neuer Regressionstest deckt
  den kompletten Anzeige-Pfad ab; pyflakes-Scan bestätigt: keine weiteren fehlenden Importe.
### Geändert
- **Echter Astro-Screenshot:** `03_astro.png` zeigt jetzt einen realen ForgePix-Stack von **M 42
  (Orion)** aus 49 Seestar-Subs (Feldrotation + Sigma-Rejection), inkl. KI-Sub-Bewertung.

## [1.15.0] – 2026-06-26
### Hinzugefügt
- **EXIF auch in 16-bit-TIFF — ohne exiftool:** TIFF-Ausgaben bekommen jetzt die Kern-Provenienz
  (Kamera/Modell/Datum als Baseline-Tags + lesbare Zusammenfassung mit Brennweite/Blende/ISO/
  Belichtung in der Bildbeschreibung) eingebaut via `tifffile` — **pixelidentisch** (Lesen/Schreiben
  über tifffile, kein BGR/RGB-Swap). Die vollständige EXIF-Unter-IFD je Einzeltag bleibt der
  exiftool-Kür vorbehalten (wird automatisch bevorzugt, wenn vorhanden).
- **Geister-Karte auch bei großen/gestreamten Stacks:** Neue speicherschonende
  `disagreement_map_streamed()` (lädt EIN Frame nach dem anderen, Online-Varianz nach Welford,
  downscaled + ausgerichtet). Damit gibt es Ghost-Map/KI-Retusche-Hinweis jetzt auch im
  RAM-schonenden Großstack-Pfad (vorher dort nicht verfügbar).
- +2 Tests (42 gesamt).

## [1.14.3] – 2026-06-26
### Hinzugefügt (selbst-enthaltend)
- **EXIF-Übernahme ohne exiftool — mitgeliefert:** Kamera/Objektiv/Brennweite/Blende/ISO/Belichtung
  werden jetzt **eingebaut** auf die **JPEG-Ausgaben** übertragen (via `piexif`; Quelle JPEG/TIFF
  direkt oder RAW über die Kernfelder). Damit braucht der Installer **keine** Zusatz-Installation
  mehr für die EXIF-Übernahme. exiftool wird weiter automatisch **bevorzugt**, wenn vorhanden, und
  bleibt die Kür für vollständige Metadaten auf 16-bit-TIFF.
- `piexif` als Abhängigkeit (requirements + CI + Installer-Bundle). +1 Test (40 gesamt).

## [1.14.2] – 2026-06-26
### Hinzugefügt / Geändert
- **EXIF-Lesen ohne exiftool:** Brennweite/Blende/ISO/Belichtung (für DOF-Rechner, KI-Kontext,
  Modul-Erkennung) werden jetzt **eingebaut** via `ExifRead` (pure-Python, JPEG **und** RAW)
  gelesen — exiftool wird dafür **nicht mehr** gebraucht. exiftool bleibt nur noch für das
  **Übertragen** der vollständigen Metadaten auf die Ausgabedateien nötig (klar so dokumentiert).
  exiftool wird weiter bevorzugt, wenn vorhanden; sonst greift automatisch der Fallback.
- `ExifRead` als Abhängigkeit (requirements + CI + Installer-Bundle). +2 Tests (39 gesamt).
### Repo
- GitHub-Themen (Topics) gesetzt: focus-stacking, astrophotography, computational-photography u. a.
  (Repo-Beschreibung steht bereits korrekt auf „ForgePix (Beta) …").

## [1.14.1] – 2026-06-26
### Geändert (Ehrlichkeit/Claim-Check + Beta)
- **Claim-Check der Doku:** Abhängigkeiten klar markiert — **EXIF-Übernahme/„Aus Foto lesen"
  brauchen `exiftool`** (sonst übersprungen), **FITS** braucht `astropy` (optional, im Installer
  enthalten). Photoshop-Ebenen-TIFF und FITS wurden real verifiziert (geschrieben + zurückgelesen).
  GraXpert/StarNet++/Siril bleiben klar als optional + Auto-Erkennung + Datei-Fallback beschrieben.
- **Datenschutz-Hinweis** zur KI jetzt einheitlich: in **Setup** (schon da), **README** und **beiden
  Guides** — es gehen nur Vorschau-Frames, Schärfeprofil, EXIF-Eckdaten, optional Fokus-/Geister-Karte
  und der Wunsch an die KI; **keine** Originaldateien, **keine** Standortdaten. Lokaler Server = nichts
  verlässt den Rechner.
- **Beta-Kennzeichnung:** README-Lead + „Beta" im „Über"-Dialog. Positionierung: „automatisches
  Fokus-Stacking und Computational Photography für Makro, Astro und Langzeitserien — lokal nutzbar,
  KI optional".

## [1.14.0] – 2026-06-26
### Hinzugefügt (KI-Hinweise, optional)
- **Geister-Karte an die KI:** Nach dem Stacken bekommt die Post-Stack-KI (Feinschliff) optional
  die **Geister-Karte** mit und nennt konkrete **Retusche-Stellen** („wo ist Ghosting?"). Die
  Karte wird dafür intern erzeugt, auch ohne `--ghost-map`. Erscheint als „KI-Retusche-Hinweis"
  im Log; ohne KI-Server passiert nichts.
- **Astro-Sub-Auswahl in Klartext:** Bei Astro fasst die KI (falls Server da) in 1–3 Sätzen
  zusammen, **welche Subs warum** rausfliegen (Wolken/Guiding/FWHM/Spuren) — rein textbasiert,
  datensparsam. Neue reine Funktion `astro_quality.subs_summary_text()`.
- +2 Tests (37 gesamt).

## [1.13.0] – 2026-06-26
### Hinzugefügt (KI-Kontext + Transparenz)
- **Reicherer KI-Vorschlag:** Der KI-Settings-Vorschlag bekommt jetzt zusätzlich **EXIF-Eckdaten**
  (Brennweite/Blende/Belichtung/ISO/Objektiv) und – bei Makro – die **Fokus-Herkunfts-Karte als
  Bild** mit. So kann die KI Fokus-Lücken erkennen und „mehr Aufnahmen nötig?" beurteilen.
- **Freitext-Wunsch:** Neues Feld „Wunsch (optional)" im KI-Bereich (z. B. „seidiges Wasser,
  Personen scharf"). Wird beim KI-Vorschlag **wörtlich berücksichtigt** (CLI: `--wish`).
- **Transparenz:** Setup zeigt klar, **was** an die KI geht (einige Vorschau-Frames, Schärfeprofil,
  EXIF-Eckdaten, dein Wunsch) — **keine** Originaldateien, **keine** Standortdaten.
- Erweiterungspunkt `suggest_settings(context=…)` + `build_ai_context()`; +3 Tests (35 gesamt).
### Dokumentation
- **Anfänger- vs. Profi-Vergleichstabelle** (wer kann was, wie, warum, wann sinnvoll) in beiden
  Guides (DE/EN).

## [1.12.0] – 2026-06-26
### Hinzugefügt (einfacher)
- **Null-Klick im Anfänger-Modus:** Ordner aufs Fenster ziehen startet **sofort die Automatik** —
  rein → fertig, ganz ohne Knopf. (Profi-Modus: weiterhin erst Reihen-Analyse.)
- **Modul automatisch erraten:** Beim Ablegen eines Ordners (von der Modul-Auswahl) rät ForgePix
  das passende Modul aus Dateitypen, Dateinamen und einer kurzen EXIF-Stichprobe — FITS/„light/
  dark/flat" → Astro, sehr lange Belichtung bei hoher ISO → Astro, lange Belichtung → Langzeit,
  sonst Makro. Wird vorgewählt + im Log/Status begründet; der Nutzer kann jederzeit umschalten.
  Neue Engine-Funktion `focus_analysis.guess_module()` (+3 Tests, 32 gesamt).

## [1.11.0] – 2026-06-26
### Geändert (Tempo)
- **Mehrkern-Verarbeitung:** RAW-Entwicklung und Schärfe-Analyse laufen jetzt über **alle
  CPU-Kerne** (ThreadPool; rawpy/OpenCV geben den GIL frei). Reihenfolge bleibt exakt erhalten.
  Auf Mehrkern-Maschinen deutlich schneller — bei RAW-Serien am stärksten.
- **Schärfe-Cache:** Analyse-Ergebnisse werden pro Datei (Schlüssel = Pfad + Änderungszeit)
  zwischengespeichert. Erneute Läufe/„Weiter wo du warst" überspringen die Neuberechnung
  (im Test ~19× schneller beim 2. Lauf, identische Ergebnisse).
- **Embedded-JPEG fürs Culling:** Für die reine Schärfe-Analyse wird – wenn groß genug – das
  eingebettete Kamera-JPEG des RAW genutzt statt voll zu entwickeln (sicherer Fallback auf
  volle Entwicklung). Die Stack-Qualität bleibt unberührt (Entwicklung fürs Ergebnis unverändert).
- Neuer geteilter `parallel.py`-Helfer (`pmap`/`cpu_workers`) + 3 Tests (29 gesamt).

## [1.10.1] – 2026-06-26
### Behoben
- **Absturz beim Beenden vermeidbar gemacht:** Der Update-Check lief als `QThread` und konnte beim
  schnellen Beenden kurz nach dem Start einen `qFatal`/Abort auslösen (Thread beim Aufräumen noch
  aktiv). Läuft jetzt als reiner Python-Daemon-Thread → das kann nicht mehr passieren.
### Geändert (interne Modularisierung 2/n — keine Verhaltensänderung)
- **`ui/main_window.py` von ~2340 auf ~1940 Zeilen** verschlankt. Weitere zusammenhängende Teile
  ausgelagert: `ui/settings_io.py` (Einstellungen laden/speichern), `ui/export.py`
  (Schnell-Export + Export-Dialog), `ui/result_view.py` (Ergebnis-/Vorschau-Anzeige, Ansicht-
  Umschalter, Entscheidungs-Panel). Funktion und Oberfläche unverändert (26 Tests grün,
  Rendering offscreen geprüft).

## [1.10.0] – 2026-06-26
### Geändert (interne Modularisierung — keine Verhaltensänderung)
- **`ui/main_window.py` von ~2640 auf ~2340 Zeilen verschlankt.** Zusammenhängende Teile in
  eigene Module ausgelagert: `ui/theme.py` (Qt-Stylesheet), `ui/workers.py`
  (Hintergrund-Threads + Versionsvergleich), `ui/welcome.py` (Startbildschirm & „Über"-Dialog
  als Mixin), `ui/appinfo.py` (geteilte Pfad-/Namens-Konstanten). Erleichtert künftige Arbeit;
  Funktion und Oberfläche unverändert (26 Tests grün, identisches Rendering).

## [1.9.5] – 2026-06-26
### Hinzugefügt
- **Auto-Update-Hinweis:** Beim Start prüft ForgePix einmal leise die GitHub-Releases und zeigt
  auf dem Startbildschirm einen dezenten Hinweis „Neue Version verfügbar → herunterladen", wenn
  eine neuere Version vorliegt. Vollständig **abschaltbar** (Setup → „Beim Start auf Updates
  prüfen"), läuft im Hintergrund-Thread und bleibt bei Offline/Fehler still. Es werden keine
  Daten gesendet (reiner Lese-Aufruf der öffentlichen Releases-API).

## [1.9.4] – 2026-06-25
### Hinzugefügt
- **„Weiter wo du warst"** auf dem Startbildschirm: Ein Chip lädt den zuletzt verwendeten Ordner
  samt Modul mit einem Klick wieder — erscheint nur, wenn der Ordner noch existiert.

## [1.9.3] – 2026-06-25
### Hinzugefügt
- **Klickbare Befunde** im Entscheidungs-Panel: Ein Befund springt per Klick zur passenden
  Ansicht/Werkzeug — „Ghosting" → Geister-Karte, „Halos" → Retusche, „Fokus/Abdeckung" →
  Fokus-Map. Der Link erscheint nur, wenn das Ziel verfügbar ist. Aus Diagnose wird ein Klick
  zur Lösung.

## [1.9.2] – 2026-06-25
### Hinzugefügt
- **Schnell-Export-Chips** im Entscheidungs-Panel: 📷 Instagram · 🌐 Web · 🖨 Druck als
  Ein-Klick direkt neben dem Ergebnis — exportiert das fertige Bild sofort ins gewählte Format
  (ohne Dialog) und öffnet den Ordner. Der ausführliche Export-Dialog (⌘E) bleibt für
  Mehrfach-Ziele/Ebenen/16-bit. Chips sind aktiv, sobald ein Ergebnis vorliegt.

## [1.9.1] – 2026-06-25
### Hinzugefügt
- **„Warum diese Einstellungen?"** im Entscheidungs-Panel: Die Begründung der Automatik/KI
  (Motiv, Vorschlag, Begründung) wird live aus dem Lauf-Log mitgeschnitten und rechts neben dem
  Ergebnis angezeigt — die Software erklärt sichtbar, *warum* sie so entschieden hat.

## [1.9.0] – 2026-06-25
### Hinzugefügt
- **3-Spalten-Layout (Lightroom-Stil):** links Einstellungen · Mitte großes Bild mit
  **Ansicht-Umschalter** (Ergebnis / Fokus-Map / Geister-Karte) + Aktionen + Filmstreifen ·
  rechts **Entscheidungs-Panel** (Stack-Konfidenz-Score, „X von Y verwendet", Befunde,
  nächste Schritte) und Log.
- **Code-Signing-Gerüst:** macOS-Build signiert ad-hoc; echte Developer-ID-Signierung +
  Notarisierung schalten sich automatisch ein, sobald die Apple-Secrets gesetzt sind
  (Anleitung: docs/SIGNING.md).

## [1.8.1] – 2026-06-25
### Behoben (aus Audit)
- **KI-Vorschlag-Knopf** startete im gebündelten Binary eine zweite GUI statt der Pipeline —
  jetzt frozen-sicher (gemeinsamer `_start_pipeline`-Helfer für alle Subprozess-Starts).
- **FITS** war in jedem Installer tot: `astropy` fehlte im Build — jetzt in build.yml + tests.yml.
- **macOS-Dock-Icon** (pyobjc) im Mac-Build ergänzt.
- **Einstellungs-Migration** von „StackForge" → „ForgePix" (alte Nutzer behalten Pfade/Modus/Fenster).
- Tote `SHINESTACKER`-Referenz + verwaiste `StackForge.iconset` entfernt; FITS-Test ergänzt (26 Tests).

## [1.8.0] – 2026-06-25
### Hinzugefügt
- **Fertige Installer für macOS · Windows · Linux** (PyInstaller via GitHub Actions, automatisch ans
  Release gehängt) — kein Python mehr nötig. Download auf der Releases-Seite.
- Gebündeltes Binary dient als GUI **und** (über `--cli`) als Pipeline-Backend.
### Behoben
- cv2-Rekursionsfehler im gebündelten Binary (Pfad-Verschmutzung im frozen-Modus).

## [1.7.0] – 2026-06-25
### Geändert
- **Umbenannt von „StackForge" zu „ForgePix"** — der alte Name war auf GitHub/PyPI mehrfach belegt.
  ForgePix ist auf PyPI und GitHub verifiziert frei. App, Icons, Bundle, Repo, Docs durchgängig umgestellt.
- Ordner aufgeräumt: veraltete Screenshots entfernt, Asset-Dateien umbenannt.

## [1.6.0] – 2026-06-25
### Geändert (foto-zentriertes Layout)
- **Bild groß oben, Log klein unten** — das Ergebnis bekommt die Hauptfläche, der Log ist Nebensache.
- **Echte Statuszeile** statt grünem Strich: Bereit · Ordner geladen · Läuft · Analysiere · Stacke · Fertig
  (farbcodiert, aus dem Live-Log abgeleitet).
- **Größerer Header:** Logo + „ForgePix" + Untertitel „Computational Photography Suite".
- **README:** „Warum ForgePix?"-Bullets geschärft + **Bilderstrecke** (Input → Analyse → Fokus-Map →
  Ergebnis) mit echten Fotos; Screenshots auf das neue Layout aktualisiert.

## [1.5.0] – 2026-06-25
### Geändert (UX-Politur)
- **Startbildschirm:** hochwertigere Karten — große Icons, Titel, Kategorie und Beispiele
  (z. B. „Produkte · Münzen · Insekten · Food“) + Empfehlungs-Pill. **Einstellungen & „Was ist das?“**
  schon am Start (Sprache/Anfänger-Profi/KI).
- **Hauptfenster:** deutlich **größere Bildfläche** (~⅔), leeres Ergebnis als klare Drag-&-Drop-Zone,
  viele Buttons in ein **„🛠 Werkzeuge“-Menü** aufgeräumt (nur Vorher/Nachher · Bearbeiten · Export sichtbar).
- **Editor:** größeres **Histogramm** und größere **Bildfläche**.
- **README** komplett aufpoliert: „Warum ForgePix?“-Sektion + Screenshot-Galerie (6 Ansichten).
- **Schieberegler** gethemt (v1.4.1).

## [1.4.1] – 2026-06-25
### Behoben
- **Schieberegler durchgängig gethemt** (grüner Verlauf + heller Griff statt Qt-Standard-Blau) —
  betraf v. a. den Camera-Raw-Editor („Bearbeiten").
- Letzte lila Canvas-Reste (Vergleichs-/Kurven-Hintergrund) auf Anthrazit umgestellt.

## [1.4.0] – 2026-06-25
### Geändert
- **Startbildschirm neu gestaltet:** Logo + Tagline, aufgeräumte Modul-Karten mit Emoji,
  Kurzbeschreibung und grünem Empfehlungs-Pill (Bildanzahl), zentriert mit fester Maximalbreite.

## [1.3.0] – 2026-06-25
### Hinzugefügt
- **Export-Dialog:** Auswahl der Ziele (Web-JPG/Instagram/WhatsApp/Web/4K/Druck-16-bit-TIFF),
  Ausgabe-Schärfung, JPG-Qualität, **Photoshop-Ebenen-Datei** und 16-bit-TIFF. Sichtbarer
  „📦 Export"-Knopf + ⌘E.
- Erstes öffentliches Release auf GitHub inkl. CI (GitHub Actions) und Tests-Badge.
### Geändert
- Welcome-Screen klarer („Schritt 1: Wähle ein Modul" + 3-Schritt-Ablauf).
- App-Launcher portabel (relatives Projektverzeichnis).

## [1.2.0] – 2026-06-25
### Hinzugefügt
- **Foto-Tastatursteuerung:** Leertaste (Vorher/Nachher), ← → (Bild wechseln), A/S/E/G/F/R,
  ⌘E (Export). **Drag&Drop:** Ordner aufs Fenster → übernehmen + im Profi-Makro Analyse starten.
### Geändert
- **Theme** auf Anthrazit + Chili-Grün (GreenChili-Marke) statt Lila.
- Messwert-Begründungen beim Aussortieren („Schärfewert 41 % vom Serien-Median").

## [1.1.0] – 2026-06-25
### Hinzugefügt
- **Tastenkürzel** (⌘O/⌘↩/⌘1–4/F1 …) + Hilfe-Dialog.
- **Test-Suite** (24 unittest-Tests, `./run_tests.sh`), inkl. i18n-Vollständigkeitstest.
### Behoben
- None-/Leer-Guards (Astro/Langzeit), Timeout-Handling (GraXpert/StarNet/Siril),
  Analyse im Hintergrund-Thread (GUI blockiert nicht mehr).

## [1.0.0] – 2026-06-24
### Hinzugefügt
- Vier Module: **Makro/Fokus-Stacking, Astro, Hybrid, Langzeitbelichtung** mit Start-Auswahl.
- **Fokus-Intelligenz:** Verwackelt-Filter, Reihen-Analyse, Stack-Optimizer, DOF-/Bracketing-
  Assistent mit EXIF-Auslesen, Stack-Konfidenz-Score, Fokus-Map.
- Astro: Kalibrierung, Translation/Feldrotation, Hot-Pixel, Drizzle, Sub-Bewertung, FITS,
  GraXpert/StarNet/Siril per Ein-Klick.
- Camera-Raw-Editor, Retusche, Export-Voreinstellungen, Batch/Watch, DE/EN, optionale KI.
