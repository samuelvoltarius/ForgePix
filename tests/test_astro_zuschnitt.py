#!/usr/bin/env python3
"""
ForgePix — der Astro-Zuschnitt auf die volle Beitragszahl.

    python3 tests/test_astro_zuschnitt.py

Beim Ausrichten wandern die Aufnahmen gegeneinander. Am Bildrand tragen darum nur wenige Subs
bei, und diese Pixel rauschen entsprechend staerker. An einem echten Stapel gemessen (IC 434,
133 von 224 Subs, Seestar S30): die aeusseren 5 px rauschen **1,6-mal** so stark wie die Mitte,
bei 80 px noch 1,3-mal. Nach dem Strecken wird daraus ein deutlich sichtbarer blau-roter Saum.

Der Saum verdirbt nicht nur den Anblick, er verdirbt die **Messung**. Am ausgelieferten Bild
nachgerechnet:

    ganzes Bild           Gradient 41,9 %     Rand oben  G/R 0,680
    40 px Rand abgezogen  Gradient 24,7 %     Mitte      G/R 0,963

Der Messbericht misst ueber die ganze Flaeche, das Regelwerk raet auf diesen Zahlen — der Rand
faelscht also Helligkeitsverlauf und Farbbalance gleich mit.

`--autocrop` ist als Standard-an dokumentiert, wurde im Astro-Modus aber nie angewandt; die
Abdeckungsmaske ist binaer ("mindestens eine Aufnahme") und sieht den Abfall gar nicht.

**Der Grund fuer diesen Test.** Die erste Fassung des Zuschnitts nahm Zeilen, in denen JEDES
Pixel genug Beitraege hat (`_gut.all(axis=1)`). Die Sigma-Rejection verwirft aber ueberall
verstreute Einzelpixel — auch mitten im Bild. Damit qualifizierte sich keine einzige Zeile, und
der Zuschnitt tat **wortlos nichts**: der Lauf sah aus wie vorher, das Bild war 1080x1920 wie
vorher, und im Protokoll stand keine Zeile darueber. Genau die Fehlerform, um die es in diesem
Projekt staendig geht. Richtig ist der Median je Zeile und je Spalte.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))


def _zuschnitt(voll, anteil=0.8):
    """Dieselbe Rechnung wie in `_astro_write` — hier isoliert pruefbar."""
    zp = np.median(voll, axis=1)
    sp = np.median(voll, axis=0)
    grenze = anteil * float(max(zp.max(), sp.max()))
    zeilen = np.where(zp >= grenze)[0]
    spalten = np.where(sp >= grenze)[0]
    if not len(zeilen) or not len(spalten):
        return None
    return int(zeilen[0]), int(zeilen[-1]) + 1, int(spalten[0]), int(spalten[-1]) + 1


def _beitragskarte(h=200, w=300, rand=12, n=133, loecher=True, seed=4):
    """Wie eine echte Karte aussieht: Rampe am Rand, Loecher ueberall."""
    k = np.full((h, w), float(n), np.float32)
    for i in range(rand):                       # linearer Abfall nach aussen
        f = (i + 1) / float(rand + 1)
        k[i, :] = np.minimum(k[i, :], n * f)
        k[h - 1 - i, :] = np.minimum(k[h - 1 - i, :], n * f)
        k[:, i] = np.minimum(k[:, i], n * f)
        k[:, w - 1 - i] = np.minimum(k[:, w - 1 - i], n * f)
    if loecher:
        # Sigma-Rejection: verstreute Pixel, die in vielen Aufnahmen verworfen wurden.
        rng = np.random.default_rng(seed)
        ys = rng.integers(0, h, 4000)
        xs = rng.integers(0, w, 4000)
        k[ys, xs] *= 0.3
    return k


class TestZuschnitt(unittest.TestCase):

    def test_der_rand_wird_gefunden(self):
        k = _beitragskarte(rand=12, loecher=False)
        y0, y1, x0, x1 = _zuschnitt(k)
        # Bei linearem Abfall liegt die 80-%-Grenze im aeusseren Fuenftel der Rampe.
        self.assertGreater(y0, 5)
        self.assertLess(y0, 13)
        self.assertEqual(y0, k.shape[0] - y1)
        self.assertEqual(x0, k.shape[1] - x1)

    def test_verstreute_rejection_verhindert_den_zuschnitt_nicht(self):
        """Der eigentliche Fehler. Mit `all()` statt Median war das Ergebnis hier None —
        und die Pipeline schnitt wortlos gar nichts."""
        k = _beitragskarte(rand=12, loecher=True)
        streng = (k >= 0.8 * k.max())
        self.assertEqual(len(np.where(streng.all(axis=1))[0]), 0,
                         "die Gegenprobe traegt nicht: hier muss die strenge Variante "
                         "versagen, sonst prueft der Test nichts")
        self.assertIsNotNone(_zuschnitt(k), "der Median-Zuschnitt versagt ebenfalls")
        y0, y1, x0, x1 = _zuschnitt(k)
        self.assertGreater(y0, 0)
        self.assertGreater(x0, 0)

    def test_ein_vollflaechiger_stapel_wird_nicht_beschnitten(self):
        """Die Gegenprobe: ohne Randabfall darf nichts wegfallen."""
        k = _beitragskarte(rand=0, loecher=True)
        self.assertEqual(_zuschnitt(k), (0, 200, 0, 300))

    def test_der_rand_rauscht_wirklich_staerker(self):
        """Die Begruendung des ganzen Zuschnitts, nachgerechnet: weniger Beitraege heisst
        mehr Rauschen, mit 1/sqrt(n)."""
        rng = np.random.default_rng(11)
        n_mitte, n_rand = 133, 20
        mitte = rng.normal(0, 1.0, (n_mitte, 5000)).mean(axis=0).std()
        rand = rng.normal(0, 1.0, (n_rand, 5000)).mean(axis=0).std()
        self.assertGreater(rand / mitte, 2.0,
                           "20 statt 133 Beitraege muessen rund sqrt(133/20)=2,6-mal so "
                           "stark rauschen")


class TestInDerPipeline(unittest.TestCase):

    def _quelle(self):
        import io
        pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core",
                            "focus_cull_stack.py")
        return io.open(pfad, encoding="utf-8").read()

    def test_der_astro_modus_wendet_autocrop_an(self):
        q = self._quelle()
        self.assertIn('stack_info.get("beitraege")', q,
                      "der Astro-Modus nutzt die Beitragszahl nicht")

    def test_kein_stiller_verzicht(self):
        """Jeder Weg, auf dem NICHT zugeschnitten wird, muss das sagen. Die erste Fassung
        schwieg in drei Faellen — und einer davon trat sofort ein."""
        q = self._quelle().split('stack_info.get("beitraege")')[1].split("\ndef ")[0]
        self.assertIn("Zuschnitt nicht moeglich", q)
        self.assertEqual(q.count("Zuschnitt uebersprungen"), 2,
                         "beide Abbruchgruende muessen im Protokoll stehen")

    def test_die_stapelfunktion_liefert_die_beitraege(self):
        import astro
        import inspect
        quelle = inspect.getsource(astro.stack)
        self.assertIn("beitraege=cnt", quelle,
                      "der sigma/winsor-Weg gibt die Beitragszahl nicht zurueck")
        self.assertIn("beitraege=anzahl_out", quelle,
                      "der linearfit-Weg gibt die Beitragszahl nicht zurueck")


if __name__ == "__main__":
    unittest.main(verbosity=2)
