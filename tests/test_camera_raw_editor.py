"""Camera-Raw-Editor (ui/components.adjust_image, AdjustDialog) und seine Bausteine in core/develop.py.

Am 23.11.2026 geprüft, was im Editor wirklich einstellbar ist. Gefunden: Rauschminderung,
Color Grading, Vignette, Körnung und Perspektive fehlten; Dunst und Capture-Schärfung
verschluckten Fehler mit `except: pass` (der Regler tat dann kommentarlos nichts).
Jeder Test hier misst eine Wirkung an einem Bild, nicht nur, dass etwas durchläuft.
"""
import os
import sys
import unittest

import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HIER, ".."), os.path.join(HIER, "..", "core")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2  # noqa: E402
import develop  # noqa: E402


def _verlauf(h=200, w=300, rausch=0.0, seed=0):
    rng = np.random.default_rng(seed)
    f = np.linspace(0.05, 0.95, w, dtype=np.float32)[None, :, None].repeat(h, 0).repeat(3, 2)
    if rausch:
        f = f + rng.normal(0, rausch, f.shape).astype(np.float32)
    return np.clip(f, 0, 1)


def _adjust():
    from ui.components import adjust_image
    return adjust_image


class TestNullIstNull(unittest.TestCase):
    def test_alle_regler_auf_null_aendern_nichts(self):
        """Ohne Anpassung kommt das Bild Wert für Wert unverändert zurück (8 bit)."""
        img = (np.arange(256, dtype=np.uint8)[None, :, None].repeat(4, 0).repeat(3, 2))
        out = _adjust()(img, {})
        self.assertEqual(int(np.abs(out.astype(int) - img).max()), 0)


class TestRauschminderung(unittest.TestCase):
    def test_luminanz_senkt_rauschen_und_erhaelt_kante(self):
        img = np.full((160, 160, 3), 0.3, np.float32)
        img[:, 80:] = 0.7
        rng = np.random.default_rng(3)
        # reines Helligkeitsrauschen, gemessen an der Helligkeit (erste Fassung des Tests maß alle
        # Kanäle und damit Farbrauschen mit, das dieser Regler gar nicht anfassen soll)
        verrauscht = np.clip(img + rng.normal(0, 0.03, (160, 160, 1)).astype(np.float32), 0, 1)
        b8 = (verrauscht * 255 + 0.5).astype(np.uint8)
        out = develop.luma(_adjust()(b8, {"nr_luma": 60}).astype(np.float32) / 255)
        vorher = float(develop.luma(b8.astype(np.float32) / 255)[20:140, 10:70].std())
        nachher = float(out[20:140, 10:70].std())
        self.assertLess(nachher, 0.6 * vorher, (vorher, nachher))
        kante = float(out[:, 82:90].mean() - out[:, 70:78].mean())
        self.assertGreater(kante, 0.35, kante)                   # Sprung 0,4 bleibt fast ganz

    def test_farbe_senkt_farbrauschen(self):
        rng = np.random.default_rng(4)
        img = np.full((160, 160, 3), 0.5, np.float32)
        img += rng.normal(0, 0.04, img.shape).astype(np.float32)   # je Kanal = Farbrauschen
        b8 = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
        def farbstreuung(b):
            f = b.astype(np.float32) / 255
            return float((f - f.mean(axis=-1, keepdims=True)).std())
        self.assertLess(farbstreuung(_adjust()(b8, {"nr_color": 60})), 0.6 * farbstreuung(b8))


class TestColorGrading(unittest.TestCase):
    def test_schatten_blau_lichter_warm_helligkeit_bleibt(self):
        img = _verlauf()
        out = develop.color_grade(img, schatten=(240, 80), lichter=(40, 80))
        dl = float(np.abs(develop.luma(out) - develop.luma(img)).mean())
        self.assertLess(dl, 0.01, dl)
        dunkel, hell = out[:, :40], out[:, -40:]
        self.assertGreater(float((dunkel[..., 0] - dunkel[..., 2]).mean()), 0.03)   # B > R
        self.assertGreater(float((hell[..., 2] - hell[..., 0]).mean()), 0.03)       # R > B

    def test_stärke_ausserhalb_wird_gemeldet(self):
        with self.assertRaises(ValueError):
            develop.color_grade(_verlauf(), schatten=(240, 150))


class TestEffekte(unittest.TestCase):
    def test_vignette_dunkelt_ecken_nicht_mitte(self):
        img = np.full((200, 300, 3), 0.5, np.float32)
        out = develop.vignette_effect(img, -60)
        self.assertLess(float(out[:10, :10].mean()), 0.35)
        self.assertAlmostEqual(float(out[95:105, 145:155].mean()), 0.5, delta=0.005)
        self.assertGreater(float(develop.vignette_effect(img, 60)[:10, :10].mean()), 0.65)

    def test_korn_ist_gleich_in_vorschau_und_vollbild(self):
        """Die Vorschau ist verkleinert. Ihr Korn muss dem verkleinerten Vollbild gleichen,
        sonst sieht man im Editor etwas anderes, als gespeichert wird."""
        img = np.full((1500, 2000, 3), 0.5, np.float32)
        for groesse in (0, 50, 100):
            voll = develop.add_grain(img, 50, groesse)
            klein_aus_voll = cv2.resize(voll, (400, 300), interpolation=cv2.INTER_AREA).std()
            vorschau = develop.add_grain(cv2.resize(img, (400, 300)), 50, groesse).std()
            self.assertLess(abs(vorschau / klein_aus_voll - 1), 0.15, (groesse, vorschau, klein_aus_voll))

    def test_korn_wiederholbar(self):
        img = np.full((100, 100, 3), 0.5, np.float32)
        self.assertTrue(np.array_equal(develop.add_grain(img, 40), develop.add_grain(img, 40)))


class TestPerspektive(unittest.TestCase):
    def test_senkrecht_zieht_oben_zusammen(self):
        img = np.zeros((200, 300), np.uint8)
        img[:, 20] = 255; img[:, 279] = 255                      # zwei senkrechte Linien
        out = develop.perspective(img, 50)
        oben = np.nonzero(out[2] > 128)[0]; unten = np.nonzero(out[-3] > 128)[0]
        self.assertLess(oben.max() - oben.min(), unten.max() - unten.min() - 20)
        out2 = develop.perspective(img, -50)
        oben = np.nonzero(out2[2] > 128)[0]; unten = np.nonzero(out2[-3] > 128)[0]
        self.assertGreater(oben.max() - oben.min(), unten.max() - unten.min() + 20)


class TestKeineStillenFehler(unittest.TestCase):
    def test_fehler_im_baustein_kommt_an(self):
        """Gegenprobe zum früheren `except: pass`: ein kaputter Baustein muss auffallen."""
        alt = develop.dehaze
        def kaputt(*a, **k):
            raise RuntimeError("absichtlich kaputt")
        develop.dehaze = kaputt
        try:
            with self.assertRaises(RuntimeError):
                _adjust()(np.full((20, 20, 3), 100, np.uint8), {"dehaze": 50})
        finally:
            develop.dehaze = alt


class TestDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_neue_regler_sind_da_und_wirken(self):
        from ui.components import AdjustDialog
        img = (_verlauf(120, 160) * 255 + 0.5).astype(np.uint8)
        dlg = AdjustDialog(img, os.path.join(HIER, "nicht_gespeichert.jpg"))
        for k in ("nr_luma", "nr_color", "cg_s_amt", "cg_balance", "vignette", "grain", "grain_size"):
            self.assertIn(k, dlg._slider_widgets)
        self.assertEqual(dlg._slider_widgets["grain"].minimum(), 0)
        self.assertEqual(dlg._slider_widgets["cg_s_hue"].maximum(), 360)
        self.assertIn("persp_v", dlg.geo_sliders)
        dlg._slider_widgets["vignette"].setValue(-80)
        dlg.geo_sliders["persp_v"].setValue(40)
        dlg._update()
        g = dlg._geometry(dlg.base)
        out = dlg._masked(g, __import__("ui.components", fromlist=["x"]).adjust_image(g, dlg._params()))
        self.assertLess(float(out[:5, :5].mean()), float(img[:5, :5].mean()) * 0.8)
        self.assertEqual(dlg.fehler.text(), "")
        dlg._reset()
        self.assertEqual(dlg.vals["grain_size"], 25)
        self.assertEqual(dlg.persp["persp_v"], 0)
        dlg.close()

    def test_fehler_steht_im_dialog(self):
        from ui.components import AdjustDialog
        alt = develop.dehaze
        def kaputt(*a, **k):
            raise RuntimeError("absichtlich kaputt")
        dlg = AdjustDialog(np.full((60, 80, 3), 100, np.uint8), os.path.join(HIER, "nicht_gespeichert.jpg"))
        develop.dehaze = kaputt
        try:
            dlg.vals["dehaze"] = 40
            dlg._update()
            self.assertIn("absichtlich kaputt", dlg.fehler.text())
        finally:
            develop.dehaze = alt
            dlg.close()


if __name__ == "__main__":
    unittest.main()
