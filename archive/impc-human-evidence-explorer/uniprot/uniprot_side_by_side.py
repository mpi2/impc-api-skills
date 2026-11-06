#!/usr/bin/env python3
"""IMPC phenotype, its top GWAS row and the gene's UniProt annotations in one table (data only).

EXPERIMENTAL (step 6b): output columns may change; not covered by evals yet. See references/uniprot-guide.md.

One row per gene x IMPC MP term. The GWAS columns are the term's first row in 06_impc_gene_to_gwas_trait.csv,
which step 6 sorts by similarity, then L2G. The UniProt columns are gene-level, as UniProt writes them, and
repeat on every MP term of the gene: the human DISEASE comments (name, acronym, MIM id, evidence origin) and
the mouse DISRUPTION PHENOTYPE text with its origin. Nothing is scored, matched or judged.

Example:
  uv run skills/impc-gwas-trait-mapper/scripts/uniprot_side_by_side.py --pairs 06_impc_gene_to_gwas_trait.csv \
    --phenotypes 01_impc_phenotypes.csv --diseases 02_uniprot_diseases.csv --statements 02_uniprot_statements.csv \
    --out 06b_impc_gwas_uniprot.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict

FIELDS = ["marker_symbol", "human_symbol", "mp_term_id", "mp_term_name",
          "gwas_trait_id", "gwas_trait_label", "similarity", "best_cs_l2g_score", "best_cs_l2g_rank",
          "n_credible_sets", "best_cs_lead_variant", "best_cs_study_id",
          "uniprot_human_diseases", "uniprot_disease_mims", "uniprot_disease_origin",
          "uniprot_mouse_disruption_phenotype", "uniprot_mouse_disruption_origin"]


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", required=True, help="06_impc_gene_to_gwas_trait.csv")
    ap.add_argument("--phenotypes", required=True, help="01_impc_phenotypes.csv (MP terms without a GWAS row keep a row)")
    ap.add_argument("--diseases", required=True, help="02_uniprot_diseases.csv")
    ap.add_argument("--statements", required=True, help="02_uniprot_statements.csv")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    first = {}
    for p in read_csv(args.pairs):  # already in step-6 order
        first.setdefault((p["marker_symbol"], p["mp_term_id"]), p)
    diseases = defaultdict(list)
    for d in read_csv(args.diseases):
        diseases[d["mouse_symbol"]].append(d)
    disruption = defaultdict(list)
    for s in read_csv(args.statements):
        if s["species"] == "mouse" and s["section"] == "DISRUPTION PHENOTYPE":
            disruption[s["mouse_symbol"]].append(s)

    rows, seen = [], set()
    for ph in read_csv(args.phenotypes):
        key = (ph["marker_symbol"], ph["mp_term_id"])
        if key in seen:
            continue
        seen.add(key)
        g = first.get(key, {})
        ds, dr = diseases.get(ph["marker_symbol"], []), disruption.get(ph["marker_symbol"], [])
        rows.append({"marker_symbol": ph["marker_symbol"], "human_symbol": g.get("human_symbol", ""),
                     "mp_term_id": ph["mp_term_id"], "mp_term_name": ph["mp_term_name"],
                     "gwas_trait_id": g.get("trait_id", ""), "gwas_trait_label": g.get("trait_label", ""),
                     "similarity": g.get("similarity", ""), "best_cs_l2g_score": g.get("best_cs_l2g_score", ""),
                     "best_cs_l2g_rank": g.get("best_cs_l2g_rank", ""), "n_credible_sets": g.get("n_credible_sets", ""),
                     "best_cs_lead_variant": g.get("best_cs_lead_variant", ""), "best_cs_study_id": g.get("best_cs_study_id", ""),
                     "uniprot_human_diseases": "; ".join(f"{d['disease_name']} ({d['disease_acronym']})" for d in ds),
                     "uniprot_disease_mims": "; ".join(d["disease_mim"] for d in ds),
                     "uniprot_disease_origin": "; ".join(sorted({d["origin"] for d in ds})),
                     "uniprot_mouse_disruption_phenotype": " | ".join(s["text"] for s in dr),
                     "uniprot_mouse_disruption_origin": "; ".join(sorted({s["origin"] for s in dr}))})

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    genes = {r["marker_symbol"] for r in rows}
    print(f"{len(rows)} gene x MP term rows for {len(genes)} genes ({sum(1 for r in rows if r['gwas_trait_id'])} with a "
          f"GWAS row, {len({r['marker_symbol'] for r in rows if r['uniprot_human_diseases']})} genes with a UniProt "
          f"disease, {len({r['marker_symbol'] for r in rows if r['uniprot_mouse_disruption_phenotype']})} with a mouse "
          f"disruption phenotype) -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
