# ForgePix local experimental models

These are ForgePix-trained restoration weights, executed locally by ONNX Runtime.
No third-party pretrained weights, GraXpert/RC Astro services or external
astronomy executables are required. They remain explicit research options and
are not selected by automatic processing.

Each folder contains a hash-checked model/manifest, training report, independent
synthetic evaluation and licence notices. Read the comparison against the earlier
parent: newer weights are not automatically better. The model ID denotes its
channel/normalization generation, not release quality.

Operations: denoise, additive background correction, deblur and starless.
All models consume one 256×256 mono plane and return the complete estimated
target, with independent application to each colour channel. Outputs retain the
linear brightness scale; the model operation itself is nonlinear and does not
provide photometrically validated measurements. Starless also exports a signed
source-minus-result residual for additive reconstruction.

Background estimation uses a resampled whole-field view and returns only a smooth
additive residual to the original grid. Other tasks use overlapping tiles. The
extra denoiser refinement was rejected after a fresh 128-scene check and is not
bundled. The bundled initial mono denoiser reduces noise on the tested scenes but
does not surpass the old RGB research baseline in aggregate pixel error.

Weights trained by ForgePix are provided under the repository MIT licence.
The NAFNet architecture is derived from
[NAFNet revision 2b4af71](https://github.com/megvii-research/NAFNet/tree/2b4af71ebe098a92a75910c233a3965a3e93ede4);
its MIT and accompanying BasicSR Apache notices are retained in every model
folder. This does not relicense the upstream architecture or the source data.

Public HST optical science products supplied observed scene structure for some
tasks, with controlled additional degradation and original noise retained.
Credit NASA/ESA Hubble, the observing programmes and STScI/MAST. The
[MAST data-use policy](https://archive.stsci.edu/publishing/data-use) distinguishes
public mission data, licensed high-level products and restricted collections;
these experiments use the recorded public HST science products, not DSS or GSC.
Original FITS are not included in the app. Source URIs, programme/filter/field,
hashes and split provenance are recorded with the training run.

Known limits: synthetic labels; few real object/instrument families; no held-out
ground-camera/noise-pair qualification; possible flux/structure/halo changes;
tile-context dependence; no field-dependent aberration model. Inspect the common
before/after display stretch and retain the original for scientific measurements.
