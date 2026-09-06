"""Pinned, native AI recipes on linear files; no scripts or arbitrary commands.

A run snapshots its recipe and input group, then delegates each ordered step to
ai_restore.run_file. Journals describe saved files, not a resumable process graph
or scientific model qualification. Completed steps survive cancellation/failure.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid

import ai_restore
from constants import ForgePixFehler, log_print
from project_store import _companions


TASKS = ("denoise", "background", "deblur", "starless")
DEVICES = ("auto", "cpu", "gpu", "cuda", "directml", "coreml")
MAX_STEPS = 32


class RecipeError(ForgePixFehler):
    """Invalid recipe/input, or a journal that could not be safely saved."""


class _Cancelled(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cancelled(cancel):
    return cancel is not None and bool(cancel.is_set() if hasattr(cancel, "is_set") else cancel())


def _check_cancel(cancel):
    if _cancelled(cancel):
        raise _Cancelled("Rezeptlauf abgebrochen.")


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _atomic_json(path, value):
    path = Path(path)
    payload = _json_bytes(value)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecipeError("Ein Rezeptfeld wurde doppelt angegeben: %s" % key)
        result[key] = value
    return result


def validate_recipe(value):
    """Return a detached canonical recipe; validate schema without loading models."""
    if not isinstance(value, dict) or set(value) != {"format", "schema_version", "name", "steps"}:
        raise RecipeError("Das Rezept benötigt Format, Version, Name und Schritte; weitere Felder sind nicht erlaubt.")
    if (value["format"] != "ForgePixRecipe" or type(value["schema_version"]) is not int
            or value["schema_version"] != 1):
        raise RecipeError("Unbekanntes Rezeptformat. Unterstützt wird ForgePix-Rezeptversion 1.")
    name = value["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > 200 or any(ord(char) < 32 for char in name):
        raise RecipeError("Bitte einen gültigen Rezeptnamen mit höchstens 200 Zeichen verwenden.")
    if not isinstance(value["steps"], list) or not 1 <= len(value["steps"]) <= MAX_STEPS:
        raise RecipeError("Ein Rezept benötigt zwischen 1 und %d Schritten." % MAX_STEPS)
    steps = []
    for index, step in enumerate(value["steps"], 1):
        if not isinstance(step, dict) or set(step) != {"task", "model_id", "model_sha256", "strength", "device"}:
            raise RecipeError("Schritt %d: Aufgabe, Modell-ID, Modell-Prüfsumme, Wirkung und Recheneinheit sind erforderlich." % index)
        if not isinstance(step["task"], str) or step["task"] not in TASKS:
            raise RecipeError("Schritt %d: Nur eigene KI-Funktionen sind in dieser Rezeptversion erlaubt." % index)
        if not isinstance(step["model_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", step["model_id"]):
            raise RecipeError("Schritt %d: Ungültige Modell-ID." % index)
        if not isinstance(step["model_sha256"], str) or not re.fullmatch(r"[a-fA-F0-9]{64}", step["model_sha256"]):
            raise RecipeError("Schritt %d: Die genaue Modell-Prüfsumme fehlt oder ist ungültig." % index)
        strength = step["strength"]
        if type(strength) not in (int, float) or not 0 <= strength <= 1 or not math.isfinite(strength):
            raise RecipeError("Schritt %d: Die Wirkung muss zwischen 0 und 1 liegen." % index)
        if not isinstance(step["device"], str) or step["device"] not in DEVICES:
            raise RecipeError("Schritt %d: Unbekannte Recheneinheit." % index)
        steps.append(dict(step, model_sha256=step["model_sha256"].lower(), strength=float(strength)))
    return {"format": "ForgePixRecipe", "schema_version": 1, "name": name.strip(), "steps": steps}


def load_recipe(path):
    """Read a portable recipe. No model or input is downloaded or executed."""
    try:
        with Path(path).open("rb") as stream:
            payload = stream.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise RecipeError("Die Rezeptdatei ist zu groß.")
        return validate_recipe(json.loads(payload, object_pairs_hook=_unique_keys))
    except RecipeError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise RecipeError("Das Rezept kann nicht gelesen werden: %s" % exc) from exc


def save_recipe(path, recipe):
    """Atomically save the validated recipe; retain an old file on write failure."""
    recipe = validate_recipe(recipe)
    path = Path(path).resolve()
    try:
        _atomic_json(path, recipe)
    except (OSError, ValueError) as exc:
        raise RecipeError("Das Rezept konnte nicht gespeichert werden: %s" % exc) from exc
    return path


def pin_step(model_id, *, strength=.5, device="auto", model_dir=None):
    """Create a step using the verified local model's exact task and byte hash."""
    try:
        manifest, _ = ai_restore._resolve(model_id, model_dir)
    except ForgePixFehler as exc:
        raise RecipeError(str(exc)) from exc
    step = {"task": manifest["task"], "model_id": manifest["id"], "model_sha256": manifest["sha256"],
            "strength": strength, "device": device}
    return validate_recipe({"format": "ForgePixRecipe", "schema_version": 1, "name": "Step", "steps": [step]})["steps"][0]


def _proof(path, cancel=None):
    path = Path(path).resolve()
    _check_cancel(cancel)
    before = path.stat()
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            _check_cancel(cancel)
            digest.update(block)
            size += len(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or size != after.st_size:
        raise RecipeError("Eine Datei wurde während der Prüfung verändert: %s" % path)
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}


def _verify_files(records, cancel=None):
    for record in records:
        actual = _proof(record["path"], cancel)
        if (actual["bytes"], actual["sha256"]) != (record["bytes"], record["sha256"]):
            raise RecipeError("Eine Datei entspricht nicht mehr dem gesicherten Rezeptlauf: %s" % record["path"])


def _model_matches(step, model_dir, cancel):
    manifest, _ = ai_restore._resolve(step["model_id"], model_dir, cancel)
    if manifest["task"] != step["task"] or manifest["sha256"].lower() != step["model_sha256"]:
        raise RecipeError("Modellaufgabe oder Prüfsumme passt nicht zum Rezept: %s" % step["model_id"])


def _preflight(recipe, source, model_dir, cancel):
    seen = set()
    for step in recipe["steps"]:
        _check_cancel(cancel)
        key = (step["model_id"], step["model_sha256"], step["task"])
        if key not in seen:
            _model_matches(step, model_dir, cancel)
            seen.add(key)
    image, header, metadata, _ = ai_restore._read_source(source)
    ai_restore._coverage(source, header, metadata, image.shape[:2], cancel)
    del image
    files, _ = _companions(source)
    names = [path.name.casefold() for path in files]
    if len(names) != len(set(names)):
        raise RecipeError("Gleichnamige Eingabe- und Begleitdateien können nicht gemeinsam gesichert werden.")
    return [_proof(path, cancel) for path in files]


def _snapshot(records, directory, cancel):
    directory.mkdir()
    created, proofs = [], []
    try:
        for record in records:
            _check_cancel(cancel)
            destination = directory / Path(record["path"]).name
            created.append(destination)
            with Path(record["path"]).open("rb") as source, destination.open("xb") as target:
                while block := source.read(1024 * 1024):
                    _check_cancel(cancel)
                    target.write(block)
                target.flush()
                os.fsync(target.fileno())
            saved = _proof(destination, cancel)
            if (saved["bytes"], saved["sha256"]) != (record["bytes"], record["sha256"]):
                raise RecipeError("Die Eingabe wurde während der Sicherung verändert: %s" % record["path"])
            proofs.append(saved)
        _verify_files(records, cancel)
        return proofs
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        directory.rmdir()
        raise


def _completed_group(result, expected, input_proof, cancel):
    report_path = result.parent / "ai_report.json"
    payload = report_path.read_bytes()
    report = json.loads(payload)
    if (not isinstance(report, dict) or report.get("schema_version") != 1
            or report.get("task") != expected["task"] or report.get("model_id") != expected["model_id"]
            or str(report.get("model_sha256", "")).lower() != expected["model_sha256"]
            or report.get("strength") != expected["strength"]
            or report.get("source", {}).get("sha256") != input_proof["sha256"]
            or report.get("execution", {}).get("requested_device") != expected["device"]):
        raise RecipeError("Das fertige KI-Ergebnis entspricht nicht dem festgelegten Rezeptschritt.")
    if not {result.name, result.with_suffix(".fits").name}.issubset(report.get("outputs", [])):
        raise RecipeError("Das fertige KI-Ergebnis enthält nicht alle wissenschaftlichen Dateien.")
    files, _ = _companions(result)
    proofs = [_proof(path, cancel) for path in files]
    record = next(item for item in proofs if Path(item["path"]) == report_path)
    if hashlib.sha256(payload).hexdigest() != record["sha256"]:
        raise RecipeError("Der KI-Bericht wurde während der Prüfung verändert.")
    return proofs, report


def _write_journal(report):
    report["updated"] = _now()
    try:
        _atomic_json(report["journal_path"], report)
    except (OSError, ValueError) as exc:
        raise RecipeError("Laufbericht konnte nicht sicher gespeichert werden. Fertige Dateien bleiben unter %s erhalten: %s"
                          % (report["run_dir"], exc)) from exc


def run_recipe(recipe, source, output_root=None, *, model_dir=None, allow_experimental=False,
               cancel=None, progress=None, log=log_print, on_step=None):
    """Run pinned AI steps and return a completed/cancelled/failed journal dict.

    Validation errors raise RecipeError before creating a run folder. Operational
    failures retain a failed journal and completed steps. A journal write failure
    raises RecipeError with the run location. on_step(index, result_path, record)
    receives detached data after the completed step is safely journaled. Progress
    receives (step_index, number_of_steps, done_tiles, total_tiles).
    """
    recipe = load_recipe(recipe) if isinstance(recipe, (str, os.PathLike)) else validate_recipe(recipe)
    recipe_hash = hashlib.sha256(_json_bytes(recipe)).hexdigest()
    if allow_experimental is not True:
        raise RecipeError("Rezeptläufe mit diesen KI-Modellen müssen ausdrücklich als experimentell bestätigt werden.")
    source = Path(source).resolve()
    parent = Path(output_root).resolve() if output_root is not None else source.parent
    if not parent.is_dir():
        raise RecipeError("Bitte einen vorhandenen Ausgabeordner für den neuen Rezeptlauf wählen.")
    pre_cancel = {"status": "cancelled", "run_dir": None, "journal_path": None, "result_path": None,
                  "completed_steps": 0, "steps": [], "recipe_sha256": recipe_hash, "error": None}
    try:
        _check_cancel(cancel)
        source_records = _preflight(recipe, source, model_dir, cancel)
        _check_cancel(cancel)
    except Exception as exc:
        if _cancelled(cancel) or isinstance(exc, _Cancelled):
            return pre_cancel
        raise RecipeError("Rezept oder Eingabe kann nicht verwendet werden: %s" % exc) from exc
    # stack-* is excluded by the raw-series finder, even when users place runs
    # under their input folder. Snapshots must not become new light exposures.
    directory = Path(tempfile.mkdtemp(prefix="stack-recipe-", dir=parent)).resolve()
    report = {"format": "ForgePixRecipeRun", "schema_version": 1, "id": uuid.uuid4().hex,
              "name": recipe["name"], "created": _now(), "updated": _now(), "status": "running",
              "run_dir": str(directory), "journal_path": str(directory / "run.json"),
              "recipe_path": str(directory / "recipe.json"), "recipe_sha256": recipe_hash,
              "input": dict(source_records[0], files=source_records), "input_snapshot": None,
              "experimental": True, "release_approved": False,
              "steps": [dict(step, index=index, status="pending") for index, step in enumerate(recipe["steps"], 1)],
              "completed_steps": 0, "result_path": None, "error": None}
    active = None
    try:
        _write_journal(report)
        _atomic_json(directory / "recipe.json", recipe)
        snapshot = _snapshot(source_records, directory / "input", cancel)
        current = Path(snapshot[0]["path"])
        report["input_snapshot"] = dict(snapshot[0], files=snapshot)
        _write_journal(report)
        current_files = snapshot
        for active in report["steps"]:
            _check_cancel(cancel)
            _verify_files(current_files, cancel)
            _model_matches(active, model_dir, cancel)
            active.update(status="running", started=_now(), source_path=str(current),
                          source_sha256=current_files[0]["sha256"])
            _write_journal(report)
            if log:
                log("Rezept: Schritt %d von %d — %s" % (active["index"], len(report["steps"]), active["task"]))
            worker_result = Path(ai_restore.run_file(current, active["model_id"], output_root=directory,
                model_dir=model_dir, strength=active["strength"], device=active["device"],
                allow_experimental=True, cancel=cancel, log=log or (lambda *_: None),
                progress=(lambda done, total: progress(active["index"], len(report["steps"]), done, total)) if progress else None)).resolve()
            if worker_result.parent.parent != directory:
                raise RecipeError("Das KI-Ergebnis liegt außerhalb dieses Rezeptlaufs.")
            _verify_files(current_files, cancel)
            proofs, core_report = _completed_group(worker_result, active, current_files[0], cancel)
            # FITS is the public and chained scientific result. Keep its proof
            # first so the next step's source hash matches the file it reads.
            result = worker_result.with_suffix(".fits")
            proofs.sort(key=lambda record: Path(record["path"]) != result)
            active.update(status="completed", finished=_now(), result_path=str(result),
                          ai_report_path=str(result.parent / "ai_report.json"), files=proofs,
                          execution=core_report.get("execution"), reconstruction_max_error=core_report.get("reconstruction_max_error"),
                          callback_status="running" if on_step else "not_requested")
            report["completed_steps"] += 1
            report["result_path"] = str(result)
            _write_journal(report)
            if on_step:
                try:
                    on_step(active["index"], str(result), deepcopy(active))
                except Exception:
                    active["callback_status"] = "failed"
                    raise
                active["callback_status"] = "completed"
                _write_journal(report)
            current, current_files = result, proofs
        report["status"] = "completed"
    except Exception as exc:
        cancelled = _cancelled(cancel) or isinstance(exc, _Cancelled)
        report["status"] = "cancelled" if cancelled else "failed"
        report["error"] = None if cancelled else str(exc)
        if active is not None and active["status"] == "running":
            active.update(status=report["status"], finished=_now(), error=report["error"])
    report["finished"] = _now()
    _write_journal(report)
    return deepcopy(report)
