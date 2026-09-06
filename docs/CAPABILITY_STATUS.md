# Native astrophotography capability status

Reviewed 2026-09-06 against source at `b89b504` and the evidence recorded in
[RELEASE_WORKLOG.md](RELEASE_WORKLOG.md). This is the current capability audit;
older parity checkmarks in COMPARISON, DEEP_GAPS and PIXINSIGHT documents are
historical inventories, not proof of equivalent behavior or image quality.
Rows include the 2026-09-06 native CFA Drizzle, stellar white balance, project history and own-AI refinements. Exact runtime/build evidence is recorded in RELEASE_WORKLOG.md.

The product goal remains broad native coverage of Siril, PixInsight, GraXpert and
RC Astro workflows with simpler operation. A tested Deep-Sky RC is an intermediate
milestone, not completion of that goal. No percentage of parity is established.
Function names, synthetic tests, optional third-party executables and release
version numbers do not establish parity.

## Meaning of status and evidence

- **Native**: an implementation exists inside ForgePix. Its stated limits still apply.
- **Partial**: useful native subset, incomplete user workflow or unverified fidelity.
- **External**: the functional path depends on another processing application/service.
- **Missing**: no complete native implementation found in the audited paths.
- **Research**: experiments exist; no production-qualified model is available.

**RC** means required to make the exposed Deep-Sky workflow safe and truthful.
**Next** means a high-priority addition toward the requested product scope;
**Later** means a larger scientific/advanced workflow. This ordering does not
remove those features from the user's goal. Acceptance is tracked separately in
[RC_ACCEPTANCE.md](RC_ACCEPTANCE.md).

## Import, calibration and integration

| Capability / reference workflow | ForgePix status and concrete implementation | Evidence and remaining work | Priority |
|---|---|---|---|
| FITS light selection; Siril image sequences | Native: `core/astro_input.py` detects nested series and excludes calibration FITS and JPEG companions when FITS exist. | `test_astro_release` tests nested ASIAIR files; M27 GUI run processed 34 FITS. Not every archive FITS layout is supported. | RC |
| Mono/OSC sensor input | Partial: `astro.read_calibrated` calibrates raw CFA before debayer and honors Bayer offsets; unlabeled mono remains mono. | Numerical FITS tests cover order and Bayer behavior. General FITS reader expects primary-HDU images; SCI/WHT/DQ archive cubes need explicit handling. Native FITS reading now preserves signed/out-of-range floats and uses bilinear float32 CFA interpolation; integer scaling uses the original data type. Advanced demosaicing remains open. Subsequent calibration fixes retain signed noise and divide by actual positive flat response; invalid nonpositive flat pixels fail explicitly. | RC / Next |
| Dark, flat, bias/dark-flat calibration | Partial: raw masters, finite/shape checks, FITS-first master selection, unsigned subtraction fixed. | `test_astro_release` and `test_calibration_precision` cover malformed inputs, unbiased signed subtraction and weak positive flat response. A later full M27 GUI run used a matching-header 300 s ASI294 master found under Y:/Backup/astro (2022). Dark-only calibration/export passed with preserved sources. Old-master stability, extreme negative defect pixels and missing matching flats still prevent final calibrated image-quality signoff. | RC |
| Calibration library / automatic frame compatibility | Partial: folder discovery and dimensions exist. | Known camera, gain, offset, readout mode, binning, temperature, exposure and flat-filter compatibility is now checked before master creation. Unknown metadata and changing optical sessions still need explicit validation; this is not a comprehensive calibrated-frame library. Equipment presets cannot make incompatible masters valid. | RC |
| Cosmetic correction and banding | Native: `astro.cosmetic_correct`, `fix_banding`. | `test_astro_gaps` has banding/gradient fixtures. Float32 cosmetic correction now limits replacement to isolated outliers and protects resolved structure; the synthetic PSF fixture retains flux instead of the prior 4.84% loss. Banding retains signed values. Real hot-pixel/amp-glow validation and raw CFA defect maps remain open. Neither feature substitutes for suitable darks/flats. | RC validation |
| Frame quality and reference choice | Native: `astro_quality`, star measurements and `best_reference`. | Synthetic quality regressions plus M27 retention of 31/34 frames. No broad camera/seeing benchmark or full interactive subframe review equivalence established. | RC / Next |
| Translation, rotation and triangle star matching | Native/partial: `astro.register_and_cache`, triangle fallback, affine matching and cluster rescue. | `test_astro_gaps` covers rotation/mirroring; M27 aligned 31/31 selected frames. Float32 cache and coverage sidecars now exclude reflected borders. Real GUI M27 run at a94fc60 passed with 31/31 registrations and finite exports. | RC |
| Local geometric distortion correction | Partial: `_tps_refine` uses matched stars and RBF/TPS remapping. | Code exists; the actual transform must also propagate valid coverage. No real wide-field residual/distortion benchmark establishing StarAlignment-level accuracy. | RC guard / Next validation |
| Sigma, Winsor, linear-fit, mean/median integration | Native/partial: `astro.stack` has iterative rejection and optional inverse-background-variance weights. | Synthetic outlier/SNR tests exist. Registration coverage now controls normalization, statistics and all integration methods; numerical border/float tests pass. Rejection maps and broader scientific benchmarks remain open. | RC |
| Local normalization / multi-session normalization | Partial: `local_normalize`, additive surface matching, exposure scaling. | `test_belichtungen` tests mixed exposures. Local background matching is not a demonstrated equivalent of signal-scale-aware PixInsight LocalNormalization. | Next |
| Drizzle and CFA/Bayer drizzle | Native square-drop reconstruction: original calibrated CFA samples retained, exact subpixel/affine area overlaps, Float64 sums, Float32 results, per-channel weights/coverage and 1x/2x GUI/CLI path. | Analytic and independent geometry tests plus full 34-FITS M27 run: QC kept 31, 99.9759% common RGB coverage at 1x. A three-frame 2x diagnostic had 0% common coverage; it is not a qualified image. No filling, clipping, silent shape changes or sigma rejection. No exposure normalization, WCS distortion/TPS, or CFA cosmetic/banding combination. See NATIVE_DRIZZLE.md. | Next scientific validation |
| Live stacking / restart | Partial: `livestack.LiveStack` saves accumulators and reference and rejects invalid frames/checkpoints. | `test_livestack` and `test_live_regressions` cover state/color regressions. Checkpoint v3 stores coverage counts and a configuration/master-pixel fingerprint; incompatible resume is rejected. Live linear output now retains signed/high values across checkpoint roundtrips. Rotation-option plumbing and real nightly-resume validation remain open. | RC |
| Lossless result export / original preservation | Native/partial: Astro exports linear float TIFF and optional FITS; repeated Astro exports choose new directories and mandatory write errors propagate. | `test_astro_release` simulates write failures and preserves old results. Whole-pipeline precision and output preservation in other modes are separate checks. | RC |

Siril documents calibration, alignment, integration and image/sequence support in
its [stable manual](https://siril.readthedocs.io/en/stable/). Its
[Drizzle documentation](https://siril.readthedocs.io/en/stable/preprocessing/drizzle.html)
distinguishes mono from preserved-CFA reconstruction, coverage and kernel choices.
PixInsight's own [M31 processing example](https://www.pixinsight.com/examples/M31-Ha/)
demonstrates local normalization, signal scaling and inspection of rejection maps.
These are concrete comparison targets, not results measured for ForgePix.

## Development, color and scientific calculations

| Capability / reference workflow | ForgePix status and concrete implementation | Evidence and remaining work | Priority |
|---|---|---|---|
| Sampled background correction; GraXpert / DBE | Partial native: `astro.background_extract` supports sampled RBF and subtraction/division; `own_astro.develop` uses it. | Gradient fixtures exist. Robust user-edited sample/exclusion regions and real faint-nebula preservation evidence are incomplete. Optional GraXpert bridge is external. | RC validation / Next UI |
| Stretch / histogram transfer | Native: MTF, asinh, GHS and color-preserving helpers. | Helpers and synthetic regressions exist; M27 preview still showed bright core and amp glow. A successful stack is not finished image-quality validation. | RC |
| Classical denoising | Native: wavelet and TV operations. | Numerical noise/detail tests exist. This is not evidence of NoiseXTerminator/GraXpert-AI quality. | RC validation |
| Classical deconvolution | Partial native: Richardson-Lucy, estimated PSF, TV regularization, support mask, optional tiled PSFs. | `test_astro_gaps` checks synthetic sharpening and tiled execution; real flux/ringing/aberration accuracy and GUI exposure of all controls remain to verify. | Next |
| Native plate solving, WCS refinement and annotations | Missing: `photometric` calls Siril, ASTAP, local astrometry.net or its online API. | Local Gaia storage is a catalog component, not a native solver. Build star/catalog matching, projection/distortion fitting and residual diagnostics. | Next / Later |
| Catalog-color PCC | Missing as actual catalog-color fitting. Native aperture/annulus stellar white balance is now the Auto/Lite path; optional Gaia routes select positions only. | Signed/HDR measurements, robust per-star gains, local sky planes, explicit unchanged result when references are inadequate, no automatic external solver/network. UI/CLI no longer call this catalog calibration. Known narrowband bypass remains. Numerical tests and full M27 execution; neutral-population and fixed-aperture assumptions limit accuracy. See NATIVE_STELLAR_BALANCE.md. | Next actual catalog-color implementation |
| Spectrophotometric color calibration (SPCC) | External only: `photometric.siril_spcc` launches installed Siril. | No native Gaia spectral integration with sensor QE, filter transmission and atmospheric response. An image-only white-balance fallback is not SPCC. | RC naming / Later implementation |
| Measured narrowband channel combination | Partial: H-alpha/OIII extraction and display palettes; filter guards prevent applying H-alpha assumptions to known SII/OIII data. | User SV220 SII/OIII 7 nm has a distinct profile. Native channels tool now splits RGB or estimates the two recorded dual-band lines, and composes RGB/HOO/SOO/SHO from independent mono FITS/TIFF with explicit gains, automatic star alignment and coverage. SII/OIII is estimated as R and (2G+B)/3, with no QE/crosstalk inversion. SHO requires a separate Ha input. LRGB and full spectral response separation remain incomplete. Synthetic SHO cannot recover unmeasured H-alpha or sulfur. | Next, high |
| PixelMath | Partial native: restricted floating-point AST expressions, arithmetic, comparisons, `where`, `clip`, named equal-shape images and 32-bit GUI output. | `test_pixelmath` checks arithmetic, masks, shape errors and non-finite output. It is a useful subset; no PixInsight expression compatibility, general channel indexing or geometric function library. | RC subset / Next expansion |
| Masks and selective processing | Partial: `masken` creates star/background/nebula/range masks and blends results. | Unit tests exist. No consistent editable mask/layer application and preview across all exposed processes. | Next, high |
| Native star separation/recombination | Native classical workflow: `star_layers` + float32 per-channel inpainting; signed residual and background TIFF layers, additive remix, unique output versions. The GUI no longer requires StarNet for this workflow. | Numerical reconstruction and preserved-source tests pass. Real M27 GUI separation reconstructs to maximum error 2.98e-8. Large halos/spikes and crowded fields remain partial; masks are detected, not interactively edited. No learned-separation parity claim. | Next quality validation |
| Star reduction / synthetic star replacement | Partial native: `reduce_stars`, `synthstar` with round Moffat replacements. | Shape/flux fixtures exist. Replacing star profiles is an aesthetic operation, not recovery of measured shapes or proof of BlurXTerminator equivalence. Exclude altered results from scientific photometry. | Next |
| Comet registration | Partial native: `komet` detects moving residuals and fits a track. | `test_komet` covers fixtures; faint/comet-versus-satellite ambiguities and real-series validation remain. | Later |
| Differential aperture photometry / AAVSO export | Partial native: `photometrie` uses aperture/annular background and comparison stars. | `test_photometrie` exists; instrumental measurements are not absolute standard-system photometry. Real uncertainty/calibration validation remains. | Later |
| Astrometric mosaics | Missing as a complete astronomical workflow. `mosaic` contains photographic stitching and manual control-point solvers. | Photography stitching/downconversion is not a float, WCS-aware sky mosaic with overlap flux matching and coverage. | Later |

Siril's [SPCC reference](https://siril.readthedocs.io/en/stable/processing/color-calibration/spcc.html)
requires linear input and combines Gaia DR3 spectra with sensor/filter responses.
For PixInsight, its official documentation endpoints were unavailable during this
audit; the accessible PTeam [SPCC announcement index](https://pixinsight.com/forum/index.php?forums%2Fannouncements.4%2Fpage-2=)
establishes the process's existence but is not sufficient algorithm documentation.
Do not turn an inaccessible reference or an existing process-name inventory into
a claim of all-process parity.

## AI and product workflow

| Capability / reference workflow | ForgePix status and evidence | Remaining work / priority |
|---|---|---|
| GraXpert automatic background / denoising | Own experimental local ONNX models: `core/ai_restore.py`, `training/train_restoration.py`, optional GUI and CLI. Native classical alternatives remain. | Independent real noise pairs and held-out cameras/filters; extended emission and stellar flux. Bundled reports compare against earlier own weights. No default promotion. |
| BlurXTerminator-like local aberration/deblur | Own experimental mono ONNX model trained with known elliptical blur and observed HST scene bases; classical tiled RL also exists. | Not field-dependent aberration correction. Validate varying PSFs, saturation and faint structures. No measured product parity. |
| StarXTerminator-like learned separation | Own experimental local model plus signed additive residual, Float32 export and matched GUI comparison. Real full-size M27 GUI execution verified. | Synthetic labels remain limited for dense fields, galaxies, spikes and halos. Trustworthy real targets and false-removal tests remain necessary. |
| Camera-general ML inference | Local ONNX execution selects an available GPU backend or CPU, with complete-image recovery on CPU after provider failure. Windows x64 packages include DirectML; full M27 CPU/GPU parity and actual packaged execution passed on RTX3060Ti. Four mono models process colour channels independently; background uses the whole field, other tasks overlapping tiles. Integrity checks survive verified reimport. | Camera-general quality is still unqualified. Actual larger-image tests detect tile-phase dependence. HST scene bases retain observational noise and do not provide real clean/noisy pairs. Models remain explicit experiments; acceleration is not quality qualification. A further 6,000-step mean-anchored Spark refinement passes all 27 development bias gates but fails other group gates and is rejected; no new weights are adopted. |
| Equipment and filter library | Partial native: persistent ZWO/ToupTek/QHY and generic presets; telescope/reducer values; named filter profiles; manual inputs. | Optical geometry/pixel-scale calculator, not complete manufacturers or measured QE/transmission/noise data. RC values must remain coherent; grow sourced metadata afterward. |
| Beginner flow / expert workspace | Partial: Astro-first start, beginner controls, filter/equipment dialog and expert options. | `test_astro_ui` covers control plumbing/layout cells. Full visual workflow, error recovery, keyboard usability and practical resolutions still require RC verification. |
| Reversible project history, reusable processing recipes | Native project manifest and immutable result snapshots with verified source/companion hashes, real GUI Save/Open/History and lossless snapshot export. | Saved FITS results can be reopened after restart, archive relocation is supported, missing/changed files are shown, and old snapshots survive working-file overwrite. Actual M27 GUI roundtrip tested. This is file-result history, not undo/redo, automatic recomputation or a reproducible parameter/mask graph; those remain open. | Next processing graph / recipes |
| Packaged release | In progress; tests and platform build history recorded in worklog. | One exact candidate commit must pass full tests, packaged GUI/CLI and real FITS E2E, with honest release notes. Previous-commit passes do not qualify a changed build. RC. |

GraXpert's [official source README](https://github.com/Steffenhir/GraXpert) describes
sampled interpolation, automatic AI background removal and denoising. Its
[release history](https://github.com/Steffenhir/GraXpert/releases) also contains
prerelease deconvolution work; distinguish prereleases from the release referenced
by its `latest` link. These capabilities do not imply its code or model weights
can be copied without checking their respective licenses.

RC Astro documents [locally varying PSF correction](https://www.rc-astro.com/blurxterminator-technical-manual/)
and [linear star separation](https://www.rc-astro.com/starxterminator-usage-notes/).
Its [product list](https://www.rc-astro.com/) separates deconvolution, denoising,
star removal, gradient removal and star-size adjustment. ForgePix experiments
cover some task names, but no controlled real-image benchmark establishes
equivalent accuracy, artifacts or generalization.

## Work ordering toward the full product

1. Protect actual measurements: compatible calibration, float intermediate data,
   valid registration/integration coverage, safe resume and reliable exports.
2. Complete the native daily workflow: channel-aware SII/OIII and independent SHO,
   float star layers/recombination, editable masks, reproducible process history and clear
   previews/errors. Remove scientific labels from approximations.
3. Verify the bounded Deep-Sky RC on real calibrated FITS and the exact packaged
   commit. Keep all unsupported or experimental behavior explicit.
4. Implement native astrometry, actual catalog-color/SPCC calculations, broaden CFA
   drizzle validation, WCS mosaics and measured calibration libraries as independent features
   with numerical and real-observation acceptance datasets.
5. Continue licensed-data/model research with untouched object/session/camera
   holdouts, independent noise observations and stellar/nebular preservation
   metrics. Adopt a model only when it beats the incumbent on those tests.

The source/test references above establish implementation or targeted regression
coverage. Except for the documented M27 run they do not constitute new execution
evidence, cross-product benchmark results or certification of every option.
