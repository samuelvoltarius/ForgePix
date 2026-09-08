#!/usr/bin/env python3
"""
ForgePix — die klassischen Werkzeuge ohne KI.

    python3 tests/test_klassiker.py

Vier Verfahren, die es in PixInsight gibt und die ForgePix fehlten. Jedes wird hier gegen
eine BEKANNTE Wahrheit geprueft, nicht gegen sich selbst — bei einem Verfahren, das ein Bild
"schoener" macht, ist das der einzige Weg, Wirkung von Einbildung zu trennen.

Und jedes hat eine GEGENPROBE: was passiert, wenn es nichts zu tun gibt? Ein Filter, der auch
ein sauberes Bild veraendert, richtet mehr Schaden an als Nutzen.
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import klassiker  # noqa: E402
import annotation  # noqa: E402


class TestSuperbias(unittest.TestCase):
    """Ein Bias ist fast nur Struktur. Superbias behaelt sie und wirft das Rauschen weg."""

    def _daten(self, n=20, rauschen=0.002):
        rng = np.random.default_rng(5)
        h, w = 120, 160
        struktur = (0.05
                    + np.sin(np.arange(w) / 7.0)[None, :] * 0.004      # Spaltenmuster
                    + np.cos(np.arange(h) / 11.0)[:, None] * 0.003)    # Zeilenmuster
        bias = [np.float32(struktur + rng.normal(0, rauschen, (h, w))) for _ in range(n)]
        return np.float32(struktur), bias

    def test_naeher_an_der_wahrheit_als_ein_median(self):
        """Der Punkt des Verfahrens: das Modell muss die WAHRE Struktur besser treffen als
        der schlichte Median derselben Aufnahmen."""
        wahrheit, bias = self._daten()
        median = np.median(np.stack(bias), axis=0)
        modell, bericht = klassiker.superbias(bias, log=lambda *a, **k: None)
        fehler_median = float(np.abs(median - wahrheit).mean())
        fehler_modell = float(np.abs(modell - wahrheit).mean())
        self.assertLess(fehler_modell, fehler_median * 0.5,
                        "Superbias ist nicht deutlich besser als der Median: %.6f gegen %.6f"
                        % (fehler_modell, fehler_median))
        self.assertEqual(bericht["aufnahmen"], 20)

    def test_die_struktur_bleibt_erhalten(self):
        """Gegenprobe: ein Verfahren, das alles glattbuegelt, waere hier ebenfalls
        rauschfrei — und wertlos. Also muss das Spaltenmuster nachweislich UEBERLEBEN."""
        wahrheit, bias = self._daten()
        modell, _ = klassiker.superbias(bias, log=lambda *a, **k: None)
        spalten_wahr = wahrheit.mean(axis=0) - wahrheit.mean()
        spalten_modell = modell.mean(axis=0) - modell.mean()
        korrelation = float(np.corrcoef(spalten_wahr, spalten_modell)[0, 1])
        self.assertGreater(korrelation, 0.95,
                           "das Spaltenmuster ueberlebt nicht (Korrelation %.3f)" % korrelation)

    def test_farbbilder_gehen_auch(self):
        wahrheit, bias = self._daten(n=6)
        farbe = [np.repeat(b[..., None], 3, axis=2) for b in bias]
        modell, _ = klassiker.superbias(farbe, log=lambda *a, **k: None)
        self.assertEqual(modell.shape, farbe[0].shape)


class TestLarsonSekanina(unittest.TestCase):
    """Rotationsgradient: was rotationssymmetrisch ist, faellt heraus."""

    def _komet(self, mit_jet=True):
        h = w = 220
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.hypot(xx - 110, yy - 110)
        bild = 0.8 * np.exp(-r / 15.0)
        if mit_jet:
            phi = np.arctan2(yy - 110, xx - 110)
            bild = bild + 0.06 * np.exp(-r / 35.0) * np.exp(-((phi - 0.6) ** 2) / (2 * 0.1 ** 2))
        return np.clip(bild, 0, 1).astype(np.float32), r, np.arctan2(yy - 110, xx - 110)

    def _jetkontrast(self, bild, r, phi):
        ring = (r > 25) & (r < 65)
        jet = ring & (np.abs(phi - 0.6) < 0.25)
        umfeld = ring & (np.abs(phi - 0.6) > 0.9)
        if not (jet.any() and umfeld.any()):
            return 0.0
        return float(bild[jet].mean() - bild[umfeld].mean()) / max(float(bild[ring].std()), 1e-9)

    def test_der_jet_wird_sichtbarer(self):
        bild, r, phi = self._komet()
        vorher = self._jetkontrast(bild, r, phi)
        nachher = self._jetkontrast(klassiker.larson_sekanina(bild, zentrum=(110, 110),
                                                              winkel=25.0), r, phi)
        self.assertGreater(nachher, vorher * 1.5,
                           "der Jet wird nicht sichtbarer: %.3f -> %.3f" % (vorher, nachher))

    def test_eine_reine_kugel_bekommt_keinen_jet(self):
        """Die GEGENPROBE. Ein Verfahren, das aus einer symmetrischen Kugel Strukturen macht,
        wuerde Strukturen ERFINDEN — der schlimmste Fehler in der Astrofotografie."""
        bild, r, phi = self._komet(mit_jet=False)
        aus = klassiker.larson_sekanina(bild, zentrum=(110, 110), winkel=25.0)
        ring = (r > 25) & (r < 65)
        # Ohne Jet darf keine Richtung deutlich herausstechen.
        richtungen = [float(aus[ring & (np.abs(phi - w) < 0.3)].mean())
                      for w in np.linspace(-2.8, 2.8, 8)]
        spanne = (max(richtungen) - min(richtungen)) / max(float(aus[ring].std()), 1e-9)
        self.assertLess(spanne, 1.0,
                        "aus einer symmetrischen Kugel entsteht Struktur (Spanne %.2f)" % spanne)


class TestPeriodischEntfernen(unittest.TestCase):
    """Fourier-Kerbfilter gegen Streifen."""

    def _bild(self):
        rng = np.random.default_rng(9)
        h = w = 256
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        rein = 0.05 + rng.normal(0, 0.002, (h, w)).astype(np.float32)
        for _ in range(20):                                  # ein paar Sterne
            y, x = int(rng.integers(20, h - 20)), int(rng.integers(20, w - 20))
            rein[y - 1:y + 2, x - 1:x + 2] += 0.4
        streifen = (0.004 * np.sin(2 * np.pi * xx / 9.0)
                    + 0.003 * np.sin(2 * np.pi * yy / 13.0)).astype(np.float32)
        return np.clip(rein, 0, 1), np.clip(rein + streifen, 0, 1)

    def test_streifen_verschwinden_groesstenteils(self):
        rein, gestoert = self._bild()
        aus, bericht = klassiker.periodisch_entfernen(gestoert, staerke=1.0,
                                                      log=lambda *a, **k: None)
        vorher = float(np.abs(gestoert - rein).mean())
        nachher = float(np.abs(aus - rein).mean())
        # 0,45 ist der gemessene Stand, nicht ein Wunsch. An einem 800x800-Ausschnitt eines
        # echten Stapels bleiben nur 15 % stehen; an diesem kleinen 256x256-Bild sind es 40 %,
        # weil die Stoerfrequenz ueber weniger Rasterpunkte verteilt ist. Geprueft wurde, ob
        # sich das an den Einstellungen liegt: ueber Schwelle 2 bis 6 und Fenster 5 bis 15
        # blieb der Rest bei 47 bis 53 % — erst das Mitnehmen der Nachbarfrequenzen (`kerbe`)
        # brachte ihn auf 40 %. Das ist die Grenze des Verfahrens bei dieser Bildgroesse.
        self.assertLess(nachher, vorher * 0.45,
                        "die Streifen bleiben stehen: %.6f -> %.6f" % (vorher, nachher))
        self.assertGreater(bericht["punkte"], 0)

    def test_ein_sauberes_bild_bleibt_sauber(self):
        """Die wichtigere Haelfte. Ein Filter, der auch dort zuschlaegt, wo nichts ist,
        richtet mehr Schaden an als Nutzen."""
        rein, _ = self._bild()
        aus, _ = klassiker.periodisch_entfernen(rein, staerke=1.0, log=lambda *a, **k: None)
        veraenderung = float(np.abs(aus - rein).mean())
        self.assertLess(veraenderung, 1e-4,
                        "der Filter veraendert ein sauberes Bild um %.6f" % veraenderung)

    def test_staerke_null_aendert_nichts(self):
        _, gestoert = self._bild()
        aus, _ = klassiker.periodisch_entfernen(gestoert, staerke=0.0,
                                                log=lambda *a, **k: None)
        self.assertLess(float(np.abs(aus - gestoert).max()), 1e-5)


class TestBlink(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_blink_")
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_ein_daumenkino_entsteht(self):
        from astropy.io import fits
        pfade = []
        rng = np.random.default_rng(2)
        for i in range(4):
            p = os.path.join(self.d, "f%d.fits" % i)
            daten = (rng.random((80, 100)) * 3000 + 1000).astype(np.uint16)
            fits.PrimaryHDU(daten).writeto(p)
            pfade.append(p)
        ziel = os.path.join(self.d, "blink.gif")
        bericht = klassiker.blink(pfade, ziel, groesse=120, log=lambda *a, **k: None)
        self.assertTrue(os.path.exists(ziel))
        self.assertEqual(bericht["aufnahmen"], 4)
        self.assertGreater(os.path.getsize(ziel), 100)

    def test_eine_kaputte_datei_kostet_nicht_das_daumenkino(self):
        from astropy.io import fits
        pfade = []
        for i in range(3):
            p = os.path.join(self.d, "g%d.fits" % i)
            fits.PrimaryHDU(np.full((60, 60), 1000, np.uint16)).writeto(p)
            pfade.append(p)
        kaputt = os.path.join(self.d, "kaputt.fits")
        with open(kaputt, "wb") as fh:
            fh.write(b"das ist kein FITS")
        ziel = os.path.join(self.d, "blink2.gif")
        bericht = klassiker.blink(pfade + [kaputt], ziel, groesse=100,
                                  log=lambda *a, **k: None)
        self.assertEqual(bericht["aufnahmen"], 3, "die kaputte Datei haette uebersprungen "
                                                  "werden muessen")


class TestAnnotation(unittest.TestCase):
    """Die Projektion muss stimmen — eine Beschriftung an der falschen Stelle ist schlimmer
    als keine."""

    def _loesung(self):
        return {"crval1": 202.4696, "crval2": 47.1952, "crpix1": 2000.0, "crpix2": 1400.0,
                "cd1_1": -3.5e-4, "cd1_2": 0.0, "cd2_1": 0.0, "cd2_2": 3.5e-4}

    def test_der_bezugspunkt_landet_auf_dem_bezugspixel(self):
        wcs = annotation._wcs_aus_loesung(self._loesung())
        x, y = annotation.himmel_zu_pixel([wcs["ra0"]], [wcs["dec0"]], wcs)
        self.assertAlmostEqual(float(x[0]), 2000.0, places=3)
        self.assertAlmostEqual(float(y[0]), 1400.0, places=3)

    def test_der_massstab_stimmt(self):
        """0,1 Grad noerdlich muessen bei 3,5e-4 Grad je Pixel genau 285,7 px sein."""
        wcs = annotation._wcs_aus_loesung(self._loesung())
        x0, y0 = annotation.himmel_zu_pixel([wcs["ra0"]], [wcs["dec0"]], wcs)
        x1, y1 = annotation.himmel_zu_pixel([wcs["ra0"]], [wcs["dec0"] + 0.1], wcs)
        self.assertAlmostEqual(float(y1[0] - y0[0]), 0.1 / 3.5e-4, delta=0.5)

    def test_ohne_loesung_keine_erfundene_beschriftung(self):
        with self.assertRaises(ValueError):
            annotation._wcs_aus_loesung({"irgendwas": 1})

    def test_beschriften_laeuft_und_nennt_das_bildfeld(self):
        bild = np.zeros((400, 600, 3), np.float32)
        aus, bericht = annotation.annotieren(bild, self._loesung(),
                                             log=lambda *a, **k: None)
        self.assertEqual(aus.shape, (400, 600, 3))
        self.assertAlmostEqual(bericht["bogensek_px"], 3.5e-4 * 3600, places=3)
        self.assertGreater(float(aus.max()), 0, "es wurde nichts gezeichnet")

    def test_objekte_werden_gelesen(self):
        d = tempfile.mkdtemp(prefix="fp_kat_")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "objekte.csv")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("name,ra,dec,typ\nM51,202.4696,47.1952,Galaxie\nkaputt,,,\n")
        objekte = annotation.objekte_lesen(p)
        self.assertEqual(len(objekte), 1, "die kaputte Zeile haette entfallen muessen")
        self.assertEqual(objekte[0]["name"], "M51")


if __name__ == "__main__":
    unittest.main(verbosity=2)
