#!/usr/bin/env python3
"""
ForgePix — die Strichspur-Erkennung hat an echten Daten NIE angeschlagen.

    python3 tests/test_strichspur.py

`analyze_frame` ruft `detect_trail` auf, das Ergebnis landet als `"trail"` im Befund, und
`select_subs` verwirft die Aufnahme daraufhin. Die Verkabelung stimmte also — nur fand die
Erkennung nichts.

Ueber alle 340 M51-Aufnahmen gemessen:

    alte Fassung                0 von 340 Aufnahmen
    neue Fassung                1 von 340   (genau die eine, die wirklich eine Spur hat)

Die eine Aufnahme (20230528-025013) traegt eine lehrbuchhafte Satellitenspur quer durchs Bild —
hell, scharf, ununterbrochen. Sie landete im fertigen Stapel als sichtbarer Strich durch die
Galaxie.

**Warum sie durchfiel.** Die alte Fassung nahm `np.std` ueber das GANZE Bild als Rauschmass:

    Hintergrund                                  9,801
    robustes Sigma (MAD)                         0,278
    np.std ueber alles                           1,548   <- 5,6-mal zu gross
    np.std ohne die hellsten 0,47 % der Pixel    0,253   <- das echte Rauschen

**0,47 % der Pixel — die Sterne — machen die ganze Ueberhoehung aus**; das hellste Pixel liegt
883 Sigma ueber dem Hintergrund. `bg + 4*std` ist damit faktisch viermal die Streuung der
Sternhelligkeiten statt viermal das Rauschen:

    Ueberschuss der Spur       2,42      = 8,7 robuste Sigma
    Schwelle bg + 4*std       15,99      -> die Spur bei 12,09 liegt DARUNTER

Im ganzen Bild lagen nur 1399 Pixel (0,08 %) ueber der Schwelle, obwohl allein die Spur rund
1900 Pixel lang ist. Und der Fehler wird groesser, je mehr helle Sterne im Feld stehen — die
Erkennung war also in reichen Feldern am blindesten.

Der zweite Teil ist das **gerichtete Oeffnen**. Ohne es stehen Tausende Sterne in der Maske und
beherrschen die Hough-Abstimmung; eine einzelne duenne Linie geht darin unter.
"""
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro_quality as Q  # noqa: E402


def _sternfeld(h=1089, w=1600, hintergrund=9.8, rauschen=0.28, sterne=900, hell=15, seed=3):
    """Ein Sternfeld wie eine echte Aufnahme.

    Entscheidend sind die WENIGEN sehr hellen Sterne: sie saettigen den Sensor und treiben
    `np.std` hoch, waehrend der Median-Abstand (MAD) unberuehrt bleibt. Genau darauf beruht der
    Fehler, den dieser Test festhaelt. An der echten Aufnahme gemessen: hellstes Pixel 883 Sigma
    ueber dem Hintergrund, np.std 5,6-mal so gross wie das robuste Sigma.
    """
    rng = np.random.default_rng(seed)
    g = rng.normal(hintergrund, rauschen, (h, w)).astype(np.float32)
    punkte = np.zeros((h, w), np.float32)
    for _ in range(sterne):
        punkte[int(rng.integers(6, h - 6)), int(rng.integers(6, w - 6))] += float(
            rng.uniform(3, 200))
    for _ in range(hell):
        punkte[int(rng.integers(6, h - 6)), int(rng.integers(6, w - 6))] += float(
            rng.uniform(2000, 8000))
    g += cv2.GaussianBlur(punkte, (0, 0), 1.6)
    return np.clip(g, 0, 255)


def _mit_spur(g, ueberschuss=2.42, breite=1.1):
    """Eine Satellitenspur quer durchs Bild, so hell wie die echte."""
    h, w = g.shape
    spur = np.zeros((h, w), np.float32)
    cv2.line(spur, (0, int(h * 0.79)), (int(w * 0.59), 0), 1.0, 1, cv2.LINE_AA)
    spur = cv2.GaussianBlur(spur, (0, 0), breite)
    spur *= ueberschuss / max(float(spur.max()), 1e-6)
    return g + spur


class TestGemessenerFall(unittest.TestCase):
    """Die Zahlen der echten Aufnahme, nachgestellt."""

    def test_die_spur_wird_gefunden(self):
        g = _mit_spur(_sternfeld())
        self.assertTrue(Q.detect_trail(g), "die Satellitenspur wird nicht erkannt")

    def test_ohne_spur_kein_alarm(self):
        """Die Gegenprobe. Eine Erkennung, die ueberall anschlaegt, ist schlimmer als keine —
        sie wuerde jede Aufnahme verwerfen. Geprueft wird das an einem REICHEN Feld mit
        gesaettigten Sternen: genau dort ist die Verwechslungsgefahr am groessten."""
        self.assertFalse(Q.detect_trail(_sternfeld()))
        self.assertFalse(Q.detect_trail(_sternfeld(sterne=2500, hell=40, seed=11)))

    def test_die_alte_schwelle_haette_die_spur_verfehlt(self):
        """Die Gegenprobe zum Kern der Aenderung: mit `np.std` liegt die Schwelle ueber der
        Spur, mit dem robusten Sigma darunter. Faellt dieser Test, bildet der Test den
        gemessenen Fall nicht mehr ab und die anderen pruefen nichts."""
        g = _mit_spur(_sternfeld())
        bg = float(np.median(g))
        alt = bg + 4 * float(np.std(g))
        neu = bg + 4 * (float(np.median(np.abs(g - bg))) * 1.4826)
        spur = float(np.percentile(g, 99.99))
        self.assertGreater(alt, neu * 1.5,
                           "np.std ist hier nicht genug ueberhoeht: alt %.2f, neu %.2f"
                           % (alt, neu))
        self.assertGreater(alt, bg + 2.42,
                           "die alte Schwelle laege unter der Spur — dann prueft der Test "
                           "den gemessenen Fehler nicht")
        self.assertLess(neu, bg + 2.42,
                        "die neue Schwelle liegt ueber der Spur")
        del spur

    def test_np_std_ist_kein_rauschmass(self):
        """Die Begruendung der Aenderung, nachgerechnet: die Sterne treiben np.std hoch,
        obwohl sie nur einen Bruchteil der Pixel ausmachen."""
        g = _sternfeld()
        bg = float(np.median(g))
        mad = float(np.median(np.abs(g - bg)) * 1.4826)
        self.assertGreater(float(np.std(g)) / mad, 3.0,
                           "np.std %.3f gegen MAD %.3f" % (float(np.std(g)), mad))
        # und der Beleg, dass es wirklich die Sterne sind
        ohne = g[g < bg + 5 * mad]
        self.assertLess(float(np.std(ohne)), 1.5 * mad,
                        "ohne die hellsten Pixel muss np.std auf das echte Rauschen fallen")
        self.assertLess(100.0 * float((g >= bg + 5 * mad).mean()), 3.0,
                        "das sind mehr als ein paar Prozent — dann ist es kein Sternproblem")


class TestVerkabelung(unittest.TestCase):
    """Die Erkennung nuetzt nur, wenn die Auswahl sie auch liest."""

    def test_analyze_frame_liefert_das_feld(self):
        import inspect
        self.assertIn('"trail"', inspect.getsource(Q.analyze_frame))

    def test_select_subs_verwirft_daraufhin(self):
        import inspect
        q = inspect.getsource(Q.select_subs)
        self.assertIn('f["trail"]', q,
                      "die Auswahl liest das Spur-Feld nicht — die Erkennung waere wirkungslos")

    def test_kein_np_std_mehr_als_rauschmass(self):
        import inspect
        q = inspect.getsource(Q.detect_trail)
        self.assertNotIn("np.std(", q,
                         "np.std ueber das ganze Bild misst den Bildinhalt, nicht das Rauschen")
        self.assertIn("1.4826", q, "es fehlt das robuste Sigma")


if __name__ == "__main__":
    unittest.main(verbosity=2)
