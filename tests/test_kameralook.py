"""Kamera-Look für RAW-Entwicklung (core/kameralook.py).

Gemessen am 23.11.2026 an 19 RAWs von 18 Herstellern: die neutrale Entwicklung war im Median
nur 0,58 so hell wie das Kamerabild, mit Kamera-Look 0,991. Diese Tests halten die Eigenschaften
fest, die dabei wichtig waren — jede mit der Fehlerform, die sie verhindert.
"""
import glob
import os
import sys
import unittest

import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, "..", "core"))

import kameralook  # noqa: E402


def _still(*a, **k):
    pass


def _szene(h=240, w=320, seed=1):
    """Dunkle, bunte Szene mit Verlauf bis in helle Lichter (wie eine neutrale RAW-Entwicklung)."""
    rng = np.random.default_rng(seed)
    y = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :].repeat(h, 0)
    b = np.stack([y * 0.30, y * 0.45, y * 0.60], axis=-1)
    b[: h // 3, : w // 3] = (0.05, 0.25, 0.10)
    b += rng.normal(0, 0.005, b.shape).astype(np.float32)
    return np.clip(b, 0, 1)


def _hell(b):
    return b.astype(np.float32) @ np.array([0.0722, 0.7152, 0.2126], np.float32)


class TestAngleichen(unittest.TestCase):
    def test_median_folgt_der_vorschau(self):
        """Die Referenz ist heller (wie das Kamera-JPEG): der Median muss ihr folgen.
        Ohne Angleichung (alte treue Entwicklung) lag er bei 0,58 der Kamera."""
        bild = _szene()
        ref = (np.clip(bild * 1.8, 0, 1) ** 0.8 * 255).astype(np.uint8)
        aus, ber = kameralook.angleichen(bild, ref, log=_still)
        ziel = float(np.median(_hell(ref.astype(np.float32) / 255)))
        ist = float(np.median(_hell(aus)))
        self.assertLess(abs(ist / ziel - 1.0), 0.05, (ist, ziel))
        self.assertEqual(ber["art"], "Kamera-Vorschau")

    def test_rueckfall_ohne_vorschau(self):
        """Ohne Vorschau (Sigma-fp-DNG) gilt eine gemeldete Filmkurve mit Median 0,40."""
        meldungen = []
        aus, ber = kameralook.angleichen(_szene(), None, log=meldungen.append)
        self.assertAlmostEqual(float(np.median(_hell(aus))), 0.40, delta=0.03)
        self.assertIn("Rückfall", ber["art"])
        self.assertAlmostEqual(ber["helligkeit_nachher"], float(np.median(_hell(aus))), delta=0.02)
        self.assertTrue(any("keine brauchbare Vorschau" in m for m in meldungen))

    def test_kein_zusaetzliches_ausbrennen(self):
        """Brennt das Kamera-JPEG aus, darf das Ergebnis das nicht übernehmen.
        Erste Fassung: Phase One 26 %, Samsung 25 % weiße Pixel statt 6 % bzw. 0 %."""
        bild = np.clip(_hell(_szene())[..., None].repeat(3, -1), 0, 1)   # grau: Weiß ist erreichbar
        ref = (np.clip(bild * 3.0, 0, 1) * 255).astype(np.uint8)      # viel ausgebrannt
        aus, ber = kameralook.angleichen(bild, ref, log=_still)
        weiss_ref = float((ref.min(axis=-1) >= 250).mean())
        weiss_aus = float((aus.min(axis=-1) >= 250 / 255).mean())
        self.assertGreater(weiss_ref, 0.2)
        self.assertLess(weiss_aus, 0.02, weiss_aus)
        self.assertIn("schulter_ab", ber)

    def test_kein_kanal_am_anschlag(self):
        """Erste Fassung skalierte die Kanäle im Verhältnis zur Helligkeit: bei dunklen, bunten
        Bildern lief ein Kanal an den Anschlag (Sigma fp 52 % der Pixel)."""
        bild = _szene() * 0.4
        aus, _ = kameralook.angleichen(bild, None, log=_still)
        anschlag = float((aus.max(axis=-1) >= 0.999).mean())
        self.assertLess(anschlag, 0.01, anschlag)

    def test_lichter_bleiben_gestuft(self):
        """Ein steigender Verlauf bleibt steigend — keine Umkehr in der Schulter."""
        rampe = np.linspace(0, 1, 2048, dtype=np.float32)[None, :, None].repeat(160, 0).repeat(3, 2)
        ref = (np.clip(rampe * 2.0, 0, 1) * 255).astype(np.uint8)
        aus, _ = kameralook.angleichen(rampe, ref, log=_still)
        zeile = _hell(aus)[80]
        self.assertTrue(np.all(np.diff(zeile) >= -1e-5))
        # oben noch Zeichnung: alte Schulter 0,0003, jetzige 0,0072 (Grenze 1,5 Stufen in 8 bit)
        self.assertGreater(zeile[-1] - zeile[-200], 1.5 / 255)

    def test_datentyp_bleibt(self):
        b16 = (_szene() * 65535).astype(np.uint16)
        aus, _ = kameralook.angleichen(b16, None, log=_still)
        self.assertEqual(aus.dtype, np.uint16)
        self.assertEqual(aus.shape, b16.shape)


class TestEinbindung(unittest.TestCase):
    def test_option_in_der_hilfe(self):
        import subprocess
        aus = subprocess.run([sys.executable, os.path.join(HIER, "..", "core", "focus_cull_stack.py"), "--help"],
                             capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        self.assertIn("--raw-look", aus.stdout)

    def test_ungueltiges_aussehen(self):
        import focus_cull_stack as fcs
        with self.assertRaises(ValueError):
            fcs.develop_raw_to_bgr("gibt-es-nicht.dng", look="bunt")


@unittest.skipUnless(glob.glob(os.path.join(HIER, "..", "testdata", "raw", "*")), "testdata/raw fehlt")
class TestEchteDatei(unittest.TestCase):
    def test_echte_rohdatei_nahe_an_der_kamera(self):
        """An einer echten RAW mit Vorschau: Helligkeit innerhalb ±30 % des Kamerabilds."""
        import cv2
        import focus_cull_stack as fcs
        for p in sorted(glob.glob(os.path.join(HIER, "..", "testdata", "raw", "*"))):
            ref = kameralook.vorschau(p)
            if ref is None:
                continue
            bild = fcs.develop_raw_to_bgr(p, look="kamera")
            klein = cv2.resize(bild, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_AREA)
            skala = 65535.0 if klein.dtype == np.uint16 else 255.0
            v = float(np.median(_hell(klein / skala))) / max(float(np.median(_hell(ref / 255.0))), 1e-4)
            self.assertLess(abs(v - 1.0), 0.30, (p, v))
            return
        self.skipTest("keine RAW mit Vorschau")


if __name__ == "__main__":
    unittest.main()
