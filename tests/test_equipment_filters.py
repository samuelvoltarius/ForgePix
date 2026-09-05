#!/usr/bin/env python3
"""
ForgePix — Tests für Filterkunde (core/filters.py) und Ausrüstungsrechnung (core/equipment.py).

Eigenständig lauffähig:

    python3 tests/test_equipment_filters.py   # oder: python3 -m unittest discover -s tests

Beide Module beantworten Fragen, die die Pipeline vorher blind entschieden hat:
  • Welche Emissionslinien kommen überhaupt an? (Filter) → Entmischung und ehrliche Paletten
  • Ist das Bild über- oder unterabgetastet? (Ausrüstung) → Binning oder Drizzle

Die Zahlen in den Tests stammen aus echten Aufnahmen und Herstellerangaben, nicht aus
Annahmen: ASI294MC Pro (4.63 µm) an 750 mm, Seestar S30 (2.90 µm) an 150 mm,
TS/GSO 8" RC 203/1624 mit 0.67×-Reducer.
"""
import os
import sys
import unittest

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import equipment  # noqa: E402
import filters  # noqa: E402


class TestFilterkunde(unittest.TestCase):
    """Der Filter entscheidet, welche Linien ankommen — und damit, was ehrlich darstellbar ist."""

    def test_alle_eintraege_sind_vollstaendig(self):
        for f in filters.FILTER:
            with self.subTest(filter=f.schluessel):
                self.assertTrue(f.name)
                self.assertIn(f.art, ("breitband", "lichtverschmutzung", "dualband",
                                      "multiband", "schmalband"))
                self.assertGreaterEqual(f.unmix, 0.0)
                self.assertLessEqual(f.unmix, 0.5)
                for linie in f.linien:
                    self.assertIn(linie, filters.LINIEN, "unbekannte Emissionslinie")

    def test_erkennung_aus_echten_headern(self):
        """Genau die Werte, die in Alfreds Dateien stehen (Seestar S30 schreibt IRCUT/LP)."""
        for wert, erwartet in (("IRCUT", "uvir"), ("LP", "lp")):
            self.assertEqual(getattr(filters.aus_header(wert), "schluessel", None), erwartet)

    def test_erkennung_markenmodelle(self):
        proben = {
            "SV220 7nm": "dual7", "L-eXtreme": "dual7", "L-Ultimate": "dual3",
            "ALP-T 3nm": "dual3", "ALP-T 5nm": "dual5", "ZWO Duo-Band": "zwo_duo",
            "L-eNhance": "lenhance", "L-Pro": "lpro", "SV260": "sv260",
            "Quad-Band": "quad", "Ha": "ha", "OIII": "oiii", "SII": "sii",
        }
        for wert, erwartet in proben.items():
            with self.subTest(header=wert):
                f = filters.aus_header(wert)
                self.assertIsNotNone(f, "nicht erkannt: %r" % wert)
                self.assertEqual(f.schluessel, erwartet)

    def test_unbekanntes_lieber_none_als_geraten(self):
        """Konservativ: eine falsche Annahme entscheidet mit, ob SII als echt gilt."""
        for wert in ("", "   ", "Foo", None):
            self.assertIsNone(filters.aus_header(wert))

    def test_schmalere_filter_entmischen_weniger(self):
        """Der Startwert der Entmischung muss mit der Bandbreite monoton steigen."""
        reihe = ["dual3", "dual5", "dual7", "dual12", "zwo_duo"]
        werte = [filters.hole(s).unmix for s in reihe]
        self.assertEqual(werte, sorted(werte), "nicht monoton: %s" % werte)

    def test_sho_aus_dualband_wird_als_synthetisch_gemeldet(self):
        """Ein Dual-Band-Filter lässt KEIN SII durch — das muss gesagt werden."""
        ok, hinweis = filters.palette_ehrlich(filters.hole("dual7"), "sho")
        self.assertFalse(ok)
        self.assertIn("SII", hinweis)
        self.assertIn("synthetisch", hinweis)

    def test_sho_mit_echtem_sii_ist_ehrlich(self):
        ok, _ = filters.palette_ehrlich(filters.hole("dual_sii_oiii"), "sho")
        self.assertTrue(ok)
        ok2, _ = filters.palette_ehrlich(filters.hole("quad"), "sho")
        self.assertTrue(ok2)

    def test_hoo_braucht_beide_linien(self):
        ok, hinweis = filters.palette_ehrlich(filters.hole("uvir"), "hoo")
        self.assertFalse(ok)
        self.assertTrue(hinweis)


class TestAbbildungsskala(unittest.TestCase):
    """Aus Brennweite und Pixelgröße folgt, ob Binning oder Drizzle etwas bringt."""

    def test_skala_an_echten_setups(self):
        # ASI294MC Pro (4.63 µm) an 750 mm -> 1.27"/px, an echten Dateien nachgerechnet
        self.assertAlmostEqual(equipment.abbildungsskala(750, 4.63), 1.273, places=2)
        # Seestar S30 (2.90 µm) an 150 mm -> 3.99"/px
        self.assertAlmostEqual(equipment.abbildungsskala(150, 2.90), 3.988, places=2)

    def test_binning_halbiert_die_aufloesung(self):
        ohne = equipment.abbildungsskala(750, 4.63, 1)
        mit = equipment.abbildungsskala(750, 4.63, 2)
        self.assertAlmostEqual(mit, ohne * 2, places=3)

    def test_unbrauchbare_angaben_geben_none(self):
        for fl, px in ((0, 4.63), (750, 0), (None, 4.63), ("x", 4.63), (-750, 4.63)):
            self.assertIsNone(equipment.abbildungsskala(fl, px))


class TestKorrektoren(unittest.TestCase):
    """Reducer/Barlow ändern die Brennweite und damit alles Nachgelagerte."""

    def test_reducer_am_echten_teleskop(self):
        """TS/GSO 8\" RC 203/1624 mit 0.67x-Reducer -> 1088 mm, f/5.4."""
        fl = equipment.wirksame_brennweite(1624.0, "red_067")
        self.assertAlmostEqual(fl, 1088.08, places=1)
        self.assertAlmostEqual(equipment.oeffnungsverhaeltnis(fl, 203.0), 5.36, places=1)
        self.assertAlmostEqual(equipment.abbildungsskala(fl, 4.63), 0.878, places=2)

    def test_flattener_laesst_brennweite_gleich(self):
        self.assertEqual(equipment.wirksame_brennweite(1624.0, "flattener"), 1624.0)
        self.assertEqual(equipment.wirksame_brennweite(1624.0, "keiner"), 1624.0)
        self.assertEqual(equipment.wirksame_brennweite(1624.0, None), 1624.0)

    def test_barlow_verlaengert(self):
        self.assertEqual(equipment.wirksame_brennweite(1000.0, "barlow_2"), 2000.0)

    def test_roher_faktor_erlaubt(self):
        self.assertAlmostEqual(equipment.wirksame_brennweite(1000.0, 0.8), 800.0)

    def test_unsinniges_oeffnungsverhaeltnis_wird_verworfen(self):
        """Der Seestar S30 schreibt APERTURE=5.0 — kein Durchmesser. Als solcher gelesen
        kaeme f/30 heraus. Solche Werte muessen verworfen werden."""
        self.assertIsNone(equipment.oeffnungsverhaeltnis(150.0, 5.0))
        self.assertAlmostEqual(equipment.oeffnungsverhaeltnis(150.0, 30.0), 5.0, places=2)


class TestAbtastungsurteil(unittest.TestCase):
    """Das Urteil haengt an der GEMESSENEN Sternbreite in Pixeln, nicht an einer Annahme."""

    def test_unterabgetastet_empfiehlt_drizzle(self):
        kennz, _, empf = equipment.sampling_urteil(1.27, 1.5)
        self.assertEqual(kennz, "unterabgetastet")
        self.assertEqual(empf, "drizzle")

    def test_ueberabgetastet_empfiehlt_binning(self):
        kennz, _, empf = equipment.sampling_urteil(0.59, 5.0)
        self.assertEqual(kennz, "ueberabgetastet")
        self.assertEqual(empf, "binning")

    def test_passend_empfiehlt_nichts(self):
        kennz, _, empf = equipment.sampling_urteil(1.27, 2.8)
        self.assertEqual(kennz, "passend")
        self.assertIsNone(empf)

    def test_ohne_messung_kein_urteil(self):
        kennz, _, _ = equipment.sampling_urteil(1.27, None)
        self.assertEqual(kennz, "unbekannt")

    def test_drizzle_rat_nennt_die_dither_bedingung(self):
        """Drizzle ohne Dithering bringt nichts ausser einem groesseren Bild — das muss
        dabeistehen, sonst folgt der Nutzer einem Rat, der ihm nichts bringt."""
        rat = equipment.empfehlung_text("unterabgetastet", "drizzle", gedithert=False)
        self.assertIn("Dithering", rat)
        rat2 = equipment.empfehlung_text("unterabgetastet", "drizzle", gedithert=True)
        self.assertIn("gedithert", rat2)


class TestFilterWarnung(unittest.TestCase):
    """Sehr schmale Filter an sehr schnellen Optiken: die Durchlasskurve wandert."""

    def test_warnt_bei_3nm_an_schneller_optik(self):
        self.assertIn("wandern", equipment.filter_warnung(3.5, filters.hole("dual3")))

    def test_schweigt_bei_alfreds_kombination(self):
        """SV220 7 nm an f/5.4 (RC8 mit 0.67x-Reducer) ist unkritisch."""
        self.assertEqual(equipment.filter_warnung(5.4, filters.hole("dual7")), "")

    def test_schweigt_ohne_bandbreite(self):
        self.assertEqual(equipment.filter_warnung(4.0, filters.hole("uvir")), "")
        self.assertEqual(equipment.filter_warnung(None, filters.hole("dual3")), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
