"""Bounded, sequential public optical HST acquisition across independent fields."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import requests
from astropy.io import fits
import numpy as np

# Cone centres identify fields, not precision astrometric reference positions.
# Every product from a field keeps the same split, including derived patches.
FIELDS = [
    ("M101", 210.8023, 54.349, "train"),
    ("M42", 83.822, -5.391, "train"),
    ("M8", 270.925, -24.38, "train"),
    ("M82", 148.969, 69.679, "train"),
    ("NGC7009", 316.044, -11.364, "train"),
    ("M16", 274.7, -13.8, "validation"),
    ("M13", 250.423, 36.461, "validation"),
    ("NGC6543", 269.639, 66.633, "test"),
]
GIB = 1024 ** 3


def query_field(ra, dec):
    rows = []
    for page in (1, 2):
        query = dict(service="Mast.Caom.Filtered.Position", format="json", pagesize=500, page=page,
            params=dict(columns="*", position=f"{ra},{dec},0.08", filters=[
                dict(paramName="obs_collection", values=["HST"]),
                dict(paramName="dataproduct_type", values=["image"]),
                dict(paramName="dataRights", values=["PUBLIC"])]))
        response = requests.post("https://mast.stsci.edu/api/v0/invoke",
                                 data={"request": json.dumps(query)}, timeout=120)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "COMPLETE":
            raise RuntimeError(payload.get("msg", "Archive query failed"))
        rows.extend(payload["data"])
        if page >= payload.get("paging", {}).get("pagesFiltered", 1):
            break
    selected, seen_filters, singles = [], set(), 0
    for row in sorted(rows, key=lambda item: str(item.get("dataURL", ""))):
        uri, band = row.get("dataURL") or "", row.get("filters") or ""
        if not re.fullmatch(r"F[4-8][0-9]{2}[WMN]", band):
            continue
        if row.get("dataRights") != "PUBLIC" or not uri.startswith("mast:HST/product/"):
            continue
        if str(row.get("target_name", "")).upper() in {"TUNGSTEN", "DARK", "BIAS", "EARTH", "FLAT"}:
            continue
        combined = uri.endswith(("_drz.fits", "_drc.fits"))
        single = uri.endswith(("_flt.fits", "_flc.fits"))
        if combined and band not in seen_filters and len(seen_filters) < 6:
            selected.append(row)
            seen_filters.add(band)
        elif single and singles < 2:
            selected.append(row)
            singles += 1
    return selected


def main():
    root = Path.home() / "forgepix-training/datasets/hst-diverse-001"
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "download.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    used = sum(p.stat().st_size for p in root.rglob("*.fits"))
    try:
        for group, ra, dec, split in FIELDS:
            folder = root / group
            folder.mkdir(exist_ok=True)
            try:
                rows = query_field(ra, dec)
                (folder / "selection.json").write_text(json.dumps(rows, indent=2))
            except Exception as exc:
                print(group, "QUERY FAILED", str(exc), flush=True)
                continue
            for row in rows:
                uri = row["dataURL"]
                name = uri.rsplit("/", 1)[-1]
                if not re.fullmatch(r"[A-Za-z0-9_.-]+\.fits", name):
                    continue
                path = folder / name
                record_path = folder / (name + ".json")
                if path.exists() and record_path.exists():
                    continue
                if used >= 25 * GIB or shutil.disk_usage(root).free < 80 * GIB:
                    print("RESOURCE LIMIT: stopping acquisition", flush=True)
                    return
                partial = folder / (name + ".part")
                try:
                    size, digest = 0, hashlib.sha256()
                    with requests.get("https://mast.stsci.edu/api/v0.1/Download/file",
                                      params={"uri": uri}, stream=True, timeout=(30, 120)) as response:
                        response.raise_for_status()
                        with partial.open("wb") as output:
                            for block in response.iter_content(1024 * 1024):
                                size += len(block)
                                if size > GIB or used + size > 25 * GIB or shutil.disk_usage(root).free < 80 * GIB:
                                    raise RuntimeError("Download resource limit exceeded")
                                digest.update(block)
                                output.write(block)
                    planes = []
                    with fits.open(partial, memmap=False) as hdus:
                        hdus.verify("exception")
                        header = {key: hdus[0].header.get(key) for key in
                                  ("TELESCOP", "INSTRUME", "DETECTOR", "PROPOSID", "TARGNAME", "EXPTIME")}
                        for index, hdu in enumerate(hdus):
                            if isinstance(hdu, (fits.PrimaryHDU, fits.ImageHDU)) and hdu.data is not None:
                                planes.append(dict(index=index, name=hdu.name, shape=list(hdu.data.shape),
                                    finite_fraction=float(np.isfinite(hdu.data).mean()), unit=hdu.header.get("BUNIT")))
                    if not planes:
                        raise RuntimeError("No image data")
                    partial.replace(path)
                    used += size
                    record = dict(uri=uri, bytes=size, sha256=digest.hexdigest(), group=group,
                        split=split, rights="PUBLIC", filter=row["filters"], header=header, planes=planes,
                        policy="https://archive.stsci.edu/publishing/data-use", retrieved_at=time.time(),
                        training_approved=False, ground_truth=False,
                        note="Candidate scene source. Mask invalid/zero-weight pixels and inspect DQ; not a clean/noisy pair or starless label.")
                    record_path.write_text(json.dumps(record, indent=2))
                    print(group, split, name, size, "VERIFIED", flush=True)
                except Exception as exc:
                    partial.unlink(missing_ok=True)
                    print(group, name, "FAILED", str(exc), flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
