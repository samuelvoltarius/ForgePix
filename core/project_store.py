"""Versioned project references and immutable result snapshots; no recomputation.

Only the project manifest and its owned result archive are written. Referenced
source images are never modified. A project is a history of saved files, not a
reversible process graph or a complete raw-frame/calibration archive.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid


class ProjectError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ref(path, base):
    path = Path(path).resolve()
    try:
        relative = os.path.relpath(path, base)
    except ValueError:  # Different Windows drives.
        relative = None
    return {"relative": relative, "absolute": str(path)}


def resolve(reference, base):
    """Prefer the moved project's relative file; fall back only if it is absent."""
    relative = reference.get("relative")
    if relative:
        candidate = (Path(base) / relative).resolve()
        if candidate.exists():
            return candidate
    return Path(reference["absolute"])


def fingerprint(path):
    path = Path(path)
    before = path.stat()
    if not path.is_file():
        raise ProjectError("Keine Bilddatei: %s" % path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ProjectError("Datei wurde während der Prüfung verändert: %s" % path)
    return {"bytes": after.st_size, "sha256": digest, "mtime_ns": after.st_mtime_ns}


def verify(record, base):
    path = resolve(record["path"], base)
    try:
        actual = fingerprint(path)
        status = "ok" if (actual["bytes"], actual["sha256"]) == (record["bytes"], record["sha256"]) else "changed"
    except FileNotFoundError:
        status = "missing"
    except (OSError, ProjectError):
        status = "unreadable"
    return {"path": str(path), "status": status}


def _record(path, base):
    return {"path": _ref(path, base), **fingerprint(path)}


def _valid_ref(value):
    if not isinstance(value, dict) or not isinstance(value.get("absolute"), str):
        raise ProjectError("Ungültiger Dateiverweis im Projekt.")
    if not Path(value["absolute"]).is_absolute() or "\x00" in value["absolute"]:
        raise ProjectError("Der absolute Dateiverweis ist ungültig.")
    relative = value.get("relative")
    if relative is not None and (not isinstance(relative, str) or not relative or "\x00" in relative
                                 or Path(relative).is_absolute() or Path(relative).drive):
        raise ProjectError("Der relative Dateiverweis ist ungültig.")


def _valid_record(value):
    if not isinstance(value, dict) or type(value.get("bytes")) is not int or value["bytes"] < 0:
        raise ProjectError("Ungültiger Dateinachweis im Projekt.")
    if not re.fullmatch(r"[a-f0-9]{64}", str(value.get("sha256", ""))):
        raise ProjectError("Die Datei-Prüfsumme im Projekt ist ungültig.")
    _valid_ref(value.get("path"))


def _validate(data):
    if (not isinstance(data, dict) or data.get("format") != "ForgePixProject"
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1):
        raise ProjectError("Unbekanntes Projektformat. Unterstützt wird ForgePix-Projektversion 1.")
    if not re.fullmatch(r"[a-f0-9]{32}", str(data.get("id", ""))):
        raise ProjectError("Ungültige Projekt-ID.")
    if not isinstance(data.get("name"), str) or not data["name"].strip() or len(data["name"]) > 200:
        raise ProjectError("Ungültiger Projektname.")
    _valid_ref(data.get("archive"))
    workspace = data.get("workspace")
    if not isinstance(workspace, dict) or type(workspace.get("module")) is not int or not 0 <= workspace["module"] <= 4:
        raise ProjectError("Ungültiger Projekt-Arbeitsbereich.")
    for key in ("input_directory", "work_directory"):
        if workspace.get(key) is not None:
            _valid_ref(workspace[key])
    if not isinstance(data.get("steps"), list) or len(data["steps"]) > 10000:
        raise ProjectError("Ungültiger oder zu großer Ergebnisverlauf.")
    seen = set()
    for step in data["steps"]:
        if (not isinstance(step, dict) or not re.fullmatch(r"[a-f0-9]{32}", str(step.get("id", "")))
                or step["id"] in seen or not isinstance(step.get("label"), str)
                or not isinstance(step.get("created"), str) or not isinstance(step.get("details"), dict)):
            raise ProjectError("Ungültiger Ergebnisschritt.")
        if step.get("parent_id") is not None and step["parent_id"] not in seen:
            raise ProjectError("Ein Ergebnisschritt verweist auf einen unbekannten Vorgänger.")
        seen.add(step["id"])
        for key in ("result", "origin"):
            _valid_record(step.get(key))
        if step.get("comparison") is not None:
            _valid_record(step["comparison"])
        if not isinstance(step.get("artifacts"), list):
            raise ProjectError("Ungültige Begleitdateien.")
        for artifact in step["artifacts"]:
            _valid_record(artifact)
    if data.get("selected_step") is not None and data["selected_step"] not in seen:
        raise ProjectError("Das gewählte Ergebnis fehlt im Projekt.")


def _atomic_json(path, data):
    """A failed write leaves the previous project file intact."""
    _validate(data)
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return hashlib.sha256(payload).hexdigest()
    finally:
        Path(temporary).unlink(missing_ok=True)


def _workspace(values, base):
    return {"module": int(values.get("module", 1)),
            **{key: _ref(values[key], base) if values.get(key) else None
               for key in ("input_directory", "work_directory")}}


class Project:
    def __init__(self, path, data, manifest_hash=None):
        self.path, self.data = Path(path).resolve(), data
        self._manifest_hash = manifest_hash or fingerprint(self.path)["sha256"]

    def _commit(self, data):
        try:
            current = fingerprint(self.path)["sha256"]
        except OSError as exc:
            raise ProjectError("Die Projektdatei fehlt oder ist nicht lesbar. Bitte erneut öffnen.") from exc
        if current != self._manifest_hash:
            raise ProjectError("Die Projektdatei wurde außerhalb dieses Fensters verändert. Bitte erneut öffnen, bevor du speicherst.")
        self._manifest_hash = _atomic_json(self.path, data)
        self.data = data

    @classmethod
    def create(cls, path, name, workspace):
        path = Path(path).resolve()
        if path.suffix.lower() != ".forgepix" or path.exists() or not path.parent.is_dir():
            raise ProjectError("Bitte eine neue .forgepix-Datei in einem vorhandenen Ordner wählen.")
        identifier = uuid.uuid4().hex
        data = {"format": "ForgePixProject", "schema_version": 1, "id": identifier,
                "name": name.strip(), "created": _now(), "updated": _now(),
                # The series finder already excludes stack-* directories. A
                # project saved among raw frames must never add its snapshots
                # back to a later integration as new input exposures.
                "archive": _ref(path.parent / ("stack-" + path.stem + ".files-" + identifier[:8]), path.parent),
                "workspace": _workspace(workspace, path.parent), "steps": [], "selected_step": None}
        digest = _atomic_json(path, data)
        return cls(path, data, digest)

    @classmethod
    def open(cls, path):
        path = Path(path).resolve()
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ProjectError("Die Projektdatei ist zu groß.")
        try:
            payload = path.read_bytes()
            data = json.loads(payload)
        except (ValueError, UnicodeError) as exc:
            raise ProjectError("Die Projektdatei ist beschädigt: %s" % exc) from exc
        _validate(data)
        return cls(path, data, hashlib.sha256(payload).hexdigest())

    def save(self, workspace=None):
        data = deepcopy(self.data)
        if workspace is not None:
            data["workspace"] = _workspace(workspace, self.path.parent)
        data["updated"] = _now()
        self._commit(data)

    def check(self):
        return {step["id"]: {key: verify(step[key], self.path.parent)
                              for key in ("result", "origin", "comparison") if step.get(key)}
                | {"artifacts": [verify(item, self.path.parent) for item in step["artifacts"]]}
                for step in self.data["steps"]}

    def step(self, identifier):
        return next(step for step in self.data["steps"] if step["id"] == identifier)

    def select(self, identifier):
        step = self.step(identifier)
        check = verify(step["result"], self.path.parent)
        if check["status"] != "ok":
            raise ProjectError("Dieser Ergebnisstand fehlt oder wurde verändert: %s" % check["path"])
        for item in step["artifacts"]:
            state = verify(item, self.path.parent)
            if state["status"] != "ok":
                raise ProjectError("Eine Begleitdatei fehlt oder wurde verändert: %s" % state["path"])
        data = deepcopy(self.data)
        data["selected_step"] = identifier
        data["updated"] = _now()
        if self.data.get("selected_step") != identifier:
            self._commit(data)
        comparison = None
        if step.get("comparison") and verify(step["comparison"], self.path.parent)["status"] == "ok":
            comparison = str(resolve(step["comparison"]["path"], self.path.parent))
        return check["path"], comparison

    def relocate(self, identifier, replacement):
        """Relink an identical saved result, never silently accept changed pixels."""
        replacement = Path(replacement).resolve()
        step = self.step(identifier)
        actual = fingerprint(replacement)
        if (actual["bytes"], actual["sha256"]) != (step["result"]["bytes"], step["result"]["sha256"]):
            raise ProjectError("Die gewählte Datei entspricht nicht dem gespeicherten Ergebnisstand.")
        data = deepcopy(self.data)
        new = next(item for item in data["steps"] if item["id"] == identifier)
        old_parent = resolve(step["result"]["path"], self.path.parent).parent
        new["result"]["path"] = _ref(replacement, self.path.parent)
        for item in new["artifacts"]:
            previous = resolve(item["path"], self.path.parent)
            candidate = replacement.parent / previous.name
            if previous.parent == old_parent and candidate.is_file():
                proof = dict(item, path=_ref(candidate, self.path.parent))
                if verify(proof, self.path.parent)["status"] == "ok":
                    item["path"] = proof["path"]
        data["updated"] = _now()
        self._commit(data)

    def export_step(self, identifier, destination):
        """Publish a verified scientific copy in a new folder, without conversion."""
        destination = Path(destination).resolve()
        if destination.exists() or not destination.parent.is_dir():
            raise ProjectError("Der Export benötigt einen neuen Ordner in einem vorhandenen Speicherort.")
        step = self.step(identifier)
        records = [step["result"], *step["artifacts"]]
        sources, names = [], set()
        for record in records:
            checked = verify(record, self.path.parent)
            if checked["status"] != "ok":
                raise ProjectError("Die gesicherten Ergebnisdateien fehlen oder wurden verändert: %s" % checked["path"])
            source = Path(checked["path"])
            if source.name.casefold() in names or source.name.casefold() == "forgepix-export.json":
                raise ProjectError("Gleichnamige Begleitdateien können nicht gemeinsam exportiert werden.")
            names.add(source.name.casefold())
            sources.append((source, record))
        staging = Path(tempfile.mkdtemp(prefix=".forgepix-export-", dir=destination.parent))
        created = []
        try:
            for source, record in sources:
                target = staging / source.name
                created.append(target)
                shutil.copyfile(source, target)
                actual = fingerprint(target)
                if ((actual["bytes"], actual["sha256"]) != (record["bytes"], record["sha256"])
                        or verify(record, self.path.parent)["status"] != "ok"):
                    raise ProjectError("Eine Ergebnisdatei wurde während des Exports verändert: %s" % source)
            report = {"format": "ForgePixScientificExport", "schema_version": 1, "created": _now(),
                      "project": self.data["name"], "step": step["label"],
                      "files_copied_unchanged": True,
                      "files": [{"name": source.name, "bytes": record["bytes"], "sha256": record["sha256"]}
                                for source, record in sources]}
            report_path = staging / "forgepix-export.json"
            created.append(report_path)
            with report_path.open("w", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            if destination.exists():
                raise ProjectError("Der Zielordner wurde inzwischen angelegt. Bitte erneut exportieren.")
            staging.rename(destination)
            return str(destination)
        except Exception:
            # Only exact files created by this operation are removed; source
            # images and a pre-existing destination are never touched.
            for path in created:
                path.unlink(missing_ok=True)
            staging.rmdir()
            raise

    def add_result(self, result, comparison=None, label="Ergebnis übernommen", workspace=None):
        result = Path(result).resolve()
        origin = _record(result, self.path.parent)
        current = self.data.get("selected_step")
        if current:
            previous = self.step(current)
            if (previous["origin"]["sha256"] == origin["sha256"]
                    and verify(previous["result"], self.path.parent)["status"] == "ok"
                    and all(verify(item, self.path.parent)["status"] == "ok" for item in previous["artifacts"])):
                return previous["id"]
        sources, details = _companions(result)
        archive = resolve(self.data["archive"], self.path.parent)
        # Loaded references may point elsewhere; the archive is only ever
        # appended to with a fresh random step folder, never recursively removed.
        archive.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="step-", dir=archive))
        created = []
        try:
            records = {}
            for source in sources:
                destination = folder / source.name
                before = fingerprint(source)
                created.append(destination)
                shutil.copyfile(source, destination)
                saved = fingerprint(destination)
                after = fingerprint(source)
                if (before["bytes"], before["sha256"]) != (saved["bytes"], saved["sha256"]) or before["sha256"] != after["sha256"]:
                    raise ProjectError("Datei wurde während der Projektsicherung verändert: %s" % source)
                records[source] = {"path": _ref(destination, self.path.parent), **saved}
            # Recheck the copied AI group against its copied report, so a
            # concurrent change cannot join pixels and provenance from two runs.
            if details.get("model_id"):
                _companions(folder / result.name)
            compare_record = None
            if comparison and Path(comparison).is_file():
                compare_record = _record(comparison, self.path.parent)
                # Reuse an already archived predecessor as the comparison when
                # it contains exactly the same pixels/file as the original.
                for previous in reversed(self.data["steps"]):
                    if previous["result"]["sha256"] == compare_record["sha256"]:
                        compare_record = deepcopy(previous["result"])
                        break
            identifier = uuid.uuid4().hex
            step = {"id": identifier, "created": _now(), "label": str(label), "parent_id": current,
                    "result": records[result], "origin": origin, "comparison": compare_record,
                    "artifacts": [record for path, record in records.items() if path != result], "details": details}
            data = deepcopy(self.data)
            data["steps"].append(step)
            data["selected_step"] = identifier
            data["updated"] = _now()
            if workspace is not None:
                data["workspace"] = _workspace(workspace, self.path.parent)
            self._commit(data)
            return identifier
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            folder.rmdir()
            raise


def _companions(result):
    """Capture recorded AI groups and explicit coverage, not unrelated siblings."""
    files, details = [result], {}
    report_path = result.parent / "ai_report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if isinstance(report, dict) and result.name in report.get("outputs", []):
            records = report.get("output_integrity")
            if not isinstance(records, list) or not records:
                raise ProjectError("Das KI-Ergebnis benötigt gültige Datei-Prüfsummen.")
            names = set()
            for item in records:
                name = item.get("name") if isinstance(item, dict) else None
                if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name or name in names:
                    raise ProjectError("Ungültige Begleitdatei im KI-Bericht.")
                names.add(name)
                source = result.parent / name
                actual = fingerprint(source)
                if (actual["bytes"], actual["sha256"]) != (item.get("bytes"), item.get("sha256")):
                    raise ProjectError("Die KI-Ergebnisdateien wurden verändert: %s" % source)
                files.append(source)
            if set(report["outputs"]) != names:
                raise ProjectError("Der KI-Bericht enthält widersprüchliche Dateiverweise.")
            files.append(report_path)
            details = {key: report[key] for key in ("task", "model_id", "strength", "status") if key in report}
    coverage = {}
    if result.suffix.lower() in {".fit", ".fits", ".fts"}:
        from astropy.io import fits
        header = fits.getheader(result)
        coverage = {key: header.get(key) for key in ("FPCOV", "FPDRZCOV", "FPDRZWGT")}
    elif result.suffix.lower() in {".tif", ".tiff"}:
        import tifffile
        with tifffile.TiffFile(result) as image:
            try:
                metadata = json.loads(image.pages[0].description or "{}")
            except ValueError:
                metadata = {}
        if isinstance(metadata, dict):
            coverage = {key: metadata.get(key) for key in ("FPCOV", "FPDRZCOV", "FPDRZWGT")}
            if isinstance(metadata.get("fits_header"), str):
                from astropy.io import fits
                header = fits.Header.fromstring(metadata["fits_header"], sep="\n")
                for key in coverage:
                    coverage[key] = coverage[key] or header.get(key)
    for name in coverage.values():
        if not name:
            continue
        if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
            raise ProjectError("Ungültiger Verweis auf die Bildabdeckung.")
        files.append(result.parent / name)
    for name in ("processing_report.json", "drizzle_report.json", "channels.json", "layers.json", "mix.json",
                 "astrometry_report.json"):
        path = result.parent / name
        if path.is_file():
            files.append(path)
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(report, dict):
                    values = {key: report[key] for key in ("method", "operation", "input_frames", "registered_frames",
                              "integration_seconds", "calibration", "filter", "channels", "palette",
                              "spectral_estimate", "nebula", "stars") if key in report}
                    if values:
                        details[name] = values
            except (ValueError, UnicodeError):
                pass  # The exact original report is still archived as evidence.
    return list(dict.fromkeys(files)), details
