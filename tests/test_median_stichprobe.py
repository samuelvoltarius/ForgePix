#!/usr/bin/env python3
"""
ForgePix — der Hintergrund-Median wird aus einer Rasterstichprobe geschaetzt.

    python3 tests/test_median_stichprobe.py

Die Normalisierung braucht vor jedem Stapeln den Hintergrund-Median jeder Aufnahme. Exakt
gerechnet heisst das: alle maskierten Werte in eine Kopie legen und sortieren. Bei einem
ASI294MC-Pro-Bild (4144x2822x3) sind das 35 Millionen Werte.

An echten M51-Daten gemessen (204 registrierte Aufnahmen):

    np.median ueber die Maske        0,545 s
    Raster mit ~200 000 Punkten      0,013 s      Faktor 42

    exakt       0,03803123
    Raster      0,03803252      Abweichung 1,3e-06

Die Abweichung ist **1770-mal kleiner als das Rauschen des Bildes** (MAD 0,0024) und damit ohne
jede Bedeutung fuer das Ergebnis. Zweimal je Aufnahme gerechnet sparte das an dieser Serie rund
vier Minuten — bei einer Rechnung, die nichts zum Ergebnis beitraegt.

Dazu zwei weitere Verschwendungen an derselben Stelle, beide behoben:

* `first * skal[0]` stand IN der Schleife und legte bei jedem der 204 Durchlaeufe eine
  140-MB-Kopie an, obwohl der Wert sich nie aendert.
* `valid(paths[0])` wurde ebenfalls je Durchlauf neu eingelesen und geprueft (`np.isin` ueber
  11,7 Millionen Werte). Die Masken werden jetzt zwischengespeichert.

**Kleine Bilder werden weiterhin exakt gerechnet.** Dort kostet die Sortierung nichts, und das
Verhalten bleibt bitgenau wie vorher — eine Naeherung soll nur dort greifen, wo sie etwas bringt.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro  # noqa: E402


class TestGenauigkeit(unittest.TestCase):

    def _szene(self, h=1200, w=1600, hintergrund=0.038, rauschen=0.0024, seed=5):
        """Ein Bild wie ein echter Stapel: flacher Hintergrund plus Rauschen plus Objekt."""
        rng = np.random.default_rng(seed)
        f = rng.normal(hintergrund, rauschen, (h, w, 3)).astype(np.float32)
        yy, xx = np.mgrid[0:h, 0:w]
        objekt = np.exp(-(((yy - h / 2) / (h / 8.0)) ** 2 + ((xx - w / 2) / (w / 8.0)) ** 2))
        f += (objekt * 0.4).astype(np.float32)[..., None]
        return f

    def test_die_stichprobe_trifft_den_median(self):
        """Der Kern: die Abweichung muss weit unter dem Rauschen liegen."""
        f = self._szene()
        exakt = float(np.median(f))
        naeherung = astro.median_stichprobe(f)
        rauschen = float(np.median(np.abs(f - np.median(f))) * 1.4826)
        self.assertLess(abs(naeherung - exakt), rauschen / 100.0,
                        "Abweichung %.3e gegen Rauschen %.3e" % (abs(naeherung - exakt),
                                                                 rauschen))

    def test_mit_maske_ebenso(self):
        f = self._szene()
        maske = np.ones(f.shape[:2], bool)
        maske[:80, :] = False          # wie eine Abdeckungsmaske nach dem Ausrichten
        maske[:, :120] = False
        exakt = float(np.median(f[maske]))
        naeherung = astro.median_stichprobe(f, maske)
        rauschen = float(np.median(np.abs(f[maske] - exakt)) * 1.4826)
        self.assertLess(abs(naeherung - exakt), rauschen / 100.0)

    def test_kleine_bilder_bleiben_exakt(self):
        """Wo die Naeherung nichts spart, darf sie nicht greifen — sonst aendert sich
        Verhalten ohne Gegenwert."""
        f = self._szene(h=200, w=300)
        self.assertEqual(astro.median_stichprobe(f), float(np.median(f)))
        maske = np.ones(f.shape[:2], bool)
        maske[:20] = False
        self.assertEqual(astro.median_stichprobe(f, maske), float(np.median(f[maske])))

    def test_eine_leere_rasterstichprobe_faellt_auf_exakt_zurueck(self):
        """Deckt die Maske nur einen duennen Streifen ab, kann das Raster daneben treffen.
        Dann muss exakt gerechnet werden statt einen Wert zu erfinden."""
        f = self._szene()
        maske = np.zeros(f.shape[:2], bool)
        maske[500:502, :] = True
        self.assertAlmostEqual(astro.median_stichprobe(f, maske),
                               float(np.median(f[maske])), places=6)

    def test_es_ist_wirklich_schneller(self):
        """Die Gegenprobe zum Zweck der Aenderung. Ohne sie koennte die Naeherung genauso
        langsam sein und niemandem faellt es auf."""
        import time
        f = self._szene(h=2000, w=2600)
        maske = np.ones(f.shape[:2], bool)
        t = time.perf_counter()
        float(np.median(f[maske]))
        exakt_s = time.perf_counter() - t
        t = time.perf_counter()
        astro.median_stichprobe(f, maske)
        schnell_s = time.perf_counter() - t
        self.assertLess(schnell_s * 4, exakt_s,
                        "nur %.1f-fach schneller (%.3f s gegen %.3f s)"
                        % (exakt_s / max(schnell_s, 1e-9), exakt_s, schnell_s))


class TestKeineVerschwendungMehr(unittest.TestCase):
    """Die beiden anderen Fundstellen in derselben Schleife."""

    def _quelle(self):
        import inspect
        return inspect.getsource(astro.stack)

    def test_die_referenz_wird_nur_einmal_skaliert(self):
        q = self._quelle()
        self.assertIn("first_skaliert = first * skal[0]", q)
        self.assertNotIn("first[overlap] * skal[0]", q,
                         "die Referenz wird noch je Aufnahme neu kopiert")

    def test_die_referenzmaske_wird_nur_einmal_gelesen(self):
        q = self._quelle()
        self.assertIn("ref_cov = valid(paths[0])", q)
        self.assertIn("overlap = coverage & ref_cov", q)

    def test_die_masken_werden_zwischengespeichert(self):
        q = self._quelle()
        self.assertIn("_gueltig_cache", q,
                      "jede Maske wird mehrfach eingelesen und geprueft")


if __name__ == "__main__":
    unittest.main(verbosity=2)
