#!/usr/bin/env python3
"""GWAS Catalog study accessions (GCST...) -> reported trait + mapped EFO traits, via the REST API v2.

One request per study (the API has no batch lookup; comma lists silently return 0).
Documented limit is 15 requests/second. Non-catalog ids (FINNGEN_R12_*, etc.) come
back as a row with note="not found in GWAS Catalog".

Examples:
  uv run skills/impc-gwas-trait-mapper/scripts/gwas_catalog_traits.py --studies GCST90480502 GCST90014463 --out 04_gwas_traits.csv
  uv run skills/impc-gwas-trait-mapper/scripts/gwas_catalog_traits.py --from-csv 03_l2g_gwas_links.csv --id-col gwas_study_id --out 04_gwas_traits.csv
  # reverse direction: studies for a trait id (descendants included with --child-traits)
  uv run skills/impc-gwas-trait-mapper/scripts/gwas_catalog_traits.py --efo MONDO_0005306 --child-traits --out studies_for_trait.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_V2 = "https://www.ebi.ac.uk/gwas/rest/api/v2"
URI_PREFIX = {"EFO": "http://www.ebi.ac.uk/efo/", "Orphanet": "http://www.orpha.net/ORDO/"}
FIELDS = ["study_id", "reported_trait", "trait_id", "trait_label", "trait_uri", "trait_role", "pubmed_id",
          "sample_size", "initial_sample_size", "discovery_ancestry", "cohort", "full_summary_stats", "note"]


def efo_uri(short_form: str) -> str:
    return URI_PREFIX.get(short_form.split("_", 1)[0], "http://purl.obolibrary.org/obo/") + short_form


def get_json(url: str, retries: int = 3, timeout: int = 30):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def sample_size(study: dict):
    ns = [int(m.group(1)) for e in study.get("discovery_ancestry") or [] if (m := re.match(r"\s*(\d+)", e))]
    return sum(ns) if ns else None


def study_rows(study: dict, gcst: str, include_background: bool) -> list[dict]:
    base = {"study_id": study.get("accession_id", gcst), "reported_trait": study.get("disease_trait"),
            "pubmed_id": study.get("pubmed_id"), "sample_size": sample_size(study),
            "initial_sample_size": study.get("initial_sample_size"),
            "discovery_ancestry": "; ".join(study.get("discovery_ancestry") or []),
            "cohort": "; ".join(study.get("cohort") or []),
            "full_summary_stats": study.get("full_summary_stats") if study.get("full_summary_stats_available") else "",
            "note": ""}
    rows = []
    traits = [(t, "mapped") for t in study.get("efo_traits") or []]
    if include_background:
        traits += [(t, "background") for t in study.get("bg_efo_traits") or []]
    if not traits:
        rows.append({**base, "trait_id": "", "trait_label": "", "trait_uri": "", "trait_role": "", "note": "no mapped EFO trait"})
    for t, role in traits:
        tid = t.get("efo_id") or ""
        rows.append({**base, "trait_id": tid, "trait_label": t.get("efo_trait"), "trait_uri": efo_uri(tid) if tid else "", "trait_role": role})
    return rows


def studies_to_traits(gcst_ids: list[str], include_background: bool, pause: float = 0.08) -> list[dict]:
    rows = []
    for gcst in gcst_ids:
        gcst = gcst.strip()
        if not re.fullmatch(r"GCST\d+", gcst):
            rows.append({"study_id": gcst, "note": "not a GWAS Catalog accession (e.g. FinnGen); skipped"})
            continue
        study = get_json(f"{API_V2}/studies/{gcst}")
        if study is None:
            rows.append({"study_id": gcst, "note": "not found in GWAS Catalog"})
        else:
            rows.extend(study_rows(study, gcst, include_background))
        time.sleep(pause)
    return rows


def trait_to_studies(efo_id: str, child_traits: bool, include_background: bool) -> list[dict]:
    """Reverse direction: all studies mapped to a trait id (HAL-paginated)."""
    # resolve current label/uri first; obsolete ids return 0 studies silently
    term = get_json(f"{API_V2}/efo-traits/{efo_id}")
    if term is None:
        print(f"trait {efo_id} not in GWAS Catalog EFO table (obsolete id? re-map via OLS first)", file=sys.stderr)
        return []
    rows, page = [], 0
    while True:
        q = urllib.parse.urlencode({"efo_id": efo_id, "show_child_traits": str(child_traits).lower(), "page": page, "size": 200})
        data = get_json(f"{API_V2}/studies?{q}")
        if not data:
            break
        studies = data.get("_embedded", {}).get("studies", []) or data.get("content", []) or []
        for s in studies:
            rows.extend(study_rows(s, s.get("accession_id", ""), include_background))
        pg = data.get("page", {})
        page += 1
        if not studies or page >= pg.get("totalPages", 1):
            break
    return rows


def compare_with_open_targets(catalog_rows: list[dict], ot_traits_csv: str, out_path: str) -> None:
    """Per study: do Open Targets' mapped trait ids agree with the GWAS Catalog's?

    Writes one row per study with status:
      agree            same id set in both
      catalog_extra    Catalog has ids Open Targets lacks
      ot_extra         Open Targets has ids the Catalog lacks
      differ           both sides have ids the other lacks
      not_in_catalog   study id is not a GWAS Catalog accession or 404
    """
    ot: dict[str, dict] = {}
    with open(ot_traits_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = (r.get("gwas_study_id") or r.get("study_id") or "").strip()
            if not sid:
                continue
            d = ot.setdefault(sid, {"ids": set(), "labels": {}, "from_source": r.get("trait_from_source", "")})
            tid = (r.get("trait_id") or "").strip()
            if tid and (r.get("trait_source", "") or "").startswith("open_targets"):
                d["ids"].add(tid)
                d["labels"][tid] = r.get("trait_label", "")
    cat: dict[str, dict] = {}
    for r in catalog_rows:
        sid = r.get("study_id", "")
        d = cat.setdefault(sid, {"ids": set(), "labels": {}, "note": r.get("note", ""), "reported": r.get("reported_trait", "")})
        if r.get("trait_id") and r.get("trait_role", "mapped") == "mapped":
            d["ids"].add(r["trait_id"])
            d["labels"][r["trait_id"]] = r.get("trait_label", "")
    rows, counts = [], {}
    for sid in sorted(set(ot) | set(cat)):
        o, c = ot.get(sid, {"ids": set(), "labels": {}, "from_source": ""}), cat.get(sid, {"ids": set(), "labels": {}, "note": "not queried", "reported": ""})
        if c.get("note") and not c["ids"]:
            status = "not_in_catalog"
        elif o["ids"] == c["ids"]:
            status = "agree"
        elif o["ids"] < c["ids"]:
            status = "catalog_extra"
        elif c["ids"] < o["ids"]:
            status = "ot_extra"
        else:
            status = "differ"
        counts[status] = counts.get(status, 0) + 1
        fmt = lambda d: ";".join(f"{i} ({d['labels'].get(i, '')})" for i in sorted(d["ids"]))
        rows.append({"study_id": sid, "status": status, "ot_trait_ids": fmt(o), "catalog_trait_ids": fmt(c),
                     "catalog_only": ";".join(sorted(c["ids"] - o["ids"])), "ot_only": ";".join(sorted(o["ids"] - c["ids"])),
                     "reported_trait": c.get("reported") or o.get("from_source", ""), "note": c.get("note", "")})
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["study_id"])
        w.writeheader()
        w.writerows(rows)
    print(f"Open Targets vs GWAS Catalog trait mapping, {len(rows)} studies: "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + f" -> {out_path}", file=sys.stderr)
    for r in rows:
        if r["status"] not in ("agree", "not_in_catalog"):
            print(f"  DIFF {r['study_id']} [{r['status']}] OT: {r['ot_trait_ids'] or '-'} | Catalog: {r['catalog_trait_ids'] or '-'}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--studies", nargs="+", help="GCST accessions")
    g.add_argument("--from-csv", help="CSV containing study accessions")
    g.add_argument("--efo", help="Reverse direction: trait id (EFO_..., MONDO_..., HP_...) -> studies")
    ap.add_argument("--id-col", default="gwas_study_id")
    ap.add_argument("--child-traits", action="store_true", help="With --efo: include studies mapped to descendant traits")
    ap.add_argument("--include-background", action="store_true", help="Also emit bg_efo_traits rows (trait_role=background)")
    ap.add_argument("--compare-ot", metavar="OT_TRAITS_CSV", help="04_gwas_traits.csv from ot_gene_to_gwas.py; writes a per-study agreement table next to --out")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.efo:
        rows = trait_to_studies(args.efo, args.child_traits, args.include_background)
    else:
        if args.from_csv:
            with open(args.from_csv, newline="", encoding="utf-8") as f:
                ids = sorted({(r.get(args.id_col) or "").strip() for r in csv.DictReader(f)} - {""})
        else:
            ids = args.studies
        rows = studies_to_traits(ids, args.include_background)

    if not rows:
        print(f"no rows; not writing {args.out}", file=sys.stderr)
        return 0
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    n_studies = len({r["study_id"] for r in rows if r.get("study_id")})
    n_missing = sum(1 for r in rows if r.get("note"))
    print(f"wrote {len(rows)} trait rows for {n_studies} studies ({n_missing} rows with notes) -> {args.out}", file=sys.stderr)
    if args.compare_ot:
        out = args.out.rsplit(".", 1)[0] + "_vs_open_targets.csv"
        compare_with_open_targets(rows, args.compare_ot, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
