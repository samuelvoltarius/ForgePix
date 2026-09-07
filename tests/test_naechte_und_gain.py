#!/usr/bin/env python3
"""
ForgePix — eine ganze Nacht darf nicht unbemerkt herausfallen, und Gain gehoert geprueft.

    python3 tests/test_naechte_und_gain.py

An echten Daten gefunden (M51, 340 Aufnahmen, ASI294MC Pro, 11,3 Stunden aus 5 Naechten):

    Nacht        Gain   Subs   BG-Median   behalten
    2023-04-06    120    136      0,1305     0/136
    2023-04-21    130     23      0,0390     23/23
    2023-04-22    130     91      0,0370     91/91
    2023-05-27    130     14      0,0470     14/14
    2023-05-28    130     76      0,0440     76/76

Zwei Befunde, beide von der bekannten Form — nichts schlaegt fehl:

1. **Eine ganze Nacht fiel komplett heraus**, viereinhalb von elf Stunden. Der 06.04.2023 war
   Vollmond, der Himmel dort 3,4-mal so hell. Die Verwerfung war sachlich richtig. Das
   Protokoll schrieb dazu **136 Einzelzeilen** "heller Hintergrund" und nirgends, dass damit
   eine ganze Nacht weg ist. Wer nicht alle 340 Zeilen liest, merkt es nicht — und haelt die
   Gesamtbelichtung fuer 11 Stunden, obwohl 6,8 uebrig sind.

2. **Diese Nacht hat Gain 120, alle anderen Gain 130.** Die Vorpruefung testete Kamera,
   Belichtung, Bildgroesse, Temperatur und Blickrichtung — die Verstaerkung nicht, obwohl das
   Feld GAIN laengst eingelesen wurde. Die Verstaerkung bestimmt, wieviele Elektronen hinter
   einem Zahlenschritt stehen: derselbe Himmel ergibt verschiedene Werte, Darks passen nur zu
   einem Teil, und die Ausreisser-Erkennung vergleicht Aufnahmen mit verschiedenem
   Rauschverhalten.
"""
import os
import sys
import unittest

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import vorpruefung  # noqa: E402


def _kopf(gain=130, nacht="2023-04-22"):
    return {"INSTRUME": "ZWO ASI294MC Pro", "EXPTIME": 120.0, "GAIN": gain,
            "DATE-OBS": nacht + "T01:00:00", "NAXIS1": 4144, "NAXIS2": 2822}


class TestVerstaerkung(unittest.TestCase):
    """Der M51-Fall: 136x Gain 120, 204x Gain 130."""

    def test_die_verstaerkung_steht_in_der_uebersicht(self):
        u = vorpruefung.uebersicht([_kopf(120)] * 136 + [_kopf(130)] * 204, gesamt=340)
        self.assertEqual(u["verstaerkungen"], {120: 136, 130: 204})

    def test_zwei_verstaerkungen_werden_beanstandet(self):
        u = vorpruefung.uebersicht([_kopf(120)] * 136 + [_kopf(130)] * 204, gesamt=340)
        titel = [r.titel for r in vorpruefung.pruefen(u)]
        self.assertIn("Mehrere Verstaerkungen in einer Serie", titel)

    def test_eine_verstaerkung_wird_nicht_beanstandet(self):
        """Die Gegenprobe — sonst beanstandete die Regel jede Serie."""
        u = vorpruefung.uebersicht([_kopf(130)] * 340, gesamt=340)
        titel = [r.titel for r in vorpruefung.pruefen(u)]
        self.assertNotIn("Mehrere Verstaerkungen in einer Serie", titel)

    def test_ohne_gain_im_header_passiert_nichts(self):
        """Fehlende Angaben duerfen NICHTS ausloesen — sonst waere der Befund erfunden."""
        koepfe = [{"INSTRUME": "X", "EXPTIME": 120.0, "DATE-OBS": "2023-04-22T01:00:00"}] * 10
        u = vorpruefung.uebersicht(koepfe, gesamt=10)
        self.assertEqual(u["verstaerkungen"], {})
        titel = [r.titel for r in vorpruefung.pruefen(u)]
        self.assertNotIn("Mehrere Verstaerkungen in einer Serie", titel)

    def test_die_verstaerkung_steht_im_textblock(self):
        u = vorpruefung.uebersicht([_kopf(120)] * 2 + [_kopf(130)] * 3, gesamt=5)
        self.assertIn("Gain 120", vorpruefung.text(u))
        self.assertIn("Gain 130", vorpruefung.text(u))


class TestNachtbericht(unittest.TestCase):
    """Faellt eine ganze Nacht heraus, muss das in EINER Zeile dastehen."""

    def setUp(self):
        import focus_cull_stack
        self.F = focus_cull_stack
        self.zeilen = []

    def _lauf(self, verteilung, behalten_je_nacht):
        """verteilung: {Nacht: Anzahl}; behalten_je_nacht: {Nacht: wieviele bleiben}."""
        import tempfile
        import shutil
        from astropy.io import fits
        import numpy as np
        d = tempfile.mkdtemp(prefix="fp_nacht_")
        self.addCleanup(shutil.rmtree, d, True)
        pfade, behalten = [], []
        for nacht, anzahl in sorted(verteilung.items()):
            for i in range(anzahl):
                p = os.path.join(d, "%s_%03d.fit" % (nacht.replace("-", ""), i))
                hdu = fits.PrimaryHDU(np.zeros((8, 8), np.uint16))
                hdu.header["DATE-OBS"] = nacht + "T01:00:00"
                hdu.header["INSTRUME"] = "Testkamera"
                hdu.writeto(p)
                pfade.append(p)
                if i < behalten_je_nacht.get(nacht, 0):
                    behalten.append(p)
        frames = [{"name": os.path.basename(p)} for p in pfade]
        self.F._naechte_melden(frames, behalten, pfade, log=self.zeilen.append)
        return "\n".join(self.zeilen)

    def test_eine_komplett_verlorene_nacht_wird_genannt(self):
        text = self._lauf({"2023-04-06": 8, "2023-04-22": 6},
                          {"2023-04-06": 0, "2023-04-22": 6})
        self.assertIn("2023-04-06", text)
        self.assertIn("VOLLSTAENDIG", text)
        self.assertIn("alle 8 Aufnahmen", text)

    def test_eine_gute_serie_erzeugt_keine_meldung(self):
        """Die Gegenprobe: wo nichts auffaellt, darf auch nichts stehen."""
        text = self._lauf({"2023-04-06": 8, "2023-04-22": 6},
                          {"2023-04-06": 7, "2023-04-22": 6})
        self.assertEqual(text, "")

    def test_halb_verlorene_nacht_wird_ebenfalls_genannt(self):
        text = self._lauf({"2023-04-06": 10, "2023-04-22": 6},
                          {"2023-04-06": 3, "2023-04-22": 6})
        self.assertIn("2023-04-06", text)
        self.assertIn("3 von 10", text)

    def test_eine_einzige_nacht_erzeugt_keine_meldung(self):
        """Bei nur einer Nacht ist "eine Nacht faellt heraus" keine nuetzliche Aussage —
        dann ist einfach alles weg, und das sagt die Sub-Bewertung schon."""
        text = self._lauf({"2023-04-06": 8}, {"2023-04-06": 0})
        self.assertEqual(text, "")


class TestInDerPipeline(unittest.TestCase):

    def test_die_pipeline_ruft_den_nachtbericht(self):
        import io
        pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core",
                            "focus_cull_stack.py")
        with io.open(pfad, encoding="utf-8") as fh:
            quelle = fh.read()
        self.assertIn("_naechte_melden(_frames, kept, paths)", quelle,
                      "die Sub-Bewertung meldet nicht, wenn eine Nacht komplett wegfaellt")


if __name__ == "__main__":
    unittest.main(verbosity=2)
