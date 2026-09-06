#!/usr/bin/env python3
"""
ForgePix — Tests für den lokalen Gaia-Katalog (core/gaia_lokal.py).

    python3 tests/test_gaia_lokal.py     # oder: python3 -m unittest discover -s tests

Der Massstab ist hier bewusst die stumpfe Vollsuche: für jede Abfrage wird zusätzlich der ganze
Katalog durchgerechnet, und beide Ergebnisse müssen EXAKT übereinstimmen. Ein Index, der
gelegentlich einen Stern am Rand verliert, fällt sonst nie auf — das Ergebnis sieht ja normal aus.

Gemessen an 300 000 gleichmässig verteilten Sternen:
    Aufbau des Index          0,07 s
    Abfrage mit Index         0,2 ms
    dieselbe Abfrage stumpf   22 ms          (Faktor rund 100)
    Datei                     6,6 MB = 22 Byte je Stern

GENAU SO EIN FEHLER wurde dabei gefunden: die Zellenbreite wurde ursprünglich aus der
Deklination des EINZELNEN STERNS gerechnet statt aus seinem Band. Damit hatten zwei Sterne im
selben Band verschiedene Raster, und bei Deklination 78° gingen sechs von 21 Sternen verloren,
ohne dass irgendetwas fehlgeschlagen wäre.
"""
import os
import sys
import shutil
import tempfile
import unittest
import json
import io
import threading
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import gaia_lokal  # noqa: E402


def _stille(*a, **k):
    pass


class TestKatalog(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(4)
        n = 60000
        cls.ra = rng.uniform(0, 360, n)
        # gleichmässig auf der Kugel, nicht in der Deklination — sonst häufen sich die Sterne
        # an den Polen und der Test prüft genau dort am wenigsten
        cls.dec = np.degrees(np.arcsin(rng.uniform(-1, 1, n)))
        cls.g = rng.uniform(8, 17, n).astype(np.float32)
        cls.c = rng.uniform(-0.3, 3.0, n).astype(np.float32)
        cls.kat = gaia_lokal.Katalog(cls.ra, cls.dec, cls.g, cls.c)

    def _stumpf(self, ra, dec, r):
        d = gaia_lokal._winkelabstand(ra, dec, self.ra, self.dec)
        return int((d <= r).sum())

    def test_index_findet_dasselbe_wie_die_vollsuche(self):
        """Der eigentliche Test. Einschliesslich der drei Stellen, an denen so ein Index
        typischerweise falsch liegt: am Pol, über den Nullpunkt der Rektaszension hinweg
        und bei grossem Radius."""
        faelle = [(45.0, 10.0, 1.0, "aequatornah"),
                  (200.0, -35.0, 0.5, "sued, kleiner Radius"),
                  (350.0, 78.0, 1.0, "polnah"),
                  (0.3, 0.0, 1.0, "ueber RA=0 hinweg"),
                  (359.8, -5.0, 1.5, "knapp vor RA=360"),
                  (120.0, -88.5, 2.0, "sehr polnah"),
                  (10.0, 89.5, 1.0, "fast am Nordpol"),
                  (77.0, 0.0, 5.0, "grosser Radius")]
        for ra, dec, r, name in faelle:
            with self.subTest(feld=name):
                gefunden = int(self.kat.kegelsuche(ra, dec, r)["ra"].size)
                self.assertEqual(gefunden, self._stumpf(ra, dec, r),
                                 "%s: Index %d, Vollsuche %d"
                                 % (name, gefunden, self._stumpf(ra, dec, r)))

    def test_index_ist_deutlich_schneller(self):
        """Ohne Geschwindigkeitsvorteil braeuchte es den Index nicht."""
        import time
        t0 = time.perf_counter()
        for _ in range(20):
            self.kat.kegelsuche(45.0, 10.0, 1.0)
        t_index = time.perf_counter() - t0
        t0 = time.perf_counter()
        for _ in range(20):
            self._stumpf(45.0, 10.0, 1.0)
        t_stumpf = time.perf_counter() - t0
        self.assertLess(t_index, t_stumpf * 0.5,
                        "Index %.1f ms, Vollsuche %.1f ms je Abfrage"
                        % (1000 * t_index / 20, 1000 * t_stumpf / 20))

    def test_helligkeitsgrenzen(self):
        alle = self.kat.kegelsuche(45.0, 10.0, 3.0)
        hell = self.kat.kegelsuche(45.0, 10.0, 3.0, max_mag=12.0)
        schwach = self.kat.kegelsuche(45.0, 10.0, 3.0, min_mag=15.0)
        self.assertLess(hell["ra"].size, alle["ra"].size)
        self.assertTrue(np.all(hell["g_mag"] <= 12.0))
        self.assertTrue(np.all(schwach["g_mag"] >= 15.0))

    def test_leeres_feld_gibt_leere_arrays(self):
        klein = gaia_lokal.Katalog([10.0], [10.0], [12.0], [1.0])
        t = klein.kegelsuche(200.0, -60.0, 0.5)
        self.assertEqual(t["ra"].size, 0)
        self.assertEqual(t["bp_rp"].size, 0)

    def test_unbrauchbare_eintraege_fliegen_raus(self):
        k = gaia_lokal.Katalog([10.0, np.nan, 12.0], [5.0, 5.0, np.inf],
                               [12.0, 13.0, 14.0], [1.0, 1.0, 1.0])
        self.assertEqual(len(k), 1)

    def test_speichern_und_laden(self):
        d = tempfile.mkdtemp(prefix="fp_gaia_")
        try:
            p = os.path.join(d, "k.npz")
            self.assertTrue(self.kat.speichern(p))
            k2 = gaia_lokal.Katalog.laden(p, log=_stille)
            self.assertIsNotNone(k2)
            self.assertEqual(len(k2), len(self.kat))
            a = self.kat.kegelsuche(45.0, 10.0, 1.0)["ra"]
            b = k2.kegelsuche(45.0, 10.0, 1.0)["ra"]
            self.assertTrue(np.array_equal(np.sort(a), np.sort(b)))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_kaputte_datei_gibt_none(self):
        d = tempfile.mkdtemp(prefix="fp_gaia_")
        try:
            p = os.path.join(d, "muell.npz")
            with open(p, "wb") as fh:
                fh.write(b"kein numpy")
            self.assertIsNone(gaia_lokal.Katalog.laden(p, log=_stille))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_zusammenfuehren_entfernt_doppelte(self):
        """Wer zwei benachbarte Felder laedt, holt den Ueberlappungsbereich zweimal."""
        a = gaia_lokal.Katalog(self.ra[:1000], self.dec[:1000], self.g[:1000], self.c[:1000])
        b = gaia_lokal.Katalog(self.ra[500:1500], self.dec[500:1500],
                               self.g[500:1500], self.c[500:1500])
        z = gaia_lokal.zusammenfuehren(a, b)
        self.assertEqual(len(z), 1500)
        self.assertEqual(len(gaia_lokal.zusammenfuehren(None, b)), len(b))
        self.assertEqual(len(gaia_lokal.zusammenfuehren(a, None)), len(a))

    def test_abdeckung_meldet_luecken_statt_still_zu_rechnen(self):
        """Ein Katalog ohne das Feld liefert einfach null Sterne — und eine Kalibrierung mit
        null Sternen wuerde entweder scheitern oder, schlimmer, mit Zufall durchlaufen."""
        ok, n, satz = gaia_lokal.abdeckung(self.kat, 45.0, 10.0, 3.0)
        self.assertTrue(ok, satz)
        self.assertGreater(n, 30)
        ok2, n2, satz2 = gaia_lokal.abdeckung(None, 45.0, 10.0, 1.0)
        self.assertFalse(ok2)
        self.assertIn("kein lokaler Katalog", satz2)
        leer = gaia_lokal.Katalog([10.0], [10.0], [12.0], [1.0])
        ok3, n3, satz3 = gaia_lokal.abdeckung(leer, 200.0, -60.0, 0.5)
        self.assertFalse(ok3)
        self.assertEqual(n3, 0)

    def test_winkelabstand_stimmt(self):
        """Haversine gegen bekannte Werte — ein falscher Abstand faellt sonst nirgends auf."""
        self.assertAlmostEqual(float(gaia_lokal._winkelabstand(0, 0, 0, 1)), 1.0, places=6)
        self.assertAlmostEqual(float(gaia_lokal._winkelabstand(0, 0, 1, 0)), 1.0, places=6)
        self.assertAlmostEqual(float(gaia_lokal._winkelabstand(0, 90, 123, -90)), 180.0, places=4)
        # am Pol liegen zwei Punkte mit 180 Grad RA-Abstand nur 1 Grad auseinander
        self.assertAlmostEqual(float(gaia_lokal._winkelabstand(0, 89.5, 180, 89.5)), 1.0, places=4)

    def test_wrapped_ra_queries_agree_with_spherical_full_search(self):
        for ra in (-597.5562673022014, 122.4437326977986, 482.4437326977986):
            with self.subTest(ra=ra):
                result = self.kat.kegelsuche(ra, -58.481389108492074, 2.1672691464432443)
                self.assertEqual(len(result["ra"]), self._stumpf(ra, -58.481389108492074, 2.1672691464432443))
        normalized = gaia_lokal.Katalog([-1, 719], [0, 0], [12, 12], [.5, .5])
        np.testing.assert_array_equal(normalized.ra, [359, 359])

    def test_bad_shapes_complex_and_invalid_search_arguments_are_rejected(self):
        for ra, dec in (([1, 2], [3]), ([[1]], [[2]]), ([1 + 2j], [2])):
            with self.subTest(ra=ra), self.assertRaises(gaia_lokal.ForgePixFehler):
                gaia_lokal.Katalog(ra, dec, [12], [.5])
        for ra, dec, radius in ((np.nan, 0, 1), (0, 91, 1), (0, 0, -1), (0, 0, np.inf)):
            with self.subTest(ra=ra, dec=dec, radius=radius), self.assertRaises(gaia_lokal.ForgePixFehler):
                self.kat.kegelsuche(ra, dec, radius)
        with self.assertRaises(gaia_lokal.ForgePixFehler):
            self.kat.kegelsuche(0, 0, 1, min_mag=15, max_mag=12)

    def test_masked_and_impossible_coordinates_do_not_become_stars(self):
        ra = np.ma.array([1., 2., 3.], mask=[False, True, False])
        k = gaia_lokal.Katalog(ra, [0, 0, 91], [12, 12, 12], [.5, .5, .5])
        np.testing.assert_array_equal(k.ra, [1])

    def test_zero_radius_at_north_pole_uses_existing_last_cell_band(self):
        k = gaia_lokal.Katalog([12., 12.], [90., -90.], [12., 13.], [.5, .5])
        np.testing.assert_array_equal(k.kegelsuche(12., 90., 0.)["dec"], [90.])
        np.testing.assert_array_equal(k.kegelsuche(12., -90., 0.)["dec"], [-90.])
        self.assertEqual(len(k.kegelsuche(12., 0., 180.)["ra"]), 2)

    def test_invalid_epoch_or_motion_metadata_is_not_presented_as_provenance(self):
        for metadata in ({"reference_epoch_jyear": "today"}, {"reference_epoch_jyear": float("nan")},
                         {"reference_epoch_jyear": True}, {"proper_motion_applied": "false"}, {"fields": ["whole sky"]}):
            with self.subTest(metadata=metadata), self.assertRaises(gaia_lokal.ForgePixFehler):
                gaia_lokal.Katalog([10.], [20.], [12.], [.5], metadata=metadata)

    def test_saved_index_is_rebuilt_and_legacy_epoch_stays_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "old.npz")
            np.savez(path, ra=[10.], dec=[20.], g_mag=[12.], bp_rp=[.5],
                     zellen=[0], zell_id=[], zell_start=[], band_grad=gaia_lokal.BAND_GRAD)
            k = gaia_lokal.Katalog.laden(path, log=_stille)
            self.assertEqual(len(k.kegelsuche(10, 20, 1)["ra"]), 1)
            self.assertEqual(k.metadata, {})
            np.savez(path, ra=[10., 11.], dec=[20.], g_mag=[12.], bp_rp=[.5])
            self.assertIsNone(gaia_lokal.Katalog.laden(path, log=_stille))

    def test_metadata_roundtrip_and_merge_do_not_invent_common_epoch(self):
        metadata = {"catalogue": "gaiadr3.gaia_source", "reference_epoch_jyear": 2016.,
                    "proper_motion_applied": False, "fields": [{"ra_deg": 10, "radius_deg": 1}]}
        new = gaia_lokal.Katalog([10.], [20.], [12.], [.5], metadata=metadata)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "new.npz")
            new.speichern(path)
            loaded = gaia_lokal.Katalog.laden(path, log=_stille)
            self.assertEqual(loaded.metadata, metadata)
        mixed = gaia_lokal.zusammenfuehren(new, gaia_lokal.Katalog([11.], [20.], [12.], [.5]))
        self.assertNotIn("reference_epoch_jyear", mixed.metadata)
        self.assertEqual(len(mixed.metadata["fields"]), 1)


class TestDownload(unittest.TestCase):
    def fake_archive(self, rows):
        table = {"ra": np.arange(rows, dtype=float) + 10, "dec": np.full(rows, 20.),
                 "phot_g_mean_mag": np.full(rows, 12.), "bp_rp": np.full(rows, .5)}
        archive = Mock(return_value=table)
        return archive, patch.object(gaia_lokal, "_tap_abfrage", archive)

    def test_async_download_requests_overflow_row_and_records_epoch(self):
        archive, modules = self.fake_archive(3)
        with modules:
            k = gaia_lokal.herunterladen(370, 20, 1, grenze=3, log=_stille)
        query = archive.call_args.args[0]
        self.assertIn("TOP 4", query)
        self.assertIn("10.000000, 20.000000", query)
        self.assertEqual(len(k), 3)
        self.assertEqual(k.metadata["reference_epoch_jyear"], 2016.)
        self.assertIs(k.metadata["proper_motion_applied"], False)
        self.assertFalse(k.metadata["fields"][0]["row_limit_reached"])

    def test_truncated_download_cannot_be_stored_as_a_complete_field(self):
        archive, modules = self.fake_archive(4)
        with modules, self.assertRaisesRegex(gaia_lokal.ForgePixFehler, "abgeschnittener"):
            gaia_lokal.herunterladen(10, 20, 1, grenze=3, log=_stille)

    def test_failed_download_preserves_existing_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "saved.npz")
            gaia_lokal.Katalog([10.], [20.], [12.], [.5]).speichern(path)
            with open(path, "rb") as stream:
                before = stream.read()
            with patch.object(gaia_lokal, "herunterladen", side_effect=gaia_lokal.ForgePixFehler("abgeschnitten")):
                with self.assertRaises(gaia_lokal.ForgePixFehler):
                    gaia_lokal.feld_hinzufuegen(10, 20, pfad=path, log=_stille)
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), before)

    def test_native_transport_runs_async_and_cleans_own_job(self):
        from urllib.error import HTTPError
        endpoint = "https://gea.esac.esa.int/tap-server/tap/async"
        job = endpoint + "/test-job"
        class Response(io.BytesIO):
            headers = {}
        reply = {"metadata": [{"name": key} for key in ("ra", "dec", "phot_g_mean_mag", "bp_rp")],
                 "data": [[10., 20., 12., .5]]}
        opener = Mock()
        opener.open.side_effect = [HTTPError(endpoint, 303, "See Other", {"Location": job}, io.BytesIO()),
                                   Response(b"COMPLETED"), Response(json.dumps(reply).encode()), Response()]
        with patch("urllib.request.build_opener", return_value=opener):
            table = gaia_lokal._tap_abfrage("SELECT TOP 2 ra,dec,phot_g_mean_mag,bp_rp FROM gaiadr3.gaia_source")
        np.testing.assert_array_equal(table["ra"], [10.])
        calls = opener.open.call_args_list
        self.assertEqual(calls[0].args[0].full_url, endpoint)
        self.assertIn(b"PHASE=RUN", calls[0].args[0].data)
        self.assertEqual(calls[-1].args[0].method, "DELETE")
        self.assertEqual(calls[-1].args[0].full_url, job)
        self.assertTrue(all(0 < call.kwargs["timeout"] <= 10 for call in calls))

    def test_pre_cancelled_and_invalid_deadline_do_not_start_network(self):
        cancel = threading.Event()
        cancel.set()
        with patch("urllib.request.build_opener") as build:
            with self.assertRaisesRegex(gaia_lokal.ForgePixFehler, "abgebrochen"):
                gaia_lokal._tap_abfrage("SELECT 1", cancel=cancel)
            build.return_value.open.assert_not_called()
        with self.assertRaisesRegex(gaia_lokal.ForgePixFehler, "Zeitlimit"):
            gaia_lokal._tap_abfrage("SELECT 1", timeout=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
