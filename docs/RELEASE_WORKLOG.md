# Active ForgePix release work

Latest RC work: calibration now converts integer input to float before dark
subtraction (avoids unsigned wraparound), rejects non-finite inputs/masters and
empty/non-positive-mean flats. Added numerical regression tests.

Equipment is now reachable from the main header. The dialog exposes existing
camera/telescope presets, custom pixel pitch/aperture/focal length, reducer/Barlow
factor and capture binning with persisted values and computed image scale.
This is an optical setup calculator: it does not override FITS headers or provide
sensor noise curves/calibration matching. These remain separate acceptance work.
Visually checked the dialog and tested reducer/binning geometry and persistence.

## 2026-09-06 active RC fixes

Actual M27 GUI run exposed a missing `_guess_from_folder` method in the FITS start
path. Replaced with existing `_guess_and_apply_module`; added regression coverage
for nested real FITS selection. Repeated GUI run in work/m27-rc-gui uses 34 FITS,
retains 31, registers all 31; inspect gui.log and final products before claiming
the complete run passed. This was not covered by the earlier startup-only smoke.
Completed: GUI process exit 0, 31 registered/integrated of 34 FITS, 9,300 seconds
accepted exposure. FITS and float TIFF outputs are finite; TIFF dimensions
2822 x 4144 x 3. Preview visibly retains strong right-edge amp glow without darks
and bright M27 core; successful execution is not a claim of finished image quality.
Latest local suite: 371 tests, 3 skipped. The test harness instantiated MainWindow
directly without the normal application theme; its screenshot is execution evidence,
not the release visual-design reference.

Real HST scene adaptation has completed on Spark; see training/README.md. Adapted
denoiser regressed against its parent on held-out object patches and was rejected.

Fixed overlapping Astro grid cells (advanced group versus image style, style
selector versus details toggle, duplicate filter help). Beginner mode now keeps
calibration, filter and session controls while technical options remain in Pro.
Combo boxes can shrink and labels wrap instead of forcing clipped horizontal
layouts. Added a regression test for mode switching and non-overlapping cells.

The existing packaged smoke harness now launches `--smoke-gui` before CLI
processing. It opens/closes the Astro workspace with temporary INI settings and
updates disabled, leaving user settings untouched. Source GUI/CLI smoke passed.
Full local suite before the final smoke-entry change: 370 tests, 3 skipped.
Re-run full suite and exact-commit platform builds before accepting this gate.

Updated 2026-09-05. This file is the working acceptance record. Older comparison
documents that say every Siril/PixInsight gap is closed are not release evidence.

## Product contract

Own local processing, beginner-friendly guided workflow and expert controls.
FITS light frames take precedence over JPEG previews. Original data is preserved.
Support arbitrary equipment through manual values and FITS metadata; catalogue
entries are conveniences, not a supported-camera whitelist.

## Verified progress

- Earlier live-stack colour/checkpoint/final-export fixes: commit 3e40568, with
  successful Linux, Windows and macOS CI and packaged CLI smoke tests.
- Current local changes: raw CFA calibration before debayering; monochrome FITS
  remains monochrome; float TIFF input remains linear; nested ASIAIR light-series
  detection excludes calibration frames and JPEG companions.
- Normal Astro GUI now passes calibration/cosmetic options without comet mode.
- GUI stop requests allow the live pipeline to export its final image.
- Native background/stretch/wavelet development replaces the default external
  enhancement action. Existing external starless/tool menu actions still remain.
- PixelMath arithmetic, element-wise functions and masks: restricted AST
  interpreter, finite-value/shape checks, 32-bit output, GUI entry.
- Astro-first start screen and initial theme cleanup. Full workspace redesign is
  unfinished; inline styles and overly dense beginner controls remain.
- Six camera presets added with manufacturer provenance in EQUIPMENT_SOURCES.md.
- Local Python 3.12 isolated environment: 369 tests passed, 3 skipped, before the
  latest PixelMath GUI entry. Earlier Python 3.14/PySide6 6.10.1 GUI access violation
  did not reproduce with Python 3.12/PySide6 6.11.2. Do not silently skip GUI tests.

## Real input validation

34 M27 FITS lights in F:\backup_usb_h\ASIAIR\Plan\Light\M27, ASI294MC Pro,
300 seconds each. Quality selection retained 31, registration aligned all 31:
155 minutes accepted integration. No matching calibration frames were found in
the inspected ASIAIR series. Amp glow remains a real limitation of this input.
Additional NGC6888/NGC7635 series are under Y:\Backup\astro\ASIAIR.
Do not mix validation objects/cameras into training without recording the split.

## Training

Spark SSH alias is configured locally. Remote project: ~/forgepix-training.
NAFNet architecture with retained upstream license; no downloaded weights.
baseline-001: 500 steps, synthetic validation worse than input. Not approved.
baseline-002: 10,000 steps, batch 4, 256-pixel patches; inspect report.json and
metrics.jsonl before starting another run. Synthetic-only even if scores improve.
Completed in 714 seconds: synthetic input MSE 3.7243e-5, output MSE 3.2908e-6.
Follow-up queue `~/forgepix-training/runs/multi-task-001` runs background,
isotropic deblur, starless and denoise sequentially, 10,000 steps each. Detached
queue PID at launch: 722933. Inspect logs/process state before restarting anything.
All task generators passed shape, finite-value and deterministic-seed checks on
the Spark. Background additionally passed a two-step GPU training smoke test.
No real-data training, ONNX release model or camera-generalization evidence yet.

## Next acceptance gates

The active hourly continuation now targets a Release Candidate. Use
RC_ACCEPTANCE.md as the release gate; research must not expand RC scope forever.
Expanded public FITS acquisition is implemented in training/collect_archive.py.
Inspect ~/forgepix-training/datasets/hst-diverse-001 and collection.log on Spark
before starting another collector. Limits and fixed splits are in training/README.md.

1. Review current diff; run full tests after latest UI changes and packaged GUI
   startup checks. Commit coherent tested changes before triggering release builds.
2. Finish professional workspace layout and beginner flow, visually verify both
   modes; preserve access to equipment, processing controls and export.
3. Expand verified telescope/filter/sensor metadata and calibration matching across
   session, camera, gain, readout mode, temperature, exposure, binning and filter.
4. Audit registration masks/coverage, rejection maps, drizzle and live rotation;
   prevent invalid borders from influencing integration and unsafe resume mixing.
5. Add native float star separation/recombination, reliable mask editing and
   reversible project history. Existing 8-bit inpainting is not an ML equivalent.
6. Validate native deconvolution and narrowband processing. Full native plate
   solving and spectrophotometric calibration are still open scope.
7. Build licensed FITS dataset manifests, object/camera/session holdouts and real
   metrics. Benchmark stars/flux/background bias and hallucinated structure.
8. Export accepted models to ONNX and test CPU/GPU and overlapping tiles. Do not
   enable experimental synthetic checkpoints in the application.
9. Final exact-commit CI/build/release and user-facing notes with explicit limits.

## Local verification environment

Python executable:
C:\Users\alf_a\Documents\Codex\2026-09-05\che-2\work\forgepix-py312\Scripts\python.exe

Run from F:\forgepix: `python -m unittest discover -s tests -q`.
For headless screenshots, register C:/Windows/Fonts/segoeui.ttf with QFontDatabase;
the Windows offscreen plugin otherwise rendered missing glyph boxes in this setup.

## Equipment catalogue and filter persistence (2026-09-06)
- Equipment dialog now selects and restores camera, telescope, corrector and filter alongside editable geometry. The accepted filter is transferred to the Astro processing control and saved; Cancel does not change the processing filter.
- Added generic 0.64x reducer; ASI294MC Pro + RC203/1624 computes f/5.12 while aperture stays 203 mm.
- Added manufacturer telescope presets for Sky-Watcher Esprit 100ED and Celestron EdgeHD 8. Camera presets already include ZWO, ToupTek Astro and QHY; filters include named and generic profiles. This is a curated catalogue, not exhaustive hardware coverage or measured sensor/transmission calibration.
- Validation: 5 Astro UI tests passed, including preset/filter roundtrip and reduced focal ratio.

## SV220 SII/OIII variant (2026-09-06)
Added the user's SVBONY SV220 2-inch SII/OIII 7 nm as a distinct filter profile, appended to preserve existing saved combo indices. Manufacturer: https://www.svbony.com/products/7nm-oiii-sii-narrowband-filter . Recognizes explicitly labelled 7 nm FITS headers without confusing the model with H-alpha/OIII or Antlia 3 nm. Corrected SHO validation: SII/OIII alone lacks H-alpha. Saved this filter in the local user equipment and Astro settings. Native SII/OIII-specific palette processing remains separate work; this change does not claim full SHO reconstruction. Validation: 38 equipment/filter and Astro UI tests passed.

## Filter-driven preview guard (heartbeat 2026-09-06)
Checked Spark: no training/collector process active. Latest pushed tests (7244705) and previous platform builds (2169d36) passed; these are distinct commits, so the RC exact-commit build gate remains open.
Found and fixed a further SII/OIII processing defect: filename detection or an explicit dualband flag could still route known SII/OIII data into Ha/OIII synthesis. Known filter metadata now overrides that heuristic, and the Ha/OIII renderer rejects incompatible filters. SII/OIII receives an ordinary RGB preview with an explicit processing log explanation; dedicated SII/OIII palettes remain unfinished. Linear exports are unaffected.
Validation: full local suite 377 tests passed, 3 skipped, including filename/flag precedence and renderer guard. No model promoted and no duplicate training started. RC acceptance remains incomplete.

## Calibration input integrity (heartbeat 2026-09-06 08:17 UTC)
Previous exact commit b379c05 passed tests and all platform builds (runs 34018741979 / 34018741655). No active Spark training/collector process; no duplicates started.
Reproduced and fixed calibration input defects: raw FITS NaN/Inf pixels were replaced before validation; calibration folders mixed FITS with preview JPEGs; empty selected folders silently disabled calibration; mismatched bias/flat shapes silently skipped bias correction. Raw calibration now rejects invalid/empty primary image data, prefers FITS in mixed folders, and reports empty folders and shape mismatches. Bias subtraction no longer clips an invalid flat into an apparently valid positive master before calibration validation. Original inputs are unchanged. Added disk-backed FITS regressions. RC gates still require complete compatibility metadata checks and end-to-end calibration evidence.
Validation: full local suite ran 380 tests, no failures, 3 skipped.

## Astro export preservation (heartbeat 2026-09-06 09:18 UTC)
Verified previous commit b626612 passed tests and platform builds (34021527473 / 34021527733). No Spark training/collector active.
Reproduced destructive repeat export: _astro_write deleted the existing stack directory before writing. Astro export now creates a unique sibling stack directory if the normal destination already exists, preserving existing results and any inputs stored there. Mandatory float TIFF and requested FITS write failures now propagate as errors instead of reporting success after skipping lossless exports. Disk-full regression mocks verify error propagation and original-file preservation. Other processing modes still need their separate output-directory audit; no broad preservation claim is made.
Validation: full local suite ran 381 tests, no failures, 3 skipped.

## Live state integrity (heartbeat 2026-09-06 10:18 UTC)
Previous exact commit ce8bd49 passed tests and platform builds (34024409940 / 34024409985). Spark has no active training or collector process; no duplicate jobs started.
Fixed invalid live input contaminating the entire accumulated image: empty/non-finite frames now fail before reference initialization or sum updates. Checkpoint load additionally rejects non-finite references, invalid counters/settings and negative weights/second moments. Tests reproduce both first-frame and later-frame NaN poisoning and corrupt persisted references/statistics. Validation: all 11 live-stack tests passed, including existing checkpoint roundtrips. Configuration/calibration identity for resume and registration coverage masks remain open RC work. No experimental model promoted.

## Integrated fidelity and workflow pass (2026-09-06)
- Added FITS metadata compatibility checks before master creation: camera, gain/offset, readout, binning, CFA phase, dimensions; flats also filter, darks temperature/exposure. Unknown fields remain explicitly unknown. All lights are checked against calibration. Report includes validation evidence. Intentional dark exposure scaling remains explicit; no catalogue defaults replace measured settings.
- Registered caches now retain float32 values and a required coverage sidecar; average/median/max/sigma/winsor/linearfit exclude uncovered pixels. Background normalization compares the same sky region. TPS propagates coverage. Separate drizzle path remains limited and is not equivalent to calibrated CFA drizzle.
- Live coverage excludes interpolation borders and tracks accepted counts per pixel/channel. Checkpoints v3 carry coverage and a context hash of input directory/options/master pixels; incompatible resume fails with the old checkpoint preserved. Final live RESULT now points at the actual unique export directory.
- Beginner button now forwards the selected filter. SII/OIII no longer undergoes broadband white balance/green suppression. Float exports remain RGB sensor-channel data, not decontaminated emission-line maps. Repeated export directories and MASTER LIGHT outputs are excluded from light discovery.
- Filter settings use stable keys with legacy migration; changed numeric equipment values clear mismatched preset identities. GUI actions fit two rows; long checkbox labels wrap; problematic grid cells separated. Header/Beginner/Pro visually inspected at 1280x800; advanced panels still require further review. Renamed native Gaia position-selected white balance honestly.
- New CAPABILITY_STATUS.md records native/partial/external/missing/research status against primary product documentation. Broad parity remains unfinished.
Validation: full suite 408 tests, no failures, 3 skipped. Preparing exact-commit real FITS GUI run using tests/gui_real_fits.py (isolated settings, output paths, original SHA256 checks). Public-data retry supports selecting only NGC6543 and bounded transient-query retries; acquisition is a held-out test group, not training ground truth.

## Verified GUI run and native star layers (2026-09-06)
Exact a94fc60: CI 34028788846 and all platform builds 34028788978 succeeded. Real MainWindow beginner action processed 34 M27 FITS, retained/registered 31, 9,300 s integration in 195.781 s. FITS and float TIFF are finite, 4144x2822 RGB. All source sizes/mtimes/SHA256 remained unchanged. Both beginner and pro measured 1280x800 with horizontal overflow zero. Evidence: work/forgepix-m27-verified-01/gui-report.json in the Codex workspace. Preview still has strong right-edge amp glow and bright core; no calibration folders found in either ASIAIR tree. This is not an image-quality release signoff.
MAST NGC6543 retrieval was attempted only for that missing test holdout. All three bounded query attempts timed out; no new FITS acquired and no training/model promotion occurred. Existing dataset and splits remain intact.
Native star workflow now uses float morphology/NS inpainting, preserves signed residual layers and creates new output versions for each additive mix. The GUI uses it directly without StarNet/GraXpert. Full-mask exports describe the actual interpolation footprint while centroid callers retain the source-detection mask. Real GUI invocation on the M27 float result succeeded with original TIFF hash unchanged; maximum reconstruction error 2.9802322387695312e-08. Limit: classical small/medium-star interpolation, partial large halos, no reconstructed hidden-sky ground truth or ML-equivalence claim. Worker overlap/window destruction is guarded.
Validation before final worker guard: 411 tests, no failures, 3 skipped; subsequent GUI/layer/translation checks: 11 passed. Full exact-commit CI/build and repeated real FITS run follow this change.

## Final verification snapshot for f76ef8d
Exact code commit f76ef8dc9fe79186f99800058b96df2b9afe9b8d passed GitHub tests (34029460527) and Windows/macOS/Linux builds including packaged CLI/GUI smoke (34029460761). Repeated full MainWindow beginner FITS run on a clean worktree exited 0 in 190.125 s; 34 inputs, 31 used, 9,300 s, finite 4144x2822 RGB float exports; source SHA256/mtime/size unchanged; no reported errors. Beginner and Pro both 1280x800 with horizontal overflow 0. Evidence is saved under Codex workspace work/forgepix-m27-verified-02 and outputs/ForgePix-FITS-GUI-Test-f76ef8d.json. Windows artifact is being copied to outputs/ForgePix-f76ef8d-Windows.
This documentation-only record follows the tested code commit; it is not a new runtime implementation or RC declaration. Still open: suitable real calibration frames/image-quality signoff, explicit rotation handling in live, advanced GUI/error-path audits, actual native astrometry/SPCC/CFA drizzle and camera-general ML. Continue from this evidence; do not repeat already completed work without a new change or regression.


## Native channel workflow and FITS precision (2026-09-06)
Downloaded exact f76ef8d Windows archive passed ZIP integrity checks and a local packaged --smoke-gui startup (exit 0, 2.75 s). SHA256 918da59f8cbccc14fbf788503f9477f0ae7e48e736fb3edbfb302c5a622ccc90. This verifies that older artifact, not the channel changes below.
- Native FITS reader no longer casts integers before choosing a fixed scale, guesses float units from the brightest pixel, clips linear floats to 0..1 or converts CFA data through uint16. Float32 bilinear debayer honors all four Bayer patterns and offsets, preserving measured samples. Float FITS retain their supplied physical values; imported float ADU files may need explicit intensity scaling for display. Engine bridges retain their separate historical scaling conventions. Calibration still clips negative corrected values and floors weak flats; that remaining scientific limitation is not solved by this reader fix.
- New channels tool in the actual GUI: RGB split; selected Ha/OIII or SII/OIII dual-band estimates; RGB/HOO/SOO/SHO combination from mono FITS/TIFF, gains, shared-grid recognition or automatic star matching, bilinear registration and common coverage. No resizing, missing-line invention, hidden channel normalization or clipping of linear output. Export float FITS and TIFF, coverage, source SHA256 and parameters in fresh directories. Derived FITS/TIFF retain line/estimate/coverage/grid identity across re-use. The simple response estimate R and (2G+B)/3 is explicitly not a pure emission-line or QE-calibrated separation.
- Veredeln now receives the selected filter and avoids broadband white balance/green suppression for narrowband images. Each run has a new output directory. Its stretched TIFF is marked as display data and rejected by the new linear channel tool.
- Numerical regressions cover signed/high/tiny float values, fixed integer scaling, all CFA phases, exact RGB file roundtrip, real star matching on an independently shifted fixture, coverage, line metadata, missing-Ha rejection, original/output preservation, filter behavior and required GUI fields. Initial full suite: 422 tests, 3 skipped, no failures; an additional coverage roundtrip test was subsequently added.
- Real menu/dialog/worker run on a copy of the full-size M27 linear FITS completed in 4.61 s: SII/OIII estimated layers, SOO recombination, finite 4144x2822 float FITS/TIFF with identical pixels, 100% common coverage, source/copy SHA256 unchanged. Processing is not mocked; only opening Explorer is suppressed. Evidence: Codex work/forgepix-channels-m27-01/gui-report.json. Filter is the user's chosen profile; historical FILTER header is absent, so capture-filter identity remains unverified. Optical image-quality signoff still lacks matching real darks/flats.
Algorithm reference: Siril's primary channel-extraction documentation distinguishes RGB/CFA extraction, interpolated resolution and sensor-response issues: https://siril.readthedocs.io/en/stable/processing/extraction.html . ForgePix's simple weighted full-resolution estimate is its own stated subset, not Siril's exact extraction implementation.
Next exact-commit GUI FITS run and platform CI/builds follow these changes. RC and broad parity remain unfinished; continue from this evidence without promoting synthetic-only models.


## Verified channel milestone bd0f592
Exact runtime commit bd0f59276d445cf305c39389fca2205f5349451c passed all 423 local tests (3 skips, no failures), GitHub tests 34030679945 and all platform builds 34030679092 including packaged startup/CLI tests. Clean-worktree real beginner GUI run: 34 M27 FITS, 31 used, 9300 s, 191.578 s elapsed, finite 4144x2822 float exports, originals unchanged, 1280x800 with no horizontal overflow. Exact-commit real channels menu/worker test: 4.719 s, no errors, original/copy hashes unchanged. Reports: Codex work/forgepix-m27-verified-03 and work/forgepix-channels-m27-02; deliverables in outputs/ForgePix-FITS-GUI-Test-bd0f592.json and ForgePix-Kanaele-GUI-Test-bd0f592.json.
Windows ZIP downloaded to Codex outputs/ForgePix-bd0f592-Windows, integrity checked (SHA256 f0397ae173e45f6ac1bef455b48a1bad91d143c07ab7ed04336b5fc6935d7bc2), locally starts GUI in 2.67 s, and completes a separate packaged four-frame synthetic CFA FITS integration (exit 0, finite float FITS, original hashes preserved). This document record does not change the tested runtime or declare an RC.
Spark is reachable (194 GiB disk available, 27 GiB available RAM), no active ForgePix training/collector. MAST base endpoints respond, but narrower Cone POST (25 s) and GET (20 s) diagnostics also time out. No additional FITS acquired or model promoted; avoid duplicate workers. Hourly RC continuation stays active. Next work remains actual calibrated image-quality evidence, scientific precision/flat handling, live rotation/cancel/error paths and further native capabilities in CAPABILITY_STATUS.md.


## Signed calibration, flat response and conservative cosmetics (heartbeat 2026-09-06)
Checked clean 1eb8b25 and prior exact-code bd0f592 tests/builds. No active Spark training/collector; no duplicate or new acquisition started after the recent bounded MAST timeouts.
Fixed measured numerical defects: calibration no longer truncates negative noise after dark subtraction or floors normalized flat response to 0.2. Positive flat pixels use their actual response; any nonpositive pixel fails with an actionable calibration error until an explicit bad-pixel mask path exists. Invalid overflowed outputs fail. Calibration without masters returns an independent signed float copy. Banding and live-result return no longer clip linear values; preview clipping remains confined to display output. Signed live data survives checkpoint reload.
Cosmetic correction now uses float32 medians, per-channel robust noise, a neighbor-structure guard and isolated-candidate checks. Spatially resolved stellar peaks are protected, while isolated bright/cold defects are corrected. This conservative method may leave adjacent defects and demosaiced clusters; undersampled point stars cannot be reliably distinguished from defects without a raw CFA defect map. No universal stellar-flux or cosmic-ray rejection claim.
Compared with 1eb8b25 on analytic fixtures: zero-signal noise mean 0.0025493 -> 0; weak-flat maximum absolute error 0.495005 -> 0; resolved stellar flux error -4.8391% -> 0. New tests use direct calibration, a FITS/CFA/cache/integration path, defective flats, signed/live restart and PSF fixtures. Full local suite: 433 tests, no failures, 3 skipped. Evidence: Codex outputs/ForgePix-Kalibrierung-Praezisionsvergleich.json (synthetic tests, not real-image quality signoff).
Primary algorithm context: https://siril.readthedocs.io/en/latest/processing/cc.html documents neighbor-based cosmetic checks and a separate CFA mode. ForgePix uses its own conservative isolated-outlier subset. Exact-commit builds and the repeated actual M27 GUI workflow follow this change. Real calibrated quality acceptance and other RC criteria remain open.


## Verified precision milestone and discovered real dark master
Runtime 3cf7f7d7d18f5b5ff2d30f3e581c7155cb2fd0af passed 433 tests (3 skipped), CI 34031483752 and all platform builds 34031483647. Actual clean-worktree beginner M27 GUI run: 34 FITS, 31 integrated, 9300 s, 195.797 s, no errors, original sizes/mtimes/SHA256 unchanged, 1280x800 without horizontal overflow. Windows ZIP downloaded to Codex outputs/ForgePix-3cf7f7d-Windows, SHA256 a4d780b3d3f4bb62e627b72ccb3bfc07bc74ed29bbfe5c6f0637efc45e1aacc3; locally starts and processes calibrated synthetic CFA FITS with signed/high output range -0.01..1.72038 and preserved sources.
Expanded read-only search beyond the ASIAIR subfolders found Y:/Backup/astro/dark_300.fit, plus 30/60/120/180 s masters. The 300 s master has matching ASI294MC Pro, 4144x2822, RGGB, gain 131, offset 30, -10 C, bin 1. Its data are normalized float FITS, made with Siril 1.0.5 from 2022 captures; this age and unspecified readout mode remain limitations. Its SHA256 is d7717a414db0c41e1b36352b11a23dd192b8a12be5c71af24d2d3fbb47bcdc43. Other masters under Y:/Backup/astro/astrofotos/darks are ASI533, different size/gain and not compatible. No matching flats found. Do not repeat the earlier claim that no usable dark candidate exists; do not automatically adopt this old master for future sessions.
Test-harness-only commit 4b2501189dada2b6fa11f2771997ea21188d237d adds explicit --dark/--flat/--bias and hashes those masters before/after. Tests 34031659275 passed. Actual clean-worktree GUI run using --dark Y:/Backup/astro/dark_300.fit passed in 188.516 s: 31/34 lights, 31 registrations, 9300 s, finite FITS/TIFF range -0.334873..0.606251, metadata validation checked all selected lights and the master with no known mismatches. All originals/master unchanged. Source/report under Codex work/forgepix-m27-dark-verified-01 and outputs/ForgePix-FITS-Dark-GUI-Test-4b25011.json; preview outputs/ForgePix-M27-Dark-Vorschau.jpg. Visual right-edge brightening is reduced, but faint-background rendering, old-dark stability, extreme negative defect pixels and missing flats still prevent image-quality signoff. A dark-only real calibration path is now exercised; do not claim a complete calibrated release or alter user's default settings.
No further MAST retry or training job launched during this heartbeat. Continue with live rotation/cancel/error workflows, precision/defect-mask coverage and remaining native capabilities; revisit model/data acquisition on new evidence rather than repeating the recent timeouts.

## Own local AI implementation and measured training iteration (2026-09-06)

User priority is own trained AI integrated into ForgePix. Four new mono NAFNet
models were trained on Spark for 4,000 steps each, with richer signed/Poisson/
correlated-noise, Moffat/filament/elliptical-blur/gradient simulations. The verified
public-HST scene bank has 563 training and 288 validation patches with object
separation and rechecked source SHA256; observational noise is retained, not
mislabelled clean truth. All source provenance is in training/reports.

Four ~1.87 MB ONNX models are bundled in assets/models, with retained architecture
licences, own-weight attribution, manifests and numerical export checks. Native
CPU inference requires no external astronomy application/server or PyTorch.
Each colour channel is processed independently; the affine normalization is
inverted without clipping. FITS metadata, dtype-based integer scale and known
coverage are handled explicitly. Raw CFA, marked nonlinear display inputs and
partial known coverage are rejected. New output directories contain Float32
FITS/TIFF, source/model SHA256, per-output integrity checks and signed star
residuals. No model is enabled in automatic processing.

GUI now exposes four own AI operations, strength, progress/cancel, common
source-derived before/after stretch, scientific copy export and explicit display
export. Audit fixed black Float/FITS previews, accidental residual selection,
lost FITS units/WCS, inconsistent integer scales and stale paired exports.
Closing a busy worker is cooperative. German and English labels are supplied.

Independent 64-scene comparison with earlier own RGB research models: v2
background MSE ratio 0.2078, deblur 0.6291, starless 0.8881; mono denoise 1.3416
(worse). Ratios describe the specific synthetic test, not product parity.
An additional 8,000-step denoiser refinement took 576.6 seconds and improved
mixed development MSE, but a fresh 128-scene suite found it 46.1% worse than
initial mono v2. It is rejected and not bundled. Initial mono v2 reduces input
MSE by 85.1% there but is 31.3% worse than the RGB baseline. Correlated noise is
the clear refinement weakness; balance per-noise-group and real-scene validation
before further selection. See refinement report and explicit selection JSON.

Background inference was further improved using whole-field AREA256 estimation,
Gaussian-sigma16-smoothed additive residual and residual-only cubic enlargement.
Original detail pixels are never resized in the scientific output. Four large
gradient scenes improved by 79–95% MSE versus input (old tiled path -3–20%).
Three gradient-free controls have smaller changes, but nonzero offsets and
nebular-contrast errors remain. Actual larger-image tests also expose tile-phase
dependence for other tasks. All results remain experimental, not photometric or
camera-general qualification. Benchmark evidence is in Codex outputs/
ForgePix-KI-Hintergrundvergleich.{py,json,md} with measured source hashes.

Final local suite: 476 tests, no failures, 3 skips. Source startup/CLI smoke and
all four actual ONNX scientific exports passed. Real full-size M27 GUI processing
already passed for starless/deblur and the earlier tiled background path, with
unchanged source, common previews, bit-identical Float32 FITS/TIFF and signed
layer reconstruction within 3.73e-9. Final exact-commit GUI/CI/package evidence
follows below. Existing RC acceptance remains open; version stays beta.

## AI cross-platform fixes and reimport integrity

The complete four-operation M27 GUI run on clean 4cded82 passed: 4144x2822 RGB,
372.687 seconds total, original size/mtime/SHA256 unchanged, finite outputs,
pixel-identical Float32 FITS/TIFF and star-layer reconstruction error 3.73e-9.
Background uses the final whole-field residual strategy and took 4.547 seconds;
denoise/deblur/starless took 123.750/115.750/121.859 seconds. Evidence is in Codex
work/forgepix-ai-m27-4cded82/gui-ai-report.json. The visible amp glow/colour cast
and bright core remain; this tests operation and integrity, not calibrated image
quality or universal camera support.

Initial CI exposed filesystem aliases on macOS (/var versus /private/var) and
Windows (short versus long account paths). 0b9c4e1 resolves aliases consistently
for linked previews and exports, with a symlink regression. Tests 34035515536 and
all platform builds 34035515161 passed, including actual inference/export of all
four bundled models through packaged executables.

An independent audit found that reimport after restart lost the AI export
context. Reimport now recognizes recorded FITS/TIFF/results/residuals, verifies
the selected file, preserves the scientific export route and reuses a valid
common display cache. The original comparison requires the source SHA256;
missing sources/previews still permit byte-preserving scientific export.
Changed results, malformed provenance and marked AI files without their report
fail explicitly instead of entering generic ADU conversion. Full group hashes
are checked on export. Nine reimport regressions exercise signed/physical values,
FITS units/WCS, missing files, invalid reports, stale sources and display failure.
Local full suite passed 485 tests (4 skips), followed by 48 focused tests (1 skip)
including the final ninth reimport case. Exact final CI and FITS evidence follow.
The main READMEs now distinguish the optional language assistant from our four
local pixel models and describe experimental status and rejected refinement.

## Verified own-AI milestone 441b432

Exact runtime 441b432b325d9b48ac962a6cc223c4fc566daf28 passed 486 tests in
GitHub run 34036025945 on Windows/macOS/Linux and all three builds in run
34036025903. Packaged smoke runs actually execute all four bundled ONNX models
on FITS, in addition to GUI startup and focus stacking.
The final clean-worktree MainWindow M27 test passed in 349.921 seconds: all four
operations and native comparisons, unchanged 140336640-byte original, finite
4144x2822 RGB Float32 FITS/TIFF with identical pixels. Task times were
111.015/4.563/115.328/112.343 seconds (denoise/background/deblur/starless).
Star-layer reconstruction error remains 3.72529e-9. Evidence: Codex
outputs/ForgePix-KI-M27-GUI-441b432.json. A separate real MainWindow reimport of
the full M27 background result restored the common preview and copied FITS/TIFF
byte-for-byte in 4.634 seconds (ForgePix-KI-Reimport-M27-441b432.json).

Downloaded Windows ZIP: 172598837 bytes, SHA256
d4b083c87541dfcd3345de1ea2278c4cd887f2cbb202ec07d9d66d0c4c2daed7,
in Codex outputs/ForgePix-441b432-Windows. Archive CRC and all four model hashes
passed. The extracted executable locally passed GUI startup, focus stacking and
all four actual model FITS exports; verification.json and smoke.log record it.
This entry changes documentation only. Version remains 1.27.1-beta, experimental
models are not defaults, and neither photometric/camera-general AI nor RC/full
product parity is declared. The existing hourly continuation remains active;
next training priority is correlated-noise breadth and separate validation gates.

## Automatic compute backends and grouped-noise experiment (heartbeat)

The user's CPU question identified the remaining forced-CPU implementation.
Own AI inference now selects available CUDA/Windows DirectML/macOS CoreML and
falls back to CPU; explicit CPU is available in the beginner dialog. Provider
errors after partial processing discard that attempt and recompute the whole
image. Cancellation is separate. Reports record actual backend/fallback, without
claiming physical GPU node placement from mere provider registration.
Windows x64 requirements/package use DirectML 1.24.4 without external CUDA DLL
installation. Packaging still includes the actual ONNX runtime/model assets.
See GPU_ACCELERATION.md for constraints, platform scope and primary references.

Initial local full suite in the isolated DirectML environment: 513 tests passed,
7 skipped (including training dependencies unavailable locally). A separate
RTX3060Ti probe ran all four own models on CPU and DirectML with normal, zero,
signed/HDR and tiny inputs: finite values, max absolute backend difference below
2.9e-6, profiling recorded DML graph execution. Warm single-tile timing is not
a full-FITS speedup claim; exact-commit full-image comparisons and packages follow.

The independently running Spark experiment uses 6,000 bounded steps, new noise
amplitudes/scales, 24 separate synthetic/M13/M16 development groups and strict
per-group MSE/MAE/bias/local-mean gates against the unchanged mono v2 parent.
Final evaluator seed 9518063 was reserved before optimization. Training code
records the actual CUDA device and source/checkpoint hashes. Models in assets
remain unchanged; evaluation may reject this candidate and cannot silently
replace the current model. Reports follow after this finite run completes.

## Verified GPU milestone 321259b and completed noise-group research

Exact runtime 321259b7a1272b92e7f8e8a489f5fa9efdf0dbde passed 515 tests on
Windows/macOS/Linux (34037462235) and all three packaged builds (34037505892).
The final two regressions also prevent backend attempts after cancellation during
native initialization. A dispatch that briefly resolved the old branch head was
cancelled; only the verified 321259b build is used for the following artifact.

Same-runtime full M27 FITS benchmark (ONNX 1.24.4, same models, 50% strength,
sequential CPU and DirectML runs, source SHA256/mtime/size unchanged): denoise
101.978 -> 6.331 s (16.1x), background 2.400 -> 2.347 s (effectively unchanged),
deblur 105.482 -> 6.085 s (17.3x), starless 100.370 -> 7.292 s (13.8x).
Times include source reading and scientific export, excluding GUI previews.
Maximum CPU/GPU absolute pixel difference across the four full-size outputs is
8.940697e-8; all predefined numerical comparisons passed. These are one-computer,
one-image measurements, not general performance or model-quality guarantees.
Evidence: Codex outputs/ForgePix-M27-CPU-GPU-321259b.json; active runtime source
hash recorded. Pending worktree files during this run were training reports.

Actual MainWindow menu/dialog/worker/comparison acceptance on the same full M27
FITS passed all four tools using the real Auto widget, selecting DirectML every
time without CPU fallback. Total 39.328 s, finite pixel-identical Float32 FITS
and TIFF, source unchanged. Report: ForgePix-M27-GPU-GUI-321259b.json.
Downloaded Windows archive: 190513709 bytes, SHA256
d7c8ae89e2e6a39dad8ac674f4a40168a01f931fb9b4bc74d5c772b32e557b91.
The archive, all bundled model hashes and locally extracted executable passed.
Local packaged smoke explicitly required DmlExecutionProvider for every model;
GUI startup, focus stacking and all four actual FITS AI exports succeeded.
Artifact/evidence: Codex outputs/ForgePix-321259b-Windows.

The separate 6,000-step denoiser experiment completed in 439.6 s on NVIDIA GB10,
CUDA 12.8. No training process/lock remains. Fresh 128-scene evaluation improves
correlated-noise MSE 3.83% and low-noise MSE 42.27%, but aggregate error worsens
2.07%, read/shot performance regresses and faint-region MSE rises 24.96%.
44 development metrics and six final gates fail: candidate rejected, bundled
models unchanged. Actual source/checkpoint/device/seed/export evidence is in the
six denoise-noise-groups-v3-001 JSON files. Research ONNX export passed equivalence
and remains outside app assets. Next research must preserve bias/faint structures
and read/shot performance; inspected seed 9518063 is no longer an untouched test.

This evidence/documentation update does not change the tested runtime. Version
remains 1.27.1-beta; GPU speed does not establish camera-general AI or RC parity.

## Native projects, CFA Drizzle and measured stellar white balance

The next user-requested expansion adds a real project document with immutable
result snapshots. New results, scientific coverage/weight companions and recorded
AI groups are archived and hashed. Save/Open/History work across restarts and
folder relocation; changed files cannot be silently relinked. Scientific export
publishes a complete verified copy into a fresh destination. Archive/export
folders are excluded from raw-frame discovery. This is result-file history, not
parameter/mask undo, a complete raw-data backup or a recomputable process graph.

The actual M27 GUI test used real menus/file dialogs, added two distinguishable
FITS results, closed/reopened the window and selected the older result. The
regular Export button copied its scientific files unchanged. Source/export SHA256
is 73355cba99ce1be18c1fe6b91001e395b1cc6de9e18c39c18071b03af2ef2f50.
Evidence: Codex work/forgepix-project-m27-02/gui-project-report.json. The second
fixture has an explicit test offset to distinguish history states; it is not
presented as an image-enhancement algorithm. Sixteen project regressions cover
integrity, missing coverage, external changes, archive discovery and failed writes.

Native Drizzle now uses exact square-drop area overlaps, Float64 accumulation,
subpixel/affine geometry, original calibrated CFA samples and separate per-color
coverage/weights. Missing samples are zero placeholders with zero support, never
inpainted; no clipping or silent shape changes. GUI and CLI support native 1x CFA
reconstruction. Actual used-frame counts and color coverage are shown in the UI.
Input guards reject known nonlinear/display data, and cancellation invalidates
partial contributions. See NATIVE_DRIZZLE.md for the flux/pixel-area convention
and unsupported combinations; it does not perform sigma rejection or local
normalization, and is not native WCS/TPS reconstruction.

Full real M27 run: 34 original ASIAIR CFA FITS, normal quality selection kept 31,
31 registrations, 9,300 s exposure, 114.0 s execution at 1x (4144 x 2822 RGB).
Joint color coverage 99.9759%, Float32 FITS/TIFF pixel-identical, per-color masks
match positive weights, original SHA256/mtime unchanged. No calibration frames
were used, so amp glow/hot pixels remain and final image quality is unqualified.
Evidence: work/forgepix-drizzle-m27-1x-full-01/drizzle-e2e-report.json. This run
preceded final non-FITS input guards and clearer warning wording. An earlier
three-frame 2x diagnostic with QC disabled had 0% joint coverage and may have
matched fixed-pattern defects in the rejected cloudy last sub. It is explicitly
not a qualified image integration. Launcher-only memory readings were discarded;
no measured real-process peak memory is claimed for these runs.

Twenty-one targeted Drizzle tests plus 80 independent random geometry cases
passed. A separate corner/edge-intersection reference tested mono/RGB/CFA,
rotation/shear/reflection/scale, null weights and invalid samples. After correcting
tiny-drop area cancellation, normal-case relative weight/flux differences were
below 2.8e-14; the smallest permitted pixfrac case differed by 1.7e-9 in weights.
An interrupted affine frame cannot be finished or reused. Independent evidence:
outputs/ForgePix-Drizzle-Independent-QA.json and its standalone reference script.

Auto/Lite color correction now measures native circular star fluxes above robust
local sky planes, fits per-star ratios and retains signed/HDR values. It does not
call external solvers/network or label a neutral-star assumption as catalog PCC.
Known narrowband data remain exempt. Independent review caught and fixed rounded
edge patches and four-pixel unsaturated symmetric PSFs being mistaken for clipping.
Fifteen targeted regressions plus GUI plumbing checks pass. Full M27 execution
selected 148 stellar references in about 1.2 s without altering its source. The
capture filter is unknown; this is not validation of its true colors.
See NATIVE_STELLAR_BALANCE.md for the aperture/reference assumptions.

## Mean-anchored denoiser research v4

Another bounded 6,000-step run completed on Spark/NVIDIA GB10 with CUDA 12.8:
544.0 s optimization, 24.0 s development evaluation. A frozen parent plus a
small mean-free student correction, original-distribution replay and local/faint
structure losses address v3 regressions. All 27 development image-bias gates pass
and the geometric development MSE is 10.90% lower, but 17 MAE, four MSE and one
local-mean gate still fail. This is development evidence, not an independent
generalization improvement. The candidate is rejected; bundled models unchanged.

Reserved final seed 9671507 was not consumed; no final evaluation or ONNX export
was run for this failed candidate. Seven focused training/selection tests passed
(three on Spark). Plan, training, decision and execution attestations are stored
under training/reports/denoise-anchored-v4-001-*.json. The per-tile mean constraint
does not guarantee unbiased whole-image overlapping inference. No GPU training
process/lock remains. Total completed optimization across the four initial v2
models and the three denoiser refinement attempts is now 36,000 steps.

Exact-commit final suite/build/package and repeat full-FITS evidence follow in
the verification entry. Version remains 1.27.1-beta. Native astrometry, actual
catalog/SPCC fitting, editable process masks/history, calibrated real-camera AI
validation and broader comparative image-quality work remain open.

## Independent acceptance caught a meridian-flip alignment defect

The d61eff4 full-FITS repeat finished in 117.5 s and preserved original files,
coverage companions and exact FITS/TIFF values. Independent stellar positions
subsequently disproved its shift-only alignment: M27 frames 21 onward contain an
approximately 179.85-degree meridian flip. The old 8-bit star detector allowed
fixed sensor defects to vote for identity transforms. Consequently the earlier
31-frame counts and 99.9759% coverage are export/geometry observations only, not
proof of correct integration. Do not use these stacks as astronomical truth.
Evidence: Codex outputs/ForgePix-Drizzle-M27-Independent-Alignment.json.

The cross-platform path-alias fixture correction 5677d8b passed all tests
(34042258869) and Windows/macOS/Linux packaged builds (34042270900), but it
predates this scientific defect correction and is not the new candidate.
The revised detector preserves float data and suppresses isolated sensor events;
shift-only must reject the flipped field while rotation fits the real stars.
GUI wording explicitly covers meridian flips and the CLI now shares its rotation
default. Subsequent exact-runtime acceptance must check stellar residuals as
well as output integrity.

The combined real project/ONNX/UI audit also found and corrected a narrower
integrity gap: AI export must verify the selected project archive's independent
hashes, including its report, before creating an output directory. A same-size,
same-mtime report change cannot be exported as the saved result. Normal/quick
exports and unchanged archived/external AI groups have regressions; the real
two-model project roundtrip works through reopening and source relocation.

Next AI research should cover all four tasks: first background controls for
faint emission and channel-ratio preservation; then empirical varying-PSF deblur
with aperture flux/centroid/ringing/tile-phase measurements; then starless tests
with inserted empirical stars and untouched nebula controls. Denoise v4 motivates
one direct pixel-MAE loss addition with architecture/replay/gates unchanged.
The weight must be fixed from training data, never the held-out final seed.
Object/session/camera splits precede patch extraction. Seed 9671507 remains unused.
No additional GPU training or downloads were started for this planning review.

The affine Drizzle kernel now integrates the original drop edges analytically
with Green's theorem, plus exact bounding-box exclusion and containment. No
angles are rounded and no extra dependency is needed. Three paired synthetic
512x768 CFA runs at angle .0026 rad / pixfrac .7 measured medians of 6.2503 ->
0.61169 s (10.22x) at scale 1 and 14.3799 -> 1.07020 s (13.44x) at scale 2.
Float32 images were bit-identical, coverage unchanged, maximum relative weight
difference 5.56e-16. Another 30,000 polygon cases matched the former clipper to
4.45e-16 absolute area with no lost/spurious coverage. The separate 80-case
independent construction also passed; these are geometry/performance checks,
not proof of astronomical resolution recovery. Evidence:
outputs/ForgePix-Drizzle-CPU-Optimization.json and its standalone comparison.

Before the final source freeze, the actual beginner GUI completed M27 with the
revised rotation detector and an explicitly supplied matching-header 300 s dark:
31/34 FITS, 224.609 s, finite full-size scientific exports, originals unchanged,
no GUI errors. work/forgepix-m27-flip-corrected-01/gui-report.json records the
worktree. The selected SV220 profile tests its GUI route; the historical FITS
capture filter remains unknown and the 2022 dark's long-term suitability and
missing flats remain unqualified. Final exact-commit evidence follows separately.

The full suite caught a useful regression in the first detector fix: real
undersampled sigma=.8 stars were too sharply peaked for the defect filter.
Significant PSF wings outside the 3x3 core now distinguish them from isolated
Bayer impulses. The original narrow-star channel fixture was retained; its
known-shift tolerance is unchanged and an independent common-field flux check
measures 0.00654% error against a 0.1% bound. Export checks account for the
reported subpixel resampling instead of assuming exact integer pixel identity.
All 120 affected tests pass, including the sensor-defect and meridian cases.

## Exact a60a832 verification completed

The clean runtime a60a832996c99cd8002c593055681938a0237ece passed 591 local
tests (10 skipped), GitHub tests 34044045018 and builds 34044086691 on all
three platforms. Its Windows ZIP (190586786 bytes, SHA256
cea993eafb2158fbe9a43ba0c85529d8f1734b62717adf96a004fb0051db268a) passed
unpacked GUI/CLI, native Drizzle and all four DirectML model smoke checks.

The actual beginner GUI completed the corrected 34-source M27 series with
31 selected frames / 9300 s exposure in 260.531 s while other tests ran.
Matching-header dark supplied, no flats; original files unchanged. No GUI
errors or horizontal overflow at 1280x800. Four real AI GUI operations on
this corrected linear stack passed output/provenance checks and selected
DirectML; this is execution acceptance, not model-quality qualification.

The full native CFA Drizzle rotation run completed in 637.031 s. All 31
matrices passed the independent predeclared stellar-position gates. Excluding
the reference, 250-286 unique mutual pairs per frame; worst median 1.083 px
and P95 1.917 px (gates 1.5/3 px), all four quadrants represented. Original
hashes agree. This supersedes the old shift-only alignment result and does
not establish general photometric accuracy or recovered detail.

Evidence: Codex outputs/ForgePix-Native-Weiterentwicklung-20260906/
Pruefbericht.md and its exact-commit JSON reports. Follow-on documentation
or feature commits must not be confused with this frozen package. The
version remains beta. User priorities now explicitly include native
catalogue solving/color calibration, executable repeatable macros and a
coherent professional GUI in addition to all four AI quality tracks.

## Native local astrometry, catalogue manager and executable recipes

Own hinted catalogue solving now matches stellar triangles with free rotation
and parity, refines a TAN/affine WCS and accepts it only after a fixed held-out
third of image stars passes independent residual/distribution checks. A native
ESA TAP client downloads bounded Gaia extracts with epoch/provenance metadata;
the local index is rebuilt on load and RA queries are normalized. Truncated
fields are rejected explicitly. The catalogue dialog loads, downloads and
merges into new files asynchronously; cancellation never destroys its worker.

Full real M27 acceptance used 16123 Gaia DR3 rows and historical raw-FITS hints
(RA 300.17904 deg, Dec 22.795087 deg, focal length 1151 mm / pixel 4.630000114 um),
not the current equipment preset. It found 154 fit and 78/80 independent
validation stars, RMS 0.426933 pixels in all quadrants. The actual reference is
frame 0017, although the stack filename uses frame 0001 as its base. Against
the unused reference ASIAIR TAN-SIP WCS, a separate 25-point grid differs by
1.80 arcsec median / 2.47 arcsec maximum; internal residuals are not absolute
accuracy certification. No blind search, distortion fit, epoch propagation or
spectrophotometric colour calibration is claimed.

Actual MainWindow menu -> solver -> project -> restart/history -> normal
scientific export passed on full 4144x2822 M27 in 14.969 s. Original data,
catalogue and exported pixel-byte hashes are unchanged; FITS and provenance
survive project archival and export. File-adapter tests also preserve Float64,
unsigned physical values, units, coverage and weights. Derived AI outputs keep
their original experimental/model provenance and record the WCS-only operation.

Versioned .fprecipe files execute pinned model IDs/SHA256, parameters and order
with a source snapshot, atomic run journal, cooperative cancellation and saved
completed steps. The GUI edits/saves/loads recipes and archives each completed
step in an active project. Real M27 GUI acceptance ran background 25% then
denoise 50% with DirectML, reopened both project results after restart and
verified all source/output hashes (43.015 s). This is repeatable processing,
not a GUI action recorder, arbitrary process graph or model-quality upgrade.

Public --recipe and --solve CLI routes support automation. Package smoke now
exercises the three new dialogs, a two-step actual recipe and native solving
against an independent WCS fixture with unchanged Float64 output. New dialogs
use consistent graphite/blue controls and English translations. Exact-commit
suite/build/package results follow after source freeze. Version remains beta.

Workspace evidence: outputs/ForgePix-Recipes-20260906,
outputs/ForgePix-Native-Astrometry-GUI-20260906-03 and
work/native-astrometry-m27/run-002.json. M27's historical filter is unknown;
these checks do not establish colour calibration or product parity.

Combined-workflow acceptance caught and fixed two integration defects before
source freeze: WCS-only derivatives of own AI estimates now retain a verified
derived AI report, with original report embedded and no second model execution
claim; Drizzle sampling companions (FPDRZCOV/FPDRZWGT) are validated and copied
byte-for-byte into own AI groups instead of leaving dangling header references.
The report explicitly distinguishes original sampling support from AI-result
uncertainty. Changed/inconsistent companions fail before publishing an AI group.
The combined AI -> native solver -> project/reopen/export regression passes;
tampered astrometry reports block export. The actual source recorded by the
completed solve is used for comparison even if the GUI input field is later edited.
