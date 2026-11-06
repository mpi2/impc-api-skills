#!/usr/bin/env python3
"""Mouse MGI gene ids <-> mouse UniProt accessions, to carry IMPC genes into UniProt.

EXPERIMENTAL (step 2c): output columns may change; not covered by evals yet.

Two sources, in order:
  1. the local IMPC -> UniProt mapping file (default results/uniprot/uniprot_mapping.tsv);
     only its UniProt ID and Link (MGI id) columns are used. It covers only the ~4,000 genes
     that have an IMPC-allele paper (Tyk2 is not in it);
  2. UniProt REST (xref:mgi-<number> AND organism_id:10090) for every MGI id the file lacks.
Each accession is then annotated from UniProt REST (reviewed status, gene, protein name,
length) unless --offline. See references/uniprot-guide.md.

Always select by MGI id, never by symbol: the allele symbols in the file are outdated
for some genes (Fam46c<...> on MGI:1921895, now Tent5c).

--out: one row per gene x accession, reviewed (Swiss-Prot) first. `is_primary` marks the
reviewed accession to use downstream; a gene with no reviewed entry has none marked.

Examples:
  uv run skills/impc-gwas-trait-mapper/scripts/uniprot_mapping.py --from-csv 01_impc_phenotypes.csv --id-col marker_accession_id --out 02_uniprot_accessions.csv
  uv run skills/impc-gwas-trait-mapper/scripts/uniprot_mapping.py --mgi MGI:1929470 MGI:1915512 --out ids.csv
  uv run skills/impc-gwas-trait-mapper/scripts/uniprot_mapping.py --accessions Q8K4X7 E9Q2T9 --out ids.csv --offline
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_MAPPING = "results/uniprot/uniprot_mapping.tsv"
UNIPROT = "https://rest.uniprot.org/uniprotkb/search"
ENTRY_URL = "https://www.uniprot.org/uniprotkb/{}/entry"
MOUSE = "10090"
FIELDS = ["mgi_id", "uniprot_accession", "is_primary", "reviewed", "uniprot_gene", "protein_name", "length",
          "source", "uniprot_url"]
ANNOT_FIELDS = "accession,reviewed,gene_primary,protein_name,length,xref_mgi"


def decode(raw: bytes) -> str:
    # A few lines carry stray cp1252 bytes (non-breaking spaces inside allele names: "Islr\xa0\xa0<tm1a").
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("cp1252", errors="replace")
    return s.replace("\xa0", "").rstrip("\r\n")


def read_file_pairs(path: str) -> set[tuple[str, str]]:
    """(MGI id, accession) pairs from the mapping file; the file has one row per accession x paper."""
    pairs = set()
    with open(path, "rb") as f:
        header = decode(next(f)).split("\t")
        i_acc, i_mgi = header.index("UniProt ID"), header.index("Link")
        for raw in f:
            cols = decode(raw).split("\t")
            if len(cols) > max(i_acc, i_mgi):
                pairs.add((cols[i_mgi], cols[i_acc]))
    return pairs


def ids_from_csv(path: str, col: str) -> list[str]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if col not in (reader.fieldnames or []):
            sys.exit(f"column {col!r} not in {path}; columns: {reader.fieldnames}")
        return sorted({(r.get(col) or "").strip() for r in reader} - {""})


def get_json(url: str, retries: int = 4, timeout: int = 90):
    # UniProt REST times out or answers 503 now and then; back off and retry.
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            retry = not isinstance(e, urllib.error.HTTPError) or e.code in (429, 500, 502, 503, 504)
            if retry and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise


def search(query: str, size: int = 500) -> list[dict]:
    qs = urllib.parse.urlencode({"query": query, "fields": ANNOT_FIELDS, "format": "json", "size": size})
    return (get_json(f"{UNIPROT}?{qs}") or {}).get("results", [])


def entry_info(r: dict) -> dict:
    desc = r.get("proteinDescription", {})
    name = (desc.get("recommendedName") or (desc.get("submissionNames") or [{}])[0]).get("fullName", {})
    genes = r.get("genes") or [{}]
    return {"reviewed": "reviewed" if "Swiss-Prot" in r.get("entryType", "") else "unreviewed",
            "uniprot_gene": genes[0].get("geneName", {}).get("value", ""),
            "protein_name": name.get("value", ""), "length": r.get("sequence", {}).get("length", ""),
            "mgi_ids": [x["id"] for x in r.get("uniProtKBCrossReferences", []) if x.get("database") == "MGI"]}


def by_accession(accessions: list[str], chunk: int = 100) -> dict[str, dict]:
    out = {}
    for i in range(0, len(accessions), chunk):
        part = accessions[i:i + chunk]
        for r in search(" OR ".join(f"accession:{a}" for a in part), size=len(part)):
            out[r["primaryAccession"]] = entry_info(r)
        time.sleep(0.3)
    return out


def by_mgi(mgi_ids: list[str], chunk: int = 20, size: int = 500) -> dict[str, dict]:
    # "xref:mgi-1929470" works; "xref:mgi-MGI:1929470" is a syntax error. 20 genes x up to ~44
    # accessions stays under one 500-row page.
    out = {}
    for i in range(0, len(mgi_ids), chunk):
        part = set(mgi_ids[i:i + chunk])
        terms = " OR ".join(f"xref:mgi-{m.split(':')[-1]}" for m in sorted(part))
        results = search(f"({terms}) AND organism_id:{MOUSE}", size=size)
        if len(results) == size:
            print(f"warning: a page of {size} results was full for {sorted(part)}; some accessions may be missing",
                  file=sys.stderr)
        for r in results:
            info = entry_info(r)
            for mgi in part & set(info["mgi_ids"]):
                out[r["primaryAccession"]] = {**info, "mgi_ids": [mgi]}
        time.sleep(0.3)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mapping", default=DEFAULT_MAPPING, help=f"UniProt mapping TSV (default {DEFAULT_MAPPING})")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--mgi", nargs="+", help="Mouse MGI gene ids (MGI:...)")
    g.add_argument("--from-csv", help="CSV to read MGI ids from")
    g.add_argument("--accessions", nargs="+", help="Mouse UniProt accessions (reverse direction: accession -> MGI)")
    ap.add_argument("--id-col", default="marker_accession_id",
                    help="MGI id column in --from-csv (marker_accession_id in 01_*, mgiGeneAccId in 02_orthologs)")
    ap.add_argument("--out", required=True, help="CSV, one row per gene x accession")
    ap.add_argument("--offline", action="store_true", help="Mapping file only: no UniProt REST fallback or annotation")
    args = ap.parse_args()

    try:
        pairs = read_file_pairs(args.mapping)
        modified = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(args.mapping)))
        print(f"mapping file {args.mapping}: {len({m for m, _ in pairs})} genes, "
              f"{len({a for _, a in pairs})} accessions, modified {modified}", file=sys.stderr)
    except FileNotFoundError:
        if args.offline:
            sys.exit(f"mapping file not found: {args.mapping} (local, gitignored) and --offline set")
        print(f"mapping file not found: {args.mapping}; using UniProt REST only", file=sys.stderr)
        pairs = set()

    rows: dict[tuple[str, str], dict] = {}
    if args.accessions:
        wanted_acc = set(args.accessions)
        for mgi, acc in pairs:
            if acc in wanted_acc:
                rows[(mgi, acc)] = {"source": "mapping_file"}
        if not args.offline:
            for acc, info in by_accession(sorted(wanted_acc - {a for _, a in rows})).items():
                for mgi in info["mgi_ids"]:
                    rows[(mgi, acc)] = {"source": "uniprot_rest"}
        wanted = wanted_acc
        found = {a for _, a in rows}
    else:
        wanted = set(args.mgi or ids_from_csv(args.from_csv, args.id_col))
        for mgi, acc in pairs:
            if mgi in wanted:
                rows[(mgi, acc)] = {"source": "mapping_file"}
        in_file = {m for m, _ in rows}
        if not args.offline:
            for acc, info in by_mgi(sorted(wanted - in_file)).items():
                rows[(info["mgi_ids"][0], acc)] = {"source": "uniprot_rest"}
        print(f"{len(in_file)}/{len(wanted)} genes found in the mapping file"
              + ("" if args.offline else f", {len({m for m, _ in rows}) - len(in_file)} more via UniProt REST"),
              file=sys.stderr)
        found = {m for m, _ in rows}

    info = {} if args.offline else by_accession(sorted({a for _, a in rows}))
    out_rows = []
    for (mgi, acc), r in rows.items():
        meta = {k: v for k, v in info.get(acc, {}).items() if k != "mgi_ids"}
        out_rows.append({"mgi_id": mgi, "uniprot_accession": acc, "source": r["source"],
                         "uniprot_url": ENTRY_URL.format(acc), **meta})
    out_rows.sort(key=lambda r: (r["mgi_id"], r.get("reviewed") != "reviewed", r["uniprot_accession"]))
    seen = set()
    for r in out_rows:
        r["is_primary"] = r.get("reviewed") == "reviewed" and r["mgi_id"] not in seen
        if r["is_primary"]:
            seen.add(r["mgi_id"])

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out_rows)
    n_genes = len({r["mgi_id"] for r in out_rows})
    print(f"{len(out_rows)} gene x accession rows for {n_genes} genes, {len(seen)} with a reviewed accession "
          f"-> {args.out}", file=sys.stderr)
    missing = sorted(wanted - found)
    if missing:
        print(f"not found ({len(missing)}): " + ", ".join(missing[:50]) + (" ..." if len(missing) > 50 else ""),
              file=sys.stderr)
    if info:
        gone = sorted({r["uniprot_accession"] for r in out_rows} - set(info))
        if gone:
            print(f"not returned by UniProt (obsolete/merged since the file?): {', '.join(gone[:30])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
