# ForgePix — Anleitung

ForgePix verwandelt eine **Serie von Fotos** in **ein besseres Bild**: durchgehend scharf
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
python3 focus_stack_gui.py        # oder ForgePix.app (macOS) doppelklicken
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
- **🔍 Reihe analysieren** (Aufnahmeanalyse) — untersucht die Fokusreihe *bevor* du stackst und
  zeigt z. B.: *„37 Bilder erkannt · Fokusbereich vollständig · Bild 14 verwackelt · Bild 21
  außerhalb der Fokusreihe"*. Pro Bild ein Status (✓ nutzbar / ♻️ redundant / ⚠️ verwackelt /
  ⤳ außerhalb der Reihe). Dazu der **Stack-Optimizer**: wie viel Schärfen-Abdeckung bei weniger
  Bildern bleibt (z. B. 40 → 99 %, 30 → 98 %, 20 → 95 %). So entscheidest du, wie viele Bilder
  wirklich nötig sind. Knopf **🗺️ Fokus-Map** färbt jeden Bereich danach, **aus welchem Foto** die
  schärfsten Details stammen (blau = frühe, rot = späte Aufnahmen) — zeigt Lücken auf einen Blick.
- **📐 DOF-Rechner / Focus-Bracketing-Assistent** — Sensor, Brennweite, Blende und Abbildung
  (z. B. 1:1) oder Distanz → Schärfentiefe je Bild, empfohlene **Schrittweite** und **benötigte
  Bildanzahl**. **📷 Aus Foto lesen (EXIF)** *(eingebaut — kein exiftool nötig)*: ein Foto wählen →
  Brennweite, Blende, Sensor und (falls vorhanden) Fokusdistanz werden automatisch übernommen
  (liest JPEG **und** RAW via `ExifRead`). Perfekt für A7V + 105 mm Makro.
- **Stack-Konfidenz** — nach jedem Stack ein Score (0–100) mit **echten Metriken**:
  Fokusbereich vollständig?, Halos, Ghosting, Schärfe — kein KI-Marketing, sondern Messwerte.

### 🌌 Astro
Viele Aufnahmen desselben Himmelsausschnitts werden ausgerichtet und **gemittelt**, um
**Rauschen zu senken**. Schlechte Aufnahmen werden automatisch aussortiert (mit Begründung).

> **Dual-Band/Schmalband-Filter (Hα+OIII):** Im **Filter**-Feld *Dual-Band* wählen (z. B. SVBony
> SV220, Optolong L-eXtreme) — oder es wird aus dem FITS-Header (`FILTER`) automatisch erkannt.
> Dann werden Hα und OIII **sauber getrennt** und neu kombiniert. Über **Palette** wählbar:
>
> - **HOO** — datentreu: Hα rot, OIII teal. Ehrlichste Wiedergabe.
> - **SHO synthetisch** — Hubble-Look gold + blau; das fehlende **SII wird aus Hα synthetisiert**
>   (kein echtes SII im Dual-Band — bewusst „gefaket").
> - **SHO Foraxx** — dynamisch: reines Hα bleibt **rot**, Hα+OIII-Mischzonen werden **gold**,
>   reines OIII **blau**. Nuancierter als das flache SHO.
> - **Bicolor (Cannistra)** — der fehlende Grün-Kanal wird aus Hα+OIII **errechnet**
>   (G = max(OIII, 0.5·Hα)) → wärmeres, natürlicheres Bild, weniger Magenta, neutralere Sterne.
>
> Ohne Filter/Breitband: aus lassen (normale Farbkalibrierung + Grünstich-Entfernung).

- **Empfohlene Bildanzahl:** 20–100+ Lights (mehr = weniger Rauschen).
- **Kalibrierung (optional):** Darks 15–30, Flats 15–30, Bias 30+ (als Ordner oder Datei).
- **Ausrichtung:** *Translation* (nachgeführte Montierung) oder *Translation + Feldrotation*
  (Alt-Az-Montierung ohne Rotator).
- **Extras:** Hot-/Cold-Pixel-Korrektur, Drizzle 2× (feineres Sampling),
  Hintergrund-/Gradienten-Entfernung, Sub-Aussortierung (FWHM/Sternzahl/Guiding/Wolken/Spuren).
- **Ergebnis:** lineares 16-bit-TIFF + 32-bit-Linear + optional FITS — fertig für GraXpert/StarNet/PixInsight.
- **Schneller & besser (neu):** Registrierung läuft **parallel** über alle Kerne; weit
  weggeditherte Frames werden über eine **Cluster-Brücke zurückgeholt** statt verworfen.
  **Binning** (2×/3×) für mehr SNR + rundere Sterne; **Kalibrierung automatisch erkennen**
  (dark/flat/bias-Unterordner); **mehrere Nächte/Sessions zu einem Stack** zusammenführen
  („➕ Weitere Nacht"); **Palette-Umschalten färbt sofort neu ein** (kein Neu-Stacken);
  **Live-Vorschau** während des Stackens.
- **✨ Veredeln (Ein-Klick):** schickt das fertige Linearbild durch **GraXpert** (Gradienten-Entfernung
  + KI-Entrauschung) und reimportiert es automatisch — der übliche Schritt nach dem Stacken, ohne
  Tool-Wechsel. GraXpert ist kostenlos (graxpert.com); ist es nicht installiert, sagt ForgePix dir,
  wo du es bekommst, und zeigt das fertige Linearbild zum manuellen Öffnen. Pfade unter **Setup →
  Externe Tools** (oder Auto-Erkennung).
- **⭐ Starless-Workflow (mit StarNet++):** der „Profi-Weg", voll automatisch — **Sterne trennen →
  Nebel verstärken (lokaler Kontrast, dezente Sättigung) → Sterne sauber per Screen-Blend zurück**.
  Holt deutlich mehr Nebelstruktur raus, ohne die Sterne aufzublähen. Im **Anfänger-Modus** macht
  „✨ Veredeln" das automatisch (wenn StarNet da ist); im **Profi-Modus** über **Werkzeuge →
  Starless-Workflow**. StarNet++ ist kostenlos (starnetastro.com).
  > **macOS-Hinweis:** StarNet++ ist meist *nicht signiert* — beim ersten Start blockt Gatekeeper.
  > Einmalig im Terminal entsperren: `xattr -dr com.apple.quarantine <StarNet-Ordner>` und
  > `chmod +x <…>/starnet++` (oder Systemeinstellungen → Datenschutz & Sicherheit → „Trotzdem erlauben").

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

## Tastatursteuerung

Die App ist komplett per Tastatur bedienbar — **F1** (oder der ⌨️-Knopf oben) zeigt die volle
Liste. **Foto-Tasten** (wie in Lightroom, greifen nur wenn kein Textfeld aktiv ist):
**Leertaste** Vorher/Nachher · **← →** Bild im Filmstreifen wechseln · **A** Reihe analysieren ·
**S** Stack/Automatik · **E** Editor · **G** Geister-Karte · **F** Fokus-Map · **R** Retusche.
**Befehle:** **⌘O** Ordner, **⌘↩** Automatik, **⌘E** Export, **⎋** Stop/zurück, **⌘1–4** Modul,
**⌘B** Anfänger/Profi, **⌘D** DOF-Rechner, **⌘] / ⌘[** Wizard. *(Windows/Linux: ⌘ = Strg.)*
Tipp: **Ordner aufs Fenster ziehen** übernimmt ihn und startet im Profi-Makro direkt die Analyse.

## Anfänger- vs. Profi-Modus

Oben rechts umschaltbar.

- **🌱 Anfänger:** nur Ordner wählen + **ein großer Automatik-Knopf**. Die Software wählt die
  Einstellungen und erklärt im Log, **warum**.
- **🛠️ Profi:** voller Schritt-für-Schritt-Wizard, alle Parameter manuell, KI abschaltbar.

### Wer kann was — und wann lohnt es sich?

| Thema | 🌱 Anfänger | 🛠️ Profi |
|---|---|---|
| **Bedienung** | Ordner aufs Fenster ziehen → **fertig** (Null-Klick) | Schritt-für-Schritt-Wizard mit allen Reglern |
| **Modul** | wird **automatisch erraten** (umschaltbar) | bewusst gewählt + feinjustiert |
| **Einstellungen** | Software entscheidet (Heuristik), erklärt **warum** | du setzt dip/abs/Transform/Detector/Schärfen/… selbst |
| **Aussortieren** | automatisch (verwackelt/strukturlos raus) | Schwellen selbst justierbar, Frames manuell behalten |
| **Bearbeiten** | Camera-Raw-Editor verfügbar | + Retusche, Ghost-Map, Ebenen-Export, 16-bit |
| **KI (optional)** | aus; Automatik läuft rein lokal | KI-Vorschlag + **Freitext-Wunsch** + Per-Frame-QC |
| **Astro/Hybrid-Feindetails** | sinnvolle Standardwerte | Kalibrierung, Feldrotation, Sigma/Drizzle, Sub-Bewertung |
| **Wann sinnvoll?** | Schnell, viele Serien, „einfach ein gutes Bild" | Schwierige Motive, maximale Kontrolle, Reproduzierbarkeit |

**Faustregel:** Im Zweifel **Anfänger** — die Automatik ist bewusst konservativ und erklärt ihre
Entscheidungen. Zum **Profi** wechseln, sobald du ein konkretes Problem gezielt lösen willst
(z. B. Ghosting wegretuschieren, Astro-Subs nach FWHM filtern, eine Wunsch-Anmutung erzwingen).

---

## Bearbeiten, Vorschau & Export

**Entscheidungs-Panel (rechts):** nach jedem Lauf siehst du den **Stack-Konfidenz-Score**,
„**X von Y** Fotos verwendet", die **Befunde** und — bei der Automatik — **„Warum diese
Einstellungen?"** (Motiv & Begründung). Die Befunde sind **anklickbar** und springen direkt zur
passenden Stelle: *Ghosting* → Geister-Karte, *Halos* → Retusche, *Fokus-Lücken* → Fokus-Map.
Darunter **Schnell-Export-Chips** (📷 Instagram · 🌐 Web · 🖨 Druck) für Ein-Klick-Export.

Nach jedem Lauf rechts in der Ergebnis-Leiste:

- **Vorschau** + **Vorher/Nachher-Schieberegler** (alle Module).
- **🎚️ Bearbeiten** — eingebauter Camera-Raw-Editor: Belichtung/Kontrast/Weißabgleich,
  Tonwertkurve, HSL pro Farbe, Klarheit, Zuschneiden/Drehen, Histogramm. (alle Module)
  - **🎯 Auto-Maske:** ein Klick — die Anpassung wirkt nur aufs Motiv (mittlere Helligkeiten),
    **Sterne und dunkler Hintergrund bleiben geschützt** (ideal für Astro & Makro).
  - **🖌 Maske von Hand:** zusätzlich auf dem Bild malen — **+ Aufnehmen** (Anpassung dort wirken)
    bzw. **− Schützen** (dort wegnehmen), weicher Rand. Tasten: **B** Pinsel ein/aus,
    **A/S** Aufnehmen/Schützen, **[ ]** Pinselgröße, **Backspace** Maske löschen.
- **✏️ Retusche** — Pinsel: scharfe Stellen aus Einzelfotos übers Ergebnis malen
  (nur Fokus-Stacking: Makro + Hybrid Fokus+Astro).
- **👻 Geister-Karte** — zeigt Bewegungsartefakte beim Fokus-Stacking.
- **📦 Export** (oder ⌘E) — Dialog: du wählst **was** exportiert wird — Ziele (Web-JPG /
  Instagram / WhatsApp / Web / 4K / Druck als 16-bit-TIFF), **Ausgabe-Schärfung**, **JPG-Qualität**,
  **Photoshop-Ebenen-Datei** und verlustfreies **16-bit-TIFF**. Für ein einzelnes Format genügt
  ein **Schnell-Export-Chip** im Panel (ohne Dialog).
- **↩ Weiter wo du warst** — auf dem Startbildschirm lädt ein Klick den zuletzt verwendeten Ordner
  samt Modul wieder.
- **Batch:** je Unterordner ein eigener Stack. **Watch-Ordner:** automatisch stacken, sobald
  neue Fotos fertig kopiert sind. (Makro, Astro, Langzeit)

EXIF ist **eingebaut** und wird mitgeliefert — **kein exiftool nötig**: **Lesen** (DOF-Rechner,
KI-Kontext, Modul-Erkennung) via `ExifRead`; **Übernahme auf JPEG** via `piexif` (volle EXIF);
**TIFF** bekommt die Kern-Provenienz (Kamera/Modell/Datum + lesbare Zusammenfassung mit
Brennweite/Blende/ISO/Belichtung) via `tifffile` — pixelidentisch. Nur die **vollständige EXIF-
Unter-IFD** auf TIFF (jedes Einzeltag) ist optional **`exiftool`** vorbehalten; es wird automatisch
bevorzugt, wenn vorhanden.

---

## Externe Tools

**Setup-Menü (⚙) → „Externe Tools (optional)"** — hier kannst du die Pfade zu **GraXpert**,
**StarNet++** und **Siril** eintragen (oder leer lassen = automatisch suchen). Die Pfade werden
gemerkt.

- **🌌 GraXpert** (Ergebnis-Leiste, bei Himmels-Modulen): Hintergrund/Gradient entfernen.
  Gefunden → Ein-Klick + automatischer Reimport; sonst Datei im Dateimanager zeigen.
- **⭐ StarNet++**: Sterne entfernen (starless). Braucht 16-bit-TIF — ForgePix übergibt
  automatisch die richtige Datei.
- **Siril**: im Astro-Bereich als alternative Engine wählbar.

Nichts davon ist Pflicht — ForgePix ist eigenständig.

---

## KI / Automatik

- Die Automatik läuft **komplett ohne KI** über eine Heuristik (kein Server, kein Download).
- Optional ein **OpenAI-kompatibler Server** (llama.cpp / LM Studio / vLLM) **oder ein Anbieter
  mit API-Schlüssel** (OpenAI / OpenRouter) — im Setup-Menü.
- Die KI **berät und prüft** nur (Einstellungs-Vorschläge, Qualitätskontrolle). Sie **verändert
  nie Pixel** und erfindet nichts (treu/nicht-generativ).
- **Datenschutz — was an die KI geht:** nur einige verkleinerte **Vorschau-Frames**, das gemessene
  **Schärfeprofil**, **EXIF-Eckdaten** (Brennweite/Blende/Belichtung/ISO/Objektiv), optional die
  **Fokus-/Geister-Karte** und dein **Freitext-Wunsch**. **Keine** Originaldateien, **keine**
  GPS-/Standortdaten. Bei einem lokalen Server (llama.cpp / LM Studio / vLLM) verlässt **nichts**
  deinen Rechner. Das Setup-Menü zeigt diesen Hinweis ebenfalls.
- *Hinweis:* Ein ChatGPT-Abo ist **kein** API-Schlüssel — dafür braucht es einen separaten
  (kostenpflichtigen) API-Key.

---

## Kommandozeile (CLI)

Die GUI ruft `core/focus_cull_stack.py` auf — das geht auch direkt:

```bash
# Makro-Automatik
python3 core/focus_cull_stack.py --input fotos/ --auto

# Astro mit Feldrotation, Hot-Pixel, Drizzle, FITS
python3 core/focus_cull_stack.py --input lights/ --astro --astro-align rotate \
    --astro-cosmetic --astro-drizzle 2 --fits-out --dark darks/ --flat flats/

# Langzeitbelichtung, glatt, 60 % virtuelle Belichtung
python3 core/focus_cull_stack.py --input serie/ --longexp --longexp-mode smooth --longexp-strength 60

# Hybrid Fokus+Astro (je Unterordner eine Position)
python3 core/focus_cull_stack.py --input positionen/ --hybrid-fa

# Batch über mehrere Serien (je Unterordner ein Stack)
python3 core/focus_cull_stack.py --input serien/ --batch --astro
```

`python3 core/focus_cull_stack.py --help` zeigt alle Optionen.

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
ForgePix streamt automatisch von der Platte; bei Bedarf `--ram-budget-gb` senken.

**RAW-Vorher-Vorschau fehlt im Vergleich (Nicht-Makro).**
Bei manchen RAWs kann die Schnellvorschau nicht gerendert werden — mit JPG/TIFF klappt es immer.

**Englische Oberfläche.**
Setup-Menü → Sprache → „English" (greift beim nächsten Start). Eigene Übersetzung:
`lang/de.json` kopieren, übersetzen, als `lang/xx.json` ablegen.

Siehe auch die [englische Anleitung](GUIDE.en.md).
