#!/usr/bin/env python3
"""Extract 5′/3′ homology-arm boundaries from an IMPC GenBank file."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


def read_source(source: str) -> str:
    if urlparse(source).scheme in {"http", "https"}:
        with urlopen(source, timeout=30) as response:
            data = response.read()
    else:
        data = Path(source).read_bytes()
    if source.lower().endswith(".gz") or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode("utf-8")


def extract_coordinates(text: str) -> dict[str, object]:
    try:
        features = text.split("FEATURES", 1)[1].split("ORIGIN", 1)[0]
    except IndexError as error:
        raise ValueError("Input is not a GenBank record with FEATURES and ORIGIN") from error

    arms: dict[str, list[tuple[int, int]]] = {"5": [], "3": []}
    blocks = re.split(r"(?=^ {5}\S+\s+\S)", features, flags=re.MULTILINE)
    for block in blocks:
        first_line = block.splitlines()[0] if block.splitlines() else ""
        location_match = re.match(r"^ {5}\S+\s+(.+)$", first_line)
        if not location_match:
            continue
        notes = re.findall(r'/note="(.*?)"', block, flags=re.DOTALL)
        for note in notes:
            normalized = re.sub(r"[\s'’_-]+", "", note).lower()
            if normalized not in {"5arm", "3arm"}:
                continue
            points = [int(value) for value in re.findall(r"\d+", location_match.group(1))]
            if not points:
                raise ValueError(f"Arm feature has no numeric location: {first_line.strip()}")
            arms[normalized[0]].append((min(points), max(points)))

    for label, matches in arms.items():
        if len(matches) != 1:
            raise ValueError(f"Expected one {label}′ arm annotation, found {len(matches)}")

    five, three = arms["5"][0], arms["3"][0]
    if five[1] >= three[0]:
        raise ValueError("Expected the 5′ arm to end before the 3′ arm starts")
    return {
        "coordinate_system": "GenBank construct, 1-based inclusive",
        "five_prime_arm": {"start": five[0], "end": five[1]},
        "three_prime_arm": {"start": three[0], "end": three[1]},
        "predicted_es_cell_interval": {"start": five[1], "end": three[0]},
    }


def self_test() -> None:
    sample = '''FEATURES             Location/Qualifiers
     misc_feature    complement(10..20)
                     /note="5' arm"
     misc_feature    31..40
                     /note="3 arm"
ORIGIN
        1 acgt
'''
    result = extract_coordinates(sample)
    assert result["five_prime_arm"] == {"start": 10, "end": 20}
    assert result["three_prime_arm"] == {"start": 31, "end": 40}
    assert result["predicted_es_cell_interval"] == {"start": 20, "end": 31}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="GenBank path or HTTP(S) URL")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            print("self-test passed")
        elif args.source:
            print(json.dumps(extract_coordinates(read_source(args.source)), indent=2))
        else:
            parser.error("source is required unless --self-test is used")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
