#!/usr/bin/env python3
"""
ForgePix — Tests für das Regelwerk (core/regeln.py).

    python3 tests/test_regeln.py

Ein Regelwerk ist nur so gut wie seine Zurückhaltung. Zwei Eigenschaften zählen darum mehr als
die einzelnen Schwellen:

1. **Auf sauberen Daten schweigt es weitgehend.** Ein Werkzeug, das bei jedem Bild fünf
   Warnungen ausgibt, wird nach dem dritten Mal ignoriert. An einem echten M27-Stack meldet es
   genau einen Punkt (zu wenige Aufnahmen) — und der stimmt.
2. **Fehlende Messwerte lösen KEINE Regel aus.** Eine Regel, die auf `None` anspringt,
   erfindet einen Befund aus einer Nicht-Messung. Genau davor schützt der Bericht mit seinem
   konsequenten `None`, und das darf hier nicht wieder aufgeweicht werden.
"""
import os
import sys
import unittest

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import regeln  # noqa: E402


def _bericht(**abweichungen):
    """Ein unauffaelliger Bericht; einzelne Werte lassen sich gezielt verbiegen."""
    b = {
        "bild": {"hoehe": 1000, "breite": 1400, "kanaele": 3, "ausgebrannt_prozent": 0.0},
        "himmel": {"median": 0.03, "rauschen": 0.00002, "gradient_prozent": 0.8},
        "sterne": {"anzahl": 300, "fwhm_px": 2.2, "rundheit": 1.1, "spur": False,
                   "quelle": "test"},
        "farbe": {"g_zu_b": 1.007, "g_zu_r": 1.005, "passt": True, "urteil": "passt"},
        "signal_zu_rauschen": 200.0,
        "ausruestung": {"kamera": "asi294mc", "brennweite_mm": 1151.0,
                        "pixelgroesse_um": 4.63, "skala_bogensek_px": 0.83,
                        "sampling": "gut", "belichtung_s": 300.0, "temperatur_c": -10.0,
                        "gain": 121.0, "filter": None},
        "serie": {"anzahl": 60, "gesamt_minuten": 300.0, "zeiten_s": [300.0], "gemischt": False},
    }
    for pfad, wert in abweichungen.items():
        teile = pfad.split("__")
        k = b
        for t in teile[:-1]:
            k = k[t]
        k[teile[-1]] = wert
    return b


class TestZurueckhaltung(unittest.TestCase):

    def test_sauberer_bericht_gibt_keinen_rat(self):
        self.assertEqual(regeln.pruefen(_bericht()), [])

    def test_fehlende_werte_loesen_nichts_aus(self):
        """Der wichtigste Test: aus einer Nicht-Messung darf kein Befund werden."""
        leer = {"bild": {"ausgebrannt_prozent": None}, "himmel": {"gradient_prozent": None},
                "sterne": {"rundheit": None, "spur": None}, "farbe": {"passt": None},
                "signal_zu_rauschen": None,
                "ausruestung": {"sampling": None},
                "serie": {"anzahl": None, "gemischt": None}}
        self.assertEqual(regeln.pruefen(leer), [])

    def test_ganz_leerer_bericht_stuerzt_nicht(self):
        self.assertEqual(regeln.pruefen({}), [])


class TestEinzelneRegeln(unittest.TestCase):

    def _titel(self, **abw):
        return [r.titel for r in regeln.pruefen(_bericht(**abw))]

    def test_signal_unter_rauschen_ist_kritisch(self):
        raete = regeln.pruefen(_bericht(signal_zu_rauschen=0.7))
        self.assertTrue(any(r.stufe == regeln.KRITISCH for r in raete))
        self.assertIn("Saettigung", raete[0].grund,
                      "der Grund muss sagen, warum Regler drehen hier NICHT hilft")

    def test_gradient_stuft_sich_ab(self):
        self.assertEqual(self._titel(himmel__gradient_prozent=0.8), [])
        self.assertIn("Leichter Helligkeitsverlauf", self._titel(himmel__gradient_prozent=5.0))
        self.assertIn("Starker Helligkeitsverlauf im Hintergrund",
                      self._titel(himmel__gradient_prozent=30.0))

    def test_farbe_passt_nicht(self):
        t = self._titel(farbe__passt=False, farbe__urteil="Flat fehlt vermutlich")
        self.assertIn("Farbverhalten passt nicht zur Kamera", t)

    def test_ausgebrannte_pixel(self):
        self.assertEqual(self._titel(bild__ausgebrannt_prozent=0.0), [])
        self.assertIn("Einzelne ausgebrannte Sternkerne",
                      self._titel(bild__ausgebrannt_prozent=0.2))
        self.assertIn("Viele ausgebrannte Pixel", self._titel(bild__ausgebrannt_prozent=1.5))

    def test_verzogene_sterne_empfehlen_synthstar_mit_warnung(self):
        raete = regeln.pruefen(_bericht(sterne__rundheit=2.0))
        r = [x for x in raete if "verzogen" in x.titel][0]
        self.assertIn("--astro-synthstar", r.einstellung)
        self.assertIn("Photometrie", r.massnahme,
                      "die Einschraenkung gehoert in den Rat, nicht nur in den Code")

    def test_abtastung(self):
        self.assertIn("Unterabgetastet", self._titel(ausruestung__sampling="unterabgetastet"))
        self.assertIn("Ueberabgetastet", self._titel(ausruestung__sampling="ueberabgetastet"))

    def test_wenige_aufnahmen(self):
        self.assertEqual([t for t in self._titel(serie__anzahl=60) if "Wenige" in t], [])
        self.assertIn("Wenige Aufnahmen", self._titel(serie__anzahl=4))

    def test_gemischte_zeiten_werden_nur_gemeldet(self):
        raete = regeln.pruefen(_bericht(serie__gemischt=True, serie__zeiten_s=[60.0, 300.0]))
        r = [x for x in raete if "Gemischte" in x.titel][0]
        self.assertEqual(r.stufe, regeln.HINWEIS,
                         "das wird automatisch behandelt, ist also kein Mangel")


class TestSchalterExistieren(unittest.TestCase):
    """Jeder Schalter, den eine Regel empfehlen kann, muss die Pipeline auch kennen.

    Das ist kein Formalismus. `--astro-bg-extract` stand hier, die Option heisst aber
    `--bg-extract` — ausgeloest wurde die Regel am haeufigsten von allen. Wer dem Rat folgte,
    bekam von argparse einen Fehler statt eines Bildes. Der Rat las sich dabei vollkommen
    plausibel, mit gemessener Begruendung und allem. Genau daran faellt so etwas nicht auf,
    und genau darum prueft es ab jetzt eine Maschine.
    """

    def test_jeder_empfohlene_schalter_existiert(self):
        import inspect
        import re
        import subprocess
        import sys
        wurzel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        hilfe = subprocess.run(
            [sys.executable, "-X", "utf8", os.path.join(wurzel, "core", "focus_cull_stack.py"),
             "--help"],
            capture_output=True, text=True, encoding="utf-8", timeout=300).stdout
        self.assertIn("--input", hilfe, "die Hilfe liess sich nicht lesen")
        quelle = inspect.getsource(regeln.pruefen)
        schalter = set()
        for treffer in re.findall(r'"(--[a-z0-9-]+(?: [^"]*)?)"', quelle):
            schalter.update(t for t in treffer.split() if t.startswith("--"))
        self.assertTrue(schalter, "es wurde gar kein Schalter gefunden — Test waere wertlos")
        fehlend = sorted(s for s in schalter if s not in hilfe)
        self.assertEqual(fehlend, [], "Regelwerk empfiehlt unbekannte Schalter: %s" % fehlend)


class TestKometenModus(unittest.TestCase):
    """Beim Kometen-Stacking wird auf den KERN ausgerichtet — die Sterne sind absichtlich
    Striche. Mehrere Regeln sind dann nicht nur nutzlos, sondern schaedlich."""

    def test_synthstar_wird_nicht_empfohlen(self):
        """`--astro-synthstar` wuerde die Striche durch runde Profile ersetzen und damit genau
        das Ergebnis zerstoeren, wegen dem man den Modus gewaehlt hat."""
        raete = regeln.pruefen(_bericht(sterne__rundheit=2.0), komet=True)
        self.assertEqual([r for r in raete if "verzogen" in r.titel], [])
        self.assertNotIn("--astro-synthstar", regeln.einstellungen(raete))

    def test_helligkeitsverlauf_wird_nicht_beurteilt(self):
        """Die Sternstriche liegen ueber das ganze Bild und gehen in die Messung des
        Hintergrunds ein — an echten Kometendaten: Gradient 133 % bei einem Bild, das nur
        Striche enthaelt."""
        raete = regeln.pruefen(_bericht(himmel__gradient_prozent=133.0), komet=True)
        self.assertEqual([r for r in raete if "Helligkeitsverlauf" in r.titel], [])

    def test_strichspur_ist_hier_keine_spur(self):
        raete = regeln.pruefen(_bericht(sterne__spur=True), komet=True)
        self.assertEqual([r for r in raete if "Strichspur" in r.titel], [])

    def test_der_hinweis_erklaert_warum(self):
        raete = regeln.pruefen(_bericht(), komet=True)
        r = [x for x in raete if "Kometen" in x.titel]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].stufe, regeln.HINWEIS)
        self.assertIn("Kern", r[0].grund)

    def test_ohne_kometen_modus_bleibt_alles_wie_bisher(self):
        """Die Gegenprobe: sonst waere nicht zu unterscheiden, ob die Regeln unterdrueckt
        werden oder ueberhaupt nicht mehr greifen."""
        raete = regeln.pruefen(_bericht(sterne__rundheit=2.0, himmel__gradient_prozent=133.0))
        titel = [r.titel for r in raete]
        self.assertTrue(any("verzogen" in t for t in titel))
        self.assertTrue(any("Helligkeitsverlauf" in t for t in titel))
        self.assertEqual([t for t in titel if "Kometen" in t], [])

    def test_was_weiter_gilt_bleibt_stehen(self):
        """Signalabstand und Aufnahmezahl gelten auch im Kometen-Modus."""
        titel = [r.titel for r in regeln.pruefen(_bericht(serie__anzahl=4), komet=True)]
        self.assertTrue(any("Wenige Aufnahmen" in t for t in titel))


class TestAusgabe(unittest.TestCase):

    def test_reihenfolge_nach_dringlichkeit(self):
        raete = regeln.pruefen(_bericht(signal_zu_rauschen=0.5,
                                        himmel__gradient_prozent=30.0,
                                        ausruestung__sampling="ueberabgetastet"))
        stufen = [r.stufe for r in raete]
        self.assertEqual(stufen[0], regeln.KRITISCH)
        self.assertEqual(stufen[-1], regeln.HINWEIS)

    def test_einstellungen_sind_eindeutig_und_geordnet(self):
        raete = regeln.pruefen(_bericht(himmel__gradient_prozent=30.0,
                                        bild__ausgebrannt_prozent=1.5))
        e = regeln.einstellungen(raete)
        self.assertEqual(len(e), len(set(e)), "doppelte Schalter")
        self.assertIn("--bg-extract", e)

    def test_text_ohne_raete(self):
        self.assertIn("Keine Auffaelligkeiten", regeln.text([]))

    def test_text_nennt_grund_und_massnahme(self):
        t = regeln.text(regeln.pruefen(_bericht(signal_zu_rauschen=0.5)))
        self.assertIn("->", t, "jede Empfehlung braucht eine Massnahme")


if __name__ == "__main__":
    unittest.main(verbosity=2)
