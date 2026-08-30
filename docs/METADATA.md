# Metadata policy

The converted 3FR has two simultaneous requirements: describe the Fuji capture
truthfully, and retain only the X2D identity needed for the tested Phocus branch.
The converter never claims that donor-private fields came from the Fuji camera.

| Class | Treatment |
| --- | --- |
| Capture facts | Copy RAF exposure time, f-number, ISO, exposure program and compensation, metering, flash, focal length, color space, and capture/modify time into existing standard TIFF/EXIF slots |
| Rendering exposure | Record Fuji `RawExposureBias`, dynamic-range metadata, and the recommended Phocus compensation in JSON; macOS writes the inverse bias to its native `.phos` sidecar without scaling RAW codes |
| White balance | Fuji Camera Auto by default; As Shot and donor choices remain explicit; values stay metadata rather than Bayer multiplication |
| Fixed lens | Write `FUJIFILM` / compact `35mm F4`; retain the full `FUJINON 35mm F4 fixed lens` description in sidecars and embed per-image optical operations in Raw IFD `OpcodeList3` |
| Derived facts | Compute 35mm equivalent as `round(focal_mm * hypot(36,24) / hypot(43.8,32.9))`; for 35 mm this is 28 mm |
| Unique IDs | MD5 the final full X2D RAW payload; write those 16 bytes as `RawDataUniqueID` and their 32-character uppercase hex as `ImageUniqueID` |
| No donor slot | Preserve timezone, subseconds, exposure mode, source WB mode, optional GPS, and other standard source fields in the JSON sidecar without restructuring the donor IFDs |
| Branch/private identity | Preserve X2D Make/Model, DNG color identity, dimensions, container structure, and every private MakerNote byte except the two-byte XCD lens-dispatch tag word neutralized by default |

This slot-preserving policy is deliberate. Adding new IFD entries would relocate
data and could invalidate opaque MakerNote offsets. A future final-export stage
may write the sidecar-only standard fields into TIFF/JPEG metadata after Phocus,
where no X2D RAW dispatch contract has to be preserved.

The converted 3FR records source-authentic public lens metadata and embeds the
selected per-image distortion, lateral-CA, and optional vignetting operations
without dispatching on a hard-coded camera or lens string. Final exported image
metadata remains Phocus's responsibility; the converter no longer accepts or
rewrites a rendered TIFF.

On the tested Phocus 4.2.2 runtime, replacing the standard donor lens identity
with `FUJIFILM / 35mm F4` keeps the full 3FR RAW adjustment branch but does not
by itself stop private donor correction. Controlled XCD 38V/55V MakerNote
ablations identify `0x0018` as the lens-profile dispatch key. The converter now
retags only that directory word to `0xff18` by default, preserving its 17-byte
payload, tag `0x0017`, and all other MakerNote data. This removes the automatic
donor vignette; the Fuji embedded profile remains available after HNCS render.
