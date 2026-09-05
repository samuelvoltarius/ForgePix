# PixInsight vs ForgePix — process by process

*[🇩🇪 Deutsche Version](PIXINSIGHT.de.md)*

## Where this list comes from

The official documentation at `pixinsight.com/doc/` answers direct requests with **HTTP 403**.
An earlier attempt therefore produced a list built on 404 error pages — that is, on nothing.

This list comes from the **source code**: the PixInsight Class Library (PCL) is open, and every
process sits there as a `…Process.cpp` under `src/modules/processes/`. Four public mirrors of the
repository were enumerated; their union gives **91 processes**, each backed by a file.

**What is missing from that, and it matters:** the PCL only contains the OPEN modules. Some of
the best-known PixInsight processes are closed and do not appear there — `Deconvolution`,
`MultiscaleLinearTransform`, `MultiscaleMedianTransform`, `ATrousWaveletTransform`, `TGVDenoise`,
`ACDNR`, `SCNR`, `StarMask`, `RangeSelection`, `StarAlignment`, `DynamicAlignment`. They appear
below in their own rows, marked *(closed)* — those are **from knowledge, not from a source**.

Symbols: ✅ present · 🟡 partial · ❌ absent · ➖ not meaningful for ForgePix

---

## Calibration and integration

| PixInsight | ForgePix | |
|---|---|---|
| ImageCalibration | `astro.calibrate` (dark/flat/bias), dark rescaling that keeps the bias pedestal fixed | ✅ |
| ImageIntegration | `astro.stack` — sigma, winsor, linearfit, average, median, max; SNR weighting; mixed exposure times | ✅ |
| DrizzleIntegration | `astro.drizzle_stack` (true drizzle with pixfrac) | ✅ |
| LocalNormalization | `astro.local_normalize` (local background surface) | ✅ |
| CosmeticCorrection | `astro.cosmetic_correct` + `sensor.defektkarte` (from the lights, no darks needed) | ✅ |
| DefectMap | `sensor.karte_laden` / `sensor.defekte_ersetzen` | ✅ |
| Debayer | `astro.detect_bayer` + demosaic path | ✅ |
| SubframeSelector | `astro_quality.select_subs` (FWHM, star count, roundness, clouds, trails) | ✅ |
| CometAlignment | `komet.stack_auf_kern` — finds the nucleus **itself**; PixInsight requires clicking it | ✅ |
| HDRComposition | `hdr.py` (exposure fusion, deghosting, tonemapping) | ✅ |
| Superbias | ❌ — smoothing a bias master via principal components | ❌ |
| SplitCFA / MergeCFA / CFA2RGB | ❌ — working on CFA planes separately | ❌ |
| StarGenerator | ➖ synthetic star fields (only inside ForgePix tests) | ➖ |

## Registration

| PixInsight | ForgePix | |
|---|---|---|
| StarAlignment *(closed)* | `astro.register_and_cache` — triangle matching, rotation, cluster bridge for dither jumps, automatic best reference | ✅ |
| DynamicAlignment *(closed)* | `astro._tps_refine` (thin-plate spline for residual distortion) | ✅ |
| ChannelMatch | 🟡 via the same registration, no dedicated process | 🟡 |
| Geometry (Crop, Resample, Rotation, IntegerResample, DynamicCrop, FastRotation) | 🟡 `stacker.crop`, `crop_to_overlap`, `astro.bin_image` — no free geometry tool | 🟡 |

## Background and colour

| PixInsight | ForgePix | |
|---|---|---|
| BackgroundNeutralization | `astro.neutralize_background` | ✅ |
| ColorCalibration | `astro.color_balance` | ✅ |
| PhotometricColorCalibration | `photometric.run_pcc` — Siril SPCC, astroquery Gaia, **own local Gaia extract (offline)**, lite | ✅ |
| LinearFit | `astro.linear_match` (robust, with outlier rejection) | ✅ |
| SCNR *(closed)* | `astro.remove_green_cast` | ✅ |
| Gaia | `gaia_lokal` — own catalogue extract with a cell index, about 100× faster than a server query | ✅ |
| APASS | ❌ — a second photometric catalogue | ❌ |
| DynamicBackgroundExtraction *(script/closed)* | `astro.background_extract` (RBF, **per channel**, subtraction or division) | ✅ |
| ColorSaturation | 🟡 available as a control inside the stretches, no hue-dependent curve | 🟡 |
| ColorManagement (ICC, RGBWorkingSpace, ColorManagementSetup) | ➖ ForgePix works in sRGB | ➖ |

## Stretching and tones

| PixInsight | ForgePix | |
|---|---|---|
| HistogramTransformation | `astro.mtf_stretch` (MTF, defined black point) | ✅ |
| ScreenTransferFunction | `astro.autostretch` | ✅ |
| ArcsinhStretch | `astro.autostretch` (asinh) | ✅ |
| CurvesTransformation | `develop.py` (PCHIP tone curves) | ✅ |
| AutoHistogram | `astro.autostretch` | ✅ |
| MaskedStretch | 🟡 `astro.stretch_starless` pursues the same goal (keeping stars small) by another route | 🟡 |
| AdaptiveStretch | 🟡 `astro.ghs_stretch` (generalised hyperbolic) | 🟡 |
| ExponentialTransformation | 🟡 `astro.ddp` (Okano) is related, not the same | 🟡 |
| LocalHistogramEqualization | `astro.local_contrast` (CLAHE, **luminance only**) | ✅ |
| Binarize / Invert / Rescale | ➖ one-liners, no dedicated process needed | ➖ |
| — | `astro.stretch_preserve_color` — channel ratios stay intact. **PixInsight has no equivalent** | ⭐ |
| — | `astro.ddp` with a measured 2.2× nebula contrast at equal blow-out | ⭐ |

## Noise and sharpness

| PixInsight | ForgePix | |
|---|---|---|
| MultiscaleLinearTransform / ATrousWaveletTransform *(closed)* | `wavelet.py` (à trous, multiscale) | ✅ |
| TGVDenoise *(closed)* | `astro.tv_denoise` (total variation, edge preserving) | ✅ |
| ACDNR *(closed)* | 🟡 covered by `tv_denoise` + masks, no dedicated process | 🟡 |
| GREYCstoration | 🟡 same as above | 🟡 |
| Deconvolution *(closed)* | `astro.deconvolve` (Richardson-Lucy, PSF from the image, TV regularisation, star protection) | ✅ |
| RestorationFilter | 🟡 Wiener / constrained least squares — covered by deconvolution | 🟡 |
| UnsharpMask | `develop.py`, `wavelet.py`, optional inside `astro.ddp` | ✅ |
| Convolution | 🟡 present internally, not as a tool | 🟡 |
| MorphologicalTransformation | 🟡 `astro.reduce_stars` uses it specifically for stars | 🟡 |
| LarsonSekanina | ❌ — rotational gradient for comet and solar detail | ❌ |
| FourierTransform / InverseFourierTransform | ❌ | ❌ |

## Stars

| PixInsight | ForgePix | |
|---|---|---|
| StarNet | `starless.py` (external, optional) + `astro.remove_stars` (classical, no ML) | ✅ |
| StarMask *(closed)* | `masken.sterne` — with minimum area and roundness filter | ✅ |
| DynamicPSF | `astro.estimate_psf` (empirical, averaged over many stars) | ✅ |
| — | `astro.synthstar` — replacing star shapes with round Moffat profiles. **PixInsight has no equivalent** (Siril does) | ⭐ |
| — | `astro.unclip_stars` — recovering the colour of blown cores from their wings | ⭐ |
| — | `astro.reduce_stars` — shrinking stars | ⭐ |

## Masks

| PixInsight | ForgePix | |
|---|---|---|
| StarMask *(closed)* | `masken.sterne` | ✅ |
| RangeSelection *(closed)* | `masken.helligkeit` | ✅ |
| — | `masken.hintergrund`, `masken.nebel` — ready-made masks for the two cases that actually matter | ⭐ |
| General mask logic (every process through any mask) | 🟡 `masken.anwenden` exists, but only the astro steps are wired to it | 🟡 |

## Measurement

| PixInsight | ForgePix | |
|---|---|---|
| AberrationInspector | `sensor.feldkarte` / `feld_urteil` — **separates field curvature from sensor tilt** | ✅ |
| Statistics | 🟡 contained in `astro_quality`, not a standalone tool | 🟡 |
| FITSHeader | 🟡 read only (`equipment.aus_header`, `filters.aus_header`) | 🟡 |
| Blink | ❌ — flipping quickly through frames | ❌ |
| StarMonitor | ❌ — tracking star quality while shooting | ❌ |
| FluxCalibration | ❌ — absolute flux calibration | ❌ |
| — | `photometrie.lichtkurve` + AAVSO export + period search. **PixInsight has no equivalent** (scripts only) | ⭐ |
| — | `equipment.py` — image scale, sampling verdict, reducers, dither detection, user-defined gear | ⭐ |
| — | `filters.py` — 20 filters with sourced bandwidths, palette plausibility | ⭐ |
| — | `livestack.py` — incremental stacking while shooting | ⭐ |

## Everything else

| PixInsight | ForgePix | |
|---|---|---|
| **PixelMath** | ❌ — **the biggest real gap.** Arbitrary expressions over images, the universal tool | ❌ |
| CloneStamp | 🟡 retouch brush in the interface (from another frame, not from the same image) | 🟡 |
| GradientsMergeMosaic | 🟡 `mosaic.py` (panorama, not built for sky mosaics) | 🟡 |
| GradientsHdr / GradientsHdrComposition | ❌ | ❌ |
| Annotation / FindingChart | ❌ — writing object names into the image, finder charts | ❌ |
| EphemerisGenerator / B3E | ❌ — orbit computation, blackbody extrapolation | ❌ |
| INDICCDFrame / INDIDeviceController / INDIMount | ❌ — **device control.** A project of its own; N.I.N.A. has an HTTP API, Seestar goes via ASCOM Alpaca | ❌ |
| NetworkService / Preferences / ReadoutOptions / FilterManager | ➖ | ➖ |
| ChannelCombination / ChannelExtraction / LRGBCombination | 🟡 `astro._extract_ha_oiii` and the four palettes cover the dual-band case; the general tool is missing | 🟡 |
| CreateAlphaChannels / ExtractAlphaChannels / NewImage / SampleFormatConversion / ImageIdentifier | ➖ | ➖ |
| NoiseGenerator / SimplexNoise | ➖ | ➖ |
| ICCProfileTransformation / AssignICCProfile | ➖ | ➖ |
| AssistedColorCalibration | ➖ covered by PCC | ➖ |

---

## What ForgePix has and PixInsight does not

The comparison runs both ways. These do not exist there, or only through scripts:

- **Colour-preserving stretch** (`stretch_preserve_color`): only brightness runs through the
  curve. On real dual-band data, saturation rose from 0.075 to 0.510.
- **Starless stretch with linear star re-insertion**: nebula +22 %, blown pixels 14× fewer.
- **The comet nucleus is found automatically** — PixInsight and Siril require two clicks.
- **`synthstar`** — re-rendering star shapes (Siril has it, PixInsight does not).
- **Sensor diagnostics without calibration frames**: defect map from the lights, field map that
  separates curvature from tilt.
- **Equipment calculations**: image scale, sampling verdict, reducers, dither detection.
- **Filter database** with sourced bandwidths and an honest warning when a palette is physically
  impossible (SHO without SII).
- **Incremental live stacking** with a saved running state.
- **Light curves and AAVSO export** straight from the same series.
- **Local Gaia extract** for colour calibration without internet.
- **All of it in an interface built for beginners** — one plain-language image style instead of
  fifty process windows.

## The three honest gaps

1. **PixelMath.** An expression evaluator over images is the tool with which anything that is not
   its own process gets built in PixInsight. It is entirely absent here.
2. **General mask logic.** The building blocks exist (`core/masken.py`), but only the astro steps
   are wired to them. In PixInsight, EVERY process can be applied through ANY mask.
3. **Device control.** INDI/ASCOM is a project of its own. The pragmatic route remains consuming
   the OUTPUT of the devices — the watch mode on their output folder is already there.

Plus the smaller ones: Superbias, APASS, LarsonSekanina, Fourier tools, Blink, Annotation,
FluxCalibration, per-plane CFA work.
