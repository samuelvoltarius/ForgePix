# ForgePix Roadmap — Pro-Tool Parity

*[🇩🇪 Deutsche Version](ROADMAP.de.md)*

> **Status (v1.22):** the parity wave (v1.20) and the gap-closing wave (v1.21–v1.22) are **done**.
> Every 🟡/❌ from the scorecard is built: focus Radius/Smoothing + halo retouch; astro full **GHS**,
> **linear-fit clipping**, **TPS** registration, **true drizzle**, real **PCC/SPCC** (Siril Gaia DR3 /
> own astroquery / lite); HDR **radiance tonemapping**; long-exposure **sigma-clip** + **freeze
> foreground**; RAW **lens corrections** (lensfun/manual) + AMaZE. Still open: lucky-imaging MAP
> (needs a good Moon/planet video) and the panorama control-point UI (a separate large GUI project).

Audit of every ForgePix module against the leading professional tools, with a concrete, prioritized
rebuild plan. Researched from Helicon/Zerene/PetteriAimonen (focus), AutoStakkert/PlanetarySystemStacker
(lucky imaging), Siril/PixInsight/APP/DSS (astro), Photomatix/Sequator/Hugin (HDR/trails/pano), and
RawTherapee/darktable (RAW develop). All recommendations are implementable in Python/OpenCV/NumPy
(+ astropy/scikit-image/pywt/lensfunpy), MIT-compatible.

## The one cross-cutting insight

**Local (non-rigid) alignment** is the single technique that separates amateur from pro results, and it
is missing everywhere in ForgePix (we only align globally). It is the root cause of:
- focus-stacking ghosting (pyramid doubling on slight misalignment / focus breathing),
- the lucky-imaging softness (global align can't fix local atmospheric seeing),
- HDR ghosting, and astro field-distortion.

So the foundation is a shared **`core/align_local.py`**: global align → local refinement (ECC sub-pixel
+ capped dense optical-flow / per-patch correlation). It unlocks several modules at once.

## What stays delegated (do NOT rebuild)

ML models are the product of their vendors and not reproducible: **GraXpert** (gradient + denoise),
**StarNet++** (star removal), **BlurXTerminator** (deconvolution), **Topaz/DxO** denoise. ForgePix
already integrates the free ones and exports linear 16/32-bit + FITS for clean hand-off. Keep that.

---

## 1. Focus stacking (vs Helicon, Zerene, PetteriAimonen/focus-stack)

**Now:** pyramid + depthmap merge; global align (rigid/homography/subject/sequential); tree merge;
culling; ghost/focus maps. **Weakness:** no local align; pyramid ghosts on tiny misalignment; no
weighted-average mode; no halo retouch.

| Priority | Build | Sketch |
|---|---|---|
| P0 | **ECC sub-pixel align refine + frame rejection** | seed `cv2.findTransformECC` with the ORB/RANSAC matrix (brightness-invariant); neighbor-chain with composed transforms; reject by correlation coeff |
| P1 | **Local non-rigid align** | where ECC residual is high: capped `DISOpticalFlow` + `cv2.remap` (coarse→fine) — kills pyramid ghosting & non-uniform breathing |
| P2 | **Consistency-voted wavelet merge** | per-frame complex/`pywt` wavelet → abs-max coeff → majority-vote among neighbors/subbands → wavelet-denoise (PetteriAimonen recipe; biggest noise/ghost win over naive pyramid) |
| P3 | **Method A (weighted average)** | focus measure (SML/Tenengrad) → normalized weights → `Σ wᵢ·fᵢ/Σ wᵢ`; expose Radius + Smoothing. Low-noise default for short stacks |
| P4 | **Color reassignment** | merge on luminance, pull real RGB from the best-matching source frame (no invented colors/halos) |
| P5 | **Halo retouch + slabbing** | dual output (depthmap base + pyramid detail) auto-composite/brush; slab 100+ frames → combine slabs with depthmap |

---

## 2. Lucky imaging — Sun/Moon/Planets (vs AutoStakkert, PlanetarySystemStacker)

**Now:** naive — global phase-correlate + average. **Measured fail:** softer than the single best frame
(Laplacian var ~4 vs ~13), because global align can't correct local seeing. **Fix = multi-point (MAP).**

| Priority | Build | Sketch |
|---|---|---|
| P0 | **Multi-point (MAP) pipeline** | global align → mean reference; staggered **alignment-point grid** (keep only AP with structure: `min(mean|∂x|,mean|∂y|) > t`); **per-AP** local quality ranking → top-K frames *per region*; per-AP sub-pixel shift (`matchTemplate` coarse→fine + paraboloid); average per patch; Hann-weighted blend, mean-image fill for gaps |
| P1 | **À-trous wavelet sharpening** (RegiStax-style) | B3-spline `[1,4,6,4,1]/16` dilated per level → 5–6 detail layers with per-layer gain + fine-layer denoise. Replaces the single unsharp |
| P2 | optional | multi-scale AP grids; drizzle 1.5×/2× (only if undersampled) |

**Honest success bar:** MAP stack sharpness **≥ single best frame** AND noise **≪** single frame
(measure both; don't trust Laplacian-var alone — wavelet sharpening inflates it).

---

## 3. Astro deep-sky (vs Siril, PixInsight, APP, DSS)

**Now:** calibration, debayer, star-offset-voting registration, sigma/winsor stacking, SCNR, dual-band
palettes, asinh stretch, GraXpert/StarNet/Siril hand-off. **Weakness:** global-only registration, no
local normalization, no photometric color calibration, asinh-only stretch.

| Priority | Build | Sketch |
|---|---|---|
| P1 | **Local normalization** (highest integration win) | per-frame coarse-grid background+scale model (low-deg polynomial/RBF, star-masked) applied *before* rejection — fixes gradients & multi-session |
| P2 | **GHS stretch** (generalized hyperbolic) | analytic family `f(x;D,b,SP,LP,HP)` with explicit shadow/highlight protection; auto-seed from median+MAD; reversible. Add MTF as simple mode |
| P3 | **Photometric color calibration (PCC)** | plate-solve → Gaia DR3 (`astroquery`) → aperture photometry (`photutils`) → per-channel scale; keep "delegate to Siril SPCC" fallback |
| P4 | **Local/distortion registration** | triangle/asterism matching + thin-plate-spline warp on star residuals (`RBFInterpolator(thin_plate_spline)` + `cv2.remap`); intensity-weighted centroids |
| P5 | **Linear-fit clipping** + **true drizzle** | line-fit rejection across normalized subs; Gaussian-kernel drizzle for dithered/undersampled data |

Keep delegating GraXpert/StarNet/deconvolution.

---

## 4. HDR (vs Photomatix, Lightroom, SNS-HDR)

**Now:** Mertens exposure fusion (correct default!), bracket auto-detect, rigid align, look presets.
**Weakness:** no deghosting, feature-align fails on flat brackets.

| Priority | Build | Sketch |
|---|---|---|
| P0 | **Deghosting** (biggest real-world win) | reference = mid-EV frame; exposure-match others; per-pixel deviation → motion mask (morph close + feather); in masked zones take the **reference only**, fusion elsewhere. `deghost: off/auto/aggressive` |
| P1 | **MTB alignment** | Ward median-threshold-bitmap (exposure-invariant) for translation; feature align as fallback for rotation/handheld |
| P2 | optional | radiance-map + tonemapping path (Debevec → Reinhard/Mantiuk) as an *alternative dramatic look*, not a replacement |

---

## 5. Long exposure / star trails (vs Sequator, StarStaX)

**Now:** smooth/trails/declutter/bright modes. **Weakness:** trails are dashed (no gap fill), mean/median
denoise, no foreground separation.

| Priority | Build | Sketch |
|---|---|---|
| P0 | **Trail gap-fill + comet mode** | directional max-filter along trail direction before lighten-stack (bridges gaps); comet = decaying lighten `accum = max(accum·decay, frame)` |
| P1 | **Sigma-clipping average** | replace mean/median in smooth/declutter with 3-iter k·σ rejection (kills planes/satellites/hot pixels, keeps mean SNR) |
| P2 | **Freeze-ground** | user boundary; sky star-aligned/lighten, foreground sigma-clip averaged, feathered composite |

---

## 6. Panorama (vs Hugin, PTGui)

**Now:** black-box `cv2.Stitcher`. **Weakness:** no control over projection/exposure/seams.

| Priority | Build | Sketch |
|---|---|---|
| P0 | **Explicit `cv2.detail` pipeline** | features→`BestOf2NearestMatcher`→`HomographyBasedEstimator`+`BundleAdjusterRay`→`waveCorrect`→user **projection** (`PyRotationWarper`)→**exposure comp** (`BlocksChannelsCompensator`)→**GraphCut seams**→**MultiBandBlender`. Keep Stitcher as `fast` fallback |

---

## 7. RAW develop & editor (vs RawTherapee, darktable)

**Now:** rawpy develop; Camera-Raw editor (exposure/contrast/WB/clarity/color + mask brush); unsharp +
edge-preserving denoise. **Weakness:** fixed demosaic, no highlight reconstruction, basic denoise/sharpen,
no tone-curve editor, no proper local adjustments, no lens corrections.

| Priority | Build | Sketch |
|---|---|---|
| P1 | **Highlight reconstruction** | masked channel-ratio fill (`blur(value·mask)/blur(mask)`) for partially-clipped pixels + desaturate-to-white for blown cores (kills magenta highlights) |
| P2 | **Wavelet sharpening** (shared with Lucky/Astro) | `pywt` multi-scale boost + per-scale denoise (RegiStax model); RL deconvolution (`skimage.restoration.richardson_lucy`, σ 0.5–0.7, 15–30 iter) as capture-sharpen |
| P3 | **Better denoise** | `cv2.fastNlMeansDenoisingColored` (fast) / `bm3d` (best, tiled, post-render); luma/chroma split |
| P4 | **Tone curves** | point (PCHIP, no overshoot) + parametric (region sliders); curve in perceptual encoding (Lab L*/working gamma); LUT apply |
| P5 | **Local adjustments** | gradient/radial/brush masks = smoothstep alpha + `cv2.ximgproc.guidedFilter` edge refine; parametric (luma/color range) gate |
| P6 | **Demosaic choice + lens corrections** | expose rawpy DHT/DCB/VNG (AMaZE needs GPL build); `lensfunpy` for distortion/TCA/vignetting (vignetting before remap) |

---

## Suggested build order (across modules)

1. **`core/align_local.py`** (ECC + capped optical-flow) — unblocks focus P0/P1 and feeds lucky.
2. **Lucky multi-point (MAP)** — the visible, currently-failing case; prove it beats the single frame.
3. **`core/wavelet.py`** (à-trous + RegiStax sharpening) — shared by lucky, astro, editor; big visible gain.
4. **Astro local normalization + GHS stretch** — biggest astro quality jump, pure math/numpy.
5. **HDR deghosting** + **trail gap-fill/comet** + **panorama `cv2.detail`** — fix the real-world failures.
6. **Editor**: highlight reconstruction → wavelet sharpen → denoise → curves → local masks → lens corr.
7. **Focus**: consistency-voted wavelet merge → Method A → color reassignment → halo retouch.

Each step ships independently, with an honest before/after measurement (sharpness **and** noise, by eye
**and** number) before any quality claim.

---

*Sources captured in the research that produced this plan: AutoStakkert, PlanetarySystemStacker,
Helicon Focus parameters, Zerene PMax/DMap, PetteriAimonen/focus-stack, astroalign, Siril (PCC/SPCC/GHS),
PixInsight StarAlignment, RawPedia/darktable manuals, lensfun. Nothing here is scheduled yet — it is the
agreed direction to build toward, module by module.*
