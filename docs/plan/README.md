# ForgePix — Ausbauplan (zum gemeinsamen Weiterschreiben)

Ziel (Alfred, 22.11.2026): **eine Mischung aus N.I.N.A. (Aufnahme), PixInsight / Siril /
GraXpert / SetiAstro / RC-Astro (Verarbeitung) und Fotobearbeitung für Makro-Stacking.**
Läuft auf **Windows, macOS und Linux**. Für die Aufnahme beides: ForgePix als **eigener
N.I.N.A.-Ersatz** und ForgePix als **Fernbedienung für ein vorhandenes N.I.N.A.**, dazu INDI.

Jede Datei hier hat oben einen Stand und unten offene Punkte. Bitte beim Ändern den Stand mit
Datum nachtragen — und nur als „erledigt" markieren, was an echten Daten oder echten Geräten
gelaufen ist (siehe CLAUDE.md: Code ist kein Beweis).

| Datei | Thema |
|---|---|
| [01_AUFNAHME.md](01_AUFNAHME.md) | N.I.N.A.-Ersatz, N.I.N.A.-Fernsteuerung, INDI, Client/Server |
| [02_WERKZEUGE.md](02_WERKZEUGE.md) | versteckte Funktionen, die jetzt im Menü sind, und was noch fehlt |
| [03_EINRICHTUNG.md](03_EINRICHTUNG.md) | Ersteinrichtung, Windows / macOS / Linux |
| [04_FEHLER.md](04_FEHLER.md) | gefundene und behobene Fehler, mit Messung |
| [05_VERARBEITUNG.md](05_VERARBEITUNG.md) | PixInsight / Siril / GraXpert / SetiAstro / RC-Astro / Makro |
| [06_KI.md](06_KI.md) | KI-Funktionen der anderen Programme und was ForgePix davon hat |
| [07_PLATESOLVE.md](07_PLATESOLVE.md) | Plate-Solver: was ForgePix nutzt, was es fertig gibt |
| [08_QUALITAET.md](08_QUALITAET.md) | **Leitlinie: alles gut, nicht nur alles da** — gemessene Qualitätsprüfung, freie Modelle, sonst verlinken |

Die vollständige Lückenliste von heute steht in [../LUECKEN.de.md](../LUECKEN.de.md).

## Stand 24.11.2026

**An echten Daten gemessen und gut**
* **Astro-Stapeln** gegen Siril, an denselben 28 Seestar-Aufnahmen: 29 % weniger Rauschen,
  2 % breitere Sterne. Mit 21 s statt 5 s ist es 4× langsamer, vorher war es 10×
  ([../vergleich/SIRIL.md](../vergleich/SIRIL.md)).
* **Fokus-Stacking:** An der Platinen-Reihe treffen alle Methoden überall den Fokus und
  überzeichnen weniger als focus-stack ([../vergleich/FOKUS.md](../vergleich/FOKUS.md)).
* **RAW:** 19 von 20 Dateien aus 18 Herstellern lassen sich entwickeln. Der Kamera-Look erreicht
  0,989 der Kamera-Helligkeit, die Farbe liegt im Mittel bei ±5 %.
* **Camera-Raw-Editor:** Jeder Regler hat eine gemessene Wirkung. Rauschminderung, Color Grading,
  Vignette, Körnung und Perspektive sind neu.
* **Langzeitbelichtung:** Mittel und Median sind exakt. Aus der Hand hält die neue Ausrichtung
  „Perspektive“ feste Felsen bei 0,6 der Einzelbild-Schärfe statt 0,22
  ([../vergleich/LANGZEIT.md](../vergleich/LANGZEIT.md)).
* **Farbtreue:** Die neutrale Entwicklung erreicht ΔE 3,5 (Kamera-JPEG 7,9). Neu ist das
  Farbprofil aus einer Farbkarte: ΔE 2,4 ([../vergleich/FARBKARTE.md](../vergleich/FARBKARTE.md)).
* **HDR:** So hell wie die Kamera, fünfmal weniger ausgebrannt, doppelt so viel Zeichnung in
  Lichtern und Schatten wie das Einzelbild ([../vergleich/HDR.md](../vergleich/HDR.md)).
* **N.I.N.A.-Fernsteuerung** gegen ein echtes N.I.N.A. 3.2 (Simulator-Kamera).
* **GraXpert** ist echt aufgerufen worden, mit 6 s Laufzeit.

**Gebaut, aber an echten Geräten ungeprüft**
* Aufnahme über ASCOM Alpaca und INDI: Kamera, Filterrad, Fokussierer, Montierung.
* Autofokus, PHD2-Nachführung mit Dithern, Plate-Solve mit Zentrieren, Meridian-Flip.
* Die Werkzeuge ASTAP, StarNet2 und Cosmic Clarity.
* Farbkalibrierung mit echten Gaia-Daten: Das Gaia-Archiv war bei der Messung im Wartungsmodus.
* macOS und Linux sind nur über die Einrichtung vorbereitet, aber nicht auf echten Rechnern gelaufen.

**Noch nicht gemessen oder fehlt**
* **Arbeitsplatz-Werkzeuge gegen PixInsight:** PixInsight ist nicht auf dem Rechner.
* **KI** (Entrauschen, Schärfen, Sterne entfernen): Gegen RC-Astro, GraXpert und Cosmic Clarity
  ist noch nichts gemessen. Das eigene Entrauschen liegt bisher hinter dem klassischen.
* **Astro-Stapeln mit ASI533MC Pro:** Der Vergleich gegen Siril fehlt noch. Die ASI294MC Pro ist
  gemessen: 30 % weniger Rauschen, 4 % breitere Sterne.
* **Aufnahme-Ablauf:** Bedingungen im Plan (Höhe, Dämmerung), Flat-Assistent, Polausrichtung,
  Rotator, Kuppel und Flat-Panel fehlen.
* **Camera Raw:** Reparatur-Pinsel, KI-Masken, automatisches Upright und Verlaufsfilter im Editor
  fehlen.

**Dauerauftrag** (Alfred, 24.11.2026): Das Ziel steht oben. Jeder Lauf arbeitet die Liste hier
ohne Rückfrage ab, misst an echten Daten, speichert und lädt Schritt für Schritt hoch und
schreibt den Stand hier nach. Ein „mach weiter“ genügt, um den nächsten Lauf zu starten.

**Nächste Schritte**, in dieser Reihenfolge:
1. Sternschonende Hotpixel-Erkennung auf den Rohdaten, danach den Debayer MHC erneut messen.
   Er hat Siril-Schärfe, erzeugt ohne Darks aber Artefaktpunkte
   ([../vergleich/SIRIL.md](../vergleich/SIRIL.md)).
2. Die ASI533MC-Pro-Serie gegen Siril messen.
3. Geschwindigkeit beim Ausrichten (ForgePix 72 s gegen Siril 36 s an der ASI294-Serie).
4. HDR-Geister messen.
5. KI-Werkzeuge gegen GraXpert am selben Stapel messen.
