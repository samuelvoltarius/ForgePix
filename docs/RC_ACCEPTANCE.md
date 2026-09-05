# Release Candidate acceptance

The user requested an RC on 2026-09-05. This is a tested release milestone,
not a promise of complete Siril/PixInsight feature parity.

- [ ] No known crash/data-loss defects in the supported FITS workflow.
- [ ] Import, raw calibration, registration, quality selection, integration,
      native development and lossless export verified end to end with real FITS.
- [ ] Professional workspace layout verified at practical window sizes; beginner
      controls understandable and reachable, equipment and expert controls usable.
- [ ] Calibration/frame compatibility checked; useful errors for missing/incompatible
      frames; original data preserved and output locations unambiguous.
- [ ] Stop/cancel and live final export tested; errors do not masquerade as success.
- [ ] PixelMath and other exposed calculations have numerical regression checks.
- [ ] All required automated tests pass on the exact candidate commit.
- [ ] Windows/macOS/Linux builds pass, including packaged CLI and GUI startup checks.
- [ ] No experimental synthetic-only AI weights enabled by default. Validated native
      classical processing remains usable without downloads or external applications.
- [ ] RC version, release notes, known limits and downloadable artifacts agree.

Training/data acquisition continues as a separate workstream. Maintain provenance,
object/camera/session splits and resource limits. Full native astrometry, advanced
spectrophotometric calibration and camera-general AI need explicit evidence before
claiming availability. Document unfinished work; do not mark it complete or hide
it behind a release label. Existing external integrations are not evidence that
their functionality has been independently implemented.
