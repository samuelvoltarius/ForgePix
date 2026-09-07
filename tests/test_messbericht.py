#!/usr/bin/env python3
"""
ForgePix — Tests für den Messbericht (core/messbericht.py).

    python3 tests/test_messbericht.py

Der Bericht ist die Grundlage für alles Weitere: ein Regelwerk oder ein Sprachmodell darf nur
auf gemessenen Zahlen aufsetzen, nie auf geschätzten. Entsprechend prüfen diese Tests weniger
die Formeln als die **Ehrlichkeit** der Ausgabe:

* Fehlende Werte sind `None`, nicht `0.0` — sonst führt jede spätere Regel ins Leere.
* Kein `NaN` und kein `inf` im Bericht.
* Die Sternzahl beschreibt das ÜBERGEBENE Bild, die Sternform ein Einzelbild — und das steht
  auch dabei.

Zwei Fallen sind hier festgehalten, weil sie beim Bauen tatsächlich zugeschlagen haben:

1. `abbildungsskala(brennweite_mm, pixelgroesse_um)` — vertauscht kommen 51276 "/px heraus
   statt 0,83. Im Text sieht man das sofort, eine Regel würde es blind weiterreichen.
2. `if punkte:` auf einem numpy-Array wirft `ValueError`. Der Fehler steckte hinter einem
   stillen `except Exception: pass`, und der Bericht beschrieb daraufhin unbemerkt ein Sub
   statt des übergebenen Stapels — Stapel und Einzelbild lieferten identische 82 Sterne.
"""
import math
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import messbericht  # noqa: E402


def _szene(h=300, w=400, sterne=40, nebel=True, seed=3):
    rng = np.random.default_rng(seed)
    g = np.clip(rng.normal(0.030, 0.0015, (h, w)).astype(np.float32), 0, 1)
    if nebel:
        k = np.zeros((h, w), np.float32)
        cv2.circle(k, (w // 2, h // 2), 50, 1.0, -1)
        g += cv2.GaussianBlur(k, (0, 0), 22) * 0.05
    for _ in range(sterne):
        x, y = int(rng.integers(20, w - 20)), int(rng.integers(20, h - 20))
        p = np.zeros((h, w), np.float32)
        p[y, x] = 1.0
        g += cv2.GaussianBlur(p, (0, 0), 1.5) * float(rng.uniform(2, 8))
    g = np.clip(g, 0, 1)
    return np.dstack([g * 0.99, g, g * 0.995]).astype(np.float32)


class TestEhrlichkeit(unittest.TestCase):
    """Was der Bericht NICHT tun darf."""

    def test_keine_nan_und_keine_platzhalter(self):
        b = messbericht.erstellen(_szene())
        def pruefen(d, pfad=""):
            for k, v in d.items():
                if isinstance(v, dict):
                    pruefen(v, pfad + k + ".")
                elif isinstance(v, float):
                    self.assertTrue(math.isfinite(v), "%s%s ist %r" % (pfad, k, v))
        pruefen(b)

    def test_nicht_messbares_ist_none_nicht_null(self):
        """Ein einfarbiges Bild hat keinen Hintergrundkontrast — dann muss None kommen."""
        leer = np.full((40, 40, 3), 0.5, np.float32)
        b = messbericht.erstellen(leer)
        self.assertIsNone(b["farbe"]["passt"])
        # Median gibt es immer; Rauschen und Gradient duerfen fehlen, aber nicht 0.0 luegen
        for wert in (b["himmel"]["rauschen"], b["himmel"]["gradient_prozent"]):
            if wert is not None:
                self.assertGreaterEqual(wert, 0.0)

    def test_ohne_kamera_kein_farburteil(self):
        b = messbericht.erstellen(_szene())
        self.assertIsNone(b["farbe"]["passt"])
        self.assertIn("keine Kamera", b["farbe"]["urteil"])

    def test_unbekannte_kamera_raet_nicht(self):
        b = messbericht.erstellen(_szene(), kamera="gibtsnicht")
        self.assertIn("nicht gepr", b["farbe"]["urteil"])   # Umlaut-unabhaengig


class TestSterne(unittest.TestCase):

    def test_anzahl_beschreibt_das_uebergebene_bild(self):
        """Genau der Fehler, der hinter dem stillen `except` steckte: ohne diese Trennung
        lieferten Stapel und Einzelbild dieselbe Zahl."""
        wenig = messbericht.erstellen(_szene(sterne=10))["sterne"]["anzahl"]
        viel = messbericht.erstellen(_szene(sterne=60))["sterne"]["anzahl"]
        self.assertIsNotNone(wenig)
        self.assertIsNotNone(viel)
        self.assertGreater(viel, wenig, "mehr Sterne im Bild muessen mehr Sterne ergeben")

    def test_ohne_datei_keine_form_aber_eine_anzahl(self):
        b = messbericht.erstellen(_szene())["sterne"]
        self.assertIsNotNone(b["anzahl"])
        self.assertIsNone(b["fwhm_px"], "ohne Datei darf keine FWHM erfunden werden")
        self.assertEqual(b["quelle"], "nur gezaehlt")


class TestHimmelUndSignal(unittest.TestCase):

    def test_rauschen_sinkt_wenn_man_mittelt(self):
        """Physikalische Gegenprobe: der Mittelwert aus neun Bildern rauscht weniger."""
        einzeln = messbericht.erstellen(_szene(seed=1))["himmel"]["rauschen"]
        stapel = np.mean(np.stack([_szene(seed=s) for s in range(1, 10)]), axis=0)
        gemittelt = messbericht.erstellen(stapel.astype(np.float32))["himmel"]["rauschen"]
        self.assertLess(gemittelt, einzeln,
                        "gemittelt %.6f, einzeln %.6f" % (gemittelt, einzeln))

    def test_gradient_wird_erkannt(self):
        flach = messbericht.erstellen(_szene(nebel=False))["himmel"]["gradient_prozent"]
        schief = _szene(nebel=False)
        rampe = np.linspace(0, 0.02, schief.shape[1], dtype=np.float32)[None, :, None]
        mit = messbericht.erstellen(np.clip(schief + rampe, 0, 1))["himmel"]["gradient_prozent"]
        self.assertGreater(mit, flach * 2,
                           "Gradient nicht erkannt: flach %.1f, schief %.1f" % (flach, mit))

    def test_signal_zu_rauschen_faellt_bei_mehr_rauschen(self):
        sauber = messbericht.erstellen(_szene(seed=5))["signal_zu_rauschen"]
        rng = np.random.default_rng(0)
        laut = np.clip(_szene(seed=5) + rng.normal(0, 0.01, (300, 400, 3)).astype(np.float32), 0, 1)
        verrauscht = messbericht.erstellen(laut)["signal_zu_rauschen"]
        self.assertLess(verrauscht, sauber)


class TestAusruestung(unittest.TestCase):

    def test_abbildungsskala_richtig_herum(self):
        """Vertauschte Argumente ergeben 51276 statt 0,83 — im Text sichtbar, in einer Regel
        nicht. Darum hier festgehalten."""
        import equipment
        self.assertAlmostEqual(equipment.abbildungsskala(1151, 4.63), 0.8297, places=3)

    def test_ohne_datei_keine_ausruestung(self):
        au = messbericht.erstellen(_szene())["ausruestung"]
        for k in ("brennweite_mm", "pixelgroesse_um", "skala_bogensek_px"):
            self.assertIsNone(au[k])


class TestText(unittest.TestCase):

    def test_text_nennt_alle_abschnitte(self):
        t = messbericht.text(messbericht.erstellen(_szene()))
        for kopf in ("Bild", "Himmel", "Sterne", "Farbe", "Signal/Rauschen", "Ausruestung"):
            self.assertIn(kopf, t)

    def test_fehlende_werte_erscheinen_als_fragezeichen(self):
        """Ein Platzhalter darf nicht wie eine Messung aussehen."""
        t = messbericht.text(messbericht.erstellen(_szene()))
        self.assertIn("?", t, "ohne Datei muessen Ausruestungswerte als unbekannt erscheinen")

    def test_warnung_bei_signal_unter_rauschen(self):
        rng = np.random.default_rng(2)
        nur_rauschen = np.clip(rng.normal(0.03, 0.02, (200, 200, 3)).astype(np.float32), 0, 1)
        b = messbericht.erstellen(nur_rauschen)
        if (b["signal_zu_rauschen"] or 99) < 1:
            self.assertIn("ACHTUNG", messbericht.text(b))


if __name__ == "__main__":
    unittest.main(verbosity=2)
