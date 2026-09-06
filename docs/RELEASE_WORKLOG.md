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
