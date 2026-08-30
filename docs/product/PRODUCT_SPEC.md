# raf2hncs Product Specification

Status: executable product contract for Web, macOS, and Android.

## Product promise

Convert a supported Fujifilm GFX100RF RAF into the tested X2D 100C-style 3FR
container locally, with the selected white-balance, sensor, metadata, and lens
policies recorded and verified. The primary screen should feel like a precise
photographic instrument, not a research dashboard or an instructional landing
page.

The visual direction takes principles from Hasselblad's restrained Scandinavian
industrial design: dark graphite surfaces, high-contrast typography, sparse
orange focus colour, exact alignment, and calm motion. It must not use
Hasselblad trademarks, logos, product photography, or copied UI assets.

## Shared experience contract

The default path has one obvious sequence:

1. Select a RAF.
2. Confirm output name/location when the platform requires it.
3. Convert.
4. See verified completion and open/share the 3FR.

Every release bundles a sanitized, integrity-checked X2D container template as
the default donor. Fixed-capacity RAW and preview regions are replaced with
deterministic non-photographic payloads; photographer identity, body/lens serial
numbers, and unnecessary capture-specific identifiers are removed or replaced
with deterministic neutral values. Only fields proven necessary for the
supported container contract remain. Selecting an external X2D donor is an
advanced diagnostic override, never first-run setup. If the bundled donor is
missing, modified, or fails validation, conversion is disabled with a specific
error.

Advanced sensor and donor controls are hidden behind settings. The main surface
exposes only white balance and the three lens components; distortion and
lateral CA default to 100%, vignetting to 0%. Negative vignetting uses the
full-plane physical CFA model by default, with an explicit skip option. Every lens-strength control pairs
its slider with an editable numeric field. Mouse, touch, and keyboard input are
all supported; slider and field stay synchronized, enforce the same documented
range, and expose an accessible value in both languages.

Every Web, macOS, and Android surface has an always-visible `中 / EN` control.
The choice persists independently on each platform and applies immediately to
navigation, controls, settings, job stages, history, notifications, validation,
and error states. Filenames, camera metadata, hashes, and engine diagnostics are
never mistranslated or altered.

Product copy uses short photographic language. Remove hero slogans, step
numbers, explanations of obvious controls, decorative status claims, research
jargon, and repeated caveats from the main workflow. Technical boundaries,
hashes, calibration cohorts, and manifests remain available in a details view.

Every platform covers: first run/no donor, ready/no RAF, selected, converting,
verifying, complete, failed, interrupted, insufficient storage, invalid file,
and inaccessible output states. A progress indicator never invents a percent;
stage and transferred-byte progress are shown separately.

## Web single page

- Desktop: compact top bar, central conversion card, persistent activity pane,
  and collapsible recent results within one page. No marketing hero.
- Narrow/mobile browser: single column; current conversion before history;
  touch targets at least 44 CSS px; no horizontal overflow at 320 CSS px.
- Keyboard: all controls reachable, visible focus, Enter/Space activation, and
  drag/drop paired with a file input.
- The server remains loopback-only and owns all writable paths.

## macOS application

- SwiftUI/AppKit single-window utility with native title-bar toolbar and
  Settings scene.
- Native Open panel, drag/drop, Save/Reveal in Finder, Quick Look/open in
  Phocus, menu commands, keyboard shortcuts, notifications, and accessibility.
- The sanitized bundled donor is the default. A security-scoped bookmark is
  used only when the user deliberately selects an external donor override.
- Background conversion is cancellable before publication and survives UI
  state changes. The source and donor remain immutable.
- Distribution bundle contains the converter runtime and pinned tools. A
  release archive must not rely on Homebrew or the user's Python installation.

## Android application

- Jetpack Compose Material 3 with a restrained product theme, edge-to-edge
  layout, native system sheets, and no embedded WebView.
- Storage Access Framework `OpenDocument`/`CreateDocument`; URI permissions are
  persisted for RAF/output access and optional external-donor overrides. No
  broad storage permission.
- Compact windows use a single task surface and bottom-sheet settings. Expanded
  windows use an adaptive main/supporting-pane layout, not a stretched phone UI.
- Conversion runs as a foreground, cancellable task with durable state and a
  completion notification. The app reports storage and thermal failures
  honestly.
- Offline conversion is mandatory for release. It may not upload RAW files or
  require a companion Mac. The portable engine must match the Python reference
  on structural output, active Bayer payload, metadata policy, opcode payload,
  manifest semantics, and verification result.

## Release definition

Every release first verifies the bundled donor hash and structural allowlist,
proves that its RAW/preview/identity/serial payloads were sanitized, exercises
the missing/corrupt-resource failure state, and checks keyboard-editable lens
values plus slider/field synchronization.

Web release requires unit/API tests, JavaScript syntax, accessibility/static
checks, real browser QA at desktop and phone widths, empty/error/success states,
and one real conversion/download round trip.

macOS release candidate requires clean Swift build/tests, a bundled-engine
smoke on a clean-path bundle, menu/keyboard/accessibility checks, one real
conversion, source immutability, output verification, and an installable `.app`
plus archive. Developer ID signing and notarisation remain a human credential
gate if no identity is installed.

Android release candidate requires clean Gradle lint/unit/instrumentation tests,
compact/expanded/font-scale screenshot checks, process-recreation and URI
permission tests, one real on-device/emulator conversion, cross-engine parity,
and an unsigned release AAB/APK. Play signing remains a human credential gate.
