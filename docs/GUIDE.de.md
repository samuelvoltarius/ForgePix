# StackForge — Anleitung

StackForge verwandelt eine **Serie von Fotos** in **ein besseres Bild**: durchgehend scharf
(Makro), rauscharm (Astro), zusammengesetzt (Mosaik) oder mit Langzeit-Look (ohne ND-Filter).
Die Automatik trifft sinnvolle Entscheidungen und **erklärt sie**. KI ist optional — ohne
Server läuft alles über eine eingebaute Heuristik.

> Schnellstart: Programm öffnen → **Modul wählen** → Ordner mit den Fotos angeben → **Automatik**.

---

## Inhalt
1. [Installation](#installation)
2. [Die vier Module](#die-vier-module)
3. [Anfänger- vs. Profi-Modus](#anfänger-vs-profi-modus)
4. [Bearbeiten, Vorschau & Export](#bearbeiten-vorschau--export)
5. [Externe Tools (GraXpert, StarNet++, Siril)](#externe-tools)
6. [KI / Automatik](#ki--automatik)
7. [Kommandozeile (CLI)](#kommandozeile-cli)
8. [Häufige Fragen & Problemlösung](#häufige-fragen--problemlösung)

---

## Installation

```bash
python3 -m pip install -r requirements.txt
python3 focus_stack_gui.py        # oder StackForge.app (macOS) doppelklicken
```

Benötigt Python 3.9+. RAW-Unterstützung über `rawpy`, FITS über `astropy` (optional).
Externe Tools (GraXpert/StarNet++/Siril) sind **nicht** nötig — nur falls du sie nutzen willst.

---

## Die vier Module

Beim Start wählst du ein Modul. Über **„◀ Module"** oben links kommst du jederzeit zurück.

### 🔬 Makro / Fokus-Stacking
Mehrere Nahaufnahmen, bei denen der Fokus **von vorne nach hinten** wandert, werden zu
**einem durchgehend scharfen Bild** verschmolzen. Ideal für Produkte, Münzen, Insekten, Food.

- **Empfohlene Bildanzahl:** 10–40 (so viele, bis alles von vorn bis hinten scharf abgedeckt ist).
- **Aufnahme:** Stativ, gleiche Belichtung, Fokus in kleinen Schritten verschieben.
- **Vorlagen:** Produkte / Münzen / Food setzen sinnvolle Startwerte.
- **Ergebnis:** scharfes 16-bit-Bild + optional Photoshop-Ebenen-TIFF zum Nachpinseln.

**🔍 Fokus-Werkzeuge** (Profi-Modus, Schritt „Auswahl"):
- **Verwackelte/unscharfe automatisch aussortieren** — wirft Fotos raus, die *nirgends* scharf
  sind (Verwackler/Fehlfokus), mit Begründung im Log. In der Automatik standardmäßig an.
- **🔍 Reihe analysieren** — untersucht die Fokusreihe *bevor* du stackst: welche Bilder
  verwackelt sind, welche redundant sind (kein neuer Schärfe-Beitrag), welcher Bildbereich den
  Fokus trägt und — als **Stack-Optimizer** — wie viel Schärfen-Abdeckung bei weniger Bildern
  bleibt (z. B. 40 Bilder → 99 %, 30 → 98 %, 20 → 95 %). So entscheidest du, wie viele Bilder
  wirklich nötig sind.
- **📐 DOF-Rechner / Shooting-Assistent** — Sensor, Brennweite, Blende und Abbildung (z. B. 1:1)
  oder Distanz eingeben → Schärfentiefe je Bild, empfohlene **Schrittweite** und **benötigte
  Bildanzahl** für die gewünschte Motivtiefe. Perfekt z. B. für A7V + 105 mm Makro.
- **Stack-Qualität** — nach jedem Stack wird automatisch ein Score (0–100) mit Befunden
  (Schärfe, Halos, Ghosting) ins Log geschrieben.

### 🌌 Astro
Viele Aufnahmen desselben Himmelsausschnitts werden ausgerichtet und **gemittelt**, um
**Rauschen zu senken**. Schlechte Aufnahmen werden automatisch aussortiert (mit Begründung).

- **Empfohlene Bildanzahl:** 20–100+ Lights (mehr = weniger Rauschen).
- **Kalibrierung (optional):** Darks 15–30, Flats 15–30, Bias 30+ (als Ordner oder Datei).
- **Ausrichtung:** *Translation* (nachgeführte Montierung) oder *Translation + Feldrotation*
  (Alt-Az-Montierung ohne Rotator).
- **Extras:** Hot-/Cold-Pixel-Korrektur, Drizzle 2× (feineres Sampling),
  Hintergrund-/Gradienten-Entfernung, Sub-Aussortierung (FWHM/Sternzahl/Guiding/Wolken/Spuren).
- **Ergebnis:** lineares 16-bit-TIFF + 32-bit-Linear + optional FITS — fertig für GraXpert/StarNet/PixInsight.

### 🌗 Hybrid
Zwei Spezialfälle in einem Modul (Untermodus oben in der Gruppe wählbar):

- **Mosaik (Mond/Sonne):** überlappende Kacheln zu einem großen Bild zusammensetzen.
  *Empfohlen:* 4–20+ Kacheln, ~30 % Überlappung.
- **Fokus + Astro:** je Fokus-Position mehrere Aufnahmen erst **entrauschen** (Astro-Stack),
  dann **fokus-stacken** (Schärfentiefe). Lege je Position einen **Unterordner** an.
  *Empfohlen:* 5–15 Aufnahmen pro Position, mehrere Positionen.

### 📷 Langzeitbelichtung
Aus einer Serie eine Langzeitbelichtung **ohne ND-Filter**. Vier Effekte:

| Effekt | Wirkung | Empfohlen |
|---|---|---|
| **Glatt** (Mitteln) | seidiges Wasser, weiche Wolken | 10–30 |
| **Lichtspuren** (Aufhellen) | Autolichter, Startrails, Feuerwerk | 30–300+ (lückenlos) |
| **Störer entfernen** (Median) | Passanten/Autos verschwinden | 8–20 |
| **Aufhellen** (additiv) | dunkle Nachtszene heller | 10–60 |

- **Virtuelle Belichtungszeit:** Schieberegler 0–100 % — stufenlos zwischen scharfem Einzelbild
  (eingefroren) und voller Glättung/Spuren. Wie eine kürzere/längere Verschlusszeit.
- **Effekt vorschlagen:** analysiert die Bewegung in der Serie und wählt den passenden Effekt.
- **Aufnahme:** Stativ, gleiche Belichtung. Bei Verwacklung „Ausrichten" auf Versatz/Freihand.

---

## Anfänger- vs. Profi-Modus

Oben rechts umschaltbar.

- **🌱 Anfänger:** nur Ordner wählen + **ein großer Automatik-Knopf**. Die Software wählt die
  Einstellungen und erklärt im Log, **warum**.
- **🛠️ Profi:** voller Schritt-für-Schritt-Wizard, alle Parameter manuell, KI abschaltbar.

---

## Bearbeiten, Vorschau & Export

Nach jedem Lauf rechts in der Ergebnis-Leiste:

- **Vorschau** + **Vorher/Nachher-Schieberegler** (alle Module).
- **🎚️ Bearbeiten** — eingebauter Camera-Raw-Editor: Belichtung/Kontrast/Weißabgleich,
  Tonwertkurve, HSL pro Farbe, Klarheit, Zuschneiden/Drehen, Histogramm. (alle Module)
- **✏️ Retusche** — Pinsel: scharfe Stellen aus Einzelfotos übers Ergebnis malen
  (nur Fokus-Stacking: Makro + Hybrid Fokus+Astro).
- **👻 Geister-Karte** — zeigt Bewegungsartefakte beim Fokus-Stacking.
- **Export-Voreinstellungen:** Instagram / WhatsApp / Web / 4K / Druck.
- **Batch:** je Unterordner ein eigener Stack. **Watch-Ordner:** automatisch stacken, sobald
  neue Fotos fertig kopiert sind. (Makro, Astro, Langzeit)

EXIF (Kamera/Objektiv/Datum) wird auf alle Ausgaben übernommen.

---

## Externe Tools

**Setup-Menü (⚙) → „Externe Tools (optional)"** — hier kannst du die Pfade zu **GraXpert**,
**StarNet++** und **Siril** eintragen (oder leer lassen = automatisch suchen). Die Pfade werden
gemerkt.

- **🌌 GraXpert** (Ergebnis-Leiste, bei Himmels-Modulen): Hintergrund/Gradient entfernen.
  Gefunden → Ein-Klick + automatischer Reimport; sonst Datei im Dateimanager zeigen.
- **⭐ StarNet++**: Sterne entfernen (starless). Braucht 16-bit-TIF — StackForge übergibt
  automatisch die richtige Datei.
- **Siril**: im Astro-Bereich als alternative Engine wählbar.

Nichts davon ist Pflicht — StackForge ist eigenständig.

---

## KI / Automatik

- Die Automatik läuft **komplett ohne KI** über eine Heuristik (kein Server, kein Download).
- Optional ein **OpenAI-kompatibler Server** (llama.cpp / LM Studio / vLLM) **oder ein Anbieter
  mit API-Schlüssel** (OpenAI / OpenRouter) — im Setup-Menü.
- Die KI **berät und prüft** nur (Einstellungs-Vorschläge, Qualitätskontrolle). Sie **verändert
  nie Pixel** und erfindet nichts (treu/nicht-generativ).
- *Hinweis:* Ein ChatGPT-Abo ist **kein** API-Schlüssel — dafür braucht es einen separaten
  (kostenpflichtigen) API-Key.

---

## Kommandozeile (CLI)

Die GUI ruft `focus_cull_stack.py` auf — das geht auch direkt:

```bash
# Makro-Automatik
python3 focus_cull_stack.py --input fotos/ --auto

# Astro mit Feldrotation, Hot-Pixel, Drizzle, FITS
python3 focus_cull_stack.py --input lights/ --astro --astro-align rotate \
    --astro-cosmetic --astro-drizzle 2 --fits-out --dark darks/ --flat flats/

# Langzeitbelichtung, glatt, 60 % virtuelle Belichtung
python3 focus_cull_stack.py --input serie/ --longexp --longexp-mode smooth --longexp-strength 60

# Hybrid Fokus+Astro (je Unterordner eine Position)
python3 focus_cull_stack.py --input positionen/ --hybrid-fa

# Batch über mehrere Serien (je Unterordner ein Stack)
python3 focus_cull_stack.py --input serien/ --batch --astro
```

`python3 focus_cull_stack.py --help` zeigt alle Optionen.

---

## Häufige Fragen & Problemlösung

**Das Ergebnis ist nicht durchgehend scharf (Makro).**
Mehr Aufnahmen mit kleineren Fokus-Schritten machen. Im Profi-Modus „Ausrichtung" auf
Homographie stellen, falls die Kamera leicht gewandert ist.

**Wasser sieht „stufig" aus (Langzeit).**
Mehr Aufnahmen (10–30+). Virtuelle Belichtung auf 100 %.

**Astro-Sterne sind länglich/doppelt.**
Bei Alt-Az-Montierung „Translation + Feldrotation" wählen. Schlechte Subs aussortieren lassen.

**Sehr großer Stack / wenig RAM.**
StackForge streamt automatisch von der Platte; bei Bedarf `--ram-budget-gb` senken.

**RAW-Vorher-Vorschau fehlt im Vergleich (Nicht-Makro).**
Bei manchen RAWs kann die Schnellvorschau nicht gerendert werden — mit JPG/TIFF klappt es immer.

**Englische Oberfläche.**
Setup-Menü → Sprache → „English" (greift beim nächsten Start). Eigene Übersetzung:
`lang/de.json` kopieren, übersetzen, als `lang/xx.json` ablegen.

Siehe auch die [englische Anleitung](GUIDE.en.md).
