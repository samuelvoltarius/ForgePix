#!/usr/bin/env python3
"""
ForgePix — die vier Bildformel-Funktionen, ohne die der Astro-Alltag nicht geht.

    python3 tests/test_pixelmath_astro.py

`core/pixelmath.py` gibt es laenger, es haengt in der Oberflaeche unter „PixelMath:
Bildformeln", und es ist sauber verriegelt: Attributzugriff, Indizes und Aufrufe ausserhalb der
Positivliste kommen nicht durch. Nur fehlten vier Funktionen, die in der Astrofotografie in fast
jedem Ausdruck vorkommen:

* **`med(A)`** — `A - med(A)`, den Hintergrund abziehen. Das ist der haeufigste PixelMath-
  Ausdruck ueberhaupt, und ohne `med` liess er sich gar nicht hinschreiben.
* **`mad(A)`** — robuste Streuung, die Grundlage jeder Schwelle. `A > med(A) + 3*mad(A)`.
* **`mtf(A, m)`** — die Midtone-Kurve, mit der PixInsight streckt.
* **`blur(A, sigma)`** — Masken bauen: `A > blur(A, 20)` trennt Feines vom Grossflaechigen.

Nebenbei bekamen alle Fehlerfaelle **dieselbe** Meldung: `med(A)` (ein Tippfehler) und
`__import__("os")` (ein Ausbruchsversuch) wurden beide mit „Unbekannter Bildname oder nicht
erlaubte Rechenoperation" quittiert. Wer `med(A)` schrieb, suchte danach den Fehler beim
Bildnamen.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

from pixelmath import evaluate  # noqa: E402


def _bild(h=48, w=64, mitte=0.30, rauschen=0.05, seed=1):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(mitte, rauschen, (h, w, 3)), 0, 1).astype(np.float32)


class TestNeueFunktionen(unittest.TestCase):

    def setUp(self):
        self.A = _bild()

    def test_med_zieht_den_hintergrund_ab(self):
        """Der haeufigste Ausdruck der Astrofotografie."""
        erg = evaluate("A - med(A)", {"A": self.A})
        soll = self.A - float(np.median(self.A))
        np.testing.assert_allclose(erg, soll, atol=1e-6)
        self.assertAlmostEqual(float(np.median(erg)), 0.0, places=6)

    def test_mad_ist_die_robuste_streuung(self):
        erg = evaluate("mad(A)", {"A": self.A})
        m = float(np.median(self.A))
        soll = float(np.median(np.abs(self.A - m)) * 1.4826)
        self.assertAlmostEqual(float(np.asarray(erg).ravel()[0]), soll, places=6)

    def test_mad_haelt_ausreissern_stand(self):
        """Die Gegenprobe zum Zweck: ein paar sehr helle Sterne duerfen die Streuung nicht
        verreissen — genau daran ist heute die Strichspur-Erkennung gescheitert."""
        b = self.A.copy()
        b[0, 0] = b[1, 1] = b[2, 2] = 1.0
        ohne = float(np.asarray(evaluate("mad(A)", {"A": self.A})).ravel()[0])
        mit = float(np.asarray(evaluate("mad(A)", {"A": b})).ravel()[0])
        self.assertLess(abs(mit - ohne) / ohne, 0.05,
                        "mad reagiert zu stark auf Ausreisser (%.5f gegen %.5f)" % (mit, ohne))

    def test_schwelle_aus_med_und_mad(self):
        """Der zweithaeufigste Ausdruck: alles ueber 3 Sigma."""
        erg = evaluate("A > med(A) + 3 * mad(A)", {"A": self.A})
        anteil = float(np.mean(np.asarray(erg) > 0.5))
        self.assertLess(anteil, 0.02, "3 Sigma treffen zu viel: %.3f" % anteil)
        self.assertGreater(anteil, 0.0)

    def test_mtf_bewegt_den_mittelton_und_laesst_die_enden_stehen(self):
        """Die Midtone-Kurve: 0 bleibt 0, 1 bleibt 1, und `m` landet auf 0,5."""
        rampe = np.linspace(0, 1, 101, dtype=np.float32)[None, :, None].repeat(3, axis=2)
        erg = np.asarray(evaluate("mtf(A, 0.25)", {"A": rampe}))
        self.assertAlmostEqual(float(erg[0, 0, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(erg[0, -1, 0]), 1.0, places=6)
        self.assertAlmostEqual(float(erg[0, 25, 0]), 0.5, places=2)
        self.assertTrue(np.all(np.diff(erg[0, :, 0]) >= -1e-6), "die Kurve muss monoton sein")

    def test_mtf_hellt_auf(self):
        """Mit m < 0,5 wird das Bild heller — das ist der Sinn beim Strecken."""
        erg = evaluate("mtf(A, 0.25)", {"A": self.A})
        self.assertGreater(float(np.mean(erg)), float(np.mean(self.A)))

    def test_blur_glaettet_und_erhaelt_die_helligkeit(self):
        erg = np.asarray(evaluate("blur(A, 3)", {"A": self.A}))
        self.assertLess(float(np.std(erg)), 0.4 * float(np.std(self.A)))
        self.assertAlmostEqual(float(np.mean(erg)), float(np.mean(self.A)), places=3)

    def test_maske_aus_blur(self):
        """Feines vom Grossflaechigen trennen — so baut man Sternmasken."""
        erg = evaluate("A > blur(A, 8)", {"A": self.A})
        anteil = float(np.mean(np.asarray(erg) > 0.5))
        self.assertGreater(anteil, 0.2)
        self.assertLess(anteil, 0.8)

    def test_blur_mit_null_laesst_das_bild_in_ruhe(self):
        np.testing.assert_allclose(np.asarray(evaluate("blur(A, 0)", {"A": self.A})),
                                   self.A, atol=1e-6)


class TestMeldungenZeigenInDieRichtigeRichtung(unittest.TestCase):
    """Vorher bekam jeder Fehlerfall denselben Satz."""

    def setUp(self):
        self.A = _bild(8, 8)

    def _fehler(self, ausdruck):
        with self.assertRaises(ValueError) as fall:
            evaluate(ausdruck, {"A": self.A})
        return str(fall.exception)

    def test_tippfehler_im_funktionsnamen(self):
        text = self._fehler("mediann(A)")
        self.assertIn("Unbekannte Funktion", text)
        self.assertIn("med", text, "die Meldung soll die vorhandenen Funktionen nennen")

    def test_falsche_argumentzahl(self):
        self.assertIn("erwartet 2", self._fehler("blur(A)"))

    def test_unbekannter_bildname(self):
        text = self._fehler("A + Z")
        self.assertIn("Bildname", text)
        self.assertIn("'Z'", text)

    def test_attributzugriff_wird_benannt(self):
        self.assertIn("Punkt", self._fehler("A.shape"))

    def test_index_wird_benannt(self):
        text = self._fehler("A[0]")
        self.assertIn("Klammern", text)
        self.assertIn("blau", text, "die Meldung soll den richtigen Weg zeigen")


class TestVerriegeltBleibtVerriegelt(unittest.TestCase):
    """Die Erweiterung darf kein Schlupfloch aufgemacht haben."""

    def setUp(self):
        self.A = _bild(8, 8)

    def test_kein_import(self):
        for ausdruck in ('__import__("os")', "open('x')", "eval('1')",
                         "().__class__", "A.__class__"):
            with self.subTest(ausdruck=ausdruck):
                with self.assertRaises(ValueError):
                    evaluate(ausdruck, {"A": self.A})

    def test_blur_mit_unsinnigem_radius_wird_abgelehnt(self):
        """Sonst haengt das Programm an einem Faltungskern von tausend Pixeln."""
        with self.assertRaises(ValueError):
            evaluate("blur(A, 5000)", {"A": self.A})

    def test_die_eingabe_wird_nicht_veraendert(self):
        vorher = self.A.copy()
        evaluate("A - med(A) + blur(A, 2)", {"A": self.A})
        np.testing.assert_array_equal(self.A, vorher)


if __name__ == "__main__":
    unittest.main(verbosity=2)
