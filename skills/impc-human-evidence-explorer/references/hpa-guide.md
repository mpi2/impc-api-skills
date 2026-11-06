# Human Protein Atlas (HPA): tissue expression as gene-level context

Experimental addition (step 2b). Not covered by evals until it is made definitive.

Step 2b adds one row per human ortholog describing where the gene is expressed
in adult human tissues. It is context for the reader. The skill does not link
HPA tissues to IMPC phenotypes (see "Not done, on purpose").

## Access

There is no official HPA MCP server; the community one is not used. The script
calls the documented download API, which needs no key:

```
https://www.proteinatlas.org/api/search_download.php?search=<symbol|ENSG>&format=json&columns=<codes>&compress=no
```

Column codes are listed at https://www.proteinatlas.org/about/help/dataaccess
(about 1,950 of them). Things that cost time when first probing it:

- **Unknown column codes are dropped silently.** `t_RNA_brain` returns nothing
  because HPA splits brain into regions (`t_RNA_cerebral_cortex`,
  `t_RNA_cerebellum`, ...). `scripts/hpa_tissue_expression.py` pins the 51
  documented `t_RNA_*` consensus tissue codes. Three carry a suffix:
  `skin_1`, `stomach_1`, `endometrium_1`.
- **The search is fuzzy.** It can return several genes; the script keeps only
  an exact match on `Gene` or `Ensembl` and writes a note row otherwise.
- **Per-tissue nTPM is only in the search API.** The per-gene entry
  (`proteinatlas.org/{ENSG}.json`) has the summary fields but no per-tissue
  values. The per-gene XML (`{ENSG}.xml`) has both, plus UBERON ids per tissue
  (`<tissue ontologyTerms="UBERON:0002107">Liver</tissue>`; 50 of 51 consensus
  tissues, all but "Blood vessel").

## Fields used

| Output column | HPA field (code) | Meaning |
| --- | --- | --- |
| `tissue_specificity` | RNA tissue specificity (`rnats`) | HPA's category: Tissue enriched, Group enriched, Tissue enhanced, Low tissue specificity, Not detected |
| `tissue_distribution` | RNA tissue distribution (`rnatd`) | Detected in all / many / some / single |
| `specificity_score` | RNA tissue specificity score (`rnatss`) | Fold change behind an enriched/enhanced call; empty for low specificity |
| `tau` | TAU score - Tissue (`t_RNA__tau`) | 0 = even across tissues, 1 = one tissue only |
| `enriched_tissues_ntpm` | RNA tissue specific nTPM (`rnatsm`) | The tissues named in HPA's enriched/enhanced call, with nTPM |
| `n_tissues_detected` | computed from `t_RNA_*` | Tissues with nTPM ≥ 1 (HPA's detection threshold), out of 51 |
| `top_tissues_ntpm` | computed from `t_RNA_*` | Highest tissues by nTPM |
| `cell_type_specificity`, `enriched_cell_types_ncpm` | `rnascs`, `rnascsm` | Same call from single-cell RNA |

nTPM is HPA's consensus normalised expression (HPA + GTEx RNA-seq). The long
per-tissue table (`--tissues-out`) holds all 51 values with ranks.

Not fetched: protein expression, brain-region, blood-cell, cell-line, cancer
and secretome data. Add them only when a user asks.

## Report table

Headed "Tissue expression (Human Protein Atlas)", one row per human gene,
built from `02_hpa_tissue_expression.csv`:

| Gene | HPA tissue specificity | Tau | Enriched tissues (nTPM) | Top tissues (nTPM) | Detected |
| --- | --- | ---: | --- | --- | --- |
| PNPT1 | Low tissue specificity | 0.28 | none | skeletal muscle 10.8; spinal cord 9; cerebellum 8.2 | 51/51 |
| ALB | Tissue enriched | 0.87 | liver 198523.8 | liver 198524; pancreas 1480.5; kidney 433.7 | 39/51 |

Show the top three tissues; the CSV keeps five.

README limitations: adult human tissue only, no bone, blood or developmental
stages, and no phenotype-to-tissue matching done.

## How to report it

Quote HPA's own call (category, tau, enriched tissues) and the top tissues as
numbers. Many IMPC genes are housekeeping genes (PNPT1, AARS1: low tissue
specificity, detected in 51/51, tau 0.28 and 0.19); say so plainly rather than
reading meaning into which tissue happens to rank first.

## Not done, on purpose

Matching an IMPC phenotype to an HPA tissue was tested and parked (2026-10-12).
Using OLS only, over all 812 MP terms in the IMPC `genotype-phenotype` core
(67,349 associations): 54% of associations have a UBERON/CL entity in the MP
logical definition, but only 20% reach an HPA tissue by walking up UBERON
(25% walking down too, which adds wrong matches such as head → retina). The
gaps are anatomy HPA does not profile (blood, bone, lens, hair) and phenotypes
with no anatomy (lethality, behaviour, lean mass). A hand-maintained
phenotype → tissue table was rejected. Until an ontology-driven route is
validated, do not label a phenotype as "matching" or "supported by" a tissue;
leave that judgement to the reader.
