# 08 — Alles gut, nicht nur alles da: die Qualitätsprüfung

Stand 23.11.2026. Vorgabe von Alfred: **eine All-in-one-App, die alles kann — und zwar gut, nicht
nur alles etwas.** Dazu: **für alles freie Modelle nutzen, soweit es geht; wo wir es selbst nicht
nachbauen können, einen Download zu dem Projekt verlinken**, das die Leute selbst holen.

## Leitlinie

1. **Gut heißt gemessen.** Jedes Modul wird an echten Daten gegen sein Vorbild gemessen (gleiche
   Eingabe, gleiche Kennzahl), bevor es „gut“ heißt. Vorhandensein ist kein Qualitätsbeweis.
2. **Eigenes zuerst, frei lizenziert.** Wo wir es selbst bauen können: selbst bauen. Freie Modelle
   (MIT/Apache/BSD, siehe 06_KI) nur nach eigener Lizenzprüfung der Gewichte.
3. **Sonst verlinken, nie mitliefern.** Programme mit nicht-kommerziellen oder fehlenden
   Weitergaberechten (GraXpert-Modelle, StarNet, Cosmic Clarity, ASTAP-Datenbanken) ruft ForgePix
   nur auf; das Fenster „Zusatzprogramme“ zeigt, was fehlt, und verlinkt die offizielle Seite.

## Was zu prüfen ist (Reihenfolge-Vorschlag)

| Bereich | Vorbild | Kennzahl | Daten | Stand |
|---|---|---|---|---|
| Astro-Stapeln (Kalibrieren, Ausrichten, Integration) | Siril, PixInsight WBPP | Sternform (FWHM, Exzentrizität), Rauschen im Hintergrund, SNR, Abdeckung | D:\astro (Seestar, ASI294, ASI533) | Teilweise gemessen (M27, IC 5146), kein Vergleich gegen Siril an denselben Daten |
| Automatik / Anfänger-Modus | — | richtige Moduswahl, sinnvolle Standardwerte, keine stillen Fehler | gemischte Ordner | offen |
| Fokus-Stacking (Makro) | Helicon Focus, Zerene Stacker | Schärfe je Region, Halos, Geister an Kanten | Makro-Fokusreihen (Beispieldaten-Download) | algorithmisch gebaut (DEEP_GAPS), Vergleich offen |
| Langzeitbelichtung aus Einzelbildern | Sequator, StarStaX, Photoshop-Mittelwert | Rauschen, Bewegungsunschärfe, Geister | Serien normaler Kameras | offen |
| RAW-Konverter | darktable, RawTherapee, Lightroom | Farbtreue (ΔE an Farbkarte), Rauschen, Details, Lichterrekonstruktion | RAW-Dateien mehrerer Kameras | Farbmanagement nicht durchgängig (05) |
| PixInsight-Werkzeuge (Arbeitsplatz) | PixInsight | je Werkzeug gleiches Bild, Differenzbild, Kennzahl | eigener Stapel | 50 Werkzeuge gebaut, kein Vergleich gegen PixInsight |
| KI (Entrauschen, Schärfen, Sterne, Hintergrund) | RC-Astro, GraXpert, Cosmic Clarity | Rauschen, Sternfluss, Artefakte | eigener Stapel | eigenes Entrauschen gemessen, Rest schlechter als klassisch |

## Testdaten (23.11.2026 besorgt)

Siehe [../TESTDATEN.md](../TESTDATEN.md): RAW von 18 Herstellern (CC0), zwei freie Fokusreihen
(eine mit Referenz-Ergebnis), ein CC0-Wasserfall-Video für Langzeit, die eigenen Beispieldaten.
Holen mit `python3 testdaten_holen.py`.

### Ergebnisse bisher

| Bereich | Ergebnis | Folge |
|---|---|---|
| RAW-Lesen | 19/20 Dateien von 18 Herstellern + A7 V/A7 III; GoPro .gpr nicht | Endungsliste ergänzt (Hasselblad/Phase One wurden nicht erkannt), GPR-Meldung mit Link |
| RAW-Aussehen | Farbe ±10 % zur Kamera; **Helligkeit im Median 0,58 der Kamera-Vorschau** | Entscheidung offen: Vorgabe „treu“ (heute) oder „wie die Kamera“ |
| Fokus-Stacking | — | als Nächstes: focus-stack_pcb gegen `expected.jpg` |
| Langzeit | — | als Nächstes: Wasserfall-Video |

## Was dafür gebraucht wird

* **Daten**: je Bereich ein echter Datensatz (Makro-Reihe, Langzeit-Serie, RAW-Dateien mit
  Farbkarte). Für Astro ist D:\astro da; für Makro/Langzeit/RAW bitte Ordner nennen.
* **Vergleichsprogramme**: Siril und GraXpert sind auf dem Testrechner; PixInsight,
  Helicon/Zerene, darktable nicht — ohne sie bleibt der Vergleich einseitig (nur Kennzahlen).
