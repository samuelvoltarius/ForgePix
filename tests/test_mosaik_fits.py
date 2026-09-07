#!/usr/bin/env python3
"""
ForgePix — der Mosaik-Modus und FITS.

    python3 tests/test_mosaik_fits.py

Zwei Fehler, die an echten Seestar-Mosaikdaten (M 31, 124 Kacheln) aufgefallen sind:

1. **`cv2.imread` kann keine FITS lesen** und gibt `None` zurück. Die Kacheln wurden danach
   still verworfen, und `stitch` meldete „Mindestens 2 überlappende Kacheln nötig" — eine
   Aussage über die Überlappung, obwohl das Problem das Lesen war. Damit scheiterte **jeder**
   Mosaik-Lauf mit Astro-Daten, denn FITS ist das Format, in dem Astrokameras aufnehmen.
2. **Ein erwartbarer Fehlschlag kam als Traceback.** Auf einem Sternfeld schätzt der
   Panorama-Zusammensetzer die Brennweite aus Merkmalspaaren; ohne Textur geht das gründlich
   daneben. An den echten Daten wollte er **2,7 TB** belegen, und der Benutzer fand einen
   `cv2.error`-Traceback im Protokoll statt einer Erklärung.
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import cv2  # noqa: E402

import mosaic  # noqa: E402
from constants import ForgePixFehler  # noqa: E402


def _stille(*a, **k):
    pass


class TestFitsKachel(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_mos_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _fits(self, name="k.fit", h=64, w=96):
        from astropy.io import fits
        rng = np.random.default_rng(4)
        a = np.clip(rng.normal(0.03, 0.002, (h, w)), 0, 1).astype(np.float32)
        for _ in range(12):                                   # ein paar Sterne
            y, x = int(rng.integers(6, h - 6)), int(rng.integers(6, w - 6))
            a[y, x] = 0.8
        p = os.path.join(self.d, name)
        fits.writeto(p, a)
        return p

    def test_fits_kachel_wird_gelesen(self):
        """Vorher: None, und die Kachel verschwand stillschweigend."""
        bild = mosaic._kachel_lesen(self._fits(), log=_stille)
        self.assertIsNotNone(bild, "FITS-Kachel nicht gelesen")
        self.assertEqual(bild.dtype, np.uint8)
        self.assertEqual(bild.ndim, 3, "der Zusammensetzer braucht drei Kanaele")

    def test_gegenprobe_cv2_kann_es_nicht(self):
        """Damit klar bleibt, warum es die eigene Leseroutine ueberhaupt gibt."""
        from constants import imread
        self.assertIsNone(imread(self._fits(), cv2.IMREAD_UNCHANGED),
                          "cv2 liest FITS inzwischen — dann waere der Umweg unnoetig")

    def test_gestreckt_und_nicht_schwarz(self):
        """Eine lineare Astro-Aufnahme in 8 Bit ist fast schwarz; darin findet kein
        Merkmalsdetektor etwas. Sie wird deshalb fuer das Zusammensetzen gestreckt."""
        bild = mosaic._kachel_lesen(self._fits(), log=_stille)
        self.assertGreater(float(bild.mean()), 8.0,
                           "die Kachel ist praktisch schwarz (Mittel %.1f)" % bild.mean())

    def test_unlesbare_datei_gibt_None_und_meldet_sich(self):
        p = os.path.join(self.d, "kaputt.fit")
        with open(p, "wb") as fh:
            fh.write(b"kein FITS")
        meldungen = []
        self.assertIsNone(mosaic._kachel_lesen(p, log=meldungen.append))
        self.assertTrue(meldungen, "eine unlesbare Kachel muss sich melden")

    def test_zu_wenige_kacheln_nennt_die_zahl(self):
        """Frueher stand dort nur "Mindestens 2 ueberlappende Kacheln noetig" — auch dann,
        wenn in Wahrheit gar nichts gelesen werden konnte."""
        with self.assertRaises(ForgePixFehler) as ctx:
            mosaic.stitch([self._fits("a.fit")], log=_stille)
        self.assertIn("lesbare", str(ctx.exception))


class TestFehlerWerdenErklaert(unittest.TestCase):

    def test_speicherfehler_wird_zu_einer_erklaerung(self):
        """Der Panorama-Zusammensetzer wollte an echten Sternfeld-Kacheln 2,7 TB belegen.
        Das ist ein erwartbarer Fehlschlag und gehoert in eine Meldung, nicht in einen
        Traceback."""
        from constants import imwrite
        d = tempfile.mkdtemp(prefix="fp_mos2_")
        self.addCleanup(shutil.rmtree, d, True)
        rng = np.random.default_rng(1)
        pfade = []
        for i in range(2):
            p = os.path.join(d, "k%d.png" % i)
            imwrite(p, rng.integers(0, 255, (40, 60, 3), dtype=np.uint8))
            pfade.append(p)

        class _Platzt:
            def stitch(self, _imgs):
                raise cv2.error("Insufficient memory: Failed to allocate 2704018472100 bytes")

        echt = cv2.Stitcher_create
        cv2.Stitcher_create = lambda *a, **k: _Platzt()
        self.addCleanup(lambda: setattr(cv2, "Stitcher_create", echt))
        with self.assertRaises(ForgePixFehler) as ctx:
            mosaic.stitch(pfade, detail=False, log=_stille)
        text = str(ctx.exception)
        self.assertIn("Sternfeld", text, "die Meldung muss den Grund nennen")
        self.assertNotIn("2704018472100", text, "die Rohzahl hilft niemandem")

    def test_alle_fehler_sind_forgepixfehler(self):
        """ForgePixFehler wird oben als verstaendliche Zeile ausgegeben, ein nacktes
        RuntimeError als Traceback-Wand."""
        import inspect
        quelle = inspect.getsource(mosaic)
        self.assertNotIn("raise RuntimeError(", quelle,
                         "hier wird noch ein nacktes RuntimeError geworfen")


if __name__ == "__main__":
    unittest.main(verbosity=2)
