"""Download a bounded public HST seed dataset with provenance and FITS checks."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import requests
from astropy.io import fits
import numpy as np

POLICY = "https://archive.stsci.edu/publishing/data-use"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    query = dict(service="Mast.Caom.Filtered", format="json", pagesize=100, page=1,
                 params=dict(columns="*", filters=[
                     dict(paramName="obs_collection", values=["HST"]),
                     dict(paramName="target_name", values=["M51"]),
                     dict(paramName="dataproduct_type", values=["image"]),
                     dict(paramName="dataRights", values=["PUBLIC"])]))
    response = requests.post("https://mast.stsci.edu/api/v0/invoke",
                             data={"request": json.dumps(query)}, timeout=60)
    response.raise_for_status()
    rows = response.json()["data"]
    selected = [row for row in rows if row.get("filters") in ("F439W", "F555W", "F656N", "F675W")
                and str(row.get("dataURL", "")).endswith("_drz.fits")][:4]
    if len(selected) != 4:
        raise RuntimeError("Expected four optical science products; inspect archive query")
    manifest = dict(source="NASA/ESA Hubble, MAST", policy_url=POLICY,
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    group="M51", split="training_candidate", training_approved=False,
                    note="Processed single-band images, not noiseless truth. Preserve headers; inspect science/weight planes before patch extraction.",
                    products=[])
    total = 0
    for row in selected:
        uri = row["dataURL"]
        name = uri.rsplit("/", 1)[-1]
        if Path(name).name != name:
            raise ValueError("Invalid archive filename")
        destination = args.output / name
        partial = destination.with_suffix(".part")
        digest = hashlib.sha256()
        size = 0
        if not partial.exists() and not destination.exists():
            with requests.get("https://mast.stsci.edu/api/v0.1/Download/file", params={"uri": uri},
                              stream=True, timeout=(20, 120)) as download:
                download.raise_for_status()
                with partial.open("xb") as output:
                    for chunk in download.iter_content(1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > 512 * 1024**2 or total > 1024**3:
                            raise RuntimeError("Seed download size limit exceeded")
                        digest.update(chunk)
                        output.write(chunk)
        source = destination if destination.exists() else partial
        digest = hashlib.sha256()
        size = source.stat().st_size
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        planes = []
        with fits.open(source, memmap=False) as hdus:
            hdus.verify("exception")
            for index, hdu in enumerate(hdus):
                if isinstance(hdu, (fits.PrimaryHDU, fits.ImageHDU)) and hdu.data is not None:
                    array = hdu.data
                    planes.append(dict(index=index, name=hdu.name, shape=list(array.shape),
                                       finite_fraction=float(np.isfinite(array).mean()),
                                       unit=hdu.header.get("BUNIT")))
            primary = {key: hdus[0].header.get(key) for key in
                       ("TELESCOP", "INSTRUME", "PROPOSID", "TARGNAME", "EXPTIME")}
        if not planes:
            raise RuntimeError("No image planes in downloaded FITS")
        if source == partial:
            partial.rename(destination)
        manifest["products"].append(dict(filename=name, uri=uri, bytes=size,
            sha256=digest.hexdigest(), filter=row["filters"], observation_id=row["obs_id"],
            rights=row.get("dataRights"), header=primary, planes=planes))
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(name, size, "bytes, FITS verified", flush=True)


if __name__ == "__main__":
    main()
