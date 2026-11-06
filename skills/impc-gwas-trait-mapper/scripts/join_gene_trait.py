#!/usr/bin/env python3
"""Step 6: join IMPC calls, orthologs, L2G credible sets, study traits and MP x trait similarity.

Each IMPC call is joined only to the credible sets of its own gene (via the one-to-one ortholog), then to the
traits of each set's study, then to the similarity of that MP term x trait. When the orthologs file gives one
mouse gene several human genes (non-one-to-one pairs chosen by the user), each pair is joined separately and
rows carry their own hgnc_id/human_symbol. Two outputs, two grains:

--detail-out  06_detail_impc_call_x_credible_set.csv: one row per IMPC call x credible set x trait, unfiltered.
--out         06_impc_gene_to_gwas_trait.csv: one row per gene x MP term x trait. n_credible_sets and
              n_lead_variants count the gene's sets for that trait; best_cs_* come from the set where the gene's
              L2G score is highest (ties: study_locus_id). Kept when best_cs_l2g_rank <= --max-rank (default 3)
              OR the pair passes the similarity rule. That rule depends on how step 5 ran: with the top-K
              neighbourhood filter (similarity file has a knn_rank column) every scored pair passed the filter,
              so any similarity keeps the row; with --top-k 0 (every pair scored) similarity must reach 0.60.
              --min-similarity overrides either default.

Both sorted by similarity desc, then L2G desc. Values are copied from the inputs as written, not reformatted.
When the similarity file holds several models, every row is repeated per model with a `similarity_model`
column; use --model to keep one. An empty similarity file (no pair passed the step 5 filter) is not an error:
similarity is left blank and the main table keeps rows on the L2G rank rule alone.

Example:
  uv run skills/impc-gwas-trait-mapper/scripts/join_gene_trait.py --phenotypes 01_impc_phenotypes.csv \
    --orthologs 02_orthologs.csv --links 03_l2g_gwas_links.csv --traits 04_gwas_traits.csv \
    --similarity 05_phenotype_trait_similarity.csv \
    --out 06_impc_gene_to_gwas_trait.csv --detail-out 06_detail_impc_call_x_credible_set.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict

DETAIL = ["marker_accession_id", "marker_symbol", "mp_term_id", "mp_term_name", "impc_p_value", "effect_size",
          "zygosity", "sex", "hgnc_id", "human_symbol", "l2g_score", "l2g_rank_in_locus", "top_l2g_gene_in_locus",
          "study_locus_id", "confidence", "lead_variant", "beta_alt", "trait_direction_alt", "gwas_study_id",
          "trait_id", "trait_label", "similarity"]
KEYS = ["marker_accession_id", "marker_symbol", "mp_term_id", "mp_term_name", "hgnc_id", "human_symbol",
        "trait_id", "trait_label"]
MAIN = KEYS + ["similarity", "n_credible_sets", "n_lead_variants", "best_cs_l2g_score", "best_cs_l2g_rank",
               "best_cs_l2g_n_genes", "best_cs_l2g_top_gene", "best_cs_confidence", "best_cs_lead_variant",
               "best_cs_beta_alt", "best_cs_direction_alt", "best_cs_study_id", "best_cs_study_locus_id"]
# main-table column <- links column, for the best credible set
BEST = {"best_cs_l2g_score": "l2g_score", "best_cs_l2g_rank": "l2g_rank_in_locus",
        "best_cs_l2g_n_genes": "n_l2g_genes_in_locus", "best_cs_l2g_top_gene": "top_l2g_gene_in_locus",
        "best_cs_confidence": "confidence", "best_cs_lead_variant": "lead_variant", "best_cs_beta_alt": "beta_alt",
        "best_cs_direction_alt": "trait_direction_alt", "best_cs_study_id": "gwas_study_id",
        "best_cs_study_locus_id": "study_locus_id"}


def read(path: str, required: list[str]) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"{path}: missing columns {missing}; columns: {reader.fieldnames}")
        return list(reader)


def num(x: str, default: float = float("-inf")) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def write(path: str, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {path}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phenotypes", required=True, help="01_impc_phenotypes.csv")
    ap.add_argument("--orthologs", required=True, help="02_orthologs.csv (mgiGeneAccId, hgncAccId, humanGeneSymbol)")
    ap.add_argument("--links", required=True, help="03_l2g_gwas_links.csv")
    ap.add_argument("--traits", required=True, help="04_gwas_traits.csv")
    ap.add_argument("--similarity", required=True, help="05_phenotype_trait_similarity.csv")
    ap.add_argument("--out", required=True, help="Main table, one row per gene x MP term x trait")
    ap.add_argument("--detail-out", help="Audit table, one row per IMPC call x credible set x trait")
    ap.add_argument("--max-rank", type=int, default=3, help="Keep pairs whose best set ranks the gene this high or better")
    ap.add_argument("--min-similarity", type=float, default=None,
                    help="...or whose similarity reaches this. Default: any score when step 5 used the top-K "
                         "filter, 0.60 when it scored every pair (--top-k 0)")
    ap.add_argument("--model", help="Similarity model to keep when the file holds several")
    args = ap.parse_args()

    calls = read(args.phenotypes, ["marker_accession_id", "marker_symbol", "mp_term_id", "mp_term_name",
                                   "p_value", "effect_size", "zygosity", "sex"])
    # A mouse gene can carry several human genes when the user opts into non-one-to-one pairs
    # (e.g. Slco1b2 -> SLCO1B1 and SLCO1B3). Keep every distinct pair; a dict keyed on the MGI id alone
    # silently kept only the last one.
    orth: dict[str, list[dict]] = defaultdict(list)
    for r in read(args.orthologs, ["mgiGeneAccId", "hgncAccId", "humanGeneSymbol"]):
        if r["hgncAccId"] not in {o["hgncAccId"] for o in orth[r["mgiGeneAccId"]]}:
            orth[r["mgiGeneAccId"]].append(r)
    for mgi, os_ in orth.items():
        if len(os_) > 1:
            print(f"{mgi}: {len(os_)} human genes ({', '.join(o['humanGeneSymbol'] for o in os_)}); "
                  "each pair joined separately", file=sys.stderr)
    links = read(args.links, list(BEST.values()) + ["hgnc_id"])
    sets_by_gene: dict[str, list[dict]] = defaultdict(list)
    for r in links:
        sets_by_gene[r["hgnc_id"]].append(r)
    traits_by_study: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in read(args.traits, ["gwas_study_id", "trait_id", "trait_label"]):
        t = (r["trait_id"], r["trait_label"])
        if r["trait_id"] and t not in traits_by_study[r["gwas_study_id"]]:
            traits_by_study[r["gwas_study_id"]].append(t)
    sim: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    models: set[str] = set()
    sim_rows = read(args.similarity, ["phenotype_id", "trait_id", "similarity", "model"])
    with open(args.similarity, newline="", encoding="utf-8") as f:
        topk_filtered = "knn_rank" in (next(csv.reader(f), []) or [])
    if args.min_similarity is None:
        args.min_similarity = float("-inf") if topk_filtered else 0.60
    sim_rule = ("any similarity (top-K filtered)" if args.min_similarity == float("-inf")
                else f"similarity >= {args.min_similarity}")
    file_models = {r["model"] for r in sim_rows}
    if args.model and file_models and args.model not in file_models:
        sys.exit(f"model {args.model} not in {args.similarity}; models there: {', '.join(sorted(file_models))}")
    for r in sim_rows:
        if args.model and r["model"] != args.model:
            continue
        if r["similarity"] != "":
            sim[(r["phenotype_id"], r["trait_id"])][r["model"]] = r["similarity"]
            models.add(r["model"])
    # An empty similarity file is a valid result (e.g. the top-K filter kept no pair): join anyway, leave
    # similarity blank, so the main table keeps rows on the L2G rank rule alone.
    no_scores = not models
    if no_scores:
        print(f"no similarity values in {args.similarity} ({len(sim_rows)} rows): similarity left blank, "
              f"main table keeps rows by best_cs_l2g_rank <= {args.max_rank} only", file=sys.stderr)
    multi = len(models) > 1
    model_list = sorted(models) or [""]

    detail, no_orth, no_sets, no_sim = [], set(), set(), 0
    for c in calls:
        os_ = orth.get(c["marker_accession_id"], [])
        if not os_:
            no_orth.add(c["marker_symbol"])
            continue
        no_sets.update(o["humanGeneSymbol"] for o in os_ if not sets_by_gene.get(o["hgncAccId"]))
        for o, s in ((o, s) for o in os_ for s in sets_by_gene.get(o["hgncAccId"], [])):
            for trait_id, trait_label in traits_by_study.get(s["gwas_study_id"], []):
                scores = sim.get((c["mp_term_id"], trait_id), {})
                for m in model_list:
                    if m not in scores:
                        no_sim += 1
                    row = {**{k: c[k] for k in ("marker_accession_id", "marker_symbol", "mp_term_id", "mp_term_name",
                                                "effect_size", "zygosity", "sex")},
                           "impc_p_value": c["p_value"], "hgnc_id": o["hgncAccId"], "human_symbol": o["humanGeneSymbol"],
                           **{k: s.get(k, "") for k in ("l2g_score", "l2g_rank_in_locus", "top_l2g_gene_in_locus",
                                                        "study_locus_id", "confidence", "lead_variant", "beta_alt",
                                                        "trait_direction_alt", "gwas_study_id")},
                           "trait_id": trait_id, "trait_label": trait_label, "similarity": scores.get(m, ""),
                           "similarity_model": m, "_set": s}
                    detail.append(row)

    def order(r):
        return (-num(r["similarity"]), -num(r["l2g_score"]), r["marker_symbol"], r["mp_term_id"], r["trait_id"])

    detail.sort(key=order)

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in detail:
        groups[tuple(r[k] for k in KEYS) + (r["similarity_model"],)].append(r)
    pairs = []
    for key, rows in groups.items():
        sets = {r["study_locus_id"]: r["_set"] for r in rows}
        best = min(sets.values(), key=lambda s: (-num(s["l2g_score"]), s["study_locus_id"]))
        pairs.append({**dict(zip(KEYS, key)), "similarity_model": key[-1], "similarity": rows[0]["similarity"],
                      "n_credible_sets": len(sets), "n_lead_variants": len({s["lead_variant"] for s in sets.values()}),
                      **{out: best.get(src, "") for out, src in BEST.items()}})
    pairs.sort(key=lambda r: (-num(r["similarity"]), -num(r["best_cs_l2g_score"]), r["marker_symbol"],
                              r["mp_term_id"], r["trait_id"]))
    kept = [r for r in pairs if num(r["best_cs_l2g_rank"], float("inf")) <= args.max_rank
            or (r["similarity"] != "" and num(r["similarity"]) >= args.min_similarity)]

    extra = ["similarity_model"] if multi else []
    write(args.out, kept, MAIN + extra)
    if args.detail_out:
        write(args.detail_out, detail, DETAIL + extra)

    per_gene = defaultdict(int)
    for r in kept:
        per_gene[f"{r['marker_symbol']}->{r['human_symbol']}"] += 1
    print(f"{len(calls)} IMPC calls; {len(detail)} detail rows; {len(pairs)} pairs -> {len(kept)} kept "
          f"(rank <= {args.max_rank} or {sim_rule}); per gene: {dict(per_gene)}; "
          f"models: {', '.join(model_list) if not no_scores else 'none'}", file=sys.stderr)
    if no_orth:
        print("no one-to-one ortholog (branch stopped): " + ", ".join(sorted(no_orth)), file=sys.stderr)
    if no_sets:
        print("no GWAS credible sets with L2G evidence (branch stopped): " + ", ".join(sorted(no_sets)), file=sys.stderr)
    if no_sim and not no_scores:
        print(f"{no_sim} detail rows without a similarity score (run step 5 on the same phenotype and trait files)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
