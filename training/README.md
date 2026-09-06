# ForgePix model development

## Real-scene adaptation result (2026-09-06)

`data-env/bin/python -m training.train_fits` was executed on the Spark.
114 fully valid 128px training patches from five object groups and 47 validation
patches from M13 were used. M16 yielded no patches under the current strict
criteria. Original FITS science/coverage planes were preserved; clipping and
non-finite regions were rejected. Patch coordinates, normalization and source
hashes are saved per run. This tests added Gaussian noise on real scene content;
it does not provide independent real-noise clean targets or colour-camera coverage.

Run `fits-adaptation-20260906-075100`: 1,500 steps in 27.5 seconds. Validation MSE:
identity 2.2492e-4, parent 2.7394e-5, adapted 3.4472e-5. The adaptation is WORSE
than its parent and must not replace it. Neither model is release-qualified.
Next work requires more representative validation objects, independent exposure
pairs and scientific preservation metrics, not merely more training iterations.

## Public FITS seed data

Expanded acquisition: `python -m training.collect_archive` on the Spark, using
`~/forgepix-training/data-env/bin/python` (isolated Astropy environment).
Output: `~/forgepix-training/datasets/hst-diverse-001`.
Eight fields have fixed object-level splits: M101/M42/M8/M82/NGC7009 training,
M16/M13 validation, NGC6543 final test. Existing M51 seed remains training-only.
Each field selects up to six distinct optical-filter combined products and two
calibrated exposures from at most 1,000 search results. This is a bounded diverse
sample, not an exhaustive archive mirror or a complete camera-general dataset.
Limits: 25 GiB total, 1 GiB per file, 80 GiB disk reserve. Each FITS has a provenance
sidecar; a process lock avoids duplicate runs. Inspect failures in collection.log.

Task suitability: science planes can supply realistic scene structure for
synthetic degradation. Real noise pairs require matching independent exposures
and alignment; combined images may already contain those exposures. Background
and starless targets require separate trusted labels/simulation. Deblurring needs
known PSFs and flux-preservation tests. Do not label downloaded frames as noiseless
truth or automatically train all restoration tasks on them. HST alone does not
represent ground-based camera/readout/seeing conditions.

`python -m training.fetch_mast --output DATA_DIRECTORY` retrieves four public
HST/WFPC2 M51 single-filter drizzled products from MAST (programme 7375).
The manifest records archive identifiers, SHA-256 hashes, filters, exposure,
image planes and data-use policy: https://archive.stsci.edu/publishing/data-use.
These are science FITS products, not JPEG press images or noiseless ground truth.
Credit NASA/ESA Hubble, the original observing programme and STScI/MAST.

Keep all M51 products and derivatives in the same training-candidate group.
Never split patches from this same object between training and independent tests.
Use the SCI extension and mask non-finite pixels and non-positive WHT coverage.
The first verified image has only about 40% finite SCI coverage; black-filled
invalid borders must not become training examples. Do not pass these multi-HDU
files directly to a loader that expects the primary HDU to contain the image.
No current model has yet been trained on this downloaded seed dataset.

## Automatic experiments

`python -m training.run_queue --output runs/multi-task-001 --steps 10000`
runs background correction, isotropic deblurring, star separation and denoising
sequentially. An exclusive lock prevents a second queue using the same directory.
Existing task directories are preserved; failures stop the queue for inspection.
Each run evaluates 32 deterministic synthetic validation scenes. Queue records
compare output error against the unprocessed input, not against a production
incumbent. No model is automatically enabled or promoted to production.

These are deliberately limited engineering baselines: smooth positive gradients,
Gaussian blur and synthetic stars are not realistic coverage of every telescope,
camera, nebula or aberration. A successful score does not demonstrate real-data
quality. Repeated development against these validation seeds requires a further
untouched final test set before release.

Spark run started 2026-09-05: `~/forgepix-training/runs/multi-task-001`.
Read `queue.jsonl`, per-task `report.json` and `supervisor.log` before launching
another run. The queue is finite; changes and follow-up experiments are handled
by the existing ForgePix continuation task.

This directory contains an experimental, synthetic-only denoising baseline.
It is not enabled in the application and is not release-qualified.

The NAFNet architecture in `vendor/nafnet_upstream.py` comes from
https://github.com/megvii-research/NAFNet at revision
`2b4af71ebe098a92a75910c233a3965a3e93ede4`.
Its license is retained in `vendor/NAFNet-LICENSE.txt`.
Changes: replace custom channel normalization with ordinary PyTorch operations;
omit the optional local-pooling conversion and command-line profiling example.
No upstream pretrained weights or upstream training data are distributed.

Install PyTorch separately in a training environment. From the repository root:

    python -m training.train_synthetic --output runs/experiment-001 --steps 500

Every run requires a new output directory. Reports include configuration, timing,
synthetic validation errors and an explicit false release-approval flag.
The current simulation varies star widths, colours, diffuse structures, signal
levels, shot noise and read noise. It does not establish camera independence.

Before release: train on licensed, calibrated linear FITS datasets; split by
object, observing session and camera before extracting patches. Include held-out
camera families, mono/OSC data, narrowband data and faint extended emission.
Measure stellar flux, star count, FWHM, background bias and false structure, not
only pixel error. Record source permissions and preprocessing per dataset.
Hardware metadata must remain optional, with measured image statistics as a
fallback. A synthetic validation pass alone must never enable a production model.
