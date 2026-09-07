#!/usr/bin/env python3
"""
ForgePix — Tests für die Trainingspaare (core/trainingspaare.py).

    python3 tests/test_trainingspaare.py

Noise2Noise braucht keine sauberen Zielbilder: zwei unabhängig verrauschte Aufnahmen derselben
Szene genügen, solange das Rauschen mittelwertfrei und zwischen beiden unabhängig ist. Genau
das prüfen diese Tests — und die Fallen, die das Verfahren still kaputtmachen:

* **Nie dasselbe Bild auf beiden Seiten.** Dann wäre die Aufgabe die Identität, und das Netz
  lernte, die Eingabe durchzureichen.
* **Nur gleiche Belichtungszeiten paaren.** Sonst unterscheidet sich das SIGNAL und nicht nur
  das Rauschen, und das Netz lernt Helligkeit umzurechnen statt zu entrauschen.
* **Nicht ausrichtbare Aufnahmen fallen raus**, statt schief einzugehen: ein um zwei Pixel
  verschobenes Paar lehrt das Netz, Kanten zu verschieben.

An echten M27-Aufnahmen gemessen: `n2n` liefert ein Rauschverhältnis von 0,99 (beide Seiten
gleich verrauscht, so soll es sein), `tief` 1,36 (das Ziel ist ruhiger).
"""
import os
import sys
import shutil
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import trainingspaare  # noqa: E402


def _stille(*a, **k):
    pass


class TestSerienFinden(unittest.TestCase):
    """Gruppiert wird nach Kamera, Belichtung und Nacht — NICHT nach Objektnamen."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_tp_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _schreiben(self, name, n, kamera="ZWO ASI294MC Pro", zeit=300.0,
                   nacht="2026-09-06", objekt="M51", art="Light"):
        from astropy.io import fits
        ordner = os.path.join(self.d, name)
        os.makedirs(ordner, exist_ok=True)
        for i in range(n):
            fits.writeto(os.path.join(ordner, "%s_%03d.fit" % (name, i)),
                         np.full((16, 16), 0.1, np.float32),
                         fits.Header({"IMAGETYP": art, "INSTRUME": kamera, "EXPTIME": zeit,
                                      "OBJECT": objekt,
                                      "DATE-OBS": "%sT22:%02d:00" % (nacht, i % 60)}))
        return ordner

    def test_zu_kleine_serien_fallen_raus(self):
        self._schreiben("klein", 5)
        self.assertEqual(trainingspaare.serien_finden(self.d, min_subs=20, log=_stille), {})

    def test_verschiedene_belichtungen_werden_getrennt(self):
        """Der wichtigste Punkt: 60 s und 300 s duerfen nie gepaart werden."""
        self._schreiben("kurz", 25, zeit=60.0)
        self._schreiben("lang", 25, zeit=300.0)
        s = trainingspaare.serien_finden(self.d, min_subs=20, log=_stille)
        self.assertEqual(len(s), 2)
        zeiten = sorted(k[1] for k in s)
        self.assertEqual(zeiten, [60.0, 300.0])

    def test_verschiedene_naechte_werden_getrennt(self):
        self._schreiben("n1", 25, nacht="2026-09-01")
        self._schreiben("n2", 25, nacht="2026-09-05")
        self.assertEqual(len(trainingspaare.serien_finden(self.d, min_subs=20, log=_stille)), 2)

    def test_objektname_gruppiert_NICHT(self):
        """In echten Daten heisst dieselbe Galaxie M51, whirl und Whirlpool Galaxy. Wer nach
        Namen gruppiert, zerreisst die Serie — hier muessen beide Ordner EINE Serie bleiben,
        weil Kamera, Zeit und Nacht gleich sind ... aber getrennte Ordner bleiben getrennt,
        damit keine Aufnahmen aus fremden Verzeichnissen zusammenkommen."""
        a = self._schreiben("teil_a", 22, objekt="M51")
        b = self._schreiben("teil_b", 22, objekt="Whirlpool Galaxy")
        s = trainingspaare.serien_finden(self.d, min_subs=20, log=_stille)
        self.assertEqual(len(s), 2, "verschiedene Ordner duerfen nicht vermischt werden")

    def test_kalibrierbilder_kommen_nicht_hinein(self):
        self._schreiben("darks", 25, art="Dark Frame")
        self.assertEqual(trainingspaare.serien_finden(self.d, min_subs=20, log=_stille), {})


class TestPaare(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_tp2_")
        rng = np.random.default_rng(3)
        h = w = 120
        wahr = np.full((h, w), 0.04, np.float32)
        k = np.zeros((h, w), np.float32)
        cv2.circle(k, (60, 60), 26, 1.0, -1)
        wahr = np.clip(wahr + cv2.GaussianBlur(k, (0, 0), 12) * 0.05, 0, 1)
        for i in range(12):
            p = np.zeros((h, w), np.float32)
            p[int(rng.integers(15, h - 15)), int(rng.integers(15, w - 15))] = 1.0
            wahr = np.clip(wahr + cv2.GaussianBlur(p, (0, 0), 1.5) * 4, 0, 1)
        self.wahr = wahr
        from constants import imwrite
        self.pfade = []
        for i in range(10):
            f = np.clip(wahr + rng.normal(0, 0.006, (h, w)).astype(np.float32), 0, 1)
            q = os.path.join(self.d, "s_%02d.tif" % i)
            imwrite(q, np.clip(np.dstack([f] * 3) * 65535, 0, 65535).astype(np.uint16))
            self.pfade.append(q)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_n2n_beide_seiten_gleich_verrauscht(self):
        """Das ist die Bedingung des Verfahrens. Waere eine Seite ruhiger, waere es kein
        Noise2Noise mehr."""
        p = trainingspaare.paare_aus_serie(self.pfade, art="n2n", max_paare=20, seed=1,
                                           log=_stille)
        g = trainingspaare.guete(p)
        self.assertGreater(g["anzahl"], 0)
        self.assertAlmostEqual(g["rauschverhaeltnis"], 1.0, delta=0.35,
                               msg="Verhaeltnis %.2f" % g["rauschverhaeltnis"])

    def test_n2n_nie_dasselbe_bild_auf_beiden_seiten(self):
        """Sonst waere die Aufgabe die Identitaet und das Netz lernte nichts."""
        p = trainingspaare.paare_aus_serie(self.pfade, art="n2n", max_paare=40, seed=2,
                                           log=_stille)
        for ein, ziel in p:
            self.assertFalse(np.array_equal(ein, ziel), "Eingabe und Ziel identisch")

    def test_tief_hat_ein_ruhigeres_ziel(self):
        p = trainingspaare.paare_aus_serie(self.pfade, art="tief", tief_n=2, max_paare=6,
                                           seed=3, log=_stille)
        g = trainingspaare.guete(p)
        self.assertGreater(g["rauschverhaeltnis"], 1.1,
                           "Ziel muss ruhiger sein, Verhaeltnis %.2f" % g["rauschverhaeltnis"])

    def test_kacheln_haben_die_geforderte_groesse(self):
        p = trainingspaare.paare_aus_serie(self.pfade, art="n2n", kacheln=3, kachelgroesse=48,
                                           max_paare=4, seed=4, log=_stille)
        self.assertGreater(len(p), 0)
        for ein, ziel in p:
            self.assertEqual(ein.shape[:2], (48, 48))
            self.assertEqual(ziel.shape[:2], (48, 48))

    def test_gleicher_seed_gleiche_paare(self):
        a = trainingspaare.paare_aus_serie(self.pfade, art="n2n", max_paare=5, seed=7,
                                           log=_stille)
        b = trainingspaare.paare_aus_serie(self.pfade, art="n2n", max_paare=5, seed=7,
                                           log=_stille)
        self.assertEqual(len(a), len(b))
        for (e1, z1), (e2, z2) in zip(a, b):
            self.assertTrue(np.array_equal(e1, e2) and np.array_equal(z1, z2))

    def test_zu_wenige_aufnahmen_geben_keine_paare(self):
        self.assertEqual(trainingspaare.paare_aus_serie(self.pfade[:1], log=_stille), [])
        self.assertEqual(trainingspaare.paare_aus_serie([], log=_stille), [])

    def test_guete_auf_leerer_liste(self):
        self.assertEqual(trainingspaare.guete([])["anzahl"], 0)


class TestFeldrotation(unittest.TestCase):
    """Gedrehte Aufnahmen duerfen nicht verlorengehen.

    Der Seestar S30 steht auf einer azimutalen Montierung, sein Bildfeld dreht sich also im
    Lauf der Nacht. Hier wurde mit `_estimate_star_shift` ausgerichtet — reine Verschiebung.
    An einer echten Serie (IC 434, 224 Subs) gemessen: bis -27,6 Grad Rotation gegenueber der
    ersten Aufnahme, und im Ergebnis blieben 2 bis 27 % der Aufnahmen uebrig.

    Das Tueckische war die Meldung: "239 Subs -> 24 Kacheln" las sich wie ein Erfolg. Dass 234
    davon weggeworfen worden waren, stand nur im Fortschrittsprotokoll. Und die behaltenen
    waren verschmiert (Exzentrizitaet 2,31 gegen 1,32 mit Drehung).
    """

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_rot_")
        from constants import imwrite
        rng = np.random.default_rng(11)
        h = w = 200
        grund = np.full((h, w), 0.03, np.float32)
        for _ in range(40):                      # genug Sterne fuer Dreiecks-Matching
            p = np.zeros((h, w), np.float32)
            p[int(rng.integers(30, h - 30)), int(rng.integers(30, w - 30))] = 1.0
            grund = np.clip(grund + cv2.GaussianBlur(p, (0, 0), 1.6) * float(rng.uniform(2, 8)),
                            0, 1)
        self.pfade = []
        mitte = (w / 2.0, h / 2.0)
        for i in range(6):
            M = cv2.getRotationMatrix2D(mitte, i * 4.0, 1.0)   # bis 20 Grad
            f = cv2.warpAffine(grund, M, (w, h), flags=cv2.INTER_LANCZOS4,
                               borderMode=cv2.BORDER_REPLICATE)
            f = np.clip(f + rng.normal(0, 0.004, (h, w)).astype(np.float32), 0, 1)
            q = os.path.join(self.d, "r_%02d.tif" % i)
            imwrite(q, np.clip(np.dstack([f] * 3) * 65535, 0, 65535).astype(np.uint16))
            self.pfade.append(q)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_gedrehte_aufnahmen_bleiben_erhalten(self):
        import astro
        aus = trainingspaare._ausrichten(
            [astro._read_float(p) for p in self.pfade], log=_stille)
        self.assertEqual(len(aus), len(self.pfade),
                         "gedrehte Aufnahmen wurden verworfen — Feldrotation nicht behandelt")

    def test_gegenprobe_reine_verschiebung_verliert_sie(self):
        """Damit der Test oben nicht aus Versehen immer gruen ist: mit reiner Verschiebung
        MUESSEN Aufnahmen wegfallen. Faellt hier nichts weg, prueft der Test oben nichts."""
        import astro
        ref = astro._gray(astro._read_float(self.pfade[0]))
        weg = sum(1 for p in self.pfade[1:]
                  if astro._estimate_star_shift(ref, astro._gray(astro._read_float(p))) is None)
        self.assertGreater(weg, 0, "die Testszene dreht sich gar nicht genug")


if __name__ == "__main__":
    unittest.main(verbosity=2)
