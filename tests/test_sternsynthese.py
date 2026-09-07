#!/usr/bin/env python3
"""
ForgePix — Tests für die Sternsynthese (core/sternsynthese.py).

    python3 tests/test_sternsynthese.py

Das Modul erzeugt Trainingspaare für die Sternentfernung. Der springende Punkt ist, dass die
Maske **nicht gesucht, sondern gewusst** wird: die Sterne werden gerechnet, also ist beim
Anlegen bekannt, wo sie sind. Damit entfällt der Zirkelschluss, an dem der naheliegende Weg
scheitert — eine Maske aus der Sternerkennung zu gewinnen, um damit ein Modell zu trainieren,
das die Sternerkennung ersetzen soll.

An echten Daten gemessen (Ausschnitt aus M27, ASI294MC Pro):
    Wahrheit bitgleich unverändert
    Unterschied mit/ohne Sterne: 0,000290 innerhalb der Maske, 0,000001 ausserhalb — 511:1
    Helligkeitsverteilung 150 / 76 / 40 / 7 / 1 über die Schwellen 0,02 / 0,05 / 0,1 / 0,3 / 0,6
"""
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro            # noqa: E402
import sternsynthese    # noqa: E402


def _stille(*a, **k):
    pass


def _untergrund(h=260, w=340, seed=4, sterne=0):
    """Sternarme Szene: Himmel plus etwas Nebelstruktur."""
    rng = np.random.default_rng(seed)
    g = np.clip(rng.normal(0.030, 0.0012, (h, w)).astype(np.float32), 0, 1)
    k = np.zeros((h, w), np.float32)
    cv2.circle(k, (w // 2, h // 2), 60, 1.0, -1)
    g += cv2.GaussianBlur(k, (0, 0), 28) * 0.04
    for _ in range(sterne):
        x, y = int(rng.integers(15, w - 15)), int(rng.integers(15, h - 15))
        p = np.zeros((h, w), np.float32)
        p[y, x] = 1.0
        g += cv2.GaussianBlur(p, (0, 0), 1.6) * float(rng.uniform(3, 8))
    return np.dstack([np.clip(g, 0, 1)] * 3).astype(np.float32)


class TestWahrheit(unittest.TestCase):
    """Der ganze Zweck: die Wahrheit muss exakt sein, nicht geschätzt."""

    def test_untergrund_bleibt_unveraendert(self):
        u = _untergrund()
        mit, ohne, maske, sterne = sternsynthese.paar_erzeugen(u, anzahl=60, seed=1, log=_stille)
        self.assertTrue(np.array_equal(ohne, np.clip(u, 0, 1)),
                        "die Wahrheit wurde veraendert — dann ist sie keine mehr")

    def test_unterschied_liegt_in_der_maske(self):
        """Wenn die Maske stimmt, passiert ausserhalb von ihr praktisch nichts."""
        u = _untergrund()
        mit, ohne, maske, _ = sternsynthese.paar_erzeugen(u, anzahl=80, seed=2, log=_stille)
        d = np.abs(astro._gray(mit) - astro._gray(ohne))
        drin = float(d[maske > 0.5].mean())
        draussen = float(d[maske < 0.5].mean())
        self.assertGreater(drin, draussen * 50,
                           "in der Maske %.7f, ausserhalb %.7f" % (drin, draussen))

    def test_maske_ist_nicht_leer_und_nicht_alles(self):
        u = _untergrund()
        _, _, maske, _ = sternsynthese.paar_erzeugen(u, anzahl=80, seed=3, log=_stille)
        anteil = float(maske.mean())
        self.assertGreater(anteil, 0.001, "Maske praktisch leer")
        self.assertLess(anteil, 0.35, "Maske deckt fast alles ab — dann ist sie wertlos")

    def test_mehr_sterne_groessere_maske(self):
        u = _untergrund()
        _, _, m1, s1 = sternsynthese.paar_erzeugen(u, anzahl=40, seed=5, log=_stille)
        _, _, m2, s2 = sternsynthese.paar_erzeugen(u, anzahl=160, seed=5, log=_stille)
        self.assertGreater(len(s2), len(s1))
        self.assertGreater(float(m2.mean()), float(m1.mean()))


class TestSternfeld(unittest.TestCase):

    def test_helligkeit_folgt_einem_potenzgesetz(self):
        """Am Himmel gibt es wenige helle und viele schwache Sterne. Gleichverteilt gewuerfelt
        entstuende ein Feld, das es nicht gibt — und ein Modell, das nur mittelhelle kennt."""
        u = _untergrund()
        _, _, _, sterne = sternsynthese.paar_erzeugen(u, anzahl=300, seed=6, log=_stille)
        fl = np.array([s[2] for s in sterne])
        schwach = int((fl < 0.1).sum())
        hell = int((fl >= 0.3).sum())
        self.assertGreater(schwach, hell * 3,
                           "schwach %d, hell %d — das ist keine Himmelsverteilung"
                           % (schwach, hell))

    def test_gleicher_seed_gleiches_feld(self):
        """Reproduzierbarkeit: ohne sie laesst sich ein Trainingslauf nicht wiederholen."""
        u = _untergrund()
        a = sternsynthese.paar_erzeugen(u, anzahl=50, seed=9, log=_stille)
        b = sternsynthese.paar_erzeugen(u, anzahl=50, seed=9, log=_stille)
        self.assertTrue(np.array_equal(a[0], b[0]))
        self.assertEqual(a[3], b[3])

    def test_sterne_liegen_im_bild(self):
        u = _untergrund()
        h, w = u.shape[:2]
        _, _, _, sterne = sternsynthese.paar_erzeugen(u, anzahl=100, seed=11, log=_stille)
        for x, y, _f in sterne:
            self.assertTrue(0 <= x < w and 0 <= y < h)

    def test_uebergebene_psf_wird_benutzt(self):
        """Eine breitere PSF muss sichtbar breitere Sterne ergeben — sonst wird sie ignoriert."""
        u = _untergrund()
        schmal = astro._moffat_kern(10, 2.0)
        breit = astro._moffat_kern(10, 6.0)
        _, _, m_schmal, _ = sternsynthese.paar_erzeugen(u, psf=schmal, anzahl=60, seed=13,
                                                        log=_stille)
        _, _, m_breit, _ = sternsynthese.paar_erzeugen(u, psf=breit, anzahl=60, seed=13,
                                                       log=_stille)
        self.assertGreater(float(m_breit.mean()), float(m_schmal.mean()) * 1.3,
                           "breite PSF %.4f, schmale %.4f" % (float(m_breit.mean()),
                                                              float(m_schmal.mean())))


class TestReststerne(unittest.TestCase):
    """Die ehrliche Grenze: der Untergrund ist nie ganz sternlos."""

    def test_sternreicher_untergrund_wird_als_solcher_gemeldet(self):
        sauber = sternsynthese.reststerne(_untergrund(sterne=0))
        voll = sternsynthese.reststerne(_untergrund(sterne=60))
        self.assertGreater(voll, sauber,
                           "sternreich %.2f %%, sternarm %.2f %%" % (voll, sauber))


if __name__ == "__main__":
    unittest.main(verbosity=2)
