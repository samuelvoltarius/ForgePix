#!/usr/bin/env python3
"""
ForgePix — Banding-Korrektur in beide Richtungen.

    python3 tests/test_banding_richtung.py

`--astro-banding-vertical` stand in der Hilfe („Banding spaltenweise statt zeilenweise
korrigieren"), wurde von argparse angenommen — und **nirgends im Programm gelesen**.
`astro.fix_banding` kann die Richtung seit jeher, der Wert wurde nur nie durchgereicht.

Das ist kein Schönheitsfehler: gemessen bewirkt die zeilenweise Korrektur auf einem Bild mit
Spalten-Banding **exakt nichts** (Streuung 0,01082 vorher wie nachher), während die spaltenweise
sie auf 0,00317 drückt. Wer Spalten-Banding hatte, setzte die Option und bekam keine Wirkung —
ohne dass irgendwo etwas dagegen sprach.

Gefunden wurde sie durch eine mechanische Prüfung aller 157 Kommandozeilen-Optionen darauf, ob
ihr Ziel überhaupt irgendwo gelesen wird. Sie war die einzige.
"""
import inspect
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro  # noqa: E402


def _szene(richtung, staerke=0.01, seed=5, h=120, w=120):
    """Ein flaches Bild mit Banding in einer Richtung."""
    rng = np.random.default_rng(seed)
    g = np.clip(rng.normal(0.05, 0.002, (h, w)), 0, 1).astype(np.float32)
    if richtung == "spalten":
        g = g + rng.normal(0, staerke, (1, w)).astype(np.float32)
    else:
        g = g + rng.normal(0, staerke, (h, 1)).astype(np.float32)
    return np.dstack([g] * 3).astype(np.float32)


def _spaltenstreuung(bgr):
    return float(np.std(bgr[:, :, 1].mean(axis=0)))


def _zeilenstreuung(bgr):
    return float(np.std(bgr[:, :, 1].mean(axis=1)))


class TestBandingRichtung(unittest.TestCase):

    def test_spaltenbanding_braucht_die_spaltenweise_korrektur(self):
        b = _szene("spalten")
        vorher = _spaltenstreuung(b)
        falsch = _spaltenstreuung(astro.fix_banding(b, strength=1.0, vertical=False))
        richtig = _spaltenstreuung(astro.fix_banding(b, strength=1.0, vertical=True))
        self.assertAlmostEqual(falsch, vorher, places=5,
                               msg="die zeilenweise Korrektur hat hier gar nichts getan — "
                                   "und genau das ist der Punkt der Option")
        self.assertLess(richtig, vorher * 0.5,
                        "spaltenweise: %.5f von %.5f" % (richtig, vorher))

    def test_zeilenbanding_braucht_die_zeilenweise_korrektur(self):
        b = _szene("zeilen")
        vorher = _zeilenstreuung(b)
        richtig = _zeilenstreuung(astro.fix_banding(b, strength=1.0, vertical=False))
        falsch = _zeilenstreuung(astro.fix_banding(b, strength=1.0, vertical=True))
        self.assertAlmostEqual(falsch, vorher, places=5)
        self.assertLess(richtig, vorher * 0.5)


class TestDurchgereicht(unittest.TestCase):
    """Die Richtung muss von der Kommandozeile bis zur Korrektur ankommen."""

    def test_die_stapel_funktionen_nehmen_die_richtung(self):
        for f in (astro.register_and_cache, astro.drizzle_stack):
            self.assertIn("banding_vertikal", inspect.signature(f).parameters,
                          "%s reicht die Banding-Richtung nicht durch" % f.__name__)

    def test_die_pipeline_gibt_sie_mit(self):
        import io
        pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core",
                            "focus_cull_stack.py")
        with io.open(pfad, encoding="utf-8") as fh:
            quelle = fh.read()
        self.assertIn("astro_banding_vertical", quelle,
                      "die Option wird nirgends gelesen")
        self.assertEqual(quelle.count("banding_vertikal=getattr("), 2,
                         "beide Stapelwege (normal und Drizzle) muessen sie mitgeben")

    def test_jede_option_wird_irgendwo_gelesen(self):
        """Die Pruefung, die diesen Fehler gefunden hat — als bleibender Test.

        Eine Option, die argparse annimmt und die niemand liest, ist ein Versprechen ohne
        Wirkung: sie steht in der Hilfe, der Benutzer setzt sie, und nichts passiert.
        """
        import ast
        import io
        import re
        wurzel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        cli = os.path.join(wurzel, "core", "focus_cull_stack.py")
        with io.open(cli, encoding="utf-8") as fh:
            src = fh.read()
        baum = ast.parse(src)
        optionen = []
        for k in ast.walk(baum):
            if isinstance(k, ast.Call) and getattr(k.func, "attr", "") == "add_argument":
                namen = [a.value for a in k.args
                         if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                lang = [n for n in namen if n.startswith("--")]
                if not lang:
                    continue
                dest = None
                for w in k.keywords:
                    if w.arg == "dest" and isinstance(w.value, ast.Constant):
                        dest = w.value.value
                optionen.append((lang[0], dest or lang[0][2:].replace("-", "_")))
        self.assertGreater(len(optionen), 100, "die Optionen wurden nicht gefunden")
        quellen = {}
        for ordner in ("core", "ui", "training"):
            p = os.path.join(wurzel, ordner)
            if not os.path.isdir(p):
                continue
            for w, _u, dateien in os.walk(p):
                if "__pycache__" in w:
                    continue
                for n in dateien:
                    if n.endswith(".py"):
                        try:
                            with io.open(os.path.join(w, n), encoding="utf-8") as fh:
                                quellen[os.path.join(w, n)] = fh.read()
                        except OSError:
                            pass
        tot = []
        for lang, dest in optionen:
            muster = [r"args\.%s\b" % re.escape(dest), r'"%s"' % re.escape(dest),
                      r"'%s'" % re.escape(dest)]
            treffer = 0
            for p, t in quellen.items():
                if p.endswith("focus_cull_stack.py"):
                    t = t.replace('add_argument("%s"' % lang, "")
                for m in muster:
                    treffer += len(re.findall(m, t))
            if treffer == 0:
                tot.append(lang)
        self.assertEqual(tot, [], "Optionen ohne jede Wirkung: %s" % tot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
