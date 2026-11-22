# 02 — Werkzeuge: was versteckt war und jetzt im Menü steht

Stand 22.11.2026. Neues Menü **„Astro-Werkzeuge"**; die Rechnung steckt in
`core/werkzeuge.py` (Blink, Superbias, Larson-Sekanina, Streifen, Beschriften) bzw. in der
Pipeline (Lichtkurve, Lucky Imaging).

| Menüpunkt | vorher erreichbar | geprüft |
|---|---|---|
| Daumenkino (Blink) | nur Kommandozeile | 12 echte Seestar-FITS (IC 5146) → GIF mit 12 Bildern |
| Superbias aus Bias-Aufnahmen | nur Kommandozeile — **und dort ohne Wirkung**, siehe 04_FEHLER | Unit-Test (rohe Form, Kopfdaten, nie überschreiben); keine echten Einzel-Bias im Archiv gefunden |
| Kometenstrukturen (Larson-Sekanina) | nur Kommandozeile | echte Aufnahme C/2024 E1 (Seestar) |
| Streifenmuster entfernen (Fourier) | nur Kommandozeile | echte Aufnahme C/2024 E1; meldet Werte außerhalb 0..1, statt still zu begrenzen |
| Objekte und Koordinatengitter einzeichnen | **gar nicht** (nur in Tests) | Umrechnung gegen astropy geprüft (< 0,01 px). Kein echtes gelöstes Bild im Archiv — **an echten Daten ungeprüft** |
| Lichtkurve messen (Photometrie, AAVSO) | nur Kommandozeile | Dialog baut die Schalter; die Messung selbst hat eigene Tests |
| Sonne, Mond, Planeten aus Video (Lucky Imaging) | nur Kommandozeile | startet `--lucky`; kein Video im Test |

## Noch nicht in der Oberfläche

* Filmischer Tonwert und Rec.2020-Arbeitsfarbraum (`develop.filmic_tonemap`,
  `develop.camera_to_working`) — gehören in den Camera-Raw-Editor, nicht ins Astro-Menü.
* Parametrische Masken (`develop.parametric_mask`) — ebenso Editor.
* `--astro-larson`/`--astro-periodisch` als Teil des Astro-Laufs (statt als Einzelwerkzeug).

## Offen

* Beschriften an einem echten gelösten Bild prüfen (erst „Himmelsposition bestimmen", dann
  „Objekte und Koordinatengitter einzeichnen").
* Superbias an echten Einzel-Bias-Aufnahmen messen (ASI294: braucht keine — Dark-Flats statt
  Bias; ASI533 / Seestar?).
