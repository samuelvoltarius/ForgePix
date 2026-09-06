# Native stellar white balance

`core/star_color.py` measures circular stellar apertures in linear floating-point
images. The automatic and legacy `lite` selections in `photometric.run_pcc` now
use this native implementation. They do not discover external solvers, query a
catalog, or launch Siril. Explicit legacy selections remain available.

This is a statistical white balance: the median measured stellar color is
assumed neutral. It is **not** catalog-color PCC, SPCC, a measured camera response,
or recovery of true emission-line ratios. Siril's
[PCC reference](https://siril.readthedocs.io/en/stable/processing/color-calibration/pcc.html)
describes the separate catalog-based workflow. Gaia-selected positions in the
legacy ForgePix routes still do not supply expected colors to the fit.

## Measurements and application

- Float detection removes a smooth field only to locate candidates. It has no
  8-bit conversion or fixed unit-range signal threshold.
- A radius-6 pixel-center aperture measures each original BGR channel. A robust
  local plane fitted to a radius-9..14 annulus supplies the sky contribution.
  The [Photutils aperture guide](https://photutils.readthedocs.io/en/stable/user_guide/aperture.html)
  explains aperture sums and local sky subtraction; no Photutils dependency or
  source code is used here.
- At least ten accepted stars are required. The measurement rejects close
  catalog positions, weak channels, obvious flat saturated cores and unsuitable
  spatial profiles. Physical saturation is optional input, never inferred from
  a supposed floating-point maximum of one.
- Robust per-star log B/G and R/G ratios prevent bright stars from dominating
  the fit. Implausible gains cause an unchanged result. They are not clamped
  into a plausible-looking measurement.
- A single per-channel affine transform applies the fitted gains and optional
  constant sky-color offset. Signed noise and values above one survive. The
  strength blends this transform with identity.
- Insufficient references leave the image unchanged with an explicit reason.
  No percentile fallback is reported as stellar photometry. Known narrowband
  inputs bypass broadband white balance, including failed external SPCC cases.

The existing Astro checkbox controls preview development. Its linear stack
exports precede preview color development and remain unchanged. External Siril
FITS exchange also preserves signed/high floats and rejects failed subprocess
exits or invalid result dimensions.

## Evidence and limits

Numerical regressions in `tests/test_star_color.py` cover known injected channel
responses over different colored sky gradients, faint-unit invariance, signed
HDR data, saturation, atypical stellar colors, missing references, strength,
native routing, narrowband preservation and FITS round trips. The GUI regression
ensures a disabled Siril-only setting cannot leak into the native command.

An execution test on the unchanged full 4144 x 2822 M27 linear FITS selected
148 references from 300 detections in approximately 1.2 seconds. Its source SHA256
is `73355cba99ce1be18c1fe6b91001e395b1cc6de9e18c39c18071b03af2ef2f50`.
The historical stack does not establish its capture filter. This is execution
and preservation evidence, not confirmation of astrophysically correct colors.

The fixed aperture, imperfect crowd/saturation recognition, chromatic PSF
differences, field-dependent extinction and the neutral-population assumption
limit accuracy. A single sky offset does not remove spatial gradients. Native
astrometry, expected catalog-color fitting and spectral response integration
remain separate unfinished capabilities. No Siril/PixInsight color-quality
equivalence has been measured.
