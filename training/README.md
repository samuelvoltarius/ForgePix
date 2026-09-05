# ForgePix model development

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
