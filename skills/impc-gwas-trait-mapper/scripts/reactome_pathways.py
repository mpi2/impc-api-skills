#!/usr/bin/env python3
"""Human genes (HGNC ids) -> their most specific Reactome pathways, as gene-level context.

EXPERIMENTAL (step 2c): output columns may change; not covered by evals yet.

Uses Reactome's public REST APIs (no auth), the same ones the Reactome MCP server wraps:
  AnalysisService  /identifier/{id}/projection        one call per gene: every pathway the gene is in,
                                                      with an `llp` (lowest-level pathway) flag and
                                                      reactions found/total and entities total
  AnalysisService  /token/{token}/found/all (POST)    which protein each query mapped to (mis-map check)
  ContentService   /data/eventsHierarchy/9606         one call per run: the pathway tree, used to roll
                                                      each pathway up to its top-level category
  ContentService   /data/database/version             the Reactome release, for the README
and UniProt REST to turn each HGNC id into its reviewed human accession(s).
See references/reactome-guide.md.

Lookup: HGNC id -> reviewed human UniProt accession(s) (UniProt REST) -> Reactome by accession.
Reactome release 98 resolves no HGNC ids (HGNC:12440 TYK2 -> 0 pathways; P29597 -> 45), so the
accession is the query. Pathways are kept only where Reactome mapped the accession to itself: its
UniProt index maps P29474 (NOS3) onto Q9UJU6 (DBNL), which would add 5 DBNL pathways. When a gene has
no reviewed accession the HGNC id is tried directly, in case a later release indexes it.
Symbols are never used. The analysis p-value and FDR are meaningless
for one gene and are not written.

--out: one row per gene x lowest-level pathway, ranked within gene by reaction coverage (reactions
with the gene / reactions in the pathway, high to low), then pathway size (entities, small to large),
then stable id. The rank says how central the gene is to the pathway, not how relevant the pathway is
to any phenotype or trait. A gene with no pathways gets one row with note "no Reactome annotation".

Examples:
  uv run skills/impc-gwas-trait-mapper/scripts/reactome_pathways.py --from-csv 02_orthologs.csv --id-col hgncAccId --symbol-col humanGeneSymbol --out 02_reactome_pathways.csv
  uv run skills/impc-gwas-trait-mapper/scripts/reactome_pathways.py --genes HGNC:6547 HGNC:12440 --out reactome.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CONTENT = "https://reactome.org/ContentService"
ANALYSIS = "https://reactome.org/AnalysisService"
UNIPROT = "https://rest.uniprot.org/uniprotkb/search"
DETAIL_URL = "https://reactome.org/content/detail/{}"
HUMAN = "9606"
DISEASE = "Disease"
# Reactome answers HTTP 403 to Python's default User-Agent, and 406 to Accept: application/json on
# text endpoints such as /data/database/version.
USER_AGENT = "impc-gwas-trait-mapper/0.1 (IMPC skills)"
PAGE_SIZE = 500
FIELDS = ["human_symbol", "hgnc_id", "queried_id", "rank", "stable_id", "pathway_name", "top_level_category",
          "reactions_with_gene", "reactions_total", "reaction_coverage", "pathway_entities", "in_disease",
          "reactome_url", "reactome_release", "note"]


def get(url: str, data: str | None = None, as_json: bool = True, retries: int = 3, timeout: int = 60):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json" if as_json else "text/plain"}
    if data is not None:
        headers["Content-Type"] = "text/plain"
    body = data.encode() if data is not None else None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=timeout) as r:
                return json.load(r) if as_json else r.read().decode().strip()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def categories() -> dict[str, list[str]]:
    """stId -> sorted top-level categories. A pathway with several parents can reach several.

    Under Disease the second level is kept ("Disease › Infectious disease"), because it separates the
    gene's own loss-of-function pathways from viral and cancer ones.
    """
    tops = get(f"{CONTENT}/data/eventsHierarchy/{HUMAN}?pathwaysOnly=true")
    found: dict[str, set[str]] = {}

    def walk(node: dict, label: str):
        found.setdefault(node["stId"], set()).add(label)
        for child in node.get("children", []):
            walk(child, label)

    for top in tops:
        found.setdefault(top["stId"], set()).add(top["name"])
        for child in top.get("children", []):
            walk(child, f"{DISEASE} › {child['name']}" if top["name"] == DISEASE else top["name"])
    return {k: sorted(v) for k, v in found.items()}


def analyse(identifier: str) -> tuple[list[dict], str | None]:
    """Lowest-level pathways for one identifier, and the analysis token."""
    pathways, page, token = [], 1, None
    while True:
        qs = urllib.parse.urlencode({"pageSize": PAGE_SIZE, "page": page, "resource": "TOTAL"})
        d = get(f"{ANALYSIS}/identifier/{urllib.parse.quote(identifier)}/projection?{qs}")
        if not d:
            break
        token = (d.get("summary") or {}).get("token")
        pathways.extend(d.get("pathways", []))
        if len(pathways) >= d.get("pathwaysFound", 0) or not d.get("pathways"):
            break
        page += 1
    return [p for p in pathways if p.get("llp")], token


def mapped_to_self(accession: str, token: str, stids: list[str]) -> set[str]:
    """Pathways where Reactome mapped the accession to itself or one of its isoforms, not another protein.

    mapsTo often names isoforms (P04035 -> P04035-1, P04035-2), so compare the base accession.
    """
    found = get(f"{ANALYSIS}/token/{token}/found/all?resource=TOTAL", data=",".join(stids)) or []
    return {pw["pathway"] for pw in found
            if any(i.split("-")[0] == accession
                   for e in pw.get("entities", []) for m in e.get("mapsTo", []) for i in m.get("ids", []))}


def reviewed_accessions(hgnc_id: str) -> list[str]:
    query = f"xref:hgnc-{hgnc_id.split(':', 1)[1]} AND reviewed:true AND organism_id:{HUMAN}"
    qs = urllib.parse.urlencode({"query": query, "fields": "accession", "format": "json"})
    return [r["primaryAccession"] for r in (get(f"{UNIPROT}?{qs}") or {}).get("results", [])]


def lookup(hgnc_id: str) -> tuple[list[dict], str, int]:
    """(lowest-level pathways, queried id(s), pathways dropped as mapped to another protein)."""
    accessions = reviewed_accessions(hgnc_id)
    if not accessions:
        llps, _ = analyse(hgnc_id)
        return llps, hgnc_id if llps else "", 0
    best: dict[str, dict] = {}
    used, dropped = [], 0
    for acc in accessions:
        acc_llps, token = analyse(acc)
        if not acc_llps:
            continue
        keep = mapped_to_self(acc, token, [p["stId"] for p in acc_llps]) if token else set()
        dropped += sum(p["stId"] not in keep for p in acc_llps)
        kept = [p for p in acc_llps if p["stId"] in keep]
        if kept:
            used.append(acc)
        for p in kept:
            if p["stId"] not in best or rank_key(p) < rank_key(best[p["stId"]]):
                best[p["stId"]] = p
    return list(best.values()), ";".join(used), dropped


def rank_key(p: dict):
    rx = p["reactions"]
    return (-(rx["found"] / rx["total"]) if rx["total"] else 0.0, p["entities"]["total"], p["stId"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--genes", nargs="+", help="HGNC ids (HGNC:6547)")
    g.add_argument("--from-csv", help="CSV to read HGNC ids from (e.g. 02_orthologs.csv)")
    ap.add_argument("--id-col", default="hgncAccId", help="HGNC id column in --from-csv")
    ap.add_argument("--symbol-col", default="humanGeneSymbol", help="Symbol column in --from-csv, copied to human_symbol")
    ap.add_argument("--out", required=True, help="CSV, one row per gene x lowest-level pathway")
    args = ap.parse_args()

    symbols: dict[str, str] = {}
    if args.from_csv:
        with open(args.from_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                gid = (r.get(args.id_col) or "").strip()
                if gid:
                    symbols.setdefault(gid, (r.get(args.symbol_col) or "").strip())
        genes = sorted(symbols)
    else:
        genes = list(dict.fromkeys(args.genes))
    bad = [x for x in genes if not x.upper().startswith("HGNC:")]
    if bad:
        print("not HGNC ids (use the hgncAccId column from step 2): " + ", ".join(bad), file=sys.stderr)
        return 2

    release = get(f"{CONTENT}/data/database/version", as_json=False) or ""
    cats = categories()

    rows, empty, via_uniprot, mismapped = [], [], [], []
    for i, gid in enumerate(genes):
        llps, queried, dropped = lookup(gid)
        llps.sort(key=rank_key)
        base = {"human_symbol": symbols.get(gid, ""), "hgnc_id": gid, "queried_id": queried,
                "reactome_release": release}
        if queried == gid:
            via_uniprot.append(gid)
        if dropped:
            mismapped.append(f"{gid} ({dropped})")
        if not llps:
            empty.append(gid)
            rows.append({**base, "note": "no Reactome annotation"})
        for r, p in enumerate(llps, 1):
            rx = p["reactions"]
            rows.append({**base, "rank": r, "stable_id": p["stId"], "pathway_name": p["name"],
                         "top_level_category": "; ".join(cats.get(p["stId"], [])),
                         "reactions_with_gene": rx["found"], "reactions_total": rx["total"],
                         "reaction_coverage": round(rx["found"] / rx["total"], 3) if rx["total"] else "",
                         "pathway_entities": p["entities"]["total"], "in_disease": p.get("inDisease", False),
                         "reactome_url": DETAIL_URL.format(p["stId"]),
                         "note": "" if p["stId"] in cats else "not in pathway hierarchy"})
        if i < len(genes) - 1:
            time.sleep(0.3)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    n_pw = sum(1 for r in rows if r.get("stable_id"))
    print(f"Reactome release {release}: {len(genes) - len(empty)}/{len(genes)} genes annotated, "
          f"{n_pw} gene x pathway rows -> {args.out}", file=sys.stderr)
    if via_uniprot:
        print("no reviewed UniProt accession, queried by HGNC id: " + ", ".join(via_uniprot), file=sys.stderr)
    if mismapped:
        print("pathways dropped, accession mapped to another protein: " + ", ".join(mismapped), file=sys.stderr)
    if empty:
        print("no Reactome annotation: " + ", ".join(empty), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
