#!/usr/bin/env python3
"""
ForgePix — Tests für das inkrementelle Live-Stacking (core/livestack.py).

    python3 tests/test_livestack.py     # oder: python3 -m unittest discover -s tests

Der bisherige Beobachtungsmodus stapelt bei jeder neuen Aufnahme den GESAMTEN Bestand neu — beim
200. Sub werden 200 Dateien gelesen, obwohl sich genau eine geändert hat. Hier werden laufende
Summen fortgeschrieben.

An echten Daten gegengeprüft (10 bzw. 12 Subs M27, ASI294MC Pro):
    mittlere Abweichung zum Stapeln am Ende: 0,000832 = 0,077 % der Bildspanne
    SNR live 62,90 gegen 62,94 am Ende
    Ergebnis nach jedem Sub: 2,8 s live gegen 7,5 s jedes Mal neu (Faktor 2,6 bei 12 Subs,
    und der Abstand wächst, weil das Neustapeln quadratisch zulegt)
    gespeicherter und wieder geladener Zustand: bitgleich

Die eine echte Einschränkung ist die Ausreisser-Erkennung: am Ende sind alle Werte gleichzeitig
da, hier wird ein neuer Wert gegen die Statistik der bisherigen geprüft. Darum wird erst ab
`min_fuer_verwurf` überhaupt verworfen.
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

import astro       # noqa: E402
import livestack   # noqa: E402
from constants import imwrite  # noqa: E402


def _stille(*a, **k):
    pass


class TestLiveStack(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_live_")
        self.h = self.w = 160
        rng = np.random.default_rng(5)
        g = np.full((self.h, self.w), 0.06, np.float32)
        neb = np.zeros((self.h, self.w), np.float32)
        cv2.circle(neb, (self.w // 2, self.h // 2), 30, 1.0, -1)
        g += cv2.GaussianBlur(neb, (0, 0), 12) * 0.05
        self.sterne = [(int(rng.integers(20, self.w - 20)), int(rng.integers(20, self.h - 20)))
                       for _ in range(25)]
        for x, y in self.sterne:
            p = np.zeros((self.h, self.w), np.float32)
            p[y, x] = 1.0
            g += cv2.GaussianBlur(p, (0, 0), 1.5) * float(rng.uniform(3, 9))
        self.wahr = np.clip(g, 0, 1)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _serie(self, n=10, unter="a", satellit_in=None, seed=7):
        rng = np.random.default_rng(seed)
        d = os.path.join(self.d, unter)
        os.makedirs(d, exist_ok=True)
        pfade = []
        for i in range(n):
            f = np.clip(self.wahr
                        + rng.normal(0, 0.004, (self.h, self.w)).astype(np.float32), 0, 1)
            if satellit_in is not None and i == satellit_in:
                cv2.line(f, (10, 20), (self.w - 10, self.h - 20), 0.9, 2)
            p = os.path.join(d, "s_%02d.tif" % i)
            imwrite(p, np.clip(np.dstack([f] * 3) * 65535, 0, 65535).astype(np.uint16))
            pfade.append(p)
        return pfade

    def test_ergebnis_entspricht_dem_stapeln_am_ende(self):
        """Der Punkt, an dem alles hängt: schneller darf es sein, anders nicht."""
        pfade = self._serie()
        ls = livestack.LiveStack(registrieren=False, gewichten=False, log=_stille)
        for p in pfade:
            ls.hinzufuegen(p)
        live = ls.ergebnis()
        ende = np.mean(np.stack([astro._read_float(p) for p in pfade]), axis=0)
        abw = float(np.abs(live - ende).mean())
        spanne = float(ende.max() - ende.min())
        self.assertLess(abw / max(spanne, 1e-9), 0.01,
                        "Abweichung %.5f = %.2f %% der Bildspanne"
                        % (abw, 100 * abw / max(spanne, 1e-9)))

    def test_satellit_wird_verworfen(self):
        """Ausreisser-Verwurf gegen die laufende Statistik — der Satellit sitzt bewusst SPÄT
        in der Serie, denn vorher ist die Statistik noch zu dünn."""
        pfade = self._serie(n=12, unter="sat", satellit_in=9)
        ls = livestack.LiveStack(registrieren=False, log=_stille)
        for p in pfade:
            ls.hinzufuegen(p)
        erg = astro._gray(ls.ergebnis())
        spur = np.zeros((self.h, self.w), np.uint8)
        cv2.line(spur, (10, 20), (self.w - 10, self.h - 20), 1, 2)
        rest = float(erg[spur > 0].mean() - erg[spur == 0].mean())
        wahr_rest = float(self.wahr[spur > 0].mean() - self.wahr[spur == 0].mean())
        self.assertLess(rest - wahr_rest, 0.02, "Satellit steht noch mit %.4f drin" % rest)

    def test_ohne_genug_frames_wird_nicht_verworfen(self):
        """Bei drei Frames ist jede Statistik Zufall — dann darf nichts verworfen werden,
        sonst frisst der Stapel echtes Signal."""
        pfade = self._serie(n=3, unter="kurz")
        ls = livestack.LiveStack(registrieren=False, gewichten=False, min_fuer_verwurf=5,
                                 log=_stille)
        for p in pfade:
            ls.hinzufuegen(p)
        ende = np.mean(np.stack([astro._read_float(p) for p in pfade]), axis=0)
        self.assertTrue(np.allclose(ls.ergebnis(), ende, atol=1e-4))

    def test_zustand_speichern_und_fortsetzen(self):
        """Ein Absturz um drei Uhr nachts darf nicht die halbe Nacht kosten."""
        pfade = self._serie(n=8, unter="save")
        ls = livestack.LiveStack(registrieren=False, log=_stille)
        for p in pfade[:5]:
            ls.hinzufuegen(p)
        z = os.path.join(self.d, "zustand.npz")
        self.assertTrue(ls.speichern(z))
        weiter = livestack.LiveStack.laden(z, log=_stille)
        self.assertIsNotNone(weiter)
        self.assertEqual(weiter.n, 5)
        self.assertTrue(np.array_equal(weiter.ergebnis(), ls.ergebnis()))
        self.assertFalse(weiter.registrieren)
        for p in pfade[5:]:
            ls.hinzufuegen(p)
            weiter.hinzufuegen(p)
        self.assertTrue(np.allclose(weiter.ergebnis(), ls.ergebnis(), atol=1e-6))

    def test_kaputter_zustand_gibt_none(self):
        z = os.path.join(self.d, "muell.npz")
        with open(z, "wb") as fh:
            fh.write(b"kein numpy")
        self.assertIsNone(livestack.LiveStack.laden(z, log=_stille))

    def test_versetzte_frames_werden_ausgerichtet(self):
        """Ohne Ausrichtung würden die Sterne doppelt stehen."""
        d = os.path.join(self.d, "shift")
        os.makedirs(d, exist_ok=True)
        rng = np.random.default_rng(3)
        pfade = []
        for i in range(6):
            f = np.clip(self.wahr + rng.normal(0, 0.003, (self.h, self.w)).astype(np.float32), 0, 1)
            M = np.array([[1, 0, 3.0 * i], [0, 1, -2.0 * i]], np.float32)
            f = cv2.warpAffine(f, M, (self.w, self.h), borderMode=cv2.BORDER_REPLICATE)
            p = os.path.join(d, "v_%02d.tif" % i)
            imwrite(p, np.clip(np.dstack([f] * 3) * 65535, 0, 65535).astype(np.uint16))
            pfade.append(p)
        mit = livestack.LiveStack(registrieren=True, gewichten=False, log=_stille)
        ohne = livestack.LiveStack(registrieren=False, gewichten=False, log=_stille)
        for p in pfade:
            mit.hinzufuegen(p)
            ohne.hinzufuegen(p)

        def spitze(a):
            g = astro._gray(a)
            hg = cv2.medianBlur((np.clip(g, 0, 1) * 255).astype(np.uint8), 31).astype(np.float32) / 255
            return float((g - hg).max())

        self.assertGreater(spitze(mit.ergebnis()), spitze(ohne.ergebnis()) * 1.2,
                           "ausgerichtet muessten die Sterne deutlich spitzer sein")

    def test_unpassende_groesse_wird_abgelehnt(self):
        ls = livestack.LiveStack(registrieren=False, log=_stille)
        ls.hinzufuegen(np.full((60, 60, 3), 0.2, np.float32))
        self.assertFalse(ls.hinzufuegen(np.full((40, 40, 3), 0.2, np.float32)))
        self.assertEqual(ls.n, 1)
        self.assertEqual(ls.verworfen, 1)

    def test_leerer_stapel(self):
        ls = livestack.LiveStack(log=_stille)
        self.assertIsNone(ls.ergebnis())
        self.assertFalse(ls.vorschau_schreiben(os.path.join(self.d, "x.jpg")))
        self.assertFalse(ls.speichern(os.path.join(self.d, "x.npz")))

    def test_neue_dateien_uebergeht_bekannte_und_fremde(self):
        pfade = self._serie(n=3, unter="nd")
        d = os.path.dirname(pfade[0])
        with open(os.path.join(d, "notiz.txt"), "w", encoding="utf-8") as fh:
            fh.write("kein Bild")
        gesehen = {}
        self.assertEqual(livestack.neue_dateien(d, set(pfade[:1]), beobachtet=gesehen, jetzt=0), [])
        raus = livestack.neue_dateien(d, set(pfade[:1]), beobachtet=gesehen, jetzt=3)
        self.assertEqual(len(raus), 2)
        self.assertTrue(all(p.endswith(".tif") for p in raus))


if __name__ == "__main__":
    unittest.main(verbosity=2)
