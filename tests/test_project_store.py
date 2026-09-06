"""Project round trips, immutable history, path relocation and failed writes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import numpy as np
from astropy.io import fits
import tifffile
from project_store import Project, ProjectError, fingerprint, resolve


class ProjectStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Canonicalize macOS /var aliases and Windows short temporary paths.
        self.root = Path(self.temp.name).resolve()
        self.bundle = self.root / "project"
        self.bundle.mkdir()
        self.source = self.bundle / "source.fits"
        fits.writeto(self.source, np.arange(240, dtype=np.float32).reshape(12, 20) / 100)
        self.original = self.source.read_bytes()
        self.project = Project.create(self.bundle / "M27.forgepix", "M27",
                                      {"module": 1, "input_directory": self.bundle, "work_directory": self.bundle})

    def test_roundtrip_preserves_sources_and_old_results_after_overwrite(self):
        first = self.project.add_result(self.source, label="Stack")
        result = self.bundle / "processed.tif"
        tifffile.imwrite(result, fits.getdata(self.source) + .03)
        old_bytes = result.read_bytes()
        second = self.project.add_result(result, self.source, "Rauschen reduziert")
        tifffile.imwrite(result, fits.getdata(self.source) + .07)
        third = self.project.add_result(result, self.source, "Weiterbearbeitet")
        opened = Project.open(self.project.path)
        selected, before = opened.select(second)
        self.assertEqual(Path(selected).read_bytes(), old_bytes)
        self.assertEqual(Path(before).read_bytes(), self.original)
        self.assertEqual(opened.data["selected_step"], second)
        self.assertEqual(Project.open(opened.path).data["selected_step"], second)
        self.assertEqual(opened.step(third)["parent_id"], second)
        self.assertEqual(opened.step(second)["parent_id"], first)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(opened.check()[second]["origin"]["status"], "changed")

    def test_moved_project_resolves_relative_archive_and_comparison(self):
        first = self.project.add_result(self.source, comparison=self.source)
        moved = self.root / "moved"
        self.assertEqual(moved.resolve().parent, self.root.resolve())
        self.assertEqual(self.bundle.resolve().parent, self.root.resolve())
        self.bundle.rename(moved)
        reopened = Project.open(moved / "M27.forgepix")
        result, before = reopened.select(first)
        self.assertTrue(Path(result).is_relative_to(moved))
        self.assertTrue(Path(before).is_relative_to(moved))
        self.assertEqual(Path(result).read_bytes(), self.original)
        self.assertIsNotNone(reopened.step(first)["result"]["path"]["relative"])

    def test_project_among_raw_frames_does_not_become_an_input_series(self):
        from astro_input import series_folders
        self.project.add_result(self.source)
        self.assertEqual(series_folders(str(self.bundle)), [(str(self.bundle), 1)])

    def test_missing_or_modified_archive_is_not_opened_even_if_mtime_is_preserved(self):
        first = self.project.add_result(self.source)
        archive = resolve(self.project.step(first)["result"]["path"], self.project.path.parent)
        original_stat = archive.stat()
        archive.write_bytes(b"x" * original_stat.st_size)
        os.utime(archive, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        self.assertEqual(self.project.check()[first]["result"]["status"], "changed")
        with self.assertRaises(ProjectError):
            self.project.select(first)
        archive.unlink()
        self.assertEqual(self.project.check()[first]["result"]["status"], "missing")
        with self.assertRaises(ProjectError):
            self.project.select(first)

    def test_relocation_requires_identical_file_and_does_not_accept_new_pixels(self):
        first = self.project.add_result(self.source)
        wrong = self.bundle / "wrong.fits"
        fits.writeto(wrong, np.ones((12, 20), np.float32))
        before = self.project.path.read_bytes()
        with self.assertRaises(ProjectError):
            self.project.relocate(first, wrong)
        self.assertEqual(self.project.path.read_bytes(), before)
        self.project.relocate(first, self.source)
        self.assertEqual(self.project.select(first)[0], str(self.source))

    def test_failed_atomic_save_preserves_manifest_and_rolls_back_new_archive_files(self):
        self.project.add_result(self.source)
        before = self.project.path.read_bytes()
        result = self.bundle / "new.tif"
        tifffile.imwrite(result, np.ones((20, 20), np.float32))
        archive = resolve(self.project.data["archive"], self.project.path.parent)
        previous = set(archive.iterdir())
        with patch("project_store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.project.add_result(result)
        self.assertEqual(self.project.path.read_bytes(), before)
        self.assertEqual(len(self.project.data["steps"]), 1)
        self.assertEqual(set(archive.iterdir()), previous)
        self.assertFalse(list(self.bundle.glob("*.tmp")))

    def test_external_manifest_change_is_not_overwritten(self):
        data = json.loads(self.project.path.read_bytes())
        data["name"] = "Changed in another window"
        self.project.path.write_text(json.dumps(data), encoding="utf-8")
        changed = self.project.path.read_bytes()
        with self.assertRaisesRegex(ProjectError, "außerhalb"):
            self.project.save()
        self.assertEqual(self.project.path.read_bytes(), changed)

    def test_scientific_export_preserves_fits_headers_and_pixels_exactly(self):
        first = self.project.add_result(self.source)
        destination = self.root / "scientific-export"
        before = self.project.path.read_bytes()
        self.assertEqual(self.project.export_step(first, destination), str(destination))
        self.assertEqual((destination / self.source.name).read_bytes(), self.original)
        report = json.loads((destination / "forgepix-export.json").read_text(encoding="utf-8"))
        self.assertTrue(report["files_copied_unchanged"])
        self.assertEqual(report["files"][0]["sha256"], fingerprint(self.source)["sha256"])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.project.path.read_bytes(), before)
        with self.assertRaises(ProjectError):
            self.project.export_step(first, destination)

    def test_failed_or_changed_export_leaves_no_partial_destination(self):
        first = self.project.add_result(self.source)
        destination = self.root / "scientific-export"
        def partial_copy(source, target):
            Path(target).write_bytes(b"partial")
            raise OSError("disk full")
        with patch("project_store.shutil.copyfile", side_effect=partial_copy):
            with self.assertRaises(OSError):
                self.project.export_step(first, destination)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.root.glob(".forgepix-export-*")))
        archived = resolve(self.project.step(first)["result"]["path"], self.bundle)
        archived.write_bytes(b"changed")
        with self.assertRaises(ProjectError):
            self.project.export_step(first, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_ai_artifacts_and_coverage_are_archived_byte_for_byte(self):
        result = self.bundle / "result_32bit.tif"
        tifffile.imwrite(result, np.ones((12, 20), np.float32),
                         description=json.dumps({"FPCOV": "coverage.tif"}))
        residual = self.bundle / "stars_residual_32bit.tif"
        tifffile.imwrite(residual, np.full((12, 20), -.01, np.float32))
        coverage = self.bundle / "coverage.tif"
        tifffile.imwrite(coverage, np.ones((12, 20), np.uint8))
        items = [result, residual, coverage]
        report = {"outputs": [p.name for p in items], "output_integrity": [
            {"name": p.name, "bytes": p.stat().st_size, "sha256": fingerprint(p)["sha256"]} for p in items],
            "task": "starless", "model_id": "test", "strength": .5}
        (self.bundle / "ai_report.json").write_text(json.dumps(report), encoding="utf-8")
        identifier = self.project.add_result(result, self.source)
        saved = Path(self.project.select(identifier)[0])
        for path in items + [self.bundle / "ai_report.json"]:
            self.assertEqual((saved.parent / path.name).read_bytes(), path.read_bytes())
        destination = self.root / "ai-export"
        self.project.export_step(identifier, destination)
        for path in items + [self.bundle / "ai_report.json"]:
            self.assertEqual((destination / path.name).read_bytes(), path.read_bytes())
        (saved.parent / "coverage.tif").unlink()
        with self.assertRaisesRegex(ProjectError, "Begleitdatei"):
            self.project.select(identifier)

    def test_unknown_schema_and_invalid_selected_step_are_rejected(self):
        for change in ({"schema_version": True}, {"schema_version": 999}, {"selected_step": "unknown"}):
            data = {**self.project.data, **change}
            self.project.path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ProjectError):
                Project.open(self.project.path)


if __name__ == "__main__":
    unittest.main()
