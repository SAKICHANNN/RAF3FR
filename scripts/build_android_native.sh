#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${HOME}/Library/Android/sdk}"
NDK_VERSION="${NDK_VERSION:-27.3.13750724}"
NDK_ROOT="${ANDROID_NDK_HOME:-${ANDROID_SDK_ROOT}/ndk/${NDK_VERSION}}"

if [[ ! -d "${NDK_ROOT}/toolchains/llvm/prebuilt" ]]; then
  echo "Android NDK ${NDK_VERSION} was not found under ${NDK_ROOT}." >&2
  exit 1
fi

TOOLCHAIN="$(find "${NDK_ROOT}/toolchains/llvm/prebuilt" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [[ -z "${TOOLCHAIN}" ]]; then
  echo "The Android NDK LLVM toolchain is missing." >&2
  exit 1
fi

LINKER="${TOOLCHAIN}/bin/aarch64-linux-android26-clang"
if [[ ! -x "${LINKER}" ]]; then
  echo "The Android ARM64 API 26 linker is missing." >&2
  exit 1
fi

export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="${LINKER}"
export CARGO_TARGET_AARCH64_LINUX_ANDROID_RUSTFLAGS="-C link-arg=-Wl,-z,max-page-size=16384"
export CC_aarch64_linux_android="${LINKER}"
export AR_aarch64_linux_android="${TOOLCHAIN}/bin/llvm-ar"

cargo build \
  --manifest-path "${PROJECT_ROOT}/native/Cargo.toml" \
  --package raf3fr-jni \
  --target aarch64-linux-android \
  --release \
  --locked

DESTINATION="${PROJECT_ROOT}/apps/android/app/src/main/jniLibs/arm64-v8a"
mkdir -p "${DESTINATION}"
install -m 0644 \
  "${PROJECT_ROOT}/native/target/aarch64-linux-android/release/libraf3fr_jni.so" \
  "${DESTINATION}/libraf3fr_jni.so"

file "${DESTINATION}/libraf3fr_jni.so"
