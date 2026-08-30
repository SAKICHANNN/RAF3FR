from __future__ import annotations

import argparse
import dataclasses
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from .lens import extract_fuji_lens_profile
from .source_info import inspect_fuji_source
from .tiff import inspect_x2d
from .transplant import convert, find_tool, sha256, verify


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="raf2hncs")
    commands = root.add_subparsers(dest="command", required=True)

    inspect_command = commands.add_parser("inspect", help="inspect an X2D 100C 3FR donor")
    inspect_command.add_argument("input", type=Path)

    copy_command = commands.add_parser("identity-copy", help="make a byte-identical donor control")
    copy_command.add_argument("input", type=Path)
    copy_command.add_argument("output", type=Path)

    commands.add_parser("doctor", help="report required local runtime and tool versions")

    source_command = commands.add_parser(
        "source-summary", help="read a RAF capture summary and lightweight preview"
    )
    source_command.add_argument("input", type=Path)
    source_command.add_argument("--preview-output", type=Path)
    source_command.add_argument("--exiftool")

    convert_command = commands.add_parser("convert", help="transplant a GFX100RF mosaic")
    convert_command.add_argument("input", type=Path)
    convert_command.add_argument("--template", type=Path, required=True)
    convert_command.add_argument("-o", "--output", type=Path, required=True)
    convert_command.add_argument("--dnglab")
    convert_command.add_argument("--raw-identify")
    convert_command.add_argument("--unprocessed-raw")
    convert_command.add_argument("--exiftool")
    wb_group = convert_command.add_mutually_exclusive_group()
    wb_group.add_argument(
        "--white-balance",
        choices=("auto", "as-shot", "donor"),
        default="auto",
        help="white balance written to AsShotNeutral (default: Fuji camera Auto WB)",
    )
    wb_group.add_argument(
        "--source-wb",
        dest="white_balance",
        action="store_const",
        const="as-shot",
        help=argparse.SUPPRESS,
    )
    convert_command.add_argument(
        "--inverse-x2d-calibration",
        action="store_true",
        help="pre-divide R/B by the observed paired 3FR-to-FFF X2D Q16 gains",
    )
    iso_group = convert_command.add_mutually_exclusive_group()
    iso_group.add_argument(
        "--iso-policy",
        choices=("nearest-x2d", "hnnr-stable", "capture"),
        default="hnnr-stable",
        help="Phocus-facing ISO selection (default: HNNR-stable, capped at ISO 6400)",
    )
    iso_group.add_argument(
        "--hnnr-compatibility",
        dest="iso_policy",
        action="store_const",
        const="hnnr-stable",
        help="legacy alias for --iso-policy hnnr-stable",
    )
    iso_group.add_argument(
        "--no-hnnr-compatibility",
        dest="iso_policy",
        action="store_const",
        const="capture",
        help="legacy alias for --iso-policy capture",
    )
    convert_command.add_argument(
        "--sensor-mapping",
        choices=("identity", "d65-dnglab-bootstrap", "wb-adaptive-bootstrap"),
        default="wb-adaptive-bootstrap",
        help="Fuji-to-X2D sensor transform (default: WB-adaptive experimental bootstrap)",
    )
    convert_command.add_argument(
        "--preview",
        choices=("source", "donor"),
        default="source",
        help="embedded JPEG thumbnail (default: source RAF; donor is diagnostic only)",
    )
    convert_command.add_argument(
        "--donor-lens-correction",
        choices=("neutralize", "preserve"),
        default="neutralize",
        help="neutralize automatic donor XCD vignetting in Phocus (default: neutralize)",
    )
    convert_command.add_argument(
        "--distortion-model",
        choices=("native-match", "legacy-in-bounds"),
        default="native-match",
        help="distortion geometry model (default: calibrated native match)",
    )
    convert_command.add_argument(
        "--distortion-strength",
        type=float,
        default=1.0,
        help="embed signed Fuji distortion profile strength (-2..2, default: 1)",
    )
    convert_command.add_argument(
        "--ca-strength",
        type=float,
        default=1.0,
        help="embed signed Fuji lateral chromatic-aberration profile strength (-2..2, default: 1)",
    )
    convert_command.add_argument(
        "--vignetting-strength",
        type=float,
        default=0.0,
        help="embed signed Fuji vignetting profile strength (-2..2, default: 0/preserve)",
    )
    convert_command.add_argument(
        "--remove-location",
        dest="preserve_location",
        action="store_false",
        default=True,
        help="omit source GPS location from output XMP",
    )
    convert_command.add_argument(
        "--remove-rights",
        dest="preserve_rights",
        action="store_false",
        default=True,
        help="omit source rating, artist, copyright and comment from output XMP",
    )
    convert_command.add_argument(
        "--remove-provenance",
        dest="preserve_provenance",
        action="store_false",
        default=True,
        help="omit private Fuji source provenance from output XMP",
    )

    verify_command = commands.add_parser("verify", help="verify donor byte preservation")
    verify_command.add_argument("donor", type=Path)
    verify_command.add_argument("candidate", type=Path)

    lens_command = commands.add_parser("lens-profile", help="extract the RAF's embedded Fuji lens profile")
    lens_command.add_argument("input", type=Path)
    lens_command.add_argument("-o", "--output", type=Path, required=True)
    lens_command.add_argument("--exiftool")

    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "doctor":
        result: dict[str, object] = {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "tools": {},
        }
        tool_commands = {
            "dnglab": ["--version"],
            "exiftool": ["-ver"],
            "raw-identify": [],
            "unprocessed_raw": [],
            "sips": [],
        }
        for name, version_args in tool_commands.items():
            try:
                path = find_tool(None, name)
                version = None
                if version_args:
                    completed = subprocess.run(
                        [path, *version_args], capture_output=True, text=True, check=True
                    )
                    version = (completed.stdout or completed.stderr).strip()
                result["tools"][name] = {"path": path, "version": version, "ok": True}
            except (FileNotFoundError, subprocess.SubprocessError) as error:
                result["tools"][name] = {"ok": False, "error": str(error)}
        phocus_info = Path("/Applications/Phocus.app/Contents/Info.plist")
        if phocus_info.is_file():
            with phocus_info.open("rb") as handle:
                info = plistlib.load(handle)
            result["phocus"] = {
                "path": str(phocus_info.parents[1]),
                "version": info.get("CFBundleShortVersionString"),
                "build": info.get("CFBundleVersion"),
                "ok": True,
            }
        else:
            result["phocus"] = {"ok": False, "error": "Phocus.app not found"}
        result["ready"] = all(
            bool(item.get("ok")) for item in result["tools"].values()
        ) and bool(result["phocus"].get("ok"))
        print(json.dumps(result, indent=2))
    elif args.command == "source-summary":
        result = inspect_fuji_source(
            args.input,
            find_tool(args.exiftool, "exiftool"),
            preview_output=args.preview_output,
        )
        print(json.dumps(result, indent=2))
    elif args.command == "inspect":
        layout = inspect_x2d(args.input)
        result = dataclasses.asdict(layout)
        result.update(
            {
                "payload_end": layout.payload_end,
                "preview_end": layout.preview_end,
                "required_file_end": layout.required_file_end,
                "complete": layout.complete,
            }
        )
        print(json.dumps(result, indent=2))
    elif args.command == "identity-copy":
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite {args.output}")
        shutil.copyfile(args.input, args.output)
        if sha256(args.input) != sha256(args.output):
            raise RuntimeError("identity copy hash mismatch")
        print(sha256(args.output))
    elif args.command == "convert":
        result = convert(
            args.input,
            args.template,
            args.output,
            dnglab_path=args.dnglab,
            raw_identify_path=args.raw_identify,
            unprocessed_raw_path=args.unprocessed_raw,
            exiftool_path=args.exiftool,
            white_balance=args.white_balance,
            inverse_x2d_calibration=args.inverse_x2d_calibration,
            iso_policy=args.iso_policy,
            sensor_mapping=args.sensor_mapping,
            preview=args.preview,
            donor_lens_correction=args.donor_lens_correction,
            distortion_model=args.distortion_model,
            distortion_strength=args.distortion_strength,
            chromatic_aberration_strength=args.ca_strength,
            vignetting_strength=args.vignetting_strength,
            preserve_location=args.preserve_location,
            preserve_rights=args.preserve_rights,
            preserve_provenance=args.preserve_provenance,
        )
        print(json.dumps(result, indent=2))
    elif args.command == "verify":
        print(json.dumps(verify(args.donor, args.candidate), indent=2))
    elif args.command == "lens-profile":
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite {args.output}")
        result = extract_fuji_lens_profile(args.input, find_tool(args.exiftool, "exiftool"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
