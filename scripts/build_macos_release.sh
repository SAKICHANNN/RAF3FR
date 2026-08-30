#!/bin/zsh
set -euo pipefail

project_root=${0:A:h:h}
packaging_python="$project_root/.tools/macos-packaging-venv/bin/python"
release_root="$project_root/build/macos"
app_path="$release_root/RAF3FR.app"
contents="$app_path/Contents"
swift_product="$project_root/apps/macos/.build/arm64-apple-macosx/release/RAF3FRMac"
engine_dist="$release_root/engine-dist"
donor_asset="$project_root/apps/macos/Resources/SanitizedX2DTemplate.3FR.gz"
release_version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$project_root/apps/macos/Support/Info.plist")
manual_en="$project_root/apps/macos/Resources/RAF3FR-$release_version-Quick-Guide-EN.pdf"
manual_zh="$project_root/apps/macos/Resources/RAF3FR-$release_version-Quick-Guide-ZH.pdf"
donor_sha256="1e7373384843a803eb986b42bf75e044142f029805db86018fa2f68b47643fd6"

if [[ ! -x "$packaging_python" ]]; then
  print -u2 "Missing macOS packaging environment. Run scripts/bootstrap_macos_release.sh."
  exit 2
fi
if [[ ! -f "$donor_asset" ]]; then
  print -u2 "Missing sanitized X2D template build asset."
  exit 2
fi
if [[ ! -f "$manual_en" || ! -f "$manual_zh" ]]; then
  print -u2 "Missing $release_version PDF quick guides."
  exit 2
fi

rm -rf "$release_root"
mkdir -p "$release_root" "$contents/MacOS" "$contents/Resources/Tools/bin"

swift build --package-path "$project_root/apps/macos" -c release --jobs 2
"$packaging_python" -m PyInstaller \
  --noconfirm --clean --onefile \
  --exclude-module cv2 \
  --exclude-module matplotlib \
  --exclude-module paddle \
  --exclude-module pandas \
  --exclude-module PIL \
  --exclude-module pytest \
  --exclude-module sklearn \
  --exclude-module torch \
  --name raf2hncs-engine \
  --distpath "$engine_dist" \
  --workpath "$release_root/engine-build" \
  --specpath "$release_root" \
  --paths "$project_root/src" \
  "$project_root/apps/macos/Support/engine_entry.py"

install -m 755 "$swift_product" "$contents/MacOS/RAF3FRMac"
install -m 755 "$engine_dist/raf2hncs-engine" "$contents/MacOS/raf2hncs-engine"
install -m 644 "$project_root/apps/macos/Support/Info.plist" "$contents/Info.plist"
install -m 644 "$project_root/apps/macos/Support/AppIcon.icns" "$contents/Resources/AppIcon.icns"
install -m 644 "$project_root/apps/macos/Resources/CleanPhocusTemplate.phos" "$contents/Resources/CleanPhocusTemplate.phos"
install -m 644 "$manual_en" "$contents/Resources/RAF3FR-$release_version-Quick-Guide-EN.pdf"
install -m 644 "$manual_zh" "$contents/Resources/RAF3FR-$release_version-Quick-Guide-ZH.pdf"
install -m 644 "$project_root/assets/fonts/Outfit-Variable.ttf" "$contents/Resources/Outfit-Variable.ttf"
gzip -dc "$donor_asset" > "$contents/Resources/SanitizedX2DTemplate.3FR"
actual_donor_sha256=$(shasum -a 256 "$contents/Resources/SanitizedX2DTemplate.3FR" | cut -d ' ' -f 1)
if [[ "$actual_donor_sha256" != "$donor_sha256" ]]; then
  print -u2 "Sanitized X2D template hash mismatch."
  exit 2
fi

for tool_name in dnglab raw-identify unprocessed_raw; do
  tool_source=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$project_root/.tools/bin/$tool_name")
  install -m 755 "$tool_source" "$contents/Resources/Tools/bin/$tool_name"
done
exiftool_source=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$project_root/.tools/bin/exiftool")
install -m 755 "$exiftool_source" "$contents/Resources/Tools/bin/exiftool"
ditto "$project_root/.tools/exiftool/lib" "$contents/Resources/Tools/bin/lib"
install -m 644 "$project_root/assets/fonts/OFL-Outfit.txt" "$contents/Resources/OFL-Outfit.txt"

codesign --force --deep --sign - "$app_path"
archive_path="$release_root/RAF3FR-$release_version-macOS-arm64.zip"
ditto -c -k --sequesterRsrc --keepParent "$app_path" "$archive_path"
/usr/bin/zip -q -j "$archive_path" "$manual_en" "$manual_zh"

print "$app_path"
