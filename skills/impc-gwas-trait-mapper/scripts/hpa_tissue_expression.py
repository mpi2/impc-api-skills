#!/usr/bin/env python3
"""Human genes -> Human Protein Atlas (HPA) tissue RNA expression, as gene-level context.

EXPERIMENTAL (step 2b): output columns may change; not covered by evals yet.

Uses the documented HPA download API (no auth), not the unofficial HPA MCP:
  https://www.proteinatlas.org/api/search_download.php?search=..&format=json&columns=..&compress=no
Column codes: https://www.proteinatlas.org/about/help/dataaccess. Unknown codes are silently
dropped by the API, so the tissue list below is pinned to the documented t_RNA_* codes.
See references/hpa-guide.md.

--out: one row per gene. HPA's own specificity call (category, score, tau, enriched tissues
and cell types), the number of the 51 consensus tissues with nTPM >= 1 and the top tissues
by nTPM. It describes the gene; it does not link any tissue to an IMPC phenotype.
--tissues-out (optional): one row per gene x tissue with the consensus nTPM (HPA + GTEx).

Symbols are matched exactly on HPA "Gene" or "Ensembl" (the search itself is fuzzy);
a query with no unique exact hit gets a row with a note and is named on stderr.

Examples:
  uv run skills/impc-gwas-trait-mapper/scripts/hpa_tissue_expression.py --from-csv 02_orthologs.csv --id-col humanGeneSymbol --out 02_hpa_tissue_expression.csv
  uv run skills/impc-gwas-trait-mapper/scripts/hpa_tissue_expression.py --genes PNPT1 ENSG00000163631 --out hpa.csv --tissues-out hpa_tissues.csv
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

SEARCH_API = "https://www.proteinatlas.org/api/search_download.php"
GENE_URL = "https://www.proteinatlas.org/{}"
TISSUES = ["adipose tissue", "adrenal gland", "amygdala", "appendix", "basal ganglia", "blood vessel", "bone marrow",
           "breast", "cerebellum", "cerebral cortex", "cervix", "choroid plexus", "colon", "duodenum", "endometrium 1",
           "epididymis", "esophagus", "fallopian tube", "gallbladder", "heart muscle", "hippocampal formation",
           "hypothalamus", "kidney", "liver", "lung", "lymph node", "midbrain", "ovary", "pancreas", "parathyroid gland",
           "pituitary gland", "placenta", "prostate", "rectum", "retina", "salivary gland", "seminal vesicle",
           "skeletal muscle", "skin 1", "small intestine", "smooth muscle", "spinal cord", "spleen", "stomach 1", "testis",
           "thymus", "thyroid gland", "tongue", "tonsil", "urinary bladder", "vagina"]
# column code -> HPA JSON key
SUMMARY = {"g": "Gene", "eg": "Ensembl", "rnats": "RNA tissue specificity", "rnatd": "RNA tissue distribution",
           "rnatss": "RNA tissue specificity score", "rnatsm": "RNA tissue specific nTPM",
           "rnascs": "RNA single cell type specificity", "rnascsm": "RNA single cell type specific nCPM",
           "t_RNA__tau": "TAU score - Tissue"}
DETECTED_NTPM = 1.0  # HPA's own "detected" threshold
FIELDS = ["query", "human_symbol", "ensembl_id", "tissue_specificity", "tissue_distribution", "specificity_score",
          "tau", "enriched_tissues_ntpm", "n_tissues_detected", "top_tissues_ntpm", "cell_type_specificity",
          "enriched_cell_types_ncpm", "hpa_url", "note"]
TISSUE_FIELDS = ["human_symbol", "ensembl_id", "tissue", "ntpm", "rank"]


def get_json(url: str, retries: int = 3, timeout: int = 60):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
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


def search(query: str) -> list[dict]:
    cols = list(SUMMARY) + ["t_RNA_" + t.replace(" ", "_") for t in TISSUES]
    qs = urllib.parse.urlencode({"search": query, "format": "json", "columns": ",".join(cols), "compress": "no"})
    return get_json(f"{SEARCH_API}?{qs}") or []


def pick(query: str, hits: list[dict]) -> dict | None:
    q = query.upper()
    exact = [h for h in hits if q in ((h.get("Gene") or "").upper(), (h.get("Ensembl") or "").upper())]
    return exact[0] if len(exact) == 1 else None


def fmt_map(d) -> str:
    return "; ".join(f"{k} {v}" for k, v in d.items()) if isinstance(d, dict) else ""


def tissue_values(hit: dict) -> list[tuple[str, float]]:
    vals = []
    for t in TISSUES:
        v = hit.get(f"Tissue RNA - {t} [nTPM]")
        if v not in (None, ""):
            vals.append((t, float(v)))
    return sorted(vals, key=lambda x: -x[1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--genes", nargs="+", help="Human gene symbols or Ensembl gene ids (ENSG...)")
    g.add_argument("--from-csv", help="CSV to read genes from")
    ap.add_argument("--id-col", default="humanGeneSymbol", help="Column in --from-csv (symbols or ENSG ids)")
    ap.add_argument("--top", type=int, default=5, help="Tissues listed in top_tissues_ntpm (default 5)")
    ap.add_argument("--out", required=True, help="Gene-level CSV, one row per gene")
    ap.add_argument("--tissues-out", help="Optional long CSV, one row per gene x tissue")
    args = ap.parse_args()

    if args.from_csv:
        with open(args.from_csv, newline="", encoding="utf-8") as f:
            genes = sorted({(r.get(args.id_col) or "").strip() for r in csv.DictReader(f)} - {""})
    else:
        genes = list(dict.fromkeys(args.genes))

    rows, tissue_rows, missing = [], [], []
    for i, q in enumerate(genes):
        hit = pick(q, search(q))
        if hit is None:
            missing.append(q)
            rows.append({"query": q, "note": "no unique exact match in HPA"})
        else:
            vals = tissue_values(hit)
            rows.append({
                "query": q, "human_symbol": hit.get("Gene"), "ensembl_id": hit.get("Ensembl"),
                "tissue_specificity": hit.get(SUMMARY["rnats"]), "tissue_distribution": hit.get(SUMMARY["rnatd"]),
                "specificity_score": hit.get(SUMMARY["rnatss"]), "tau": hit.get(SUMMARY["t_RNA__tau"]),
                "enriched_tissues_ntpm": fmt_map(hit.get(SUMMARY["rnatsm"])),
                "n_tissues_detected": f"{sum(v >= DETECTED_NTPM for _, v in vals)}/{len(TISSUES)}",
                "top_tissues_ntpm": "; ".join(f"{t} {v:g}" for t, v in vals[:args.top]),
                "cell_type_specificity": hit.get(SUMMARY["rnascs"]),
                "enriched_cell_types_ncpm": fmt_map(hit.get(SUMMARY["rnascsm"])),
                "hpa_url": GENE_URL.format(hit.get("Ensembl")), "note": ""})
            tissue_rows.extend({"human_symbol": hit.get("Gene"), "ensembl_id": hit.get("Ensembl"), "tissue": t,
                                "ntpm": v, "rank": r} for r, (t, v) in enumerate(vals, 1))
        if i < len(genes) - 1:
            time.sleep(0.3)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    if args.tissues_out:
        with open(args.tissues_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=TISSUE_FIELDS)
            w.writeheader()
            w.writerows(tissue_rows)
    print(f"{len(genes) - len(missing)}/{len(genes)} genes found in HPA -> {args.out}", file=sys.stderr)
    if missing:
        print("not matched: " + ", ".join(missing), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
