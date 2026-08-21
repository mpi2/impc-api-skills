#!/usr/bin/env python3
"""Find IMPC pipeline/procedure/parameter stable-id triplets for data terms."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BASE_URL = "https://www.ebi.ac.uk/mi/impc/solr/experiment/select"
PIVOT_FIELDS = [
    "pipeline_stable_id",
    "pipeline_name",
    "procedure_stable_id",
    "procedure_name",
    "parameter_stable_id",
    "parameter_name",
]


def words(text: str) -> list[str]:
    return [word for word in re.findall(r"[A-Za-z0-9]+", text.casefold()) if word]


def variants(token: str) -> list[str]:
    return sorted({token, token.upper(), token.capitalize()})


def solr_query(text: str) -> str:
    tokens = words(text)
    if not tokens:
        raise ValueError("Search text must contain at least one letter or number.")
    clauses = []
    for field in ("parameter_name", "procedure_name", "parameter_stable_id", "procedure_stable_id"):
        field_tokens = []
        for token in tokens:
            variants_query = " OR ".join(
                f"{field}:*{variant}*" for variant in variants(token)
            )
            field_tokens.append(f"({variants_query})")
        clauses.append("(" + " AND ".join(field_tokens) + ")")
    return " OR ".join(clauses)


def request_pivot(term: str, timeout: int) -> dict[str, Any]:
    params = {
        "q": solr_query(term),
        "rows": 0,
        "wt": "json",
        "facet": "on",
        "facet.pivot": ",".join(PIVOT_FIELDS),
        "facet.limit": -1,
        "facet.mincount": 1,
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def flatten_pivot(nodes: list[dict[str, Any]], depth: int = 0, row=None):
    row = {} if row is None else row
    field = PIVOT_FIELDS[depth]
    for node in nodes:
        current = {**row, field: node.get("value", "")}
        children = node.get("pivot") or []
        if children and depth + 1 < len(PIVOT_FIELDS):
            yield from flatten_pivot(children, depth + 1, current)
        else:
            current["count"] = node.get("count", 0)
            yield current


def matching_rows(rows: list[dict[str, Any]], term: str) -> list[dict[str, Any]]:
    tokens = words(term)
    result = []
    for row in rows:
        haystack = " ".join(str(row.get(field, "")) for field in PIVOT_FIELDS).casefold()
        if all(token in haystack for token in tokens):
            result.append(row)
    return result


def triplets(data: dict[str, Any], term: str) -> list[dict[str, Any]]:
    pivot = data.get("facet_counts", {}).get("facet_pivot", {})
    rows = list(flatten_pivot(pivot.get(",".join(PIVOT_FIELDS), [])))
    return sorted(
        matching_rows(rows, term),
        key=lambda row: tuple(str(row.get(field, "")) for field in PIVOT_FIELDS),
    )


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*PIVOT_FIELDS, "count"])
        writer.writeheader()
        writer.writerows(rows)


def print_table(rows: list[dict[str, Any]]) -> None:
    fields = [*PIVOT_FIELDS, "count"]
    if not rows:
        print("No matching triplets found.")
        return
    widths = {
        field: max(len(field), *(len(str(row.get(field, ""))) for row in rows))
        for field in fields
    }
    print("  ".join(field.ljust(widths[field]) for field in fields))
    print("  ".join("-" * widths[field] for field in fields))
    for row in rows:
        print("  ".join(str(row.get(field, "")).ljust(widths[field]) for field in fields))


def self_test() -> None:
    assert words("Body Weight") == ["body", "weight"]
    assert words("CSD_008") == ["csd", "008"]
    query = solr_query("Body Weight")
    assert "parameter_name:*body*" in query
    assert "procedure_stable_id:*Weight*" in query
    fake = {
        "facet_counts": {
            "facet_pivot": {
                ",".join(PIVOT_FIELDS): [
                    {
                        "value": "IMPC_001",
                        "count": 3,
                        "pivot": [
                            {
                                "value": "Pipeline",
                                "count": 3,
                                "pivot": [
                                    {
                                        "value": "IMPC_BWT_001",
                                        "count": 3,
                                        "pivot": [
                                            {
                                                "value": "Body Weight",
                                                "count": 3,
                                                "pivot": [
                                                    {
                                                        "value": "IMPC_BWT_001_001",
                                                        "count": 3,
                                                        "pivot": [
                                                            {
                                                                "value": "Body weight",
                                                                "count": 3,
                                                            }
                                                        ],
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }
    }
    rows = triplets(fake, "body weight")
    assert rows[0]["parameter_stable_id"] == "IMPC_BWT_001_001"
    assert rows[0]["parameter_name"] == "Body weight"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find observed IMPC stable-id triplets for a data term."
    )
    parser.add_argument("term", nargs="?", help='Data term, e.g. "body weight".')
    parser.add_argument("--out", type=Path, help="Optional CSV output path.")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds.")
    parser.add_argument("--self-test", action="store_true", help="Run offline checks and exit.")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("self-test OK")
        return
    if not args.term:
        parser.error("term is required unless --self-test is used")

    rows = triplets(request_pivot(args.term, args.timeout), args.term)
    print_table(rows)
    if args.out:
        write_csv(rows, args.out)
        print(f"\nSaved {len(rows)} triplets to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
