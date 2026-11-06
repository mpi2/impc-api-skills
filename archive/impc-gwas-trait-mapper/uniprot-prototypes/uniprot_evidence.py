#!/usr/bin/env python3
"""UniProt protein-level evidence for IMPC genes and their human orthologs (ideas 2-4, prototype).

EXPERIMENTAL (step 2c): output columns may change; not covered by evals yet. See references/uniprot-guide.md.

Inputs: --accessions (02_uniprot_accessions.csv, mouse; is_primary rows used), --orthologs (02_orthologs.csv),
--links (03_l2g_gwas_links.csv, for Ensembl ids and GWAS lead variants).

--statements-out: one row per gene x species x statement (FUNCTION, DISEASE, DISRUPTION PHENOTYPE), with
  the ECO evidence codes and where the statement comes from: `experimental`, `by_similarity` (with the
  accession it was copied from), `automatic` or `curated_other`. The class is read from the ECO ontology
  in OLS (ancestors ECO:0000006 experimental, ECO:0000041 similarity, ECO:0000501 automatic), not from a
  hand-made code table.
--diseases-out: one row per human gene x UniProt DISEASE comment, with the MIM id and the MONDO/EFO id
  Open Targets assigns to that MIM id in its UniProt evidence (target.associatedDiseases restricted to
  uniprot_literature / uniprot_variants, matched on the disease's OMIM dbXRef). Columns trait_id and
  trait_label feed straight into ols_similarity.py.
--variants-out: one row per gene x GWAS lead variant (from --links): its consequence, credible sets,
  traits and beta signs, and, when UniProt lists it as a natural variant (matched on dbSNP id), the
  residue change, UniProt's note, the domain it falls in and the mutagenesis results in that domain.

Example:
  uv run skills/impc-gwas-trait-mapper/scripts/uniprot_evidence.py --accessions 02_uniprot_accessions.csv \
    --orthologs 02_orthologs.csv --links 03_l2g_gwas_links.csv --statements-out 02_uniprot_statements.csv \
    --diseases-out 02_uniprot_diseases.csv --variants-out 02_uniprot_gwas_variants.csv
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
from collections import defaultdict

UNIPROT_ACCESSIONS = "https://rest.uniprot.org/uniprotkb/accessions"
OT_API = "https://api.platform.opentargets.org/api/v4/graphql"
OLS_TERM = "https://www.ebi.ac.uk/ols4/api/ontologies/eco/terms/{}/hierarchicalAncestors?size=200"
UNIPROT_FIELDS = ("accession,gene_primary,organism_id,cc_function,cc_disease,cc_disruption_phenotype,"
                  "ft_variant,ft_mutagen,ft_domain")
SECTIONS = ("FUNCTION", "DISEASE", "DISRUPTION PHENOTYPE")
OT_SOURCES = ("uniprot_literature", "uniprot_variants")
# ECO classes read from the ontology: first ancestor found wins, in this order.
ECO_CLASSES = [("ECO:0000006", "experimental"), ("ECO:0000501", "automatic"), ("ECO:0000041", "by_similarity")]

STATEMENT_FIELDS = ["mgi_id", "mouse_symbol", "human_symbol", "species", "uniprot_accession", "section",
                    "disease_mim", "text", "origin", "transferred_from", "eco_codes", "pmids"]
DISEASE_FIELDS = ["mgi_id", "mouse_symbol", "human_symbol", "uniprot_accession", "disease_name", "disease_acronym",
                  "disease_mim", "trait_id", "trait_label", "ot_uniprot_scores", "origin", "pmids", "description"]
VARIANT_FIELDS = ["mgi_id", "mouse_symbol", "human_symbol", "lead_variant", "rsids", "variant_consequence",
                  "n_credible_sets", "best_l2g_score", "traits", "beta_signs", "ot_amino_acid_change",
                  "uniprot_accession", "uniprot_variant_id",
                  "residue_change", "uniprot_note", "uniprot_variant_origin", "domain", "domain_mutagenesis"]

Q_TARGET = """query($e:String!, $ds:[DatasourceSettingsInput!]){ target(ensemblId:$e){ approvedSymbol
  proteinIds{ id source }
  associatedDiseases(page:{index:0,size:200}, datasources:$ds){ rows{ disease{ id name dbXRefs } datasourceScores{ id score } } } } }"""


def request_json(url: str, data: bytes | None = None, retries: int = 4, timeout: int = 90):
    # UniProt and OT time out or answer 5xx now and then; back off and retry.
    for attempt in range(retries):
        try:
            headers = {"Accept": "application/json"}
            if data is not None:
                headers["Content-Type"] = "application/json"
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                return None
            retry = not isinstance(e, urllib.error.HTTPError) or e.code in (429, 500, 502, 503, 504)
            if retry and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise


def uniprot_entries(accessions: list[str], chunk: int = 25) -> dict[str, dict]:
    out = {}
    for i in range(0, len(accessions), chunk):
        qs = urllib.parse.urlencode({"accessions": ",".join(accessions[i:i + chunk]), "fields": UNIPROT_FIELDS,
                                     "format": "json"})
        for r in (request_json(f"{UNIPROT_ACCESSIONS}?{qs}") or {}).get("results", []):
            out[r["primaryAccession"]] = r
        time.sleep(0.3)
    return out


def ot_target(ensembl_id: str) -> dict:
    """Swiss-Prot accessions and the diseases OT supports with UniProt evidence."""
    proteins, diseases = [], {}
    for source in OT_SOURCES:
        ds = [{"id": source, "weight": 1, "propagate": False, "required": True}]
        body = json.dumps({"query": Q_TARGET, "variables": {"e": ensembl_id, "ds": ds}}).encode()
        t = ((request_json(OT_API, data=body) or {}).get("data") or {}).get("target") or {}
        proteins = proteins or [p["id"] for p in t.get("proteinIds", []) if p["source"] == "uniprot_swissprot"]
        for row in t.get("associatedDiseases", {}).get("rows", []):
            d = diseases.setdefault(row["disease"]["id"], {**row["disease"], "scores": {}})
            d["scores"].update({s["id"]: s["score"] for s in row["datasourceScores"] if s["id"] in OT_SOURCES})
    return {"proteins": proteins, "diseases": list(diseases.values())}


def ot_amino_acid_change(variant_id: str, symbol: str) -> str:
    """Amino-acid change (e.g. P1104A) of this exact allele on the gene's canonical transcript, per Open Targets."""
    q = """query($v:String!){ variant(variantId:$v){ transcriptConsequences{ aminoAcidChange isEnsemblCanonical
           target{ approvedSymbol } } } }"""
    body = json.dumps({"query": q, "variables": {"v": variant_id}}).encode()
    v = ((request_json(OT_API, data=body) or {}).get("data") or {}).get("variant") or {}
    return next((t.get("aminoAcidChange") or "" for t in v.get("transcriptConsequences", [])
                 if t.get("isEnsemblCanonical") and (t.get("target") or {}).get("approvedSymbol") == symbol), "")


class EcoClassifier:
    def __init__(self):
        self.cache: dict[str, str] = {}

    def __call__(self, code: str) -> str:
        if code not in self.cache:
            iri = f"http://purl.obolibrary.org/obo/{code.replace(':', '_')}"
            enc = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
            terms = (request_json(OLS_TERM.format(enc)) or {}).get("_embedded", {}).get("terms", [])
            ancestors = {t.get("obo_id") for t in terms}
            self.cache[code] = next((label for anc, label in ECO_CLASSES if anc in ancestors), "curated_other")
        return self.cache[code]


def summarise_evidence(evidences: list[dict], eco: EcoClassifier) -> dict:
    codes = sorted({e["evidenceCode"] for e in evidences if e.get("evidenceCode")})
    classes = {eco(c) for c in codes}
    origin = next((c for c in ("experimental", "by_similarity", "curated_other", "automatic") if c in classes), "")
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
            ev = summarise_evidence(d.get("evidences", []), eco)
            xref = d.get("diseaseCrossReference", {})
            rows.append({**base, "species": species, "uniprot_accession": entry["primaryAccession"], "section": kind,
                         "disease_mim": xref.get("id", "") if xref.get("database") == "MIM" else "",
                         "text": f"{d.get('diseaseId', '')} ({d.get('acronym', '')}): {d.get('description', '')}", **ev})
        else:
            for t in c.get("texts", []):
                ev = summarise_evidence(t.get("evidences", []), eco)
                rows.append({**base, "species": species, "uniprot_accession": entry["primaryAccession"],
                             "section": kind, "disease_mim": "", "text": t.get("value", ""), **ev})
    return rows


def span(f: dict) -> tuple[int, int]:
    loc = f.get("location", {})
    return loc.get("start", {}).get("value") or 0, loc.get("end", {}).get("value") or 0


def change(f: dict) -> str:
    alt = f.get("alternativeSequence", {})
    start, _ = span(f)
    return f"{alt.get('originalSequence', '')}{start}{'/'.join(alt.get('alternativeSequences', []) or ['del'])}"


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
    ap.add_argument("--links", required=True, help="03_l2g_gwas_links.csv")
    ap.add_argument("--statements-out", required=True)
    ap.add_argument("--diseases-out", required=True)
    ap.add_argument("--variants-out", required=True)
    args = ap.parse_args()

    mouse_acc = {r["mgi_id"]: r for r in read_csv(args.accessions) if r["is_primary"] == "True"}
    orth = {r["mgiGeneAccId"]: r for r in read_csv(args.orthologs)}
    links = read_csv(args.links)
    ensembl = {r["hgnc_id"]: r["ensembl_id"] for r in links if r.get("ensembl_id")}

    genes = sorted(set(mouse_acc) | set(orth))
    targets = {}
    for mgi in genes:
        hgnc = orth.get(mgi, {}).get("hgncAccId", "")
        if ensembl.get(hgnc):
            targets[mgi] = ot_target(ensembl[hgnc])
    human_acc = {mgi: t["proteins"] for mgi, t in targets.items()}
    entries = uniprot_entries(sorted({r["uniprot_accession"] for r in mouse_acc.values()}
                                     | {a for accs in human_acc.values() for a in accs}))
    eco = EcoClassifier()

    st_rows, dis_rows, var_rows = [], [], []
    for mgi in genes:
        o = orth.get(mgi, {})
        base = {"mgi_id": mgi, "mouse_symbol": o.get("mouseGeneSymbol") or mouse_acc.get(mgi, {}).get("uniprot_gene", ""),
                "human_symbol": o.get("humanGeneSymbol", "")}
        if mgi in mouse_acc and mouse_acc[mgi]["uniprot_accession"] in entries:
            st_rows += statements(entries[mouse_acc[mgi]["uniprot_accession"]], base, "mouse", eco)
        ot_dis = targets.get(mgi, {}).get("diseases", [])
        by_mim = defaultdict(list)
        for d in ot_dis:
            for x in d.get("dbXRefs", []):
                if x.startswith("OMIM:"):
                    by_mim[x.split(":", 1)[1]].append(d)
        human_entries = [entries[a] for a in human_acc.get(mgi, []) if a in entries]
        for entry in human_entries:
            rows = statements(entry, base, "human", eco)
            st_rows += rows
            for c in entry.get("comments", []):
                if c.get("commentType") != "DISEASE":
                    continue
                d = c.get("disease", {})
                mim = d.get("diseaseCrossReference", {}).get("id", "")
                ev = summarise_evidence(d.get("evidences", []), eco)
                hits = by_mim.get(mim) or [{}]
                for hit in hits:
                    dis_rows.append({**base, "uniprot_accession": entry["primaryAccession"],
                                     "disease_name": d.get("diseaseId", ""), "disease_acronym": d.get("acronym", ""),
                                     "disease_mim": mim, "trait_id": hit.get("id", ""), "trait_label": hit.get("name", ""),
                                     "ot_uniprot_scores": "; ".join(f"{k} {v:.2f}" for k, v in hit.get("scores", {}).items()),
                                     "origin": ev["origin"], "pmids": ev["pmids"], "description": d.get("description", "")})

        # GWAS lead variants of this gene's credible sets, located on the human protein when UniProt lists them.
        hgnc = o.get("hgncAccId", "")
        by_lead = defaultdict(list)
        for r in links:
            if r["hgnc_id"] == hgnc:
                by_lead[r["lead_variant"]].append(r)
        features = [(e["primaryAccession"], f) for e in human_entries for f in e.get("features", [])]
        for lead, rs in by_lead.items():
            rsids = {x.strip() for r in rs for x in (r.get("rsids") or "").replace(";", ",").split(",") if x.strip()}
            signs = [r.get("trait_direction_alt") for r in rs]
            row = {**base, "lead_variant": lead, "rsids": "; ".join(sorted(rsids)),
                   "variant_consequence": rs[0].get("variant_consequence", ""), "n_credible_sets": len(rs),
                   "best_l2g_score": max(float(r["l2g_score"] or 0) for r in rs),
                   "traits": "; ".join(sorted({r["trait_from_source"] for r in rs if r.get("trait_from_source")}))[:500],
                   "beta_signs": "; ".join(f"{s} {signs.count(s)}" for s in ("increase", "decrease") if s in signs)}
            for acc, f in features:
                if f["type"] != "Natural variant":
                    continue
                if rsids & {x["id"] for x in f.get("featureCrossReferences", []) if x.get("database") == "dbSNP"}:
                    # One rsid can carry several alleles (LDLR rs2228671: synonymous C>T is the GWAS lead,
                    # C27W is another allele), so confirm with OT's amino-acid change for this exact allele.
                    ot_change = ot_amino_acid_change(lead, base["human_symbol"])
                    row["ot_amino_acid_change"] = ot_change
                    if ot_change != change(f):
                        row["uniprot_note"] = (f"same rsid as UniProt {f.get('featureId', '')} {change(f)}, but this "
                                               f"allele is {ot_change or 'not protein-changing'}; not the same variant")
                        continue
                    pos = span(f)[0]
                    doms = [d for a, d in features if a == acc and d["type"] == "Domain" and span(d)[0] <= pos <= span(d)[1]]
                    dom = doms[0] if doms else None
                    muts = [m for a, m in features if a == acc and m["type"] == "Mutagenesis"
                            and dom and span(dom)[0] <= span(m)[0] <= span(dom)[1]]
                    row.update({"uniprot_accession": acc, "uniprot_variant_id": f.get("featureId", ""),
                                "residue_change": change(f), "uniprot_note": f.get("description", ""),
                                "uniprot_variant_origin": summarise_evidence(f.get("evidences", []), eco)["origin"],
                                "domain": f"{dom['description']} {span(dom)[0]}-{span(dom)[1]}" if dom else "",
                                "domain_mutagenesis": " | ".join(f"{change(m)}: {m.get('description', '')}" for m in muts)[:800]})
            var_rows.append(row)
    var_rows.sort(key=lambda r: (r["mgi_id"], not r.get("uniprot_variant_id"), -r["n_credible_sets"]))

    write_csv(args.statements_out, STATEMENT_FIELDS, st_rows)
    write_csv(args.diseases_out, DISEASE_FIELDS, dis_rows)
    write_csv(args.variants_out, VARIANT_FIELDS, var_rows)
    unmapped = [f"{r['human_symbol']} {r['disease_acronym']} (MIM {r['disease_mim']})" for r in dis_rows if not r["trait_id"]]
    on_protein = sum(1 for r in var_rows if r.get("uniprot_variant_id"))
    print(f"{len(genes)} genes: {len(st_rows)} UniProt statements -> {args.statements_out}; {len(dis_rows)} human "
          f"disease rows ({len(dis_rows) - len(unmapped)} with an OT disease id) -> {args.diseases_out}; "
          f"{len(var_rows)} GWAS lead variants, {on_protein} listed as UniProt natural variants -> {args.variants_out}",
          file=sys.stderr)
    if unmapped:
        print("UniProt diseases without an OT id: " + ", ".join(unmapped), file=sys.stderr)
    no_human = [mgi for mgi in genes if mgi in orth and not human_acc.get(mgi)]
    if no_human:
        print("no human Swiss-Prot accession via OT: " + ", ".join(no_human), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
