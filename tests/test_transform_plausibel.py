#!/usr/bin/env python3
"""
ForgePix — die Ausrichtung muss gegen die Physik geprueft werden, nicht nur gegen sich selbst.

    python3 tests/test_transform_plausibel.py

`_estimate_star_transform_robust` nahm jede Abbildung an, sobald RANSAC drei Punktpaare fand:

    if M is not None and (inl is None or int(inl.sum()) >= 3):
        return M.astype(np.float32)

Drei zusammenpassende Paare findet man in zwei Sternfeldern fast immer zufaellig. Das Ergebnis
war darum keine Absage, sondern ein **erfundener Treffer** — und der ist gefaehrlicher als ein
Fehlschlag, weil er sich wie ein Erfolg meldet. An echten Daten gemessen (Seestar S30 mit
3,99 "/px gegen ASI533MC Pro mit 0,776 "/px, Massstabsverhaeltnis 5,14):

    ASI533 -> Seestar, direkt        "ok", Massstab 0,5826 — erwartet war 0,195
    Seestar -> ASI533, direkt        keine Ausrichtung
    dieselben Daten vorskaliert      4 von 4 "ok", Restmassstab 3,0524 / 0,9963 / 2,7183 / 4,2369

Also **eine richtige Ausrichtung und drei erfundene**, alle ununterscheidbar gemeldet.

Die Lehre ist dieselbe wie bei der Kometen-Bahnpruefung, nur andersherum. Dort leitete die
Pruefung ihre Toleranz aus der geprueften Groesse ab und hob damit ihre eigene Schwelle an. Hier
prueft das Verfahren nur seine **innere** Konsistenz (passen die Inlier zueinander?) und faellt
auf eine in sich stimmige Erfindung herein. Beide Male fehlt ein Bezug von aussen: bei gleicher
Ausruestung ist der erwartete Massstab 1,0, ueber verschiedene Optiken kommt er aus den
Kopfdaten (206,265 * Pixelgroesse[um] / Brennweite[mm]).
"""
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro  # noqa: E402


def _M(massstab=1.0, winkel_grad=0.0, tx=0.0, ty=0.0):
    w = math.radians(winkel_grad)
    return np.array([[massstab * math.cos(w), -massstab * math.sin(w), tx],
                     [massstab * math.sin(w), massstab * math.cos(w), ty]], np.float32)


class TestGemesseneFaelle(unittest.TestCase):
    """Genau die Zahlen, die der Kamera-Versuch geliefert hat."""

    def test_die_richtige_ausrichtung_wird_angenommen(self):
        ok, grund = astro.transform_plausibel(_M(0.9963))
        self.assertTrue(ok, grund)

    def test_die_drei_erfundenen_werden_verworfen(self):
        for massstab in (3.0524, 2.7183, 4.2369):
            with self.subTest(massstab=massstab):
                ok, grund = astro.transform_plausibel(_M(massstab))
                self.assertFalse(ok, "Massstab %.4f wurde angenommen" % massstab)
                self.assertIn("Massstab", grund)

    def test_der_direkte_kamera_wechsel_wird_verworfen(self):
        """ASI533 -> Seestar: erwartet 0,195 aus den Kopfdaten, geliefert wurde 0,5826."""
        ok, _ = astro.transform_plausibel(_M(0.5826), erwarteter_massstab=0.195)
        self.assertFalse(ok)

    def test_mit_richtigem_erwartungswert_geht_der_kamera_wechsel_durch(self):
        """Die Gegenprobe: waere die Abbildung richtig gewesen, duerfte sie nicht scheitern."""
        ok, grund = astro.transform_plausibel(_M(0.195), erwarteter_massstab=0.195)
        self.assertTrue(ok, grund)


class TestNormalfallBleibtHeil(unittest.TestCase):
    """Eine Pruefung, die den Alltag kaputt macht, ist schlimmer als keine."""

    def test_feldrotation_ist_kein_grund_zum_verwerfen(self):
        """Der Seestar steht azimutal — Bildfeldrotation ist der Normalfall, nicht die
        Ausnahme. Die Pruefung darf ausschliesslich den Massstab beurteilen."""
        for winkel in (0, 1, 8, 45, 90, 179):
            with self.subTest(winkel=winkel):
                ok, grund = astro.transform_plausibel(_M(1.0, winkel))
                self.assertTrue(ok, "%d Grad verworfen: %s" % (winkel, grund))

    def test_grosse_verschiebung_stoert_nicht(self):
        ok, grund = astro.transform_plausibel(_M(1.0, 3.0, tx=500, ty=-300))
        self.assertTrue(ok, grund)

    def test_leichte_massstabsdrift_geht_durch(self):
        """Temperatur und Fokus aendern den Massstab um Bruchteile eines Prozents. Bis 15 %
        wird angenommen — das ist reichlich und verwirft trotzdem jeden der gemessenen
        Fehltreffer (der kleinste lag bei 172 %% daneben)."""
        for s in (0.92, 0.98, 1.0, 1.02, 1.10):
            with self.subTest(massstab=s):
                self.assertTrue(astro.transform_plausibel(_M(s))[0])


class TestKennwerte(unittest.TestCase):

    def test_massstab_und_winkel_werden_richtig_zerlegt(self):
        sx, sy, scherung = astro.transform_kennwerte(_M(2.5, 30.0))
        self.assertAlmostEqual(sx, 2.5, places=5)
        self.assertAlmostEqual(sy, 2.5, places=5)
        self.assertAlmostEqual(scherung, 0.0, places=5)

    def test_scherung_wird_erkannt(self):
        """Nur bei voller Affine moeglich — dort ist eine verzogene Abbildung ein Zeichen
        dafuer, dass die Korrespondenzen nicht stimmen.

        Beide Spalten haben hier absichtlich die Laenge 1, sonst faellt schon die
        Massstabspruefung darauf und die Scherungspruefung waere gar nicht geprueft. (Genau
        das ist beim ersten Anlauf dieses Tests passiert.)
        """
        w = math.radians(60.0)
        M = np.array([[1.0, math.cos(w), 0.0], [0.0, math.sin(w), 0.0]], np.float32)
        sx, sy, scherung = astro.transform_kennwerte(M)
        self.assertAlmostEqual(sx, 1.0, places=5)
        self.assertAlmostEqual(sy, 1.0, places=5)
        self.assertAlmostEqual(scherung, 0.5, places=5)
        ok, grund = astro.transform_plausibel(M, max_scherung=0.2)
        self.assertFalse(ok)
        self.assertIn("Scherung", grund)
        # Gegenprobe: mit grosszuegiger Schranke geht dieselbe Matrix durch — die Absage kam
        # also wirklich von der Scherung und nicht nebenbei vom Massstab.
        self.assertTrue(astro.transform_plausibel(M, max_scherung=0.9)[0])

    def test_kaputte_eingaben_gehen_nicht_durch(self):
        self.assertFalse(astro.transform_plausibel(None)[0])
        self.assertFalse(astro.transform_plausibel(_M(float("nan")))[0])
        self.assertFalse(astro.transform_plausibel(_M(1.0), erwarteter_massstab=0.0)[0])


class TestInDerRegistrierung(unittest.TestCase):

    def test_die_pruefung_haengt_wirklich_im_weg(self):
        import inspect
        quelle = inspect.getsource(astro._estimate_star_transform_robust)
        self.assertIn("transform_plausibel", quelle,
                      "die robuste Ausrichtung prueft ihr Ergebnis nicht")
        self.assertIn("erwarteter_massstab", inspect.signature(
            astro._estimate_star_transform_robust).parameters)


if __name__ == "__main__":
    unittest.main(verbosity=2)
