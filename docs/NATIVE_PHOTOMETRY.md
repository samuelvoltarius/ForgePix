# Native catalogue photometry diagnostics

ForgePix can measure stellar aperture fluxes against a local Gaia DR3/GSPC field.
This first implementation writes measurements and exclusions to JSON and CSV.
It does not alter an image, fit colour terms, apply white balance, or qualify a
PCC/SPCC result. The existing position-only Gaia NPZ remains a separate format.

## Use

The command line is the first entry point. A dedicated beginner-facing colour
calibration workflow is still pending. Commands below also work with the packaged
`ForgePix.exe` in place of `python focus_stack_gui.py`.

Download a small public field once into a **new** file (network required):

```text
python focus_stack_gui.py --photometry-catalogue --catalogue gaia-m27-photometry.npz --ra 300.18 --dec 22.79 --radius 0.65 --max-mag 15.5
```

Then measure a linear, registered FITS with celestial WCS entirely offline:

```text
python focus_stack_gui.py --photometry --input solved.fits --catalogue gaia-m27-photometry.npz --output-root results
```

The result is a new `stack-photometry-*` folder containing
`photometry_report.json` and `stars.csv`. Original images, catalogues, masks and
weights are read-only. A changed dependency or cancellation prevents publishing
the report. Generated folders are excluded from light-frame discovery.

Optional inputs must describe the **actual stack**, not just current equipment:

- `--epoch` is a documented effective Julian observation year in TCB. Otherwise only
  `DATE-AVG`/`MJD-AVG` is used; a raw frame's `DATE-OBS` is not a stack average.
  Conflicting/invalid averages stay unknown. A supplied average is not proof of
  exposure weighting or multi-session timing.
- `--saturation` takes one threshold or three values in R G B order, in the
  original physical FITS pixel units. No camera ADU ceiling is automatically
  applied to a normalized stack. Unsaturated stack pixels do not prove that
  each contributing exposure was unsaturated.
- `--variance` supplies a separate FITS of the same shape in input-unit squared.
  It is diagonal variance, not resampling covariance. Drizzle overlap weights,
  camera gain settings and total exposure time are not interchangeable with it.
- `--linear` records an explicit assertion of linearity when FITS provenance is
  absent. It cannot override a header that declares a stretch or AI estimate.
- `--aperture`, `--annulus-inner`, `--annulus-outer` set radii in pixels.
  Defaults are 6, 9 and 14. They are diagnostic settings, not a validated
  aperture correction for an arbitrary PSF or telescope. The inner annulus must
  be at least two pixels outside the aperture to avoid shared noise samples.

## What is measured and retained

FITS physical values are read after standard BSCALE/BZERO handling, in Float64
working precision with no additional normalization or clipping. Colour files
use RGB planes `(3, height, width)`; mono remains mono. Each star uses one common
subpixel aperture across channels, a local sky plane and an annulus with neighbour
masking. Blends, insufficient sky support, invalid pixels, saturation and missing
coverage are reported. Known mask holes exclude affected measurements instead of
being filled. Missing coverage or saturation evidence is kept explicit.
If repeated sky clipping would remove too much annulus support, the last
sufficiently supported fit is retained as a flagged diagnostic, never as an
eligible reference. This also handles essentially noiseless synthetic skies
without inventing a noise floor or a precise sky estimate.

The separate photometric field retains lossless 64-bit `source_id`, coordinates,
reference epoch, proper motion and uncertainty/quality fields, plus GSPC BVR
magnitudes, fluxes, errors and flags. Report/CSV IDs are decimal strings to avoid
loss in consumers that represent JSON numbers with floating point. Gaia
`pmra` already contains cos(dec). Astropy propagates supported rows to the supplied
epoch. Missing-motion/epoch rows are explicitly marked; their reference positions
may be measured diagnostically but never count as epoch-correct associations.

GSPC Johnson-Kron-Cousins B/V/R is not a camera's RGB response. Aperture-level
eligibility and catalogue quality are separate diagnostics; all final
`fit_eligible` values remain false in this version. Flux errors document a
diagonal noise approximation and its missing terms. No complete uncertainty of
resampled data, independent WCS revalidation, or empirically verified aperture
correction is implied by a successful command.

## Next acceptance work

Implement the explicitly gated empirical broadband colour fit in
[NATIVE_COLOR_CALIBRATION_PLAN.md](NATIVE_COLOR_CALIBRATION_PLAN.md), together with
calibrated FITS from independent camera families and observing sessions. Existing
M27 data have unknown historical filters/saturation and no matching flats; they
can test report construction, not validate colour accuracy. The SV220 SII/OIII
7 nm profile has its own narrowband meaning and does not qualify broadband PCC.

Scientific contracts: [ESA GSPC data model](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_performance_verification/ssec_dm_synthetic_photometry_gspc.html),
[Astropy proper motion](https://docs.astropy.org/en/stable/coordinates/apply_space_motion.html),
[Astropy celestial WCS](https://docs.astropy.org/en/stable/wcs/wcstools.html), and
[Photutils aperture photometry](https://photutils.readthedocs.io/en/stable/user_guide/aperture.html).
The aperture implementation is native NumPy/SciPy; Photutils is a reference, not
a new runtime dependency.
