# Installation and runtime

## macOS application

Download `RAF3FR-0.9.6-macOS-arm64.zip` from the GitHub Release, expand it and
move `RAF3FR.app` to Applications. The 0.9.6 build supports Apple silicon and
macOS 14 or later. It is ad-hoc signed but not Apple-notarized, so macOS may
require an explicit first-open confirmation.

Phocus is not required for conversion. Install Phocus separately only when the
result should be opened or rendered there.

## Android application

Download `RAF3FR-0.9.6-android-arm64.apk` from the GitHub Release and allow your
file manager or browser to install that package. It supports arm64 Android
devices running Android 8.0 (API 26) or later. The APK is signed with the
project's dedicated release certificate and is not a Play Store package.

Both applications bundle the sanitized X2D routing reference used by the
converter. Choosing an external compatible reference is optional.

## Local web interface

Create a Python environment and install the project from a checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
PYTHONPATH=src python -m raf2hncs.web
```

The page opens at `http://127.0.0.1:8765/`. The service is loopback-only; it
does not upload RAF or 3FR files. Runtime data is stored beneath the current
user's Application Support directory.

## Development prerequisites

The Python converter discovers ExifTool, LibRaw, DNGLab and the macOS `sips`
utility through its documented tool paths. Run the environment check before
converting:

```bash
raf2hncs doctor
```

Android development requires JDK 17, Android SDK 36, NDK `27.3.13750724`, and
the Rust `aarch64-linux-android` target. No project signing key is stored in the
repository; public CI builds an unsigned/debug validation artifact only.

After moving a checkout or changing any converter dependency, rerun `doctor`,
the automated tests, `inspect`, and `verify`. Phocus compatibility should be
treated as separately observed behavior for the specific Phocus version used.
