"""Independent ID/epoch/quality/file contracts for the separate Gaia/GSPC field."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import gaia_lokal
import photometric_catalogue as pc


def good_columns(count=3):
    data = {"source_id": np.array([9007199254740993 + 2 * i for i in range(count)], np.int64),
        "ra": np.linspace(10, 11, count), "dec": np.full(count, 60.), "ref_epoch": np.full(count, 2016.),
        "pmra": np.full(count, 1000.), "pmdec": np.full(count, 100.),
        "ra_error": np.full(count, .3), "dec_error": np.full(count, .4),
        "pmra_error": np.full(count, .05), "pmdec_error": np.full(count, .06),
        "c_star": np.zeros(count), "ruwe": np.ones(count), "phot_g_mean_mag": np.full(count, 12.),
        "ipd_frac_multi_peak": np.zeros(count, np.int16), "duplicated_source": np.zeros(count, np.int16),
        "astrometric_params_solved": np.full(count, 31, np.int16),
        "phot_variable_flag": ["NOT_AVAILABLE"] * count}
    for band in "bvr":
        data[band + "_jkc_mag"] = np.full(count, 12.)
        data[band + "_jkc_flux"] = np.full(count, 3e-16)
        data[band + "_jkc_flux_error"] = np.full(count, 3e-18)
        data[band + "_jkc_flag"] = np.ones(count, np.int16)
    return data


class PhotometricCatalogueTests(unittest.TestCase):
    def test_int64_ids_survive_roundtrip_beyond_float_precision(self):
        catalogue = pc.PhotometricCatalogue(good_columns(), {"origin": "test"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "field.npz"
            catalogue.save(path)
            restored = pc.PhotometricCatalogue.load(path)
        np.testing.assert_array_equal(restored.columns["source_id"], [9007199254740993, 9007199254740995, 9007199254740997])
        self.assertEqual(restored.columns["source_id"].dtype, np.dtype("int64"))
        self.assertEqual(restored.metadata["origin"], "test")
        self.assertEqual(restored.metadata["epoch_time_scale"], "tcb")
        self.assertEqual(restored.metadata["flux_unit"], "W m-2 nm-1")

    def test_float_boolean_duplicate_masked_overflow_ids_are_rejected(self):
        bad = ([float(9007199254740993)], [1.], [True], [None], [0], [-1], [2 ** 63],
               np.array([2 ** 63], np.uint64), np.ma.array([123], mask=[True]), [123, 123], ["1e18"])
        for ids in bad:
            with self.subTest(ids=ids), self.assertRaises(pc.ForgePixFehler):
                pc.PhotometricCatalogue({"source_id": ids, "ra": [10.] * len(ids), "dec": [20.] * len(ids)})
        exact = pc.PhotometricCatalogue({"source_id": ["9007199254740993"], "ra": [10], "dec": [20]})
        self.assertEqual(exact.columns["source_id"][0], 9007199254740993)

    def test_import_owns_arrays_and_never_modifies_caller_ra(self):
        columns = good_columns()
        columns["ra"][0] = -1
        before = {key: np.array(value, copy=True) for key, value in columns.items()}
        catalogue = pc.PhotometricCatalogue(columns)
        for key, value in columns.items():
            np.testing.assert_array_equal(value, before[key])
        self.assertEqual(catalogue.columns["ra"][0], 359.)
        columns["ra"][0] = 100.
        self.assertEqual(catalogue.columns["ra"][0], 359.)
        with self.assertRaises(ValueError):
            catalogue.columns["ra"][0] = 2.

    def test_missing_pm_epoch_and_observation_epoch_stay_explicit(self):
        data = good_columns(4)
        data["ref_epoch"][1] = np.nan
        data["pmra"][2] = np.nan
        data["pmdec"] = np.ma.array(data["pmdec"], mask=[False, False, False, True])
        catalogue = pc.PhotometricCatalogue(data)
        positions = catalogue.positions_at(2026.)
        np.testing.assert_array_equal(positions["usable"], [True, False, False, False])
        self.assertTrue(np.isnan(positions["ra"][1:]).all())
        self.assertEqual(positions["status"][1], "missing_reference_epoch")
        self.assertEqual(positions["status"][2], "missing_proper_motion")
        reference = catalogue.positions_at(2016.)
        np.testing.assert_array_equal(reference["usable"], [True, False, True, True])
        unknown = catalogue.positions_at(None)
        self.assertFalse(unknown["usable"].any())
        self.assertEqual(unknown["report"]["status_counts"], {"missing_observation_epoch": 4})
        self.assertTrue(np.isnan(unknown["ra"]).all())
        self.assertTrue(np.isfinite(catalogue.columns["ra"]).all())

    def test_motion_matches_independent_cartesian_tangent_prediction(self):
        data = good_columns(3)
        data["ra"] = np.array([359.999, 12., 175.])
        data["dec"] = np.array([60., 89.9, -85.])
        data["pmra"] = np.array([1000., -2000., 450.])
        data["pmdec"] = np.array([100., 300., -600.])
        data["ref_epoch"] = np.array([2016., 2015., 2017.])
        catalogue = pc.PhotometricCatalogue(data)
        actual = catalogue.positions_at(2026.)
        ra, dec = np.radians(data["ra"]), np.radians(data["dec"])
        radial = np.column_stack((np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)))
        east = np.column_stack((-np.sin(ra), np.cos(ra), np.zeros(3)))
        north = np.column_stack((-np.sin(dec) * np.cos(ra), -np.sin(dec) * np.sin(ra), np.cos(dec)))
        step = np.radians((2026. - data["ref_epoch"]) / 3_600_000.)
        moved = radial + step[:, None] * (east * data["pmra"][:, None] + north * data["pmdec"][:, None])
        moved /= np.linalg.norm(moved, axis=1)[:, None]
        # Compare angular separation, not bare RA close to a pole. ERFA also
        # accounts for light-time effects absent from this independent tangent
        # approximation; the tolerance remains 1e-8 degrees on the sky.
        ar, ad = np.radians(actual["ra"]), np.radians(actual["dec"])
        observed = np.column_stack((np.cos(ad) * np.cos(ar), np.cos(ad) * np.sin(ar), np.sin(ad)))
        error_deg = np.degrees(np.arctan2(np.linalg.norm(np.cross(observed, moved), axis=1),
                                         np.sum(observed * moved, axis=1)))
        self.assertLess(float(error_deg.max()), 1e-8)
        self.assertLess(actual["ra"][0], .01)  # Wrap crossed; cos(dec) applied exactly once.
        self.assertFalse(actual["report"]["covariance_propagated"])
        self.assertFalse(actual["report"]["perspective_acceleration_modelled"])

    def test_epoch_validation_and_precancellation(self):
        catalogue = pc.PhotometricCatalogue(good_columns())
        for epoch in (np.nan, np.inf, True, 1000, 2400, 2026 + 1j):
            with self.subTest(epoch=epoch), self.assertRaises(pc.ForgePixFehler):
                catalogue.positions_at(epoch)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(pc.ForgePixFehler, "abgebrochen"):
            catalogue.positions_at(2026, cancel=cancel)

    def test_quality_flags_must_be_valid_and_good_catalogue_is_not_stability_proof(self):
        data = good_columns(7)
        data["b_jkc_flag"][1] = 0
        data["v_jkc_flux_error"][2] = np.nan
        data["r_jkc_flux"][3] = 1e-19
        data["duplicated_source"][4] = 1
        data["phot_variable_flag"][5] = "VARIABLE"
        data["c_star"][6] = .5
        catalogue = pc.PhotometricCatalogue(data)
        np.testing.assert_array_equal(catalogue.quality_mask(), [True, False, False, False, False, False, False])
        self.assertEqual(catalogue.quality_report()["variability_not_available"], 6)
        self.assertIn("not evidence of constant", catalogue.quality_report()["limitations"])

    def test_null_fields_survive_storage_and_cannot_become_zero_quality_flags(self):
        data = good_columns()
        data["duplicated_source"] = [False, None, True]
        data["b_jkc_flag"] = [1, None, 0]
        data["pmra"] = [1000., None, 0.]
        catalogue = pc.PhotometricCatalogue(data)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nulls.npz"
            catalogue.save(path)
            catalogue = pc.PhotometricCatalogue.load(path)
        np.testing.assert_array_equal(catalogue.columns["duplicated_source"], [0, -1, 1])
        np.testing.assert_array_equal(catalogue.columns["b_jkc_flag"], [1, -1, 0])
        self.assertTrue(np.isnan(catalogue.columns["pmra"][1]))
        np.testing.assert_array_equal(catalogue.quality_mask(), [True, False, False])

    def test_bad_shapes_units_flags_errors_and_coordinates_fail(self):
        for key, value in (("ra", [10]), ("dec", [0, 91, 0]), ("pmra_error", [-1, 0, 0]),
                           ("ra_dec_corr", [0, 2, 0]), ("b_jkc_flag", [1, .5, 1]),
                           ("ipd_frac_multi_peak", [0, 101, 0]), ("ra", [1j, 0, 1])):
            data = good_columns()
            data[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(pc.ForgePixFehler):
                pc.PhotometricCatalogue(data)
        for metadata in ({"epoch_time_scale": "utc"}, {"reference_frame": "FK5"}, {"flux_unit": "ADU"}):
            with self.assertRaises(pc.ForgePixFehler):
                pc.PhotometricCatalogue(good_columns(), metadata)

    def test_legacy_or_corrupt_format_is_not_silently_upgraded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.npz"
            gaia_lokal.Katalog([10], [20], [12], [.5]).speichern(path)
            original = path.read_bytes()
            with self.assertRaises(pc.ForgePixFehler):
                pc.PhotometricCatalogue.load(path)
            self.assertEqual(path.read_bytes(), original)
            path.write_bytes(b"not an archive")
            with self.assertRaises(pc.ForgePixFehler):
                pc.PhotometricCatalogue.load(path)

    def test_save_refuses_existing_file_and_publication_race(self):
        catalogue = pc.PhotometricCatalogue(good_columns())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "existing.npz"
            path.write_bytes(b"keep")
            with self.assertRaises(pc.ForgePixFehler):
                catalogue.save(path)
            self.assertEqual(path.read_bytes(), b"keep")
            path = Path(folder) / "raced.npz"
            name = "rename" if os.name == "nt" else "link"
            original = getattr(pc.os, name)
            def race(src, dst):
                Path(dst).write_bytes(b"concurrent writer")
                return original(src, dst)
            with patch.object(pc.os, name, side_effect=race), self.assertRaises(pc.ForgePixFehler):
                catalogue.save(path)
            self.assertEqual(path.read_bytes(), b"concurrent writer")
            self.assertFalse(list(Path(folder).glob("*.pending")))

    def test_failed_flush_publishes_no_catalogue_and_cleans_pending_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "failed.npz"
            with patch.object(pc.os, "fsync", side_effect=OSError("storage failure")):
                with self.assertRaises(pc.ForgePixFehler):
                    pc.PhotometricCatalogue(good_columns()).save(path)
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_unknown_schema_and_missing_measurement_column_are_rejected(self):
        catalogue = pc.PhotometricCatalogue(good_columns())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "future.npz"
            catalogue.save(path)
            with np.load(path, allow_pickle=False) as stored:
                payload = {key: stored[key] for key in stored.files}
            payload["schema_version"] = np.int64(2)
            np.savez(path, **payload)
            with self.assertRaises(pc.ForgePixFehler):
                pc.PhotometricCatalogue.load(path)
            payload["schema_version"] = np.int64(1)
            del payload["b_jkc_flux_error"]
            np.savez(path, **payload)
            with self.assertRaises(pc.ForgePixFehler):
                pc.PhotometricCatalogue.load(path)

    def test_empty_catalogue_has_explicit_empty_positions_and_quality(self):
        catalogue = pc.PhotometricCatalogue({"source_id": [], "ra": [], "dec": []})
        self.assertEqual(len(catalogue), 0)
        self.assertEqual(catalogue.quality_mask().shape, (0,))
        self.assertEqual(catalogue.positions_at(2026)["report"]["usable_positions"], 0)


class PhotometricDownloadTests(unittest.TestCase):
    @staticmethod
    def raw_table(count=3):
        catalogue = pc.PhotometricCatalogue(good_columns(count))
        rows = [[catalogue.columns[name][i].item() for name in pc.COLUMNS] for i in range(count)]
        # JSON carries nulls; no dataframe or floating matrix is used for rows.
        rows = [[None if isinstance(value, float) and np.isnan(value) else value for value in row] for row in rows]
        return {"columns": list(pc.COLUMNS), "rows": rows, "metadata": [{"name": name} for name in pc.COLUMNS]}

    def test_download_join_retains_ids_flags_and_nulls(self):
        with patch.object(gaia_lokal, "_tap_abfrage", return_value=self.raw_table()) as transport:
            catalogue = pc.download_field(370, 20, .2, max_mag=14, limit=3, log=lambda *_: None)
        self.assertEqual(catalogue.columns["source_id"][0], 9007199254740993)
        self.assertEqual(catalogue.metadata["origin"], "ESA TAP")
        self.assertFalse(catalogue.metadata["spatial_completeness_proven"])
        query = transport.call_args.args[0]
        self.assertIn("TOP 4", query)
        self.assertIn("INNER JOIN gaiadr3.synthetic_photometry_gspc", query)
        self.assertIn("g.source_id = p.source_id", query)
        self.assertIn("p.r_jkc_flux_error", query)
        self.assertIn("10.0000000000", query)
        self.assertTrue(transport.call_args.kwargs["raw_rows"])

    def test_overflow_and_lossy_transport_ids_are_rejected(self):
        with patch.object(gaia_lokal, "_tap_abfrage", return_value=self.raw_table(4)):
            with self.assertRaisesRegex(pc.ForgePixFehler, "abgeschnitten"):
                pc.download_field(10, 20, limit=3, log=lambda *_: None)
        table = self.raw_table()
        table["rows"][0][0] = float(table["rows"][0][0])
        with patch.object(gaia_lokal, "_tap_abfrage", return_value=table):
            with self.assertRaisesRegex(pc.ForgePixFehler, "int64"):
                pc.download_field(10, 20, log=lambda *_: None)

    def test_large_or_cancelled_queries_never_start_network(self):
        with patch.object(gaia_lokal, "_tap_abfrage") as transport:
            for kwargs in ({"radius_deg": 6}, {"radius_deg": 0}, {"limit": 20001}, {"max_mag": 19}):
                with self.assertRaises(pc.ForgePixFehler):
                    pc.download_field(10, 20, **kwargs)
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(pc.ForgePixFehler):
                pc.download_field(10, 20, cancel=cancel)
            transport.assert_not_called()

    def test_native_transport_raw_rows_never_converts_json_integer_to_float(self):
        from urllib.error import HTTPError
        endpoint = "https://gea.esac.esa.int/tap-server/tap/async"
        class Response(io.BytesIO):
            headers = {}
        raw = {"metadata": [{"name": "source_id"}, {"name": "duplicated_source"}, {"name": "pmra"}],
               "data": [[9007199254740993, False, None]]}
        opener = Mock()
        opener.open.side_effect = [HTTPError(endpoint, 303, "See Other", {"Location": endpoint + "/test"}, io.BytesIO()),
            Response(b"COMPLETED"), Response(json.dumps(raw).encode()), Response()]
        with patch("urllib.request.build_opener", return_value=opener):
            result = gaia_lokal._tap_abfrage("SELECT source_id, duplicated_source, pmra FROM gaiadr3.gaia_source", raw_rows=True)
        self.assertIs(type(result["rows"][0][0]), int)
        self.assertEqual(result["rows"][0][0], 9007199254740993)
        self.assertIs(result["rows"][0][1], False)
        self.assertIsNone(result["rows"][0][2])
        self.assertEqual(opener.open.call_args_list[-1].args[0].method, "DELETE")


if __name__ == "__main__":
    unittest.main()
