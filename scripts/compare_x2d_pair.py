#!/usr/bin/env python3
"""Validate the observed Q16 transform between a decoded X2D 3FR/FFF pair."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from raf2hncs.transplant import read_pgm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("three_fr_pgm", type=Path)
    parser.add_argument("fff_pgm", type=Path)
    parser.add_argument("--crop", default="128,96,11656,8742", help="x,y,width,height")
    parser.add_argument("--black", type=int, default=4096)
    parser.add_argument("--white", type=int, default=65535)
    parser.add_argument(
        "--preserve-saturated-sentinel",
        action="store_true",
        help="Preserve input value 65535 while clipping transformed samples to --white",
    )
    parser.add_argument("--gain-r", type=int, default=67376)
    parser.add_argument("--gain-g1", type=int, default=65536)
    parser.add_argument("--gain-g2", type=int, default=65536)
    parser.add_argument("--gain-b", type=int, default=66448)
    args = parser.parse_args()

    three_fr, width, height = read_pgm(args.three_fr_pgm)
    fff, fff_width, fff_height = read_pgm(args.fff_pgm)
    if (width, height) != (fff_width, fff_height):
        raise ValueError("decoded pair dimensions differ")
    x, y, crop_width, crop_height = (int(value) for value in args.crop.split(","))
    gains = {
        "R": args.gain_r,
        "G1": args.gain_g1,
        "G2": args.gain_g2,
        "B": args.gain_b,
    }
    planes = ((0, 0, "R"), (0, 1, "G1"), (1, 0, "G2"), (1, 1, "B"))
    result: dict[str, object] = {
        "full_size": [width, height],
        "crop": [x, y, crop_width, crop_height],
        "black_level": args.black,
        "white_level": args.white,
        "preserve_saturated_sentinel": args.preserve_saturated_sentinel,
        "q16_gains": gains,
        "planes": {},
    }
    total = total_mismatches = maximum_error = 0
    for row_parity, column_parity, name in planes:
        source = np.asarray(
            three_fr[y + row_parity : y + crop_height : 2, x + column_parity : x + crop_width : 2],
            dtype=np.int64,
        )
        target = np.asarray(
            fff[y + row_parity : y + crop_height : 2, x + column_parity : x + crop_width : 2],
            dtype=np.int64,
        )
        predicted = np.clip(
            args.black + (((source - args.black) * gains[name]) >> 16),
            0,
            args.white,
        )
        if args.preserve_saturated_sentinel:
            predicted[source == 65535] = 65535
        error = predicted - target
        mismatches = int(np.count_nonzero(error))
        plane_maximum = int(np.max(np.abs(error)))
        result["planes"][name] = {
            "pixel_count": int(error.size),
            "mismatch_count": mismatches,
            "maximum_absolute_error_dn": plane_maximum,
        }
        total += error.size
        total_mismatches += mismatches
        maximum_error = max(maximum_error, plane_maximum)
    result.update(
        {
            "pixel_count": int(total),
            "mismatch_count": total_mismatches,
            "mismatch_fraction": total_mismatches / total,
            "maximum_absolute_error_dn": maximum_error,
        }
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
