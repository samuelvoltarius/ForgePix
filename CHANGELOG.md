# Changelog

*[🇩🇪 Deutsche Version](CHANGELOG.de.md)*

All notable changes to ForgePix. Format based on
[Keep a Changelog](https://keepachangelog.com/), versioning per
[SemVer](https://semver.org/).

## [1.20.0] – 2026-07-13
### Pro-tool parity wave — every module upgraded (researched against Helicon/Zerene, AutoStakkert/PSS, Siril/PixInsight, Photomatix/Sequator/Hugin, RawTherapee/darktable)
The recurring cross-cutting insight — **local (non-rigid) alignment** — plus the highest-impact
technique from each pro tool, implemented in pure OpenCV/NumPy. See `docs/ROADMAP.md`.
- **Local alignment foundation (`core/align_local.py`):** ECC sub-pixel refine (brightness-invariant)
  + capped dense optical-flow warp — shared building block.
- **Lucky imaging — real multi-point (MAP):** alignment-point grid, per-region best-frame selection +
  sub-pixel local shift, seamless Hann blend (`lucky_stack_map`). Always also saves the sharpest single
  frame. (Honest: on featureless/low-res discs the single frame can still win; MAP shines on detailed
  Moon/planet targets.)
- **Wavelet sharpening (`core/wavelet.py`):** à-trous multi-scale boost + denoise (RegiStax-style),
  colour-faithful. Shared by lucky/astro/editor.
- **Astro:** local normalization before rejection (`--astro-local-norm`, against gradients/multi-session)
  + MTF/histogram stretch (`--astro-stretch-mode mtf`, PixInsight AutoSTF-style, reversible).
- **HDR:** deghosting (`--hdr-deghost`, motion-masked reference fusion — no more ghosted leaves/people).
- **Long exposure:** comet mode + star-trail gap-fill (`--longexp-gapfill`).
- **Panorama:** explicit `cv2.detail` pipeline (projection, exposure compensation, GraphCut seams,
  MultiBand blending) replacing the black-box stitcher, with fallback.
- **RAW editor (`core/develop.py`):** highlight reconstruction (`--raw-highlights`), demosaic choice
  (`--raw-demosaic`), tone curves (PCHIP), NLM denoise, local-adjustment masks.
- **Focus stacking:** Method A (weighted average) + wavelet merge with consistency vote + colour
  reassignment (`--focus-method average|wavelet`).
- All wired into CLI + GUI, bilingual, +13 tests (83 total green).

## [1.19.3] – 2026-07-12
### Focus map reads better (only colour the sharp areas)
- The focus-origin map used to show colourful **random noise** in **flat/out-of-focus areas**
  (e.g. bokeh background) — there is no real "sharpest" frame there. Such areas are now left
  **neutral grey** (confidence from the absolute tile sharpness); only areas with real **sharp
  edges/detail** get coloured. The subject's shape is readable at a glance.
  (`focus_analysis.focus_map(mask_flat=True)`, on by default)

## [1.19.2] – 2026-07-11
### Camera-Raw editor everywhere + HDR classified correctly
- **"Edit" (Camera Raw) now works everywhere:** always enabled, and with no run result it opens a
  file dialog for **any image — including RAW** (developed faithfully). HDR results land in the
  `stack/` folder like everything else, so they are directly editable.
- **HDR mode classified correctly:** `is_hdr` is no longer mistaken for "macro" — the focus map and
  retouch tools (both for focus stacking) no longer appear in HDR mode.

## [1.19.1] – 2026-07-11
### HDR looks (presets against the flat fusion look)
- Exposure Fusion (Mertens) looks **flat** by nature — new **tone-look presets** add pop, faithfully
  (tones only, no invented content): `--hdr-look {neutral,natural,vivid,dramatic}` or the GUI "Look"
  selector in HDR mode. **Default = `natural`** (subtle contrast/pop) so HDRs no longer come out flat.
  `vivid` is stronger, `dramatic` adds strong local contrast (CLAHE, clouds/structure), `neutral`
  leaves the raw fusion result. Done in LAB space: black point, contrast S-curve (sigmoid), clarity
  (local contrast), saturation. (`hdr.apply_look`)

## [1.19.0] – 2026-07-10
### New — 📸 HDR module (Exposure Fusion) + more robust focus alignment
- **HDR from exposure brackets (`core/hdr.py`, mode "📸 HDR"/`--hdr`):** Merges AEB brackets
  (e.g. −1/0/+1 EV) via **Mertens Exposure Fusion** into a well-balanced image — highlights from the
  darker, shadows from the brighter frames, with no tonemapping artefacts and without needing exposure
  times. **Multiple brackets** in one folder are detected automatically (`--hdr-bracket` for a fixed
  group size) and merged individually. **Handheld brackets are feature-aligned (rigid) before fusion**
  → no ghosting. Made clear in the UI: HDR ≠ focus stacking.
- **Pairwise/sequential alignment (`--align-sequential`, GUI "Pairwise align"):** Aligns each frame to
  its **direct neighbour** (2→1, 3→2, …) and accumulates the transforms — instead of all to one global
  reference. Neighbouring frames are nearly identical → very robust estimate. For deep tripod series
  with a large focus range, it makes the difference between "holds" and "breaks".
- **Hierarchical tree merge (`--merge tree`, GUI "Tree merge"):** Merges pairwise (1+2, 3+4, …) and the
  results onward — often cleaner than merging everything flat at once with many frames.

## [1.18.8] – 2026-07-09
### Macro: moving subject + depth-map method
- **Moving subject (subject alignment):** New option "Moving subject (align on the subject)"
  (Alignment group) or `--moving-subject`. For subjects that drift slightly during the focus series
  (a flower in the wind, an insect), the photos are aligned **on the subject** instead of the whole
  frame; shots where the subject moved too far are **discarded** — preventing double edges. **Auto mode
  detects** moving subjects on its own (centroid drift of colour saturation) and switches on subject
  alignment with a plain-language beginner hint (tripod/windless). The confidence display no longer
  mistakes the (intentionally) shifted, blurred background zone for ghosting.
- **Depth-map merge (Helicon "DMap" style):** New "Merge method" selection or
  `--focus-method {pyramid,depthmap}`. `depthmap` picks the **sharpest photo** per pixel
  (power-weighted, hole-free) — strong on **hard depth edges** (insects, coins, circuit boards). The
  default remains the **Laplacian pyramid**, which is clearly sharper on fine/soft structures (flowers,
  fur) in tests; the method is labelled honestly so you can pick the right one per subject.

## [1.18.7] – 2026-07-08
### Starless workflow: nebula + stars adjustable live
- StarNet runs **once**, after which **nebula boost** and **star strength** can be tuned **instantly**
  via two sliders (Astro section: "Starless: nebula / stars") — the preview updates in ~30 ms without
  StarNet recomputing (the layers are cached). So you get stars subtler or stronger, nebula flatter or
  fuller — all visible in the preview. (To be clear: the final image of course contains the stars; only
  the separate `*_nebula` file is starless.)

## [1.18.6] – 2026-07-07
### Starless workflow: stronger, core-preserving nebula boost
- The nebula boost in the starless workflow now lifts **weak/medium nebula regions noticeably**
  (asinh lift), but leaves the **already-bright core unchanged** (core mask) — so e.g. the M42
  Trapezium core does not blow out further while the outer Hα wings show visibly more structure. Plus
  local contrast + gentle saturation.

## [1.18.5] – 2026-07-06
### New — ⭐ Starless workflow (StarNet++ integration)
Fully automated "pro path" for astro: **separate stars → enhance nebula (local contrast + gentle
saturation) → screen-blend the stars back cleanly** (`1−(1−nebula)·(1−stars)`). Before that, GraXpert
(gradient) runs on the linear image, then our palette/stretch. Pulls out far more nebula structure
without bloating stars. (`core/starless.py`.)
- **Mode-dependent, always explained:** In **beginner mode** "✨ Enhance" does the full workflow
  automatically (when StarNet is present). In **pro mode** "Enhance" stays lean (GraXpert only) and the
  full workflow lives under **Tools → Starless workflow**; individual steps (StarNet only / GraXpert
  only) are there too. Every step is explained in the log.
- **StarNet++ auto-detection** already extended in v1.18.4. **macOS note** (guide + when the tool is
  missing): unblock the unsigned StarNet binary once with `xattr -dr com.apple.quarantine <folder>`.

## [1.18.4] – 2026-07-05
### Astro: polish after feedback
- **Softer auto-stretch:** black point lowered from median+0.5·MAD to **0.25·MAD** and core protection
  earlier (from 80 % instead of 85 %). Shows **more of the faint outer nebula** without lifting the
  noise; the bright core stays protected (no further blowout). Stars unchanged.
- **Palettes renamed & reordered** (clearer, sensible default order):
  **HOO — true to nature (dual-band)** · **Bicolor — warm/natural** · **Foraxx — dynamic** ·
  **SHO Gold — synthetic Hubble look**.
### External tools
- **StarNet++ auto-detection extended:** now also searches `~/siril/starnet`, `~/Documents/starnet`,
  `~/StarNet` and the Siril app folder. (Note: macOS may quarantine the unsigned StarNet binary —
  `xattr -dr com.apple.quarantine <folder>` needed once.)
- **Siril now reads OSC in colour:** during conversion the CFA is **debayered automatically**
  (`-debayer`, when BAYERPAT is in the header) — previously the Siril path produced greyscale only.

## [1.18.3] – 2026-07-04
### Cleaned up (code)
- **Dead imports removed** (pyflakes): ~18 unused imports in main_window.py/components.py (incl.
  hashlib, subprocess, unused Qt classes, unused components re-imports), one unused variable (`peaks`)
  and an f-string without a placeholder. No behaviour change.
- README screenshots updated to the current v1.18.2 state (translated UI, collapsible astro).

## [1.18.2] – 2026-07-03
### UI cleaned up + style consolidated (stabilization)
- **Astro panel decluttered:** rarely used options (engine, bias, FITS, hot/cold pixel, drizzle,
  binning) now sit in a **collapsible "Advanced" section** (collapsed by default). Common settings
  (method, kappa, alignment, dark/flat, auto-calibration, filter, palette, sessions) stay directly
  visible. New reusable `CollapsibleSection`.
- **Layout bug fixed:** two astro elements were on the same grid row (overlapping) — separated.
- **Style consolidated:** recurring inline styles (green section headers, grey hints) replaced by
  central THEME rules (`QLabel#sectionHeader`, `QLabel#hint`) — fewer magic strings, more consistent
  look.
- No behaviour change, no new features.

## [1.18.1] – 2026-07-02
### Stabilization (translations + docs)
- **English UI was half German — fixed.** About 90 visible strings were not in `tr()` (incl. the
  **entire Edit/Retouch dialog** in components.py, where `tr` was not even imported) and appeared in
  German in the English UI. All wrapped + English translations added (en.json grew noticeably). DE
  stays unchanged (key = German text).
- **i18n test tightened:** new regression guard that detects raw German UI strings (in QLabel/
  QPushButton/QCheckBox/QGroupBox/setToolTip/setWindowTitle/setPlaceholderText/_row) not in `tr()` —
  so the gap doesn't come back.
- **Manual (DE):** the dual-band/narrowband block was wrongly in the **macro** chapter; now correctly
  in the **astro** section (as in the EN guide).
- No new features — a deliberate stabilization round.

## [1.18.0] – 2026-07-01
### Faster
- **Parallel registration:** the alignment loop now uses all cores (OpenCV releases the GIL) instead
  of running serially — much faster with many frames.
- **Switch palette instantly:** a dual-band palette change (HOO/SHO/Foraxx/Bicolor) recolours the
  finished 32-bit linear image **in milliseconds**, instead of restacking everything.

### Better (result)
- **Recover widely dithered frames:** frames that won't align to the reference are rescued via a
  **cluster bridge** (sub-reference → ORB bridge → chaining) — EACH recovered frame is verified (stars
  must fall cleanly onto the reference), otherwise it stays out. (In testing: 15 → 17 of 20 frames,
  without smearing.)
- **Auto-detect calibration:** dark/flat/bias subfolders are found in the capture folder (and above)
  and applied — removes amp glow/vignetting without manual work.
- **Binning (2×/3×):** combines pixels → higher SNR, rounder/smaller stars (good for oversampled data).
- **Combine multiple nights/sessions:** "➕ Another night/session" merges several capture folders of
  the same object into ONE stack (more integration = better result).

### Easier
- **Live preview:** during stacking (astro & macro/focus) ForgePix continuously shows an intermediate
  result instead of only at the end.

### CLI
- New: `--bin {1,2,3}`, `--also <folder…>` (additional sessions), `--no-auto-calib`.

### Tests
- +3 tests (binning, calibration auto-detect). 62 green.

## [1.17.0] – 2026-06-30
### New — one-click "✨ Enhance" (GraXpert integration)
- **Enhance button in the result bar (astro/long-exposure/hybrid):** sends the finished 32-bit linear
  image through **GraXpert** with ONE click — first gradient/background extraction, then AI denoising —
  and re-imports the result automatically. The usual post-stacking step, without switching tools.
  (`tools_engine.run_graxpert_enhance`.)
- **Friendly hint instead of an error when a tool is missing:** if GraXpert (or StarNet) is not
  installed, ForgePix explains in a dialog what the tool does and where to get it **for free**
  (graxpert.com / starnetastro.com), and offers to show the finished linear image in the file manager.
  Paths under **Setup → External tools** (or auto-detection). Also applies to the individual
  GraXpert/StarNet calls in the Tools menu.
- Note: RC-Astro (BlurXTerminator/StarX/NoiseX) are proprietary AI models and can't be reproduced —
  ForgePix integrates the free tools GraXpert/StarNet.

### Tests
- +2 tests for the tool integration (hint info, clean abort without GraXpert). 59 green.

## [1.16.19] – 2026-06-29
### Fixed (astro: cyan stars neutralized, colours calmer)
- **Stars glowed bright cyan/turquoise.** In narrowband, star colour is an artefact (a dual-band filter
  passes only Hα-red + OIII-cyan → turquoise star spheres). Star desaturation previously caught only the
  brightest cores (brightness gate too high) and left the coloured **glow/halo** standing. Now: lower
  gate (also medium-bright stars) **plus dilating the mask onto the star halos** → stars become
  neutral/white, the nebula keeps its colour.
- **Saturation default 1.1 → 1.05** (CLI/GUI/AI) — calmer, more natural colours.

## [1.16.18] – 2026-06-28
### Fixed (astro: real processing instead of "comic" — round stars, less noise)
Thorough diagnosis on real IC 5146 data (dual-band, ASI294MC Pro) uncovered and fixed two serious bugs:

- **Stars were teardrop-shaped (with a ghost) — registration bug.** `cv2.phaseCorrelate` locked onto
  the **fixed pattern** (hot pixels/amp glow) in astro frames and completely missed the stars that
  **drifted over the night** (residual up to ~27 px → smeared stars). Replaced with **star-based offset
  voting** (robust against hot pixels) + RANSAC fine alignment; ORB as a fallback for large dither
  jumps. Star detection switched from Otsu (found only ~5 stars) to a **noise-adaptive MAD threshold**
  (100–200 stars). Residual now **<1 px = round stars**. Frames that can't be aligned safely (e.g. far
  dithered, little overlap) are **skipped rather than averaged in smeared**.
- **Result far too garish/noisy — stretch defaults toned down.** Black point now sits at the **robust
  sky background** (median + 0.5·MAD) instead of a fixed 0.08 % → background goes dark, noise isn't
  lifted. **Chroma denoising** (smooth colour, keep luminance sharp) kills the colourful grain. Default
  stretch 14 → **6**, saturation 1.3 → **1.1**; AI suggestion capped too (strength ≤12, saturation
  ≤1.25). GUI slider defaults adjusted.

### Tests
- +2 registration regression tests (find drift despite a fixed hot-pixel pattern; MAD star detection).
  57 green.

## [1.16.17] – 2026-06-27
### Tests & docs (dual-band palettes caught up)
- **Tests for all palettes:** previously only HOO was test-covered. Now also **SHO** (Hα→gold),
  **Foraxx** (pure Hα stays red) and **Bicolor** (synthetic green present) — 55 tests green.
- **Manual (DE/EN) updated:** the astro section described HOO only. Now the **filter selection**
  (SVBony SV220 / L-eXtreme, auto-detection) and all **four palettes** (HOO · SHO · Foraxx · Bicolor)
  are documented.

## [1.16.16] – 2026-06-27
### Added (dual-band: Bicolor palette)
- **Fourth palette "Bicolor" (Cannistra technique):** the missing channel is **synthesized** from the
  two available narrowband channels (Hα, OIII) — here the **green** as G = max(OIII, 0.5·Hα). Result: a
  more natural, warmer amber/gold, **less magenta** and more neutral stars than pure HOO. Selection now:
  **HOO · SHO (gold) · SHO Foraxx · Bicolor** — GUI dropdown + CLI `--palette hoo|sho|foraxx|bicolor`.
  As always: SII stays out (only Hα+OIII present).

## [1.16.15] – 2026-06-26
### Added (dual-band: Foraxx palette)
- **Third palette "SHO Foraxx" (dynamic):** researched (thecoldestnights.com / Foraxx method) and
  built in — the green channel is mixed depending on Hα·OIII strength: G = f·Hα + (1−f)·OIII with
  f = (Hα·OIII)^(1−Hα·OIII). So **pure Hα → red, Hα+OIII mixed → gold, pure OIII → blue** (more nuanced
  than flat SHO; pure-Hα targets stay correctly red instead of forced gold). Selection now:
  **HOO · SHO (gold) · SHO Foraxx (dynamic)** — GUI dropdown + CLI `--palette hoo|sho|foraxx`. SII stays
  synthetic (no real SII in dual-band).

## [1.16.14] – 2026-06-26
### Added (dual-band palette: synthetic SHO)
- **SHO/Hubble palette from dual-band (faked SII):** new palette choice for dual-band — **HOO**
  (red+teal, data-true) or **SHO synthetic** (Hubble gold+blue). Since dual-band has **no real SII**,
  SII is **synthesized** from Hα (common narrowband practice): Red=SII(≈Hα), Green=0.8·Hα+0.2·OIII,
  Blue=OIII → Hα regions become gold, OIII blue. Clearly labelled "synthetic, not scientific". GUI
  palette dropdown + CLI `--palette hoo|sho`. Stars stay desaturated, nebula coloured.

## [1.16.13] – 2026-06-26
### Changed (astro: filter selectable)
- **Filter selection in the astro module** instead of a simple checkbox: dropdown **"No filter /
  broadband"** vs. **"Dual-band Ha+OIII (e.g. SVBony SV220, L-eXtreme)"**. Also auto-detected from the
  FITS header. Dual-band → HOO processing (red+teal), broadband → colour calibration+SCNR. The setting
  is remembered.

## [1.16.12] – 2026-06-26
### Added / changed (astro quality)
- **Star-based registration:** for "Translation + field rotation", real **star centres** are now
  detected and matched (RANSAC affine) instead of generic image features (ORB stays fallback) — more
  accurate alignment.
- **Star desaturation in HOO:** small, high-contrast points (stars = continuum) are pulled neutral → no
  more red/teal colour fringe (Bayer R/B offset + chromatic aberration); **extended nebulae keep their
  colour** (local-contrast mask, not just brightness).
- Together with the clean Hα/OIII separation: red nebulae, neutral background, neutral stars.

## [1.16.11] – 2026-06-26
### Changed (dual-band: cleaner line separation)
- **HOO now separates Hα and OIII cleanly into two signals:** Hα from the **red** channel, OIII from
  the **blue** channel (instead of `max(G,B)` — green is most Hα-contaminated on OSC). Plus per-channel
  background subtraction + **slight linear unmixing** (Hα −= k·OIII, OIII −= k·Hα) against residual
  crosstalk. Result: purer red/teal, neutral background — clearly two tones.

## [1.16.10] – 2026-06-26
### Added (dual-band colour — HOO)
- **Dual-band is now processed as HOO:** for dual-band/narrowband (Ha+OIII) the lines are **separated**
  — Hα (red, red channel) and OIII (teal, green+blue) — **normalized individually** (so the often
  weaker OIII becomes visible) and recombined (Red=Hα, Green+Blue=OIII). Result: red Hα nebulae **and**
  teal OIII regions instead of red-dominated; stars get natural (teal/white) colours, neutral
  background. Applies automatically in dual-band mode (switch or header detection). +1 test (52).
### Note
- Hα-dominated targets (e.g. IC 5146 Cocoon) stay mostly red — that's astrophysically correct (little
  OIII). Teal shows clearly on OIII-rich targets (Cirrus, planetary nebulae).
- Star shape: rotate alignment makes stars round; a residual offset remains due to registration (a
  star-based registration as a future step would sharpen them further).

## [1.16.9] – 2026-06-26
### Added
- **Mask brush in the editor (local brightness/clarity):** in addition to the auto mask, the adjustment
  can now be **painted by hand** — **+ Add** (applies there) or **− Protect** (removes it there), soft
  edge, adjustable brush size, "Clear mask". Starts from the auto mask (if active), otherwise empty.
  Works for **astro & macro**. **Keys:** B brush on/off · A/S Add/Protect · [ ] brush size · Backspace
  clear mask. +1 test (51).

## [1.16.8] – 2026-06-26
### Changed (cleanup — project structure)
- **Engine modules moved to `core/`:** the project root now contains only the launcher
  `focus_stack_gui.py` (+ `ui/`, `core/`, `assets/`, `docs/`, `lang/`, `tests/`) instead of 13 loose
  `.py` files — clearer, less overwhelming. No behaviour change: the engine
  (astro/stacker/focus_*/longexp/mosaic/parallel/siril/tools/constants/i18n) lives in `core/`, included
  by path (`--paths core` in the build, hidden-imports unchanged). i18n still finds `lang/` (source +
  bundle), `SCRIPT` points to `core/`. 50 tests green, app + pipeline + i18n verified in source mode.

## [1.16.7] – 2026-06-26
### Added
- **Auto mask in the editor (local brightness, no painting):** new option "🎯 Auto mask: brighten only
  the subject" — exposure/clarity/levels act only on the **midtones** (nebula/subject) while the
  **bright core/stars and dark background stay protected** (soft luminance mask). Works for **astro AND
  macro**, one click — ideal for beginners. +1 test (50).
- **Dual-band filter also auto-detected:** if the filter name is in the FITS header
  (Dual/Duo/Extreme/Enhance/OIII/SHO/HOO …), green removal is switched off automatically (OIII stays).
  Otherwise the manual switch applies. So: detected WHEN in the metadata — otherwise adjustable.

## [1.16.6] – 2026-06-26
### Fixed/added (dual-band correctness)
- **Green removal no longer forced — new option "Dual-band/narrowband filter (Ha+OIII)":** with a
  dual-band filter, green is real **OIII signal** (partly lands in the green channel on OSC sensors);
  automatic SCNR green removal would have destroyed it (→ "red only"). With the switch on, NO green
  removal is done, OIII (teal) is preserved. Without a filter/broadband, SCNR stays active (removes
  green cast + green hot pixels). CLI: `--dualband`. Persisted, +i18n.
  Note: for serious dual-band/narrowband processing (HOO/SHO palette), the **linear 32-bit/FITS export
  → PixInsight/Siril/GraXpert** is the right path — that stays untouched.

## [1.16.5] – 2026-06-26
### Fixed (astro colour)
- **Green cast removed (SCNR):** the astro preview clamps green to the average of red/blue — in deep
  sky, green is practically never real signal (comes from OSC Bayer/light pollution). Also removes green
  hot-pixel/star speckles. Subtractive/faithful, runs BEFORE stretching. +1 test (49). (Residuals like
  faint amp glow/satellite trails need dark frames — calibration.)

## [1.16.4] – 2026-06-26
### Fixed (astro quality — found during the verification run)
- **Default alignment was `shift` (translation only):** on real datasets with field rotation this led
  to **elongated, colour-split stars** and a flat image (shown on IC 5146 / ASI294). The default is now
  **`rotate` (translation + field rotation)** — also corrects rotated fields and works equally for pure
  tracking. Stars become round.
- **Hot/cold pixel correction on by default:** removes the coloured single-pixel dots (Bayer/sensor hot
  pixels) that were previously visible as colour speckle.
- Astro screenshot = real IC 5146 (Cocoon Nebula) with round stars.

## [1.16.3] – 2026-06-26
### Fixed (CI)
- **tests.yml:** `psdtags` was missing from the CI dependencies → the new layered-TIFF regression test
  broke in GitHub Actions (green locally). psdtags added; the test also skips cleanly if psdtags is
  missing. CI green again.

## [1.16.2] – 2026-06-26 — Beta stabilization
### Fixed (found during the verification run)
- **Photoshop layers preserved during EXIF copy:** the built-in EXIF copy rewrote TIFFs and would have
  **flattened a layered TIFF** (losing Photoshop ImageSourceData). Such files are now detected (tag
  37724) and skipped when writing EXIF — layers are preserved. Regression test added (48 tests).
### Changed (docs)
- **README EXIF bullet clarified** (DE/EN): "EXIF/provenance is copied where possible — JPEG with EXIF,
  TIFF with core provenance, full TIFF metadata optionally via exiftool" instead of a blanket "EXIF is
  preserved".
### Verified (real data, locally on macOS)
- Macro stack (JPG series) + ghost map · export JPG/16-bit TIFF/Photoshop layered TIFF + EXIF copy ·
  Seestar FITS M 42 (GRBG, field rotation, colour) · ASI294MC FITS IC 5146 (RGGB auto-detect,
  translation, colour) · Sony ARW development (16-bit + EXIF) · streamed ghost map. AI path end-to-end
  via Spark (Qwen3.6-27B). Open: native Win/macOS launch tests (CI build only); star colour fringing on
  OSC = polish.

## [1.16.1] – 2026-06-26
### Added (astro processing: adjustable + AI)
- **Three astro sliders for the preview image — auto (AI) or manual:** **brightness** (5–30),
  **saturation** (1.0–1.6) and **colour calibration** (0–1). Default = "Processing automatic
  (AI / standard)": the AI now also detects the **colour cast** and suggests the colour calibration (in
  addition to brightness/saturation). Uncheck → set everything yourself (GUI sliders or CLI
  `--astro-bright/--astro-saturation/--astro-color`). Values are remembered.
- `astro.color_balance(strength)` is now **blendable** (0 = off … 1 = full). Affects the preview JPG
  only; linear exports stay faithful.
- +1 test (47). Folder note: build artefacts are already excluded via `.gitignore`.

## [1.16.0] – 2026-06-26
### Added / changed (astro colour & quality)
- **Debayering of OSC FITS:** colour cameras (Seestar, ZWO ASI …) deliver Bayer raw data as 2D FITS —
  previously read as greyscale (grey result). Now debayered → **real colour**.
- **Bayer pattern auto-detection:** `BAYERPAT` is read from the header; if missing, the pattern is
  **detected automatically** (tries all 4, picks the one with the fewest colour artefacts). Verified:
  GRBG (Seestar) and RGGB (ASI294MC) correctly detected from the raw data.
- **Colour calibration for the preview image:** neutralize the background per channel + balance stars
  neutral → against the red cast of OSC/LP filters, real nebula colours (blue reflection, red Ha). The
  linear exports (16/32-bit, FITS) stay faithful for GraXpert/StarNet/PixInsight.
- **Highlight/core protection when stretching:** bright areas are stretched more gently (the core stays
  structured instead of a white blob) + a slight colour boost.
- **AI suggests brightening for the finished astro image** (strength/saturation/core protection), with
  the explicit instruction NOT to brighten the core further — only the faint signal.
- +3 tests (46 total). Real M 42 stack (Seestar, field rotation, Spark AI) as 03_astro.png.

## [1.15.1] – 2026-06-26
### Fixed (critical)
- **Result display crashed:** since the modularization (v1.10.1), `ui/result_view.py` was missing the
  `IMG_EXTS` import — `_find_result`/`_show_result` threw a `NameError` after **every** run, and the
  result wasn't shown. Import added. A new regression test covers the entire display path; a pyflakes
  scan confirms: no further missing imports.
### Changed
- **Real astro screenshot:** `03_astro.png` now shows a real ForgePix stack of **M 42 (Orion)** from 49
  Seestar subs (field rotation + sigma rejection), incl. AI sub rating.

## [1.15.0] – 2026-06-26
### Added
- **EXIF in 16-bit TIFF too — without exiftool:** TIFF outputs now get core provenance (camera/model/
  date as baseline tags + a readable summary with focal length/aperture/ISO/exposure in the image
  description) embedded via `tifffile` — **pixel-identical** (read/write via tifffile, no BGR/RGB swap).
  The full per-tag EXIF sub-IFD remains the exiftool bonus (automatically preferred when present).
- **Ghost map also for large/streamed stacks:** new memory-friendly `disagreement_map_streamed()`
  (loads ONE frame at a time, online variance via Welford, downscaled + aligned). So the ghost map/AI
  retouch hint is now available in the RAM-friendly large-stack path too (previously unavailable there).
- +2 tests (42 total).

## [1.14.3] – 2026-06-26
### Added (self-contained)
- **EXIF copy without exiftool — bundled:** camera/lens/focal length/aperture/ISO/exposure are now
  **built-in** transferred onto the **JPEG outputs** (via `piexif`; source JPEG/TIFF directly or RAW via
  the core fields). So the installer needs **no** extra install for EXIF copy. exiftool is still
  **preferred** automatically when present, and remains the bonus for full metadata on 16-bit TIFF.
- `piexif` as a dependency (requirements + CI + installer bundle). +1 test (40 total).

## [1.14.2] – 2026-06-26
### Added / changed
- **EXIF reading without exiftool:** focal length/aperture/ISO/exposure (for the DOF calculator, AI
  context, module detection) are now read **built-in** via `ExifRead` (pure Python, JPEG **and** RAW) —
  exiftool is **no longer** needed for this. exiftool remains needed only to **transfer** the full
  metadata onto the output files (documented clearly). exiftool is still preferred when present;
  otherwise the fallback kicks in automatically.
- `ExifRead` as a dependency (requirements + CI + installer bundle). +2 tests (39 total).
### Repo
- GitHub topics set: focus-stacking, astrophotography, computational-photography and more (the repo
  description already correctly reads "ForgePix (Beta) …").

## [1.14.1] – 2026-06-26
### Changed (honesty/claim check + Beta)
- **Claim check of the docs:** dependencies clearly marked — **EXIF copy/"read from photo" need
  `exiftool`** (otherwise skipped), **FITS** needs `astropy` (optional, included in the installer).
  Photoshop layered TIFF and FITS were really verified (written + read back). GraXpert/StarNet++/Siril
  stay clearly described as optional + auto-detection + file fallback.
- **Privacy note** about the AI now consistent: in **Setup** (already there), **README** and **both
  guides** — only preview frames, sharpness profile, EXIF key facts, optionally the focus/ghost map and
  your wish go to the AI; **no** original files, **no** location data. A local server = nothing leaves
  the machine.
- **Beta marking:** README lead + "Beta" in the "About" dialog. Positioning: "automatic focus stacking
  and computational photography for macro, astro and long-exposure series — locally usable, AI
  optional".

## [1.14.0] – 2026-06-26
### Added (AI hints, optional)
- **Ghost map to the AI:** after stacking, the post-stack AI (polish) optionally gets the **ghost map**
  and names concrete **retouch spots** ("where is ghosting?"). The map is generated internally for this,
  even without `--ghost-map`. Appears as "AI retouch hint" in the log; without an AI server nothing
  happens.
- **Astro sub selection in plain language:** for astro the AI (if a server is present) summarizes in
  1–3 sentences **which subs are dropped and why** (clouds/guiding/FWHM/trails) — purely text-based,
  data-frugal. New pure function `astro_quality.subs_summary_text()`.
- +2 tests (37 total).

## [1.13.0] – 2026-06-26
### Added (AI context + transparency)
- **Richer AI suggestion:** the AI settings suggestion now additionally gets **EXIF key facts**
  (focal length/aperture/exposure/ISO/lens) and — for macro — the **focus-origin map as an image**. So
  the AI can spot focus gaps and judge "more shots needed?".
- **Free-text wish:** new field "Wish (optional)" in the AI section (e.g. "silky water, people sharp").
  Taken into account **verbatim** for the AI suggestion (CLI: `--wish`).
- **Transparency:** Setup shows clearly **what** goes to the AI (a few preview frames, sharpness
  profile, EXIF key facts, your wish) — **no** original files, **no** location data.
- Extension point `suggest_settings(context=…)` + `build_ai_context()`; +3 tests (35 total).
### Documentation
- **Beginner vs. pro comparison table** (who can do what, how, why, when it makes sense) in both guides
  (DE/EN).

## [1.12.0] – 2026-06-26
### Added (easier)
- **Zero-click in beginner mode:** dropping a folder on the window **starts the automatic run
  immediately** — in → done, no button at all. (Pro mode: still series analysis first.)
- **Guess the module automatically:** when dropping a folder (from the module selection), ForgePix
  guesses the right module from file types, file names and a short EXIF sample — FITS/"light/dark/flat"
  → astro, very long exposure at high ISO → astro, long exposure → long-exposure, otherwise macro.
  Preselected + justified in the log/status; the user can switch anytime. New engine function
  `focus_analysis.guess_module()` (+3 tests, 32 total).

## [1.11.0] – 2026-06-26
### Changed (speed)
- **Multi-core processing:** RAW development and sharpness analysis now run across **all CPU cores**
  (ThreadPool; rawpy/OpenCV release the GIL). The order is preserved exactly. Much faster on multi-core
  machines — most of all on RAW series.
- **Sharpness cache:** analysis results are cached per file (key = path + modification time). Repeat
  runs/"continue where you left off" skip the recomputation (~19× faster on the 2nd run in testing,
  identical results).
- **Embedded JPEG for culling:** for sharpness analysis alone, the RAW's embedded camera JPEG is used —
  if large enough — instead of fully developing (safe fallback to full development). Stack quality is
  untouched (development for the result unchanged).
- New shared `parallel.py` helper (`pmap`/`cpu_workers`) + 3 tests (29 total).

## [1.10.1] – 2026-06-26
### Fixed
- **Crash on quit made avoidable:** the update check ran as a `QThread` and could trigger a
  `qFatal`/abort when quitting quickly right after launch (thread still active during cleanup). Now runs
  as a plain Python daemon thread → that can no longer happen.
### Changed (internal modularization 2/n — no behaviour change)
- **`ui/main_window.py` slimmed from ~2340 to ~1940 lines.** Further coherent parts extracted:
  `ui/settings_io.py` (load/save settings), `ui/export.py` (quick export + export dialog),
  `ui/result_view.py` (result/preview display, view switcher, decision panel). Function and UI unchanged
  (26 tests green, offscreen rendering checked).

## [1.10.0] – 2026-06-26
### Changed (internal modularization — no behaviour change)
- **`ui/main_window.py` slimmed from ~2640 to ~2340 lines.** Coherent parts extracted into their own
  modules: `ui/theme.py` (Qt stylesheet), `ui/workers.py` (background threads + version comparison),
  `ui/welcome.py` (welcome screen & "About" dialog as a mixin), `ui/appinfo.py` (shared path/name
  constants). Eases future work; function and UI unchanged (26 tests green, identical rendering).

## [1.9.5] – 2026-06-26
### Added
- **Auto-update hint:** on launch ForgePix quietly checks the GitHub releases once and shows a subtle
  hint on the welcome screen "New version available → download" if a newer version exists. Fully
  **switchable off** (Setup → "Check for updates on start"), runs in a background thread and stays quiet
  when offline/on error. No data is sent (a pure read of the public releases API).

## [1.9.4] – 2026-06-25
### Added
- **"Continue where you left off"** on the welcome screen: a chip reloads the last used folder and
  module with one click — appears only if the folder still exists.

## [1.9.3] – 2026-06-25
### Added
- **Clickable findings** in the decision panel: a finding jumps on click to the matching view/tool —
  "Ghosting" → ghost map, "Halos" → retouch, "Focus/coverage" → focus map. The link appears only when
  the target is available. Diagnosis becomes one click to the fix.

## [1.9.2] – 2026-06-25
### Added
- **Quick-export chips** in the decision panel: 📷 Instagram · 🌐 Web · 🖨 Print as one-click right next
  to the result — exports the finished image straight into the chosen format (no dialog) and opens the
  folder. The detailed export dialog (⌘E) stays for multiple targets/layers/16-bit. Chips are active as
  soon as a result is present.

## [1.9.1] – 2026-06-25
### Added
- **"Why these settings?"** in the decision panel: the reasoning of the auto/AI (subject, suggestion,
  rationale) is captured live from the run log and shown next to the result — the software visibly
  explains *why* it decided that way.

## [1.9.0] – 2026-06-25
### Added
- **3-column layout (Lightroom style):** settings on the left · large image in the centre with a **view
  switcher** (Result / Focus map / Ghost map) + actions + filmstrip · **decision panel** on the right
  (stack confidence score, "X of Y used", findings, next steps) and log.
- **Code-signing scaffold:** the macOS build is ad-hoc signed; real Developer-ID signing + notarization
  switch on automatically once the Apple secrets are set (guide: docs/SIGNING.md).

## [1.8.1] – 2026-06-25
### Fixed (from audit)
- **AI suggestion button** launched a second GUI instead of the pipeline in the bundled binary — now
  frozen-safe (shared `_start_pipeline` helper for all subprocess launches).
- **FITS** was dead in every installer: `astropy` was missing from the build — now in build.yml +
  tests.yml.
- **macOS dock icon** (pyobjc) added in the Mac build.
- **Settings migration** from "StackForge" → "ForgePix" (old users keep paths/mode/window).
- Dead `SHINESTACKER` reference + orphaned `StackForge.iconset` removed; FITS test added (26 tests).

## [1.8.0] – 2026-06-25
### Added
- **Ready-made installers for macOS · Windows · Linux** (PyInstaller via GitHub Actions, attached to
  the release automatically) — no Python needed anymore. Download on the releases page.
- The bundled binary serves as the GUI **and** (via `--cli`) as the pipeline backend.
### Fixed
- cv2 recursion error in the bundled binary (path pollution in frozen mode).

## [1.7.0] – 2026-06-25
### Changed
- **Renamed from "StackForge" to "ForgePix"** — the old name was taken multiple times on GitHub/PyPI.
  ForgePix is verified free on PyPI and GitHub. App, icons, bundle, repo, docs all switched over.
- Folder cleaned up: outdated screenshots removed, asset files renamed.

## [1.6.0] – 2026-06-25
### Changed (photo-centric layout)
- **Image large on top, log small below** — the result gets the main area, the log is secondary.
- **Real status line** instead of a green strip: Ready · Folder loaded · Running · Analyzing · Stacking
  · Done (colour-coded, derived from the live log).
- **Larger header:** logo + "ForgePix" + subtitle "Computational Photography Suite".
- **README:** "Why ForgePix?" bullets sharpened + **image strip** (input → analysis → focus map →
  result) with real photos; screenshots updated to the new layout.

## [1.5.0] – 2026-06-25
### Changed (UX polish)
- **Welcome screen:** higher-quality cards — large icons, title, category and examples (e.g. "Products ·
  Coins · Insects · Food") + recommendation pill. **Settings & "What is this?"** already at the start
  (language/beginner-pro/AI).
- **Main window:** noticeably **larger image area** (~⅔), an empty result as a clear drag-&-drop zone,
  many buttons tidied into a **"🛠 Tools" menu** (only Before/After · Edit · Export visible).
- **Editor:** larger **histogram** and larger **image area**.
- **README** fully polished: "Why ForgePix?" section + screenshot gallery (6 views).
- **Sliders** themed (v1.4.1).

## [1.4.1] – 2026-06-25
### Fixed
- **Sliders themed throughout** (green gradient + light handle instead of Qt-default blue) — affected
  mainly the Camera-Raw editor ("Edit").
- Last purple canvas remnants (compare/curves background) switched to anthracite.

## [1.4.0] – 2026-06-25
### Changed
- **Welcome screen redesigned:** logo + tagline, tidy module cards with emoji, a short description and a
  green recommendation pill (image count), centred with a fixed maximum width.

## [1.3.0] – 2026-06-25
### Added
- **Export dialog:** target selection (Web JPG/Instagram/WhatsApp/Web/4K/Print 16-bit TIFF), output
  sharpening, JPG quality, **Photoshop layered file** and 16-bit TIFF. Visible "📦 Export" button + ⌘E.
- First public release on GitHub incl. CI (GitHub Actions) and a tests badge.
### Changed
- Welcome screen clearer ("Step 1: choose a module" + 3-step flow).
- App launcher portable (relative project directory).

## [1.2.0] – 2026-06-25
### Added
- **Photo keyboard control:** space (before/after), ← → (switch image), A/S/E/G/F/R, ⌘E (export).
  **Drag & drop:** folder onto the window → adopt it + start analysis in pro macro.
### Changed
- **Theme** to anthracite + chili green (GreenChili brand) instead of purple.
- Metric reasons when culling ("sharpness value 41 % of the series median").

## [1.1.0] – 2026-06-25
### Added
- **Keyboard shortcuts** (⌘O/⌘↩/⌘1–4/F1 …) + help dialog.
- **Test suite** (24 unittest tests, `./run_tests.sh`), incl. an i18n completeness test.
### Fixed
- None/empty guards (astro/long-exposure), timeout handling (GraXpert/StarNet/Siril), analysis in a
  background thread (GUI no longer blocks).

## [1.0.0] – 2026-06-24
### Added
- Four modules: **Macro/focus stacking, Astro, Hybrid, Long exposure** with a start selection.
- **Focus intelligence:** blur filter, series analysis, stack optimizer, DOF/bracketing assistant with
  EXIF reading, stack confidence score, focus map.
- Astro: calibration, translation/field rotation, hot pixel, drizzle, sub rating, FITS,
  GraXpert/StarNet/Siril with one click.
- Camera-Raw editor, retouch, export presets, batch/watch, DE/EN, optional AI.
