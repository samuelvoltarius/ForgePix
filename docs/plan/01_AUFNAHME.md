# 01 — Aufnahme: N.I.N.A.-Ersatz, N.I.N.A.-Fernsteuerung, INDI

Stand 22.11.2026.

## Aufbau: Anschlüsse statt einer festen Lösung

```
            ForgePix-Oberfläche (Windows / macOS / Linux)
                 Menü „Aufnahme → Aufnahme steuern …“
                 │
     ┌───────────┼─────────────────────┬──────────────────────┐
     ▼           ▼                     ▼                      ▼
 ASCOM Alpaca  N.I.N.A.-Brücke       INDI (fehlt noch)     später: ForgePix-
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
| INDI | — | fehlt | — |
| ZWO-Geräte direkt (ASI-SDK, EAF, EFW) ohne ASCOM | — | fehlt | Unter Windows gehen sie heute über ASCOM-Treiber + ASCOM Remote, unter Linux/macOS über INDI (sobald gebaut). |
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
2. **INDI-Anschluss** (Linux/macOS, Raspberry Pi am Rig): getProperties, CCD_EXPOSURE,
   BLOB-Empfang (FITS), Filterrad, Fokussierer, Montierung. Test gegen `indiserver` mit
   `indi_simulator_ccd` auf Linux.
3. **Autofokus**: Fokussierer in Schritten fahren, HFR je Position messen (Sternmessung gibt
   es schon in `astro_quality`), Kurve anpassen, Minimum anfahren.
4. **Plate-Solve zum Einrichten**: Testaufnahme lösen (`astrometry.py`), Montierung syncen,
   Ziel nachschwenken.
5. **Nachführung**: PHD2 über seine JSON-Schnittstelle (Port 4400): starten, Dithern zwischen
   Aufnahmen, Pause beim Flip.
6. **Meridian-Flip**: `TimeToMeridianFlip`/SideOfPier lesen, rechtzeitig anhalten, flippen,
   neu lösen, weiter.
7. **Bedingungen**: Höhe über Horizont, Dämmerung, Mond; Start/Ende danach.
8. **Flat-Assistent**: Belichtung suchen, bis der Median ~40–50 % trifft.
9. **Eigener Aufnahme-Server** (ohne Oberfläche, am Rig), ForgePix als Client.
10. Makro: **Fokusschiene** (StackShot/WeMacro/Cognisys) und Kamera-Auslösung (gPhoto2, Sony-SDK).

## Offene Fragen

* Welcher Rechner steht am Teleskop (Windows-Laptop, Mini-PC, Raspberry Pi)? Entscheidet,
  ob INDI oder ASCOM zuerst kommt.
* Eine ASIAIR oder zwei? Soll ForgePix die ASIAIR ersetzen oder neben ihr laufen?
