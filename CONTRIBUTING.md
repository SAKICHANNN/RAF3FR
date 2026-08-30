# Contributing

Thank you for helping improve RAF / 3FR.

## Before opening a change

1. Search existing issues and keep each change narrowly scoped.
2. Do not commit camera RAW files, generated 3FR files, donor captures,
   credentials, signing material, local paths or personal metadata.
3. Preserve the scientific claim boundary: successful Phocus rendering is not
   evidence of colorimetric or sensor equivalence.
4. Add regression tests for conversion-core changes and keep Python/Rust wire
   values aligned.

## Local checks

```bash
PYTHONPATH=src python3 -m pytest -q
cargo fmt --manifest-path native/Cargo.toml --all --check
cargo test --manifest-path native/Cargo.toml --workspace
swift build --package-path apps/macos --jobs 2
```

Android changes must additionally build the native arm64 library and run
`testDebugUnitTest assembleDebug` with JDK 17, SDK 36 and NDK 27.3.13750724.

## Pull requests

- Explain the user-visible behavior and capability boundary.
- List files changed and commands run.
- Include screenshots for UI changes, but remove capture metadata and location.
- Do not mix refactoring with a behavioral fix unless they cannot be separated.
- Never include proprietary sample images in a public issue or pull request.

By submitting a contribution, you confirm that you have the right to submit
the material. No broader project license is implied by accepting a change.
