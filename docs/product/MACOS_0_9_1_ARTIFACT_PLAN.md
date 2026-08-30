# RAF3FR macOS 0.9.1 field-of-view, highlight and HNNR plan

## Document role

This is the executable diagnosis and conditional release tracker for plan node
`PDX2ART091`, a child of the RAF-to-3FR macOS product line. It starts from
sealed local 0.9.0 commit `379a50f` on branch
`zhouzi/raf2hncs-0.9.1`. A symptom is not admitted as a release fix until a
same-RAW control isolates its producer layer.

## Goal

Determine whether converted 3FR files unnecessarily lose outer field of view,
whether point-light dark rings are introduced by conversion or by an optional
Phocus rendering migration, and why HNNR can still show a regular grid. Produce
0.9.1 only for fixes that are falsifiable, reversible and do not reduce RAW
integrity or existing HNNR compatibility.

## Non-goals and claim boundary

- Do not call a corrected image wider than the recorded sensor lattice.
- Do not hide HNNR artifacts by smoothing, clipping shadows, raising black or
  disabling inspection at high exposure.
- Do not infer Phocus visual behavior from a thumbnail or container geometry.
- Do not change HNCS/color calibration while testing geometry or HNNR.
- Do not overwrite or delete user-created RAF, 3FR, HNNR or sidecar files.

## Current facts

- `DSCF2834.RAF` is a local ISO 10000, DR200 night scene with point lights.
  Existing sibling outputs include model ISO 6400 and 12800 HNNR results.
- The RAF visible crop is 11648 x 8736. The X2D donor DefaultCrop is
  11656 x 8742 and the mapped content lattice is 11664 x 8750; a simple TIFF
  crop cannot explain a materially narrower view.
- The embedded Fuji 35 mm F4 distortion table reaches -10.098% at its outer
  knot. Current WarpRectilinear fixes `kr0=1`, so the corrected output edge
  samples an inner source radius and necessarily discards outer source content.
- The relevant existing sidecar has USM amount 0, but applies the inverse
  RawExposureBias and DR200 Highlight Recovery 10. Sharpening is therefore not
  the leading point-light-ring cause for this sample.
- Existing ISO evidence shows the same Bayer produces a grid at model ISO
  8000/12800 and clean results at 6400 in tested scenes. The new report means
  6400 must be re-tested on this exact night scene rather than treated as a
  universal guarantee.

## Constraints

- Preserve the 11664 x 8750 CFA lattice, signed sub-black residuals, donor
  identity, source preview, metadata privacy and clean noise flags.
- Keep distortion and lateral CA independently selectable. A field-of-view
  policy must not silently change the meaning of the strength sliders.
- Use unique temporary names and exact auto-cleaned test directories. Source
  hashes must match before and after every conversion.
- Phocus/HNNR remains an external visual gate. If macOS is locked, automated
  evidence may advance but cannot close that gate.

## Tracker

| Step | Status | Scope | Required verification | Commit point | Rollback |
| --- | --- | --- | --- | --- | --- |
| D0 | COMPLETE | Freeze current evidence and controls | Current branch/status; exact RAF/3FR ISO and geometry; official DNG/Phocus semantics | Plan commit | Revert plan |
| D1 | NUMERICAL_PASS_VISUAL_BLOCKED | Quantify field-of-view loss and design a bounded correction scale | Same Fuji profile coordinate maps; identity/current/full-field transforms; no out-of-bounds source samples; independent parser readback | Geometry evidence commit | Keep current centre-scale policy |
| D2 | NUMERICAL_AND_INDEPENDENT_RENDER_PASS | Isolate point-light ring | Same RAW with exposure/DR/warp/CA toggles; RAW saturation and clip counts; Phocus visual A/B when available | Rendering decision commit | Keep migrations independently selectable |
| D3 | SAME_BAYER_EVIDENCE_PASS | Re-open HNNR model gate | Same Bayer at ISO 64/100/400/1600/3200/6400 with identical non-ISO bytes; first-run unique outputs; deep-shadow grid metric plus Phocus visual A/B | HNNR evidence commit | Retain bounded 6400 cap and disclose scene failure |
| D4 | PACKAGE_PASS_EXTERNAL_VISUAL_BLOCKED | Conditionally implement and release 0.9.1 | Targeted tests, full regression, three real conversions, packaged doctor/sign/ZIP, bilingual UI/manual, Phocus/HNNR gate or explicit block | Scoped implementation and release commits | 0.9.0 remains intact |

## Experiments and gates

### Field of view

Compare three WarpRectilinear policies over the exact DNG coordinate equations:

1. identity/no correction;
2. current centre-scale correction (`kr0=1`);
3. bounded full-field correction, uniformly scaling all plane polynomials so
   the farthest corrected output samples the source boundary without exceeding
   it.

The full-field candidate is admissible only if it preserves monotonicity,
keeps every RGB plane in bounds, retains the expected Fuji distortion ordering,
and Phocus shows more source content without blank corners or a new halo.

### Point-light ring

Hold the RAW payload and WB fixed. Compare no sidecar, exposure only, exposure
plus DR, warp without CA, warp plus CA, and the current complete sidecar. The
root cause is the smallest toggle that introduces the ring in a full-quality
Phocus render. If no automated renderer can reproduce Phocus, the decision
remains visually blocked rather than guessed.

### HNNR grid

Produce same-Bayer files whose only intended model-selector difference is ISO.
Every file gets a fresh name and exactly one first HNNR attempt. Automated
analysis measures periodic energy and 32-pixel block-boundary discontinuity in
deep shadows before and after HNNR; final acceptance also requires a 100% zoom
visual check because a low-amplitude curved grid can evade global statistics.

## Definition of done

- Each symptom has a confirmed producer or an explicit unresolved boundary.
- Any admitted change has a regression test proving the producer invariant,
  not merely hiding the symptom.
- 0.9.1 is packaged only if at least one warranted fix is implemented and all
  affected gates pass. Otherwise 0.9.0 remains the latest package and the
  evidence record states why no software change is justified.

## Change propagation

Any geometry policy change must update DNG opcode encoding, manifests, CLI,
web/macOS settings, localization, model tests, manuals and release evidence.
Any HNNR policy change must update ISO mappings, compatibility docs and exact
same-Bayer evidence. Any default-render change must update sidecar tests and
the 0.9.x optimum-default decision. After those parent, child, sibling,
dependency, interface-consumer, validation and documentation impacts are
checked, record propagation evidence and re-integrate the affected leaves
bottom-up before release closure.
