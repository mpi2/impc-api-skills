#!/usr/bin/env python3
"""Mouse -> human one-to-one orthologs via the hosted IMPC orthology MCP server.

Fallback for when the `impc-orthology` MCP server is not installed in the
agent's client, or for batches (max 600 ids per call). Same data as the
`find_orthologs_by_mgi_ids` / `find_orthologs_by_mouse_genes` tools.

Example:
  uv run skills/impc-human-evidence-explorer/scripts/orthologs.py --mgi MGI:1928394 MGI:1347521 --out 02_orthologs.csv
  uv run skills/impc-human-evidence-explorer/scripts/orthologs.py --symbols Mtor Ror2 Dvl3 --out 02_orthologs.csv
  uv run skills/impc-human-evidence-explorer/scripts/orthologs.py --from-csv 01_impc_phenotypes.csv --id-col marker_accession_id --out 02_orthologs.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_client import McpClient  # noqa: E402

ORTHOLOGY_MCP = "https://www.ebi.ac.uk/mi/impc/mcp/orthology/"
FIELDS = ["mgiGeneAccId", "mouseGeneSymbol", "hgncAccId", "humanGeneSymbol", "category", "supportCount",
          "humanCategoryForThreshold", "mouseCategoryForThreshold", "isMaxHumanToMouse", "isMaxMouseToHuman"]


def chunks(xs, n=600):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--mgi", nargs="+", help="MGI accession ids")
    g.add_argument("--symbols", nargs="+", help="Mouse gene symbols")
    g.add_argument("--human-symbols", nargs="+", help="Human gene symbols (reverse direction, find_orthologs_by_human_genes)")
    g.add_argument("--from-csv", help="CSV to read ids/symbols from")
    ap.add_argument("--id-col", default="marker_accession_id", help="Column in --from-csv (MGI ids if values start with MGI:, HGNC ids if HGNC:, else mouse symbols; add --human for human symbols)")
    ap.add_argument("--human", action="store_true", help="Treat --from-csv values as human symbols")
    ap.add_argument("--all-relationships", action="store_true", help="Include one-to-many orthologs (find_all_orthologs_by_mgi_ids); default is one-to-one only")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ids: list[str] = []
    if args.from_csv:
        with open(args.from_csv, newline="", encoding="utf-8") as f:
            ids = sorted({(r.get(args.id_col) or "").strip() for r in csv.DictReader(f)} - {""})
    else:
        ids = args.mgi or args.symbols or args.human_symbols
    by_mgi = all(x.upper().startswith("MGI:") for x in ids)
    by_hgnc = all(x.upper().startswith("HGNC:") for x in ids)
    human = bool(args.human_symbols) or args.human
    if args.all_relationships and not by_mgi:
        sys.exit("--all-relationships requires MGI ids")
    if by_mgi:
        tool, arg_name = ("find_all_orthologs_by_mgi_ids" if args.all_relationships else "find_orthologs_by_mgi_ids"), "mgi_ids"
    elif by_hgnc:
        tool, arg_name = "find_orthologs_by_hgnc_ids", "hgnc_ids"
    elif human:
        tool, arg_name = "find_orthologs_by_human_genes", "genes"
    else:
        tool, arg_name = "find_orthologs_by_mouse_genes", "genes"

    client = McpClient(ORTHOLOGY_MCP, protocol="2025-06-18")
    rows = []
    for batch in chunks(ids):
        data = client.call_json(tool, {arg_name: batch})
        rows.extend(data.get("data", []))
    key = "mgiGeneAccId" if by_mgi else "hgncAccId" if by_hgnc else "humanGeneSymbol" if human else "mouseGeneSymbol"
    found = {r.get(key) for r in rows}
    missing = [x for x in ids if x not in found]

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print(f"{tool}: {len(ids)} queried, {len(rows)} ortholog rows, {len(missing)} without one-to-one ortholog -> {args.out}", file=sys.stderr)
    if missing:
        print("no ortholog returned for: " + ", ".join(missing), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
