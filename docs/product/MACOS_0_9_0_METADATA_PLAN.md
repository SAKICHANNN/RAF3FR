# RAF3FR macOS 0.9.0 metadata and framing fidelity plan

## Document role

This is the executable implementation plan for `PDX2META`. It starts from the
sealed macOS 0.8.0 release on `zhouzi/raf2hncs-0.9.0`; it does not replace the
scientific calibration artifacts or release-evidence record.

## Goal

Preserve every GFX100RF field that can be transferred without inventing a
Hasselblad capture fact. Exact capture facts must survive in the 3FR, standard
XMP, reversible Phocus sidecar, or conversion manifest according to the
consumer that can represent them. Fuji creative intent must be visible and
independently selectable, but may affect the Phocus render only after an
explicit mapping and validation gate passes.

## Non-goals and claim boundary

- Do not replace the Hasselblad `Make`, `Model`, DNG colour identity or private
  camera MakerNotes with Fuji identity.
- Do not copy Fuji/internal serial numbers or face names, birthdays, categories
  or positions.
- Do not describe source RAF compression or bit depth as the target 3FR's
  physical encoding.
- Do not claim that a Phocus approximation is byte-identical to the Fuji JPEG
  engine, a Fuji film simulation, or a hidden HNCS stage.
- Do not auto-apply camera roll, focus point, AF, shutter, drive or warning
  fields as image corrections.

## Current state

- Version 0.8.0/build 10 is sealed at commit `65dcc1b`.
- Exposure, DR100/200/400, highlight/shadow tone and grain are already decoded;
  exposure and DR default on while approximate tone and grain default off.
- Existing in-container metadata patching is fixed-slot and preserves donor
  ranges. DNG lens opcodes use an append-only replacement-IFD pattern.
- The donor has an existing IFD0 Orientation slot and XMP packet, but no GPS
  IFD. The clean Phocus sidecar has reversible crop, rotation, saturation,
  clarity, sharpening, noise and colour-adjustment fields.
- Seventeen local GFX100RF RAFs prove Orientation 8, 4:3/1:1/65:24 aspect
  ratios, a Digital Tele-Conv crop, per-file timestamps, and optional GPS.

## Constraints

- Preserve RAW-strip bytes, preview integrity, donor colour calibration and the
  private-lens neutralisation boundary.
- New metadata is append-only where a donor slot is absent; verification must
  declare and hash every appended range.
- Preserve the user's preferred defaults: English launch; Fuji camera AWB;
  distortion and lateral CA at 100%; vignetting off; donor lens identity
  neutralised; WB-adaptive sensor mapping; inverse X2D calibration off. Change
  default ISO selection to HNNR-stable and enable every admitted Phocus
  rendering migration by default.
- Batch conversion and isolated packaged operation must remain supported.
- One verified leaf per local commit; no push, install replacement or public
  release without a separately sealed release node.

## Implementation tracker

| Step | Status | Scope | Required verification | Commit point | Rollback |
| --- | --- | --- | --- | --- | --- |
| M0 | DONE | Freeze plan, field classes and source/destination contracts | Branch/worktree clean; plan and tracker review; DRPT lint PASS | `97bf97f`, `50743fd` | Revert plan commits |
| M1 | DONE | Decode exact framing, standard metadata and remaining Fuji creative intent | 98 Python tests; real zoom/GPS and portrait-orientation source summaries; missing/unknown values fail soft | `feat(metadata): decode complete Fuji intent` | Revert decoder commit |
| M2 | DONE | Preserve Orientation and append standard provenance/XMP metadata without moving RAW/preview | 101 Python tests; real DSCF2009 GPS/provenance/zoom XMP; replacement-IFD byte-range tests | `feat(metadata): preserve orientation and provenance` | Disable append path/revert commit |
| M3 | DONE | Rebuild aspect-ratio and Digital Tele-Conv framing in `.phos` | Swift 4:3 zoom, 1:1, 65:24 normalized-crop tests; Orientation remains container-owned to prevent double rotation | `feat(macOS): preserve Fuji framing` | Turn framing toggle off |
| M4 | DONE | Add GPS/time/rating/rights controls and privacy policy | 104 Python tests; policy-removal from pre-existing XMP; independent CLI/macOS arguments | `feat(metadata): add migration privacy policies` | Disable metadata categories |
| M5 | DONE | Display all safe capture/creative facts and expose independent bilingual controls | Swift build/model checks; complete schema fixture; >=40 pt new action target; bilingual copy | `feat(macOS): expose complete Fuji intent` | Disable individual toggles |
| M6 | DONE | Admit evidence-backed or explicitly bounded Phocus mappings for saturation, contrast, clarity, sharpness and neutral BW; reject unsafe/no-equivalent fields | official semantics; installed Phocus preset anchors; sidecar readback; forced-noise flags remain false | `feat(macOS): migrate safe Fuji creative intent` | Disable independent mappings |
| M7 | DONE_LOCAL_WITH_VISUAL_DEFERRED | Full conversion, Phocus/HNNR, batch, package and release evidence | 104 Python + 20 Rust tests; Swift debug/release/model checks; real portrait/crop/GPS conversions; packaged doctor/sign/ZIP/manual QA. Live UI, Phocus render and HNNR visual replay are explicitly deferred because the Mac remained locked. | Release evidence commits | 0.8.0 remains installable |

## Source-to-destination contract

### Exact and default-on

- `Orientation` -> existing IFD0 Orientation. Sidecar rotation stays zero so
  Phocus does not apply the same camera rotation twice.
- `RawImageAspectRatio`, `RawZoomActive`, `RawZoomTopLeft`, `RawZoomSize`,
  `CropMode` -> reversible Phocus relative crop over the full linear RAW.
- offset/subsecond capture time -> standard XMP time fields.
- GPS latitude/longitude/altitude/date/time -> standard EXIF/XMP semantics with
  a user-visible preserve/remove-location option.
- Rating, artist, copyright and user comment -> standard XMP/IPTC only when
  present.
- original Fuji make/model and source filename -> private `raf3fr` provenance
  namespace and manifest; never the Phocus-routing camera tags.

### Record/display only

- shutter/drive/AF/focus point/flash compensation/flicker/warnings;
- camera elevation and roll;
- firmware, source compression/depth, LMO and composite-capture facts.

### Independently selectable; enabled by default after admission

- film simulation and monochrome warm/cool/green-magenta intent;
- Fuji Color/Saturation, Color Chrome and Color Chrome FX Blue;
- Clarity, Sharpness and High ISO Noise Reduction.

Before admission these fields remain record-only rather than presenting a
misleading enabled no-op. Sharpening/noise mappings must additionally prove that
their application order does not reintroduce forced smoothing, grid patterns or
other HNNR regressions.

## Validation gates

1. **Container gate:** only declared TIFF pointer/slot and append ranges may
   differ outside existing payload/preview/lens ranges.
2. **Framing gate:** source preview framing and Phocus crop must agree at all
   four edges within two source pixels after lattice mapping.
3. **Metadata gate:** ExifTool and an independent XML parser must read the same
   standard values; absent fields must create no fabricated defaults.
4. **Privacy gate:** no source/internal serial or face identity/geometry may
   appear in 3FR, XMP, `.phos`, manifest or UI.
5. **Render gate:** a direct mapping needs controlled image evidence. When no
   direct equivalent exists, only a bounded, monotonic, reversible semantic
   approximation may be admitted, and it must be labelled as approximate.
   Fields with no safe monotonic equivalent remain record-only. In particular,
   no mapping may enable `NoiseFilterBias` or `CNFilter`.
6. **Compatibility gate:** genuine donor, converted 3FR, Phocus open/render and
   HNNR first-run controls must remain valid; a thumbnail alone is not proof.
7. **Release gate:** packaged doctor, source verification, deep signature,
   archive integrity, bilingual UI and batch conversion must all pass.

## Success criteria / definition of done

M0-M6 are `DONE` and M7 is locally complete with any blocked visual replay
explicitly named; every exact field round-trips through its declared consumer;
the privacy scan is empty; creative mappings either pass the render gate or are
visibly record-only; full regression and three representative real conversions
pass; release evidence identifies the archive hash and every remaining claim
boundary; the worktree is clean after the final scoped commit.

## Change propagation

Any schema change must update Python manifest/source presentation, Swift
decoding, UI/localization, sidecar writer, tests, release docs and the manual.
Any new append-only TIFF structure must update verify-range validation and
release evidence. Any mapping rejected by M6 remains visible as recorded intent
but cannot silently fall back to a guessed Phocus value.

After each meaningful change, check parent impact, child/dependency impact,
sibling features, interface consumers, validation and documentation, record the
propagation evidence, and re-integrate the affected leaves bottom-up before the
parent node may close.
