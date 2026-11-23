"""Sigma/Winsor-Stapeln in Streifen (astro.stack) rechnet wie der alte Weg über ganze Bilder.

Gemessen am 24.11.2026 an 28 Seestar-Aufnahmen (IC 5146, 1080x1920): das Stapeln brauchte 30 s,
Siril für Ausrichten UND Stapeln 5 s. Ursache: jede Datei wurde viermal komplett gelesen und
jedes Mal als ganzes Bild in Float64 durchgerechnet. Der Streifenweg liest jede Datei einmal.
Er darf dabei nichts anders rechnen — derselbe Satz Aufnahmen geht einmal als zeilenweise
lesbares TIFF (Streifenweg) und einmal komprimiert (alter Weg) durch, mit Ausreißern, einer
Satellitenspur, Rändern ohne Abdeckung und gemischten Belichtungszeiten.
"""
import os
import sys
import tempfile
import unittest

import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, "..", "core"))

import astro  # noqa: E402


def _still(*a, **k):
    pass


def _satz(ordner, komprimiert, n=12, h=70, w=90, seed=5):
    import tifffile
    rng = np.random.default_rng(seed)
    himmel = np.full((h, w, 3), 0.05, np.float32)
    himmel[30:34, 40:44] += 0.6                               # ein Stern
    pfade = []
    for i in range(n):
        f = himmel + rng.normal(0, 0.01, himmel.shape).astype(np.float32) + 0.002 * i
        if i == 3:
            f[10, :, :] += 0.8                                # Satellitenspur
        if i == 7:
            f[50, 60] = 1.0                                   # kosmischer Treffer
        cov = np.ones((h, w), np.uint8)
        cov[:, : (i % 4) * 3] = 0                             # unterschiedlich belegte Ränder
        p = os.path.join(ordner, "reg_%02d.tif" % i)
        tifffile.imwrite(p, np.ascontiguousarray(f[..., ::-1]),
                         compression="zlib" if komprimiert else None)
        tifffile.imwrite(p + ".coverage.tif", cov)
        pfade.append(p)
    return pfade


class TestStreifenGleichAltemWeg(unittest.TestCase):
    def _beide(self, **kw):
        log_neu, log_alt = [], []
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            neu = astro.stack(_satz(a, False), log=log_neu.append, return_info=True, **kw)
            alt = astro.stack(_satz(b, True), log=log_alt.append, return_info=True, **kw)
        # sicherstellen, dass wirklich ZWEI Wege verglichen werden
        self.assertTrue(any("Rejection Zeilen" in z for z in log_neu), log_neu[-3:])
        self.assertFalse(any("Rejection Zeilen" in z for z in log_alt), log_alt[-3:])
        return neu, alt

    def _vergleichen(self, **kw):
        (r_neu, i_neu), (r_alt, i_alt) = self._beide(**kw)
        self.assertEqual(r_neu.shape, r_alt.shape)
        self.assertLess(float(np.abs(r_neu - r_alt).max()), 1e-6, kw)
        self.assertTrue(np.array_equal(i_neu["coverage"], i_alt["coverage"]))
        self.assertLess(float(np.abs(i_neu["beitraege"] - i_alt["beitraege"]).max()), 1e-4)
        return r_neu

    def test_sigma(self):
        r = self._vergleichen(method="sigma", kappa=2.5)
        self.assertLess(float(r[10, 30:, 1].mean()), 0.08)    # Spur verworfen

    def test_sigma_einpass_und_gewichtet(self):
        self._vergleichen(method="sigma", kappa=3.0, sigma_iters=1, weight=True)

    def test_winsor(self):
        self._vergleichen(method="winsor", kappa=2.0)

    def test_gemischte_belichtung(self):
        self._vergleichen(method="sigma", kappa=2.5, belichtungen=[30, 60] * 6)

    def test_gegenprobe_der_vergleich_faellt(self):
        """Ein Test, der immer grün ist, prüft nichts: anderes kappa muss auffallen."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            neu = astro.stack(_satz(a, False), method="sigma", kappa=1.0, log=_still)
            alt = astro.stack(_satz(b, True), method="sigma", kappa=3.0, log=_still)
        self.assertGreater(float(np.abs(neu - alt).max()), 1e-3)


if __name__ == "__main__":
    unittest.main()
