# Compatibility and claim matrix

This matrix is the supported local research scope, not a general promise for
all Hasselblad or Fujifilm files.

| Component | Tested scope | Result | Boundary |
| --- | --- | --- | --- |
| Source camera | GFX100RF firmware 0112; thirteen 16-bit lossless RAF scenes at ISO 40–102400 plus the twelve-file encoding matrix below | PASS | Other Fuji bodies and CFA layouts are rejected |
| RAF encoding matrix | Lossless, lossy, and uncompressed x 14/16-bit x ISO 3200/4000 (`DSCF2632`–`DSCF2643`) | STRUCTURAL PASS | All 12 decode and convert through the packaged macOS engine, preserve the donor ranges, transfer ISO, and finish with zero final below-code-zero clips; Phocus/HNNR validation is still pending, and the manifest currently labels the 14-bit decoder carrier as 16-bit while using the correct 16383 white level |
| Donor | X2D 100C camera-original `B0000079.3FR`, firmware 1.1.0, SHA-256 `dcc5a4…56280` | PASS | Only the observed little-endian, single-strip, uncompressed layout |
| X2D calibration pairs | Five 3FR/FFF pairs in two RawDataUniqueID cohorts; firmware 1.0.0 and 1.1.0; ISO 64/100/400; XCD 38V/55V | PASS PER OBSERVED COHORT | 509,483,760 DefaultCrop samples reproduce exactly; body and firmware effects remain confounded |
| Geometry/CFA | 11664 x 8750 active RGGB lattices, 1:1 at X2D `(124,92)` | PASS | No resize, crop, pad, demosaic, or remosaic in identity mode |
| Phocus | macOS Phocus 4.2.2 | PASS | Genuine/copy/transplant retain full 3FR controls; generic DNG separates |
| WB | Fuji Camera Auto default; As Shot and donor options | PASS | Identity is metadata-only; adaptive and D65 modes map both Bayer channels and the neutral |
| Capture metadata | ISO/SOS, shutter, aperture, EV, time, metering, flash, focal length, 28 mm equivalent, IDs | PASS | The fixed donor ISO slot is SHORT; exact ISO above 65535 and other missing slots remain in JSON; opaque X2D private fields remain donor-derived except the isolated lens dispatch key |
| Default Phocus exposure | Per-file `RawExposureBias` to native `.phos` exposure; RAW payload unchanged | PASS FOR ADMITTED GFX100RF SET | 15 files resolve to +0.72 EV at DR100 or +1.72 EV at DR200; ISO-only and DNG BaselineExposure controls do not alter Phocus brightness |
| Embedded preview | Fuji RAF preview in the fixed donor JPEG slot with synchronized byte count | PASS | Oversize source preview is recompressed to fit; `--preview donor` is diagnostic only and visibly stale |
| Identity sensor mapping | Explicit diagnostic control | PASS | Enters tested X2D/HNCS branch but leaves Fuji white coordinates in the X2D response domain |
| WB-adaptive sensor mapping | Default `wb-adaptive-bootstrap` | EXPERIMENTAL, BOUNDED | Positive diagonal repairs the per-image white point; no paired-camera spectral/color equivalence claim |
| D65 sensor mapping | Explicit `d65-dnglab-bootstrap` | EXPERIMENTAL | Public database matrices only; no X2D Illuminant-A or paired-chart validation |
| X2D inverse calibration | Explicit `--inverse-x2d-calibration`; Web default off; donor cohort selected from RawDataUniqueID | EXACT PAIRED TRANSFORM, EXPERIMENTAL FOR DIRECT 3FR | Two observed cohorts need different gains; unknown cohorts fail closed; direct-edit/HNCS necessity remains unproven |
| XCD lens isolation | Same Fuji mosaic in XCD 38V/55V donors; MakerNote group/tag ablations; default `0x0018` neutralization | PASS | Donor profiles change radial brightness by up to 31%; retagging only `0x0018` removes dispatch while preserving its payload; observed Phocus 4.2.2 scope |
| Fuji lens profile | Per-image schema-v2 profile encoded in 3FR `OpcodeList3`; independent 0-200% distortion/CA/vignetting | IMPLEMENTED, PHOCUS-APPLIED | Phocus radial A/B proves embedded distortion executes; held-out grid/flat/frame-edge CA targets remain unavailable |
| RAW radiometry | Synthetic black/white/ramp plus seven natural scenes | YELLOW | Real dark/flat/chart captures unavailable; no calibrated radiometric/color claim |
| HNNR | Phocus 4.2.2 Purity mode; same-Bayer ISO A/B plus ISO 40–102400 packaged-engine matrix | PASS WITH COMPATIBILITY MODE | Signed sub-black residuals are preserved; model ISO is capped at 6400 above that value; exact capture ISO remains in the record; one donor/version and bounded scenes, not every file or Detail mode |

Recommended bounded workflow:

1. Run `raf2hncs doctor` and `inspect` the donor.
2. Convert with default Camera Auto WB, WB-adaptive sensor mapping, inverse
   3FR-to-FFF compensation off, and donor XCD lens dispatch neutralized. Preserve
   the donor profile only for a bounded diagnostic comparison.
3. Keep distortion and lateral CA at 100% and vignetting at 0% for the preferred
   default, or adjust the three independent strengths before conversion.
4. Open the resulting 3FR in Phocus. Its standard DNG opcodes are applied there;
   no TIFF upload or second correction pass is required.
5. Keep the `.3FR.json` and lens-profile JSON beside the output as the audit
   record.

The twelve-file source-encoding measurements are frozen in
`docs/product/RAF_ENCODING_MATRIX_EVIDENCE.json`. A structural pass means the
source decoder, Bayer-domain mapping, metadata writer, and donor-preservation
verifier passed. It does not erase information already lost in Fuji lossy RAW
compression and does not by itself prove Phocus/HNNR compatibility.

The rejected full-matrix DSCF2166 probe put 6.50% of the active lattice below
black. The positive-diagonal replacement has zero below-black sites and 0.0347%
above-white sites on DSCF2166, and zero clipping on DSCF2098. Phocus discovers
the new file, but the final side-by-side render is still pending because the
current Phocus naming presets reject import before processing. These results
support a bounded WB-domain repair only.

## HNNR protocol and result

Run HNNR from the exact file's thumbnail context menu. The controlled matrix in
`calibration/x2d100c/HNNR_COMPATIBILITY.json` passed for a camera-original X2D
3FR, its byte-identical copy, the ordinary transplant, the recommended
inverse-calibrated transplant, the experimental D65 transplant, and a fresh
transplant with the synchronized Fuji embedded preview. The current default
`0x0018` lens-dispatch-neutralized output also completed on its first Purity-mode
attempt. Every new
file was 213311488 bytes and independently decoded as a 11904 x 8842 X2D 100C
RGGB RAW with a 11664 x 8750 image area. The genuine and identity-copy HNNR
outputs were byte-identical. H2/H3/H4/H6 denoised mosaics correlate 0.99965 or
better with their Fuji inputs and only 0.164--0.175 with the genuine Hasselblad
RAW; HNNR did not substitute donor image content.

Older candidates made before the source-preview fix retain the donor's embedded
JPEG, so their thumbnails can all show the Hasselblad donor even though the RAW
Bayer plane is the Fuji scene. Phocus database/cache state can also temporarily
show a stale donor render. Current conversion defaults to `--preview source`;
the sidecar records both the JPEG hash and its synchronized byte-count patch.
When UI and file evidence disagree, independently decoded RAW identity wins.

Do not diagnose a first failure by immediately running HNNR again. Phocus can
reject the second attempt when a same-named output or a previously denoised
state exists. If a progress bar exits near completion, first preserve and
inspect the newly created `_denoised_*` file (including a partial file), then
rename or isolate a fresh input before any reproduction attempt. The generic
second-run message is not evidence that the original RAW format was unsupported.

The Mac regression is recorded in
`calibration/x2d100c/HNNR_BLACK_NOISE_REGRESSION.json`. Rotation, WB, and the
embedded Fuji lens opcode are not root causes. Same-Bayer A/B tests isolate the
Phocus-facing high ISO as the decisive HNNR model selector: DSCF2541 failed at
8000 and DSCF2610 at 12800, while both were clean at 6400. Additional packaged
outputs at capture ISO 51200 and 102400 complete first-attempt Purity HNNR with
model ISO 6400; the 102400 shadow render remains clean at +4 EV. Since 0.3.0,
the standards-oriented default is `--iso-policy nearest-x2d`: it selects the
closest X2D-supported ISO in EV/log2 space and chooses the lower value at an
exact midpoint. `--iso-policy hnnr-stable` retains the empirically validated
6400 ceiling, while `--iso-policy capture` preserves the Fuji value subject to
the EXIF-short sentinel. Every mode records the exact capture ISO separately.
Preserving signed sub-black residuals remains a necessary low-end integrity
fix, but it was not sufficient by itself to eliminate the high-ISO mosaic.
