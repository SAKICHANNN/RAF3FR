# RAF/3FR Geometry Matching Plan — macOS 0.9.4

## Document role

This is the executable diagnosis, implementation and release tracker for
`PDX2GEO094`. It supersedes the 0.9.1 maximum-in-bounds framing decision only
where current real Phocus evidence shows that decision does not match the RAF
render. It does not replace prior lens-profile or HNNR evidence.

## Current state

- Branch: `zhouzi/raf2hncs-0.9.4`, based on the sealed 0.9.3 source.
- The RAF contains nine geometric samples ending at `-10.09809875%`.
- The 0.9.3 Python/macOS opcode fits those samples to DNG
  `WarpRectilinear`, then multiplies every RGB coefficient by an independently
  derived in-bounds framing scale (`1.0330723395301635` for DSCF2961).
- The Rust/Android encoder fits the same polynomial but does not apply that
  framing scale. This is an existing cross-engine semantic mismatch.
- DSCF2961 proves that Phocus executes the generated opcode when its sidecar
  uses `ApplyLensCorrection=true` and mask 6, but the corrected geometry still
  differs visibly from Phocus' RAF render.

## Goal and non-goals

Goal: make the default 3FR distortion geometry match Phocus' corrected RAF
geometry as closely as the admitted DNG opcode and Fuji metadata permit, while
preserving Bayer samples, noise statistics, HNNR eligibility and independent
distortion/CA controls.

Non-goals:

- no Bayer-domain geometric resampling;
- no color, WB, exposure, DR, vignette or HNNR policy changes;
- no claim of pixel-identical reproduction of a proprietary decoder;
- no hidden crop selected only to make one scene appear similar.

## Hypotheses and decision rules

1. **H1 — framing-scale mismatch (leading):** the extra common coefficient
   scale is the dominant visible difference. Remove it if multi-scene edge
   registration improves without blank borders or non-monotone mapping.
2. **H2 — cubic-fit residual:** after H1, residual geometry follows radius and
   exceeds two output pixels. Consider a higher-order DNG opcode only if Phocus
   support is proven and held-out error materially improves.
3. **H3 — center/crop mismatch:** after H1, residuals are asymmetric or contain
   a translation. Fit optical center/crop only from multiple scenes and retain
   a held-out scene; do not infer it from one photograph.
4. **Invalid result:** tone/color differences prevent robust registration, or
   the third-party renderer does not execute the same path as Phocus. Keep the
   numerical change blocked and use a Phocus-rendered grid/architecture A/B.

## Constraints and interfaces

- Preserve the 11664×8750 CFA lattice and source RAF bytes.
- Keep DNG OpcodeList3 as the correction stage and sidecar mask semantics from
  0.9.3 (`2 distortion | 4 CA | 1 positive vignette`).
- Python and Rust encoders must emit the same coefficient semantics.
- Use unique temporary outputs and delete only artifacts created by this plan.
- The final archive remains ad-hoc signed Apple Silicon; no push or publishing.

## Tracker

| Step | Status | Scope | Required verification | Commit point | Rollback |
| --- | --- | --- | --- | --- | --- |
| G0 | DONE | Freeze 0.9.3 trigger and competing hypotheses | Exact RAF profile, generated opcode, crop and sidecar readback | Plan commit | Revert plan commit |
| G1 | DONE | Build multi-scene corrected-RAF versus 3FR geometry measurements | Five scenes; identical-decoder on/off controls; three train/two holdout; durable metrics | Evidence commit | Keep 0.9.3 scale |
| G2 | DONE | Implement the smallest supported coefficient/crop correction in Python and Rust | Unit parity, monotonicity, boundary and strength controls | `4d4a82e` | Revert implementation commit |
| G3 | DONE | Real packaged conversion and Phocus A/B | Fresh output, opcode/sidecar readback, corrected FOV inspection and source hash | Release evidence commit | Restore 0.9.3 package |
| G4 | DONE | Version, manuals, package and release evidence | Full tests, model checks, bilingual PDF, signature and ZIP integrity | `3fc60ac` plus release evidence | 0.9.3 archive remains installable |

## Validation and collateral proof

- Root-cause proof: compare otherwise identical opcodes with common scale 1.0
  and 1.033072; the selected path must reduce multi-scene geometry residual.
- Trigger proof: the 0.9.3 output must reproduce the observed difference while
  the RAF vendor correction and 3FR opcode are both enabled.
- Collateral proof: distortion disabled remains identity; signed strength
  remains reversible; CA plane ordering and vignette policy remain unchanged;
  Python/Rust full test suites pass.
- Equivalent-trigger proof: test at least three RAFs with different exposure,
  ISO and scene content so the decision is not tied to DSCF2961.

## Rollback and claim boundary

Every implementation leaf receives a narrow local commit. Reverting the
geometry commit restores 0.9.3 coefficient semantics; the 0.9.3 ZIP remains
untouched. Completion permits the claim that held-out tested scenes are closer
to the native RAF render. It does not permit claiming access to Fujifilm's or
Apple's proprietary calibration.

## Closure evidence

- Five-scene same-decoder calibration used three train and two held-out RAFs.
  On the held-out scenes, the new model reduced the native-render registration
  median from 1.199 px to 0.540 px, p90 from 2.372 px to 0.933 px and p99 from
  9.091 px to 2.471 px at the 2400x1800 measurement scale.
- A direct Phocus A/B of DSCF2961 used the same clean sidecar and 11% display
  scale for the RAF, 0.9.3 control and 0.9.4 candidate. The 0.9.4-to-RAF screen
  residual median was 0.329 px versus 0.481 px for 0.9.3; p90 was 0.890 versus
  1.102 px and p99 was 1.786 versus 2.142 px.
- The final candidate preserves the full CFA lattice, reports
  `gfx100rf_native_vendor_render_match_v1`, writes the calibrated centre and
  retains the sidecar lens mask `true/6`. No Bayer-domain resampling was added.
