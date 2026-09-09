"""Die Feldspanne der Vorpruefung, robust gegen einzelne kaputte Kopfeintraege.

Warum es diesen Test gibt: die Spanne wurde als *Abstand zum Mittelwert x 2* berechnet. Ein
einziger Kopf mit falscher Koordinate zieht den Mittelwert weg UND setzt das Maximum. An
NGC 7023 gemessen — 215 Aufnahmen, davon EINE mit DEC +28,81 statt +68,18 (Fehlmeldung der
Montierung) — meldete die Vorpruefung "Ausrichtungen bis 78,4 Grad auseinander" und riet
KRITISCH, den Ordner nach Objekten zu trennen. Es gab nichts zu trennen.

Die Gegenprobe zaehlt genauso: der `whirl`-Ordner enthaelt wirklich fuenf Ziele, und dort MUSS
die Warnung weiter kommen. Ein Filter, der beide Faelle gleich behandelt, waere kein Fortschritt.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
import vorpruefung
from regeln import KRITISCH


def koepfe(richtungen):
    """Minimale Kopfdaten — nur was die Richtungspruefung liest."""
    return [{"RA": ra, "DEC": dec, "INSTRUME": "ZWO ASI533MC Pro", "EXPTIME": 60.0}
            for ra, dec in richtungen]


class Feldspanne(unittest.TestCase):
    def test_ein_kaputter_kopf_loest_keine_kritische_warnung_aus(self):
        richtungen = [(315.4 + 0.02 * (i % 5), 68.18 + 0.01 * (i % 3)) for i in range(214)]
        richtungen.append((315.17, 28.81))          # die eine Fehlmeldung
        u = vorpruefung.uebersicht(koepfe(richtungen))

        self.assertEqual(u["richtung_ausreisser"], 1)
        self.assertLess(u["richtungsspanne_grad"], 1.0)
        titel = [r.titel for r in vorpruefung.pruefen(u) if r.stufe == KRITISCH]
        self.assertNotIn("Mehrere Himmelsausschnitte in einer Serie", titel)
        # Gemeldet wird es trotzdem — nur als das, was es ist.
        alle = [r.titel for r in vorpruefung.pruefen(u)]
        self.assertIn("Einzelne Aufnahmen mit unglaubwuerdiger Koordinate", alle)

    def test_zwei_echte_ziele_werden_weiter_kritisch_gemeldet(self):
        # Gegenprobe: 120 Aufnahmen auf einem Feld, 80 auf einem zweiten, 8 Grad entfernt.
        richtungen = ([(202.5, 47.2)] * 120) + ([(210.8, 54.3)] * 80)
        u = vorpruefung.uebersicht(koepfe(richtungen))
        self.assertEqual(u["richtung_ausreisser"], 0)
        self.assertGreater(u["richtungsspanne_grad"], 1.0)
        titel = [r.titel for r in vorpruefung.pruefen(u) if r.stufe == KRITISCH]
        self.assertIn("Mehrere Himmelsausschnitte in einer Serie", titel)

    def test_die_spanne_verschweigt_das_dithering_nicht(self):
        # Bei EINEM Feld darf nicht 0,00 Grad herauskommen — das waere die Aussage, alle
        # Aufnahmen laegen exakt uebereinander, und dann waere jedes Dithering unsichtbar.
        richtungen = [(315.40, 68.18), (315.40, 68.24), (315.46, 68.18), (315.46, 68.24)]
        u = vorpruefung.uebersicht(koepfe(richtungen))
        self.assertGreater(u["richtungsspanne_grad"], 0.01)
        self.assertLess(u["richtungsspanne_grad"], 1.0)

    def test_lauter_kleine_felder_gelten_nicht_alle_als_ausreisser(self):
        # Wenn JEDES Feld unter der Schwelle liegt, waere "alles Ausreisser" die falsche
        # Antwort — dann sind es echte Ziele, und die Spanne muss zaehlen.
        richtungen = [(200.0, 40.0), (210.0, 45.0), (220.0, 50.0)]
        u = vorpruefung.uebersicht(koepfe(richtungen))
        self.assertEqual(u["richtung_ausreisser"], 0)
        self.assertGreater(u["richtungsspanne_grad"], 1.0)


if __name__ == "__main__":
    unittest.main()


class AusreisserRegel(unittest.TestCase):
    """Die Regel muss in BEIDE Richtungen halten — sonst ist sie kein Fortschritt."""

    def test_bei_drei_aufnahmen_ist_eine_kein_ausreisser(self):
        # Ein Drittel der Daten ist keine Fehlmeldung. Genau dieser Fall stand schon als Test
        # im Bestand (test_vorpruefung.py) und wurde von einer reinen Stueckzahlschwelle
        # kaputtgemacht.
        u = vorpruefung.uebersicht(koepfe(
            [(202.47, 47.19), (202.50, 47.21), (210.75, 54.30)]))
        self.assertEqual(u["richtung_ausreisser"], 0)
        self.assertGreater(u["richtungsspanne_grad"], 5.0)

    def test_bei_fuenfzig_aufnahmen_ist_ein_falscher_kopf_ein_ausreisser(self):
        # Hier waeren 2 % genau eine Aufnahme — eine reine Verhaeltnisschwelle liesse den
        # kaputten Kopf durch.
        richtungen = [(315.4, 68.18)] * 49 + [(315.17, 28.81)]
        u = vorpruefung.uebersicht(koepfe(richtungen))
        self.assertEqual(u["richtung_ausreisser"], 1)
        self.assertLess(u["richtungsspanne_grad"], 1.0)
