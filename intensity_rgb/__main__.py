"""Module entrypoint for `python -m intensity_rgb`.

Wave 4 will replace this stub with a real GUI launcher (importing from
``intensity_rgb.app``). For now we just print a hint and exit cleanly.
"""
import sys


def main() -> int:
    print(
        "Intensity-RGB V2.0 GUI — coming in M4 (Wave 4). "
        "Use 'python -m intensity_rgb.cli' for now."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
