#!/usr/bin/env python3
"""
ForgePix — der Messbericht muss dunkle Hoefe um die Sterne bemerken.

    python3 tests/test_sternhoefe.py

Der lehrreichste Fund dieses Tages. Ein M51-Stapel mit `--astro-deconv` bekam um **jeden**
Stern einen schwarzen Ring; die Sterne sahen aus wie Blaeschen. Der Messbericht meldete fuer
genau diesen Lauf lauter bessere Zahlen:

    Signal/Rauschen    5,4  ->  7,5
    Himmelsrauschen    0,00054 -> 0,00038
    Gradient           7,9 %  ->  6,8 %
    FWHM               1,98 -> 1,99 px
    Sterne             2000 -> 2000

Gemessen wurde alles ausser dem, was kaputtging. Nichts schlug fehl, und der Bericht empfahl
nichts — er lobte.

**Der Mechanismus.** Richardson-Lucy schiebt Licht aus den Sternflanken in den Kern und nimmt es
dem Umfeld weg. Im LINEAREN Bild ist das winzig: -0,00217 bei einem Himmelspegel von 0,0381.
Die Streckung ist nahe Null fast senkrecht und macht daraus Schwarz — im fertigen JPG lag der
Ring bei jedem gemessenen Stern auf 0,000, die Ringtiefe im Median bei -0,114 gegen +0,034 ohne
Dekonvolution.

**Regularisierung hilft nicht.** Gemessen mit reg = 0 / 0,02 / 0,05 / 0,1 blieb die Ringtiefe
bei -0,0019. Der Fehler ist nicht zu wenig Glaettung, sondern dass ueberhaupt Licht aus dem
Himmel genommen wird. Der Riegel ist darum eine Untergrenze: das Ergebnis darf nirgends unter
das Minimum aus Originalpixel und Hintergrundflaeche fallen.

**Und die Schwelle muss relativ sein.** Der erste Anlauf nahm die -0,005 aus dem GESTRECKTEN
Bild als absolute Schranke — am linearen Stapel mit -0,00217 waere die Regel nie angesprungen.
Bezogen auf den Himmelspegel sind es in beiden Faellen rund -6 %.
"""
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import messbericht  # noqa: E402
import regeln  # noqa: E402
import astro  # noqa: E402


def _sternfeld(hof=0.0, h=420, w=560, himmel=0.038, rauschen=0.0004, seed=7):
    """Sternfeld mit einstellbarem dunklem Hof — `hof` als Anteil des Himmelspegels."""
    rng = np.random.default_rng(seed)
    g = rng.normal(himmel, rauschen, (h, w)).astype(np.float32)
    punkte = np.zeros((h, w), np.float32)
    stellen = []
    for _ in range(70):
        y, x = int(rng.integers(20, h - 20)), int(rng.integers(20, w - 20))
        stellen.append((y, x))
        punkte[y, x] += float(rng.uniform(2, 40))
    g += cv2.GaussianBlur(punkte, (0, 0), 1.8)
    if hof:
        # Ein Ring in 5..11 px Abstand, so wie ihn die Dekonvolution erzeugt.
        yy, xx = np.mgrid[-14:15, -14:15]
        r = np.hypot(yy, xx)
        kern = np.where((r > 5) & (r < 11), 1.0, 0.0).astype(np.float32)
        marken = np.zeros((h, w), np.float32)
        for y, x in stellen:
            marken[y - 14:y + 15, x - 14:x + 15] = np.maximum(
                marken[y - 14:y + 15, x - 14:x + 15], kern)
        g = g - cv2.GaussianBlur(marken, (0, 0), 1.2) * (abs(hof) * himmel)
    return np.clip(np.dstack([g] * 3), 0, 1).astype(np.float32)


class TestMessung(unittest.TestCase):

    def test_ein_sauberes_feld_hat_keinen_hof(self):
        r = messbericht._ringe(_sternfeld(hof=0.0))
        self.assertIsNotNone(r, "die Messung findet keine geeigneten Sterne")
        self.assertGreater(r, -0.02, "ohne Hof darf nichts gemeldet werden: %.4f" % r)

    def test_ein_hof_wird_gemessen(self):
        r = messbericht._ringe(_sternfeld(hof=0.35))
        self.assertIsNotNone(r)
        self.assertLess(r, -0.05, "der Hof wird nicht erkannt: %.4f" % r)

    def test_der_wert_ist_relativ_zum_himmel(self):
        """Sonst haengt die Schwelle daran, wie hell der Himmel zufaellig war — und genau
        daran ist der erste Anlauf gescheitert."""
        hell = messbericht._ringe(_sternfeld(hof=0.35, himmel=0.038))
        dunkel = messbericht._ringe(_sternfeld(hof=0.35, himmel=0.0038, rauschen=0.00004))
        self.assertIsNotNone(hell)
        self.assertIsNotNone(dunkel)
        self.assertAlmostEqual(hell, dunkel, delta=0.05,
                               msg="der Wert haengt am Himmelspegel: %.3f gegen %.3f"
                                   % (hell, dunkel))

    def test_ohne_sterne_wird_nichts_erfunden(self):
        """Eine Nicht-Messung ist kein Befund."""
        flach = np.full((300, 300, 3), 0.04, np.float32)
        self.assertIsNone(messbericht._ringe(flach))


class TestRegel(unittest.TestCase):

    def test_der_hof_wird_beanstandet(self):
        titel = [r.titel for r in regeln.pruefen({"ringtiefe": -0.10})]
        self.assertIn("Dunkle Hoefe um die Sterne", titel)

    def test_ein_leichter_saum_ebenfalls(self):
        titel = [r.titel for r in regeln.pruefen({"ringtiefe": -0.056})]
        self.assertIn("Ansatz von Hoefen um die Sterne", titel)

    def test_ohne_hof_schweigt_die_regel(self):
        """Die Gegenprobe — sonst beanstandete sie jeden Stapel."""
        for wert in (0.001, 0.0, -0.01):
            with self.subTest(wert=wert):
                titel = " ".join(r.titel for r in regeln.pruefen({"ringtiefe": wert}))
                self.assertNotIn("Hoefe", titel)

    def test_eine_fehlende_messung_loest_nichts_aus(self):
        titel = " ".join(r.titel for r in regeln.pruefen({"ringtiefe": None}))
        self.assertNotIn("Hoefe", titel)

    def test_die_regel_empfiehlt_nicht_die_regularisierung(self):
        """Sie hilft nachweislich nicht — an echten Daten blieb die Ringtiefe von reg=0 bis
        reg=0,1 unveraendert. Ein Rat, der nichts bewirkt, ist schlimmer als keiner."""
        r = [x for x in regeln.pruefen({"ringtiefe": -0.10})
             if x.titel == "Dunkle Hoefe um die Sterne"][0]
        self.assertIsNone(r.einstellung)
        self.assertIn("NICHT", r.massnahme + r.grund)


class TestRiegelInDerDekonvolution(unittest.TestCase):

    def test_die_dekonvolution_drueckt_nicht_unter_den_himmel(self):
        feld = _sternfeld(hof=0.0)
        aus = astro.deconvolve(feld.copy(), iterations=12, deringing=True,
                               log=lambda *a, **k: None)
        r = messbericht._ringe(aus)
        self.assertIsNotNone(r)
        self.assertGreater(r, -0.03, "mit Riegel bleibt ein Hof: %.4f" % r)

    def test_ohne_riegel_ist_der_hof_da(self):
        """Die Gegenprobe: ohne den Riegel muss der Unterschwinger messbar sein, sonst
        prueft der Test oben nichts."""
        feld = _sternfeld(hof=0.0)
        mit = messbericht._ringe(astro.deconvolve(feld.copy(), iterations=12, deringing=True,
                                                  log=lambda *a, **k: None))
        ohne = messbericht._ringe(astro.deconvolve(feld.copy(), iterations=12, deringing=False,
                                                   log=lambda *a, **k: None))
        self.assertIsNotNone(ohne)
        self.assertLess(ohne, mit,
                        "der Riegel macht keinen Unterschied (%.4f gegen %.4f)" % (ohne, mit))


class TestImBericht(unittest.TestCase):

    def test_die_ringtiefe_steht_im_bericht(self):
        b = messbericht.erstellen(_sternfeld(hof=0.35), log=lambda *a, **k: None)
        self.assertIn("ringtiefe", b)
        self.assertIsNotNone(b["ringtiefe"])

    def test_und_im_textblock(self):
        b = messbericht.erstellen(_sternfeld(hof=0.35), log=lambda *a, **k: None)
        text = messbericht.text(b)
        self.assertIn("Sternhoefe", text)
        self.assertIn("ACHTUNG", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
