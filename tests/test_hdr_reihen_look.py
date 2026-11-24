"""HDR: Reihen richtig erkennen und so hell wie die Kamera werden.

Gemessen am 24.11.2026 an Sony-ARW-Reihen (−1/0/+1 EV, `Y:\\Backup\\fell`, nur lokal):
* Die automatische Reihenerkennung machte aus 462 Aufnahmen EINE Reihe. PIL liest aus ARW keine
  Belichtungszeit (dann galt still „alles eine Reihe“), und selbst mit Zeiten ist der Rücksprung
  von +1 auf 0 EV genau Faktor 2 — die alte Regel verlangte „mehr als die Hälfte“.
* Das HDR war halb so hell wie die normale Aufnahme (0,44) mit 14 % fast schwarzer Fläche und
  weniger Schattenzeichnung als das Einzelbild. An das Kamerabild angeglichen: 1,00, 0,58 %.
"""
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HIER, ".."), os.path.join(HIER, "..", "core")]

import hdr  # noqa: E402


def _leise(*a, **k):
    pass


class _Zeiten:
    """read_exposure_times für einen Test ersetzen (echte Funktion, kein Mock)."""
    def __init__(self, zeiten):
        self.zeiten, self.alt = zeiten, None

    def __enter__(self):
        self.alt = hdr.read_exposure_times
        hdr.read_exposure_times = lambda paths: (None if self.zeiten is None
                                                 else np.asarray(self.zeiten[:len(paths)], np.float32))
        return self

    def __exit__(self, *a):
        hdr.read_exposure_times = self.alt


class TestReihenErkennen(unittest.TestCase):
    def test_sony_reihenfolge_null_minus_plus(self):
        pfade = ["f%03d.arw" % i for i in range(12)]
        with _Zeiten([1 / 4, 1 / 8, 1 / 2] * 4):
            g = hdr.split_brackets(pfade, log=_leise)
        self.assertEqual([len(x) for x in g], [3, 3, 3, 3])
        self.assertEqual(g[1], pfade[3:6])

    def test_minus_null_plus_und_fuenfer(self):
        with _Zeiten([1 / 8, 1 / 4, 1 / 2] * 3):
            self.assertEqual(len(hdr.split_brackets(["a%d" % i for i in range(9)], log=_leise)), 3)
        z = [1 / 60, 1 / 30, 1 / 15, 1 / 8, 1 / 4] * 2
        with _Zeiten(z):
            g = hdr.split_brackets(["b%d" % i for i in range(10)], log=_leise)
        self.assertEqual([len(x) for x in g], [5, 5])

    def test_eine_reihe(self):
        with _Zeiten([1 / 60, 1 / 30, 1 / 15, 1 / 8, 1 / 4]):
            self.assertEqual(len(hdr.split_brackets(["c%d" % i for i in range(5)], log=_leise)), 1)

    def test_ohne_zeiten_viele_bilder_klare_meldung(self):
        """Früher: still EINE Reihe aus allen Bildern."""
        with _Zeiten(None):
            with self.assertRaises(ValueError):
                hdr.split_brackets(["d%d" % i for i in range(30)], log=_leise)
            meldungen = []
            g = hdr.split_brackets(["e%d" % i for i in range(3)], log=meldungen.append)
        self.assertEqual(len(g), 1)
        self.assertTrue(meldungen)

    def test_kein_muster_klare_meldung(self):
        with _Zeiten([1 / 4, 1 / 4, 1 / 8, 1 / 2, 1 / 30, 1 / 4, 1 / 4]):
            with self.assertRaises(ValueError):
                hdr.split_brackets(["f%d" % i for i in range(7)], log=_leise)

    def test_exifread_liest_belichtungszeit(self):
        import piexif
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.jpg")
            cv2.imwrite(p, np.full((16, 16, 3), 100, np.uint8))
            piexif.insert(piexif.dump({"Exif": {piexif.ExifIFD.ExposureTime: (1, 8)}}), p)
            self.assertAlmostEqual(hdr._exposure_times_exifread([p])[0], 0.125)


def _szene(h=240, w=360):
    """Raum mit hellem Fenster (wie die Sony-Reihen): Radianz über ~8 EV."""
    rng = np.random.default_rng(1)
    rad = np.full((h, w), 0.05, np.float32)
    rad += cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 2) * 0.08
    rad[40:120, 220:330] = 1.6 + cv2.GaussianBlur(rng.random((80, 110)).astype(np.float32), (0, 0), 2)
    return rad


class TestHdrWieDieKamera(unittest.TestCase):
    def test_jpeg_reihe_so_hell_wie_die_normale_belichtung(self):
        import argparse
        import focus_cull_stack as F
        rad = _szene()
        with tempfile.TemporaryDirectory() as d:
            ein = os.path.join(d, "ein"); os.makedirs(ein)
            for i, ev in enumerate((0, -1, 1)):                  # Sony-Reihenfolge
                b = np.clip((rad * 2.0 ** ev) ** (1 / 2.2), 0, 1)
                cv2.imwrite(os.path.join(ein, "s_%d.jpg" % i),
                            cv2.cvtColor((b * 255 + 0.5).astype(np.uint8), cv2.COLOR_GRAY2BGR))
            normal = cv2.imread(os.path.join(ein, "s_0.jpg"))
            args = argparse.Namespace(prefix="", hdr_bracket=3, hdr_look="kamera", hdr_tonemap="reinhard",
                                      hdr_method="fusion", hdr_deghost="off", hdr_deghost_flow=False,
                                      no_align=True, web_jpg=False, export=None, raw_wb="camera")
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                ziel = F.run_hdr(ein, os.path.join(d, "arbeit"), args)
            erg = cv2.imread(os.path.join(ziel, "s_0_hdr.tif"))
        l_e = cv2.cvtColor(erg, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        l_n = cv2.cvtColor(normal, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        self.assertAlmostEqual(float(np.median(l_e) / np.median(l_n)), 1.0, delta=0.1)
        fenster = (slice(50, 110), slice(230, 320))
        self.assertLess(float((l_e[fenster] >= 0.99).mean()), float((l_n[fenster] >= 0.99).mean()))

    def test_oberflaeche_hat_kamera_als_vorgabe(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from ui.main_window import MainWindow
        w = MainWindow()
        self.assertEqual(w.hdr_look.currentData(), "kamera")
        w.close()


if __name__ == "__main__":
    unittest.main()
