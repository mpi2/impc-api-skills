# STRING PPI enrichment guide

Figures below are from STRING 12.5, mouse, 2026-11-06.

## Background note

Copy this into each run's README:

> **Why two backgrounds.** STRING's default test compares a gene set against
> the whole proteome, but IMPC genes are not a random sample of it. As a group
> they are more connected than the proteome, so a proteome p-value partly
> reflects which genes IMPC studied rather than the phenotype. The IMPC-tested
> background instead asks whether this set is more connected than other genes
> IMPC phenotyped, including those with no significant phenotype. Both are
> reported because they answer different questions. Comparing them shows how
> much the background affects a result, and the shift can go either way.

Evidence for that note, at required score 400:

| Gene set | Proteins | Observed edges | Expected, proteome | p, proteome | Expected, IMPC-tested | p, IMPC-tested |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MP:0000063 *decreased bone mineral density* | 314 | 352 | 277 | 8.52e-06 | 295 | 6.5e-04 |
| MP:0010119 *abnormal bone mineral density* | 457 | 715 | 578 | 2.24e-08 | 618 | 6.93e-05 |
| MP:0005390 *skeleton phenotype* | 1,554 | 7,989 | 7,070 | 5.01e-27 | 7,440 | 1.6e-10 |
| MP:0002160 *abnormal reproductive system morphology* | 829 | 1,770 | 1,715 | 0.094 | 1,684 | 0.019 |

The last row moves the other way, because expected edges fall under the
IMPC-tested background for that set.

All 8,429 genes with an IMPC phenotype call, tested as one list against the
proteome, return p=7.64e-53 (8,255 proteins mapped by symbol). No phenotype
selection went into that list.

## Background definition

Genes in the `statistical-result` core with `status:Successful`: 9,880 genes,
9,790 proteins, mapped by the same rule as query genes. It includes genes tested
with no hit, so it is wider than the 8,429 in `genotype-phenotype`, all of which
it contains.

STRING returns an error if a query protein is missing from the background
("not a subset of the provided background list"). The script adds any such
protein and lists it under `query_proteins_added` in `string_run.json`.

## Why two routes

The MCP tool takes only `identifiers`, `species` and `required_score`. REST also
takes `background_string_identifiers`, which accepts STRING ids only, so
`string_ppi.py` maps genes first. Without a custom background the two routes
return identical results. The `source` column shows which one produced a row.

## Parent terms merge directions

A parent term includes everything below it, which can combine opposite effects.
The merged p-value does not say which direction drives it:

| Set | Genes | p, proteome | p, IMPC-tested |
| --- | ---: | ---: | ---: |
| MP:0001259 *abnormal body weight*, with descendants | 173 | 0.0015 | 0.01 |
| MP:0001262 *decreased body weight* | 155 | 0.028 | 0.088 |
| MP:0001260 *increased body weight* | 17 | 0.22 | 0.25 |

`mp_term_name` in `02_impc_genes.csv` shows each row's own term, so a user can
rerun the child terms.

## Confidence score

`required_score` runs from 0 to 1000; 400 gave the same result as omitting it.
Results depend on it, shown here for MP:0000063 against the proteome:

| Score | Edges | Expected | p |
| ---: | ---: | ---: | ---: |
| 150 | 2,252 | 2,086 | 1.7e-04 |
| 400 | 352 | 277 | 8.52e-06 |
| 700 | 63 | 57 | 0.21 |

## Output columns

`01_resolved_terms.csv`:

| Column | Meaning |
| --- | --- |
| `rows` | IMPC rows matched |
| `exact_genes` | Genes with a row on the term itself |
| `intermediate_new_genes` | Further genes found through `intermediate_mp_term_id` |
| `top_level_new_genes` | Further genes found through `top_level_mp_term_id` |
| `total_genes` | Unique genes, the sum of the three |

`02_impc_genes.csv` has one row per statistical call. `match_level` is how that
row matched, and `gene_match_level` is the first level at which the gene matched.

`04_ppi_enrichment.csv`:

| Column | Meaning |
| --- | --- |
| `gene_set`, `gene_set_label` | MP id or `combined`; label or the terms merged |
| `set_type` | `single` or `combined` |
| `background` | `proteome` or `impc_tested` |
| `source` | `mcp`, `rest`, or empty if not run |
| `required_score` | Confidence threshold used |
| `genes_in_set`, `proteins_mapped` | Unique genes in, proteins sent to STRING |
| `number_of_nodes`, `number_of_edges`, `average_node_degree`, `local_clustering_coefficient`, `expected_number_of_edges`, `p_value` | STRING's fields, unchanged |
| `status` | `worked`, or why the row has no result |

`p_value` is STRING's value for one test. Neither STRING nor this skill corrects
it across gene sets.

`03_string_mapping.csv`:

| Column | Meaning |
| --- | --- |
| `mapped_via` | `mgi_id`, `symbol` or `unmapped` |
| `name_differs` | STRING's preferred name differs from the IMPC symbol |
| `rejected_symbol_hit` | Name STRING offered for a symbol that was refused |

## Mapping

STRING's docs list gene names, synonyms and UniProt ids as inputs. MGI ids are
not documented but work with species 10090. The species decides the network:
with no species, `Trp53` resolves to human TP53, so the script always sends it.

Order, for query genes and the background:

1. MGI id. Ids are stable and symbols drift.
2. Symbol, only when STRING's name matches exactly. A different name is refused
   because the hit can be another gene: Pla2g2a resolves to Itga5, Ccdc40 to
   Ccdc39.
3. Otherwise unmapped, recorded and left out of the test.

This maps 9,790 of 9,880 tested genes.

`name_differs` flags 295 of these genes, plus 12 more. For 145 of the 295, the
symbol reaches the same protein, so the name is just different (Sars1 is Sars in
STRING). For 148, only the MGI id maps, so that check is not available. For the
12, the MGI id reaches a different entry from the one carrying the gene's name,
such as Cox5b → Gm11273. Those entries look like near-identical proteins, and
the MGI entry often holds the fuller protein annotation, so neither is clearly
wrong. Semg1 and Fcrl2 disagree with IMPC by both routes; review them if they
matter to a result.

UniProt does not improve on this. Using one accession per gene, it mapped fewer
genes (9,534), rescued none of the genes left unmapped, and reached an entry
with another name for 11 of those 12 genes.

## Limits

No size limit appeared up to 8,429 ids in about 10 seconds. STRING asks for one
second between calls and no parallel scripts, which the script follows. STRING
describes its MCP server as under development, so a tool may change; the script
checks that `string_ppi_enrichment` is listed and otherwise uses REST.
