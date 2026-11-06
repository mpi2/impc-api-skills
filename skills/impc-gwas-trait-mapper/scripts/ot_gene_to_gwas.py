#!/usr/bin/env python3
"""Open Targets Platform: human gene -> L2G evidence -> GWAS credible set -> study -> mapped traits.

Path (tested 2026-09-22 against API v4):
  0. mapIds(queryTerms:[HGNC ids])  -> Ensembl gene ids (exact id lookup; no symbol search, so no fuzzy hits)
  1. target.associatedDiseases(datasources:[{id:"gwas_credible_sets", required:true}])  -> diseases with GWAS L2G evidence
  2. target.evidences(efoIds, datasourceIds:["gwas_credible_sets"], size:1000, cursor)  -> one row per credible set x disease;
     evidence.score is the gene's L2G score; credibleSet.study carries the GWAS study and its mapped trait ids.

Reverse entry point (--study-ids): credibleSets(studyIds) -> l2GPredictions -> candidate genes.
--disease-ids first finds the GWAS studies mapped to those EFO/MONDO ids (descendants included) with studies(diseaseIds).

Examples:
  uv run skills/impc-gwas-trait-mapper/scripts/ot_gene_to_gwas.py --orthologs 02_orthologs.csv \
      --out-evidence 03_ot_l2g_evidence.csv --out-links 03_l2g_gwas_links.csv --out-traits 04_gwas_traits.csv
  uv run skills/impc-gwas-trait-mapper/scripts/ot_gene_to_gwas.py --ensembl ENSG00000198793 --out-links links.csv
  uv run skills/impc-gwas-trait-mapper/scripts/ot_gene_to_gwas.py --study-ids GCST90480502 GCST90014463 --out-links study_l2g_genes.csv
  uv run skills/impc-gwas-trait-mapper/scripts/ot_gene_to_gwas.py --disease-ids MONDO_0005306 --out-links as_l2g_genes.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request

API = "https://api.platform.opentargets.org/api/v4/graphql"

Q_MAP_IDS = """query($t:[String!]!){ mapIds(queryTerms:$t, entityNames:["target"]){ mappings{ term hits{ id name entity } } } }"""

Q_DISEASES = """query($id:String!){ target(ensemblId:$id){ id approvedSymbol
  associatedDiseases(datasources:[{id:"gwas_credible_sets",weight:1,propagate:false,required:true}], page:{index:0,size:3000}){
    count rows{ disease{ id name } } } } }"""

Q_EVIDENCE = """query($id:String!,$efo:[String!]!,$size:Int!,$cursor:String){ target(ensemblId:$id){ approvedSymbol
  evidences(efoIds:$efo, datasourceIds:["gwas_credible_sets"], size:$size, cursor:$cursor){ count cursor rows{
    score disease{ id name }
    credibleSet{ studyLocusId studyType chromosome position pValueMantissa pValueExponent confidence finemappingMethod
      beta standardError effectAlleleFrequencyFromSource
      variant{ id rsIds referenceAllele alternateAllele mostSevereConsequence{ label } }
      l2GPredictions(page:{index:0,size:%d}){ count rows{ score target{ id approvedSymbol } } }
      study{ id studyType projectId traitFromSource traitFromSourceMappedIds diseases{ id name } backgroundTraits{ id name }
             pubmedId publicationFirstAuthor publicationDate nSamples nCases hasSumstats } } } } } }"""

Q_STUDY_CS = """query($ids:[String!]!,$i:Int!){ credibleSets(studyIds:$ids, studyTypes:[gwas], page:{index:$i,size:200}){ count rows{
    studyLocusId studyId pValueMantissa pValueExponent finemappingMethod confidence beta standardError effectAlleleFrequencyFromSource
    variant{ id rsIds referenceAllele alternateAllele mostSevereConsequence{ label } }
    l2GPredictions(page:{index:0,size:%d}){ count rows{ score target{ id approvedSymbol } } }
    study{ id projectId traitFromSource diseases{ id name } pubmedId publicationFirstAuthor publicationDate nSamples nCases } } } }"""

Q_DISEASE_STUDIES = """query($ids:[String!]!,$i:Int!){ studies(diseaseIds:$ids, enableIndirect:true, page:{index:$i,size:200}){ count rows{
    id studyType projectId traitFromSource } } }"""

EVIDENCE_FIELDS = ["human_symbol", "hgnc_id", "ensembl_id", "l2g_score", "l2g_rank_in_locus", "n_l2g_genes_in_locus", "top_l2g_gene_in_locus",
                   "top_l2g_score_in_locus", "study_locus_id", "lead_variant", "rsids", "chromosome", "position", "p_value",
                   "finemapping_method", "confidence", "ref_allele", "alt_allele", "alt_allele_freq", "beta_alt", "beta_se",
                   "trait_direction_alt", "variant_consequence", "gwas_study_id", "gwas_source", "trait_from_source", "study_trait_ids",
                   "study_trait_labels", "background_trait_ids", "pubmed_id", "first_author", "publication_date", "n_samples",
                   "n_cases", "has_sumstats", "ot_disease_id", "ot_disease_name"]
TRAIT_FIELDS = ["gwas_study_id", "gwas_source", "trait_id", "trait_label", "trait_from_source", "trait_source"]


def gql(query: str, variables: dict, retries: int = 3) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(API, body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.load(r)
            if out.get("errors"):
                raise RuntimeError(json.dumps(out["errors"])[:500])
            return out["data"]
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries - 1:
                raise
            print(f"retrying after {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def resolve_hgnc(hgnc_ids: list[str]) -> dict[str, tuple[str, str]]:
    """HGNC id -> (Ensembl id, approved symbol) via mapIds, an exact identifier lookup.

    The orthology server gives HGNC ids, not Ensembl ids, and Open Targets is keyed on Ensembl.
    mapIds resolves ids without free-text search, so a symbol that is a prefix or alias of another
    gene cannot pull in the wrong target. Anything other than exactly one hit is reported and dropped.
    """
    out: dict[str, tuple[str, str]] = {}
    for i in range(0, len(hgnc_ids), 200):
        chunk = hgnc_ids[i:i + 200]
        for m in gql(Q_MAP_IDS, {"t": chunk})["mapIds"]["mappings"]:
            hits = [h for h in m["hits"] if h.get("entity") == "target"]
            if len(hits) == 1:
                out[m["term"]] = (hits[0]["id"], hits[0]["name"])
            else:
                print(f"{m['term']}: {len(hits)} Open Targets targets for this HGNC id; skipped", file=sys.stderr)
    return out


def pval(cs: dict) -> str:
    m, e = cs.get("pValueMantissa"), cs.get("pValueExponent")
    return f"{m}e{e}" if m is not None and e is not None else ""


def effect_cols(cs: dict) -> dict:
    """Signed trait effect of the alternate allele, as Open Targets stores it on the credible set.

    beta is per copy of variant.alternateAllele; log(OR) for binary traits. Direction is derived
    from the sign only; magnitude units differ between studies (often inverse-normalised).
    """
    v = cs.get("variant") or {}
    beta = cs.get("beta")
    direction = "" if beta is None else ("increase" if beta > 0 else "decrease" if beta < 0 else "null")
    return {"ref_allele": v.get("referenceAllele", ""), "alt_allele": v.get("alternateAllele", ""),
            "alt_allele_freq": cs.get("effectAlleleFrequencyFromSource", ""),
            "beta_alt": "" if beta is None else beta, "beta_se": cs.get("standardError", ""),
            "trait_direction_alt": direction,
            "variant_consequence": (v.get("mostSevereConsequence") or {}).get("label", "")}


def l2g_context(preds: list[dict], ensembl: str | None) -> dict:
    preds = sorted(preds, key=lambda p: -p["score"])
    ids = [p["target"]["id"] for p in preds]
    return {"l2g_rank_in_locus": ids.index(ensembl) + 1 if ensembl in ids else "",
            "top_l2g_gene_in_locus": preds[0]["target"]["approvedSymbol"] if preds else "",
            "top_l2g_score_in_locus": preds[0]["score"] if preds else ""}


def gene_to_evidence(symbol: str, ensembl: str, l2g_size: int, hgnc_id: str = "") -> list[dict]:
    d = gql(Q_DISEASES, {"id": ensembl})["target"]
    if d is None:
        print(f"{symbol}: {ensembl} not in Open Targets", file=sys.stderr)
        return []
    efo = [r["disease"]["id"] for r in d["associatedDiseases"]["rows"]]
    print(f"{symbol} ({ensembl}): {len(efo)} diseases with gwas_credible_sets evidence", file=sys.stderr)
    if not efo:
        return []
    rows, cursor, size = [], None, 1000
    while True:
        try:
            e = gql(Q_EVIDENCE % l2g_size, {"id": ensembl, "efo": efo, "size": size, "cursor": cursor})["target"]["evidences"]
        except RuntimeError as err:
            if "too expensive" in str(err) and size > 100:
                size //= 2  # query-cost limiter: shrink the page and retry
                continue
            raise
        for r in e["rows"]:
            cs, st = r["credibleSet"], r["credibleSet"]["study"] or {}
            preds = cs["l2GPredictions"]["rows"]
            rows.append({
                "human_symbol": symbol, "hgnc_id": hgnc_id, "ensembl_id": ensembl, "l2g_score": r["score"],
                "n_l2g_genes_in_locus": cs["l2GPredictions"]["count"], **l2g_context(preds, ensembl),
                "study_locus_id": cs["studyLocusId"],
                "lead_variant": (cs.get("variant") or {}).get("id", ""), "rsids": ";".join((cs.get("variant") or {}).get("rsIds") or []),
                "chromosome": cs.get("chromosome", ""), "position": cs.get("position", ""), "p_value": pval(cs),
                "finemapping_method": cs.get("finemappingMethod", ""), "confidence": cs.get("confidence", ""),
                **effect_cols(cs),
                "gwas_study_id": st.get("id", ""), "gwas_source": st.get("projectId", ""),
                "trait_from_source": st.get("traitFromSource", ""),
                "study_trait_ids": ";".join(x["id"] for x in st.get("diseases") or []),
                "study_trait_labels": ";".join(x["name"] for x in st.get("diseases") or []),
                "background_trait_ids": ";".join(x["id"] for x in st.get("backgroundTraits") or []),
                "pubmed_id": st.get("pubmedId", ""), "first_author": st.get("publicationFirstAuthor", ""),
                "publication_date": st.get("publicationDate", ""), "n_samples": st.get("nSamples", ""), "n_cases": st.get("nCases", ""),
                "has_sumstats": st.get("hasSumstats", ""),
                "ot_disease_id": r["disease"]["id"], "ot_disease_name": r["disease"]["name"],
                "_study": st,
            })
        cursor = e.get("cursor")
        if not cursor or not e["rows"]:
            break
    print(f"{symbol}: {len(rows)} evidence rows (count={e['count']})", file=sys.stderr)
    return rows


def diseases_to_studies(disease_ids: list[str]) -> list[str]:
    """GWAS study ids mapped to these EFO/MONDO ids or their descendants (Open Targets study index)."""
    ids, i = [], 0
    while True:
        page = gql(Q_DISEASE_STUDIES, {"ids": disease_ids, "i": i})["studies"]
        ids.extend(r["id"] for r in page["rows"] if r.get("studyType") == "gwas")
        i += 1
        if not page["rows"] or i * 200 >= page["count"]:
            break
    print(f"{len(disease_ids)} disease ids (with descendants): {page['count']} studies, {len(ids)} GWAS", file=sys.stderr)
    return ids


def studies_to_genes(study_ids: list[str], l2g_size: int) -> list[dict]:
    rows, i = [], 0
    while True:
        cs_page = gql(Q_STUDY_CS % l2g_size, {"ids": study_ids, "i": i})["credibleSets"]
        for cs in cs_page["rows"]:
            st = cs["study"] or {}
            for rank, p in enumerate(sorted(cs["l2GPredictions"]["rows"], key=lambda p: -p["score"]), 1):
                rows.append({
                    "human_symbol": p["target"]["approvedSymbol"], "ensembl_id": p["target"]["id"], "l2g_score": p["score"],
                    "l2g_rank_in_locus": rank, "n_l2g_genes_in_locus": cs["l2GPredictions"]["count"],
                    "top_l2g_gene_in_locus": cs["l2GPredictions"]["rows"][0]["target"]["approvedSymbol"] if rank else "",
                    "top_l2g_score_in_locus": cs["l2GPredictions"]["rows"][0]["score"] if rank else "",
                    "study_locus_id": cs["studyLocusId"],
                    "lead_variant": (cs.get("variant") or {}).get("id", ""), "rsids": ";".join((cs.get("variant") or {}).get("rsIds") or []),
                    "p_value": pval(cs), "finemapping_method": cs.get("finemappingMethod", ""), "confidence": cs.get("confidence", ""),
                    **effect_cols(cs),
                    "gwas_study_id": cs.get("studyId", ""), "gwas_source": st.get("projectId", ""),
                    "trait_from_source": st.get("traitFromSource", ""),
                    "study_trait_ids": ";".join(x["id"] for x in st.get("diseases") or []),
                    "study_trait_labels": ";".join(x["name"] for x in st.get("diseases") or []),
                    "pubmed_id": st.get("pubmedId", ""), "first_author": st.get("publicationFirstAuthor", ""),
                    "publication_date": st.get("publicationDate", ""), "n_samples": st.get("nSamples", ""), "n_cases": st.get("nCases", ""),
                    "_study": st,
                })
        i += 1
        if not cs_page["rows"] or i * 200 >= cs_page["count"]:
            break
    print(f"{len(study_ids)} studies: {cs_page['count']} GWAS credible sets, {len(rows)} L2G gene rows", file=sys.stderr)
    return rows


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    if not rows:
        print(f"no rows; not writing {path}", file=sys.stderr)
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"wrote {len(rows)} rows -> {path}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--orthologs", help="CSV from orthologs.py: HGNC ids in --hgnc-col are mapped to Ensembl ids with mapIds")
    g.add_argument("--hgnc", nargs="+", help="HGNC ids (HGNC:12440 ...), mapped to Ensembl ids with mapIds")
    g.add_argument("--ensembl", nargs="+", help="Ensembl gene ids, used as given")
    g.add_argument("--study-ids", nargs="+", help="Reverse direction: GWAS study ids -> credible sets -> L2G genes")
    g.add_argument("--disease-ids", nargs="+", help="Reverse direction: EFO/MONDO ids (descendants included) -> GWAS studies -> as --study-ids")
    ap.add_argument("--hgnc-col", default="hgncAccId")
    ap.add_argument("--l2g-size", type=int, default=5, help="L2G candidates fetched per credible set (rows sorted by score desc)")
    ap.add_argument("--out-evidence", help="All evidence rows (one per credible set x disease)")
    ap.add_argument("--out-links", required=True, help="One row per gene x credible set (deduplicated on study_locus_id)")
    ap.add_argument("--out-traits", help="One row per study x mapped trait id, ready for ols_similarity.py")
    args = ap.parse_args()

    if args.disease_ids:
        args.study_ids = diseases_to_studies(args.disease_ids)
        if not args.study_ids:
            print("no GWAS studies for these disease ids; check them with search_entities", file=sys.stderr)
            return 1
    if args.study_ids:
        rows = studies_to_genes(args.study_ids, args.l2g_size)
        links = rows
    else:
        if args.ensembl:
            genes = [(e, "", e) for e in args.ensembl]  # (symbol, hgnc_id, ensembl)
        else:
            if args.orthologs:
                with open(args.orthologs, newline="", encoding="utf-8") as f:
                    hgnc_ids = sorted({(r.get(args.hgnc_col) or "").strip() for r in csv.DictReader(f)} - {""})
            else:
                hgnc_ids = args.hgnc
            resolved = resolve_hgnc(hgnc_ids)
            print(f"{len(resolved)}/{len(hgnc_ids)} HGNC ids resolved to Ensembl ids", file=sys.stderr)
            genes = [(sym, h, ens) for h, (ens, sym) in resolved.items()]
        rows = []
        for sym, hgnc, ens in genes:
            rows.extend(gene_to_evidence(sym, ens, args.l2g_size, hgnc))
        # the same credible set appears once per mapped disease: keep one row per gene x locus
        seen, links = set(), []
        for r in sorted(rows, key=lambda r: -r["l2g_score"]):
            key = (r["ensembl_id"], r["study_locus_id"])
            if key not in seen:
                seen.add(key)
                links.append(r)
        print(f"{len(rows)} evidence rows -> {len(links)} unique gene x credible set", file=sys.stderr)

    if args.out_evidence and not args.study_ids:
        write_csv(args.out_evidence, rows, EVIDENCE_FIELDS)
    write_csv(args.out_links, links, EVIDENCE_FIELDS)

    if args.out_traits:
        seen, traits = set(), []
        for r in links:
            st = r["_study"]
            for d in st.get("diseases") or []:
                key = (st.get("id"), d["id"])
                if key not in seen:
                    seen.add(key)
                    traits.append({"gwas_study_id": st.get("id", ""), "gwas_source": st.get("projectId", ""), "trait_id": d["id"],
                                   "trait_label": d["name"], "trait_from_source": st.get("traitFromSource", ""), "trait_source": "open_targets_study.diseases"})
            if not st.get("diseases"):
                traits.append({"gwas_study_id": st.get("id", ""), "gwas_source": st.get("projectId", ""), "trait_id": "", "trait_label": "",
                               "trait_from_source": st.get("traitFromSource", ""), "trait_source": "unmapped: resolve label via OLS"})
        write_csv(args.out_traits, traits, TRAIT_FIELDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
