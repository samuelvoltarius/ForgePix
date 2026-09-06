# Projekte und gesicherte Ergebnisse

Über **Projekt > Neues Projekt** legst du eine `.forgepix`-Datei an. Ab dann
sichert ForgePix neue fertige Ergebnisse als eigene Dateikopien im Projekt.
Einen vorhandenen linearen Stack kannst du über **Ergebnis hinzufügen** aufnehmen.

**Ergebnisverlauf** zeigt die gespeicherten Stände mit Datum und Dateistatus.
Wähle einen Stand und **Ergebnis öffnen**, um ihn wieder anzuzeigen und weiter
zu bearbeiten. Neue Ergebnisse werden als weitere Stände gesichert; eine
überschriebene Arbeitsdatei ersetzt die vorherige Sicherung nicht.

Die Datei und ihr Ordner `stack-<Projektname>.files-<ID>` gehören zusammen.
Verschiebe oder sichere beide, wenn du das Projekt an einen anderen Ort legst.
Originalaufnahmen werden verlinkt und nicht verändert. Das Projekt ersetzt
kein Backup aller Lights, Darks, Flats und Bias-Aufnahmen.

Fehlende oder veränderte Dateien stehen im Verlauf. Eine Datei lässt sich nur
neu zuordnen, wenn ihre Prüfsumme dem gespeicherten Stand entspricht. Eine
unveränderte Sicherung bleibt nutzbar, auch wenn die ursprüngliche Arbeitsdatei
inzwischen geändert wurde. Ein fehlendes Vergleichsbild wird nicht durch ein
anderes Bild ersetzt.

**Gesicherten Stand exportieren** kopiert die verifizierten Ergebnisdateien samt
benötigten Begleitdateien in einen neuen Ordner. FITS-/TIFF-Pixel und Metadaten
bleiben dabei bytegleich. Drizzle-Abdeckung und Gewichte sowie aufgezeichnete
KI-Ergebnisgruppen gehören zur Sicherung. Eine fehlerhafte Kopie wird nicht als
fertiger Export übernommen.

Projektdatei und Sicherungen werden bei Verwendung geprüft. Die Speicherung
erkennt eine außerhalb des Fensters geänderte Projektdatei, statt sie still
zu überschreiben. Sicherungs- und Exportordner tragen ein `stack-`-Präfix, damit
die Erkennung von Aufnahmeordnern sie nicht als neue Rohbildserie auswählt.

Diese Funktion speichert Ordner, Modul und fertige Ergebnisstände. Sie ist noch
kein Undo/Redo aller Verarbeitungsschritte: Reglerstellungen, editierbare Masken
und ein automatisch neu berechenbarer Prozessgraph werden damit nicht vollständig
wiederhergestellt. Verarbeitungseinstellungen bleiben vorerst in der Anwendung.
