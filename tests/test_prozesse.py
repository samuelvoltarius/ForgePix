#!/usr/bin/env python3
"""
Der Arbeitsplatz (core/prozesse.py): jedes Werkzeug, Masken, Verlauf, Rezepte.

Am 22.11.2026 an einem echten Stapel (8 Seestar-Aufnahmen IC 5146, 1884×1047, linear mit
negativem Hintergrund) gemessen; zwei Funde daraus stehen hier als Test:

* GHS scheiterte, weil sein Parameter „b“ mit dem Bildnamen der Hülle kollidierte.
* `masken.anwenden` beschnitt das Ergebnis still auf 0..1 — bei linearen Daten mit negativem
  Hintergrund änderte das JEDES Pixel außerhalb der Maske (100 %, bis 0,019). Eine Maske, die
  außen etwas verändert, ist keine Maske.
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))

import masken  # noqa: E402
import prozesse  # noqa: E402


def sternfeld(h=96, w=128, hintergrund=0.02, seed=0):
    rng = np.random.default_rng(seed)
    b = np.full((h, w, 3), hintergrund, np.float32) + rng.normal(0, 0.002, (h, w, 3)).astype(np.float32)
    yy, xx = np.mgrid[:h, :w]
    for _ in range(25):
        x, y, a = rng.uniform(8, w - 8), rng.uniform(8, h - 8), rng.uniform(0.05, 0.8)
        b += (a * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2)))[..., None].astype(np.float32)
    return b


STILL = lambda *a, **k: None  # noqa: E731


class TestProzesse(unittest.TestCase):
    def test_jedes_klassische_werkzeug_laeuft(self):
        bild = sternfeld()
        for p in prozesse.PROZESSE:
            # experimentelle Modelle, externe Programme und Werkzeuge mit Pflicht-Zweitbild haben
            # eigene Tests (unten) — hier nur, was mit dem offenen Bild allein läuft
            if p.experimentell or p.extern or any((x.bild or x.standard is None) and x.pflicht for x in p.params):
                continue
            with self.subTest(p.id):
                r = prozesse.anwenden(bild, p.id)
                self.assertTrue(np.isfinite(r).all())
                if not p.aendert_groesse:
                    self.assertEqual(r.shape, bild.shape)

    def test_ghs_parameter_b(self):
        r = prozesse.anwenden(sternfeld(), "ghs", {"b": 1.0})
        self.assertEqual(r.shape, (96, 128, 3))

    def test_jeder_prozess_hat_vorbild_und_gueltige_standards(self):
        ids = [p.id for p in prozesse.PROZESSE]
        self.assertEqual(len(ids), len(set(ids)))
        for p in prozesse.PROZESSE:
            self.assertTrue(p.vorbild and p.beschreibung, p.id)
            for x in p.params:                          # Standardwerte liegen in der Spanne
                if not x.bild and x.standard is not None:
                    x.pruefen(x.standard)

    def test_ausserhalb_der_spanne_ist_fehler(self):
        with self.assertRaises(ValueError):
            prozesse.anwenden(sternfeld(), "mtf", {"target_bg": 2.0})
        with self.assertRaises(ValueError):
            prozesse.anwenden(sternfeld(), "mtf", {"unbekannt": 1})

    def test_maske_laesst_aussen_unveraendert_auch_bei_negativen_werten(self):
        bild = sternfeld(hintergrund=-0.015)            # linear, Hintergrund unter null
        m = prozesse.maske_bauen(bild, "Sterne")
        r = prozesse.anwenden(bild, "tv", maske=m)
        aussen = m == 0
        self.assertTrue(aussen.any())
        np.testing.assert_array_equal(r[aussen], bild[aussen])
        self.assertTrue((np.abs(r[m > 0.5] - bild[m > 0.5]) > 0).any(), "innen muss etwas passieren")

    def test_masken_anwenden_beschneidet_nicht(self):
        a = np.full((4, 4, 3), -0.5, np.float32)
        np.testing.assert_array_equal(masken.anwenden(a, np.zeros((4, 4)), a * 0), a)

    def test_groesse_aendern_mit_maske_abgelehnt(self):
        bild = sternfeld()
        with self.assertRaises(ValueError):
            prozesse.anwenden(bild, "binning", maske=np.ones(bild.shape[:2]))

    def test_experimentell_nur_mit_zusage(self):
        with self.assertRaises(ValueError):
            prozesse.anwenden(sternfeld(), "ki_entrauschen")

    def test_verlauf_rueckgaengig_und_nachrechnen(self):
        """Mit nur einem behaltenen Zwischenstand muss ältere Geschichte nachgerechnet werden —
        und dasselbe ergeben."""
        a = prozesse.Arbeitsbild(sternfeld(), behalten=1, log=STILL)
        a.anwenden("hintergrund_neutral")
        nach1 = a.bild.copy()
        a.anwenden("mtf")
        a.anwenden("tv", maske={"art": "Hintergrund"})
        ende = a.bild.copy()
        a.rueckgaengig(); a.rueckgaengig()
        np.testing.assert_array_equal(a.bild, nach1)
        a.wiederholen(); a.wiederholen()
        np.testing.assert_array_equal(a.bild, ende)
        with self.assertRaises(ValueError):
            a.wiederholen()

    def test_neuer_schritt_verwirft_wiederholen_zweig(self):
        a = prozesse.Arbeitsbild(sternfeld(), log=STILL)
        a.anwenden("mtf"); a.anwenden("tv"); a.rueckgaengig()
        a.anwenden("invertieren")
        self.assertEqual([s["id"] for s in a.schritte], ["mtf", "invertieren"])
        self.assertFalse(a.kann_vor)

    def test_rezept_auf_anderes_bild(self):
        a = prozesse.Arbeitsbild(sternfeld(seed=1), log=STILL)
        a.anwenden("mtf"); a.anwenden("sterne_kleiner", maske={"art": "Sterne"})
        d = tempfile.mkdtemp()
        try:
            pfad = prozesse.rezept_speichern(a.rezept(), os.path.join(d, "r.json"))
            rezept = prozesse.rezept_laden(pfad)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        np.testing.assert_array_equal(prozesse.Arbeitsbild.nachspielen(sternfeld(seed=1), rezept, log=STILL), a.bild)
        anderes = prozesse.Arbeitsbild.nachspielen(sternfeld(seed=2), rezept, log=STILL)
        self.assertEqual(anderes.shape, a.bild.shape)

    def test_graubild_bleibt_grau(self):
        grau = sternfeld()[..., 0]
        a = prozesse.Arbeitsbild(grau, log=STILL)
        a.anwenden("mtf")                               # mtf behandelt Kanäle gleich
        self.assertEqual(a.zum_speichern().ndim, 2)

    def test_speichern_fits_mit_verlauf(self):
        from astropy.io import fits
        a = prozesse.Arbeitsbild(sternfeld(), log=STILL)
        a.anwenden("mtf")
        d = tempfile.mkdtemp()
        try:
            pfad = prozesse.bild_speichern(os.path.join(d, "x.fits"), a.zum_speichern(),
                                           fits.Header({"OBJECT": "M 27"}), a.schritte)
            with fits.open(pfad) as h:
                self.assertEqual(h[0].data.shape, (3, 96, 128))
                self.assertEqual(h[0].header["OBJECT"], "M 27")
                self.assertIn("mtf", str(h[0].header["HISTORY"]))
            with self.assertRaises(OSError):            # nie überschreiben
                prozesse.bild_speichern(pfad, a.zum_speichern())
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_jedes_werkzeug_hat_englische_texte(self):
        """Namen, Beschreibungen, Einstellungen und Auswahlwerte laufen in der Oberfläche durch
        tr() — die i18n-Wächter sehen sie nicht, weil sie keine Literale in ui/ sind."""
        import json
        with open(os.path.join(ROOT, "lang", "en.json"), encoding="utf-8") as fh:
            en = json.load(fh)
        fehlt = []
        for p in prozesse.PROZESSE:
            texte = [p.name, p.beschreibung, p.gruppe] + [x.label for x in p.params]
            texte += [w for x in p.params for w in (x.wahl or [])]
            fehlt += [t for t in texte if t not in en]
        fehlt += [m for m in prozesse.MASKEN if m not in en]
        fehlt += [v for v in prozesse.PHASE_TEXT.values() if v not in en]
        self.assertEqual(fehlt, [])

    def test_statistik(self):
        s = prozesse.statistik(sternfeld())
        self.assertEqual([k["kanal"] for k in s], ["Blau", "Grün", "Rot"])
        self.assertAlmostEqual(s[0]["median"], 0.02, places=2)


if __name__ == "__main__":
    unittest.main()
