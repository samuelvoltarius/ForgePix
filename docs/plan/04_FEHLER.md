# 04 — Gefundene und behobene Fehler

Stand 22.11.2026. Je Fehler: was, wie es sich meldete, wie gemessen, Test.

## `--superbias` hatte keine Wirkung

* **Was:** Das Superbias-Modell wurde erst nach `_load_astro_calibration` gebaut und in eine
  Variable geschrieben, die danach niemand mehr las. Zusätzlich wurden die Bias-Aufnahmen
  debayert gelesen (H×B×3), alle anderen Master roh (H×B).
* **Wie es sich meldete:** gar nicht — das Protokoll schrieb „Superbias: Modell aus 3 Aufnahmen,
  Rauschen … statt …".
* **Gemessen:** 8 echte Seestar-Aufnahmen (IC 5146) + 3 Bias, alter Code mit Superbias gegen ohne:
  größte Abweichung **0,0**. Neuer Code: bis 0,006, mittel 4,6·10⁻⁵.
* **Test:** `tests/test_superbias_wirkung.py` — fällt mit dem alten Code (2 von 3).

## Start-Skripte mit festem Python-Pfad

* Siehe 03_EINRICHTUNG. **Test:** `tests/test_einrichten.py` — fällt mit dem alten `run.sh`.

## Vorschau im Aufnahme-Fenster blieb leer (heute eingebaut, heute gefunden)

* `_bgr_to_pixmap` liefert `(pixmap, scale)`, übergeben wurde das Paar. Gefunden vom
  Oberflächentest `tests/test_aufnahme_ui.py`, bevor es jemand sah.

## Ein Test hing vom Inhalt des Temp-Ordners ab (behoben)

* `test_live_regressions.test_retry_and_stop_export_real_files` legt Lights direkt in einen
  Temp-Ordner. Die Kalibrier-Erkennung sucht auch im ELTERNORDNER — also im ganzen
  Temp-Verzeichnis — und fand dort Bias-Dateien aus einem anderen Lauf (Größenfehler, laut).
  Der Test schaltet die Erkennung jetzt ab (`no_auto_calib`).
* Zum Nachdenken: dieselbe Suche findet in einem Ordner wie `D:\astro\<Objekt>` auch die
  Kalibrierbilder anderer Objekte daneben. Heute meldet sie Größen-/Kopfdaten-Unterschiede
  laut; gleich große fremde Darks würden aber angenommen.

## Kleinkram aus dem Testlauf (behoben)

* `tests/test_windows_gaps.py:197`: `SyntaxWarning: "\P" is an invalid escape sequence` —
  heute harmlos, in einer künftigen Python-Version ein Fehler. Docstring jetzt roh (`r"""`).
* `tests/test_photometrie.py:218`: Datei wurde nicht geschlossen (ResourceWarning).
