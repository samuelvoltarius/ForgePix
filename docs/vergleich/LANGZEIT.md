# Langzeitbelichtung aus Einzelbildern — gemessen

Stand 24.11.2026. Wiederholbar mit
`python docs/vergleich/langzeit_vergleich.py <video> <neuer-ordner> [anzahl]`.

Daten: Wasserfall-Video, Wikimedia Commons, CC0 (`testdata/langzeit/`). Gemessen an 90 Bildern
(3 s). Das Video ist **aus der Hand** gefilmt, mit bis zu ~15 px Versatz zwischen den Bildern.
Es ist damit ein echter Freihand-Fall.

## Treue

| Modus | Abweichung vom exakt nachgerechneten Ergebnis | Zeit |
|---|---|---|
| smooth (Mittel) | **0,0** | 9 s |
| declutter (Median) | **0,0** | 82 s |

## Aus der Hand: wie scharf bleiben feste Felsen?

Gemessen wird die Schärfe an zwei festen Felsen, geteilt durch die Schärfe des mittleren
Einzelbilds (1,0 = so scharf wie ein Einzelbild).

| Ausrichtung | Fels oben links | Fels unten rechts | Zeit |
|---|---|---|---|
| keine | 0,26 | 0,24 | 9 s |
| shift (Stern-Ausrichtung, war der Vorschlag) | 0,77 | **0,22** | 21 s |
| feature (ORB, starr) | 0,67 | 0,34 | 143 s |
| feature (SIFT, Perspektive) | **0,90** | 0,28 | 58 s |
| nur ruhige Flächen (Maske) + ECC | 0,30 | 0,20 | 84 s |
| **perspective** (ECC, Homographie, ¼ → ½ Auflösung) | 0,61 | **0,60** | 36 s |
| **Kommandozeile mit Vorschlag** (wählt jetzt perspective) | 0,62 | 0,63 | |

## Was daraus folgt

* **Neue Ausrichtung „Freihand mit Wasser/Wolken — Perspektive“.** Die Automatik wählt sie, sobald
  sie Verwackeln erkennt. Sie ist die einzige, die keine Stelle verwischt lässt.
* **Warum die Merkmals-Ausrichtung schwächelt:** Die Merkmale sitzen fast alle im schäumenden
  Wasser, das sich bewegt.
* **Eine Vermutung war falsch:** Nur auf ruhigen Flächen auszurichten war *schlechter*. Die Maske
  aus der zeitlichen Streuung traf glatten Schnee statt Felsen.
* **Grenze der weltweiten Ausrichtung:** etwa 0,6. Mehr bräuchte eine örtliche Ausrichtung
  (Parallaxe, Rolling Shutter), aber ohne dabei das Wasser „einzufrieren“. Das ist offen.
* **`shift` und Tagesszenen:** `shift` ist die Stern-Ausrichtung. An einer Tagesszene endete sie
  mit „keine Frames zum Stacken“. Jetzt sagt sie, dass Sterne fehlen und `perspective` hilft.
* **Stille Fehler behoben:**
  * Ein unbekannter Modus wurde still zu „smooth“.
  * Die Stärke wurde still auf 0…1 bzw. 0…100 beschnitten.
  * Unlesbare Bilder fielen ohne Meldung heraus.

## Messfalle, die zugeschnappt ist

Die erste Fassung nahm das reine Mittel als „Stativ-Wahrheit“ und verwackelte künstlich. Weil das
Video selbst verwackelt ist, war schon diese Wahrheit verwischt. Die Merkmals-Ausrichtung schien
dadurch „doppelt so scharf wie die Wahrheit“ (1,94). Erst der Blick auf die Ausschnitte zeigte
den Fehler.

## Offen

* Der Vorschlag nennt für einen Wasserfall „declutter“ (Median) mit der Begründung „vorbeilaufende
  Störer“. Die bewegte Fläche wird gemessen, während die Kamera wackelt. Die Moduswahl ist noch
  nicht überprüft.
* Kein Vergleich mit Sequator oder StarStaX: Beide sind nicht auf dem Testrechner.
