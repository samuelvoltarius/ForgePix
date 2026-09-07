#!/usr/bin/env python3
"""
ForgePix — die Sub-Bewertung und ihre Platzhalter (core/astro_quality.py).

    python3 tests/test_sub_auswahl.py

`analyze_frame` setzt für eine Aufnahme ohne gefundene Sterne die Platzhalter **FWHM 99,0** und
**Exzentrizität 9,0**. Das heißt „nicht gemessen", nicht „sehr unscharf". Diese Werte gingen in
die Mediane ein, an denen die Schwellen hängen — und schalteten damit genau die Prüfungen ab,
die gebraucht werden:

* Bei 6 bewölkten von 8 Aufnahmen wurde der Sternzahl-Median **0**, und die Bedingung
  `med_stars > 0` war nie erfüllt.
* Der FWHM-Median wurde **99,0**, und `99 > 1,5 × 99` ist nie wahr.

Die bewölkten Aufnahmen fielen dann nur noch über die Exzentrizität heraus — also **durch
Zufall**, weil der Platzhalter 9,0 zufällig über der Schwelle 1,7 liegt. Wäre er 1,0, wären alle
sechs im Stapel gelandet. Und die genannte Begründung war falsch: „längliche Sterne
(Elongation 9,00) — Guidingfehler" für eine Aufnahme, die gar keine Sterne hat.
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro_quality  # noqa: E402
from constants import imwrite  # noqa: E402


def _stille(*a, **k):
    pass


class TestSubAuswahl(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_sel_")
        self.rng = np.random.default_rng(7)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _szene(self, sterne, unschaerfe=1.6, name="x"):
        h = w = 200
        g = np.full((h, w), 0.03, np.float32)
        for _ in range(sterne):
            p = np.zeros((h, w), np.float32)
            p[int(self.rng.integers(15, h - 15)), int(self.rng.integers(15, w - 15))] = 1.0
            g += cv2.GaussianBlur(p, (0, 0), unschaerfe) * float(self.rng.uniform(3, 9))
        g = np.clip(g + self.rng.normal(0, 0.002, (h, w)).astype(np.float32), 0, 1)
        q = os.path.join(self.d, name + ".tif")
        imwrite(q, np.clip(np.dstack([g] * 3) * 65535, 0, 65535).astype(np.uint16))
        return q

    def _namen(self, frames, behalten):
        return sorted(os.path.basename(p) for p in behalten)

    def test_sternlose_aufnahme_bekommt_den_richtigen_grund(self):
        """Vorher stand dort "laengliche Sterne (Elongation 9,00) — Guidingfehler" fuer eine
        Aufnahme, die ueberhaupt keine Sterne hat. Eine falsche Diagnose ist schlimmer als
        keine: sie schickt den Benutzer die Nachfuehrung pruefen, obwohl Wolken schuld sind."""
        pfade = [self._szene(40, name="gut_%d" % i) for i in range(4)]
        pfade.append(self._szene(0, name="wolke"))
        frames, _behalten = astro_quality.select_subs(pfade, log=_stille)
        wolke = [f for f in frames if f["name"].startswith("wolke")][0]
        grund = "; ".join(wolke["reasons"])
        self.assertIn("keine Sterne", grund)
        self.assertNotIn("Guidingfehler", grund,
                         "eine sternlose Aufnahme ist kein Guidingfehler")

    def test_unschaerfe_wird_erkannt_obwohl_die_mehrheit_sternlos_ist(self):
        """Der eigentliche Fehler. Mit den Platzhaltern im Median lag der FWHM-Median bei 99,0
        und die Bedingung `99 > 1,5*99` war nie wahr — die unscharfen Aufnahmen kamen durch."""
        pfade = [self._szene(40, 1.5, name="scharf_%d" % i) for i in range(2)]
        pfade += [self._szene(40, 6.0, name="matsch_%d" % i) for i in range(2)]
        pfade += [self._szene(0, name="wolke_%d" % i) for i in range(6)]
        frames, behalten = astro_quality.select_subs(pfade, log=_stille)
        namen = self._namen(frames, behalten)
        self.assertTrue(all(n.startswith("scharf") for n in namen),
                        "unscharfe oder sternlose Aufnahmen wurden behalten: %s" % namen)
        matsch = [f for f in frames if f["name"].startswith("matsch")]
        self.assertTrue(all(f["reasons"] for f in matsch),
                        "eine unscharfe Aufnahme wurde ohne Beanstandung behalten")
        # Der Beleg, dass der Median jetzt aus Aufnahmen MIT Sternen kommt: keine Begruendung
        # nennt mehr den Platzhalter 99,0 als Vergleichswert. Vorher stand dort "FWHM 99.0 vs.
        # 99.0" — oder die Pruefung schwieg ganz.
        alle_gruende = "; ".join(g for f in frames for g in f["reasons"])
        self.assertNotIn("vs. 99.0", alle_gruende,
                         "der Platzhalter steckt noch im Vergleichswert: %s" % alle_gruende)

    def test_alle_sternlos_stuerzt_nicht_ab(self):
        """Dann gibt es keinen Bezug — es darf trotzdem nichts explodieren, und behalten wird
        nichts."""
        pfade = [self._szene(0, name="w_%d" % i) for i in range(4)]
        frames, behalten = astro_quality.select_subs(pfade, log=_stille)
        self.assertEqual(behalten, [])
        self.assertEqual(len(frames), 4)

    def test_gute_serie_bleibt_vollstaendig(self):
        """Die Gegenprobe: eine saubere Serie darf nichts verlieren."""
        pfade = [self._szene(40, name="gut_%d" % i) for i in range(6)]
        _frames, behalten = astro_quality.select_subs(pfade, log=_stille)
        self.assertEqual(len(behalten), 6)

    def test_platzhalter_sind_noch_die_erwarteten(self):
        """Wenn `analyze_frame` andere Platzhalter setzt, gilt die Begruendung oben nicht mehr
        — dann muss dieser Test auffallen und nicht die Auswahl still danebenliegen."""
        f = astro_quality.analyze_frame(self._szene(0, name="leer"))
        self.assertEqual(f["stars"], 0)
        self.assertEqual(f["fwhm"], 99.0)
        self.assertEqual(f["ecc"], 9.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
