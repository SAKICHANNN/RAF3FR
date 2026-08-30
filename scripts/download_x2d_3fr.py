#!/usr/bin/env python3
"""Download a slow raw.pixls.us sample with resumable parallel ranges."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


URL = "https://raw.pixls.us/download/data/Hasselblad/X2D%20100C/B0000079.3FR"
SIZE = 213_311_488
SHA256 = "dcc5a4abe3498e6f25e89bb491995fd12c3b669d9277c71b45b49210d3e56280"


def fetch(part: Path, start: int, end: int, url: str) -> int:
    expected = end - start + 1
    if part.is_file() and part.stat().st_size == expected:
        return expected
    subprocess.run(
        ["curl", "-L", "-sS", "--fail", "--retry", "5", "--range", f"{start}-{end}", "-o", str(part), url],
        check=True,
    )
    if part.stat().st_size != expected:
        raise RuntimeError(f"short range {part.name}: {part.stat().st_size} != {expected}")
    return expected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--url", default=URL)
    parser.add_argument("--size", type=int, default=SIZE)
    parser.add_argument("--sha256", default=SHA256, help="expected digest; pass an empty string for size-only validation")
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--parts", type=int, default=256)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    part_dir = args.output.with_name(args.output.name + ".parts")
    part_dir.mkdir(parents=True, exist_ok=True)
    chunk = (args.size + args.parts - 1) // args.parts
    ranges = [
        (index, index * chunk, min(args.size - 1, (index + 1) * chunk - 1))
        for index in range(args.parts)
        if index * chunk < args.size
    ]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch, part_dir / f"{index:04d}.part", start, end, args.url): index
            for index, start, end in ranges
        }
        completed = 0
        for future in as_completed(futures):
            completed += future.result()
            print(f"{completed / args.size:.1%}", flush=True)

    assembling = args.output.with_name(args.output.name + ".assembling")
    digest = hashlib.sha256()
    with assembling.open("wb") as destination:
        for index, _, _ in ranges:
            with (part_dir / f"{index:04d}.part").open("rb") as source:
                while block := source.read(1024 * 1024):
                    digest.update(block)
                    destination.write(block)
        destination.flush()
        os.fsync(destination.fileno())
    actual_sha256 = digest.hexdigest()
    if assembling.stat().st_size != args.size or (args.sha256 and actual_sha256 != args.sha256):
        raise RuntimeError(f"validation failed: {assembling.stat().st_size}, {digest.hexdigest()}")
    assembling.replace(args.output)
    print(f"verified size={args.size} sha256={actual_sha256}")


if __name__ == "__main__":
    main()
