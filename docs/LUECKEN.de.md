# Was ForgePix noch fehlt — gegen N.I.N.A., PixInsight, Siril, GraXpert, SetiAstro, RC-Astro und Fotobearbeitung

Stand 22.11.2026. Ziel laut Alfred: **eine Mischung aus N.I.N.A. (Aufnahme), PixInsight /
Siril / GraXpert / SetiAstro / RC-Astro (Verarbeitung) und Fotobearbeitung für Makro-Stacking,
dazu die Steuerung der ZWO ASIAIR.**

**Wie diese Liste entstanden ist — und was sie nicht ist.** Die ForgePix-Seite ist am Code
geprüft (Funktionen gesucht, Menüs und Kommandozeile durchgesehen). Die Seite der anderen
Programme stammt **aus Kenntnis, nicht aus einer heute abgerufenen Quelle** — ungeprüft. Kein
einziger Bildqualitätsvergleich wurde dafür gerechnet. Ein Haken heißt „es gibt eine
Umsetzung", nicht „so gut wie das Original". Den genauen Prüfstand je Funktion hat
[CAPABILITY_STATUS.md](CAPABILITY_STATUS.md); der Prozess-für-Prozess-Vergleich steht in
[PIXINSIGHT.de.md](PIXINSIGHT.de.md) (dort sind einige Lücken inzwischen überholt, siehe unten).

---

## Kurzfassung

| Bereich | Stand | Größte Lücke |
|---|---|---|
| **Aufnahme (N.I.N.A., ASIAIR)** | **fehlt fast ganz.** ForgePix verarbeitet nur, was andere aufgenommen haben (Beobachtungsordner + Live-Stack). | Keine einzige Gerätesteuerung: Kamera, Montierung, Fokussierer, Filterrad, Nachführung, Ablaufplan. |
| **Verarbeitung (PixInsight, Siril, GraXpert, SetiAstro, RC-Astro)** | **breit vorhanden**, aber vieles nur auf der Kommandozeile und nichts davon gegen die Originale gemessen. | Bedienung (Bild-Arbeitsfläche, Masken für jeden Schritt, nicht-zerstörender Verlauf) und belegte Qualität der KI-Werkzeuge. |
| **Fotobearbeitung / Makro** | Fokus-Stacking stark; Camera-Raw-Editor vorhanden. | Keine Steuerung von Fokusschiene oder Kamera, Editor ohne Ebenen, ohne Verlauf, ohne Farbmanagement. |

---

## A. Aufnahme — der N.I.N.A.-Teil und die ASIAIR

Im Code gibt es **keine** Anbindung an ASCOM, Alpaca, INDI, PHD2, gPhoto2 oder ein Kamera-SDK
(Suche nach diesen Wörtern in `core/` und `ui/`: null Treffer). Vorhanden ist nur die Verwertung
der Ausgabe: FITS-Kopfdaten von ASIAIR, N.I.N.A. und Seestar werden gelesen, ein Ordner kann
beobachtet und live gestapelt werden (`--live`, `core/livestack.py`). Die Fernsteuerung ist als
Idee in [REMOTE_CAPTURE.de.md](REMOTE_CAPTURE.de.md) festgehalten, aber nicht begonnen.

| N.I.N.A. kann (aus Kenntnis) | ForgePix | |
|---|---|---|
| Kameras steuern (ZWO, QHY, ToupTek, DSLR), Kühlung, Gain/Offset | — | ❌ |
| Montierung: GoTo, Parken, Nachführen, **Meridian-Flip** | — | ❌ |
| Fokussierer + **Autofokus** (HFR-Kurve) | — Sternmessung (HFR/FWHM) wäre da (`astro_quality`), aber kein Motor | ❌ |
| Filterrad, Rotator, Flat-Panel, Kuppel, Wetter, Sicherheitsmonitor | — | ❌ |
| Nachführung über PHD2, **Dithern** | — Dithering wird nur nachträglich erkannt (`equipment.py`) | ❌ |
| **Ablaufplan** (Sequenzer): Ziele, Filter, Belichtungen, Bedingungen, Schleifen | — | ❌ |
| Plate-Solve zum Einrichten (Ziel genau ins Bild) | 🟡 Plate-Solve gibt es (`core/astrometry.py`), aber nur nachträglich, mit Hinweis aus dem Header, ohne Blindsuche | 🟡 |
| Bildausschnitt-Planer / Mosaikplaner mit Himmelskarte | — | ❌ |
| Zielplanung: Höhe über Horizont, Mond, Dämmerung | — | ❌ |
| Flat-Assistent (Belichtung automatisch finden) | — | ❌ |
| Polausrichtung | — | ❌ |
| Live-Qualitätsanzeige je Aufnahme (HFR, Sternzahl) | 🟡 Messung vorhanden, aber erst beim Stapeln | 🟡 |
| Live-Stapeln während der Nacht | ✅ `livestack.py`, mit Neustart-Sicherung | ✅ |

### Die ASIAIR — warum das der schwierigste Punkt ist

*Gelesen als „ZWO ASIAIR". Falls „zwo" hier „zwei Geräte" hieß, gilt alles doppelt — dann
kommt noch die gleichzeitige Steuerung mehrerer Rigs dazu.*

Die ASIAIR ist ein geschlossenes Gerät, das von ZWOs eigener App bedient wird. **Ob es eine
offizielle, dauerhaft gültige Schnittstelle für fremde Programme gibt, ist ungeklärt** (offene
Frage, siehe unten). Drei Wege, mit sehr unterschiedlichem Risiko:

| Weg | Was ForgePix dann kann | Haken |
|---|---|---|
| **1. Ausgabe verwerten** (heute schon) | Die ASIAIR nimmt auf, ForgePix beobachtet den Ordner (Netzfreigabe/USB) und stapelt live. | Keine Steuerung — nur Mitlesen. |
| **2. ASIAIR fernsteuern** über ihr Netzwerkprotokoll | Aufnahme starten/stoppen, Status lesen, aus ForgePix heraus. | Ohne offizielle Schnittstelle nur nachgebaut; jede Firmware-Aktualisierung kann es zerbrechen. Muss im eigenen Netz an Alfreds Gerät gemessen werden, bevor es irgendwer benutzt. |
| **3. ASIAIR ersetzen**: ForgePix spricht die ZWO-Geräte direkt (ZWO-Kamera-SDK, EAF-Fokussierer, EFW-Filterrad; Montierung über ASCOM/Alpaca oder INDI) | Volle Kontrolle wie N.I.N.A. — auf einem Laptop oder Mini-PC am Teleskop. | Großes Vorhaben; der Rechner am Rig muss die ganze Nacht laufen. Das ist der Weg, den N.I.N.A. selbst geht. |

Empfehlung: **Weg 1 ausbauen (sofort nützlich), Weg 3 als eigentliches Ziel**, Weg 2 nur nach
einer Messung am echten Gerät. Für die Seestar S30 gilt Ähnliches; sie lässt sich nach
bisheriger Notiz über ASCOM Alpaca ansprechen (in PIXINSIGHT.de.md erwähnt, ungeprüft).

---

## B. Verarbeitung — PixInsight, Siril, GraXpert, SetiAstro, RC-Astro

Die Rechenseite ist der weiteste Teil von ForgePix: Kalibrierung, Ausrichtung mit Rotation,
Sigma-/Winsor-/Linear-Fit-Stapeln, echtes und CFA-Drizzle, Hintergrund per Stützstellen, MTF/
asinh/GHS, Dekonvolution, Wavelet- und TV-Entrauschen, Sterne trennen und wieder einmischen,
PixelMath, Kanäle trennen/kombinieren (HOO/SHO), Plate-Solve, lokaler Gaia-Katalog,
Photometrie mit Lichtkurve, Komet, Rezepte, Projekte mit Verlauf. Dazu die drei Stufen
Messbericht → Regelwerk → Berater, die so keines der anderen Programme hat.

### B1. Schon gebaut, aber in der Oberfläche nicht erreichbar

Am Code geprüft: Für diese Funktionen gibt es eine Umsetzung, aber **keinen Menüpunkt und
keinen Schalter in der Oberfläche** — wer nicht die Kommandozeile benutzt, kommt nicht dran.
Das ist der billigste Gewinn in der ganzen Liste.

| Funktion | wo | erreichbar über |
|---|---|---|
| Blink (Aufnahmen durchblättern) | `klassiker.blink` | nur Kommandozeile |
| Superbias | `klassiker.superbias` | nur Kommandozeile |
| Larson-Sekanina (Kometen) | `klassiker.larson_sekanina` | nur Kommandozeile |
| Periodische Streifen entfernen (Fourier) | `klassiker.periodisch_entfernen` | nur Kommandozeile |
| Objektnamen/Gitter ins Bild (Annotation) | `annotation.annotieren` | **gar nicht** — nur in Tests aufgerufen |
| Photometrie, Lichtkurve, AAVSO-Export | `photometrie.py` | nur Kommandozeile |
| Lucky Imaging (Sonne/Mond/Planeten aus Video) | `lucky.py` | nur Kommandozeile (`--lucky`) |
| Filmischer Tonwert, Arbeitsfarbraum Rec.2020 | `develop.filmic_tonemap`, `develop.camera_to_working` | **gar nicht** |
| Parametrische Masken (nach Helligkeit/Farbton) | `develop.parametric_mask` | **gar nicht** |

Stichprobe, dass „gebaut" hier auch „läuft" heißt: `--blink` über 12 echte Seestar-FITS aus
`D:\astro\IC 5146_sub` lieferte ein Daumenkino mit 12 Bildern (900 × 506), zurückgelesen am
22.11.2026. Die übrigen Zeilen sind nur am Code geprüft.

*Damit sind fünf Punkte aus „Die ehrlichen Lücken" in PIXINSIGHT.de.md überholt: Superbias,
Larson-Sekanina, Fourier, Blink und Annotation gibt es — sie fehlen nur in der Oberfläche.
PixelMath hat inzwischen auch einen Kommandozeilen-Schalter (`--pixelmath`).*

### B2. Was wirklich fehlt

| Was | Vorbild | Warum es zählt |
|---|---|---|
| **Bild-Arbeitsfläche**: mehrere Bilder offen, Bildschirm-Streckung (STF) ohne die Daten zu ändern, Vorschau-Ausschnitte, Pixelwerte unter dem Mauszeiger, Histogramm | PixInsight, Siril | Heute ist ForgePix ein Ablauf „Ordner rein, Bild raus" mit Einzeldialogen. PixInsight-Arbeit heißt: an einem Bild Schritt für Schritt probieren. |
| **Jede Maske auf jeden Schritt** | PixInsight | Masken gibt es (`core/masken.py`), angebunden sind nur einige Astro-Schritte. |
| **Nicht-zerstörender Verlauf / Rückgängig über alle Schritte**, als wiederholbare Verarbeitungskette | PixInsight (History, ProcessIcons), Siril-Skripte | Projekte speichern heute fertige Ergebnisse, nicht die Kette der Schritte. Rezepte decken erst die vier eigenen KI-Werkzeuge ab. |
| **Echtes SPCC ohne Siril** (Gaia-Spektren × Sensor-QE × Filterkurve) | PixInsight, Siril | Heute nur über ein installiertes Siril; die eigene Grundlage (Messung) steht, die Anpassung fehlt. |
| **Himmelsmosaike** (WCS-bewusst, Flussangleich in den Überlappungen) | PixInsight, Siril, SetiAstro (Mosaik-Werkzeug) | `mosaic.py` ist Fotopanorama, nicht Himmelsmosaik. |
| **Plate-Solve ohne Hinweis (Blindsuche)** | Siril, ASTAP, astrometry.net | Ohne RA/DEC im Header geht es heute nicht. |
| **KI-Werkzeuge auf belegtem Niveau** | RC-Astro BlurX/NoiseX/StarX, GraXpert, SetiAstro Cosmic Clarity | Eigene Modelle sind ausdrücklich experimentell; laut eigenen Messungen hält nur der Entrauscher. Fremde Modelle werden schon angesteuert (GraXpert, StarNet, Cosmic Clarity), RC-Astro-Werkzeuge laufen nur in PixInsight und lassen sich nicht einbinden. |
| **Feldabhängige Dekonvolution** (PSF ändert sich übers Bild) | BlurXTerminator | Gekachelte PSF gibt es, eine Prüfung an echten Verzeichnungen fehlt. |
| **LRGB-Kombination** und allgemeines Kanalwerkzeug für Mono-Kameras | PixInsight, Siril | HOO/SHO aus Einzeldateien geht; Luminanz einmischen nicht. |
| **Kleine SetiAstro-Helfer** (aus Kenntnis, ungeprüft): Kontinuum abziehen (Hα minus Rot), Halos um helle Sterne dämpfen, Frequenztrennung, Sternspitzen | SetiAstro Suite | Einzeln klein; das meiste ließe sich mit PixelMath + Masken bauen, sobald B2 „jede Maske auf jeden Schritt" steht. |

---

## C. Fotobearbeitung und Makro-Stacking

Stark: Fokus-Stacking mit fünf Verfahren, Halo-Retusche, Fokus-Map, Konfidenz, Ausschuss
aussortieren, HDR, Langzeit, Panorama, RAW in 16 bit, Camera-Raw-Editor (Tonwerte, Kurve,
HSL, Objektivkorrektur, Drehen/Beschneiden, Pinselmaske), geschichteter TIFF-Export.

| Was fehlt | Vorbild | Anmerkung |
|---|---|---|
| **Fokusschiene steuern** (StackShot, WeMacro, Cognisys) und **Kamera auslösen** | Helicon Remote, Zerene + StackShot | Das Makro-Gegenstück zum N.I.N.A.-Teil. Plan in REMOTE_CAPTURE.de.md (Sony-SDK zuerst, gPhoto2 später), nicht begonnen. |
| **Fokusreihe am Objektiv fahren** (Kamera-Fokusbracketing per SDK) | Helicon Remote | wie oben |
| **Ebenen** im Editor (mehrere Bearbeitungen übereinander, je mit Maske) | Photoshop, Affinity | Der Editor ist ein Dialog mit Reglern; der Retusche-Pinsel hat ein eigenes Rückgängig, der Editor nicht. |
| **Stempel / Reparaturpinsel aus demselben Bild** | Photoshop, Lightroom | Retusche holt heute nur aus einer anderen Aufnahme der Reihe (gut gegen Halos, nicht gegen Staub). |
| **Farbmanagement durchgängig** (Arbeitsfarbraum, ICC-Ausgabe, Bildschirmprofil) | darktable, Lightroom | Bausteine da (B1), Editor arbeitet in sRGB. Für Druck und Produktfotos wichtig. |
| **Bildbibliothek** (Sterne/Bewertung/Stichwörter über viele Reihen) | Lightroom, darktable | Heute gibt es nur Ordner und Projekte. |
| **Staubflecken-Erkennung** über die ganze Reihe | Lightroom (Spot-Visualisierung) | Bei Makro mit kleiner Blende häufig. |

---

## Vorschlag für die Reihenfolge

1. **Versteckte Funktionen in die Oberfläche** (B1). Fast alles ist gebaut und getestet — es
   fehlen Menüpunkte. Größter Gewinn je Aufwand.
2. **ASIAIR-Ausgabe besser verwerten** (Weg 1): Netzordner der ASIAIR beobachten, Qualität jeder
   neuen Aufnahme sofort anzeigen, live stapeln. Schritt zur N.I.N.A.-Ähnlichkeit ohne jedes
   Geräterisiko.
3. **Bild-Arbeitsfläche + Masken für jeden Schritt + Verlauf** (B2) — das, was PixInsight-Arbeit
   ausmacht.
4. **Gerätesteuerung** (Weg 3): erst Kamera (ZWO-SDK) + Fokussierer mit Autofokus, dann
   Montierung über ASCOM/Alpaca, dann Ablaufplan. Parallel für Makro: Fokusschiene.
5. **SPCC nativ, Himmelsmosaik, Blind-Plate-Solve.**
6. **KI-Qualität belegen**: gegen GraXpert/Cosmic Clarity an denselben Daten messen, bevor
   irgendein Gleichwertigkeitsanspruch fällt.

## Offene Fragen

* **ASIAIR-Schnittstelle**: gibt es eine offizielle? Klärt eine Anfrage bei ZWO oder ein
  Mitschnitt im eigenen Netz an Alfreds Gerät. Bis dahin: nur Weg 1 und 3 planen.
* **Eine ASIAIR oder zwei?** Ändert, ob mehrere Rigs gleichzeitig gesteuert werden müssen.
* **Rechner am Teleskop**: Windows-Laptop, Mini-PC oder Raspberry Pi? Entscheidet zwischen
  ASCOM (nur Windows) und INDI/Alpaca.
* **Bildqualität gegen die Originale**: nicht gemessen. Gleiche M27-Daten durch beide Wege,
  Sternform, Rauschen und Hintergrund vergleichen.
