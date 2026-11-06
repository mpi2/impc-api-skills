#!/usr/bin/env python3
"""UniProt statements and diseases for IMPC genes and their human orthologs, as written in UniProt.

EXPERIMENTAL (step 2c): output columns may change; not covered by evals yet. See references/uniprot-guide.md.

Inputs: --accessions (02_uniprot_accessions.csv, mouse; is_primary rows used) and --orthologs
(02_orthologs.csv). Human reviewed accessions come from UniProt REST
(xref:hgnc-<n> AND reviewed:true AND organism_id:9606).

--statements-out: one row per gene x species x statement (FUNCTION, DISEASE, DISRUPTION PHENOTYPE), with
  the ECO evidence codes and where the statement comes from: `experimental`, `by_similarity` (with the
  accession it was copied from), `automatic` or `curated_other`. The class is read from the ECO ontology
  in OLS (ancestors ECO:0000006 experimental, ECO:0000501 automatic, ECO:0000041 similarity), not from a
  hand-made code table.
--diseases-out: one row per human gene x UniProt DISEASE comment: name, acronym, MIM id, description and
  evidence origin, as UniProt has them. No mapping to other disease ontologies.

Example:
  uv run skills/impc-gwas-trait-mapper/scripts/uniprot_evidence.py --accessions 02_uniprot_accessions.csv \
    --orthologs 02_orthologs.csv --statements-out 02_uniprot_statements.csv --diseases-out 02_uniprot_diseases.csv
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

UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"
OLS_TERM = "https://www.ebi.ac.uk/ols4/api/ontologies/eco/terms/{}/hierarchicalAncestors?size=200"
UNIPROT_FIELDS = "accession,gene_primary,organism_id,xref_hgnc,cc_function,cc_disease,cc_disruption_phenotype"
SECTIONS = ("FUNCTION", "DISEASE", "DISRUPTION PHENOTYPE")
# ECO classes read from the ontology: first ancestor found wins, in this order.
ECO_CLASSES = [("ECO:0000006", "experimental"), ("ECO:0000501", "automatic"), ("ECO:0000041", "by_similarity")]

STATEMENT_FIELDS = ["mgi_id", "mouse_symbol", "human_symbol", "species", "uniprot_accession", "section",
                    "disease_mim", "text", "origin", "transferred_from", "eco_codes", "pmids"]
DISEASE_FIELDS = ["mgi_id", "mouse_symbol", "human_symbol", "uniprot_accession", "disease_name", "disease_acronym",
                  "disease_mim", "description", "origin", "pmids"]


def get_json(url: str, retries: int = 4, timeout: int = 90):
    # UniProt and OLS time out or answer 5xx now and then; back off and retry.
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                return None
            retry = not isinstance(e, urllib.error.HTTPError) or e.code in (429, 500, 502, 503, 504)
            if retry and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise


def search(query: str, size: int = 500) -> list[dict]:
    qs = urllib.parse.urlencode({"query": query, "fields": UNIPROT_FIELDS, "format": "json", "size": size})
    return (get_json(f"{UNIPROT_SEARCH}?{qs}") or {}).get("results", [])


def mouse_entries(accessions: list[str], chunk: int = 100) -> dict[str, dict]:
    out = {}
    for i in range(0, len(accessions), chunk):
        part = accessions[i:i + chunk]
        for r in search(" OR ".join(f"accession:{a}" for a in part), size=len(part)):
            out[r["primaryAccession"]] = r
        time.sleep(0.3)
    return out


def human_entries(hgnc_ids: list[str], chunk: int = 20) -> dict[str, list[dict]]:
    """HGNC id -> reviewed human entries cross-referenced to it."""
    out: dict[str, list[dict]] = {h: [] for h in hgnc_ids}
    for i in range(0, len(hgnc_ids), chunk):
        part = set(hgnc_ids[i:i + chunk])
        terms = " OR ".join(f"xref:hgnc-{h.split(':')[-1]}" for h in sorted(part))
        for r in search(f"({terms}) AND reviewed:true AND organism_id:9606"):
            for h in part & {x["id"] for x in r.get("uniProtKBCrossReferences", []) if x.get("database") == "HGNC"}:
                out[h].append(r)
        time.sleep(0.3)
    return out


class EcoClassifier:
    def __init__(self):
        self.cache: dict[str, str] = {}

    def __call__(self, code: str) -> str:
        if code not in self.cache:
            iri = f"http://purl.obolibrary.org/obo/{code.replace(':', '_')}"
            enc = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
            terms = (get_json(OLS_TERM.format(enc)) or {}).get("_embedded", {}).get("terms", [])
            ancestors = {t.get("obo_id") for t in terms}
            self.cache[code] = next((label for anc, label in ECO_CLASSES if anc in ancestors), "curated_other")
        return self.cache[code]


def summarise_evidence(evidences: list[dict], eco: EcoClassifier) -> dict:
    codes = sorted({e["evidenceCode"] for e in evidences if e.get("evidenceCode")})
    classes = [eco(c) for c in codes]
    # All classes are listed so a statement backed by both experiment and copying shows both.
    origin = "; ".join(c for c in ("experimental", "by_similarity", "curated_other", "automatic") if c in classes)
    return {"origin": origin, "eco_codes": "; ".join(codes),
            "transferred_from": "; ".join(sorted({e["id"] for e in evidences if e.get("source") == "UniProtKB"})),
            "pmids": "; ".join(sorted({e["id"] for e in evidences if e.get("source") == "PubMed"}))}


def statements(entry: dict, base: dict, species: str, eco: EcoClassifier) -> list[dict]:
    rows = []
    for c in entry.get("comments", []):
        kind = c.get("commentType")
        if kind not in SECTIONS:
            continue
        if kind == "DISEASE":
            d = c.get("disease", {})
            xref = d.get("diseaseCrossReference", {})
            rows.append({**base, "species": species, "uniprot_accession": entry["primaryAccession"], "section": kind,
                         "disease_mim": xref.get("id", "") if xref.get("database") == "MIM" else "",
                         "text": f"{d.get('diseaseId', '')} ({d.get('acronym', '')}): {d.get('description', '')}",
                         **summarise_evidence(d.get("evidences", []), eco)})
        else:
            for t in c.get("texts", []):
                rows.append({**base, "species": species, "uniprot_accession": entry["primaryAccession"],
                             "section": kind, "disease_mim": "", "text": t.get("value", ""),
                             **summarise_evidence(t.get("evidences", []), eco)})
    return rows


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: str, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--accessions", required=True, help="02_uniprot_accessions.csv (mouse, from uniprot_mapping.py)")
    ap.add_argument("--orthologs", required=True, help="02_orthologs.csv")
    ap.add_argument("--statements-out", required=True)
    ap.add_argument("--diseases-out", required=True)
    args = ap.parse_args()

    mouse_acc = {r["mgi_id"]: r for r in read_csv(args.accessions) if r["is_primary"] == "True"}
    orth = {r["mgiGeneAccId"]: r for r in read_csv(args.orthologs)}
    genes = sorted(set(mouse_acc) | set(orth))
    mouse = mouse_entries(sorted({r["uniprot_accession"] for r in mouse_acc.values()}))
    human = human_entries(sorted({o["hgncAccId"] for o in orth.values() if o.get("hgncAccId")}))
    eco = EcoClassifier()

    st_rows, dis_rows = [], []
    for mgi in genes:
        o = orth.get(mgi, {})
        base = {"mgi_id": mgi, "mouse_symbol": o.get("mouseGeneSymbol") or mouse_acc.get(mgi, {}).get("uniprot_gene", ""),
                "human_symbol": o.get("humanGeneSymbol", "")}
        if mgi in mouse_acc and mouse_acc[mgi]["uniprot_accession"] in mouse:
            st_rows += statements(mouse[mouse_acc[mgi]["uniprot_accession"]], base, "mouse", eco)
        for entry in human.get(o.get("hgncAccId", ""), []):
            st_rows += statements(entry, base, "human", eco)
            for c in entry.get("comments", []):
                if c.get("commentType") == "DISEASE":
                    d = c.get("disease", {})
                    xref = d.get("diseaseCrossReference", {})
                    ev = summarise_evidence(d.get("evidences", []), eco)
                    dis_rows.append({**base, "uniprot_accession": entry["primaryAccession"],
                                     "disease_name": d.get("diseaseId", ""), "disease_acronym": d.get("acronym", ""),
                                     "disease_mim": xref.get("id", "") if xref.get("database") == "MIM" else "",
                                     "description": d.get("description", ""), "origin": ev["origin"], "pmids": ev["pmids"]})

    write_csv(args.statements_out, STATEMENT_FIELDS, st_rows)
    write_csv(args.diseases_out, DISEASE_FIELDS, dis_rows)
    no_human = [orth[m]["hgncAccId"] for m in genes if m in orth and not human.get(orth[m].get("hgncAccId", ""))]
    print(f"{len(genes)} genes: {len(st_rows)} UniProt statements -> {args.statements_out}; "
          f"{len(dis_rows)} human disease rows -> {args.diseases_out}", file=sys.stderr)
    if no_human:
        print("no reviewed human entry for: " + ", ".join(no_human), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
