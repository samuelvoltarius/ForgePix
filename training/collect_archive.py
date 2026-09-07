"""Bounded, sequential public optical HST acquisition across independent fields."""
import argparse
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
    # --- 07.09.2026 ergaenzt -------------------------------------------------------------
    # Oft beobachtete oeffentliche HST-Felder. Grund: mit acht Feldern (43 Aufnahmen, rund
    # 2600 Kacheln) laesst sich kein Netz in GraXperts Groessenklasse trainieren — 107,65
    # Millionen Parameter bei width 256 gegen 0,44 Millionen heute.
    # Galaxien
    ("M31", 10.6847, 41.2687, "train"),
    ("M33", 23.4621, 30.6600, "train"),
    ("M51", 202.4696, 47.1952, "train"),
    ("M64", 194.1824, 21.6829, "train"),
    ("M74", 24.1739, 15.7836, "train"),
    ("M81", 148.8882, 69.0653, "train"),
    ("M83", 204.2538, -29.8657, "train"),
    ("M87", 187.7059, 12.3911, "train"),
    ("M104", 189.9976, -11.6231, "train"),
    ("NGC253", 11.8880, -25.2882, "train"),
    ("NGC891", 35.6392, 42.3492, "train"),
    ("NGC1300", 49.9208, -19.4111, "train"),
    ("NGC2841", 140.5108, 50.9765, "train"),
    ("NGC3521", 166.4525, -0.0359, "train"),
    ("NGC4038", 180.4713, -18.8672, "train"),
    ("NGC4414", 186.6129, 31.2235, "train"),
    ("NGC4565", 189.0866, 25.9876, "validation"),
    ("NGC6946", 308.7180, 60.1539, "test"),
    # Nebel
    ("M1", 83.6331, 22.0145, "train"),
    ("M17", 275.1963, -16.1772, "train"),
    ("M20", 270.6708, -22.9717, "train"),
    ("M27", 299.9016, 22.7211, "train"),
    ("M57", 283.3962, 33.0292, "train"),
    ("M76", 25.5771, 51.5754, "train"),
    ("NGC3132", 151.7592, -40.4361, "train"),
    ("NGC3372", 161.2650, -59.8678, "train"),
    ("NGC6302", 258.4333, -37.1031, "train"),
    ("NGC7293", 337.4108, -20.8372, "train"),
    ("IC434", 85.2458, -2.4583, "train"),
    ("NGC7635", 350.2013, 61.2011, "validation"),
    ("NGC6960", 311.6667, 30.7167, "test"),
    # Kugelsternhaufen und dichte Felder — viele Sterne, wenig Flaechenhelligkeit
    ("M2", 323.3626, -0.8233, "train"),
    ("M4", 245.8968, -26.5256, "train"),
    ("M15", 322.4930, 12.1670, "train"),
    ("M22", 279.0999, -23.9047, "train"),
    ("M53", 198.2302, 18.1682, "train"),
    ("M80", 244.2600, -22.9761, "train"),
    ("M92", 259.2808, 43.1359, "train"),
    ("NGC104", 6.0236, -72.0814, "train"),
    ("NGC5139", 201.6970, -47.4795, "validation"),
    # Magellansche Wolken — andere Sternpopulation, andere Farben
    ("NGC346", 14.7625, -72.1775, "train"),
    ("NGC602", 22.4000, -73.5500, "train"),
    ("NGC2070", 84.6767, -69.1008, "test"),
]
GIB = 1024 ** 3


def query_field(ra, dec, *, attempts=3):
    if not 1 <= attempts <= 3:
        raise ValueError("Query attempts must be between one and three")
    rows = []
    for page in (1, 2):
        query = dict(service="Mast.Caom.Filtered.Position", format="json", pagesize=500, page=page,
            params=dict(columns="*", position=f"{ra},{dec},0.08", filters=[
                dict(paramName="obs_collection", values=["HST"]),
                dict(paramName="dataproduct_type", values=["image"]),
                dict(paramName="dataRights", values=["PUBLIC"])]))
        # Cone searches can time out transiently. Retry this page only, with a
        # finite budget; previously one timeout permanently omitted the holdout.
        for attempt in range(attempts):
            try:
                response = requests.post("https://mast.stsci.edu/api/v0/invoke",
                                         data={"request": json.dumps(query)}, timeout=(15, 60))
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") != "COMPLETE":
                    raise RuntimeError(payload.get("msg", "Archive query failed"))
                break
            except (requests.RequestException, RuntimeError) as exc:
                if (isinstance(exc, requests.HTTPError) and exc.response is not None
                        and exc.response.status_code not in {408, 429, 500, 502, 503, 504}):
                    raise
                if attempt + 1 == attempts:
                    raise
                print("QUERY RETRY", page, attempt + 1, str(exc), flush=True)
                time.sleep(2 ** (attempt + 1))
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


def main(field_names=None, max_gib=25):
    selected_fields = FIELDS if field_names is None else [f for f in FIELDS if f[0] in field_names]
    if field_names is not None and set(field_names) - {field[0] for field in FIELDS}:
        raise ValueError("Unknown field selection")
    root = Path.home() / "forgepix-training/datasets/hst-diverse-001"
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "download.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    used = sum(p.stat().st_size for p in root.rglob("*.fits"))
    budget = max(1, int(max_gib)) * GIB
    try:
        for group, ra, dec, split in selected_fields:
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
                if used >= budget or shutil.disk_usage(root).free < 80 * GIB:
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
                                if (size > GIB or used + size > budget
                                        or shutil.disk_usage(root).free - len(block) < 80 * GIB):
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-gib", type=int, default=25,
                        help="Obergrenze fuer die heruntergeladene Menge in GiB (Vorgabe 25). "
                             "Der Schutz, mindestens 80 GiB Plattenplatz frei zu lassen, "
                             "bleibt unabhaengig davon bestehen.")
    parser.add_argument("--field", action="append", choices=[field[0] for field in FIELDS],
                        help="Acquire only this field; repeat to select several. Existing splits stay fixed.")
    _a = parser.parse_args()
    main(_a.field, max_gib=_a.max_gib)
