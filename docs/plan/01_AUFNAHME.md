# 01 — Aufnahme: N.I.N.A.-Ersatz, N.I.N.A.-Fernsteuerung, INDI

Stand 22.11.2026 (INDI am selben Tag nachgezogen).

## Aufbau: Anschlüsse statt einer festen Lösung

```
            ForgePix-Oberfläche (Windows / macOS / Linux)
                 Menü „Aufnahme → Aufnahme steuern …“
                 │
     ┌───────────┼─────────────────────┬──────────────────────┐
     ▼           ▼                     ▼                      ▼
 ASCOM Alpaca  N.I.N.A.-Brücke       INDI                  später: ForgePix-
 (HTTP)        (Advanced API, HTTP)  (XML über TCP 7624)   Aufnahme-Server
     │           │                     │
 Seestar,      N.I.N.A. am           indiserver am Rig
 ASCOM Remote, Teleskop-Rechner      (Linux / Raspberry Pi,
 Simulatoren   (nur Windows)          Astroberry, StellarMate)
```

Alle drei Wege gehen **übers Netz**. Darum ist es egal, wo ForgePix läuft:

* **Alles auf einem Rechner** (Laptop am Teleskop): Adresse `127.0.0.1`.
* **Client / Server**: Geräte hängen an einem Rechner am Teleskop (Mini-PC, Raspberry Pi, der
  Windows-Rechner mit N.I.N.A.), ForgePix läuft am Schreibtisch und trägt dessen Adresse ein.
  Die Bilder kommen übers Netz in den Zielordner und werden dort live gestapelt.

Was es noch NICHT gibt: einen eigenen ForgePix-Server, der am Rig *ohne Oberfläche* läuft und
die Nacht selbst abarbeitet, während der Client nur zuschaut. Heute muss die Oberfläche
offen bleiben, solange ein Ablaufplan läuft.

## Stand je Anschluss

| Anschluss | Datei | Stand | geprüft wie |
|---|---|---|---|
| ASCOM Alpaca: Suche im Netz, Geräteliste, Kamera, Filterrad, Fokussierer, Montierung | `core/alpaca.py` | gebaut | gegen nachgebautes Gerät nach der Alpaca-Beschreibung (`tests/test_alpaca_aufnahme.py`). **Nicht** gegen ein echtes Gerät oder die OmniSim-Simulatoren — die liefen am 22.11. nicht. |
| Ablaufplan (N × Belichtung × Typ × Filter → FITS mit Kopfdaten) | `core/aufnahme.py` | gebaut | gegen das nachgebaute Gerät, auch über die Knöpfe (`tests/test_aufnahme_ui.py`) |
| N.I.N.A.-Brücke: Version, Geräte, verbinden/trennen, Testaufnahme, Ablaufplan starten/stoppen/Status, gespeicherte Bilder abholen | `core/nina.py` | gebaut | **live** gegen N.I.N.A. 3.2.0.9001 + Advanced API 2.2.15.2 auf Alfreds PC: Version, Geräteliste, Simulatorkamera verbunden, 1-s-Aufnahme als 640×480-Vorschau, getrennt. Rohdaten aus dem Bildverlauf: nur gegen den Nachbau (dafür braucht es einen Ablaufplan in N.I.N.A., der speichert). |
| INDI: Geräteliste mit Typ (DRIVER_INTERFACE oder typisches Merkmal), Kamera mit Bildtyp (Light/Dark/Bias/Flat) und FITS-Bild, Filterrad, Fokussierer, Montierung | `core/indi.py` | gebaut, im Aufnahme-Fenster wählbar | gegen nachgebauten indiserver nach der Protokollbeschreibung 1.7, auch über die Knöpfe (`tests/test_indi.py`, `tests/test_aufnahme_ui.py`). **Nicht** gegen einen echten `indiserver` — kein Linux in dieser Sitzung. |
| ZWO-Geräte direkt (ASI-SDK, EAF, EFW) ohne ASCOM/INDI | — | fehlt | Unter Windows über ASCOM-Treiber + ASCOM Remote, unter Linux/macOS über INDI (`indi_asi_ccd` usw.). |
| ASIAIR | — | offen | keine bekannte offizielle Schnittstelle; Ausgabeordner beobachten geht schon (Live-Stapeln). |

### Gemessene Eigenheiten der N.I.N.A. Advanced API (22.11.2026)

* Grundadresse `http://<rechner>:1888/v2/api/…`, Antwort immer `{Response, Error, StatusCode, Success, Type}`.
* `equipment/<gerät>/rescan` liefert die Treiberliste mit `Id`; verbinden mit `connect?to=<Id>`.
* `equipment/camera/capture` mit `waitForResult=true` belichtet, kommt aber **nicht** in den
  Bildverlauf. `capture?getResult=true&stream=true` liefert ein gestrecktes **PNG** — auch mit
  `raw_fits=true`. Rohdaten nur über `image/<index>?raw_fits=true&stream=true` für Bilder aus
  dem Bildverlauf (ungeprüft gegen echtes N.I.N.A.).
* Ohne verbundene Geräte fehlt in `equipment/info` der Name; ForgePix zeigt dann „nicht verbunden".

## Was ein N.I.N.A.-Ersatz noch braucht (Reihenfolge-Vorschlag)

1. **Live-Test an echten Geräten**: ASCOM OmniSimulator starten, dann Alfreds Kamera über
   ASCOM Remote / Seestar über Alpaca. Erst danach „funktioniert" sagen.
2. **INDI an einem echten indiserver prüfen**: unter Linux die INDI-Simulatoren starten
   (`indi_simulator_ccd`, `indi_simulator_wheel`, `indi_simulator_telescope`,
   `indi_simulator_focus`), dann Alfreds ZWO-Kamera mit `indi_asi_ccd`.
3. [x] **Autofokus** (23.11.2026). Offen: an echtem Fokussierer prüfen; Temperaturnachführung.
4. **Plate-Solve zum Einrichten**: Testaufnahme lösen (`astrometry.py`), Montierung syncen,
   Ziel nachschwenken.
5. [x] **Nachführung mit PHD2**, Dithern (23.11.2026). Offen: an echtem PHD2 prüfen; Pause beim Flip.
6. **Meridian-Flip**: `TimeToMeridianFlip`/SideOfPier lesen, rechtzeitig anhalten, flippen,
   neu lösen, weiter.
7. **Bedingungen**: Höhe über Horizont, Dämmerung, Mond; Start/Ende danach.
8. **Flat-Assistent**: Belichtung suchen, bis der Median ~40–50 % trifft.
9. **Eigener Aufnahme-Server** (ohne Oberfläche, am Rig), ForgePix als Client.
10. Makro: **Fokusschiene** (StackShot/WeMacro/Cognisys) und Kamera-Auslösung (gPhoto2, Sony-SDK).

## Haben wir alle N.I.N.A.-Funktionen? — Nein.

Stand 22.11.2026, aus Kenntnis von N.I.N.A. 3.x (nicht Funktion für Funktion nachgeschlagen):

| N.I.N.A. | ForgePix |
|---|---|
| Kamera: belichten, Gain/Offset, Kühlung, Binning | belichten ✅ (Alpaca, INDI); Gain/Offset/Temperatur nur **lesen**; Kühlung und Binning setzen ❌ |
| Filterrad | ✅ (Alpaca, INDI) |
| Fokussierer fahren, **Autofokus** | ✅ HFR-Kurve mit Hyperbel wie N.I.N.A. (`autofokus.py`), im Fenster; gegen nachgebaute Optik geprüft, HFR an echten Seestar-Aufnahmen gemessen (1,9 px) — **nicht** an einem echten Fokussierer |
| Montierung: GoTo, Nachführen, Parken, Stopp | ✅ im Fenster (Alpaca und INDI), gegen nachgebautes Gerät |
| Rotator, Kuppel, Flat-Panel, Wetter, Sicherheitsmonitor, Schalter | ❌ (über die N.I.N.A.-Brücke nur anzeigen) |
| Ablaufplan (Sequenzer) | einfach ✅: N × Belichtung × Typ × Filter. Bedingungen, Schleifen, Auslöser, Ziele mit Koordinaten ❌ |
| Nachführung (PHD2), Dithern | ✅ PHD2 über seinen Ereignis-Server: Zustand, Führen starten, Dithern alle N Lights im Ablaufplan mit Warten auf „SettleDone“ (`phd2.py`); gegen nachgebauten PHD2-Server — **nicht** gegen echtes PHD2 |
| Meridian-Flip | ❌ |
| Plate-Solve + Zentrieren | Lösen nachträglich ✅ (`astrometry.py`), mit der Montierung zentrieren ❌ |
| Framing-Assistent, Himmelsatlas, Mosaikplaner | ❌ |
| Flat-Assistent, Polausrichtung | ❌ |
| HFR/Sternzahl je Aufnahme während der Nacht | Messung vorhanden (`astro_quality`), Anzeige beim Aufnehmen ❌ |
| Live-Stapeln | ✅ |
| Plugins | ❌ |

ForgePix ist heute ein **Aufnahme-Grundgerüst mit drei Anschlüssen**, kein vollständiger
N.I.N.A.-Ersatz. Die Reihenfolge oben ist der Weg dahin.

## Gibt es Linux-Treiber? — Ja, über INDI.

Unter Linux und macOS ist INDI die Treiberwelt; ForgePix spricht sie jetzt als Client. Die
Treiber selbst kommen aus den INDI-Paketen, nicht von ForgePix (aus Kenntnis, nicht an einem
Linux-Rechner nachgeprüft):

* Ubuntu/Debian: Paket `indi-full` aus dem PPA `mutlaqja/ppa` — enthält u. a. `indi_asi_ccd`,
  `indi_asi_focuser`, `indi_asi_wheel` (ZWO), `indi_eqmod_telescope`, `indi_lx200*`,
  `indi_ioptron*`, `indi_celestron_gps` und die Simulatoren.
* Raspberry Pi am Teleskop: Astroberry oder StellarMate bringen indiserver fertig mit.
* macOS: KStars bringt INDI mit; ForgePix verbindet sich mit dessen indiserver.
* ZWO liefert für Linux/macOS auch ein eigenes Kamera-SDK; ForgePix nutzt es (noch) nicht
  direkt, der Weg geht über `indi_asi_ccd`.
* ASCOM Alpaca geht auch unter Linux: Geräte mit eigenem Alpaca (Seestar) brauchen gar keinen
  Treiber auf dem Rechner.

## Offene Fragen

* Welcher Rechner steht am Teleskop (Windows-Laptop, Mini-PC, Raspberry Pi)? Entscheidet,
  ob INDI oder ASCOM zuerst kommt.
* Eine ASIAIR oder zwei? Soll ForgePix die ASIAIR ersetzen oder neben ihr laufen?
