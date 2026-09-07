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
             "gesamt_minuten": 200.0}
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
