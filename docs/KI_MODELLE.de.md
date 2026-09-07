# Die eigenen KI-Modelle — was sie an echten Daten tun

*Stand: 07.09.2026. Alle Zahlen hier stammen aus tatsächlich ausgeführten Läufen, nicht aus dem
Trainingsbericht der Modelle.*

ForgePix bringt vier kleine ONNX-Modelle mit (je 1,8 MB, NAFNet-Architektur, einkanalig,
256×256-Kacheln):

| Modell | Aufgabe |
|---|---|
| `forgepix-denoise-mono-v2` | Entrauschen |
| `forgepix-deblur-mono-v2` | Schärfen |
| `forgepix-starless-mono-v2` | Sterne trennen |
| `forgepix-background-mono-v2` | Hintergrundverlauf schätzen |

Alle vier sind im Manifest als **experimentell** geführt (`release_approved: false`). Sie werden
nur mit `allow_experimental=True` geladen und sind in keinem Standardweg eingeschaltet. Dieses
Dokument sagt, was eine Messung an echten Aufnahmen ergibt — damit die Entscheidung, ob sie
freigegeben werden, auf Zahlen steht und nicht auf einem Eindruck.

## Warum diese Messung überhaupt nötig war

Eine frühere Beurteilung des **Schärfe**-Modells war falsch, und der Fehler ist lehrreich: das
Testbild war auf 35 % verkleinert worden. Die Modelle arbeiten auf 256×256-Kacheln und sind auf
Sterne einer bestimmten Breite trainiert; ein verkleinertes Bild schiebt die Sterne aus dem
Arbeitsbereich heraus. Gemessen wurde daraufhin ein Verbreitern, tatsächlich schärft das Modell
bei voller Auflösung. **Ein Modell außerhalb seines Arbeitsbereichs zu messen ergibt eine Zahl,
die nichts bedeutet — und die sich trotzdem wie ein Befund liest.**

Alles hier ist deshalb bei **voller Auflösung** gemessen, an ganzen Stapeln, ohne Skalierung.

## Entrauschen

Zwei verschiedene Motive, beide 1920×1080, linear (vor jeder Streckung). Rauschen ist die
robuste Streuung (MAD × 1,4826) in den dunkelsten 40 % des Bildes. „Sternfluss" ist die
Summe über die hellsten 0,1 % der Pixel — bleibt sie erhalten, erfindet oder frisst das
Modell keine Helligkeit.

**C 31, 4 Aufnahmen à 30 s (verrauschte Ausgangslage), Seestar S30**

| Stärke | Rauschen | Änderung | Sterne gefunden | FWHM | Sternfluss |
|---|---|---|---|---|---|
| — (vorher) | 0,0003160 | | 118 | 2,241 px | |
| 0,3 | 0,0002655 | **−16,0 %** | 114 | 2,312 px | +0,05 % |
| 0,5 | 0,0002348 | **−25,7 %** | 112 | 2,312 px | +0,09 % |
| 1,0 | 0,0001802 | **−43,0 %** | 105 | 2,355 px | +0,17 % |

**IC 434, 40 Aufnahmen à 30 s (tieferer Stapel), Seestar S30**

| Stärke | Rauschen | Änderung | Sterne gefunden | FWHM | Sternfluss |
|---|---|---|---|---|---|
| — (vorher) | 0,0001185 | | 26 | 2,631 px | |
| 0,3 | 0,0001058 | **−10,7 %** | 26 | 2,631 px | +0,16 % |
| 0,5 | 0,0000974 | **−17,7 %** | 26 | 2,631 px | +0,26 % |
| 1,0 | 0,0000805 | **−32,1 %** | 26 | 2,646 px | +0,52 % |

**Was daraus folgt:**

* Das Modell entrauscht wirklich, und zwar deutlich. Es ist kein Weichzeichner mit gutem Namen.
* **Es erfindet keine Helligkeit.** Der Sternfluss ändert sich um weniger als 0,6 %. Das ist der
  wichtigste Punkt: ein Modell, das Struktur halluziniert, würde hier auffallen.
* **Der Preis sind die schwächsten Sterne.** Auf dem verrauschten Bild verschwanden bei voller
  Stärke 13 von 118 gefundenen Sternen (−11 %). Auf dem tiefen Stapel keiner. Das passt
  zusammen: was knapp über dem Rauschen liegt, geht mit dem Rauschen.
* Die Sternbreite wächst um 3 bis 5 % — messbar, aber gering.

**Empfehlung:** 0,3 bis 0,5. Volle Stärke nur, wenn schwache Sterne nicht zählen — und nie vor
einer Photometrie.

## Die drei anderen Modelle — und der Vergleich mit dem klassischen Weg

Gemessen an demselben tiefen IC-434-Stapel (40 Aufnahmen), volle Auflösung.

### Schärfen

| | FWHM | Sterne gefunden | Rauschen | Sternfluss |
|---|---|---|---|---|
| vorher | 2,631 px | 26 | | |
| Modell, Stärke 0,5 | 2,646 px | 26 | +0,9 % | +3,5 % |
| Modell, Stärke 1,0 | 2,544 px | 29 | +3,0 % | +6,9 % |
| klassisch, RL 15 Iterationen | 2,355 px | 39 | +15,2 % | −0,2 % |
| klassisch, RL 30 Iterationen | **2,220 px** | **42** | +25,5 % | −3,3 % |

Das Modell schärft — die frühere gegenteilige Aussage war ein Messfehler und ist damit
widerlegt. Aber es schärft **schwach**: −3,3 % FWHM gegen −15,6 % bei der klassischen
Richardson-Lucy-Dekonvolution, und es findet 29 Sterne statt 42. Richardson-Lucy erkauft das mit
Rauschen (+25,5 %), das Modell ist darin schonender.

Ein Punkt spricht gegen das Modell: **es erhöht den Sternfluss um 6,9 %.** Richardson-Lucy tut
das nicht (−0,2 %). Ein Schärfeverfahren soll Helligkeit umverteilen, nicht vermehren; für
Photometrie ist das Modell damit unbrauchbar.

### Sterne trennen

Gemessen wird der Sternfluss **über dem Himmelsniveau**, der nach der Trennung übrig bleibt.
Weniger ist besser.

| | Sternfluss übrig |
|---|---|
| Modell, Stärke 0,5 | 67,7 % |
| Modell, Stärke 1,0 | 35,3 % |
| klassisch (`remove_stars`) | **4,8 %** |

Der klassische Weg ist hier **siebenmal gründlicher**. Das Modell lässt bei voller Stärke mehr
als ein Drittel des Sternlichts stehen.

### Hintergrund

Gemessen wird der Helligkeitsverlauf über die Bildfläche. Weniger ist besser.

| Bild | vorher | Modell 0,5 | Modell 1,0 | klassisch |
|---|---|---|---|---|
| C 31 (4 Aufnahmen) | 4,63 % | 5,50 % | **6,37 %** | **1,55 %** |
| IC 434 (40 Aufnahmen) | 2,69 % | 2,33 % | 2,37 % | **0,29 %** |
| IC 434 + künstlicher Verlauf | 101,87 % | 54,82 % | 15,14 % | **0,29 %** |

Auf einem groben künstlichen Verlauf arbeitet das Modell (102 % → 15 %) — es ist also nicht
kaputt. Auf **echten** Verläufen taugt es nichts: bei C 31 macht es den Verlauf sogar schlechter
(4,63 % → 6,37 %). Der klassische Weg schlägt es in allen drei Fällen deutlich.

## Fazit

Von den vier Modellen hat nur der **Entrauscher** eine Daseinsberechtigung. Beim Schärfen, beim
Sternetrennen und beim Hintergrund ist der klassische, bereits eingebaute Weg besser — teils um
ein Vielfaches. Dass alle vier als experimentell und nicht freigegeben geführt werden, ist nach
diesen Zahlen richtig.

Das ist kein Argument gegen das Nachtrainieren, sondern eines dafür, es dort anzusetzen, wo es
etwas bringt. Und es ist ein Beleg dafür, dass die klassischen Verfahren dieses Projekts nicht
die schwache Notlösung sind, für die ein „KI"-Etikett sie gern ausgibt.

## Was noch nicht gemessen ist

Ehrlich benannt, damit niemand mehr hineinliest, als dasteht:

* **Nur Seestar-S30-Aufnahmen.** Beide Messungen stammen von derselben Kamera. Ob das Modell an
  ASI294MC- oder ASI533MC-Daten genauso arbeitet, ist offen — anderer Pixelmaßstab, andere
  Sternbreite, anderes Ausleserauschen.
* **Nur Breitband (IRCUT).** Schmalband hat ein anderes Verhältnis von Signal zu Untergrund.
* **Beim Entrauschen fehlt der Vergleich mit dem klassischen Weg.** Für Schärfen, Sternetrennen
  und Hintergrund steht er oben; für das Entrauschen nicht.
* **Nur ein Motiv je Vergleich.** Die drei Vergleichsmessungen stammen alle vom selben
  IC-434-Stapel. Beim Hintergrund waren es drei Bilder, bei den anderen beiden eines.

## Ein Detail zur Normierung

Trainiert wurde mit Perzentilen (0,1 / 99,9), die **je 256×256-Szene** bestimmt wurden. Bei der
Anwendung bestimmt `core/ai_restore.py` sie **einmal über das ganze Bild** und teilt sie allen
Kacheln zu (`_infer`, „Shared statistics across all channels, never per tile or per channel").

Das ist eine bewusste Entscheidung und keine Nachlässigkeit: eine Normierung je Kachel würde
Helligkeitssprünge an den Kachelgrenzen erzeugen, also sichtbare Kanten im Bild. Der Preis ist,
dass die Eingabeverteilung bei der Anwendung nicht exakt der beim Training entspricht. Die
Messungen oben zeigen, dass es trotzdem trägt — sie sind der Beleg dafür, nicht die Theorie.
