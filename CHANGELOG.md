# Changelog

All notable public changes are documented here. The project follows semantic
versioning while it remains pre-1.0.

## 0.9.6 - 2026-08-31

### Changed

- Batch capture navigation keeps the current/total counter geometrically
  centered between equal-width previous and next controls.
- Fujifilm Color now maps to Phocus Saturation at 5 units per camera step;
  `+3` therefore maps to `+15` instead of `+30`.
- Highlight and shadow tone anchors use a slightly stronger 10-level movement
  per Fujifilm step while preserving the curve endpoints.
- Manual DR100/200/400 remains a highlight-recovery mapping. Fujifilm D Range
  Priority additionally maps Weak/Strong to Phocus Shadow Fill 10/20, matching
  Fujifilm's documented distinction between the two controls.
- DR200 and DR400 highlight recovery are strengthened from 10/20 to 15/30 by
  user preference; DR100 remains the zero-recovery baseline.
- `camera-jpeg` is the new default distortion model. Its final six-parameter
  radial-and-tangential fit uses four training and four holdout scenes, fresh
  generated 3FR files, full-size Phocus renders and original camera JPEGs.
- The 0.9.5 `native-match` model remains selectable as Vendor RAW match, while
  `legacy-in-bounds` continues to preserve the 0.9.3 compatibility geometry.

### Verification

- The final camera-JPEG geometry passed the full-frame image, blink and
  structural-edge review after numerical replay; the user explicitly accepted
  the result. Python, Rust, macOS and Android release gates are recorded in the
  0.9.6 release evidence.

### Research boundary

- The accepted result is a same-camera rendering match, not a claim that
  Fujifilm's proprietary optical function has been recovered exactly. Opening
  in Phocus also remains distinct from spectral or colorimetric equivalence.

## 0.9.5 - 2026-08-30

### Added

- Selectable `native-match` and exact 0.9.3 `legacy-in-bounds` distortion
  models across the conversion core, macOS, web and Android interfaces.
- Visible 0.9.5 version identity in the native apps.
- Bundled sanitized X2D routing template for Android, with external-template
  override and restore-to-bundled control retained.
- Android ISO routing controls aligned with the macOS product defaults.

### Preserved

- Native match remains the recommended default.
- White balance, color mapping, ISO/HNNR, chromatic-aberration and vignetting
  behavior are unchanged by the distortion-model selector.

### Verification

- Python, Rust core/JNI, Swift debug/release and packaged macOS model checks.
- Android unit, debug, release and release-lint builds; dedicated release APK
  signature and bundled-reference integrity checks.
- Real GFX100RF conversion in both distortion modes with donor-preservation
  verification.
- Bilingual five-page quick-guide render review.

## Earlier development releases

Versions 0.3.0 through 0.9.4 established the container transplant, metadata,
preview, WB/color bootstrap, HNNR-safe ISO, lens pipeline, product interfaces,
negative-vignetting safety work and native-render geometry calibration.
