#!/usr/bin/env python3
"""Pairwise embedding similarity between IMPC phenotypes (MP) and GWAS traits (EFO/OBA/MONDO/HP) via the OLS MCP server.

The OLS MCP `getClassSimilarity` tool returns the cosine similarity (0-1) of two
ontology classes' precomputed label/definition embeddings. This script runs it
for every phenotype x trait pair and writes a long-format table.

Example:
  uv run skills/impc-gwas-trait-mapper/scripts/ols_similarity.py \
      --phenotypes 01_impc_phenotypes.csv --phenotype-id-col mp_term_id --phenotype-label-col mp_term_name \
      --traits 04_gwas_traits.csv --trait-id-col trait_id --trait-label-col trait_label \
      --out 05_phenotype_trait_similarity.csv

Identifiers may be CURIEs (MP:0005566, EFO:0001360), underscore form
(EFO_0001360, MONDO_0005148) or full IRIs. Rows with an empty id are skipped.
"""
from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_client import McpClient  # noqa: E402

OLS_MCP = "https://www.ebi.ac.uk/ols4/api/mcp"
DEFAULT_MODEL = "harrier-oss-v1-27b_pca512"

EFO_PREFIXES = {"EFO"}
OBO_PREFIXES = {"MP", "HP", "MONDO", "OBA", "GO", "UBERON", "PATO", "CHEBI", "DOID", "NCIT", "UPHENO", "VT", "CL"}


def to_iri(term: str) -> str | None:
    term = (term or "").strip()
    if not term:
        return None
    if term.startswith("http://") or term.startswith("https://"):
        return term
    if ":" in term:
        prefix, local = term.split(":", 1)
    elif "_" in term:
        prefix, local = term.split("_", 1)
    else:
        return None
    prefix = prefix.upper()
    if prefix in EFO_PREFIXES:
        return f"http://www.ebi.ac.uk/efo/EFO_{local}"
    if prefix == "ORPHANET":
        return f"http://www.orpha.net/ORDO/Orphanet_{local}"
    return f"http://purl.obolibrary.org/obo/{prefix}_{local}"


def read_terms(path: str, id_col: str, label_col: str | None) -> list[dict]:
    seen, out = set(), []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = (row.get(id_col) or "").strip()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out.append({"id": tid, "label": (row.get(label_col) or "").strip() if label_col else "", "iri": to_iri(tid)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phenotypes", required=True, help="CSV with IMPC phenotype terms (one row per term or per association; deduplicated on id)")
    ap.add_argument("--phenotype-id-col", default="mp_term_id")
    ap.add_argument("--phenotype-label-col", default="mp_term_name")
    ap.add_argument("--traits", required=True, help="CSV with GWAS trait terms")
    ap.add_argument("--trait-id-col", default="trait_id")
    ap.add_argument("--trait-label-col", default="trait_label")
    ap.add_argument("--model", nargs="+", default=[DEFAULT_MODEL], help="One or more OLS embedding models (see listEmbeddingModels); one output row per pair per model")
    ap.add_argument("--list-models", action="store_true", help="Print the models OLS currently offers and exit")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--min-score", type=float, default=None, help="Only keep pairs at or above this similarity (default: keep all)")
    args = ap.parse_args()

    client = McpClient(OLS_MCP)
    available = {m["model"]: m for m in client.call_json("listEmbeddingModels", {})}
    if args.list_models:
        for m in available.values():
            print(f"{m['model']}\tcan_embed={m['can_embed']}")
        return 0
    unknown = [m for m in args.model if m not in available]
    if unknown:
        sys.exit(f"unknown model(s) {unknown}; OLS offers: {sorted(available)}")

    phenos = read_terms(args.phenotypes, args.phenotype_id_col, args.phenotype_label_col)
    traits = read_terms(args.traits, args.trait_id_col, args.trait_label_col)
    pairs = [(p, t, m) for m in args.model for p in phenos for t in traits if p["iri"] and t["iri"]]
    skipped = [x["id"] for x in phenos + traits if not x["iri"]]
    print(f"{len(phenos)} phenotypes x {len(traits)} traits x {len(args.model)} model(s) = {len(pairs)} calls; models={args.model}", file=sys.stderr)
    if skipped:
        print(f"skipped unparseable ids: {skipped}", file=sys.stderr)

    def score(job):
        p, t, model = job
        try:
            val = float(client.call("getClassSimilarity", {"classIri1": p["iri"], "classIri2": t["iri"], "model": model}))
            return p, t, model, val, ""
        except Exception as e:  # term missing from OLS embeddings, transport error, etc.
            return p, t, model, None, str(e)[:200]

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(score, pairs))

    rows = []
    for p, t, model, val, err in results:
        rows.append({"phenotype_id": p["id"], "phenotype_label": p["label"], "trait_id": t["id"], "trait_label": t["label"],
                     "model": model, "similarity": val, "error": err})
    scored = [r for r in rows if r["similarity"] is not None]
    # rank within each phenotype and within each trait, separately per model
    for key, rank_col in (("phenotype_id", "rank_within_phenotype"), ("trait_id", "rank_within_trait")):
        groups: dict[tuple, list[dict]] = {}
        for r in scored:
            groups.setdefault((r["model"], r[key]), []).append(r)
        for g in groups.values():
            for i, r in enumerate(sorted(g, key=lambda r: -r["similarity"]), 1):
                r[rank_col] = i
    for model in args.model:
        vals = sorted(r["similarity"] for r in scored if r["model"] == model)
        if vals:
            print(f"{model}: n={len(vals)} min={vals[0]:.3f} median={vals[len(vals) // 2]:.3f} max={vals[-1]:.3f}", file=sys.stderr)
    if args.min_score is not None:
        rows = [r for r in rows if r["similarity"] is None or r["similarity"] >= args.min_score]
    rows.sort(key=lambda r: (r["model"], -(r["similarity"] or -1), r["phenotype_id"], r["trait_id"]))

    fields = ["phenotype_id", "phenotype_label", "trait_id", "trait_label", "similarity", "rank_within_phenotype", "rank_within_trait", "model", "error"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    n_err = sum(1 for r in rows if r["similarity"] is None)
    print(f"wrote {len(rows)} rows to {args.out} ({n_err} pairs failed)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
