#!/usr/bin/env python3
"""
ForgePix — Tests für die vier kleinen Siril-Werkzeuge in core/astro.py.

    python3 tests/test_siril_klein.py     # oder: python3 -m unittest discover -s tests

`linear_match`, `unpurple`, `ddp` und `dark_skalieren`. Alle vier werden gegen eine bekannte
Wahrheit geprüft, nicht gegen sich selbst: bei `linear_match` ist die Referenz das Original, bei
`unpurple` weiß der Test, welcher Bildteil Saum und welcher echter Hα-Nebel ist, bei `ddp` steht
der Vergleich gegen eine Gamma-Streckung GLEICHER Ausbrenn-Menge, und bei `dark_skalieren` ist
das korrekt skalierte Dark analytisch bekannt.

Gemessen (Stand 05.09.2026): linear_match zieht die mittlere Abweichung von 0.130 auf 0.0005,
unpurple senkt den Magenta-Anteil von 0.0020 auf 0.0002 ohne den roten Nebel anzurühren, und DDP
erreicht bei gleicher Ausbrenn-Menge (135 gegen 134 Pixel) den 2,2-fachen Nebelkontrast einer
Gamma-Streckung (0.18 gegen 0.083).
"""
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro  # noqa: E402


def _stille(*a, **k):
    pass


def _szene(seed=3, h=200, w=200):
    """Himmel + Nebel + drei Sterne — die übliche Astro-Ausgangslage."""
    rng = np.random.default_rng(seed)
    g = np.clip(rng.normal(0.05, 0.005, (h, w)).astype(np.float32), 0, 1)
    neb = np.zeros((h, w), np.float32)
    cv2.circle(neb, (w // 2, h // 2), 40, 1.0, -1)
    g += cv2.GaussianBlur(neb, (0, 0), 20) * 0.06
    for (x, y) in [(30, 30), (160, 40), (50, 170)]:
        p = np.zeros((h, w), np.float32)
        cv2.circle(p, (x, y), 2, 1.0, -1)
        g += cv2.GaussianBlur(p, (0, 0), 2.0) * 8.0
    return np.clip(g, 0, 1)


class TestLinearMatch(unittest.TestCase):
    """Zwei Aufnahmen derselben Szene auf dieselbe Skala ziehen."""

    def setUp(self):
        rng = np.random.default_rng(3)
        self.ref = np.clip(rng.normal(0.30, 0.02, (200, 200)).astype(np.float32), 0, 1)
        self.bild = np.clip(self.ref * 0.40 + 0.05, 0, 1)      # anderer Gain, anderer Sockel

    def _abw(self, a):
        return float(np.abs(np.asarray(a, np.float32) - self.ref).mean())

    def test_pegel_und_gain_werden_zurueckgerechnet(self):
        vorher = self._abw(self.bild)
        nachher = self._abw(astro.linear_match(self.bild, self.ref))
        self.assertLess(nachher, vorher * 0.05,
                        "Anpassung greift kaum: %.5f -> %.5f" % (vorher, nachher))

    def test_ausreisser_verziehen_die_anpassung_nicht(self):
        """Genau dafür ist `robust`: ein paar helle Sterne dürfen die Gerade nicht kippen."""
        kaputt = self.bild.copy()
        kaputt[::37, ::41] = 1.0
        mit = self._abw(astro.linear_match(kaputt, self.ref, robust=True))
        ohne = self._abw(astro.linear_match(kaputt, self.ref, robust=False))
        self.assertLess(mit, ohne,
                        "robuste Anpassung nicht besser (%.5f gegen %.5f)" % (mit, ohne))

    def test_unpassende_groesse_bleibt_unveraendert(self):
        klein = np.zeros((50, 50), np.float32)
        self.assertIs(astro.linear_match(klein, self.ref), klein)
        self.assertIs(astro.linear_match(None, self.ref), None)


class TestUnpurple(unittest.TestCase):
    """Violettsaum weg, roter Nebel unberührt — das zweite ist das Schwierige."""

    def setUp(self):
        h = w = 120
        f = np.zeros((h, w, 3), np.float32)
        f[..., 2] = 0.35                                     # Hα-Nebel über das ganze Feld
        stern = np.zeros((h, w), np.float32)
        cv2.circle(stern, (60, 60), 3, 1.0, -1)
        stern = cv2.GaussianBlur(stern, (0, 0), 4.0)
        stern /= float(stern.max())
        f[..., 1] += stern * 0.60                            # G
        f[..., 0] += stern * 0.85                            # B  \ zusammen der Saum
        f[..., 2] += stern * 0.85                            # R  /
        self.f = np.clip(f, 0, 1)

    @staticmethod
    def _magenta(a):
        b, g, r = a[..., 0], a[..., 1], a[..., 2]
        return float(np.clip(np.minimum(b - g, r - g), 0, None).mean())

    def test_saum_wird_deutlich_schwaecher(self):
        vor, nach = self._magenta(self.f), self._magenta(astro.unpurple(self.f, 1.0))
        self.assertLess(nach, vor * 0.5, "Saum kaum reduziert (%.5f -> %.5f)" % (vor, nach))

    def test_roter_nebel_bleibt_unangetastet(self):
        """Der teuerste denkbare Fehlgriff wäre, Hα für einen Farbfehler zu halten."""
        out = astro.unpurple(self.f, 1.0)
        self.assertAlmostEqual(float(out[5, 5, 2]), float(self.f[5, 5, 2]), places=5)
        self.assertAlmostEqual(float(out[5, 5, 0]), float(self.f[5, 5, 0]), places=5)

    def test_staerke_null_und_graustufen_sind_identitaet(self):
        self.assertIs(astro.unpurple(self.f, 0.0), self.f)
        grau = self.f[..., 1]
        self.assertIs(astro.unpurple(grau, 1.0), grau)


class TestDDP(unittest.TestCase):
    """Okano-Kurve: schwaches Signal hoch, Sterne nicht zu Klumpen."""

    def setUp(self):
        self.g = _szene()

    @staticmethod
    def _kontrast(a):
        return float(a[90:110, 90:110].mean() - a[5:25, 5:25].mean())

    def test_hebt_den_nebel_deutlich_an(self):
        d = astro.ddp(self.g)
        self.assertGreater(self._kontrast(d), self._kontrast(self.g) * 2.0)

    def test_besser_als_gamma_bei_gleicher_ausbrennung(self):
        """Der ehrliche Vergleich: nicht gegen das Original, sondern gegen eine Streckung, die
        genauso viel ausbrennt. Gemessen 0.18 gegen 0.083."""
        d = astro.ddp(self.g)
        n_d = int((d > 0.99).sum())
        gamma = np.power(self.g, 0.20)                       # brennt gleich viel aus
        self.assertLessEqual(n_d, int((gamma > 0.99).sum()) + 5,
                             "DDP brennt mehr aus als der Vergleich — Test unfair")
        self.assertGreater(self._kontrast(d), self._kontrast(gamma) * 1.5)

    def test_kurve_ist_monoton(self):
        """Eine Tonwertkurve, die irgendwo fällt, würde Helligkeiten vertauschen."""
        rampe = np.linspace(0, 1, 500).astype(np.float32).reshape(1, -1)
        out = astro.ddp(rampe, hintergrund=0.05)[0]
        self.assertTrue(bool(np.all(np.diff(out) >= -1e-6)), "Kurve nicht monoton")

    def test_farben_bleiben_erhalten(self):
        """Angewandt wird ein Faktor auf die Helligkeit — die Farbverhältnisse bleiben."""
        bgr = np.dstack([self.g * 0.5, self.g * 0.8, self.g])
        out = astro.ddp(np.clip(bgr, 0, 1))
        h = out[100, 100]
        self.assertAlmostEqual(float(h[0] / max(float(h[2]), 1e-6)), 0.5, places=2)

    def test_staerke_null_ist_identitaet(self):
        self.assertIs(astro.ddp(self.g, staerke=0.0), self.g)


class TestDarkSkalieren(unittest.TestCase):
    """Die Falle: der Bias skaliert NICHT mit."""

    def setUp(self):
        rng = np.random.default_rng(11)
        h = w = 200
        self.bias = (np.full((h, w), 0.02, np.float32)
                     + rng.normal(0, 0.0005, (h, w)).astype(np.float32))
        # So sieht ein echtes Dark aus: die meisten Pixel fast ohne Dunkelstrom, dazu ein
        # Schwanz heißer Pixel. Ein gleichmäßiges Rauschfeld wäre hier die falsche Vorlage.
        self.strom = rng.exponential(0.004, (h, w)).astype(np.float32)
        self.strom[rng.random((h, w)) < 0.001] += 0.4
        self.dark60 = self.bias + self.strom                 # Master bei 60 s
        self.wahr120 = self.bias + self.strom * 2.0          # so sähe es bei 120 s aus

    def test_bias_wird_nicht_mitskaliert(self):
        s = astro.dark_skalieren(self.dark60, 120, 60, bias=self.bias, log=_stille)
        fehler = float(np.abs(s - self.wahr120).mean())
        naiv = float(np.abs(self.dark60 * 2.0 - self.wahr120).mean())
        self.assertLess(fehler, 1e-6, "skaliertes Dark trifft die Wahrheit nicht")
        self.assertGreater(naiv, 0.01, "naive Multiplikation wäre hier fälschlich richtig")

    def test_ohne_bias_immer_noch_deutlich_besser_als_naiv(self):
        """Ohne Bias-Frame wird der Sockel geschätzt. Gemessen: Fehler 0.0006 statt 0.020,
        also 35-mal näher an der Wahrheit als das naive Verdoppeln."""
        s = astro.dark_skalieren(self.dark60, 120, 60, log=_stille)
        geschaetzt = float(np.abs(s - self.wahr120).mean())
        naiv = float(np.abs(self.dark60 * 2.0 - self.wahr120).mean())
        self.assertLess(geschaetzt, naiv * 0.1,
                        "Schätzung kaum besser als naiv (%.6f gegen %.6f)" % (geschaetzt, naiv))

    def test_gleichmaessiger_dunkelstrom_ist_die_bekannte_grenze(self):
        """Ehrlich dokumentiert statt verschwiegen: hat KEIN Pixel wenig Dunkelstrom, liegt das
        1. Perzentil weit über dem Bias und die Schätzung greift daneben. Dann braucht es ein
        echtes Bias-Frame — mit einem trifft dieselbe Funktion exakt."""
        rng = np.random.default_rng(4)
        gleich = np.clip(rng.normal(0.03, 0.004, self.bias.shape).astype(np.float32), 0, None)
        dark, wahr = self.bias + gleich, self.bias + gleich * 2.0
        ohne = float(np.abs(astro.dark_skalieren(dark, 120, 60, log=_stille) - wahr).mean())
        mit = float(np.abs(astro.dark_skalieren(dark, 120, 60, bias=self.bias,
                                                log=_stille) - wahr).mean())
        self.assertGreater(ohne, 0.005, "Grenze verschwunden — Kommentar prüfen")
        self.assertLess(mit, 1e-6, "mit Bias muss es exakt sein")

    def test_temperatur_verdoppelt_je_sechs_grad(self):
        s = astro.dark_skalieren(self.dark60, 60, 60, bias=self.bias,
                                 ziel_temp=-4.0, dark_temp=-10.0, log=_stille)
        self.assertLess(float(np.abs(s - self.wahr120).mean()), 1e-6)

    def test_unsinnige_zeiten_geben_das_dark_zurueck(self):
        for args in ((0, 60), (60, 0), ("x", 60)):
            with self.subTest(args=args):
                out = astro.dark_skalieren(self.dark60, args[0], args[1], log=_stille)
                self.assertTrue(np.array_equal(out, self.dark60))
        self.assertIsNone(astro.dark_skalieren(None, 120, 60, log=_stille))

    def test_ergebnis_wird_nicht_negativ(self):
        s = astro.dark_skalieren(self.dark60, 10, 60, bias=self.bias, log=_stille)
        self.assertGreaterEqual(float(s.min()), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
