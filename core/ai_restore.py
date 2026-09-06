"""Local, explicitly experimental monochrome ONNX restoration of linear images.

Contract v1: a single 1x1x256x256 float32 input/output, shared affine percentile
normalization, and independent inference for each image channel. Model outputs
are complete normalized target images, not residuals. No clipping or stretch is
applied to scientific exports; a signed star residual preserves reconstruction.
Background correction estimates a smooth whole-field residual at 256x256 and
subtracts it from the original grid. The other tasks use overlapping image tiles.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

import numpy as np
import tifffile
import cv2

from constants import ForgePixFehler, log_print, require_astropy


TASKS = ("denoise", "background", "deblur", "starless")
TILE_SIZE, HALO, STRIDE = 256, 32, 192
NORMALIZATION = "affine_percentile_v1"


def default_model_dir():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "assets" / "models"


def _cancelled(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()):
        raise ForgePixFehler("KI-Verarbeitung abgebrochen.")


def _model_bytes(path, cancel=None):
    chunks, digest = [], hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            _cancelled(cancel)
            digest.update(block)
            chunks.append(block)
    return b"".join(chunks), digest.hexdigest()


def _file_integrity(path, cancel=None):
    """Hash an exported file without keeping another image-sized byte buffer."""
    _cancelled(cancel)
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            _cancelled(cancel)
            size += len(block)
            digest.update(block)
    _cancelled(cancel)
    return {"name": path.name, "bytes": size, "sha256": digest.hexdigest()}


def _manifest(path, cancel=None):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError("unbekannte Manifest-Version")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", str(data.get("id", ""))):
            raise ValueError("ungültige Modell-ID")
        if data.get("task") not in TASKS:
            raise ValueError("unbekannte Modellaufgabe")
        if data.get("output") != "complete_target":
            raise ValueError("unbekannte Ausgabe-Semantik; erwartet wird complete_target")
        for key, expected in (("channels", 1), ("tile_size", TILE_SIZE), ("halo", HALO)):
            if type(data.get(key)) is not int or data[key] != expected:
                raise ValueError("unpassender Modellvertrag: " + key)
        normalization = data.get("normalization")
        if isinstance(normalization, dict):
            normalization = normalization.get("method")
        if normalization != NORMALIZATION:
            raise ValueError("unbekannte Normalisierung")
        name = data.get("model_file")
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.onnx", name)
                or name.startswith(".")):
            raise ValueError("die ONNX-Datei muss direkt neben dem Manifest liegen")
        folder = Path(path).resolve().parent
        model_path = (folder / name).resolve()
        if model_path.parent != folder:
            raise ValueError("Modellpfad verlässt den Modellordner")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", str(data.get("sha256", ""))):
            raise ValueError("SHA256-Prüfsumme fehlt oder ist ungültig")
        content, digest = _model_bytes(model_path, cancel)
        if digest != data["sha256"].lower():
            raise ValueError("SHA256-Prüfsumme stimmt nicht; Modell beschädigt oder verändert")
        data = dict(data, manifest_path=str(Path(path).resolve()))
        return data, content
    except ForgePixFehler:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise ForgePixFehler("KI-Modell kann nicht geladen werden: %s" % exc) from exc


def list_models(model_dir=None):
    """Discover local model manifests, including unusable entries for the UI."""
    root = Path(model_dir) if model_dir is not None else default_model_dir()
    if not root.is_dir():
        return []
    result = []
    for path in sorted(set(root.glob("*.json")) | set(root.glob("*/manifest.json"))):
        # A model repository may contain a collection-level report as well.
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict) or (not raw.get("id") and path.name != "manifest.json"):
            continue
        entry = {"id": raw.get("id", path.parent.name), "task": raw.get("task"),
                 "status": raw.get("status", "experimental"),
                 "release_approved": raw.get("release_approved") is True,
                 "manifest_path": str(path.resolve()), "available": False, "reason": ""}
        try:
            _manifest(path)
            entry["available"] = True
        except ForgePixFehler as exc:
            entry["reason"] = str(exc)
        result.append(entry)
    return result


def _resolve(model_id, model_dir, cancel=None):
    root = Path(model_dir) if model_dir is not None else default_model_dir()
    matches = []
    for path in sorted(set(root.glob("*.json")) | set(root.glob("*/manifest.json"))):
        _cancelled(cancel)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict) and raw.get("id") == model_id:
            matches.append(path)
    if len(matches) != 1:
        raise ForgePixFehler("KI-Modell nicht eindeutig vorhanden: %s. Bitte die Modelldateien prüfen." % model_id)
    return _manifest(matches[0], cancel)


_PROVIDERS = {"cpu": "CPUExecutionProvider", "cuda": "CUDAExecutionProvider",
              "directml": "DmlExecutionProvider", "coreml": "CoreMLExecutionProvider"}


class _InferenceError(ForgePixFehler):
    """A provider failure, distinct from cancellation or invalid source pixels."""


def _device(value):
    if not isinstance(value, str) or value.lower() not in ("auto", "cpu", "gpu", "cuda", "directml", "coreml"):
        raise ForgePixFehler("Unbekannte KI-Recheneinheit. Erlaubt: auto, cpu, gpu, cuda, directml, coreml.")
    return value.lower()


def _execution_record(device):
    return {"requested_device": _device(device), "provider": None, "registered_providers": [],
            "attempts": [], "fallback_used": False, "fallback_reasons": [],
            "whole_image_restarts": 0, "gpu_execution_verified": False,
            "placement_evidence": "Provider registration does not prove GPU node placement.",
            "applied": False}


def _create_session(content, *, device="auto", execution=None, log=log_print):
    device = _device(device)
    if execution is None:
        execution = _execution_record(device)
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise ForgePixFehler("Die lokale KI-Laufzeit ONNX Runtime fehlt. Bitte ForgePix mit KI-Unterstützung installieren.") from exc
    available = list(ort.get_available_providers())
    execution["available_providers"] = available
    execution["runtime_version"] = ort.__version__
    if device in ("auto", "gpu"):
        candidates = ["cuda"]
        if sys.platform == "win32":
            candidates.append("directml")
        elif sys.platform == "darwin":
            candidates.append("coreml")
        candidates = [name for name in candidates if _PROVIDERS[name] in available]
    else:
        candidates = [device] if _PROVIDERS[device] in available else []
    if not candidates and device != "cpu":
        reason = "Keine passende GPU-Laufzeit verfügbar (Anforderung: %s)." % device
        execution["fallback_used"] = True
        execution["fallback_reasons"].append(reason)
        log(reason + " Verarbeitung auf CPU.")
    if "cpu" not in candidates:
        candidates.append("cpu")
    for candidate in candidates:
        provider = _PROVIDERS[candidate]
        attempt = {"provider": provider, "status": "initializing"}
        execution["attempts"].append(attempt)
        session = None
        try:
            options = ort.SessionOptions()
            options.intra_op_num_threads = min(4, os.cpu_count() or 1)
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            provider_options = {}
            if candidate == "cuda":
                # Scientific comparisons use float32, not Ampere's default TF32.
                provider_options = {"device_id": "0", "use_tf32": "0",
                                    "cudnn_conv_algo_search": "HEURISTIC",
                                    "cudnn_conv_use_max_workspace": "0"}
            elif candidate == "directml":
                # DirectML forbids parallel execution and memory pattern reuse.
                options.enable_mem_pattern = False
                provider_options = {"device_id": "0"}
            elif candidate == "coreml":
                provider_options = {"ModelFormat": "MLProgram", "MLComputeUnits": "CPUAndGPU",
                                    "RequireStaticInputShapes": "1",
                                    "AllowLowPrecisionAccumulationOnGPU": "0"}
            providers = [(provider, provider_options)]
            if candidate != "cpu":
                providers.append(_PROVIDERS["cpu"])
            # Execute precisely the hash-checked bytes; no external tensor files.
            session = ort.InferenceSession(content, sess_options=options, providers=providers)
            # ORT's own run() fallback would mix GPU tiles with later CPU tiles.
            # ForgePix handles the failure by recomputing the complete image.
            session.disable_fallback()
            registered = list(session.get_providers())
            if provider not in registered:
                raise RuntimeError("Der angeforderte Backend-Treiber wurde nicht geladen: " + provider)
            inputs, outputs = session.get_inputs(), session.get_outputs()
            if (len(inputs) != 1 or len(outputs) != 1
                    or inputs[0].type != "tensor(float)" or outputs[0].type != "tensor(float)"
                    or list(inputs[0].shape) != [1, 1, TILE_SIZE, TILE_SIZE]
                    or list(outputs[0].shape) != [1, 1, TILE_SIZE, TILE_SIZE]):
                raise ValueError("erwartet wird genau ein Float32-Ein-/Ausgang mit Form 1×1×256×256")
            attempt["status"] = "ready"
            execution.update(provider=provider, registered_providers=registered,
                             provider_options=provider_options)
            log("KI-Rechenbackend: %s (Anforderung: %s)." % (provider, execution["requested_device"]))
            return session, inputs[0].name, outputs[0].name
        except Exception as exc:
            session = None
            attempt.update(status="initialization_failed", error=str(exc))
            if candidate == "cpu":
                raise ForgePixFehler("Das lokale ONNX-Modell kann nicht ausgeführt werden: %s" % exc) from exc
            reason = "%s konnte nicht gestartet werden: %s" % (provider, exc)
            execution["fallback_used"] = True
            execution["fallback_reasons"].append(reason)
            log(reason + ". Ein anderes Rechenbackend wird versucht.")


def _image(image):
    a = np.asarray(image)
    if (a.ndim not in (2, 3) or (a.ndim == 3 and a.shape[-1] != 3)
            or not a.size or not np.issubdtype(a.dtype, np.number) or np.iscomplexobj(a)):
        raise ForgePixFehler("Die KI benötigt ein gültiges Mono- oder RGB-Bild.")
    with np.errstate(over="ignore", invalid="ignore"):
        a = a.astype(np.float32, copy=True)
    if not np.isfinite(a).all():
        raise ForgePixFehler("Das Bild enthält NaN, Inf oder Werte außerhalb des Float32-Bereichs.")
    return a


def _predict(session, input_name, output_name, tile, cancel):
    _cancelled(cancel)
    try:
        prediction = np.asarray(session.run([output_name], {input_name: tile})[0])
    except Exception as exc:
        raise _InferenceError("KI-Inferenz fehlgeschlagen: %s" % exc) from exc
    _cancelled(cancel)
    if prediction.shape != (1, 1, TILE_SIZE, TILE_SIZE) or not np.isfinite(prediction).all():
        raise _InferenceError("Das KI-Modell lieferte ungültige Pixel oder eine unpassende Bildgröße.")
    return prediction


def _global_background(image, session, input_name, output_name, offset, scale, strength, progress, cancel):
    """Estimate only a smooth full-field residual; preserve the original detail grid."""
    h, w = image.shape[:2]
    channels = 1 if image.ndim == 2 else image.shape[-1]
    result = np.empty_like(image)
    if progress:
        progress(0, channels)
    for channel in range(channels):
        _cancelled(cancel)
        plane = image if image.ndim == 2 else image[..., channel]
        with np.errstate(over="ignore", invalid="ignore"):
            normalized = ((plane.astype(np.float64) - offset) / scale).astype(np.float32)
        if not np.isfinite(normalized).all():
            raise ForgePixFehler("Die Bilddynamik überschreitet den Bereich des KI-Modells.")
        small = cv2.resize(normalized, (TILE_SIZE, TILE_SIZE), interpolation=cv2.INTER_AREA)
        prediction = _predict(session, input_name, output_name,
                              np.ascontiguousarray(small[None, None]), cancel)[0, 0]
        # The affine offset cancels in input minus complete target. Do not add it
        # again, recenter the model estimate, or resize the restored scene itself.
        residual = small.astype(np.float64) - prediction
        smooth = cv2.GaussianBlur(residual, (0, 0), sigmaX=16, sigmaY=16,
                                  borderType=cv2.BORDER_REFLECT_101)
        full_residual = cv2.resize(smooth, (w, h), interpolation=cv2.INTER_CUBIC)
        _cancelled(cancel)
        with np.errstate(over="ignore", invalid="ignore"):
            corrected = (plane.astype(np.float64) - strength * scale * full_residual).astype(np.float32)
        if not np.isfinite(corrected).all():
            raise ForgePixFehler("Die KI-Verarbeitung erzeugte Werte außerhalb des Float32-Bereichs.")
        if image.ndim == 2:
            result[...] = corrected
        else:
            result[..., channel] = corrected
        if progress:
            progress(channel + 1, channels)
    return result


def _infer(image, content, strength, progress, cancel, task="denoise", *, device="auto", log=log_print):
    # Shared statistics across all channels, never per tile or per channel.
    low, high = np.percentile(image, [.1, 99.9])
    offset, scale = float(low), max(float(high) - float(low), 1e-6)
    info = {"method": NORMALIZATION, "offset": offset, "scale": scale,
            "percentiles": [.1, 99.9], "clipped": False, "execution": _execution_record(device)}
    if task == "background":
        info["inference"] = {"strategy": "global_background_residual", "applied": strength != 0,
                             "working_shape": [TILE_SIZE, TILE_SIZE], "residual_smoothing_sigma": 16,
                             "residual_smoothing_boundary": "reflect_101",
                             "input_interpolation": "area", "residual_interpolation": "cubic"}
    else:
        info["inference"] = {"strategy": "overlapping_tiles", "applied": strength != 0,
                             "tile_size": TILE_SIZE, "halo": HALO, "stride": STRIDE,
                             "blend": "cosine over 64-pixel overlap", "padding": "reflect"}
    if strength == 0:
        if progress:
            progress(1, 1)
        return image.copy(), info
    execution = info["execution"]
    session, input_name, output_name = _create_session(content, device=device, execution=execution, log=log)
    retry_cpu = False
    try:
        result = _infer_session(image, session, input_name, output_name, offset, scale,
                                strength, progress, cancel, task)
    except _InferenceError as exc:
        _cancelled(cancel)
        if execution["provider"] not in {_PROVIDERS[name] for name in ("cuda", "directml", "coreml")}:
            raise
        reason = "%s: %s" % (execution["provider"], exc)
        execution["attempts"][-1].update(status="execution_failed", error=str(exc))
        execution["fallback_used"] = True
        execution["fallback_reasons"].append(reason)
        execution["whole_image_restarts"] += 1
        log(reason + ". Das vollständige Bild wird auf CPU neu berechnet.")
        retry_cpu = True
    if retry_cpu:
        # Outside the except block, its exception/traceback no longer retains
        # the failed session and partially accumulated image-sized arrays.
        session = None
        _cancelled(cancel)
        session, input_name, output_name = _create_session(content, device="cpu", execution=execution, log=log)
        result = _infer_session(image, session, input_name, output_name, offset, scale,
                                strength, progress, cancel, task)
    execution["applied"] = True
    return result, info


def _infer_session(image, session, input_name, output_name, offset, scale, strength, progress, cancel, task):
    """One complete image attempt; no accumulated values survive a retry."""
    if task == "background":
        return _global_background(image, session, input_name, output_name, offset, scale,
                                  strength, progress, cancel)
    h, w = image.shape[:2]
    channels = 1 if image.ndim == 2 else image.shape[-1]
    ny, nx = max(1, math.ceil(h / STRIDE)), max(1, math.ceil(w / STRIDE))
    ph, pw = TILE_SIZE + (ny - 1) * STRIDE, TILE_SIZE + (nx - 1) * STRIDE
    overlap = TILE_SIZE - STRIDE
    ramp = .5 - .5 * np.cos(np.pi * (np.arange(overlap, dtype=np.float32) + .5) / overlap)
    window = np.ones(TILE_SIZE, np.float32)
    window[:overlap], window[-overlap:] = ramp, ramp[::-1]
    weights = window[:, None] * window[None, :]
    result = np.empty_like(image)
    total, done = ny * nx * channels, 0
    if progress:
        progress(0, total)
    for channel in range(channels):
        _cancelled(cancel)
        plane = image if image.ndim == 2 else image[..., channel]
        # Calculate in float64 to avoid overflow of finite physical pixel values,
        # then use the explicitly float32 network contract without clipping.
        normalized = ((plane.astype(np.float64) - offset) / scale).astype(np.float32)
        if not np.isfinite(normalized).all():
            raise ForgePixFehler("Die Bilddynamik überschreitet den Bereich des KI-Modells.")
        padded = np.pad(normalized, ((HALO, ph - h - HALO), (HALO, pw - w - HALO)), mode="reflect")
        accumulator, denominator = np.zeros((ph, pw), np.float32), np.zeros((ph, pw), np.float32)
        for y in range(0, ph - TILE_SIZE + 1, STRIDE):
            for x in range(0, pw - TILE_SIZE + 1, STRIDE):
                _cancelled(cancel)
                tile = np.ascontiguousarray(padded[y:y + TILE_SIZE, x:x + TILE_SIZE][None, None])
                prediction = _predict(session, input_name, output_name, tile, cancel)
                accumulator[y:y + TILE_SIZE, x:x + TILE_SIZE] += prediction[0, 0] * weights
                denominator[y:y + TILE_SIZE, x:x + TILE_SIZE] += weights
                done += 1
                if progress:
                    progress(done, total)
        region = np.s_[HALO:HALO + h, HALO:HALO + w]
        predicted = accumulator[region].astype(np.float64) / denominator[region]
        restored = offset + scale * predicted
        mixed = plane.astype(np.float64) + strength * (restored - plane)
        with np.errstate(over="ignore", invalid="ignore"):
            mixed = mixed.astype(np.float32)
        if not np.isfinite(mixed).all():
            raise ForgePixFehler("Die KI-Verarbeitung erzeugte Werte außerhalb des Float32-Bereichs.")
        if image.ndim == 2:
            result[...] = mixed
        else:
            result[..., channel] = mixed
    return result


def restore(image, model_id, *, model_dir=None, strength=.5, allow_experimental=False,
            log=log_print, progress=None, cancel=None, device="auto"):
    """Restore an array without changing its channel order; return a float32 array."""
    source, manifest, content, strength = _prepare(image, model_id, model_dir, strength, allow_experimental, cancel)
    log("Lokale experimentelle KI: %s; Stärke %.0f %%" % (manifest["task"], strength * 100))
    result, _ = _infer(source, content, strength, progress, cancel, task=manifest["task"], device=device, log=log)
    _cancelled(cancel)
    return result


def _prepare(image, model_id, model_dir, strength, allow_experimental, cancel):
    _cancelled(cancel)
    source = _image(image)
    try:
        strength = float(strength)
    except (TypeError, ValueError) as exc:
        raise ForgePixFehler("Die KI-Stärke muss zwischen 0 und 1 liegen.") from exc
    if not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ForgePixFehler("Die KI-Stärke muss zwischen 0 und 1 liegen.")
    manifest, content = _resolve(model_id, model_dir, cancel)
    if (manifest.get("status") == "experimental" or manifest.get("release_approved") is not True) and not allow_experimental:
        raise ForgePixFehler("Dieses KI-Modell ist experimentell. Die experimentelle Verarbeitung muss ausdrücklich aktiviert werden.")
    return source, manifest, content, strength


def _read_source(path):
    source = Path(path)
    metadata, header = {}, None
    if source.suffix.lower() in {".fits", ".fit", ".fts"}:
        fits = require_astropy("Lineares KI-Eingangsbild lesen")
        with fits.open(source, memmap=False) as hdus:
            data, header = hdus[0].data, hdus[0].header.copy()
            if data is None:
                raise ForgePixFehler("Das FITS benötigt ein Bild im primären HDU.")
            if data.ndim == 2 and header.get("BAYERPAT"):
                raise ForgePixFehler("Bayer-Rohdaten zuerst kalibrieren und debayern beziehungsweise stacken. Die KI benötigt ein lineares Mono- oder Farbergebnis.")
            if header.get("FPLINEAR") is False:
                raise ForgePixFehler("Dieses FITS wurde bereits gestreckt. Bitte das lineare Ergebnis wählen.")
            if data.ndim == 3:
                if data.shape[0] != 3:
                    raise ForgePixFehler("Das FITS-Farbbild benötigt die Achsenfolge (3, Höhe, Breite).")
                data = np.moveaxis(data, 0, -1)
            image = _image(data)
    elif source.suffix.lower() in {".tif", ".tiff"}:
        with tifffile.TiffFile(source) as file:
            data = file.asarray()
            try:
                metadata = json.loads(file.pages[0].description or "{}")
            except (ValueError, TypeError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            if isinstance(metadata.get("fits_header"), str):
                fits = require_astropy("Wissenschaftliche TIFF-Metadaten lesen")
                try:
                    header = fits.Header.fromstring(metadata["fits_header"], sep="\n")
                except (TypeError, ValueError) as exc:
                    raise ForgePixFehler("Die gespeicherten FITS-Metadaten des TIFF sind ungültig.") from exc
            if isinstance(metadata, dict) and metadata.get("linear") is False:
                raise ForgePixFehler("Dieses TIFF wurde bereits gestreckt. Bitte das lineare Ergebnis wählen.")
            if header is not None and header.get("FPLINEAR") is False:
                raise ForgePixFehler("Die TIFF-Metadaten kennzeichnen ein bereits gestrecktes Bild.")
            if data.ndim == 2 and (metadata.get("BAYERPAT") or (header is not None and header.get("BAYERPAT"))):
                raise ForgePixFehler("Bayer-Rohdaten zuerst kalibrieren und debayern beziehungsweise stacken.")
            if data.dtype == np.uint8:
                raise ForgePixFehler("8-Bit-TIFFs sind Anzeigeformate. Bitte das lineare 16-/32-Bit-Ergebnis wählen.")
            image = _image(data)
    else:
        raise ForgePixFehler("Bitte ein lineares FITS- oder TIFF-Bild verwenden, keine JPEG-Vorschau.")
    divisor = float(np.iinfo(data.dtype).max) if np.issubdtype(data.dtype, np.integer) else 1.0
    original_unit = header.get("BUNIT") if header is not None else metadata.get("BUNIT")
    if divisor != 1.0:
        image /= divisor
        fits = require_astropy("Normierung der Bilddaten dokumentieren")
        header = header.copy() if header is not None else fits.Header()
        if original_unit is not None:
            header["FPOUNIT"] = original_unit
            metadata["FPOUNIT"] = original_unit
        header["BUNIT"], header["FPISCALE"] = "relative", divisor
        metadata["BUNIT"], metadata["FPISCALE"] = "relative", divisor
        header.add_history("Integer input divided by %.0f to match ForgePix linear stacking scale." % divisor)
    scaling = {"divisor": divisor, "original_unit": original_unit,
               "output_unit": "relative" if divisor != 1.0 else original_unit}
    return image, header, metadata, scaling


def read_source(path):
    """Read the inference input scale for comparisons; color file order is RGB."""
    return _read_source(path)[0]


def _coverage(source, header, metadata, shape, cancel):
    name = metadata.get("FPCOV") or (header.get("FPCOV") if header is not None else None)
    if not name:
        return None, None
    if not isinstance(name, str) or "/" in name or "\\" in name or name in {".", ".."}:
        raise ForgePixFehler("Ungültiger Verweis auf die Bildabdeckung.")
    path = (source.parent / name).resolve()
    if path.parent != source.parent or not path.is_file():
        raise ForgePixFehler("Die benötigte Bildabdeckung fehlt oder liegt außerhalb des Bildordners.")
    _cancelled(cancel)
    mask = tifffile.imread(path)
    if mask.shape != shape or not np.isin(mask, [0, 1]).all():
        raise ForgePixFehler("Die Bildabdeckung passt nicht zum KI-Eingangsbild.")
    if not np.all(mask):
        raise ForgePixFehler("Das Bild enthält unbedeckte Bereiche. Bitte zuerst auf einen vollständig abgedeckten Bereich zuschneiden; die KI unterstützt noch keine Maskenlücken.")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return mask.astype(bool), {"source": str(path), "sha256": digest,
                               "fraction": float(mask.mean()), "output": "coverage.tif"}


def _output_header(fits, source_header, source_metadata, manifest, role, has_coverage):
    header = source_header.copy() if source_header is not None else fits.Header()
    # The array already contains physical values. Old integer scaling, checksums
    # and dimensions must not be applied again when writing a float32 PrimaryHDU.
    structural = {"SIMPLE", "BITPIX", "NAXIS", "BSCALE", "BZERO", "BLANK", "CHECKSUM", "DATASUM",
                  "PCOUNT", "GCOUNT", "XTENSION", "EXTEND", "BAYERPAT", "XBAYROFF", "YBAYROFF"}
    for key in list(header.keys()):
        if key in structural or re.fullmatch(r"NAXIS\d+", key):
            header.remove(key, remove_all=True, ignore_missing=True)
    for key in ("FPLINE", "FPCOORD", "FILTER", "OBJECT", "INSTRUME", "TELESCOP", "EXPTIME", "BUNIT"):
        if key not in header and key in source_metadata and source_metadata[key] is not None:
            header[key] = source_metadata[key]
    header.update({"CREATOR": "ForgePix", "FPLINEAR": True, "FPDOMAIN": "LINEAR_AI_ESTIMATE",
                   "FPQUAL": "EXPERIMENTAL", "FPAITASK": manifest["task"], "FPAIMOD": manifest["id"],
                   "FPAIROLE": role, "FPCHTYPE": "RESIDUAL" if role == "stars_residual" else "ESTIMATE"})
    if has_coverage:
        header["FPCOV"] = "coverage.tif"
    else:
        header.remove("FPCOV", remove_all=True, ignore_missing=True)
    header.add_history("No display stretch. Nonlinear AI estimate; photometry has not been validated.")
    if role == "stars_residual":
        header.add_history("Signed source minus restored image; this is not a pure stellar flux map.")
    return header


def run_file(source, model_id, output_root=None, *, model_dir=None, strength=.5,
             allow_experimental=False, log=log_print, progress=None, cancel=None, device="auto"):
    """Write a unique result directory; return its RGB/mono result_32bit.tif path."""
    source = Path(source).resolve()
    _cancelled(cancel)
    raw, source_header, source_metadata, source_scaling = _read_source(source)
    image, manifest, content, strength = _prepare(raw, model_id, model_dir,
                                                strength, allow_experimental, cancel)
    coverage, coverage_record = _coverage(source, source_header, source_metadata, image.shape[:2], cancel)
    with source.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    log("Lokale experimentelle KI: %s; Original bleibt erhalten." % manifest["task"])
    result, normalization = _infer(image, content, strength, progress, cancel, task=manifest["task"], device=device, log=log)
    inference = normalization.pop("inference")
    execution = normalization.pop("execution")
    _cancelled(cancel)
    fits = require_astropy("KI-Ergebnis speichern")
    parent = Path(output_root).resolve() if output_root else source.parent
    parent.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="ai-%s-" % manifest["task"], dir=parent))
    layers = {"result_32bit": result}
    reconstruction_error = None
    if manifest["task"] == "starless":
        residual = image - result
        if not np.isfinite(residual).all():
            destination.rmdir()
            raise ForgePixFehler("Die signierte Sternebenen-Differenz überschreitet Float32.")
        layers["stars_residual_32bit"] = residual
        reconstruction_error = float(np.max(np.abs(result.astype(np.float64) + residual - image)))
    created = []
    try:
        if coverage is not None:
            _cancelled(cancel)
            coverage_path = destination / "coverage.tif"
            created.append(coverage_path)
            tifffile.imwrite(coverage_path, coverage.astype(np.uint8), metadata=None)
        for name, layer in layers.items():
            _cancelled(cancel)
            role = "stars_residual" if name == "stars_residual_32bit" else "result"
            header = _output_header(fits, source_header, source_metadata, manifest, role, coverage is not None)
            metadata = dict(source_metadata, forgepix=True, linear=True, domain="LINEAR_AI_ESTIMATE",
                            status="experimental", photometry_validated=False, role=role,
                            model_id=manifest["id"], task=manifest["task"],
                            fits_header=header.tostring(sep="\n", endcard=False, padding=False))
            for key in ("FPLINE", "FPCOORD", "FILTER", "OBJECT", "INSTRUME", "TELESCOP", "EXPTIME", "BUNIT", "FPOUNIT", "FPISCALE", "FPCHTYPE"):
                if key in header:
                    metadata[key] = header[key]
            for key in ("BAYERPAT", "XBAYROFF", "YBAYROFF", "FPCOV"):
                metadata.pop(key, None)
            if coverage is not None:
                metadata["FPCOV"] = "coverage.tif"
            tif_path, fits_path = destination / (name + ".tif"), destination / (name + ".fits")
            created.append(tif_path)
            tifffile.imwrite(tif_path, layer, photometric="rgb" if layer.ndim == 3 else "minisblack",
                             metadata=None, description=json.dumps(metadata))
            _cancelled(cancel)
            created.append(fits_path)
            fits.writeto(fits_path, np.moveaxis(layer, -1, 0) if layer.ndim == 3 else layer, header)
        _cancelled(cancel)
        output_integrity = [_file_integrity(path, cancel) for path in created]
        report = {"schema_version": 1, "source": {"path": str(source), "sha256": source_hash},
                  "model_id": manifest["id"], "model_sha256": manifest["sha256"], "task": manifest["task"],
                  "strength": strength, "normalization": normalization, "shape": list(image.shape),
                  "range": [float(result.min()), float(result.max())], "channel_processing": "independent mono",
                  "strategy": inference["strategy"], "inference": inference, "execution": execution,
                  "status": "experimental", "release_approved": False, "photometry_validated": False,
                  "domain": "unstretched linear brightness scale; nonlinear model operation",
                  "source_header_preserved": source_header is not None,
                  "source_scaling": source_scaling,
                  "coverage": coverage_record,
                  "reconstruction_max_error": reconstruction_error,
                  "residual": "signed source minus result; not a pure stellar flux measurement" if reconstruction_error is not None else None,
                  "limitations": "Model estimates may alter flux and structures; camera generalization and tile phase effects require validation.",
                  "outputs": [path.name for path in created], "output_integrity": output_integrity}
        if inference["strategy"] == "overlapping_tiles":
            report["tiling"] = {key: value for key, value in inference.items() if key not in {"strategy", "applied"}}
        report_path = destination / "ai_report.json"
        created.append(report_path)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _cancelled(cancel)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        destination.rmdir()
        raise
    log("KI-Ergebnis als Float32-FITS und TIFF gespeichert: %s" % destination)
    return str(destination / "result_32bit.tif")
