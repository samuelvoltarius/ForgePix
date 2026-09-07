#!/usr/bin/env python3
"""
ForgePix — die Dekonvolution darf keine Ringe um die Sterne legen.

    python3 tests/test_dekonvolution_ringe.py

Richardson-Lucy schwingt an hellen Punktquellen: erst ein Graben (Unterschwinger), dann ein
Wall (Ueberschwinger). Im linearen Bild ist beides winzig, die Streckung ist nahe Null aber
fast senkrecht und macht daraus einen sichtbaren Ring um JEDEN Stern.

Am M51-Stapel gemessen, Ueberschuss ueber den Himmelspegel:

    r:        4      5      6      7      8      9     10     11     12     13
    ohne  +0.187 +0.082 +0.038 +0.019 +0.010 +0.007 +0.005 +0.003 +0.003 +0.002
    mit   +0.073 +0.005 +0.004 +0.004 +0.004 +0.004 +0.011 +0.024 +0.026 +0.017

Ohne Dekonvolution faellt das Profil monoton. Mit ihr sitzt bei r=11 ein Wall, achtmal so
hoch; nach der Streckung das 2,5-fache der Himmelshelligkeit.

Der Stern-Schutz half dagegen nicht, aus zwei Gruenden: er griff erst ab Helligkeit 0,85
(am M51-Stapel lagen darueber NEUN Bereiche im ganzen Bild, groesster 86 px, bei ueber 2000
Sternen), und er deckte nur den Kern ab (Radius 3-4 px), waehrend der Wall bei 10-13 px sitzt.

Zwei Faelle werden geprueft, und der zweite ist der wichtigere:

1. MIT Schutz darf kein Wall entstehen.
2. OHNE Schutz MUSS einer entstehen — sonst wuerde dieser Test auch bestehen, wenn die
   Dekonvolution abgeschaltet waere oder gar nichts taete.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro  # noqa: E402


HIMMEL = 0.04


def _sternfeld(seed=7, groesse=420, anzahl=40):
    """Ein kuenstliches Sternfeld: Punktquellen, mit einer PSF verschmiert, plus Rauschen.

    Ohne die Verschmierung haette die Dekonvolution nichts zu tun und wuerde nichts tun —
    der Test wuerde dann aus dem falschen Grund bestehen.
    """
    import cv2
    rng = np.random.default_rng(seed)
    bild = np.zeros((groesse, groesse), np.float32)
    orte = []
    rand = 30
    while len(orte) < anzahl:
        y, x = int(rng.integers(rand, groesse - rand)), int(rng.integers(rand, groesse - rand))
        if any(abs(y - a) < 34 and abs(x - b) < 34 for a, b in orte):
            continue          # Sterne auseinanderhalten, sonst ueberlagern sich die Profile
        orte.append((y, x))
        bild[y, x] += float(rng.uniform(3.0, 9.0))
    bild = cv2.GaussianBlur(bild, (0, 0), 1.8)        # Seeing
    bild += HIMMEL
    bild += rng.normal(0, 0.0006, bild.shape).astype(np.float32)
    return np.clip(bild, 0, 1).astype(np.float32), orte


def _profil(g, orte, bis=15):
    """Median-Ueberschuss ueber den Himmel, je Radius, in Vielfachen des Himmelspegels."""
    R = 20
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    rad = np.hypot(yy, xx)
    himmel = float(np.median(g))
    aus = []
    for lo in range(1, bis + 1):
        zone = (rad >= lo) & (rad < lo + 1)
        werte = [float(np.median(g[y - R:y + R + 1, x - R:x + R + 1][zone])) for y, x in orte]
        aus.append((float(np.median(werte)) - himmel) / himmel)
    return aus


def _wall(profil, ab=6):
    """Wie stark steigt das Profil jenseits des Kerns wieder AN?

    Ein Stern faellt monoton. Jeder Anstieg dahinter ist der Ueberschwinger.
    """
    schwanz = profil[ab - 1:]
    return max(0.0, max(schwanz) - schwanz[0]) if len(schwanz) > 1 else 0.0


class TestDekonvolutionsringe(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.bild, cls.orte = _sternfeld()
        cls.orte = [(y, x) for y, x in cls.orte
                    if 22 < y < cls.bild.shape[0] - 22 and 22 < x < cls.bild.shape[1] - 22]
        cls.roh = _profil(cls.bild, cls.orte)

    def test_das_rohbild_hat_keinen_wall(self):
        """Grundlage: das ungefilterte Sternfeld faellt monoton. Waere das nicht so, wuerde
        der Test unten Aepfel mit Birnen vergleichen."""
        self.assertLess(_wall(self.roh), 0.01,
                        "schon das Rohbild hat einen Wall: %s" % [round(x, 4) for x in self.roh])

    def test_ohne_schutz_entsteht_ein_wall(self):
        """Die GEGENPROBE. Ohne sie wuerde der Test unten auch bestehen, wenn die
        Dekonvolution nichts taete."""
        aus = astro.deconvolve(self.bild, iterations=15, star_protect=1.0,
                               deringing=True, log=lambda *a, **k: None)
        p = _profil(aus, self.orte)
        self.assertGreater(_wall(p), 0.01,
                           "ohne Stern-Schutz entsteht kein Wall — dann misst dieser Test "
                           "nicht, was er messen soll: %s" % [round(x, 4) for x in p])

    def test_mit_schutz_bleibt_das_profil_ringfrei(self):
        aus = astro.deconvolve(self.bild, iterations=15, star_protect=0.85,
                               deringing=True, log=lambda *a, **k: None)
        p = _profil(aus, self.orte)
        self.assertLessEqual(_wall(p), _wall(self.roh) + 0.005,
                             "die Dekonvolution legt einen Ring um die Sterne.\n"
                             "  roh: %s\n  mit: %s"
                             % ([round(x, 4) for x in self.roh], [round(x, 4) for x in p]))

    def test_kein_graben_unter_den_himmel(self):
        """Das Gegenstueck: der Unterschwinger. Dagegen wirkt der Riegel je Kanal."""
        aus = astro.deconvolve(self.bild, iterations=15, star_protect=0.85,
                               deringing=True, log=lambda *a, **k: None)
        p = _profil(aus, self.orte)
        self.assertGreater(min(p), -0.05,
                           "um die Sterne liegt ein Graben unter dem Himmelspegel: %s"
                           % [round(x, 4) for x in p])

    def test_ausgedehnte_objekte_werden_weiter_geschaerft(self):
        """Der Schutz darf nur STERNE ausnehmen. Deckte er auch Galaxie und Nebel ab, waere
        die Dekonvolution stillschweigend abgeschaltet — genau die Art Fehler, die durchlaeuft
        und ein plausibles Ergebnis liefert."""
        import cv2
        rng = np.random.default_rng(11)
        yy, xx = np.mgrid[0:300, 0:300]
        objekt = 0.5 * np.exp(-(((yy - 150) ** 2 + (xx - 150) ** 2) / (2 * 45.0 ** 2)))
        objekt += 0.12 * np.sin(xx / 3.0) * np.exp(
            -(((yy - 150) ** 2 + (xx - 150) ** 2) / (2 * 40.0 ** 2)))   # Feinstruktur
        bild = np.clip(cv2.GaussianBlur(objekt.astype(np.float32), (0, 0), 1.8) + HIMMEL
                       + rng.normal(0, 0.0006, (300, 300)).astype(np.float32), 0, 1)

        def feinstruktur(g):
            himmel = float(np.median(g))
            drin = g > himmel + 3 * float(np.median(np.abs(g - himmel))) * 1.4826
            hoch = g - cv2.GaussianBlur(g, (0, 0), 2.0)
            return float(np.sqrt((hoch[drin] ** 2).mean())) if drin.any() else 0.0

        aus = astro.deconvolve(bild, iterations=15, star_protect=0.85,
                               deringing=True, log=lambda *a, **k: None)
        vorher, nachher = feinstruktur(bild), feinstruktur(aus)
        self.assertGreater(nachher, vorher * 1.05,
                           "das ausgedehnte Objekt wurde nicht geschaerft (%.6f -> %.6f) — "
                           "der Stern-Schutz deckt zu viel ab" % (vorher, nachher))


if __name__ == "__main__":
    unittest.main(verbosity=2)
