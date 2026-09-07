# The bundled AI models — what they do on real data

*As of 2026-09-07. Every number here comes from runs that were actually executed, not from the
models' own training reports.*

ForgePix ships four small ONNX models (1.8 MB each, NAFNet architecture, single channel,
256×256 tiles):

| Model | Task |
|---|---|
| `forgepix-denoise-mono-v2` | denoising |
| `forgepix-deblur-mono-v2` | sharpening |
| `forgepix-starless-mono-v2` | star separation |
| `forgepix-background-mono-v2` | background gradient estimation |

All four are marked **experimental** in their manifests (`release_approved: false`). They load
only with `allow_experimental=True` and are not enabled on any default path. This document
records what measuring them on real frames produces — so that the decision whether to release
them rests on numbers rather than on an impression.

## Why this measurement was needed at all

An earlier verdict on the **sharpening** model was wrong, and the mistake is instructive: the
test image had been scaled down to 35%. The models work on 256×256 tiles and are trained on stars
of a certain width; a downscaled image pushes the stars outside that working range. What got
measured was a widening; at full resolution the model in fact sharpens. **Measuring a model
outside its working range produces a number that means nothing — and still reads like a
finding.**

Everything here is therefore measured at **full resolution**, on whole stacks, with no scaling.

## Denoising

Two different targets, both 1920×1080, linear (before any stretch). Noise is the robust spread
(MAD × 1.4826) over the darkest 40% of the image. "Star flux" is the sum over the brightest 0.1%
of pixels — if it is preserved, the model is neither inventing nor eating brightness.

**C 31, 4 frames of 30 s (noisy starting point), Seestar S30**

| Strength | Noise | Change | Stars found | FWHM | Star flux |
|---|---|---|---|---|---|
| — (before) | 0.0003160 | | 118 | 2.241 px | |
| 0.3 | 0.0002655 | **−16.0%** | 114 | 2.312 px | +0.05% |
| 0.5 | 0.0002348 | **−25.7%** | 112 | 2.312 px | +0.09% |
| 1.0 | 0.0001802 | **−43.0%** | 105 | 2.355 px | +0.17% |

**IC 434, 40 frames of 30 s (deeper stack), Seestar S30**

| Strength | Noise | Change | Stars found | FWHM | Star flux |
|---|---|---|---|---|---|
| — (before) | 0.0001185 | | 26 | 2.631 px | |
| 0.3 | 0.0001058 | **−10.7%** | 26 | 2.631 px | +0.16% |
| 0.5 | 0.0000974 | **−17.7%** | 26 | 2.631 px | +0.26% |
| 1.0 | 0.0000805 | **−32.1%** | 26 | 2.646 px | +0.52% |

**What follows from this:**

* The model genuinely denoises, and substantially. It is not a blur with a good name.
* **It invents no brightness.** Star flux changes by less than 0.6%. That is the most important
  point: a model hallucinating structure would show up here.
* **The price is the faintest stars.** On the noisy image, full strength lost 13 of 118 detected
  stars (−11%). On the deep stack, none. That is consistent: whatever sits just above the noise
  goes with the noise.
* Star width grows by 3 to 5% — measurable, but small.

**Recommendation:** 0.3 to 0.5. Full strength only where faint stars do not matter — and never
before photometry.

## The three other models — and the comparison against the classical path

Measured on the same deep IC 434 stack (40 frames), full resolution.

### Sharpening

| | FWHM | stars found | noise | star flux |
|---|---|---|---|---|
| before | 2.631 px | 26 | | |
| model, strength 0.5 | 2.646 px | 26 | +0.9% | +3.5% |
| model, strength 1.0 | 2.544 px | 29 | +3.0% | +6.9% |
| classical, RL 15 iterations | 2.355 px | 39 | +15.2% | −0.2% |
| classical, RL 30 iterations | **2.220 px** | **42** | +25.5% | −3.3% |

The model does sharpen — the earlier claim to the contrary was a measurement error and is hereby
refuted. But it sharpens **weakly**: −3.3% FWHM against −15.6% for classical Richardson-Lucy
deconvolution, and it finds 29 stars instead of 42. Richardson-Lucy pays for that in noise
(+25.5%); the model is gentler there.

One point counts against the model: **it raises star flux by 6.9%.** Richardson-Lucy does not
(−0.2%). A sharpening method should redistribute brightness, not create it; that makes the model
unusable for photometry.

### Star separation

Measured as the star flux **above sky level** remaining after separation. Less is better.

| | star flux remaining |
|---|---|
| model, strength 0.5 | 67.7% |
| model, strength 1.0 | 35.3% |
| classical (`remove_stars`) | **4.8%** |

The classical path is **seven times more thorough** here. At full strength the model leaves more
than a third of the starlight standing.

### Background

Measured as the brightness gradient across the frame. Less is better.

| Image | before | model 0.5 | model 1.0 | classical |
|---|---|---|---|---|
| C 31 (4 frames) | 4.63% | 5.50% | **6.37%** | **1.55%** |
| IC 434 (40 frames) | 2.69% | 2.33% | 2.37% | **0.29%** |
| IC 434 + artificial gradient | 101.87% | 54.82% | 15.14% | **0.29%** |

On a coarse artificial gradient the model works (102% → 15%), so it is not broken. On **real**
gradients it is useless: on C 31 it makes the gradient worse (4.63% → 6.37%). The classical path
beats it clearly in all three cases.

## Conclusion

Of the four models, only the **denoiser** earns its place. For sharpening, star separation and
background, the classical path already built into ForgePix is better — in places by a wide
margin. Keeping all four marked experimental and unreleased is, on these numbers, correct.

This is not an argument against retraining; it is an argument for aiming it where it pays. And it
is evidence that this project's classical methods are not the weak stopgap that an "AI" label
likes to imply.

## What is not measured yet

Stated plainly, so nobody reads more into the numbers than is there:

* **Seestar S30 frames only.** Both measurements come from the same camera. Whether the model
  behaves the same on ASI294MC or ASI533MC data is open — different pixel scale, different star
  width, different read noise.
* **Broadband only (IRCUT).** Narrowband has a different signal-to-background ratio.
* **For denoising, the comparison against the classical path is missing.** It is above for
  sharpening, star separation and background; not for denoising.
* **One target per comparison.** All three comparison measurements come from the same IC 434
  stack. Background used three images, the other two used one.

## A note on normalisation

Training used percentiles (0.1 / 99.9) computed **per 256×256 scene**. At inference,
`core/ai_restore.py` computes them **once over the whole image** and shares them across all tiles
(`_infer`, "Shared statistics across all channels, never per tile or per channel").

That is a deliberate decision, not an oversight: per-tile normalisation would create brightness
steps at tile boundaries, i.e. visible seams. The price is that the input distribution at
inference does not exactly match the one at training. The measurements above show that it holds
up anyway — they are the evidence for it, not the theory.
