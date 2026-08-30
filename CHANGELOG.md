# Changelog

All notable public changes are documented here. The project follows semantic
versioning while it remains pre-1.0.

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
