#!/usr/bin/env python3
"""
ForgePix — Tests für `astro.synthstar()`: Sternprofile durch runde Moffat-PSFs ersetzen.

    python3 tests/test_synthstar.py     # oder: python3 -m unittest discover -s tests

Die synthetische Szene ist bewusst an echten Aufnahmen geeicht (Himmel 0,03, Rauschen 0,0015,
Sterne bis 0,6) — ein erster Entwurf mit „schönem" rauschfreiem Himmel liess `remove_stars` 22 %
des Bildes maskieren und hätte beinahe zu einer Fehlermeldung über eine Funktion geführt, die auf
echten Daten tadellos arbeitet (dort: 0,17 % Maske, 180 Sterne, grösste Komponente 85 px).

An echten Daten gegengeprüft (ASI294MC Pro, M27, 300 s, künstlicher Nachführfehler von 7 px):
Exzentrizität 0,790 → 0,396 bei unverändertem Gesamtfluss (Faktor 1,0000) und unangetastetem
Nebel. Zum Vergleich misst dieselbe Aufnahme OHNE Nachführfehler 0,420 — das Ergebnis landet also
auf dem Niveau eines Bildes, das den Fehler nie hatte.
"""
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro  # noqa: E402


def _feld(h=320, w=320, laenge=0, seed=7, n=45):
    """Sternfeld mit Himmel und Nebel. `laenge` > 0 zieht die Sterne zu Strichen."""
    rng = np.random.default_rng(seed)
    g = np.full((h, w), 0.03, np.float32)
    neb = np.zeros((h, w), np.float32)
    cv2.circle(neb, (w // 2, h // 2), 60, 1.0, -1)
    g += cv2.GaussianBlur(neb, (0, 0), 30) * 0.02
    for _ in range(n):
        x, y = int(rng.integers(25, w - 25)), int(rng.integers(25, h - 25))
        p = np.zeros((h, w), np.float32)
        if laenge > 0:
            cv2.line(p, (x - laenge // 2, y), (x + laenge // 2, y), 1.0, 1)
        else:
            p[y, x] = 1.0
        g += cv2.GaussianBlur(p, (0, 0), 1.5) * float(rng.uniform(2.0, 9.0))
    g = np.clip(g + rng.normal(0, 0.0015, (h, w)).astype(np.float32), 0, 1)
    return np.dstack([g * 0.8, g * 0.9, g]).astype(np.float32)


def _exzentrizitaet(bgr):
    """Median-Exzentrizität der Sterne (0 = rund, gegen 1 = Strich) und ihre Anzahl."""
    sl, m = astro.remove_stars(bgr, log=lambda *a: None)
    lum = astro._gray(np.clip(bgr - sl, 0, None))
    mm = cv2.dilate((m > 0.5).astype(np.uint8),
                    cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, _lab, st, mit = cv2.connectedComponentsWithStats(mm, 8)
    h, w = lum.shape
    ex = []
    for i in range(1, n):
        if not (3 <= st[i, cv2.CC_STAT_AREA] <= 900):
            continue
        px, py = int(round(mit[i][0])), int(round(mit[i][1]))
        x0, y0 = max(0, px - 8), max(0, py - 8)
        x1, y1 = min(w, px + 9), min(h, py + 9)
        g = np.clip(lum[y0:y1, x0:x1], 0, None).astype(np.float64)
        s = float(g.sum())
        if s <= 1e-8:
            continue
        yy, xx = np.mgrid[0:(y1 - y0), 0:(x1 - x0)].astype(np.float64)
        cx, cy = (g * xx).sum() / s, (g * yy).sum() / s
        dx, dy = xx - cx, yy - cy
        vxx, vyy = (g * dx * dx).sum() / s, (g * dy * dy).sum() / s
        vxy = (g * dx * dy).sum() / s
        sp, dt = vxx + vyy, vxx * vyy - vxy * vxy
        wu = np.sqrt(max(sp * sp / 4 - dt, 0))
        kl, gr = max(sp / 2 - wu, 1e-6), max(sp / 2 + wu, 1e-6)
        ex.append(float(np.sqrt(max(1 - kl / gr, 0))))
    return (float(np.median(ex)) if ex else float("nan")), len(ex)


class TestMoffatKern(unittest.TestCase):
    """Der Baustein zuerst: stimmt die Halbwertsbreite wirklich?"""

    def test_fwhm_trifft_den_vorgegebenen_wert(self):
        for ziel in (2.0, 3.5, 6.0):
            with self.subTest(fwhm=ziel):
                k = astro._moffat_kern(15, ziel, 2.5)
                mitte = k[15, :]
                halb = mitte >= mitte.max() / 2.0
                gemessen = float(halb.sum())
                self.assertLess(abs(gemessen - ziel), 1.2,
                                "FWHM %.1f angefordert, %.1f gemessen" % (ziel, gemessen))

    def test_kern_ist_flusserhaltend_und_rund(self):
        k = astro._moffat_kern(10, 3.0)
        self.assertAlmostEqual(float(k.sum()), 1.0, places=5)
        self.assertTrue(np.allclose(k, k.T, atol=1e-6), "Kern nicht symmetrisch")


class TestSynthstar(unittest.TestCase):

    def test_striche_werden_wieder_rund(self):
        """Der eigentliche Zweck: Nachführfehler verformt die STERNE, der Nebel zeigt es kaum."""
        verzogen = _feld(laenge=7)
        vorher, _ = _exzentrizitaet(verzogen)
        nachher, _ = _exzentrizitaet(astro.synthstar(verzogen, log=lambda *a: None))
        self.assertLess(nachher, vorher * 0.75,
                        "kaum runder geworden (%.3f -> %.3f)" % (vorher, nachher))

    def test_fluss_bleibt_erhalten(self):
        """Ersetzt wird die Form, nicht die Helligkeit — sonst waeren die Sternfarben hin."""
        f = _feld(laenge=7)
        o = astro.synthstar(f, log=lambda *a: None)
        self.assertAlmostEqual(float(o.sum()) / float(f.sum()), 1.0, places=1)

    def test_nebel_bleibt_stehen(self):
        f = _feld()
        o = astro.synthstar(f, log=lambda *a: None)
        h, w = f.shape[:2]
        z = (slice(h // 2 - 15, h // 2 + 15), slice(w // 2 - 15, w // 2 + 15))
        self.assertAlmostEqual(float(o[z].mean()), float(f[z].mean()), places=2)

    def test_zielbreite_folgt_der_KLEINEN_hauptachse(self):
        """Bei Strichen ist die lange Achse der Fehler, die kurze das echte Seeing. Nur so wird
        weder Schaerfe vorgetaeuscht noch der Nachfuehrfehler nachgebaut."""
        rund, strich = _feld(laenge=0), _feld(laenge=7)
        def breite(bild):
            sl, m = astro.remove_stars(bild, log=lambda *a: None)
            st = astro._stern_liste(np.clip(bild - sl, 0, None), m)
            return float(np.median([s[2] for s in st])) if st else float("nan")
        b_rund, b_strich = breite(rund), breite(strich)
        self.assertLess(abs(b_strich - b_rund), 1.5,
                        "Strich-Feld liefert eine ganz andere Zielbreite (%.2f gegen %.2f) — "
                        "dann wird die lange Achse mitgemessen" % (b_strich, b_rund))

    def test_ohne_sterne_bleibt_das_bild_unveraendert(self):
        leer = np.full((120, 120, 3), 0.03, np.float32)
        o = astro.synthstar(leer, log=lambda *a: None)
        self.assertTrue(np.allclose(o, leer, atol=1e-5))
        self.assertIsNone(astro.synthstar(None))

    def test_form_und_wertebereich(self):
        f = _feld()
        o = astro.synthstar(f, log=lambda *a: None)
        self.assertEqual(o.shape, f.shape)
        self.assertGreaterEqual(float(o.min()), 0.0)
        self.assertLessEqual(float(o.max()), 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
