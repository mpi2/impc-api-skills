# Reactome: pathway context per human gene

Experimental addition (step 2c). Not covered by evals until it is made definitive.

Step 2c lists, for each human ortholog, the most specific Reactome pathways
it takes part in. It is context for the reader, next to HPA expression. It is
not evidence and it is not scored against any trait or phenotype.

Together with the other hops it gives three views of gene function:
mouse knockout → phenotype (IMPC), human variant → trait with direction
(GWAS/L2G), and human gene → the pathways and reactions it acts in (Reactome).

## Access

Reactome publishes an MCP server (`github.com/reactome/reactome-mcp`), but it
runs locally over stdio and has no hosted endpoint, and its own config warns
that the public origin is sensitive to load. `scripts/reactome_pathways.py`
calls the same public REST APIs directly (no key). The MCP is useful for
one-off checks of a single gene or pathway.

| Call | Endpoint | Per |
| --- | --- | --- |
| Reviewed human accession(s) | UniProt REST `uniprotkb/search?query=xref:hgnc-<n> AND reviewed:true AND organism_id:9606` | gene |
| Pathways for an accession, with counts | `AnalysisService/identifier/{accession}/projection?pageSize=500&resource=TOTAL` | accession |
| What the accession mapped to (mis-map check) | `POST AnalysisService/token/{token}/found/all?resource=TOTAL` (body: stable ids) | accession |
| Pathway tree for the roll-up | `ContentService/data/eventsHierarchy/9606?pathwaysOnly=true` (560 KB) | run |
| Release number | `ContentService/data/database/version` (text/plain) | run |

The HGNC id comes from the IMPC orthology step (`02_orthologs.csv`,
`hgncAccId`), so the chain is IMPC orthology → UniProt → Reactome. All calls
are per gene; nothing is downloaded in bulk.

Things that cost time when first probing it:

- **Python's default User-Agent gets HTTP 403**; curl works. The script sends
  its own User-Agent.
- **`Accept: application/json` on a text endpoint gets HTTP 406**
  (`/data/database/version`).
- **One analysis call does both lookup and counts.** Every pathway returned
  carries `llp` (lowest-level pathway), `reactions.found/total` and
  `entities.total`. For LDLR the `llp=true` set is exactly the 5 pathways
  `/data/mapping/UniProt/P01130/pathways` returns, so the mapping call adds
  nothing and is not used.
- **The analysis p-value and FDR mean nothing for a single gene.** They are
  not written.
- **Gene not in Reactome:** the analysis answers HTTP 200 with
  `pathwaysFound: 0` (the mapping endpoint answers 404). Many genes have no
  curated pathways; the script writes one row with note
  `no Reactome annotation`, which is not an error.

## Lookup: HGNC id → reviewed UniProt accession → Reactome, with a check

Symbols are never used: they can be ambiguous or retired, and Reactome's
symbol index mis-maps. On the ankylosing spondylitis gene set, SYT4 and SNX29
have no pathways by accession but 4 each by symbol, because "SYT4" maps to
Q9BT88 (SYT11) and "SNX29" to Q02223 (TNFRSF17).

- **Reactome release 98 resolves no HGNC ids.** `HGNC:12440` (TYK2) returns
  0 pathways while the symbol, the Ensembl id and `P29597` return 45 (all
  levels). Release 97 resolved most HGNC ids (144 of 150 random genes), so the
  HGNC id used to be the primary query. Now the reviewed accession is. When a
  gene has no reviewed accession the HGNC id is still tried, in case a later
  release indexes it again.
- **UniProt accessions can mis-map.** Reactome's identifier index maps
  `P29474` (NOS3) onto `Q9UJU6` (DBNL), so a NOS3 query by accession returns
  18 pathways, 5 of them DBNL's ("Caspase-mediated cleavage of cytoskeletal
  proteins", "Neutrophil degranulation", ...). The script keeps a pathway only
  if Reactome mapped the accession to itself
  (`POST AnalysisService/token/{token}/found/all`, `mapsTo`). On NOS3 that
  keeps the 13 real pathways and drops the 5 DBNL ones.
- **`mapsTo` names isoforms.** HMGCR's `P04035` maps to `P04035-1` and
  `P04035-2`, SCARB1's `Q8WTV0` to `Q8WTV0-2`. The check compares the base
  accession; an exact-string check dropped 6 real HMGCR pathways and every
  SCARB1 pathway.
- Where a gene has several reviewed accessions, each is queried and the union
  kept (CUX1: 4 pathways in total, 1 from the CASP accession Q13948).

`queried_id` records the accession(s) used; stderr names every gene queried
by HGNC id and every pathway dropped by the check.

## Fields

| Output column | Source | Meaning |
| --- | --- | --- |
| `queried_id` | | Reviewed UniProt accession(s) that returned pathways, or the HGNC id when the gene has no reviewed accession; empty when nothing was found |
| `stable_id`, `pathway_name` | `stId`, `name` | Lowest-level pathway containing the gene |
| `top_level_category` | `eventsHierarchy` | Reactome's top-level pathway(s) above it; `;`-separated when there are several parents (Retinoid metabolism and transport → `Metabolism; Sensory Perception`). Under Disease the second level is kept: `Disease › Disorders of transmembrane transporters` |
| `reactions_with_gene`, `reactions_total` | `reactions.found/total` | Reactions in the pathway that involve the gene, and all reactions in it |
| `reaction_coverage` | computed | `reactions_with_gene / reactions_total` |
| `pathway_entities` | `entities.total` | Pathway size: molecules (proteins, small molecules) in it |
| `in_disease` | `inDisease` | Pathway sits under Reactome's Disease branch |
| `rank` | computed | Rank within gene (see Ranking) |

"Lowest-level" is not the same as "leaf": Clathrin-mediated endocytosis
(LDLR: 16/35 reactions) is flagged lowest-level and also contains Cargo
recognition for clathrin-mediated endocytosis (1/15), which is flagged too.
Both are kept.

## Ranking

Within each gene: `reaction_coverage` high to low, then `pathway_entities`
small to large, then `stable_id`. Simple and reproducible, and honest about
what it measures: how central the gene is to the pathway, not how relevant the
pathway is to the phenotype or trait. On real genes:

- LDLR: Chylomicron clearance 4/4 → Clathrin-mediated endocytosis 16/35 →
  LDL clearance 9/20 → Cargo recognition 1/15 → Retinoid metabolism 1/28
- TYK2 (24 pathways): Regulation of IFNA/IFNB signaling 4/5 →
  Interleukin-6 signaling 14/20 → ...
- NOS3: NOSIP mediated eNOS trafficking 2/2 → NOSTRIN mediated eNOS
  trafficking 4/4 → eNOS activation 15/19 → ...
- PNPT1: one pathway, Mitochondrial RNA degradation 2/10

## Disease pathways are kept

Reactome's Disease branch holds two kinds of pathway for a gene:

- **The gene's own human loss of function**, e.g. "Defective SLC2A1 causes
  GLUT1 deficiency syndrome 1" (1/1, size 2) or "Defective CFTR causes cystic
  fibrosis" (8/8). These are the human counterpart of a knockout and usually
  rank first.
- **Other agents acting on the protein**: viruses ("Evasion by RSV of host
  interferon responses", TYK2 1/12) or cancer mutants of other genes
  ("Constitutive Signaling by AKT1 E17K in Cancer", MTOR 1/18). These have low
  coverage and rarely reach the top 5.

The second-level label (`Disease › Infectious disease` vs
`Disease › Disorders of transmembrane transporters`) tells them apart from
Reactome's own tree; no mapping table is used.

## Report table

Headed "Pathways (Reactome, release N)", the top 5 pathways per gene by
`rank`, built from `02_reactome_pathways.csv`:

| Gene | Pathway | Top-level category | Reactions with gene | Pathway size |
| --- | --- | --- | ---: | ---: |
| SLC2A1 | [Defective SLC2A1 causes GLUT1 deficiency syndrome 1 (GLUT1DS1)](https://reactome.org/content/detail/R-HSA-5619043) (R-HSA-5619043) | Disease › Disorders of transmembrane transporters | 1/1 | 2 |
| SLC2A1 | [Lactose synthesis](https://reactome.org/content/detail/R-HSA-5653890) (R-HSA-5653890) | Metabolism | 1/3 | 9 |
| PNPT1 | [Mitochondrial RNA degradation](https://reactome.org/content/detail/R-HSA-9836573) (R-HSA-9836573) | Metabolism of RNA | 2/10 | 30 |
| ADGB | no Reactome annotation | | | |

Follow it with one line: how many pathways each gene has in total and that
the full list is in `02_reactome_pathways.csv`, e.g. "Top 5 of 24 pathways for
TYK2, 1 of 1 for PNPT1. Full list: `02_reactome_pathways.csv`."

README limitations: the release used, curation is uneven (no annotation means
not curated, not no function), the ranking measures how central the gene is
to a pathway and not how relevant the pathway is, and no pathway-to-phenotype
matching done.

## How to report it

Show the top 5 pathways per gene, for one gene or many, with stable id,
top-level category, reactions with the gene / total and pathway size. Say a gene with one pathway has one
pathway; do not read importance into rank 1 of a list of 24 beyond "the gene
takes part in most of that pathway's reactions". Do not say a pathway
"explains" or "matches" an IMPC phenotype or GWAS trait; leave that to the
reader. Pathway curation is uneven: absence from Reactome means "not curated",
not "no function". Expect many genes without pathways: about 11,500 of 20,300
reviewed human genes have one (54 of 92 genes in an ankylosing spondylitis
test run).
