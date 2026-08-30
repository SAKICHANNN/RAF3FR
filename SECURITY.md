# Security Policy

## Supported version

Security fixes target the newest published release.

## Reporting a vulnerability

Do not open a public issue for a vulnerability, credential exposure or sample
file containing personal metadata. Use GitHub's private vulnerability reporting
feature for this repository. Include the affected version, platform, minimal
reproduction and impact. Do not attach camera originals unless explicitly
requested through a private channel.

## Data handling

The applications process files locally and do not require a network service.
They intentionally refuse output overwrite and verify donor preservation.
Signing keys, GitHub credentials and raw test captures are not repository
assets and must never be committed.

The macOS release is currently ad-hoc signed rather than notarized. The Android
GitHub build is for direct side-loading rather than Play Store distribution.
