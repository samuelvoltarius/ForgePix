#!/usr/bin/env python3
"""
ForgePix — das Regelwerk darf nicht empfehlen, was gerade gelaufen ist.

    python3 tests/test_rat_kein_zirkel.py

An echten Daten gesehen (IC 434, 133 von 224 Subs, Seestar S30). Der Lauf machte:

    PHASE:background
      Hintergrund/Gradient entfernen …
        Hintergrund (RBF/DBE-Stil, je Kanal): 144 Sky-Stuetzpunkte, Nebel geschuetzt

und schrieb danach:

      !  Starker Helligkeitsverlauf im Hintergrund
         -> Hintergrund-Entfernung einschalten.
            --bg-extract
      RAT:--bg-extract

Die Hintergrund-Entfernung **lief bereits**. Der Rat schickt den Benutzer im Kreis: er setzt den
Schalter, rechnet 20 Minuten neu und bekommt exakt dasselbe Bild.

Die Ursache ist nicht die Regel, sondern die Reihenfolge: `_astro_write` bindet
`result = astro.background_extract(result)` nur lokal, der Messbericht des Aufrufers sieht also
den Stapel **vor** der Entfernung. Die 16,1 % sind echt gemessen — nur eben am Rohstapel. Darum
wird der Rat nicht geloescht, sondern zum Hinweis herabgestuft, der das dazusagt.
"""
import ast
import io
import os
import sys
import unittest

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import regeln  # noqa: E402


BERICHT = {
    "himmel": {"median": 0.0033, "rauschen": 7e-5, "gradient_prozent": 16.1},
    "signal_zu_rauschen": 6.0,
    "bild": {"ausgebrannt_prozent": 0.0},
}


class TestKeinZirkel(unittest.TestCase):

    def test_der_rat_kommt_wenn_der_schalter_aus_war(self):
        """Die Gegenprobe zuerst — sonst wuerde ein Regelwerk, das gar nichts mehr sagt,
        diesen Test ebenfalls bestehen."""
        raete = regeln.pruefen(BERICHT)
        self.assertIn("--bg-extract", regeln.einstellungen(raete))

    def test_kein_rat_auf_einen_schalter_der_schon_lief(self):
        raete = regeln.pruefen(BERICHT, bereits=["--bg-extract"])
        self.assertEqual(regeln.einstellungen(raete), [],
                         "empfiehlt einen Schalter, der bei diesem Lauf schon gesetzt war")

    def test_der_befund_verschwindet_nicht_stillschweigend(self):
        """Die Messung bleibt wahr: 16 % Verlauf sind 16 % Verlauf. Der Benutzer muss davon
        erfahren — nur eben ohne die falsche Handlungsanweisung."""
        raete = regeln.pruefen(BERICHT, bereits=["--bg-extract"])
        titel = [r.titel for r in raete]
        self.assertIn("Starker Helligkeitsverlauf im Hintergrund", titel)
        treffer = [r for r in raete if r.titel == "Starker Helligkeitsverlauf im Hintergrund"][0]
        self.assertEqual(treffer.stufe, regeln.HINWEIS)
        self.assertIn("lief", treffer.grund,
                      "der Hinweis muss sagen, dass die Massnahme schon lief: %s" % treffer.grund)

    def test_ein_wert_mit_argument_wird_am_schalter_erkannt(self):
        """`--astro-starless-stretch 0.35` und `--astro-starless-stretch` sind derselbe
        Schalter. Ein reiner Zeichenkettenvergleich haette hier danebengelegen."""
        b = dict(BERICHT, bild={"ausgebrannt_prozent": 2.0})
        self.assertIn("--astro-starless-stretch",
                      " ".join(regeln.einstellungen(regeln.pruefen(b))))
        raete = regeln.pruefen(b, bereits=["--astro-starless-stretch"])
        self.assertNotIn("--astro-starless-stretch", " ".join(regeln.einstellungen(raete)))

    def test_fremde_schalter_stoeren_nicht(self):
        raete = regeln.pruefen(BERICHT, bereits=["--astro-cosmetic", "--astro-deconv"])
        self.assertIn("--bg-extract", regeln.einstellungen(raete))


class TestPipelineReichtEsDurch(unittest.TestCase):
    """Die Regel nuetzt nichts, wenn die Pipeline die Liste nicht mitgibt."""

    def _quelle(self):
        pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core",
                            "focus_cull_stack.py")
        return io.open(pfad, encoding="utf-8").read()

    def test_die_pipeline_uebergibt_bereits(self):
        self.assertIn("bereits=_bereits", self._quelle(),
                      "die Pipeline sagt dem Regelwerk nicht, was schon gelaufen ist")

    def test_jeder_genannte_schalter_existiert(self):
        """Ein Tippfehler in der Liste faellt sonst nirgends auf — der Schalter waere einfach
        nie 'bereits gelaufen' und der Zirkel bliebe."""
        src = self._quelle()
        baum = ast.parse(src)
        vorhanden = set()
        for k in ast.walk(baum):
            if isinstance(k, ast.Call) and getattr(k.func, "attr", "") == "add_argument":
                for a in k.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        vorhanden.add(a.value)
        block = src.split("_bereits = [s for s, an in (")[1].split(") if an]")[0]
        genannt = [z.split('"')[1] for z in block.split("\n") if z.strip().startswith('("--')]
        self.assertTrue(genannt)
        fehlend = [g for g in genannt if g not in vorhanden]
        self.assertEqual(fehlend, [], "Schalter gibt es gar nicht: %s" % fehlend)


if __name__ == "__main__":
    unittest.main(verbosity=2)
