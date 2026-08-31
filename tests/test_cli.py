from raf2hncs import __version__
from raf2hncs.cli import parser


def test_package_version_matches_release() -> None:
    assert __version__ == "0.9.7"


def test_convert_defaults_to_hnnr_stable_iso() -> None:
    args = parser().parse_args(
        ["convert", "source.RAF", "--template", "donor.3FR", "-o", "output.3FR"]
    )
    assert args.iso_policy == "hnnr-stable"
    assert args.preserve_location is True
    assert args.preserve_rights is True
    assert args.preserve_provenance is True


def test_convert_privacy_flags_are_independent() -> None:
    args = parser().parse_args(
        [
            "convert", "source.RAF", "--template", "donor.3FR", "-o", "output.3FR",
            "--remove-location", "--remove-rights", "--remove-provenance",
        ]
    )
    assert args.preserve_location is False
    assert args.preserve_rights is False
    assert args.preserve_provenance is False
