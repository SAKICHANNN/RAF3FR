# RAF / 3FR

RAF / 3FR converts Fujifilm GFX100RF RAF files into X2D 100C-style 3FR
containers for editing in Hasselblad Phocus. It provides a native macOS app,
an Android app, a local web interface, and a command-line research tool.

The converter preserves the native Bayer lattice, migrates supported capture
metadata, embeds the source preview, and expresses the GFX100RF lens profile as
editable DNG opcodes. The current development source offers three distortion
models. Version 0.9.7 defaults to Camera JPEG match while preserving the two
earlier geometries:

- **Camera JPEG match** is the default introduced in 0.9.6, fitted from full-size Phocus
  renders and accepted against original same-capture Fujifilm camera JPEGs.
- **Vendor RAW match** preserves 0.9.5's Native match geometry calibrated
  against Fujifilm's native RAW rendering.
- **Legacy no-blank-edge** reproduces the 0.9.3 maximum-in-bounds framing for
  comparison and personal preference.

## Download

Installable builds are published on the
[GitHub Releases](https://github.com/SAKICHANNN/RAF3FR/releases) page.

- macOS: Apple silicon, macOS 14 or later. The current build is ad-hoc signed
  and is not Apple-notarized.
- Android: arm64, Android 8.0 (API 26) or later. The GitHub APK is intended for
  direct side-loading and is not a Play Store package.

Both apps default to English and provide an immediate `En / 中` language
switch. The sanitized X2D routing template is bundled; an external compatible
template remains optional.

## What 0.9.7 does

- Maps the complete 11664 x 8750 GFX100RF Bayer lattice into the matching X2D
  image-content lattice without demosaic/remosaic.
- Uses Fujifilm Camera Auto WB by default, with As Shot and donor controls.
- Preserves source preview and supported exposure, ISO, lens and capture data.
- Lets macOS batch users remove the currently viewed RAF from the selection
  without deleting or modifying the source file.
- Embeds distortion, lateral chromatic-aberration and optional vignetting
  operations for the Phocus RAW path.
- Defaults to HNNR-safe ISO routing and preserves the exact capture sensitivity
  in the conversion record.
- Refuses unsupported geometry, compressed/incomplete donors and output
  overwrite; verifies donor preservation after conversion.

The macOS app also writes an editable sibling `.3FR.phos` rendering sidecar for
Phocus-specific exposure, DR, tone, grain and framing intent. Android produces
the verified 3FR and JSON audit record; it does not claim macOS Phocus-sidecar
parity because Phocus is not available on Android.

## Scientific boundary

Opening and rendering in Phocus proves container and processing-path
compatibility. It does **not** prove that a converted Fujifilm capture is
spectrally or colorimetrically identical to a native X2D capture. The current
Fuji-to-X2D sensor transform remains a bounded bootstrap until paired-camera
ColorChecker measurements are available.

This project is independent and is not affiliated with or endorsed by
Fujifilm, Hasselblad, DJI or Sony. Product and company names belong to their
respective owners.

## Build and test

Python and web:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
PYTHONPATH=src python -m pytest -q
```

Rust portable core:

```bash
cargo test --manifest-path native/Cargo.toml --workspace
```

macOS:

```bash
scripts/bootstrap_macos_release.sh
scripts/build_macos_release.sh
```

Android requires JDK 17, Android SDK 36, NDK `27.3.13750724`, and the Rust
`aarch64-linux-android` target:

```bash
scripts/build_android_native.sh
JAVA_HOME=/path/to/jdk17 apps/android/gradlew -p apps/android \
  testDebugUnitTest assembleDebug
```

More detail is available in [Installation](docs/INSTALL.md),
[Compatibility](docs/COMPATIBILITY.md), and [Metadata](docs/METADATA.md).

## Security and privacy

Conversion is local. RAF files and generated 3FR files are not uploaded by the
applications. Serial-number and face metadata are excluded, missing fields are
not invented, and optional GPS/rights/provenance migration is independently
controllable. See [Security policy](SECURITY.md) for responsible reporting.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. No
third-party license is granted by this repository at present; do not assume
permission to redistribute modified builds or source outside GitHub without
the owner's written permission.
