#!/usr/bin/env python3
"""Embedding similarity between IMPC phenotypes (MP) and GWAS traits (EFO/OBA/MONDO/HP/GO) via OLS.

Default mode (--top-k 20): nearest neighbours in each ontology, then join.
  For each MP term, OLS returns its K nearest classes in each searched ontology
  (default EFO, MONDO, OBA, HP, GO: K from each; obsolete classes and MONDO
  non-human animal diseases dropped). A GWAS trait is kept for that MP term
  only if it is among the K nearest classes of its own ontology. The trait list
  does not influence which classes compete for the slots, so a trait has to
  beat every other class in its ontology, not only the other traits Open
  Targets returned. Kept pairs are then scored with OLS `getClassSimilarity`,
  the same score as in --top-k 0 mode. --top-k-scope pooled shares K slots
  across all ontologies instead (stricter; MONDO and HP crowd out the rest).

--top-k 0: every phenotype x trait pair is scored with `getClassSimilarity`
  (the earlier behaviour; no neighbourhood filter).

Example:
  uv run skills/impc-gwas-trait-mapper/scripts/ols_similarity.py \
      --phenotypes 01_impc_phenotypes.csv --phenotype-id-col mp_term_id --phenotype-label-col mp_term_name \
      --traits 04_gwas_traits.csv --trait-id-col trait_id --trait-label-col trait_label \
      --out 05_phenotype_trait_similarity.csv

In top-K mode a second file (default <out>_neighbours.csv) lists every MP
term's K neighbours with `is_gwas_trait`, so the reader can see what the GWAS
traits were competing against.

Identifiers may be CURIEs (MP:0005566, EFO:0001360), underscore form
(EFO_0001360, MONDO_0005148) or full IRIs. Rows with an empty id are skipped.
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_client import McpClient  # noqa: E402

OLS_MCP = "https://www.ebi.ac.uk/ols4/api/mcp"
OLS_REST = "https://www.ebi.ac.uk/ols4/api/v2"
DEFAULT_MODEL = "text-embedding-3-large_pca512"  # precision; suits the top-K neighbourhood filter
DEFAULT_TOP_K = 20  # K=10 kept 15 pairs, K=20 25 on CYP2C19 + AARS1 + Tyk2/Ldlr + Mtor (2026-11-05); see ols-similarity-guide.md
DEFAULT_ONTOLOGIES = ["efo", "mondo", "oba", "hp", "go"]  # go: Open Targets maps drug-response studies to GO
DEFAULT_EXCLUDE_BRANCHES = ["MONDO:0005583"]  # non-human animal disease; filtered via each hit's hierarchicalAncestor
MAX_KNN_PAGE = 1000

EFO_PREFIXES = {"EFO"}
OBO_PREFIXES = {"MP", "HP", "MONDO", "OBA", "GO", "UBERON", "PATO", "CHEBI", "DOID", "NCIT", "UPHENO", "VT", "CL"}
# prefix of a trait id -> OLS ontology id that defines it (for the "not searched" warning)
PREFIX_TO_ONTOLOGY = {"EFO": "efo", "MONDO": "mondo", "OBA": "oba", "HP": "hp", "ORPHANET": "ordo", "GO": "go",
                      "DOID": "doid", "NCIT": "ncit", "UBERON": "uberon", "CHEBI": "chebi"}


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


def id_prefix(term: str) -> str:
    local = term.rsplit("/", 1)[-1]
    for sep in (":", "_"):
        if sep in local:
            return local.split(sep, 1)[0].upper()
    return ""


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


# --- OLS REST (embedding vectors and vector search; not exposed by the MCP server) ---

def _enc(iri: str) -> str:
    return urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")  # OLS wants IRIs double-encoded


def rest(url: str, body: bytes | None = None, retries: int = 3):
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def class_embedding(iri: str, model: str) -> list[float]:
    vec = rest(f"{OLS_REST}/classes/{_enc(iri)}/llm_embedding?model={urllib.parse.quote(model)}")
    if not isinstance(vec, list) or not vec:
        raise RuntimeError(f"no embedding for {iri} under {model}")
    return vec


def _first(x) -> str:
    return (x[0] if x else "") if isinstance(x, list) else (x or "")


def _ancestors(e: dict) -> set[str]:
    ha = e.get("hierarchicalAncestor")
    return set(ha) if isinstance(ha, list) else ({ha} if ha else set())


def nearest(vector: list[float], ontology: str, model: str, k: int, exclude: frozenset[str] = frozenset()) -> list[dict]:
    """K nearest non-obsolete classes defined in `ontology`, best first.

    Label/synonym embeddings only (includeCurations=false): curated text-to-term
    mappings otherwise lift classes whose own description is not close. Classes
    that are, or sit under, an IRI in `exclude` are dropped (e.g. MONDO
    non-human animal disease). The endpoint's `page` parameter returns page 0
    again, so dropped classes are compensated for by asking for a bigger single page.
    """
    body = json.dumps(vector).encode()
    size = max(3 * k, 30)
    while True:
        url = (f"{OLS_REST}/ontologies/{ontology}/classes/llm_embedding?model={urllib.parse.quote(model)}"
               f"&size={size}&isDefiningOntology=true&includeCurations=false")
        els = rest(url, body).get("elements", [])
        live = [e for e in els if not e.get("isObsolete") and e["iri"] not in exclude and not (_ancestors(e) & exclude)]
        if len(live) >= k or len(els) < size or size >= MAX_KNN_PAGE:
            break
        size = min(size * 2, MAX_KNN_PAGE)
    hits = [{"iri": e["iri"], "id": e.get("curie") or e.get("shortForm") or e["iri"], "label": _first(e.get("label")),
             "ontology": ontology, "knn_score": float(e["score"])} for e in live]
    hits.sort(key=lambda h: (-h["knn_score"], h["iri"]))  # approximate search: near-ties arrive in varying order
    return hits[:k]


def neighbourhood(p: dict, model: str, ontologies: list[str], k: int, scope: str, exclude: frozenset[str]) -> list[dict]:
    vec = class_embedding(p["iri"], model)
    per_onto = {o: nearest(vec, o, model, k, exclude) for o in ontologies}
    if scope == "per-ontology":
        out = []
        for hits in per_onto.values():
            for i, h in enumerate(hits, 1):
                out.append({**h, "knn_rank": i})
        return out
    best: dict[str, dict] = {}
    for hits in per_onto.values():
        for h in hits:
            if h["iri"] not in best or h["knn_score"] > best[h["iri"]]["knn_score"]:
                best[h["iri"]] = h
    pooled = sorted(best.values(), key=lambda h: (-h["knn_score"], h["iri"]))[:k]
    return [{**h, "knn_rank": i} for i, h in enumerate(pooled, 1)]


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
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                    help=f"Keep a trait only if it is among the MP term's K nearest classes in --ontologies (default {DEFAULT_TOP_K}); 0 scores every pair instead")
    ap.add_argument("--ontologies", nargs="+", default=DEFAULT_ONTOLOGIES,
                    help=f"OLS ontology ids searched for neighbours in top-K mode (default: {' '.join(DEFAULT_ONTOLOGIES)})")
    ap.add_argument("--top-k-scope", choices=["per-ontology", "pooled"], default="per-ontology",
                    help="per-ontology: K slots in each ontology (default); pooled: K slots shared across all --ontologies")
    ap.add_argument("--exclude-branch", nargs="*", default=DEFAULT_EXCLUDE_BRANCHES,
                    help=f"Top-K mode: drop neighbours that are, or descend from, these classes (default: {' '.join(DEFAULT_EXCLUDE_BRANCHES)} "
                         "= MONDO non-human animal disease). Pass the flag with no value to drop nothing")
    ap.add_argument("--neighbours-out", help="Top-K mode: where to write every MP term's K neighbours (default: <out>_neighbours.csv)")
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
    if args.top_k < 0:
        sys.exit("--top-k must be >= 0")
    ontologies = [o.lower() for o in args.ontologies]
    exclude = frozenset(filter(None, (to_iri(b) for b in args.exclude_branch or [])))

    phenos = read_terms(args.phenotypes, args.phenotype_id_col, args.phenotype_label_col)
    traits = read_terms(args.traits, args.trait_id_col, args.trait_label_col)
    skipped = [x["id"] for x in phenos + traits if not x["iri"]]
    if skipped:
        print(f"skipped unparseable ids: {skipped}", file=sys.stderr)

    def score(job):
        p, t, model = job
        try:
            val = float(client.call("getClassSimilarity", {"classIri1": p["iri"], "classIri2": t["iri"], "model": model}))
            return val, ""
        except Exception as e:  # term missing from OLS embeddings, transport error, etc.
            return None, str(e)[:200]

    rows: list[dict] = []
    neighbour_rows: list[dict] = []
    if args.top_k == 0:
        pairs = [(p, t, m) for m in args.model for p in phenos for t in traits if p["iri"] and t["iri"]]
        print(f"all-pairs mode: {len(phenos)} phenotypes x {len(traits)} traits x {len(args.model)} model(s) = {len(pairs)} calls; models={args.model}", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(score, pairs))
        for (p, t, model), (val, err) in zip(pairs, results):
            rows.append({"phenotype_id": p["id"], "phenotype_label": p["label"], "trait_id": t["id"], "trait_label": t["label"],
                         "model": model, "similarity": val, "error": err})
    else:
        not_searched: dict[str, int] = {}
        for t in traits:
            onto = PREFIX_TO_ONTOLOGY.get(id_prefix(t["id"]), id_prefix(t["id"]).lower() or "?")
            if onto not in ontologies:
                not_searched[onto] = not_searched.get(onto, 0) + 1
        if not_searched:
            print(f"WARNING: trait ids from ontologies not in --ontologies cannot pass the top-K filter: {not_searched}", file=sys.stderr)
        jobs = [(p, m) for m in args.model for p in phenos if p["iri"]]
        print(f"top-{args.top_k} mode ({args.top_k_scope}) over {ontologies}, excluding branches {sorted(exclude) or 'none'}: {len(jobs)} MP term x model neighbourhoods "
              f"({len(jobs) * (1 + len(ontologies))} OLS calls); {len(traits)} GWAS traits to join; models={args.model}", file=sys.stderr)

        def fetch(job):
            p, model = job
            try:
                return neighbourhood(p, model, ontologies, args.top_k, args.top_k_scope, exclude), ""
            except Exception as e:
                return [], str(e)[:200]

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            hoods = list(ex.map(fetch, jobs))

        trait_by_iri = {t["iri"]: t for t in traits if t["iri"]}
        matched = []
        for (p, model), (hood, err) in zip(jobs, hoods):
            if err:
                neighbour_rows.append({"phenotype_id": p["id"], "phenotype_label": p["label"], "model": model, "error": err})
                rows.append({"phenotype_id": p["id"], "phenotype_label": p["label"], "model": model, "similarity": None, "error": f"neighbourhood: {err}"})
                continue
            for h in hood:
                t = trait_by_iri.get(h["iri"])
                neighbour_rows.append({"phenotype_id": p["id"], "phenotype_label": p["label"], "model": model,
                                       "knn_rank": h["knn_rank"], "neighbour_id": h["id"], "neighbour_label": h["label"],
                                       "neighbour_ontology": h["ontology"], "knn_score": round(h["knn_score"], 6),
                                       "is_gwas_trait": bool(t), "error": ""})
                if t:
                    matched.append((p, t, model, h))
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(score, [(p, t, m) for p, t, m, _ in matched]))
        for (p, t, model, h), (val, err) in zip(matched, results):
            rows.append({"phenotype_id": p["id"], "phenotype_label": p["label"], "trait_id": t["id"], "trait_label": t["label"],
                         "model": model, "similarity": val, "knn_rank": h["knn_rank"], "knn_score": round(h["knn_score"], 6),
                         "knn_ontology": h["ontology"], "error": err})
        n_hit_traits = len({r["trait_id"] for r in rows if r.get("trait_id")})
        n_hit_phenos = len({r["phenotype_id"] for r in rows if r.get("trait_id")})
        print(f"{len(matched)} MP x trait pairs passed top-{args.top_k}: {n_hit_phenos}/{len(phenos)} MP terms, "
              f"{n_hit_traits}/{len(traits)} GWAS traits", file=sys.stderr)

    scored = [r for r in rows if r["similarity"] is not None]
    # rank within each phenotype and within each trait, separately per model (among the rows written)
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
    rows.sort(key=lambda r: (r["model"], -(r["similarity"] or -1), r["phenotype_id"], r.get("trait_id", "")))

    fields = ["phenotype_id", "phenotype_label", "trait_id", "trait_label", "similarity", "rank_within_phenotype", "rank_within_trait", "model"]
    if args.top_k:
        fields += ["knn_rank", "knn_score", "knn_ontology"]
    fields += ["error"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    n_err = sum(1 for r in rows if r["similarity"] is None)
    print(f"wrote {len(rows)} rows to {args.out} ({n_err} failed)", file=sys.stderr)

    if args.top_k:
        out = Path(args.out)
        npath = args.neighbours_out or str(out.with_name(f"{out.stem}_neighbours{out.suffix or '.csv'}"))
        nfields = ["phenotype_id", "phenotype_label", "model", "knn_rank", "neighbour_id", "neighbour_label",
                   "neighbour_ontology", "knn_score", "is_gwas_trait", "error"]
        with open(npath, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=nfields)
            w.writeheader()
            for r in neighbour_rows:
                w.writerow({k: r.get(k, "") for k in nfields})
        print(f"wrote {len(neighbour_rows)} neighbour rows to {npath}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
