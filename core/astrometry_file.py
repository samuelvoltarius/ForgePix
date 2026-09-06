"""FITS-only astrometry transactions retaining pixels, units and coverage."""
from pathlib import Path
from copy import deepcopy
import json
import os
import shutil
import tempfile

import numpy as np
from astropy.io import fits

import ai_restore
import astrometry
from constants import ForgePixFehler, log_print
from gaia_lokal import Katalog
from project_store import _companions


def _proof(path, cancel):
    return dict(ai_restore._file_integrity(Path(path), cancel), path=str(Path(path).resolve()))


def solve_file(source, catalogue_path, hints, output_root=None, *, cancel=None, log=log_print):
    """Publish a new result directory only after source and output checks pass.

    Supports linear single-primary-HDU FITS with complete known coverage. Source
    pixel values and dtype are kept; no resampling or color calibration occurs.
    """
    source, catalogue_path = Path(source).resolve(), Path(catalogue_path).resolve()
    if source.suffix.lower() not in {".fit", ".fits", ".fts"}:
        raise ForgePixFehler("Für die eigene Astrometrie bitte einen linearen FITS-Stack wählen.")
    parent = Path(output_root).resolve() if output_root else source.parent
    if not parent.is_dir():
        raise ForgePixFehler("Bitte einen vorhandenen Ergebnisordner wählen.")
    ai_restore._cancelled(cancel)
    source_proof, catalogue_proof = _proof(source, cancel), _proof(catalogue_path, cancel)
    image, _, metadata, _ = ai_restore._read_source(source)
    with fits.open(source, memmap=False) as hdus:
        if len(hdus) != 1:
            raise ForgePixFehler("Die eigene Astrometrie unterstützt derzeit ein Bild im primären FITS-HDU ohne weitere HDUs.")
        data, header = hdus[0].data.copy(), hdus[0].header.copy()
    ai_restore._coverage(source, header, metadata, image.shape[:2], cancel)
    if data.ndim == 3:
        image = image[..., ::-1]  # FITS/AI reader RGB -> solver's BGR convention.
    files, _ = _companions(source)
    declared_ai = (header.get("CREATOR") == "ForgePix" and header.get("FPDOMAIN") == "LINEAR_AI_ESTIMATE"
                   and header.get("FPAIROLE") in {"result", "stars_residual"})
    source_ai = None
    if declared_ai:
        try:
            source_ai = json.loads((source.parent / "ai_report.json").read_text(encoding="utf-8"))
            if source.name not in source_ai["outputs"] or not source_ai.get("output_integrity"):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ForgePixFehler("Für dieses KI-Ergebnis fehlt ein gültiger Herkunftsbericht.") from exc
    source_files = [_proof(path, cancel) for path in files]
    catalogue = Katalog.laden(catalogue_path, log=log)
    if catalogue is None:
        raise ForgePixFehler("Der lokale Sternkatalog konnte nicht gelesen werden.")
    result = astrometry.solve(image, catalogue, hints, cancel=cancel, log=log)
    ai_restore._cancelled(cancel)
    for proof in [source_proof, catalogue_proof, *source_files]:
        if _proof(proof["path"], cancel)["sha256"] != proof["sha256"]:
            raise ForgePixFehler("Eingabe oder Katalog wurde während der Astrometrie verändert.")
    staging = Path(tempfile.mkdtemp(prefix="stack-astrometry-pending-", dir=parent))
    destination = parent / staging.name.replace("-pending-", "-", 1)
    created = []
    try:
        out = staging / "solved.fits"
        created.append(out)
        updated = astrometry.solution_header(result, header)
        # Supplying the original physical pixel array recomputes FITS structural
        # cards and unsigned scaling without normalizing its scientific units.
        fits.PrimaryHDU(data, header=updated).writeto(out, checksum=True)
        companions = []
        for key in ("FPCOV", "FPDRZCOV", "FPDRZWGT"):
            name = header.get(key)
            if name:
                if Path(name).name != name or name in {"solved.fits", "astrometry_report.json"}:
                    raise ForgePixFehler("Ungültiger Begleitdateiname im FITS-Header.")
                src, target = source.parent / name, staging / name
                if target in created:
                    continue
                before = _proof(src, cancel)
                created.append(target)
                shutil.copyfile(src, target)
                after = _proof(target, cancel)
                if before["sha256"] != after["sha256"] or before["sha256"] != _proof(src, cancel)["sha256"]:
                    raise ForgePixFehler("Die Abdeckungsdatei wurde während der Sicherung verändert.")
                companions.append(after)
        with fits.open(out, memmap=False, checksum=True) as hdus:
            if (hdus[0].data.shape != data.shape or hdus[0].data.dtype.kind != data.dtype.kind
                    or hdus[0].data.dtype.itemsize != data.dtype.itemsize
                    or not np.array_equal(hdus[0].data, data)):
                raise ForgePixFehler("Die Astrometrie-Ausgabe erhält die ursprünglichen FITS-Werte nicht exakt.")
        source_reports = {}
        for proof in source_files:
            if Path(proof["path"]).suffix.lower() == ".json":
                source_reports[proof["name"]] = json.loads(Path(proof["path"]).read_text(encoding="utf-8"))
        report = {"format": "ForgePixAstrometry", "schema_version": 1, "source": source_proof,
                  "source_files": source_files, "catalogue": catalogue_proof,
                  "source_processing_reports": source_reports,
                  "catalogue_metadata": catalogue.metadata, "hints": dict(hints),
                  "solution": result.report, "pixels_unchanged": True,
                  "original_dtype": str(data.dtype), "resampled": False,
                  "output_integrity": [{k: v for k, v in _proof(out, cancel).items() if k != "path"},
                      *[{k: v for k, v in item.items() if k != "path"} for item in companions]]}
        report_path = staging / "astrometry_report.json"
        created.append(report_path)
        with report_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        if source_ai is not None:
            # WCS changes file bytes but leaves the AI estimate's pixels intact.
            # Keep its original inference provenance and record this additional
            # operation explicitly instead of reclassifying it as observed data.
            derived = deepcopy(source_ai)
            derived["postprocessing"] = list(derived.get("postprocessing", [])) + [{
                "operation": "native_astrometry", "report": report_path.name,
                "input_sha256": source_proof["sha256"], "pixels_unchanged": True,
                "model_executed_again": False}]
            derived["range"] = [float(data.min()), float(data.max())]
            derived["shape"] = list(image.shape)
            derived.pop("reconstruction_max_error", None)
            derived.pop("residual", None)
            derived["output_integrity"] = deepcopy(report["output_integrity"]) + [
                {key: value for key, value in _proof(report_path, cancel).items() if key != "path"}]
            derived["outputs"] = [item["name"] for item in derived["output_integrity"]]
            ai_report_path = staging / "ai_report.json"
            created.append(ai_report_path)
            with ai_report_path.open("x", encoding="utf-8") as stream:
                json.dump(derived, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
        for proof in [source_proof, catalogue_proof, *source_files]:
            if _proof(proof["path"], cancel)["sha256"] != proof["sha256"]:
                raise ForgePixFehler("Eine Quelldatei wurde vor dem Abschluss verändert.")
        ai_restore._cancelled(cancel)
        staging.rename(destination)
        return {"result_path": str(destination / out.name),
                "report_path": str(destination / report_path.name), "report": report}
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        staging.rmdir()
        raise
