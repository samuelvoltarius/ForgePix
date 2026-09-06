# Stack acquisition metadata and accepted coverage

Native ordinary and CFA Drizzle stacks now preserve observation evidence from
the FITS lights actually integrated and the geometric reference actually used.
Current equipment presets do not replace historical headers. Sources are read
only; primary-header hashes, size and modification time are checked before and
after integration. The helper hashes metadata, not the complete pixel payload.

`observation_report.json` retains per-light values, missing/conflicting fields,
time interpretation, reference sampling and processing assumptions. FITS and the
Float32 TIFF description carry matching science headers. Project snapshots and
exports include this report. The solver nests original processing reports in its
own provenance report; no dangling active report filename is added to FITS.

| Evidence | Export behavior |
|---|---|
| Actual contributions | `NCOMBINE` counts integrated files, excluding QC/registration failures. |
| Acquisition duration | `FPTOTEXP` is the sum of known input exposure durations, only when complete. `EXPTIME`, when present, is explicitly the common single-light exposure, not mean-stack brightness or effective gain. |
| Observation time | `DATE/MJD-BEG`, `-END` and `-AVG` require complete, consistent exposure bounds. The average is the duration-weighted mean of exposure midpoints calculated in continuous TAI, represented in UTC. `FPETEXAC=False`: rejection, SNR and Drizzle do not have verified per-pixel time weights. |
| Ambiguous start | Bare `DATE-OBS` does not establish exposure start. An explicit start comment, `DATE-BEG`, supported end plus duration, or the helper's explicit override is required. Incomplete timing stays incomplete. |
| Catalogue epoch | `FPTEPOCH` is the average represented as a TCB Julian year. This time-scale conversion is not a barycentric photon-arrival correction or clock validation. |
| Object/instrument/filter | Only values known and identical in every integrated light become common fields. The historical filter remains unknown when missing. |
| Search hints | RA/DEC and optical sampling come from the actual reference. `PIXSCALE` accounts for the documented camera pixel convention, software binning and output scale. It is a search hint, not WCS. Raw WCS is not copied. |
| Noise and units | Raw `GAIN`, `EGAIN`, saturation and read-noise cards are not inherited as properties of the processed image. Output physical units and variance remain unqualified. Original cards and integer scaling are retained in the JSON evidence. |
| Image domain | Explicit linear/nonlinear headers are respected. Integer Bayer light headers are recorded as a raw-sensor linearity assumption. Unknown Float-FITS do not acquire a linearity assertion, including Drizzle. Post-integration pixel corrections are recorded separately. |

All six ordinary integrators can return actual accepted support. `FPCOV` is true
only when every channel has an accepted contribution, including after rejection;
software binning requires every constituent pixel to be covered. Real zero-valued
measurements remain valid. A union of input masks cannot prove accepted support
when rejection removes every sample in one channel. Coverage reporting itself
does not change pixel values. A separate numerical correction uses stable
Float64 statistics for Sigma/Winsor so roundoff cannot reject identical frames;
an empty refinement retains the previous bounds instead of inventing a zero model.
This binary mask is neither a rejection-count map, variance nor exposure map.

Known holes block the existing whole-image AI and solver adapters, which do not
yet support partial coverage. The CLI aperture diagnostics already handle such
holes locally. Background correction/deconvolution/denoising during integration
also stop on known holes rather than process placeholders as measured pixels.
Non-FITS/external workflows without verified contributors retain an explicit
unavailable metadata report instead of invented FITS acquisition evidence.

Validation includes independent time-scale/leap-second and missing-evidence
tests, actual-reference and dropped-frame fixtures, all six integration methods,
single-channel rejection, binning and FITS/TIFF/project round trips. Package smoke
executes both ordinary and CFA Drizzle exports. Exact-commit real-data and package
evidence belongs in RELEASE_WORKLOG.md; none of these contracts qualifies PCC,
camera-independent AI or an RC by itself.
