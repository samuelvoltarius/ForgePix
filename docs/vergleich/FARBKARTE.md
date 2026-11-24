# Farbtreue an der Farbkarte (ΔE 2000) — gemessen

Stand 24.11.2026. Wiederholbar mit `python docs/vergleich/farbkarte_vergleich.py` (Aufruf und
Feldmitten für die Testdatei stehen im Kopf des Skripts).

* **Daten:** Fuji X-T4, `testdata/raw/Fujifilm/X-T4__DSCF0268.RAF` (raw.pixls.us, CC0). Ein
  ColorChecker Classic liegt hochkant im Waldschatten.
* **Sollwerte:** X-Rite ColorChecker24 „After November 2014“ (D50), aus den Referenzdaten von
  colour-science.
* **Rechnung:**
  * ΔE 2000 ist selbst gerechnet und an den Testpaaren von Sharma et al. (2005) sowie an
    colour-science geprüft (Abweichung 0).
  * Die Belichtung wird über Neutral 8 angeglichen.
  * Feld 18 (Cyan) liegt außerhalb von sRGB. Selbst eine perfekte sRGB-Wiedergabe hat dort
    ΔE 3,37.

## Ergebnis

| Wiedergabe | wie aufgenommen | nach Weißabgleich über Grau | mit Farbprofil (eins ausgelassen) |
|---|---|---|---|
| Kamera-JPEG (eingebettet) | 9,7 | 7,9 | — |
| ForgePix „Wie die Kamera“ | 9,7 | 8,0 | — |
| ForgePix neutral | 7,2 | **3,5** | **2,4 (2,7)** |

* **Neutral ist farbtreuer als die Kamera.** Das Kamera-JPEG setzt auf Wirkung (Kontrast,
  Sättigung), nicht auf Messgenauigkeit. „Wie die Kamera“ übernimmt das bewusst.
* **Neu: Farbprofil aus Farbkarte** (wie „Kalibrierung“ in Camera Raw bzw. ColorChecker-Profile
  in Lightroom). Aus einem Foto mit Karte im selben Licht entsteht eine 3×3-Matrix. Im fertigen
  Bild ergibt sie ΔE 2,40 (Rückprobe über den echten Entwicklungsweg).
  * Ehrlich gemessen wird die Matrix je Feld ohne dieses Feld berechnet und daran geprüft:
    ΔE 2,69.
  * Die Karte findet ForgePix selbst, in jeder Drehung. Die Abweichung zu den von Hand gesetzten
    Feldmitten beträgt höchstens 6,8 px.
  * Gegenprobe: Mit verdrehter Zuordnung kommt ΔE 24,9 heraus, die Lage wird also über die
    Farben eindeutig erkannt.
* **Bedienung:**
  * Oberfläche: RAW → Farbprofil → „Aus Farbkarte …“.
  * Kommandozeile: `--farbprofil-erstellen BILD`, dann `--raw-farbprofil BILD.farbprofil.json`.

## Messfalle

Die Feldmitten wurden zuerst von Hand im Kamerabild bestimmt und über SIFT auf jede Entwicklung
übertragen. Ein Bild mit eingezeichneten Messfeldern zeigte, dass alle 24 auf ihren Feldern
liegen. Erst danach galten die Zahlen.

## Offen

* **Nur eine Karte, nur eine Kamera.** Weitere Testdateien mit Farbkarte fehlen.
* **Profil auf andere Lichtsituation:** Ein Profil gilt für das Licht, in dem die Karte fotografiert
  wurde. Wie weit es auf anderes Licht übertragbar ist, ist nicht gemessen.
* **Weitere Karten:** ColorChecker SG und IT8 werden nicht erkannt.
