# 05 — Verarbeitung: PixInsight, Siril, GraXpert, SetiAstro, RC-Astro, Makro

Stand 22.11.2026. Ausführlich in [../LUECKEN.de.md](../LUECKEN.de.md) und
[../CAPABILITY_STATUS.md](../CAPABILITY_STATUS.md); hier nur die Reihenfolge zum Abhaken.

Die Funktionsliste der anderen Programme ist **aus Kenntnis**, nicht heute nachgeschlagen.
Kein Bildqualitätsvergleich gegen sie ist gerechnet.

## Reihenfolge-Vorschlag

1. [ ] Bild-Arbeitsfläche: mehrere Bilder offen, Bildschirm-Streckung ohne Datenänderung,
       Pixelwerte unter dem Mauszeiger, Histogramm (PixInsight/Siril-Arbeitsweise).
2. [ ] Jede Maske auf jeden Schritt (`core/masken.py` an alle Werkzeuge).
3. [ ] Verlauf / Rückgängig über alle Schritte, als wiederholbare Kette (Rezepte erweitern).
4. [ ] SPCC ohne Siril (Gaia-Spektren × Sensor-QE × Filterkurve).
5. [ ] Himmelsmosaik (WCS-bewusst).
6. [ ] Plate-Solve ohne Hinweis aus dem Header (Blindsuche) — auch für die Aufnahme nötig.
7. [ ] LRGB-Kombination.
8. [ ] KI-Werkzeuge gegen GraXpert / Cosmic Clarity an denselben Daten messen.
9. [ ] Kleine SetiAstro-artige Helfer: Kontinuum abziehen, Halos dämpfen, Frequenztrennung.

## Makro / Fotobearbeitung

1. [ ] Fokusschiene + Kamera steuern (siehe 01_AUFNAHME, Punkt 10).
2. [ ] Ebenen und Rückgängig im Editor.
3. [ ] Reparaturpinsel aus demselben Bild (Staub).
4. [ ] Farbmanagement durchgängig (Bausteine in `develop.py` vorhanden, nicht angeschlossen).
5. [ ] Filmischer Tonwert und parametrische Masken in den Editor.
