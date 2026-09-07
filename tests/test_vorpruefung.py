#!/usr/bin/env python3
"""
ForgePix — Tests für die Vorprüfung (core/vorpruefung.py).

    python3 tests/test_vorpruefung.py

Das Regelwerk urteilt über den fertigen Stapel. Für einen Teil der Befunde ist das zu spät:
dass nur vier Aufnahmen da sind, dass zwei Kameras im Ordner liegen oder dass Ha und L gemischt
wurden, steht in den Kopfdaten. Das nach zwanzig Minuten Rechnen zu erfahren, ist eine
vermeidbare Enttäuschung.

Zwei Prüfungen zählen hier mehr als die übrigen:

1. **Mehrere Kameras müssen kritisch sein.** Der Stapel läuft durch, das Ergebnis sieht aus wie
   ein Bild, und die Sterne sind Matsch — nichts daran meldet sich von selbst.
2. **Fehlende Angaben lösen nichts aus.** Wie beim Regelwerk: eine Regel, die auf einer
   Nicht-Messung anspringt, erfindet einen Befund.
"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import regeln  # noqa: E402
import vorpruefung  # noqa: E402


def _stille(*a, **k):
    pass


class TestKopfdaten(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_vp_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _schreiben(self, n, **felder):
        from astropy.io import fits
        pfade = []
        for i in range(n):
            p = os.path.join(self.d, "l_%03d.fit" % i)
            kopf = {"INSTRUME": "ZWO ASI294MC Pro", "EXPTIME": 300.0, "FILTER": "L",
                    "CCD-TEMP": -10.0, "DATE-OBS": "2026-09-06T22:00:00"}
            kopf.update(felder)
            fits.writeto(p, np.zeros((8, 8), np.float32), fits.Header(kopf))
            pfade.append(p)
        return pfade

    def test_liest_die_felder(self):
        p = self._schreiben(3)
        u = vorpruefung.uebersicht(vorpruefung.kopfdaten(p, log=_stille))
        self.assertEqual(u["kameras"], {"ZWO ASI294MC Pro": 3})
        self.assertEqual(u["belichtungen_s"], {300.0: 3})
        self.assertEqual(u["naechte"], ["2026-09-06"])

    def test_nicht_fits_wird_ignoriert(self):
        p = os.path.join(self.d, "x.jpg")
        with open(p, "wb") as fh:
            fh.write(b"nichts")
        self.assertEqual(vorpruefung.kopfdaten([p], log=_stille), [])
        self.assertEqual(vorpruefung.kopfdaten([], log=_stille), [])

    def test_stichprobe_bei_vielen_dateien(self):
        """2000 Header zu lesen kostet Minuten, die niemand fuer eine Vorpruefung ausgibt."""
        p = self._schreiben(20)
        koepfe = vorpruefung.kopfdaten(p, max_dateien=5, log=_stille)
        self.assertLessEqual(len(koepfe), 6)
        u = vorpruefung.uebersicht(koepfe, gesamt=len(p))
        self.assertEqual(u["anzahl"], 20, "die GESAMTzahl muss erhalten bleiben")
        self.assertLess(u["gelesen"], 20)

    def test_kaputte_datei_bricht_nicht_ab(self):
        p = self._schreiben(2)
        kaputt = os.path.join(self.d, "kaputt.fit")
        with open(kaputt, "wb") as fh:
            fh.write(b"kein FITS")
        self.assertEqual(len(vorpruefung.kopfdaten(p + [kaputt], log=_stille)), 2)


class TestPruefen(unittest.TestCase):

    def _u(self, **abw):
        u = {"anzahl": 40, "gelesen": 40, "kameras": {"ZWO ASI294MC Pro": 40},
             "filter": {"L": 40}, "belichtungen_s": {300.0: 40},
             "temperatur_c": (-10.5, -9.8), "naechte": ["2026-09-06"],
             "richtungsspanne_grad": 0.01, "gesamt_minuten": 200.0,
             "bildgroessen": {(1080, 1920): 40}, "enthaltene_subs": None}
        u.update(abw)
        return u

    def test_saubere_serie_gibt_nichts(self):
        self.assertEqual(vorpruefung.pruefen(self._u()), [])

    def test_leere_uebersicht_stuerzt_nicht(self):
        self.assertEqual(vorpruefung.pruefen({}), [])
        self.assertEqual(vorpruefung.pruefen(None), [])

    def test_mehrere_kameras_sind_kritisch(self):
        """Der wichtigste Befund: der Stapel laeuft durch und die Sterne sind Matsch."""
        r = vorpruefung.pruefen(self._u(kameras={"ZWO ASI294MC Pro": 20, "Seestar S30": 20}))
        self.assertEqual(r[0].stufe, regeln.KRITISCH)
        self.assertIn("Kameras", r[0].titel)
        self.assertIn("Seestar S30", r[0].grund)

    def test_mehrere_himmelsausschnitte_sind_kritisch(self):
        """Derselbe stille Fehler wie bei den Trainingsserien, nur beim Benutzer: die
        Aufnahmen des zweiten Ziels fallen beim Stapeln als 'nicht ausrichtbar' heraus, ohne
        dass jemand erfaehrt, dass es sie gab. An einem echten Ordner gemessen: fuenf Ziele in
        einem Verzeichnis."""
        r = vorpruefung.pruefen(self._u(richtungsspanne_grad=9.0))
        self.assertEqual(r[0].stufe, regeln.KRITISCH)
        self.assertIn("Himmelsausschnitte", r[0].titel)

    def test_dithering_loest_nichts_aus(self):
        """Dithering und Nachfuehrfehler bewegen sich im Bogenminutenbereich."""
        for spanne in (0.0, 0.05, 0.5, 1.0):
            self.assertEqual([x for x in vorpruefung.pruefen(self._u(richtungsspanne_grad=spanne))
                              if "Himmelsausschnitte" in x.titel], [], "%.2f Grad" % spanne)

    def test_ohne_richtungsangabe_kein_befund(self):
        self.assertEqual([x for x in vorpruefung.pruefen(self._u(richtungsspanne_grad=None))
                          if "Himmelsausschnitte" in x.titel], [])

    def test_spanne_wird_aus_den_kopfdaten_berechnet(self):
        koepfe = [{"RA": 202.47, "DEC": 47.19}, {"RA": 202.50, "DEC": 47.21},
                  {"RA": 210.75, "DEC": 54.30}]
        u = vorpruefung.uebersicht(koepfe)
        self.assertIsNotNone(u["richtungsspanne_grad"])
        self.assertGreater(u["richtungsspanne_grad"], 5.0)

    def test_eine_einzelne_aufnahme_hat_keine_spanne(self):
        self.assertIsNone(vorpruefung.uebersicht([{"RA": 1.0, "DEC": 2.0}])
                          ["richtungsspanne_grad"])

    def test_verschiedene_bildgroessen_sind_kritisch(self):
        """Der Seestar schreibt neben dem normalen Ergebnis auch ein doppelt so grosses.
        Am echten Ordner M 42 gefunden: 1080x1920 und 2160x3840 nebeneinander."""
        r = vorpruefung.pruefen(self._u(bildgroessen={(1080, 1920): 3, (2160, 3840): 3}))
        self.assertEqual(r[0].stufe, regeln.KRITISCH)
        self.assertIn("Bildgroessen", r[0].titel)

    def test_eine_bildgroesse_loest_nichts_aus(self):
        self.assertEqual([x for x in vorpruefung.pruefen(self._u())
                          if "Bildgroessen" in x.titel], [])

    def test_fertige_stapel_zaehlen_ihre_wahre_belichtung(self):
        """Sechs zusammengefasste M-42-Ergebnisse meldeten "3 Minuten" statt 199 — Faktor 66.
        Der Seestar schreibt TOTALEXP und STACKCNT in seine fertigen Stapel."""
        koepfe = [{"EXPTIME": 30.0, "TOTALEXP": 5490.0, "STACKCNT": 183},
                  {"EXPTIME": 30.0, "TOTALEXP": 4470.0, "STACKCNT": 149}]
        u = vorpruefung.uebersicht(koepfe)
        self.assertAlmostEqual(u["gesamt_minuten"], (5490 + 4470) / 60.0, places=1)
        self.assertEqual(u["enthaltene_subs"], 332)
        self.assertIn("332 Einzelaufnahmen", vorpruefung.text(u))

    def test_ohne_totalexp_zaehlt_die_belichtungszeit(self):
        u = vorpruefung.uebersicht([{"EXPTIME": 300.0}, {"EXPTIME": 300.0}])
        self.assertAlmostEqual(u["gesamt_minuten"], 10.0, places=3)
        self.assertIsNone(u["enthaltene_subs"])

    def test_mehrere_filter(self):
        t = [x.titel for x in vorpruefung.pruefen(self._u(filter={"Ha": 20, "L": 20}))]
        self.assertTrue(any("Filter" in x for x in t))

    def test_zu_wenige_aufnahmen(self):
        r = vorpruefung.pruefen(self._u(anzahl=3))
        self.assertEqual(r[0].stufe, regeln.KRITISCH)
        r = vorpruefung.pruefen(self._u(anzahl=8))
        self.assertTrue(any("Wenige" in x.titel for x in r))
        self.assertEqual([x for x in vorpruefung.pruefen(self._u(anzahl=40))
                          if "Aufnahmen" in x.titel], [])

    def test_azimutal_nur_bei_shift(self):
        """Im Standard (rotate) ist alles in Ordnung — dann darf nichts gemeldet werden."""
        u = self._u(kameras={"Seestar S30": 40})
        self.assertEqual([x for x in vorpruefung.pruefen(u, align_mode="rotate")
                          if "zimutal" in x.titel], [])
        self.assertEqual([x for x in vorpruefung.pruefen(u)
                          if "zimutal" in x.titel], [])
        r = [x for x in vorpruefung.pruefen(u, align_mode="shift") if "zimutal" in x.titel]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].einstellung, "--astro-align rotate")
        self.assertIn("27,6", r[0].grund, "die Messung gehoert in die Begruendung")

    def test_nachgefuehrte_kamera_loest_nichts_aus(self):
        u = self._u(kameras={"ZWO ASI294MC Pro": 40})
        self.assertEqual([x for x in vorpruefung.pruefen(u, align_mode="shift")
                          if "zimutal" in x.titel], [])

    def test_gemischte_zeiten_sind_nur_ein_hinweis(self):
        r = [x for x in vorpruefung.pruefen(self._u(belichtungen_s={60.0: 10, 300.0: 30}))
             if "Belichtungszeiten" in x.titel]
        self.assertEqual(r[0].stufe, regeln.HINWEIS)

    def test_temperaturspanne(self):
        self.assertEqual([x for x in vorpruefung.pruefen(self._u(temperatur_c=(-10.5, -9.8)))
                          if "Temperatur" in x.titel], [])
        self.assertTrue([x for x in vorpruefung.pruefen(self._u(temperatur_c=(-15.0, 2.0)))
                         if "Temperatur" in x.titel])

    def test_kalibrierung_nur_wenn_beides_fehlt(self):
        self.assertEqual([x for x in vorpruefung.pruefen(self._u(), hat_dark=True,
                                                         hat_flat=False)
                          if "Kalibrier" in x.titel], [])
        self.assertTrue([x for x in vorpruefung.pruefen(self._u(), hat_dark=False,
                                                        hat_flat=False)
                         if "Kalibrier" in x.titel])
        self.assertEqual([x for x in vorpruefung.pruefen(self._u())
                          if "Kalibrier" in x.titel], [],
                         "unbekannt ist nicht dasselbe wie nicht vorhanden")

    def test_reihenfolge_nach_dringlichkeit(self):
        r = vorpruefung.pruefen(self._u(kameras={"a": 1, "b": 1},
                                        belichtungen_s={60.0: 1, 300.0: 1}))
        self.assertEqual(r[0].stufe, regeln.KRITISCH)
        self.assertEqual(r[-1].stufe, regeln.HINWEIS)


class TestText(unittest.TestCase):

    def test_leer(self):
        self.assertEqual(vorpruefung.text({}), "")
        self.assertEqual(vorpruefung.text(None), "")

    def test_nennt_die_eckdaten(self):
        t = vorpruefung.text({"anzahl": 40, "kameras": {"ZWO ASI294MC Pro": 40},
                              "filter": {"L": 40}, "belichtungen_s": {300.0: 40},
                              "temperatur_c": (-10.5, -9.8), "naechte": ["2026-09-06"],
                              "gesamt_minuten": 200.0})
        for teil in ("40 Aufnahmen", "ASI294MC", "300 s", "2026-09-06"):
            self.assertIn(teil, t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
