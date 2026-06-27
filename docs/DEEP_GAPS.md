# ForgePix — Deep Algorithmic Gap Analysis vs Pro Tools (v1.23)

Not a feature checklist — this is an **algorithm-level** audit of where ForgePix is genuinely weaker than
the leading tools, why, and what would close the gap. Researched per module (pro-tool algorithms + ForgePix
source). Honest: it also says where ForgePix is already on par.

Legend — Impact: 🔴 high · 🟠 medium · ⚪ low. Effort: S/M/L.

---

## 🔬 Focus stacking — vs Helicon Focus / Zerene Stacker

The method *coverage* (pyramid/depthmap/average/wavelet/halofix) is competitive. The real deficit is
**alignment precision** and **edge-coherent selection**.

| # | Gap | Pro tool | ForgePix | Fix | I/E |
|---|---|---|---|---|---|
| F1 | **ECC sub-pixel align is built but NOT wired** | Zerene: continuous Levenberg-Marquardt over X/Y/scale/rot, sub-pixel, brightness-invariant | `align_local.ecc_refine` exists, is **dead code** — focus path only uses ORB→`estimateAffinePartial2D` (3px RANSAC); ORB is weak on the defocused stack ends | Add ECC refine as 2nd stage after the feature estimate | 🔴 S |
| F2 | **Focus breathing not modeled** | Magnification drift handled as a free, regularized scale over the stack | Per-frame scale from features only, noisy at stack ends; `align_sequential` even chains the error | Estimate per-frame scale, then smooth/fit monotonically over the sequence | 🔴 M |
| F3 | **Pyramid halo is reactive, not structural** | PMax = cross-scale-consistent coefficient selection (dampens halos *before* mixing) | Naive per-level `argmax(|Laplace|)`; `halofix` only clamps the amplitude afterwards | Couple selection index across pyramid levels (coarse guides fine) | 🟠 M |
| F4 | **Depth map has no spatial regularization** | Helicon B/Zerene DMap regularize the "which frame" map over neighborhoods (+order prior) | `focus_stack_depthmap` is per-pixel; `color_reassign` only median-blurs the index | Edge-aware smoothing of the index (guided/joint-bilateral with image as guide) | 🟠 M |
| F5 | Pyramid selector is noise-amplifying; median deghost is crude | Window-based contrast (SML/Tenengrad), frame-based retouch | `|Laplace|` per pixel can let a noisy pixel "win"; deghost = global median (kills sharpness) | Window-averaged energy in the selector; deghost = sharpest consistent frame | 🟠 S |

**On par / better:** method coverage, `halofix` (pixel-envelope clamp — no standard tool ships this as auto),
`color_reassign`, `align_on_subject` (saturation anchor for wind-blown macros — original), `crop_to_overlap`,
memory-streaming + tree-merge.

---

## 🌌 Astro stacking — vs PixInsight / Siril / APP

Registration scaffold, real variable-pixel drizzle, Winsor/LinearFit rejection, MTF/GHS, RL deconv, real
3-tier SPCC — all genuinely good for OpenCV-only. The gaps are concentrated and high-value.

| # | Gap | Pro tool | ForgePix | Fix | I/E |
|---|---|---|---|---|---|
| A1 | **No luminance noise reduction** | MultiscaleLinearTransform (per-scale k·σ wavelet NR); NoiseXTerminator (ML) | Only `denoise_chroma` (a chroma Gaussian blur). Luminance noise is pulled up unchecked by the stretch | à-trous wavelet NR on luminance (MAD σ per level, soft-threshold). `wavelet.py` already has the building block | 🔴 M |
| A2 | **Background = lowpass blur, not sampled surface** | DBE/ABE/GraXpert: auto sample points in star-free regions → robust 2D polynomial/RBF surface | `background_extract` = median+big Gaussian blur → a pure lowpass that **eats extended nebula** (IFN, M31 halo, Hα) | Tile → robust per-tile sample → σ-clip stars → `RBFInterpolator` (TPS) surface. The RBF is already used in `_tps_refine` | 🔴 S–M |
| A3 | **Star matching is translation-centric** | Triangle/asterism similarity matching (scale/rot/mirror invariant) | `_coarse_offset_vote` votes on pure translation; breaks on big field rotation / mosaic / mixed optics | Triangle hashing (k-NN triangles, invariant side ratios, cKDTree vote) — what astroalign does | 🔴 M |
| A4 | **No per-frame SNR weighting + non-iterative sigma** | Noise/SNR weights per frame; iterative Winsor | All frames equal-weighted; σ estimated in 1 pass (contaminated by the outliers it should reject) | Weight = 1/σ_bg²; iterate sigma 1–2× | 🟠 S |
| A5 | **Deconv: no regularization/deringing, stationary PSF** | Regularized RL + local deringing support; BlurXTerminator (ML, non-stationary) | Bare RL, one global PSF, brightness-gate star protect | TV/wavelet-regularized RL + deringing support mask; tiled PSF | 🟠 M |
| A6 | **No real star-removal layer** | StarXTerminator/StarNet (ML) → starless nebula for SHO | `_star_desat` only desaturates; no starless image | Morphological star-removal (partial; large stars need ML) | 🟠 L |

**On par:** registration scaffold (voting+RANSAC+sub-pixel+TPS+cluster-rescue), real variable-pixel drizzle,
stretch family (MTF/GHS/asinh), real catalog SPCC via Siril/Gaia, Winsor/LinearFit rejection.
**Out of reach (ML):** BlurXT/NoiseXT/StarXT — classical equivalents reach "good PixInsight ~2015", not today's ML.

---

## 🪐 Lucky imaging — vs AutoStakkert! / RegiStax / PSS

Architecture is right (now incl. feature-homography auto-align + wavelet sharpen). Gaps:

| # | Gap | Pro tool | ForgePix | Fix | I/E |
|---|---|---|---|---|---|
| L1 | **No drizzle / super-resolution** | AS! 1.5×/3× drizzle (sub-pixel jitter fills the high-res grid); on-the-fly drizzle-debayer | Sub-pixel shifts measured then **thrown away** (resample on input grid) | Accumulate onto a 1.5×/3× grid with a drop kernel | 🔴 L |
| L2 | **Reference not iteratively refined** | Quality-weighted ref from best ~50%; optional "use last stack as reference" 2nd pass | `lucky_stack` ref = single sharpest frame (geometric bias); MAP matches against soft mean → localisation bias | Ref from top-N; 2nd MAP pass against the sharpened result | 🔴 M |
| L3 | **Quality metric raw** | Brightness-normalized, LoG with noise param | `Laplacian.var` on raw uint8 (noise²-driven, no brightness norm) | Light blur + brightness-normalize the score | 🔴 S |
| L4 | **AP grid rigid, single-scale** | Adaptive AP size/density on structure; multi-scale | Fixed `ap_step`/patch sizes, one scale | Derive AP density/size from the contrast map; 2 scales | 🟠 M |
| L5 | **No derotation; mean (not sigma-clip) patch stack** | WinJUPOS derotation; outlier-robust patch combine | No derotation (caps Jupiter seq length); `patch_acc` is a plain mean → one bad match pulls the AP | Sigma-clip/median the patch stack (code exists!); derotation later | 🔴(clip) S |

**On par / better:** feature-homography auto-align actually beats AS! for handheld/panning (AS! assumes a fixed
mount). Biggest single visible deficit vs AS! = **no drizzle**.

---

## 📷 HDR & 🌠 Long exposure — vs Photomatix/Aurora/Lightroom · Sequator/StarStaX

Exposure Fusion (Mertens) is on par with / better than Lightroom for the natural case. Gaps:

| # | Gap | Pro tool | ForgePix | Fix | I/E |
|---|---|---|---|---|---|
| H1 | **No true star-point stacking (field rotation)** | Sequator: region-local star registration compensating field rotation → stacks point stars | longexp only does Lighten/Max (trails); `align` is global-rigid, no field rotation; sky never star-registered | New `stars_point` mode: detect stars in sky mask, per-frame affine/homography, average-stack | 🔴 L |
| H2 | **Tonemapping only global operators** | Photomatix Details Enhancer = local-adaptive | `merge_radiance` = Reinhard/Drago/Mantiuk global; `apply_look` only unsharp+CLAHE | Durand 2002 bilateral base/detail local tonemap (`cv2.bilateralFilter`/guidedFilter) | 🔴 M |
| H3 | **Deghosting = simple brightness diff mask** | Reference replacement / optical-flow warp | `_deghost` raw-RGB diff + hard threshold; loses HDR benefit in motion zones | Gradient-space diff + adaptive (Otsu/MAD) threshold; optional Farneback warp | 🔴 M |
| H4 | **Sky detection variance-only** | Sequator: motion + spatial coherence + interpolation | `_auto_sky_mask` temporal variance only — fails on wind-blown foreground / tracked mounts | Couple with spatial constraint (largest connected component above horizon) | 🟠 S |
| H5 | **Noise: trails/comet/bright unhandled; `bright` max-normalize is hotpixel-fragile** | Sequator adaptive NR, separate sky/ground √N | sigma_clip only for smooth/declutter; `bright` ÷max → one hot pixel darkens everything | Percentile (99.5%) normalize; hotpixel reject before max | 🟠 S |

**On par:** Mertens fusion (= modern "natural" HDR), star trails (= StarStaX, minus end-to-end interpolation),
declutter median, virtual-exposure blend (original).

---

## 🌐 Panorama — vs Hugin / PTGui

Blending (GraphCut + MultiBand) is on par — no gap there. The whole deficit is **optimization**.

| # | Gap | Pro tool | ForgePix | Fix | I/E |
|---|---|---|---|---|---|
| P1 | **BA optimizes no lens distortion (a/b/c)** | Hugin/PTGui self-calibrate radial distortion + R + f in one LM over all control points | `BundleAdjusterRay` optimizes only rotation + focal; no distortion term anywhere | Own `scipy.optimize.least_squares` BA over [R_i, f, a, b, c] | 🔴 L |
| P2 | **No photometric optimization** | Vignette polynomial + exposure + WB + EMoR response | Only `GAIN_BLOCKS` brightness gain; no real vignette/WB/response | scipy fit of vignette `1+Vb·r²+Vc·r⁴` + exposure offsets, de-vignette before warp | 🔴 M |
| P3 | **`WAVE_CORRECT_HORIZ` hardwired; no projection auto-select** | HORIZ+VERT, projection chosen by FOV, multi-row | Single-row assumption baked in — a real bug for grid (Moon) mosaics | `WAVE_CORRECT_AUTO`; pick projection from estimated FOV | 🟠 S |
| P4 | **Manual control points only 2-image** | Manual points feed the same N-image solver | `stitch_from_points` = single homography, 2 images only | Feed manual points into the N-image BA | 🟠 M |
| P5 | **No include/exclude masks** | Per-image masks; seam finder respects them | Input masks hardwired to 255 | Optional per-image mask param | 🟠 S |

**On par:** seam finding + multi-band blending (= enblend class).

---

## 🖼️ RAW develop — vs RawTherapee / darktable

ForgePix is a faithful developer + editor by design — but one gap is fundamental.

| # | Gap | Pro tool | ForgePix | Fix | I/E |
|---|---|---|---|---|---|
| R1 | **No color management — everything in sRGB-gamma BGR** | Demosaic→linear→camera matrix/DCP→wide working space→edit→output ICC | Forces `output_color=sRGB`; entire editor edits in sRGB-gamma BGR; ICC tag copied but never applied | rawpy linear out + camera matrix (`raw.rgb_xyz_matrix`) → edit in linear working space | 🔴 L |
| R2 | **No scene-referred tonemapping (filmic/sigmoid)** | darktable filmic/sigmoid; hue/sat preserving highlight rolloff | `2^EV` mul + sigmoid contrast; no controlled highlight compression | Filmic-style luminance curve, ratio-preserving chroma (needs R1) | 🔴 M |
| R3 | **Capture sharpening (deconv) not wired to RAW editor** | RT Capture Sharpening = RL deconv vs capture blur | RL exists only in `astro.deconvolve`; photo editor only unsharp/wavelet | Reuse the RL loop with a generic Gaussian PSF + highlight protect | 🟠 S |
| R4 | **Denoise not profiled / not chroma-separated; `fast_denoise` loses 16-bit** | darktable profiled denoise (Anscombe+NLM/wavelet), luma/chroma | NLM over uint8 (depth loss); wavelet denoise luminance-only | Wavelet denoise on Lab a/b; ISO-scaled threshold from EXIF | 🟠 M |
| R5 | **Parametric masks missing; demosaic capped** | Param masks (by L/color) in every module; AMaZE/RCD/LMMSE | Only drawn/geometric masks; AMaZE needs GPL LibRaw (silent AHD fallback) | Parametric masks (trivial in NumPy) on all modules; demosaic = build/dep issue | 🟠 S(masks)/L(demosaic) |
| R6 | **No dehaze** | Dark-channel-prior dehaze | absent | Dark-channel prior (~40 lines; guided filter already present) | ⚪ S |

**On par:** à-trous sharpening, multi-scale local contrast, lensfun lens corrections, PCHIP curves, guided masks.

---

## Synthesis — what actually separates ForgePix from the pros

**Cheap, high-impact quick-wins (do first):**
1. **Wire `align_local` ECC into the focus path** (F1) — built, dead. 🔴 S.
2. **Astro luminance wavelet NR** (A1) — the single most visible astro quality gap. 🔴 M.
3. **Astro sampled RBF background** (A2) — stop eating nebula; RBF already present. 🔴 S–M.
4. **Astro per-frame SNR weighting + iterative sigma** (A4). 🟠 S.
5. **Lucky: brightness-normalized quality metric + sigma-clip patch stack** (L3, L5). 🔴 S.
6. **Panorama `WAVE_CORRECT_AUTO`** (P3) — a real multi-row bug. 🟠 S.
7. **RAW: wire RL capture-sharpening + dark-channel dehaze** (R3, R6) — engines already exist. 🟠 S.
8. **HDR: percentile-normalize `bright`, gradient+adaptive deghost** (H5, H3). 🟠 S.

**Big, genuinely hard (separate projects):**
- RAW **color management** (R1) — the one "faithful developer" claim that color management would actually back up.
- Lucky **drizzle/super-resolution** (L1) — the biggest visible planetary deficit.
- Panorama **distortion + photometric BA** (P1, P2) — needs an own scipy LM solver.
- HDR **true star-point field-rotation stacking** (H1) — Sequator's signature.
- ML-only: BlurXT/NoiseXT/StarXT, AMaZE/RCD demosaic (GPL build).
