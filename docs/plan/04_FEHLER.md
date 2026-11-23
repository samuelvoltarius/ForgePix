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

## Masken veränderten das Bild auch außerhalb der Maske

* **Was:** `masken.anwenden` beschnitt das Ergebnis auf 0..1. Eine Mischung zweier Bilder bleibt
  ohnehin in deren Wertebereich — das Beschneiden traf nur Werte, die schon vorher draußen lagen.
* **Wie es sich meldete:** gar nicht.
* **Gemessen:** echter linearer Stapel (IC 5146, Hintergrund unter null): Entrauschen durch eine
  Sternmaske änderte **100 %** der Pixel außerhalb der Maske, um bis zu 0,019. Danach: 0 %.
* **Betroffen:** in der bisherigen Pipeline folgenlos — sie mischt nur das schon gestreckte
  Bild (0..1); PixelMath nutzt die Funktion nicht. Getroffen hätte es den neuen Arbeitsplatz.
* **Test:** `tests/test_prozesse.py` — fällt mit dem alten Code (2 Fehlschläge).

## GHS im Arbeitsplatz scheiterte (heute eingebaut, heute gefunden)

* Der GHS-Parameter heißt `b` — genau wie das Bild in der Hülle. Gefunden beim Lauf aller
  Werkzeuge am echten Stapel. Jetzt ist der Bildparameter nur positional.

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

## Gaia-Wartung meldete sich als ForgePix-Fehler (23.11.2026, behoben)

* Das ESA-Archiv antwortet in der Wartung mit „200 OK“ und einer HTML-Seite. ForgePix sagte
  „keine gültige Auftragsadresse“. Jetzt: „Das Gaia-Archiv der ESA ist gerade nicht verfügbar“
  — am echten Archiv während der Wartung geprüft.

## ASTAP unter Windows nicht gefunden (23.11.2026, behoben, ungeprüft)

* `_find_solver` suchte ASTAP nur im PATH und im macOS-Programmordner; der Windows-Installer
  trägt sich nicht in den PATH ein (dieselbe Falle wie bei Siril, W5). Jetzt auch
  `%ProgramFiles%\astap\`. ASTAP ist auf dem Testrechner nicht installiert — ungeprüft.

## Ein Test maß Rauschen statt Farbe (23.11.2026)

* Der erste Farbkalibrierungs-Test summierte alle positiven Pixel; das Rauschen zog die
  Kanalverhältnisse Richtung 1 und meldete 12,7 % Fehler. Die Rechnung traf die Faktoren auf
  0,2 %. Der Test misst jetzt nur über Sternpixeln (CLAUDE.md: ist ein Test rot, zuerst den Test).

## Autofokus 99 Schritte daneben (heute gebaut, heute gefunden)

* Die erste HFR-Messung nahm ein festes Fenster um jeden Stern; bei Unschärfe griff es in
  Nachbarsterne, die Kurve war nicht V-förmig (z. B. 18,4 / 26,4 / 17,6 px nebeneinander). Eine
  Parabel darauf landete 99 Schritte neben dem Fokus. Jetzt: nur der Stern selbst, Sterne mit
  berührendem Nachbarn werden nicht gemessen, Hyperbel statt Parabel → saubere V-Kurve
  (6,7 … 1,9 … 4,6 px), Treffer unter 30 Schritten. Test `test_autofokus_phd2`.

## Gerät ohne Namen ließ die Statuszeile abstürzen — und kein Test merkte es

* Alpaca-Treiber müssen keinen Namen melden; `", ".join(...)` mit None warf in einem Qt-Slot. PySide
  druckt solche Ausnahmen nur aus, der Test blieb grün. Jetzt steht der Gerätetyp da, und die
  Oberflächentests sammeln Ausnahmen aus Slots ein und fallen damit (Gegenprobe: mit dem alten
  Fehler fällt der Test).

## GraXpert-Aufruf scheiterte unter pytest (23.11.2026, behoben)

* `graxpert_engine` startete GraXpert mit `capture_output=True`, aber ohne `stdin=`. Unter
  pytest erbt der Aufruf ein stdin ohne gültigen Windows-Handle → `OSError: [WinError 50]`.
  Gefunden durch den neuen echten GraXpert-Test. Jetzt `stdin=subprocess.DEVNULL`.
* `test_prozesshilfe` erwartete für dieselbe Ursache nur WinError 6; je nach vorher gelaufenem
  Test kam 50. Der Test lässt jetzt beide gelten.
* **Verdacht, nicht nachgewiesen:** 15 weitere `subprocess.run(... capture_output=True)` ohne
  `stdin=` in `core/` (Siril, StarNet, Cosmic Clarity, exiftool, …). Im fertigen Windows-Paket
  ohne Konsole legt Python laut seiner Quelle selbst eine Ersatzleitung an — dort vermutlich
  unkritisch. Am echten Paket prüfen, dann einheitlich `stdin=subprocess.DEVNULL` setzen.

## Kleinkram aus dem Testlauf (behoben)

* `tests/test_windows_gaps.py:197`: `SyntaxWarning: "\P" is an invalid escape sequence` —
  heute harmlos, in einer künftigen Python-Version ein Fehler. Docstring jetzt roh (`r"""`).
* `tests/test_photometrie.py:218`: Datei wurde nicht geschlossen (ResourceWarning).
