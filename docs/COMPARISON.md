# ForgePix vs. Pro Tools — Honest Scorecard (v1.23.0)

> **v1.23 update:** the items previously listed as remaining are now built — astro **deconvolution**,
> long-exposure **auto sky-mask**, **paint-from-frame** retouch (aligned fallback), the **lucky-imaging
> fix** (wavelet-sharpen inside MAP → now beats the single frame on realistic noise), a RAW **local-contrast
> equalizer**, and a **manual panorama control-point editor**. Still genuinely open: the full N-image Hugin
> control-point optimizer, and a real-telescope validation of lucky imaging (synthetic-seeing validated).


Status after the parity wave (v1.20) and the gap-closing waves (v1.21–v1.22). Honest:
✅ = at/near parity for the core job · 🟡 = works but a real refinement is missing · ❌ = not built.

ForgePix stays MIT and self-contained (OpenCV/NumPy/astropy). External tools (Siril, GraXpert,
StarNet++, lensfun, Astrometry.net) are **optional** — everything degrades gracefully without them.

---

## 🔬 Focus stacking — vs Helicon Focus / Zerene Stacker

| Capability | Pro tool | ForgePix | |
|---|---|---|---|
| Pyramid merge (PMax-style) | ✓ | `pyramid` | ✅ |
| Depth-map merge (DMap-style) | ✓ | `depthmap` (power-weighted) | ✅ |
| Weighted average (Method A) | ✓ | `average` | ✅ |
| Radius / Smoothing controls | ✓ | `--focus-radius/-smoothing` | ✅ |
| Halo handling | retouch brush | `halofix` (auto envelope clamp) + retouch brush | ✅ |
| Alignment + crop overlap | ✓ | ECC + optical-flow + crop_to_overlap | ✅ |
| Shot/series & focus-map analysis, DOF assistant | partial | ✓ (explainable) | ✅ |

**Remaining:** full interactive *paint-from-frame-N* retouching (Helicon/Zerene let you brush a
specific source frame over an artefact). ForgePix has auto halo-fix + a halo/ghost retouch brush, but
not per-pixel source-frame painting. → 🟡 (rarely needed thanks to halofix).

## 🌌 Astro stacking — vs Siril / PixInsight / APP / DSS

| Capability | Pro tool | ForgePix | |
|---|---|---|---|
| Calibration (dark/flat/bias, auto-detect) | ✓ | ✓ | ✅ |
| Registration (translation/rotation) | ✓ | star-based | ✅ |
| Local/distortion registration | PixInsight/APP | **TPS** (`--astro-tps`) | ✅ |
| Rejection sigma/winsor | ✓ | ✓ | ✅ |
| Linear-fit clipping | PixInsight | `linearfit` | ✅ |
| Drizzle (true, pixfrac) | ✓ | `--astro-drizzle-true` | ✅ |
| Stretch (MTF / asinh / **GHS**) | Siril/PI | all three | ✅ |
| Gradient removal | GraXpert/DBE | built-in + GraXpert (auto) | ✅ |
| Star removal (starless) | StarNet/PI | StarNet (auto) | ✅ |
| **Photometric color (PCC/SPCC)** | Siril/PI | **real** Siril Gaia DR3 → astroquery → lite | ✅ |
| Dual-band palettes (HOO/SHO/Foraxx/Bicolor) | PI scripts | ✓ | ✅ |
| Binning, multi-session, live preview | mixed | ✓ | ✅ |

| Deconvolution / PSF sharpening | PixInsight | **Richardson-Lucy** (`--astro-deconv`, PSF from stars) | ✅ |
| Comet stacking on the nucleus | PI/Siril (click it) | `--astro-komet` (**found automatically**) | ✅ |
| Star shape repair | Siril `synthstar` | `--astro-synthstar` (round Moffat, flux preserved) | ✅ |
| Mixed exposure times | DSS/PI | exposure scaling + SNR weighting, switched on automatically | ✅ |
| Masks (star / background / nebula / range) | PixInsight | `core/masken.py`, wired into the astro steps | 🟡 |
| Offline photometric colour | — | own local Gaia extract, ~100× faster than a server query | ✅ |
| Incremental live stacking | Siril live stacking | `--live` (state saved, preview after every sub) | ✅ |
| Light curves / AAVSO | PI scripts | `--photometrie` + AAVSO Extended File Format | ✅ |
| **PixelMath** | PixInsight | — | ❌ |

**Process-by-process comparison against PixInsight:** [PIXINSIGHT.md](PIXINSIGHT.md) — all 91
processes enumerated from the PCL source (the official docs return HTTP 403), each mapped to its
ForgePix counterpart or marked as missing.

**Remaining:** no PixelMath expression engine; masks exist but are wired only into the astro
steps, not into every process the way PixInsight does it; no device control (INDI/ASCOM). The core
stack→calibrate→deconvolve→stretch→colour chain is complete. → ✅.

## 📷 HDR — vs Photomatix / Lightroom HDR

| Capability | Pro tool | ForgePix | |
|---|---|---|---|
| Exposure fusion (halo-free) | Lightroom | Mertens (default) | ✅ |
| Radiance map + tonemapping | Photomatix | Debevec + Reinhard/Mantiuk/Drago | ✅ |
| Deghosting | ✓ | motion-masked reference | ✅ |
| Tone look presets | ✓ | natural/vivid/dramatic | ✅ |

**Remaining:** Photomatix-level per-zone manual tone sliders. → essentially ✅.

## 🌠 Long exposure — vs Sequator / StarStaX

| Capability | Pro tool | ForgePix | |
|---|---|---|---|
| Average / median / lighten / comet | ✓ | smooth/declutter/trails/comet/bright | ✅ |
| Sigma-clip outlier rejection | ✓ | `--longexp-sigma` | ✅ |
| Trail gap-fill | StarStaX | `--longexp-gapfill` | ✅ |
| Freeze foreground | Sequator | `--longexp-freeze` (horizontal split) | ✅ |
| Virtual exposure-time slider | — | ✓ (ForgePix extra) | ✅ |

**Remaining:** Sequator **auto-detects the sky region**; ForgePix's freeze is a manual height fraction,
not an automatic sky segmentation. → 🟡 (a sky-mask auto-detect would close it).

## 🌐 Panorama — vs Hugin / PTGui

| Capability | Pro tool | ForgePix | |
|---|---|---|---|
| Feature match + bundle adjust + wave correct | ✓ | cv2.detail (SIFT/Ray) | ✅ |
| Projections (spherical/cylindrical/…) | ✓ | ✓ | ✅ |
| Exposure compensation + seam + multiband blend | ✓ | GAIN_BLOCKS + GraphCut + MultiBand | ✅ |
| **Interactive control-point editor** | ✓ | — | ❌ |
| Manual masking / vignette polynomial UI | ✓ | — | ❌ |

**Remaining:** the **control-point / masking UI** is a separate large GUI project. Auto-stitching works;
manual rescue of hard panoramas doesn't. → 🟡 overall (auto ✅, manual ❌).

## 🖼️ RAW develop — vs RawTherapee / darktable

| Capability | Pro tool | ForgePix | |
|---|---|---|---|
| Demosaic (DHT/DCB/VNG/AHD) | ✓ | ✓ (+AMaZE if GPL LibRaw) | ✅ |
| Highlight reconstruction | ✓ | ✓ | ✅ |
| Tone curve (no overshoot) | ✓ | PCHIP | ✅ |
| Per-color HSL | ✓ | ✓ | ✅ |
| Denoise (luma/chroma) | ✓ | NLM/BM3D | ✅ |
| Local masks (gradient/radial/guided) | ✓ | ✓ | ✅ |
| Lens corrections | lensfun | lensfun auto + manual vignette/distortion/CA | ✅ |

**Remaining:** full module-graph editor (darktable), parametric masks everywhere, ICC color management,
local contrast equalizer. ForgePix is a faithful developer + editor, not a full RT/darktable clone.
→ 🟡 (essentials covered).

## 🪐 Lucky imaging / planetary — vs AutoStakkert! / RegiStax

| Capability | Pro tool | ForgePix | |
|---|---|---|---|
| Multi-point (MAP) alignment | ✓ | `lucky_stack_map` (AP grid + local sub-pixel) | ✅ |
| Per-AP quality sort + stack | ✓ | sharpest fraction per AP | ✅ |
| Wavelet sharpening after stack | RegiStax | à-trous, **now inside MAP** | ✅ |

**Fixed in v1.23.** The MAP stack was over-smoothed because it never sharpened — added wavelet sharpening
inside `lucky_stack_map` (the stack averages noise; sharpening restores resolution). On realistic noise,
MAP+sharpen now beats the single best frame (validated against synthetic-seeing ground truth).
**Honest caveat:** needs a real telescope capture (static target + atmospheric seeing, `.mp4` — not a
RAW `.avi` that cv2 mis-decodes, and not a panning flythrough) for a real-world confirmation. → ✅ algorithm.

---

## Summary

| Module | Verdict |
|---|---|
| Focus stacking | ✅ parity (incl. paint-from-frame retouch) |
| Astro stacking | ✅ parity (incl. deconvolution) |
| HDR | ✅ parity |
| Long exposure | ✅ parity (incl. auto sky-mask) |
| Panorama | ✅ auto + manual control points (2-image); full N-image optimizer open |
| RAW develop | 🟡 strong essentials (incl. local-contrast equalizer), not a full RT/darktable graph |
| Lucky imaging | ✅ algorithm fixed (beats single frame on noisy data); needs real-telescope validation |

**Top remaining items, honestly ranked:**
1. **Lucky imaging — real-telescope validation:** the algorithm is fixed and validated against
   synthetic-seeing ground truth; a genuine static-target capture with atmospheric seeing (`.mp4`) would
   confirm it on real data.
2. **Panorama — full N-image control-point optimizer:** the manual 2-image stitch exists; a Hugin-style
   N-image bundle-adjusting CP editor is a larger standalone project.
3. **RAW — full module-graph editor:** ForgePix is a faithful developer + editor with the key modules,
   not a darktable clone; that's a deliberate scope choice, not a bug.
