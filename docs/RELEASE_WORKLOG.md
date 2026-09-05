# Active ForgePix release work

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
