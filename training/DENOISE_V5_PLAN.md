# V5: ein zusätzlicher Pixel-MAE-Term

Versuchsnotiz vom 06.09.2026. Nur Vorbereitung: keine Downloads, kein Trainingsstart, keine Änderung laufender Prozesse oder der Anwendung. Vorgeschlagene Laufkennung: `denoise-anchored-v5-mae-001`.

## Ausgangspunkt und einzige Änderung

V4 absolvierte 6.000 CUDA-Schritte auf dem Spark (NVIDIA GB10). Der geometrische Gruppen-MSE sank gegenüber dem ursprünglichen Elternmodell um 10,90 %. Trotzdem scheiterte der Kandidat an 17 MAE-, vier MSE- und einem Lokalmittel-Gate; alle 27 Bildbias-Gates bestanden. Er wurde abgewiesen. Der Finalseed **9671507 ist unbenutzt**. Das begründet die Untersuchung eines direkten MAE-Terms, aber keine Aussage über dessen Erfolg.

Für den normalisierten Pixelrest `e = prediction − target` gilt ausschließlich:

```text
L5 = L4 + lambda_mae * mean(abs(e))
L4 = MSE + 0.5 * Gradient-MSE + 4 * Lokalmittel-MSE
     + 2 * Schwachsignal-MSE + 0.25 * Replay-Anker-MSE
```

Definitionen, Masken, Poolinggrößen und bisherige Koeffizienten bleiben exakt aus `preservation_loss()` erhalten. Keine zusätzliche Verlustfunktion, Datenaugmentation oder Architekturänderung. Beide Netze beginnen erneut mit dem ursprünglichen Mono-v2-Elterncheckpoint; der gescheiterte V4-Student wird nicht fortgesetzt. Eltern-SHA256:
`e2c5b901b8761908edb9cd23d3d49ee4302b8b357a5dfad4a57eca446857e417`.

## Gewicht ausschließlich aus Trainingsdaten

Vor jeder Optimierung wird diese Regel festgeschrieben:

1. Die ersten **96 Trainingsbatches** mit je vier Beispielen aus der unveränderten V4-Folge auswerten: vier vollständige Zyklen des 24er-Schedules. Nur Trainingsbank und Trainingsgenerator verwenden, keine Entwicklungsfälle.
2. Am initialen Modell ohne Gradienten/Optimierung je Batch `L4` und Pixel-MAE messen. Einmalig festlegen: **`lambda_mae = 0.10 * median(L4) / median(Pixel-MAE)`**. Die vorab gewählten 10 % sind eine Versuchsentscheidung über anfängliche Lossskalen, kein aus Validierung abgeleitetes Optimum; sie garantieren keine entsprechende Gradientengewichtung.
3. Nichtendliche oder nichtpositive Mediane brechen den Versuch ab. Kein Ersatzgewicht, kein Gewichtssweep und keine spätere Anpassung anhand eines Ergebnisses.
4. Kalibrierung mit geklontem Generatorzustand nach unveränderter Modellinitialisierung durchführen; globale CPU-/CUDA-Zufallszustände und Modellmodus sichern/wiederherstellen. Die eigentliche Trainingsfolge darf nicht vorrücken. Reproduktion der ersten 96 Batch-Hashes prüfen. Beide Mediane, Gewicht, Batch-Hashes und Quell-/Daten-/Eltern-Hashes vor Schritt 1 protokollieren. Die 96 Messbatches zählen nicht als Optimierungsschritte.

## Unveränderter Versuch und Entscheidung

- Architektur: eingefrorener Parent plus identischer trainierbarer NAFNet-Student, `alpha=0.25`; Korrekturmittel je 256er-Kachel abziehen. Mono, bestehende affine Normalisierung und Ein-/Ausgabevertrag unverändert. Diese Zentrierung bewahrt den Parent-Mittelwert je Kachel, nicht nachweislich den wahren Himmel oder den Mittelwert des zusammengesetzten Bildes.
- Training: Seed **609064**, Batch 4, 50 % Original-Replay; übriger Schedule mit Identity, Low-/Read-/Shot-Noise, drei korrelierten Skalen und Zeilenrauschen unverändert. AdamW `lr=1e-5`, `weight_decay=0`, Cosine bis `1e-6`, Gradientenclip `0.25`, exakt **6.000 Optimierungsschritte**. Keine Änderung von Präzision, Replay, Generatoren oder deren Aufrufreihenfolge.
- Daten: dieselben 563 Trainingspatches aus M101/M42/M8/M82/NGC7009 und 288 Entwicklungspatches aus M13/M16 mit denselben Manifest-/Bank-Hashes. Keine Verschiebung zwischen Splits. Beobachtete Patches enthalten eigenes Rauschen und sind keine unabhängig gemessenen sauberen Referenzen; überlappende Patches sind keine unabhängigen Aufnahmen.
- Entwicklung: Seed **830125**, dieselben 27 Gruppen mit je 16 Szenen, Prüfungen alle 1.000 Schritte und unveränderte Auswahl. Pro Gruppe darf MSE höchstens Parent + `1e-12`, MAE/Bildbias/Lokalmittel-RMS höchstens Parent + `1e-8` betragen; zusätzlicher geometrischer MSE-Score < 1 für einen geeigneten Kandidaten. Kein Durchschnitt darf einzelne Gate-Verletzungen aufheben.
- Erst ein geeigneter, unveränderlich gehashter Kandidat darf einmal die **128 unabhängigen synthetischen Finalszenen mit Seed 9671507** verwenden. Unveränderter Evaluator: Gesamt-MSE, MSE jeder Rauschklasse, absoluter Sternapertur-Flussfehler, Schwachstruktur-MSE und mittlerer absoluter Bildbias jeweils höchstens Parent; fehlende/nichtendliche Werte bedeuten Ablehnung. Keine Final-Wiederholung nach Nachjustierung. Frühere verbrauchte Seeds 9237401/9374209/9518063 bleiben ausgeschlossen.
- Vor dem nächsten Spark-Start (der Nutzerauftrag zum Training liegt bereits vor): CUDA prüfen, vorhandene exklusive Trainingssperre respektieren, mindestens 80 GiB freie Platte und ausreichenden aktuellen RAM/VRAM nachweisen, neues Ausgabeverzeichnis verwenden. V4 benötigte etwa 544 s Optimierung und 24 s Entwicklungsprüfung; ungefähr zehn Minuten sind nur eine historische Größenordnung, keine Ressourcenzusage. Keine anderen Prozesse beenden oder verdrängen.

Bei jedem Fehlschlag bleibt das ursprüngliche Modell aktiv. Ein bestandener Finalvergleich erlaubt nach bestehender Logik höchstens einen klar bezeichneten Forschungsexport. **Keine neue ONNX-Einbindung**, bevor zusätzlich Vollbild-/Kachelphasen-, reale Kamera-/Filter- und tatsächliche Backend-Gates bestanden und dokumentiert sind. V5 erhält eigene Artefaktmetadaten; keine Überschreibung von V4. Die bereits betrachtete Entwicklung bleibt Entwicklung, kein unabhängiger Qualitätsnachweis.

## Nächste Erhaltungsprüfungen für andere Aufgaben

Diese Prüfungen werden zuerst gebaut und mit unveränderten Modellen ausgeführt; sie begründen noch kein größeres Training. Unabhängiger Szenen-/Messcode, bekannte Komponenten, vor Ausführung eingefrorene Fälle und Fehlerbudgets; mindestens ein Vollbild über mehrere Kacheln sowie verschobene Kachelursprünge, signierte Werte und HDR. Den reservierten Denoise-Finalseed dabei nicht verwenden.

| Aufgabe | Nächster überprüfbarer Test und Ablehnungsgrund |
|---|---|
| Background | Identische ausgedehnte Nebel-/Sternszene mit und ohne bekannten additiven, mittelwertfreien Gradienten; dasselbe Rauschen bleibt im Ziel. Nebel-Aperturfluss, schwache Filamente, Sternfluss und verbleibenden Gradienten getrennt gegen bekannte Wahrheit messen. Gradientfreie Kontrollbilder dürfen keine systematische Nebelentfernung zeigen. Verbesserter Hintergrundfehler bei verschlechterter Nebelerhaltung genügt nicht; absoluter Himmelsoffset bleibt ohne Referenz unbestimmt. |
| Deblur | Bekannte Einzel-/Doppelsterne und Nebel mit unabhängig erzeugter, normierter elliptischer Moffat-PSF verwischen; rauschfreie und bekannte verrauschte Fälle getrennt. Fluss, Schwerpunkt, Doppelsternabstand, Ringing und Fehler nach erneuter Faltung mit derselben bekannten PSF prüfen; zusätzlich unverwaschene Identitätskontrolle. Schärferer Eindruck/FWHM allein besteht den Test nicht. |
| Starless | Bekannte Sternkomponente auf Nebelfilamente legen, einschließlich Überlagerungen und sternfreier Kontrolle. Reststernfluss und Verlust echter Nebelemission getrennt in vorher festgelegten Masken/Aperturen messen; dasselbe Beobachtungsrauschen im Ziel behalten. `starless + residual = input` ist nur eine algebraische Kontrolle und belegt keine korrekte Trennung. |

Für diese neuen Prüfungen müssen Wahrheitsfehler und Vergleich zum unveränderten aktuellen Modell gemeinsam ausgewiesen werden; kein automatisches Bestehen allein durch einen verbesserten Gesamtscore. Konkrete numerische Toleranzen werden aus bekanntem injiziertem Rauschen und numerischer Referenzfehlerrechnung vor dem ersten Modellvergleich festgelegt, nicht nach dessen Ergebnissen.

Quellen dieses Entwurfs: [V4-Trainer](refine_denoise_v4.py), [unveränderter Selektor](evaluate_denoise_v4.py), [Trainingsgenerator](train_restoration.py), [unabhängiger Evaluator](evaluate_models.py), [V4-Entscheidung](reports/denoise-anchored-v4-001-decision.json), [Ausführungsbericht](reports/denoise-anchored-v4-001-execution.json).
