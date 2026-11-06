# Open Targets: gene → L2G → credible set → GWAS study → traits

Tested against Platform API v4 (`https://api.platform.opentargets.org/api/v4/graphql`)
and the Open Targets MCP tools (`query_open_targets_graphql`,
`batch_query_open_targets_graphql`, `search_entities`, `get_open_targets_graphql_schema`)
on 2026-09-22. The bundled `scripts/ot_gene_to_gwas.py` implements everything here.

## Why the route looks the way it does

There is no one-hop field from a gene to the GWAS credible sets where it is an
L2G candidate:

- `Query.credibleSets(studyIds, variantIds, studyLocusIds, studyTypes, regions)`
  has no gene argument.
- `Target.credibleSets` returns only molQTL credible sets whose QTL gene is the
  target (eQTL/pQTL/sQTL…). For MTOR it returns 20 sets, all QTL, none with L2G
  predictions. Do not use it for GWAS.
- `regions:` is an exact string match on `CredibleSet.region`, the fine-mapping
  window (e.g. `19:10186554-10586312` on a TYK2 set, probed 2026-09-23; some
  sets have `null`). A gene's coordinates never equal that string, so the
  region filter is not a way from a gene to its GWAS sets, which is why earlier
  attempts saw 0.
- `Target.evidences` requires `efoIds` (empty list → 0 rows, parent terms are
  not expanded). So a disease list is needed first.

The L2G assignments live in `gwas_credible_sets` evidence rows. Two requests get them,
after one id-mapping request.

## Step 0 — HGNC id → Ensembl id

```graphql
query($t: [String!]!) {
  mapIds(queryTerms: $t, entityNames: ["target"]) { mappings { term hits { id name entity } } }
}
```

Variables: `{"t": ["HGNC:12440", …]}`. The orthology server returns HGNC ids and
symbols, not Ensembl ids; `mapIds` is an exact identifier lookup, so it avoids
free-text `search`, which is fuzzy (`NAT2` returns NAT2, SLC38A1 and NAA16).
Require exactly one `target` hit per term; the script skips and names anything
else. `target.dbXrefs` carries the HGNC id back (`{id: "12440", source: "HGNC"}`)
if a round-trip check is ever wanted.

## Step 1 — diseases with GWAS credible-set evidence (server-side filtered)

```graphql
query GwasCredibleSetDiseases($id: String!) {
  target(ensemblId: $id) {
    id approvedSymbol
    associatedDiseases(
      datasources: [{id: "gwas_credible_sets", weight: 1, propagate: false, required: true}]
      page: {index: 0, size: 3000}
    ) { count rows { disease { id name } } }
  }
}
```

`required: true` is what makes this cheap: MTOR returns 21 rows instead of the
2,599 unfiltered associations that then had to be filtered locally on
`datasourceScores`. `propagate: false` because step 2 does no ontology
expansion, so only the direct ids matter.

## Step 2 — evidence rows with credible set and study

```graphql
query GwasCredibleSetEvidence($id: String!, $efo: [String!]!, $size: Int!, $cursor: String) {
  target(ensemblId: $id) {
    evidences(efoIds: $efo, datasourceIds: ["gwas_credible_sets"], size: $size, cursor: $cursor) {
      count cursor
      rows {
        score                      # this target's L2G score for the credible set
        disease { id name }
        credibleSet {
          studyLocusId studyType chromosome position pValueMantissa pValueExponent confidence finemappingMethod
          beta standardError effectAlleleFrequencyFromSource
          variant { id rsIds referenceAllele alternateAllele mostSevereConsequence { label } }
          l2GPredictions(page: {index: 0, size: 5}) { count rows { score target { id approvedSymbol } } }
          study {
            id studyType projectId traitFromSource traitFromSourceMappedIds
            diseases { id name } backgroundTraits { id name }
            pubmedId publicationFirstAuthor publicationDate nSamples nCases hasSumstats
          }
        }
      }
    }
  }
}
```

Variables: `{"id": "ENSG00000198793", "efo": [<ids from step 1>], "size": 1000, "cursor": null}`.
Loop on `cursor` until null. MTOR: 31 rows in one page.

What the fields mean:

| Field | Meaning |
| --- | --- |
| `score` | The gene's L2G score for that credible set (verified equal to its entry in `l2GPredictions`). Floor is 0.05: evidence is only emitted above it, so weak assignments are absent rather than zero. |
| `l2GPredictions.rows` | Sorted by score desc. Gene is the top candidate iff `rows[0].target.id == ensemblId`; rank = its index + 1. `count` is the total number of candidates; raise `size` if `count > size` and the gene is not in the returned rows. |
| `credibleSet.finemappingMethod`, `confidence` | How the set was built (SuSiE / SuSiE-inf / PICS; in-sample vs out-of-sample LD; from summary statistics vs reported top hit). See Gotchas. |
| `study.id` / `projectId` | `GCST…` + `GCST` = GWAS Catalog; `FINNGEN_R12_…` + `FINNGEN_R12` = FinnGen (not in the Catalog). |
| `study.diseases` | Platform-normalised mapped traits (id + label). This is what the evidence rows are keyed on. Use it as the trait list. |
| `study.traitFromSourceMappedIds` | Raw mapped ids from the source; occasionally differs from `diseases` (e.g. EFO_0000516 vs MONDO_0005041 glaucoma). |
| `credibleSet.beta`, `standardError` | Signed effect of the lead variant per copy of `variant.alternateAllele`; log-odds for binary traits. Present for most credible sets (27/30 for MTOR; some PICS sets lack it). Sign gives the trait direction for the alt allele; magnitude is in the study's own units. |
| `credibleSet.effectAlleleFrequencyFromSource` | Alt-allele frequency in the study. |
| `variant.referenceAllele`, `alternateAllele`, `mostSevereConsequence` | Allele orientation for the sign, and the VEP consequence class (intron_variant, missense_variant, …). Consequence class is not a direction. |
| `study.traitFromSource` | Free-text reported trait (e.g. `Impedance of arm left (UKB data field 23110)`); can contain mojibake. |
| `study.backgroundTraits` | Conditioning traits for GxE / conditional studies; not the outcome. |
| evidence-level `studyId`, `variantRsId`, `pValueMantissa`, `beta` | Null for this datasource; read them from `credibleSet` instead. |

## Gotchas

- **Query-cost limiter.** `size: 3000` together with nested `l2GPredictions(size: 5)`
  returns HTTP 400 "Query is too expensive". `size: 1000` + `l2GPredictions(size: 5)`
  is fine; the script halves the page on that error.
- **Duplicates.** One evidence row per (credible set, disease); a study mapped to
  two traits yields two rows with the same `studyLocusId`. Deduplicate on
  (gene, `studyLocusId`) for the link table; keep all rows in the evidence file.
- **Coarse mappings are upstream.** UKB impedance studies map to
  `HP_0000924 Abnormality of the skeletal system` in both Open Targets and the
  GWAS Catalog. The skill scores the assigned terms as they are; carry
  `traitFromSource` alongside so the reader can see when the mapped label is
  broader than the measured trait, and note it in the README.
- **Coverage.** Evidence exists only for studies with a mapped disease. Credible
  sets from unmapped studies where the gene has L2G ≥ 0.05 are not reachable
  from the gene side.
- **Effect direction is per allele, not per gene.** `beta` tells you what the
  alt allele does to the trait. It does not tell you whether the allele raises
  or lowers the L2G gene's function, so do not read it as knockout concordance.
  The GWAS Catalog's curated association betas/ORs are not joined: they cover
  only reported top hits (25 rows vs 248 credible sets for GCST90480502), their
  rsIDs are often not the Open Targets lead variants, and their "risk allele"
  is frequently the reference allele, so a naive sign comparison is wrong.
- **Ensembl id resolution.** Use `mapIds` with HGNC ids (step 0). Free-text
  `search` / `search_entities` is fuzzy and only acceptable for a gene typed by
  the user with no HGNC id; then take the hit whose `name` equals the symbol.
- **Fine-mapping method is credible-set resolution, not gene evidence.**
  `confidence` values seen: `SuSiE fine-mapped credible set with in-sample LD`,
  `… with out-of-sample LD`, `PICS fine-mapped credible set extracted from summary
  statistics`, `PICS fine-mapped credible set based on reported top hit`. TYK2:
  26 / 53 / 40 / 55 sets; every SuSiE set had `beta`, 63 of 95 PICS sets did.
  `credibleSetConfidence` is one of the 31 L2G features (0.75 for an
  out-of-sample SuSiE set), so the L2G score already accounts for it.

## Reverse entry (trait → studies)

```graphql
query($ids: [String!]!) {
  studies(diseaseIds: $ids, enableIndirect: true, page: {index: 0, size: 200}) {
    count rows { id studyType projectId traitFromSource diseases { id name } } } }
```

`enableIndirect: true` adds studies mapped to descendants of the id.
MONDO_0005306 (ankylosing spondylitis) gave 41 studies (GCST and FinnGen),
including pleiotropy studies that list it among several diseases.
`scripts/ot_gene_to_gwas.py --disease-ids …` runs this and passes the GWAS
study ids to the study → genes query below. Get the id from `search_entities`,
not from memory.

## Reverse entry (study → genes)

```graphql
query($ids: [String!]!) {
  credibleSets(studyIds: $ids, studyTypes: [gwas], page: {index: 0, size: 200}) {
    count rows { studyLocusId studyId pValueMantissa pValueExponent beta standardError effectAlleleFrequencyFromSource
      variant { id rsIds referenceAllele alternateAllele mostSevereConsequence { label } }
      l2GPredictions(page: {index: 0, size: 5}) { count rows { score target { id approvedSymbol } } }
      study { id traitFromSource diseases { id name } } } } }
```

Two ankylosing-spondylitis / lupus studies gave 315 credible sets and 562 L2G
gene rows; expect large outputs and filter on rank 1 / L2G ≥ 0.5 before taking
genes to the orthology step. `scripts/ot_gene_to_gwas.py --study-ids …` runs this.

## Using the MCP instead of the script

`query_open_targets_graphql` accepts the same query + variables. Use it when
the user is interactive and the gene list is short; the results are identical
(verified for MTOR step 1). For more than a few genes, or whenever the output
must land in CSV, the script is less error-prone than hand-copying JSON.
