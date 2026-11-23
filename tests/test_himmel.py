#!/usr/bin/env python3
"""
Framing, Zentrieren, Meridian-Flip, Himmelsmosaik und Farbkalibrierung — gegen einen
künstlichen Himmel mit bekannter Wahrheit.

Ein echter Lauf gegen Gaia war am 23.11.2026 nicht möglich: das ESA-Archiv war in Wartung,
VizieR nicht erreichbar. Darum hier ein eigener Katalog, aus dem eine nachgebaute Kamera je
nach (falscher) Montierungsposition das Bild rechnet:

* Zentrieren: Montierung zeigt 0,12° / −0,08° daneben → nach Sync und Nachschwenken < 1′.
* Meridian-Flip: genau einmal, beim Überschreiten der Grenze, mit Seitenwechsel; ohne
  Seitenwechsel eine Warnung.
* Mosaik: zwei Panele (eines gedreht) mit verschiedenem Hintergrund → Versatz erkannt, Himmel
  einheitlich, Sterne am vorhergesagten Ort.
* Farbkalibrierung: eingebauter Kanalfehler (B × 0,7, R × 1,4) wird zurückgerechnet.
* Framing: Seestar S30 = 3,99 ″/px (CLAUDE.md), Panelabstände stimmen auch nahe am Pol.
"""
import math
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))

import aufnahme  # noqa: E402
import framing  # noqa: E402
import himmelsmosaik  # noqa: E402
import prozesse  # noqa: E402
import zentrieren  # noqa: E402
from gaia_lokal import Katalog  # noqa: E402

RA0, DEC0, SKALA = 299.9, 22.7, 3.6
FORM = (512, 768)
STILL = lambda *a, **k: None  # noqa: E731


def himmel(seed=5, n=1600, breite=2.4):
    rng = np.random.default_rng(seed)
    dec = DEC0 + rng.uniform(-breite / 2, breite / 2, n)
    ra = RA0 + rng.uniform(-breite / 2, breite / 2, n) / np.cos(np.radians(DEC0))
    mag = rng.uniform(8, 14, n)
    farbe = rng.uniform(0.2, 2.2, n)
    return Katalog(ra, dec, mag, farbe)


def wcs_bei(ra, dec, winkel=0.0, form=FORM):
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra % 360, dec]
    w.wcs.crpix = [(form[1] + 1) / 2.0, (form[0] + 1) / 2.0]
    t = np.radians(winkel)
    w.wcs.cd = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]]) @ np.diag([-1, 1]) * (SKALA / 3600)
    return w


def rendern(kat, w, form=FORM, hintergrund=0.01, farbfehler=(1.0, 1.0, 1.0), seed=0):
    """BGR-Bild der Katalogsterne. Echte Sternfarbe aus BP-RP; `farbfehler` = Kanalverstärkung."""
    rng = np.random.default_rng(seed)
    h, b = form
    x, y = w.world_to_pixel_values(kat.ra, kat.dec)
    drin = (x > 3) & (x < b - 4) & (y > 3) & (y < h - 4)
    bild = np.full((h, b, 3), hintergrund, np.float32)
    for xi, yi, m, c in zip(x[drin], y[drin], kat.g_mag[drin], kat.bp_rp[drin]):
        amp = 0.6 * 10 ** (-0.4 * (m - 8))
        anteile = np.exp(np.array([-0.4, 0.0, 0.5]) * (c - 0.82))   # B, G, R
        x0, y0 = int(xi), int(yi)
        yy, xx = np.mgrid[max(0, y0 - 6):min(h, y0 + 7), max(0, x0 - 6):min(b, x0 + 7)]
        profil = amp * np.exp(-((xx - xi) ** 2 + (yy - yi) ** 2) / (2 * 1.4 ** 2))
        bild[yy, xx] += (profil[..., None] * anteile * np.array(farbfehler)).astype(np.float32)
    return bild + rng.normal(0, 0.0004, bild.shape).astype(np.float32)


class FakeMontierung:
    """Zeigt um `fehler` (°) daneben. Wahre Richtung = Befehl + Fehler + gelernte Korrektur;
    ein Sync auf die gemessene Position lernt die Korrektur (wie ein echtes Pointing-Modell)."""

    def __init__(self, fehler=(0.12, -0.08), ha_start=None, ha_schritt=0.0):
        self.cmd = [RA0, DEC0]
        self.fehler, self.korr = list(fehler), [0.0, 0.0]
        self.ha, self.ha_schritt = ha_start, ha_schritt
        self._seite = "Ost"
        self.schwenks = 0

    def wahr(self):
        return self.cmd[0] + self.fehler[0] + self.korr[0], self.cmd[1] + self.fehler[1] + self.korr[1]

    def position(self):
        return self.cmd[0] / 15.0, self.cmd[1]

    def schwenken(self, ra_h, dec):
        self.cmd = [ra_h * 15.0, dec]
        self.schwenks += 1
        if self.ha is not None and self.ha >= 0:
            self._seite = "West"
        return self.position()

    def synchronisieren(self, ra_h, dec):
        self.korr[0] += self.cmd[0] - ra_h * 15.0
        self.korr[1] += self.cmd[1] - dec
        return self.position()

    def stundenwinkel(self):
        if self.ha is None:
            return None
        self.ha += self.ha_schritt
        return self.ha

    def seite(self):
        return self._seite


class FakeKamera:
    def __init__(self, kat, montierung):
        self.kat, self.m = kat, montierung

    def belichten(self, dauer, **_):
        ra, dec = self.m.wahr()
        return rendern(self.kat, wcs_bei(ra, dec))

    def info(self):
        return {"name": "Fake"}

    def temperatur(self):
        return None


class TestFraming(unittest.TestCase):
    def test_seestar_bildfeld(self):
        b, h, skala = framing.bildfeld(150, 2.9, 1080, 1920)
        self.assertAlmostEqual(skala, 3.99, places=2)
        self.assertAlmostEqual(b, 1080 * skala / 3600, places=6)

    def test_panele_abstaende(self):
        for dec in (22.7, 85.0):
            with self.subTest(dec=dec):
                p = framing.panele(RA0, dec, 1.0, 0.7, spalten=3, zeilen=2, ueberlappung=0.2)
                self.assertEqual(len(p), 6)
                a, b = p[0], p[1]
                abstand = zentrieren.winkelabstand(a["ra_h"] * 15, a["dec"], b["ra_h"] * 15, b["dec"])
                self.assertAlmostEqual(abstand, 0.8, delta=0.01)
                c = p[3]                                      # darunter
                self.assertAlmostEqual(zentrieren.winkelabstand(a["ra_h"] * 15, a["dec"], c["ra_h"] * 15, c["dec"]),
                                       0.56, delta=0.01)
                self.assertGreater(a["dec"], c["dec"], "Zeile 1 liegt nördlich")

    def test_eins_mal_eins_ist_die_mitte(self):
        p = framing.panele(RA0, DEC0, 1.0, 1.0)
        self.assertAlmostEqual(p[0]["ra_h"] * 15, RA0, places=9)
        self.assertAlmostEqual(p[0]["dec"], DEC0, places=9)

    def test_falsche_angaben(self):
        with self.assertRaises(ValueError):
            framing.bildfeld(0, 2.9, 100, 100)
        with self.assertRaises(ValueError):
            framing.panele(RA0, DEC0, 1, 1, ueberlappung=0.95)


class TestZentrieren(unittest.TestCase):
    def test_zentriert_trotz_montierungsfehler(self):
        kat = himmel()
        m = FakeMontierung(fehler=(0.12, -0.08))
        e = zentrieren.zentrieren(FakeKamera(kat, m), m, RA0 / 15.0, DEC0, kat, SKALA, log=STILL)
        self.assertLess(e["abstand_bogenmin"], 1.0)
        wahr = m.wahr()
        self.assertLess(zentrieren.winkelabstand(wahr[0], wahr[1], RA0, DEC0) * 60, 1.0)
        self.assertGreaterEqual(e["versuche"], 2, "der erste Versuch muss den Fehler sehen")

    def test_ohne_sterne_kein_raten(self):
        kat = himmel()
        m = FakeMontierung(fehler=(0, 0))

        class Leer(FakeKamera):
            def belichten(self, dauer, **_):
                return np.full(FORM + (3,), 0.01, np.float32)
        with self.assertRaises(Exception):
            zentrieren.zentrieren(Leer(kat, m), m, RA0 / 15.0, DEC0, kat, SKALA, versuche=2, log=STILL)


class TestMeridianFlip(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _lauf(self, m, **k):
        kat = himmel()
        return aufnahme.Lauf(FakeKamera(kat, m), [aufnahme.Schritt(6, 0, "Light")], self.d,
                             montierung=m, meridian_minuten=0.0, takt=0.0, **k)

    def test_genau_ein_flip_mit_seitenwechsel(self):
        m = FakeMontierung(fehler=(0, 0), ha_start=-0.05, ha_schritt=0.02)
        zeilen = []
        lauf = self._lauf(m, log=zeilen.append)
        self.assertEqual(len(lauf.ausfuehren()), 6)
        self.assertEqual(lauf.flips, 1)
        self.assertEqual(m.seite(), "West")
        self.assertFalse([z for z in zeilen if "unverändert" in z])

    def test_ohne_seitenwechsel_warnung(self):
        m = FakeMontierung(fehler=(0, 0), ha_start=0.1, ha_schritt=0.0)
        m.schwenken = lambda ra_h, dec: m.position()          # Montierung flippt nicht
        zeilen = []
        self._lauf(m, log=zeilen.append).ausfuehren()
        self.assertTrue([z for z in zeilen if "unverändert" in z])

    def test_ohne_stundenwinkel_aus(self):
        m = FakeMontierung(fehler=(0, 0), ha_start=None)
        zeilen = []
        lauf = self._lauf(m, log=zeilen.append)
        lauf.ausfuehren()
        self.assertEqual(lauf.flips, 0)
        self.assertTrue([z for z in zeilen if "Meridian-Flip aus" in z])

    def test_ziele_werden_angefahren(self):
        m = FakeMontierung(fehler=(0, 0))
        kat = himmel()
        ziele = framing.panele(RA0, DEC0, 0.5, 0.3, spalten=2, zeilen=1)
        lauf = aufnahme.Lauf(FakeKamera(kat, m), [aufnahme.Schritt(2, 0, "Light")], self.d,
                             montierung=m, ziele=ziele, log=STILL)
        self.assertEqual(len(lauf.ausfuehren()), 4)
        self.assertEqual(m.schwenks, 2)
        from astropy.io import fits
        objekte = sorted({fits.getheader(p)["OBJECT"] for p in lauf.dateien})
        self.assertEqual(objekte, ["Panel 1-1", "Panel 1-2"])


class TestMosaikUndFarbe(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kat = himmel()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
        prozesse.KATALOG_PFAD = None

    def _fits(self, name, bild, w):
        from astropy.io import fits
        pfad = os.path.join(self.d, name)
        fits.PrimaryHDU(np.ascontiguousarray(bild[..., ::-1].transpose(2, 0, 1)), header=w.to_header()).writeto(pfad)
        return pfad

    def test_mosaik(self):
        w1 = wcs_bei(RA0 - 0.25, DEC0)
        w2 = wcs_bei(RA0 + 0.25, DEC0 + 0.05, winkel=5.0)
        p1 = self._fits("a.fits", rendern(self.kat, w1, hintergrund=0.10), w1)
        p2 = self._fits("b.fits", rendern(self.kat, w2, hintergrund=0.13, seed=1), w2)
        bild, wcs, bericht = himmelsmosaik.mosaik([p1, p2], log=STILL)
        self.assertAlmostEqual(bericht["versatz"][1] - bericht["versatz"][0], 0.03, delta=0.002)
        l = np.nanmean(bild, axis=2)
        links, rechts = l[:, : l.shape[1] // 4], l[:, -l.shape[1] // 4:]
        self.assertAlmostEqual(float(np.nanmedian(links)), float(np.nanmedian(rechts)), delta=0.002)
        # helle Sterne am vorhergesagten Ort
        hell = self.kat.g_mag < 9.5
        x, y = wcs.world_to_pixel_values(self.kat.ra[hell], self.kat.dec[hell])
        treffer = 0
        for xi, yi in zip(x, y):
            xi, yi = int(round(xi)), int(round(yi))
            if 5 < xi < l.shape[1] - 5 and 5 < yi < l.shape[0] - 5 and np.isfinite(l[yi, xi]):
                treffer += int(l[yi, xi] > np.nanmedian(l) + 0.05)
        self.assertGreaterEqual(treffer, 5)

    def test_mosaik_ohne_wcs_abgelehnt(self):
        from astropy.io import fits
        roh = os.path.join(self.d, "roh.fits")
        fits.writeto(roh, np.zeros((10, 10), np.float32))
        with self.assertRaises(ValueError):
            himmelsmosaik.mosaik([roh, roh])

    def test_mosaik_ohne_ueberlappung_abgelehnt(self):
        w1, w2 = wcs_bei(RA0 - 1.0, DEC0), wcs_bei(RA0 + 1.0, DEC0)
        p1 = self._fits("a.fits", rendern(self.kat, w1), w1)
        p2 = self._fits("b.fits", rendern(self.kat, w2), w2)
        with self.assertRaises(ValueError):
            himmelsmosaik.mosaik([p1, p2], log=STILL)

    def test_farbkalibrierung_rechnet_kanalfehler_zurueck(self):
        pfad = os.path.join(self.d, "kat.npz")
        self.kat.speichern(pfad)
        prozesse.KATALOG_PFAD = pfad
        w = wcs_bei(RA0, DEC0)
        wahr = rendern(self.kat, w)
        falsch = rendern(self.kat, w, farbfehler=(0.7, 1.0, 1.4))
        r = prozesse.anwenden(falsch, "farbkalibrierung", {"ra": RA0 + 0.02, "dec": DEC0 - 0.01, "skala": SKALA},
                              log=STILL)
        # Kanalverhältnisse der Sternflüsse, NUR über Sternpixeln. Erste Fassung summierte alle
        # positiven Pixel — das Rauschen zog die Verhältnisse Richtung 1 (wahr gegen falsch nur
        # 0,79 statt der eingebauten 0,7), und der Test meldete 12,7 % Fehler, wo die Rechnung
        # die Faktoren auf 0,2 % traf.
        stern = wahr.mean(axis=2) > 0.01 + 0.02

        def verh(b):
            s = (b - np.median(b, axis=(0, 1)))[stern].sum(axis=0)
            return s[0] / s[1], s[2] / s[1]
        for ist, soll in zip(verh(r), verh(wahr)):
            self.assertAlmostEqual(ist / soll, 1.0, delta=0.02)
        vorher = verh(falsch)
        self.assertGreater(abs(vorher[1] / verh(wahr)[1] - 1), 0.3, "Gegenprobe: vorher wirklich falsch")

    def test_farbkalibrierung_ohne_angaben(self):
        with self.assertRaises(ValueError):
            prozesse.anwenden(rendern(self.kat, wcs_bei(RA0, DEC0)), "farbkalibrierung")


if __name__ == "__main__":
    unittest.main()
