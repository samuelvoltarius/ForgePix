# Changelog

Alle nennenswerten Änderungen an ForgePix. Format orientiert an
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/).

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
