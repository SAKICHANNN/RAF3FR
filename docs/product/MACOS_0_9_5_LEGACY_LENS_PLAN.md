# RAF / 3FR 0.9.5 Legacy Lens Compatibility Plan

## Contract

Node: `PDX2LENS095`

Add an explicit distortion-model choice while preserving 0.9.4 as the default:

- `native-match`: calibrated GFX100RF native-render geometry introduced in 0.9.4;
- `legacy-in-bounds`: exact 0.9.3 maximum-in-bounds common-scale geometry;
- distortion disabled remains the existing zero-strength identity path.

The model selection changes only distortion geometry. CA strength, vignette
policy, Bayer payload, WB, exposure, color, ISO and HNNR behavior are unchanged.

## Execution and evidence

| Leaf | Status | Evidence |
| --- | --- | --- |
| L1 Core contract | DONE | Python and Rust accept the same stable wire values; old callers default to `native-match` |
| L2 Product controls | DONE | macOS, web and Android expose bilingual/native labels without crowding the conversion hero |
| L3 Regression | DONE | exact 0.9.3 coefficient equality, 0.9.4 default equality, disabled identity, 107 Python and 20+3 Rust tests |
| L4 Release | DONE_BOUNDED | 0.9.5/build 16, bilingual manuals, signed macOS archive, signed Android APK and real dual-mode RAF conversion; Android host-emulator runtime remains unclaimed |

## Rollback and boundary

Reverting the core compatibility commit removes the selector and restores the
0.9.4 default without changing stored RAW files. `legacy-in-bounds` is preserved
for comparison and preference, not presented as more accurate than
`native-match`.
