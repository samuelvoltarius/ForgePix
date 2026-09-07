#!/usr/bin/env python3
"""
ForgePix — die eigenen KI-Modelle muessen im Stapel-Ablauf ueberhaupt ankommen koennen.

    python3 tests/test_ki_im_ablauf.py

Befund, der zu diesen Tests gefuehrt hat: `core/focus_cull_stack.py` importierte `ai_restore`
an KEINER Stelle. ForgePix liefert vier eigene Modelle mit (Hintergrund, Entrauschen,
Schaerfen, Sterntrennung), und der automatische Ablauf hat nie eines davon angefasst —
erreichbar waren sie nur ueber Dialoge in der Oberflaeche, ueber Rezepte und ueber `--model`.
Wer stapelt, bekam sie nie zu sehen, auch dann nicht, wenn das externe Werkzeug fehlte, das
denselben Schritt haette machen sollen.

Die Regel, die jetzt gilt und hier festgehalten wird:

* freigegeben (`release_approved`)  -> laeuft automatisch mit
* experimentell                     -> nur mit `--ki-experimentell`
* `--ki-aus`                        -> gar nichts, auch nichts Freigegebenes

Warum nicht einfach alles automatisch? Weil gemessen wurde, was die Modelle heute koennen
(M51, 800x800-Ausschnitte, gegen den klassischen Weg):

    Hintergrund   klassisch Gradient 0,91 -> 0,43 %   Modell 0,91 -> 0,99 %   (schlechter)
    Entrauschen   klassisch Feinstruktur 0,001692 -> 0,001308
                  Modell    Feinstruktur 0,001692 -> 0,001503 bei gleichem Rauschen  (besser)
    Schaerfen     klassisch Feinstruktur x2,4 auf der Galaxie, Modell x1,18  (schlechter)

Ein ungeprueftes Modell in jedes Bild zu rechnen waere genau die Art Fehler, die durchlaeuft
und ein plausibles Ergebnis liefert. Der Riegel bleibt — er haengt jetzt nur an etwas.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import focus_cull_stack  # noqa: E402


def _args(**kw):
    grund = dict(ki_aus=False, ki_experimentell=False, ki_staerke=0.5,
                 ki_geraet="auto", ki_modellordner=None)
    grund.update(kw)
    return argparse.Namespace(**grund)


class TestModellauswahl(unittest.TestCase):
    """Die Auswahl, gegen einen selbst gebauten Modellordner — unabhaengig davon, was
    gerade mitgeliefert wird."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_ki_")
        self.addCleanup(shutil.rmtree, self.d, True)

    def _modell(self, kennung, aufgabe, freigegeben):
        """Ein Manifest schreiben, das `ai_restore.list_models` lesen kann."""
        ordner = os.path.join(self.d, kennung)
        os.makedirs(ordner)
        # Eine ONNX-Datei, die es gibt: sonst meldet list_models `available: False` und der
        # Test pruefte nur, dass kaputte Modelle nicht genommen werden.
        echt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "assets", "models", "forgepix-denoise-mono-v2", "model.onnx")
        if not os.path.exists(echt):
            self.skipTest("kein mitgeliefertes Modell zum Kopieren vorhanden")
        shutil.copy(echt, os.path.join(ordner, "model.onnx"))
        import hashlib
        with open(os.path.join(ordner, "model.onnx"), "rb") as fh:
            digest = hashlib.file_digest(fh, "sha256").hexdigest()
        manifest = dict(schema_version=1, id=kennung, task=aufgabe, model_file="model.onnx",
                        sha256=digest, channels=1, tile_size=256, halo=32,
                        normalization="affine_percentile_v1", output="complete_target",
                        status="stable" if freigegeben else "experimental",
                        release_approved=bool(freigegeben), license="MIT",
                        onnx_opset=17)
        with open(os.path.join(ordner, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        return ordner

    def test_freigegebene_modelle_laufen_automatisch(self):
        self._modell("probe-denoise", "denoise", freigegeben=True)
        auswahl = focus_cull_stack._ki_modelle(_args(ki_modellordner=self.d),
                                               log=lambda *a: None)
        self.assertEqual(auswahl.get("denoise"), "probe-denoise",
                         "ein freigegebenes Modell muss ohne Schalter genommen werden")

    def test_experimentelle_bleiben_ohne_schalter_aus(self):
        self._modell("probe-exp", "denoise", freigegeben=False)
        auswahl = focus_cull_stack._ki_modelle(_args(ki_modellordner=self.d),
                                               log=lambda *a: None)
        self.assertEqual(auswahl, {},
                         "ein experimentelles Modell darf nicht von selbst mitlaufen")

    def test_experimentelle_mit_schalter_an(self):
        self._modell("probe-exp", "denoise", freigegeben=False)
        auswahl = focus_cull_stack._ki_modelle(
            _args(ki_modellordner=self.d, ki_experimentell=True), log=lambda *a: None)
        self.assertEqual(auswahl.get("denoise"), "probe-exp")

    def test_ki_aus_schaltet_auch_freigegebene_ab(self):
        self._modell("probe-denoise", "denoise", freigegeben=True)
        auswahl = focus_cull_stack._ki_modelle(
            _args(ki_modellordner=self.d, ki_aus=True), log=lambda *a: None)
        self.assertEqual(auswahl, {})

    def test_freigegeben_hat_vorrang_vor_experimentell(self):
        """Zwei Modelle fuer dieselbe Aufgabe: das gepruefte gewinnt."""
        self._modell("probe-exp", "denoise", freigegeben=False)
        self._modell("probe-stabil", "denoise", freigegeben=True)
        auswahl = focus_cull_stack._ki_modelle(
            _args(ki_modellordner=self.d, ki_experimentell=True), log=lambda *a: None)
        self.assertEqual(auswahl.get("denoise"), "probe-stabil")


class TestAnwendung(unittest.TestCase):

    def test_ohne_modell_bleibt_das_bild_unveraendert(self):
        bild = np.full((64, 64), 0.04, np.float32)
        aus, gelaufen = focus_cull_stack._ki_anwenden(bild, "denoise", _args(),
                                                      log=lambda *a: None)
        self.assertFalse(gelaufen)
        self.assertIs(aus, bild, "ohne Modell darf nichts kopiert oder veraendert werden")

    def test_ein_fehlschlag_faellt_auf_den_klassischen_weg_zurueck(self):
        """Wenn das Modell scheitert, muss der Aufrufer das ERFAHREN und weiterrechnen —
        nicht mit einem halben Ergebnis dastehen."""
        bild = np.full((64, 64), 0.04, np.float32)
        args = _args(ki_experimentell=True)
        args._ki_auswahl = {"denoise": "gibt-es-nicht"}
        zeilen = []
        aus, gelaufen = focus_cull_stack._ki_anwenden(bild, "denoise", args,
                                                      log=zeilen.append)
        self.assertFalse(gelaufen, "ein Fehlschlag darf nicht als Erfolg gelten")
        self.assertIs(aus, bild)
        self.assertTrue(any("klassischer Weg" in z for z in zeilen),
                        "der Fehlschlag wird nicht gemeldet: %s" % zeilen)

    def test_die_mitgelieferten_modelle_bleiben_im_normalbetrieb_aus(self):
        """Heute ist keines der vier freigegeben. Aendert sich das, faellt es hier auf —
        und dann gehoert die Messung wiederholt, bevor es in jedes Bild rechnet."""
        auswahl = focus_cull_stack._ki_modelle(_args(), log=lambda *a: None)
        self.assertEqual(auswahl, {},
                         "ein mitgeliefertes Modell wurde freigegeben (%s) — bitte erst "
                         "gegen den klassischen Weg messen" % auswahl)


if __name__ == "__main__":
    unittest.main(verbosity=2)
