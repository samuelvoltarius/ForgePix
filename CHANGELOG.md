# Changelog

*[🇩🇪 Deutsche Version](CHANGELOG.de.md)*

All notable changes to ForgePix. Format based on
[Keep a Changelog](https://keepachangelog.com/), versioning per
[SemVer](https://semver.org/).

## [Unreleased]
### Live stacking, measurement photometry, a local Gaia catalogue — and a sourced PixInsight comparison

**Incremental live stacking** (`--live`, together with `--watch`). The previous watch mode
re-stacks the entire set for EVERY new frame: at the 200th sub it reads 200 files although
exactly one changed. Running sums are carried forward instead. Measured on real subs: **deviation
from stacking at the end 0.077 % of the image range, SNR 62.90 against 62.94**, and for a result
after every frame 2.8 s instead of 7.5 s (12 subs — the gap widens because re-stacking grows
quadratically: *n* against *n(n+1)/2* read operations). The state is saved after every sub; a
crash at three in the morning does not cost half the night. Three decisions are argued in the
code: outlier rejection only from 5 frames on (before that the running statistics are too thin),
the weight per PIXEL rather than per frame (a sub with a satellite trail should only drop out
along the trail), and a frame that cannot be aligned does NOT go into the stack unshifted — it
would double the stars.

**Measurement photometry** (`--photometrie`, `core/photometrie.py`). Aperture photometry with an
annulus background, differential against several comparison stars: variable stars, eclipses,
exoplanet transits. Checked against a known truth (40 frames over 6 h, 3 h period, 0.35 mag
amplitude, plus a transparency variation and a drifting field):

| | residual |
|---|---|
| differential against three comparison stars | **0.058 mag** |
| the same series measured raw | 0.189 mag |

The factor of 3.3 *is* the reason for the method — transparency hits every star equally and drops
out. The period came out at 2.95 h against 3.00 h. Three places where nothing is glossed over: a
**dead time axis** is detected (the test TIFFs carried no `DATE-OBS` and all shared one write
second — the light curve looked entirely normal and the period search returned 24.00 h instead of
3.00 h), **blown stars** give a systematically too-small flux and are kept out of the report file,
and **without a catalogue reference** the values are instrumental — stated in the AAVSO header AND
in the notes field of every line. No interface: choosing target and comparison stars is an expert
decision, and saying so honestly beats an interface that guesses.

**Local Gaia catalogue** (`core/gaia_lokal.py`, `--gaia-feld-laden`, PCC backend `lokal`). Colour
calibration without internet. The Gaia catalogue is **not** bundled — terabytes and its own terms
of use; instead you fetch the regions of sky you photograph once while online. Measured on
300 000 stars: **query 0.2 ms instead of 22 ms** (about 100×), file size 22 bytes per star. No
HEALPix, and for a stated reason: it would require `healpy` or `astropy_healpix` and brings
nothing at this size — declination bands with 1/cos-scaled cells do the same job. If the local
catalogue does not cover a field, the process stops cleanly instead of guessing a channel scaling
from ten stars that would look measured.
*Honest limitation:* plate solving still needs a solver; Siril and ASTAP solve offline, the
Astrometry.net route does not.

**The test found exactly the kind of defect that otherwise never surfaces:** the cell width was
computed from the declination of the INDIVIDUAL STAR rather than from its band. Two stars in the
same band therefore had different grids, and at declination 78° **six out of 21 stars went
missing** without anything failing. On top of that, the right-ascension span was computed at the
pole-farthest rather than the pole-nearest point of the circle. Every test now checks against
brute-force search for exact equality, across eight fields including the pole, the
right-ascension origin and a large radius.

**PixInsight comparison, process by process** ([docs/PIXINSIGHT.md](docs/PIXINSIGHT.md)). The
previous attempt produced a list from an aborted agent whose eleven downloaded pages were all 404
error pages — an unsourced claim. This time from the **source code**: the PixInsight Class
Library is open and every process sits there as a `…Process.cpp`. Four public mirrors enumerated,
union **91 processes**, each backed by a file. The official documentation still answers with HTTP
403 — that is stated in the document too, as is the fact that the closed modules (Deconvolution,
TGVDenoise, SCNR, StarMask, StarAlignment …) do not appear there and are therefore marked *from
knowledge*.
The three real gaps, named plainly: **PixelMath**, **general mask logic** (the building blocks
exist but only the astro steps are wired to them) and **device control**.

### Star shapes, comets, mixed exposures and a mask system

**Re-rendering star shapes** (`--astro-synthstar`). Coma at the edges, sensor tilt and tracking
errors distort the STARS while the nebulosity barely shows it. That cannot be undone by
calculation — but the stars can be put back: measure them, remove them, write them back as round
Moffat profiles carrying the same flux. On real data (M27, ASI294MC Pro, 300 s, artificial 7 px
tracking error): **distortion 0.790 → 0.388 at a total flux of 1.0000**, nebulosity untouched.
The same frame without the tracking error measures 0.420 — the result lands at the level of an
image that never had the fault. Moffat rather than Gauss, because seeing gives real stars wider
wings; Gaussian stars look like pasted-on dots.
*Honest limit, stated in the help text too:* the star shape is invented. What was a line on the
sensor becomes a round dot — unusable for photometry and astrometry.

**Comet stacking on the nucleus** (`--astro-komet`). A comet moves against the stars between
frames; aligned on the stars it becomes a streak — the very object the night outside was spent
on. Siril and most others require **clicking** the nucleus in two frames. Here the program finds
it itself: subtract the median of the star-aligned frames, look for the brightest *extended* blob
in the residual (the minimum area rules out noise spikes — a comet is diffuse), and fit a robust
straight line through the positions. Checked against a known trajectory: **nucleus found in 12 of
12 frames, residual to the line 0.33 px, largest error 1.30 px, peak brightness of the nucleus up
by a factor of 3.75.** The time axis comes from `DATE-OBS` where available — cloud breaks make the
spacing uneven. If the timestamp is missing, that is reported rather than silently using the frame
index.

**Mixed exposure times.** The obvious part is the level; the important part is outlier rejection:
without exposure information, sigma clipping compares a 60 s sub with a 300 s sub and treats the
short one as an outlier — it spends its rejection budget on the short subs and lets real artefacts
through. Measured (12 subs, a satellite in one short sub):

| | SNR | satellite residual |
|---|---|---|
| sigma without exposures | 87.0 | 0.0423 |
| sigma with exposures | 66.4 | 0.0161 |
| sigma with exposures + weighting | **85.8** | **0.0161** |

Scaling *alone* therefore costs signal-to-noise — the scaled-up short subs bring their noise with
them. That is why the pipeline switches SNR weighting on by itself once mixed exposures are
detected, rather than letting the user end up in the worse half. Uniform exposures leave the
result bit-for-bit unchanged.

*Built, measured and removed again:* DeepSkyStacker's "Entropy Weighted Average". A satellite
trail carries the highest local variance of anything in the frame and therefore receives the
highest weight. On the same series the trail then stood at **0.845 against a sky of 0.036** (sigma
with exposures: 0.013 against 0.010, i.e. essentially gone), and the sky variance rose by a factor
of **414**. The method reliably promotes exactly the artefacts that are supposed to be rejected.
The reasoning stays in the code and a test keeps the method from coming back.

**Mask system** (`core/masken.py`, `--astro-hintergrund-entrauschen`, `--astro-nebelkontrast`).
This is what really separates a fixed tool chain from PixInsight: there, every step can be applied
only where it belongs. Denoise into the background, local contrast into the nebulosity. On real
data (10 subs of M27, stacked, stretched):

| | sky noise | star peak |
|---|---|---|
| untreated | 0.0252 | 0.948 |
| denoise without mask | 0.0155 | 0.919 |
| denoise **with** mask | 0.0161 | **0.938** |
| local contrast without mask | 0.0640 | — |
| local contrast **with** mask | **0.0255** | — |

The mask costs almost nothing in effect and prevents the damage. *Honestly:* local contrast does
not help M27 even masked (0.0406 → 0.0343 inside the nebulosity) — CLAHE compresses more there
than it brings out. In this case the mask only limits the damage.

**Three defects this measuring exposed:**
- **Star detection used `cv2.subtract`**, which clips negative values to 0. That flattens half the
  noise distribution, the MAD collapses to 0 and the threshold falls back to its floor of 3/255.
  On a real sub: **MAD 0.000 instead of 10.378, threshold 3.0 instead of 51.9, 39.9 % of pixels
  flagged as star candidates instead of 4.0 %.** Invisible on linear subs, devastating on
  stretched ones.
- **Every blob from ONE pixel upwards counted as a star** (`area < 1` excluded nothing). With a
  minimum area of 4: 165 → 70 blobs linear, 8313 → 2079 stretched.
- **`synthstar` ran on the stretched image.** There the star mask covered 65 %, re-rendering cost
  27 % of the total flux and halved the sky. It now runs on the LINEAR data (mask 0.13 %, total
  flux 1.0000) **and** carries an emergency brake: above 10 % mask coverage the image is left
  alone.

*Side finding, fixed along the way:* an unknown stacking method fell **silently** into the sigma
branch. Through the library interface a typo would have quietly computed something other than
what was asked for.

### Siril and PixInsight counterparts — four small tools and two post-processing steps

**`--astro-stretch-mode ddp` — Digital Development (Okano).** The curve `y = x/(x+k)` with the
sky level `k` as its inflection point: weak signal is lifted hard, bright areas are compressed so
stars do not turn into white blobs. The honest comparison is not against the original but against
a stretch that **blows out just as much** — at 135 versus 134 blown pixels, DDP delivers **2.2x
the nebula contrast** of a gamma curve (0.18 versus 0.083). A gamma curve could not reach that
contrast at all: it peaked at 0.098 and fell again afterwards. Optionally with the unsharp mask
that belongs to the original (`--astro-ddp-schaerfe`).

**`--astro-unpurple` — purple fringing around bright stars.** Optics focus blue and red in a
different plane than green, which leaves a magenta halo. The give-away is that **both** channels
sit above green — something that essentially does not occur in real astronomical objects. That is
what the correction tests for, instead of simply damping magenta: the magenta share drops from
0.0020 to 0.0002 while a red Hα nebula in the same frame stays **unchanged to five decimal
places**. Mistaking Hα for a colour defect would have been the most expensive possible error
here.

**`--dark-skalieren` — rescale a master dark to a different exposure time/temperature.**
The trap is in the physics: dark current grows linearly with time (and doubles about every 6 °C),
but the **bias pedestal does not**. Multiplying the dark scales the pedestal along with it —
measured error 0.020, whereas `bias + (dark − bias) · factor` hits the truth **exactly**. Without
a bias frame the pedestal is estimated from the 1st percentile, which on a realistic dark (most
pixels with almost no dark current plus a tail of hot pixels) is still **35x closer** than naive
doubling (0.0006 versus 0.020). The limit is documented and pinned down by a test: with dark
current uniform across the sensor the estimate misses, and only a real bias frame helps.
When the exposure times of lights and darks do not match, the pipeline now **warns** even without
this switch — but only rescales when explicitly told to, because for the IMX294 (ASI294MC Pro)
the manufacturer explicitly advises against it.

**`astro.linear_match()` — put one image on the linear scale of another.** For two nights, two
filters, two sessions at different levels. Robust fit with iterative outlier rejection so the
line follows the background and the nebula rather than a few bright stars: mean deviation
0.130 → 0.0005, and with outliers present the robust variant is 27x more accurate than the plain
one (0.0005 versus 0.0144).

**Local contrast and edge-preserving denoise** (counterparts to the PixInsight processes
`LocalHistogramEqualization` and `TGVDenoise`). Both building blocks already existed but were
unreachable: CLAHE sat in `hdr.py` (at 0 in every preset there), the TV step only *inside*
deconvolution against ringing. Both now act on **luminance only** — otherwise the channels tilt
against each other and colour blotches appear.
- **An OpenCV trap found along the way:** `cv2.createCLAHE` **ignores `clipLimit` for 16-bit
  input**. The limit is computed as `clipLimit × tile area / histogram size`; with 65536 bins that
  falls below 1 and rounds to zero — so no clipping happens at all, just full histogram
  equalisation with the noise pulled up. Measured, `clipLimit` 1, 2, 4 and 8 produced
  **bit-identical** results (std 13337.7 for all four), versus 6.5 against 16.2 in 8-bit. Now
  luminance is equalised in 8-bit and applied as a *ratio* at full precision. On a real result
  (NGC7380): local contrast 0.183 → 0.194 / 0.209 / 0.241 / 0.274 — properly graded, where every
  step used to be identical.
- **TV denoise:** noise 0.1084 → 0.0960 (−11 %) at only −5 % local contrast, so it removes more
  noise than detail.

In the interface, purple fringing and dark rescaling live under "Advanced"; the image style sets
purple fringing along with it (off for "Natural", full for "Emphasise stars" — emphasising stars
is exactly when the fringe shows most). 17 new tests (272 → 289, all green).

### Astro pass on real data — stretching, filter knowledge, equipment
Everything below was measured on Alfred's own frames (ASI294MC Pro, 120 s, gain 121, −10 °C,
SVBONY SV220 7 nm dual-band — without darks and flats, which do not exist for this camera).

**The core finding: stars too bright and nebula too weak are THE SAME problem.**
The white point of a stretch is always set by the brightest pixels — and those are stars. The
nebula signal sat only 6 % above the sky; after normalising to the 99.9 % quantile (= a star),
the nebula was left at 3.5 % of the value range.
- **Starless stretch** (`--astro-starless-stretch`): remove the stars, stretch the nebula (which
  now sets the white point itself), bring the stars back **linearly**. Measured: nebula
  0.513 → 0.628, blown pixels 0.573 % → 0.041 %.
  Important: the star layer must **not** be stretched with the same curve — the first attempt did
  exactly that and cancelled the benefit (5.0 % of pixels above 0.8, practically as without it).
- **Colour-preserving stretch** (`--astro-color-stretch`): only the brightness runs through the
  curve, the channel ratios stay. A per-channel stretch desaturates heavily because the strongest
  channel runs towards white and everything converges to grey — saturation fell from 0.257 to
  0.075, and the stretch's own saturation control recovered only 0.108 even at 2.0.
  Colour-preserving: **saturation 0.510, cyan share 39 % → 55 %** at the same nebula brightness.

**Further fixes:**
- **Background extraction could not remove coloured gradients.** It estimated ONE greyscale
  surface and subtracted it from all three channels alike. On real dual-band data that made the
  red channel **twice as bad** (11.6 % → 24.0 %), because red sits much lower than blue. Now
  per channel: all below 0.2 %.
- **The gradient only appeared during stretching.** Both linear exports were completely flat
  (0.0 %), the finished JPG had 35.6 %. The existing correction ran only in the broadband branch —
  in the dual-band path nothing happened after the stretch. Now for both, and after a
  colour-preserving stretch by **division** instead of subtraction (the residual is multiplicative
  there): 47.4 % → 3.0 %.
- **Star desaturation drained the colour from the whole image.** The fixed 13×13 halo dilation
  merged into a blanket in star-rich fields: 1.3 % real star cores → 33 % mask → 65 % affected
  area, and saturation fell from 0.472 to 0.257. Now capped: 0.460, with stars still neutralised.
- **`winsor` barely clipped outliers.** It used the thresholds from the first, uncleaned pass — an
  outlier inflates the spread itself and ends up inside its own threshold. On the stack 16.7 % of
  a cosmic hit survived, nearly as much as a plain mean (19.6 %). With iterative refinement: 0.46 %.

**New features:**
- **Filter knowledge** (`core/filters.py`, `--filter`): 20 entries with the emission lines they
  pass, bandwidth and an unmixing starting value. Documented manufacturer figures — SVBONY SV220
  7 nm, Optolong L-eXtreme 7 nm / L-Ultimate 3 nm, Antlia ALP-T 3/5 nm, ZWO Duo-Band
  Hα 15 nm / OIII 35 nm. Detected from the FITS `FILTER` field, brand names included. Plus the
  honest statement: an SHO palette from dual-band data is synthetic, because SII was never measured.
- **Equipment maths** (`core/equipment.py`): image scale from focal length, pixel size and
  corrector — and from that the decision ForgePix used to make blind. Well sampled is 2–3 px per
  star FWHM; below that drizzle helps, above it binning. The seeing is not estimated but measured.
  Reducers/flatteners/barlows, telescope and camera presets, and all of it **user-editable** (an
  own entry with the same key replaces the preset).
- **Dither detection**: the condition under which drizzle helps at all. Previously only mentioned
  in comments.
- **Row banding** (`--astro-banding`): sensor readout offset that dark/flat/bias do not remove.
  Measured factor 4–12 reduction, the real gradient preserved.
- **Recolour blown star cores** (`--astro-unclip-stars`): recover the colour from the intact
  wings. 12 of 16 colourless cores → 0, colour error −82 %, brightness unchanged.
- **Shrink stars** (`--astro-star-reduce`), **best sub as registration reference**, **second merge
  and slabs as retouching brush sources** (`--alt-merge`, `--slabs`).

**Interface:** the astro tools are wired up — but as **one plain-language choice** (true to nature ·
emphasise nebula · emphasise stars · clean up sensor defects), not a wall of sliders. The
individual values appear only under "Advanced". If an external tool is missing, a button opens its
download page.

**What was NOT shipped although tried** — each failed on measurement:
a glow master from the median of the unregistered subs (removed 99 % of the glow but ate the
nebula: 2.2 % left), a higher ghosting threshold (blinded the detector for small ghosts), a
star-free normalisation (65 % of the image blew out), automatic slabbing (measurably pointless —
flat 59.6 versus slabs 58.9–59.1 against a target of 60.0), and framing modes (the edges were
already clean, edge noise identical to the centre).

**Honest limit:** in the 14 subs examined, Hα sits at SNR 0.75 and OIII at 0.72 — both below 1, the
signal is weaker than the noise. Real OIII regions exist, but they drown. More colour needs more
exposure time, not more computation. And without darks/flats the residual glow and vignetting stay
uncalibrated — no post-processing can replace them.

### New features — from the comparison with Zerene, Helicon and Siril
- **Best sub as the registration reference** instead of the middle one. The reference determines
  what every frame is fitted to; sub grading only removed outliers so far, not mediocrity. The
  data (FWHM, eccentricity, star count) was already being measured.
  Measured: ±0 % with comparable subs, **7 % tighter stars** when the middle sub is weak
  (48 instead of 85 stars, eccentricity 1.14 — still passing the grading).
- **Row banding removal** (`--astro-banding`). Sensor readout offset that dark/flat/bias do NOT
  remove: it differs per shot and does not average out in the stack either.
  Measured against known ground truth: banding reduced by a **factor of 4–12**, the real
  gradient preserved (left/right 0.0801/0.1510 → 0.0800/0.1508). Column banding too.
- **A second merge as a brush source** (`--alt-merge`). The standard move in Zerene/Helicon: the
  depth map keeps colours and smooth areas clean, the pyramid picks up detail in hair and
  bristles — take one as the base and paint in the strengths of the other. Computed during the
  stack, not when the dialog opens: one merge takes a measured 30 s at 24 MP × 16 frames, which
  would freeze the interface.
- **Slabbing** (`--slabs N`): partial merges over groups of neighbouring shots, also as brush
  sources ("Group 2 (shots 04-06)"). The final result deliberately stays unchanged — measurements
  show grouping brings no benefit to the automatic merge (flat 59.6, tree merge 58.7, slabs of
  3/4/6: 59.0/58.9/59.1 against a target of 60.0). The value is in the painting, not the merging.

### Fixed
- **Retouching sources only covered the start of the focus series.** The FIRST 16 frames were
  loaded — in a 150-frame series those all sit in the frontmost focus plane, so nothing in the
  rear half of the subject could be painted over. Now spread evenly across the series, at
  unchanged memory cost.

### Quality pass — measured against synthetic ground truth, not estimated
- **The stack score rated gapped focus series BETTER than complete ones.** Measured on a
  focus series built from a known sharp original: 9 gap-free frames scored 85/100 at 144 % of
  the original sharpness, 3 gapped frames scored 92/100 at only 45 %. Cause: the gap penalty
  was a flat −8 while ghosting cost −15 — yet a focus gap is the only one of those defects
  that cannot be fixed afterwards. Now proportional to the missing coverage
  (`focus_analysis.focus_gap_penalty`), and the text says what to do about it.
  After the fix: 85 vs 67 — correct ordering.
- **The ghosting heuristic asserted motion where there was none.** The measured ranges
  overlap: a completely static focus series reaches 0.00–0.81 % ghost area depending on the
  degree of defocus, a series with real motion 0.56–2.67 %. An area threshold cannot separate
  those (an attempt with a higher threshold blinded the detector for small ghosts and was
  discarded). Sensitivity is therefore unchanged, but the finding now states a possibility
  rather than a diagnosis and points at the ghost map; the penalty drops from 15 to 8. The
  measurements are recorded as a comment in the code.
- **`winsor` barely clipped outliers at all.** It used the thresholds from the first,
  uncleaned pass — but an outlier inflates the spread itself and thus ends up inside its own
  threshold. Worked through for 9× 0.06 + 1× 1.00: hi=0.859, result 133 % too bright. On a
  real stack 16.7 % of a cosmic hit survived — nearly as much as a plain mean (19.6 %).
  `winsor` now uses the same iterative threshold refinement as `sigma`: 0.46 % left (36×).

### Windows portability pass — ForgePix was practically unusable on Windows
ForgePix was built on a Mac, where paths and the console are UTF-8. On Windows the locale
code page applies (cp1252 on German systems). Every finding below was reproduced, fixed and
re-verified — none of it was inferred from reading the code.

**Images were never loaded / results silently lost:**
- **`cv2.imread` returned `None` for EVERY non-ASCII path** — even a German `Blüte_01.jpg`
  or a user folder `C:\Users\Jürgen\`. The pipeline ran with zero images and still reported
  success.
- **`cv2.imwrite` returned `True` but wrote NO file** when the target path contained an
  umlaut. ForgePix said "done" and the finished stack was gone. The most dangerous finding.
- Fix: `constants.imread`/`imwrite` read and write the bytes themselves
  (`np.fromfile`/`imdecode` and `imencode`/`tofile`); OpenCV only decodes. The originals'
  `None`/`False` semantics are preserved. 75 call sites migrated.

**The pipeline crashed on its own log output:**
- The code contains 1134 characters cp1252 cannot encode (`→` 378×, `─` 462×, `σ`, `α` …).
  Every `print` of those raised `UnicodeEncodeError` and aborted the run. Measured: `--help`
  crashed; the HDR run died on its first log line with exit code 1.
- Fix: `constants.force_utf8_stdio()` in both entry points; the GUI child process also gets
  `PYTHONIOENCODING=utf-8` (which also covers the PyInstaller binary). `constants.log_print()`
  replaces `log=print` as the default in 62 engine signatures — a log line must never abort a
  running computation.
- 15 `subprocess` calls decoded the UTF-8 output of Siril/GraXpert/exiftool with the locale
  code page (`Frühling→` arrived as `FrÃ¼hlingâ†'`) → `encoding="utf-8"` set.

**External tools were never found on Windows:**
- All four finders knew macOS paths only (`/Applications`, `/usr/local/bin`). Evidence:
  Siril 1.4.2 sat in `C:\Program Files\Siril\bin\siril-cli.exe` and `find_siril()` returned
  `None`. Windows installers typically do not add themselves to PATH.
- New: `siril_engine._windows_cands()` (Program Files, Program Files (x86),
  `%LOCALAPPDATA%\Programs`, `%ProgramData%`) for Siril, GraXpert, StarNet++ (including the
  v2.5 names) and Cosmic Clarity. Nothing changes on macOS/Linux.
- `graxpert_engine.find_cli()` had a SECOND, divergent candidate list and now delegates to
  `tools_engine.find_graxpert()` — maintaining one of them only fixed half the code.

**Being honest with the user:**
- **A run that produced nothing exited with code 0** → the GUI showed a green "Done ✓" and
  announced "Stack finished 🎉" although every frame had been culled and nothing was written.
  Now exit code 1; `--no-stack` remains an intentional success. Batch mode counts the stacks
  actually produced ("3/5" instead of "5").
- **A missing astropy produced a 20-line traceback wall.** `constants.require_astropy()` now
  states the cause, the fix (`pip install astropy`) and the reassurance (JPG/TIFF/PNG/RAW keep
  working). Four previously unguarded sites covered — including the GraXpert backend, which
  required astropy without that being documented anywhere.
- `constants.ForgePixFehler` separates expected, user-fixable errors (one plain-text line) from
  genuine program errors (full traceback for bug reports). Ctrl-C now ends with "Abgebrochen.".

**Tests:** new file `tests/test_windows_gaps.py` (16 tests). Two of the six failing tests were
test defects, not code defects: the i18n tests read UTF-8 sources without `encoding=`, and the
FITS tests reported the missing OPTIONAL astropy as a failure instead of skipping.
Before: 165 tests / 6 errors → now: 181 tests / 0 errors (6 skipped: optional deps).

## [1.27.1] – 2026-07-22
### Big cleanup/correctness pass — 4 review + 3 fix agents across the whole codebase
No new features; ~70 verified findings fixed (bugs > leaks > dead code > duplication).
All 165 tests green; GUI + pipeline verified together.

**Pipeline bugs (the silent, nasty kind):**
- **Real PCC/SPCC never ran on the default path:** a duplicate `_broadband` definition in
  `_astro_write` shadowed the Siril/Gaia path with the lite fallback — the whole three-tier
  chain (Siril SPCC → Gaia → lite) was only reachable with `--no-astro-stretch`. Fixed.
- **Bias master was accepted, reported — and never applied** (own engine). Now: without a dark,
  lights are calibrated with light−bias and the flat is bias-corrected; with a dark, no double
  subtraction.
- **Drizzle-lite only scaled the translation,** not the image content → frames sat unscaled in
  the 2× canvas. The full matrix is scaled now (matching the true-drizzle path).
- **FITS normalization used each frame's own maximum** (a hot pixel/satellite shifted whole-sub
  brightness) → fixed scale via one shared helper (`siril_engine.fits_scale01`) for
  astro/Siril/GraXpert.
- **Wavelet focus stacking had zero effect on color images** (the fusion was discarded) and
  clipped 16-bit to 255 → luma transfer + dtype-correct clipping.
- **Mosaic exposure compensation was a no-op** (applied to a discarded copy) → works now.
- **Highlight reconstruction** desaturated partially clipped pixels instead of filling them from
  intact channels (`.any` → `.all`).
- Double sharpening in `--auto`, dedup culling compared against already-removed frames, median
  stack ignored local normalization, `align_mode`/`detector` were no-op parameters (wired now,
  incl. triangle matching as fallback), star counting: nebula blobs ate the budget, one corrupt
  image aborted the whole analysis, lucky: top-N frames counted twice + ~5 GB RAM spike, HDR was
  missing from three GUI mode checks.

**GUI:**
- GraXpert/StarNet/starless ran **synchronously on the GUI thread** (beachball for up to 30 min)
  → now a background thread with live log.
- API keys were echoed in clear text into the log → masked. SSH password no longer visible in
  the process list via `sshpass -p` (now `sshpass -e`).
- Hard-coded `/tmp` (all previews broken on Windows) → `tempfile.gettempdir()`; Windows Explorer
  `/select` fixed; garbled umlauts in the live log (UTF-8 chunk buffering); extra sessions stuck
  to every astro run until app restart; preview/thumbnail cache is actually used now; Ctrl+5 +
  shortcut help for HDR.
- ~30 hard-coded dialog strings wrapped in `tr()` + 32 new English translations.

**Cleanup:**
- Dead code removed (ShineStacker relics, unused engine finders, `fast_denoise`, `refine_mask`);
  duplicates consolidated: `to_uint8()`/`luma()` (Rec. 709 instead of a 601/709 mix!) in
  `constants.py`, `write_tiff16`/`read_fits_bgr`/`find_siril` in `siril_engine`,
  `app_settings()`/`save_image()`/`_is_makro()` in the GUI.
- External tools: stale-output trap (an old run passed as the result) + return-code checks;
  temp-dir leaks (Siril bridge, SPCC) with try/finally; Cosmic Clarity no longer wipes foreign
  files from input/output; exiftool as ONE batch call instead of a process per file.
- Honesty fix: **AutoBGE/Statistical_Stretch** removed from the Siril bridge — advertised in
  1.27.0 but never callable from the app (only AberrationRemover is wired).

**Second round (the previously deferred rebuilds):**
- **One clarity implementation:** preview (GUI) and final pipeline used two different "clarity"
  algorithms → same slider value, different result. Now the multi-scale, halo-safe equalizer
  everywhere; verified: preview ≡ final result (max deviation 1/255 = quantization).
- **One decode instead of three:** the tile sharpness matrix is computed inside `analyze` —
  the blur filter and focus-coverage check no longer re-decode the series (identical culling
  verified on a synthetic series).
- **Astro stacking IO:** registered 16-bit TIFFs are read **row-wise** via memmap during
  median/linear-fit stacking (before: every file fully decoded per band — 100 frames × 20 bands
  = 2000 full reads); normalization median + SNR sigma in ONE pre-pass (was two); result
  verified bit-identical.
- **Registration: ~120× faster offset voting** (KD-tree instead of the O(n²) Python loop,
  30/30 test cases identical to the old semantics; fallback without scipy included).
- **Machine-readable status markers:** the pipeline now emits `PHASE:`/`RESULT:`/`RATIONALE:`
  (like the proven `PREVIEW:`) — the GUI's status line, result detection and "why?" panel no
  longer depend on German log phrasing (the old keyword matching remains as fallback for older
  pipeline versions).

## [1.27.0] – 2026-06-28
### Siril Python bridge, AI super-resolution, optional remote GPU — all local-first
- **Siril Python bridge** (`core/siril_pyscript.py`): runs Siril's bundled Python scripts **headless**
  (load → pyscript → save). Wired: **AberrationRemover** (AI star-shape correction, optional before
  StarNet), **AutoBGE** (background), **Statistical_Stretch**. SCUNet/DeepSNR are GUI-only → honestly
  not headless.
- **AI super-resolution** (`--upscale`, `core/superres.py`): Real-ESRGAN 2× (BSD-3, ONNX) via
  onnxruntime (CoreML/CUDA/CPU) — fully local, no external app, across modules. Graceful if
  onnxruntime/model missing. Sharpness 20→134, no artifacts.
- **GraXpert: optional remote GPU host** (e.g. DGX Spark) via `FORGEPIX_GRAXPERT_REMOTE` — only when
  configured; default and fallback are ALWAYS local (not everyone has a Spark).
- **Cosmic Clarity sharpening** slightly milder (less plastic, from VLLM feedback).
- Honest open item: GraXpert CUDA on the Spark ARM needs an onnxruntime-gpu build (pip is CPU-only);
  the local Mac path (CoreML) is the fast default.

## [1.26.0] – 2026-06-27
### Pro AI-tool chain (StarNet → GraXpert → Cosmic Clarity), correct order, robustness
External AI tools fully wired as optional backends (ForgePix stays MIT — tools are called, not bundled).
Core rule: **enhancement filters NEVER touch the stars.**
- **Starless workflow reordered:** stretch → **StarNet** (remove stars → untouched star layer) →
  **GraXpert** (background + AI denoise) → **Cosmic Clarity** (AI sharpening, free BlurXTerminator
  alternative, MIT) — all three on the STARLESS nebula only — → nebula boost → untouched stars back.
  Background pulled color-neutral (no blue/green cast). VLLM on real IC5146: **grade 1–2**.
- **GraXpert** now runs on GPU (CoreML/CUDA) and does background extraction **+** denoising by default;
  selectable astro backend (`--astro-bg-backend graxpert`).
- **Cosmic Clarity** newly integrated (`core/cosmicclarity_engine.py`, AppleSilicon CLI/MPS) + GUI path.
- **Siril** engine now also uses `subsky` (background) + `rmgreen` (SCNR), not just stacking.
- **Panorama:** `--no-autocrop` now applies here too (mosaic always cropped before).
- **Robustness:** 10 runs per module with varied settings — focus/panorama/HDR/long-exposure/astro 10/10,
  RAW 9/10 — no crashes, no black/miscolored results.

## [1.25.1] – 2026-06-27
### Verified on REAL footage (own captures) + objectively graded by a vision model — default-path bugs fixed
Every module tested on real own captures and the result graded by a vision model (instead of "by eye");
this surfaced several defects in the **default path** that are now fixed.
- **Astro – default output was BLACK:** `--astro-stretch` defaulted OFF, `color_balance` hard-clipped the
  sky to 0, and the default stretch (`asinh`) normalised to the bright stars. Now: stretch ON by default,
  neutral background pedestal, default **MTF**; asinh/ghs lift faint signal via a sky anchor (all three
  modes work). VLLM: black → **good (2-)**.
- **Astro – blue/green cast:** the aggressive stretch amplified tiny per-channel imbalances into a cast →
  exact background neutralisation before the stretch + SCNR/neutralisation after. Neutral background.
- **Astro – gradient removal** now rejects support points residually (vs a 2D trend) instead of globally.
- **HDR – fusion blue cast/flatness:** auto white balance + more bite (VLLM 4 → 2). Radiance path uses real
  EXIF exposure times + chroma denoise; local Durand tonemapping no longer overexposes.
- **Long exposure:** `suggest_mode` detects camera pan (phase correlation) and auto-aligns.
- **Panorama:** auto-crop to the largest interior rectangle (no black wedges; VLLM 4 → 1).
- **Focus stacking:** alignment borders are auto-cropped (`--no-autocrop` keeps the full frame).
- **GUI:** astro stretch default is now MTF (color-neutral), clearer labels.

## [1.25.0] – 2026-06-27
### Every remaining deep gap built — 6 parallel module agents + integration
The full `DEEP_GAPS.md` backlog implemented as real engine algorithms (one subagent per module, then
verification + fixes + CLI/GUI wiring). Pure OpenCV/NumPy/scipy. +55 tests (161 total, all green).
- **Focus:** focus-breathing correction (smoothed scale, `--focus-breathing`), cross-scale-consistent
  pyramid merge (`--focus-method pyramid-consistent`), edge-aware depth-map regularization
  (`--focus-regularize`), window-energy selector + sharpest-frame deghost.
- **Astro:** triangle/asterism star matching (rotation/mirror invariant), per-frame SNR weighting +
  iterative sigma (`--astro-weight`), regularized + deringing + tiled-PSF deconvolution
  (`--astro-deconv-regularize`), classic morphological star removal (`--astro-starless-classic`).
- **Lucky:** drizzle / super-resolution 1.5×/3× (`--lucky-drizzle`), iteratively-refined reference
  (`--lucky-refine`), adaptive alignment-point density (`--lucky-adaptive-ap`).
- **HDR / long exposure:** point-star stacking with field-rotation compensation (`--longexp-mode stars`),
  local Durand tonemapping (`--hdr-tonemap local`), gradient/adaptive + optical-flow deghosting
  (`--hdr-deghost-flow`), spatially-constrained sky mask.
- **Panorama:** own scipy bundle adjuster that self-calibrates lens distortion a/b/c, photometric
  vignette+exposure optimization, manual N-image control points, per-image include/exclude masks.
- **RAW:** real color management (camera matrix → Rec2020/ProPhoto/sRGB working space + Bradford),
  scene-referred filmic tonemapping (hue-preserving highlight rolloff), separated luma/chroma denoise
  (16-bit-faithful), parametric masks (by luminance/hue/saturation).
- Honestly not feasible: Jupiter derotation (ephemerides), AMaZE/RCD demosaic (GPL LibRaw build),
  the ML tools (BlurX/NoiseX/StarXTerminator). Panorama distortion BA and RAW color management are
  engine-ready; full pipeline-default wiring of color management is a follow-up.

## [1.24.0] – 2026-06-27
### Deep gap-closing — algorithm-level fixes from the pro-tool audit (`docs/DEEP_GAPS.md`)
A module-by-module **algorithm** audit (not feature checkboxes) found substantive gaps; the quick-wins:
- **Focus — ECC sub-pixel align was dead code:** `align_local.ecc_refine` (brightness-invariant) existed
  but was never called — the focus path only used ORB→affine, which is weak on defocused stack ends. Now
  wired as a refine stage (defocused-frame residual −39% in tests).
- **Astro — luminance noise reduction** (`--astro-denoise`): there was *no* luminance NR (only a chroma
  blur), so the stretch pulled up background noise. Multi-scale wavelet NR on the linear data (−42% bg noise
  on IC5146, nebula preserved).
- **Astro — RBF background extraction** (DBE/GraXpert principle): the old lowpass blur followed extended
  nebula and ate it; now a thin-plate-spline surface through robust sky samples (nebula samples sigma-clipped
  out). Gradient residual 0.0000 vs 0.0035.
- **Lucky — quality metric + robust patch combine:** brightness-normalized, pre-blurred sharpness score
  (was noise²-driven); per-AP **sigma-clip** + correlation-confidence rejection (one bad match no longer
  pulls the point). Plus the earlier **feature-homography auto-align** that de-streaks panning captures.
- **Panorama — `WAVE_CORRECT_AUTO`** instead of hardwired HORIZ (a real bug that warped multi-row/grid mosaics).
- **RAW — dehaze + capture sharpening:** dark-channel-prior dehaze and RL capture-sharpening (recovers real
  resolution, not just edge contrast) as editor sliders — the RL engine previously lived only in the astro path.
- **Long exposure — hotpixel-robust `bright`:** normalize to the 99.95th percentile, not max (one hot pixel
  no longer darkens the whole frame).
- `docs/DEEP_GAPS.md` documents every gap honestly, incl. the big ones left as separate projects (RAW color
  management, lucky drizzle, panorama distortion/photometric BA, true star-point field-rotation stacking, ML tools).
- +5 tests (106 total, green).

## [1.23.0] – 2026-06-27
### Closing the last comparison gaps — deconvolution, sky-mask, lucky fix, control points
The remaining 🟡/❌ items from the pro-tool scorecard, built and tested:
- **Astro — deconvolution** (`--astro-deconv`): Richardson-Lucy with a PSF estimated from the stars,
  applied to the linear master, with soft star-protection against ringing. The one missing astro
  *technique* — verified on IC5146 (tighter stars, no overshoot).
- **Long exposure — automatic sky mask** (`--longexp-freeze-auto`): separates sky (moving stars) from
  the static foreground via temporal pixel variance, instead of a fixed height split (Sequator-style).
- **Focus — paint-from-frame retouch:** the retouch editor already painted from a chosen source frame;
  the fallback now aligns those frames to the result on-the-fly, so it works without the layered file.
- **Lucky imaging — the real fix:** the MAP stack was over-smoothed because it never sharpened. Now it
  wavelet-sharpens inside `lucky_stack_map` (AutoStakkert/RegiStax principle: stack averages noise,
  sharpening restores resolution) and stacks fewer frames per point. On realistic noise, MAP+sharpen now
  **beats the single best frame** (validated against synthetic-seeing ground truth). *(Honest: needs a real
  telescope capture — static target + seeing — to shine; a panning flythrough isn't a lucky scenario.)*
- **RAW — local-contrast equalizer:** the "Clarity" slider now uses a multi-scale (halo-arm) local
  contrast equalizer (darktable/RawTherapee module) instead of a single-radius unsharp.
- **Panorama — manual control points:** `mosaic.stitch_from_points` + a `ControlPointDialog` (Tools menu)
  to stitch two tiles by hand when auto-stitch fails (homography from ≥4 user point pairs, feathered blend).
  First version for a pair; the full N-image Hugin optimizer remains a larger project.
- +6 engine tests (104 total, green).

## [1.22.1] – 2026-06-27
### Astrometry.net online plate-solving for PCC (bring-your-own key)
- The Gaia PCC path can now blind-solve via the **nova.astrometry.net online API** when no Siril/local
  solver is available — solver order is **Siril → Astrometry.net → ASTAP/solve-field**.
- **Your own API key**, supplied at runtime — **never hardcoded or committed**: GUI field under
  *Setup → External tools* (password‑masked, stored only in local app settings), `--astrometry-key`, or
  the `ASTROMETRY_API_KEY` env var. Uploads the luminance, polls the job, downloads the WCS (with the
  required `Referer` header), then runs the Gaia DR3 match as usual.

## [1.22.0] – 2026-06-27
### Real photometric color calibration (PCC/SPCC) with a three-tier fallback
PCC was upgraded from the star-based lite version to **real catalog photometry** (`core/photometric.py`),
with graceful degradation so it never hard-fails:
1. **Siril SPCC** (preferred): drives an installed Siril headless — plate-solve + Spectrophotometric
   Color Calibration against the **Gaia DR3** catalog. No extra Python deps.
2. **Own Gaia path** (MIT): plate-solve (reuses Siril's solver, or ASTAP / astrometry.net) →
   Gaia DR3 cone search via `astroquery` → match catalog stars to image stars via WCS → per-channel fit.
3. **PCC-lite** (always available): star-based neutral white balance from the image itself — no catalog,
   no network.
- `--astro-pcc-backend {auto,siril,gaia,lite}`, `--astro-oscsensor`, `--astro-narrowband`; GUI combo +
  sensor field + narrowband toggle; verified on real IC5146 subs (plate-solve + WCS confirmed; the catalog
  query needs network/Gaia access, which the sandbox blocked — the chain degrades to lite there).
- Note: AI/LLMs are deliberately **not** used for the photometry — PCC is a measurement (star colors vs
  catalog), not a judgement.
- `astroquery`/`scipy`/`lensfunpy` documented as optional deps. +4 tests (97 total, green).

## [1.21.0] – 2026-06-27
### Pro-tool gap-closing wave — every remaining 🟡/❌ scorecard item built in
Closes the last partials and open items from the pro-tool comparison (Helicon/Zerene, Siril/PixInsight/APP,
Photomatix/Lightroom, Sequator/StarStaX, Hugin/PTGui, RawTherapee/darktable). Pure OpenCV/NumPy(/scipy).
- **GraXpert/StarNet now run automatically:** fixed the LZW-TIFF bug (cv2 writes LZW by default, which
  GraXpert/StarNet's `tifffile` can't read) — inputs are rewritten uncompressed transparently, so the
  starless/gradient steps just work.
- **Astro — full GHS stretch** (`--astro-stretch-mode ghs`, `--astro-ghs-d/-b/-sp`): fully parametric
  Generalised Hyperbolic Stretch (intensity D, character b, symmetry point SP), built by numerical
  integration → guaranteed monotonic, maps [0,1]→[0,1].
- **Astro — linear-fit clipping** (`--astro-method linearfit`): PixInsight-style per-pixel line fit +
  residual rejection — better than sigma-clipping with few subs.
- **Astro — TPS local registration** (`--astro-tps`): thin-plate-spline against residual field
  distortion (wide-angle/refractor field curvature) → round stars across the whole field.
- **Astro — true drizzle** (`--astro-drizzle-true`, `--astro-pixfrac`): real variable-pixel linear
  reconstruction (inverse point-kernel with pixfrac, flux+weight accumulation) → resolution recovery
  from dithered subs, not just upscaling.
- **Astro — photometric color calibration** (`--astro-pcc`): star-based neutral white balance from many
  unsaturated stars (PCC-lite, no online catalog needed).
- **HDR — radiance-map tonemapping** (`--hdr-method radiance`, `--hdr-tonemap reinhard|mantiuk|drago`):
  Debevec radiance map + tonemapping as a dramatic alternative to Exposure Fusion.
- **Long exposure — sigma-clipping** (`--longexp-sigma`) and **freeze foreground** (`--longexp-freeze`,
  Sequator-style: sky long-exposed, ground sharp from a single frame).
- **Focus — Helicon-style Radius/Smoothing** (`--focus-radius`, `--focus-smoothing`) for depthmap/average,
  and **halo retouch** (`--focus-method halofix`): dual-output — PMax sharpness clamped to the per-pixel
  source envelope → sharpness without halo over/undershoot.
- **RAW — lens corrections** (`--lens-auto` via lensfun if installed, else `--lens-vignette/-distortion/-ca`)
  and AMaZE demosaic attempt with graceful fallback.
- All wired into CLI + GUI + i18n; +9 engine tests (93 total, green).

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
