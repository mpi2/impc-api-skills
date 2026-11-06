#!/usr/bin/env python3
"""IMPC x GWAS x UniProt, side by side (ideas 2 and 4, prototype).

EXPERIMENTAL (step 6b): output columns may change; not covered by evals yet. See references/uniprot-guide.md.

--concordance-out: one row per gene x IMPC MP term. The best GWAS trait for the term among credible sets
  where the gene is the top L2G gene (similarity, L2G, sets), the best UniProt human disease of the same
  gene (similarity, evidence origin), and whether the mouse UniProt entry has a DISRUPTION PHENOTYPE.
  No combined score. A fixed similarity cutoff cannot say whether a layer agrees: on Tyk2 + Ldlr the
  MP terms scored a median 0.634 against their own gene's UniProt diseases and 0.623 against the other
  gene's. So each layer is tested against a null from the same run: the same MP term scored against the
  other genes' top-L2G traits (GWAS) or UniProt diseases (UniProt). `layers` names a layer only when its
  best similarity beats that null's best. With one gene there is no null and `layers` says so.
--direction-out: one row per step-6 pair whose best credible set's lead variant changes the protein and
  is a UniProt natural variant: the MP term (knockout = loss of the gene), the trait with the allele's
  beta sign, the residue change, UniProt's note, the domain and the mutagenesis results in it. The
  columns are the evidence; whether the directions agree is a reading, written in the report.

Example:
  uv run skills/impc-gwas-trait-mapper/scripts/uniprot_concordance.py --pairs 06_impc_gene_to_gwas_trait.csv \
    --trait-similarity 05_phenotype_trait_similarity.csv --disease-similarity 05b_phenotype_uniprot_disease_similarity.csv --diseases 02_uniprot_diseases.csv \
    --statements 02_uniprot_statements.csv --variants 02_uniprot_gwas_variants.csv \
    --concordance-out 06b_uniprot_concordance.csv --direction-out 06c_direction_evidence.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict

CONC_FIELDS = ["marker_symbol", "human_symbol", "mp_term_id", "mp_term_name", "layers",
               "gwas_trait", "gwas_similarity", "gwas_null_best", "gwas_l2g_score", "gwas_n_credible_sets",
               "gwas_n_traits_compared", "gwas_n_null_traits",
               "uniprot_disease", "uniprot_similarity", "uniprot_null_best", "uniprot_n_null_diseases",
               "uniprot_disease_origin",
               "mouse_disruption_phenotype", "mouse_disruption_origin"]
DIR_FIELDS = ["marker_symbol", "human_symbol", "mp_term_id", "mp_term_name", "trait_label", "similarity",
              "best_cs_l2g_score", "lead_variant", "best_cs_beta_alt", "best_cs_direction_alt", "residue_change",
              "uniprot_note", "domain", "domain_mutagenesis", "uniprot_disease", "mouse_disruption_phenotype"]


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: str, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", required=True, help="06_impc_gene_to_gwas_trait.csv")
    ap.add_argument("--trait-similarity", required=True, help="05_phenotype_trait_similarity.csv (all MP x trait pairs)")
    ap.add_argument("--disease-similarity", required=True, help="ols_similarity.py output: MP x UniProt disease")
    ap.add_argument("--model", default="harrier-oss-v1-27b_pca512", help="Similarity model to read (default harrier)")
    ap.add_argument("--diseases", required=True, help="02_uniprot_diseases.csv")
    ap.add_argument("--statements", required=True, help="02_uniprot_statements.csv")
    ap.add_argument("--variants", required=True, help="02_uniprot_gwas_variants.csv")
    ap.add_argument("--concordance-out", required=True)
    ap.add_argument("--direction-out", required=True)
    args = ap.parse_args()

    pairs = read_csv(args.pairs)
    diseases = defaultdict(list)  # human symbol -> UniProt disease rows with an OT id
    for d in read_csv(args.diseases):
        if d["trait_id"]:
            diseases[d["human_symbol"]].append(d)
    dis_sim = {(r["phenotype_id"], r["trait_id"]): num(r["similarity"]) for r in read_csv(args.disease_similarity)
               if r.get("model", args.model) == args.model}
    trait_sim = {(r["phenotype_id"], r["trait_id"]): num(r["similarity"]) for r in read_csv(args.trait_similarity)
                 if r.get("model", args.model) == args.model}
    top_traits = defaultdict(set)  # human symbol -> trait ids from credible sets where it is the top L2G gene
    for p in pairs:
        if p["best_cs_l2g_rank"] in ("1", "1.0"):
            top_traits[p["human_symbol"]].add(p["trait_id"])
    disruption = {}
    for s in read_csv(args.statements):
        if s["species"] == "mouse" and s["section"] == "DISRUPTION PHENOTYPE":
            disruption[s["mouse_symbol"]] = s
    on_protein = {(v["human_symbol"], v["lead_variant"]): v for v in read_csv(args.variants) if v["uniprot_variant_id"]}

    by_term = defaultdict(list)
    for p in pairs:
        by_term[(p["marker_symbol"], p["human_symbol"], p["mp_term_id"], p["mp_term_name"])].append(p)

    conc = []
    for (mouse, human, mp, mp_name), rows in by_term.items():
        top = [r for r in rows if r["best_cs_l2g_rank"] in ("1", "1.0")]
        g = max(top, key=lambda r: num(r["similarity"]), default=None)
        u = max(((d, dis_sim.get((mp, d["trait_id"]), float("nan"))) for d in diseases.get(human, [])),
                key=lambda x: x[1] if x[1] == x[1] else -1, default=(None, float("nan")))
        gs, us = (num(g["similarity"]) if g else float("nan")), u[1]
        others = [h for h in top_traits.keys() | diseases.keys() if h != human]
        null_traits = {t for h in others for t in top_traits.get(h, ())} - top_traits.get(human, set())
        null_dis = {d["trait_id"] for h in others for d in diseases.get(h, ())} - {d["trait_id"] for d in diseases.get(human, ())}
        g_null = max((trait_sim.get((mp, t), float("nan")) for t in null_traits), default=float("nan"))
        u_null = max((dis_sim.get((mp, t), float("nan")) for t in null_dis), default=float("nan"))
        named = [name for name, s, n in (("GWAS", gs, g_null), ("UniProt", us, u_null)) if s == s and n == n and s > n]
        if not others:
            named = ["no null (single gene)"]
        dr = disruption.get(mouse)
        conc.append({"marker_symbol": mouse, "human_symbol": human, "mp_term_id": mp, "mp_term_name": mp_name,
                     "layers": " + ".join(["IMPC"] + named),
                     "gwas_trait": f"{g['trait_label']} ({g['trait_id']})" if g else "",
                     "gwas_similarity": round(gs, 3) if g else "", "gwas_l2g_score": round(num(g["best_cs_l2g_score"]), 3) if g else "",
                     "gwas_n_credible_sets": g["n_credible_sets"] if g else "", "gwas_n_traits_compared": len(top),
                     "gwas_null_best": round(g_null, 3) if g_null == g_null else "", "gwas_n_null_traits": len(null_traits),
                     "uniprot_null_best": round(u_null, 3) if u_null == u_null else "", "uniprot_n_null_diseases": len(null_dis),
                     "uniprot_disease": f"{u[0]['disease_acronym']} ({u[0]['trait_id']})" if u[0] else "",
                     "uniprot_similarity": round(us, 3) if u[0] else "",
                     "uniprot_disease_origin": u[0]["origin"] if u[0] else "",
                     "mouse_disruption_phenotype": "yes" if dr else "no", "mouse_disruption_origin": dr["origin"] if dr else ""})
    conc.sort(key=lambda r: (r["marker_symbol"], -len(r["layers"]), -num(r["gwas_similarity"] or 0)))

    dirs = []
    for p in pairs:
        v = on_protein.get((p["human_symbol"], p["best_cs_lead_variant"]))
        if v:
            dis = "; ".join(d["disease_acronym"] for d in diseases.get(p["human_symbol"], []))
            dirs.append({**p, "lead_variant": p["best_cs_lead_variant"], "residue_change": v["residue_change"],
                         "uniprot_note": v["uniprot_note"], "domain": v["domain"],
                         "domain_mutagenesis": v["domain_mutagenesis"], "uniprot_disease": dis,
                         "mouse_disruption_phenotype": (disruption.get(p["marker_symbol"]) or {}).get("text", "")})
    dirs.sort(key=lambda r: (r["marker_symbol"], -num(r["similarity"])))

    write_csv(args.concordance_out, CONC_FIELDS, conc)
    write_csv(args.direction_out, DIR_FIELDS, dirs)
    counts = defaultdict(int)
    for r in conc:
        counts[r["layers"]] += 1
    print(f"{len(conc)} gene x MP terms ({args.model}): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
          + f" -> {args.concordance_out}", file=sys.stderr)
    print(f"{len(dirs)} pairs whose best credible set's lead variant is a UniProt natural variant -> {args.direction_out}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
