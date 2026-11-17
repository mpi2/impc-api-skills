# STRING PPI enrichment guide

Figures below are from STRING 12.5, mouse, refreshed on 2026-11-17 after an
IMPC data release that raised IMPC-tested genes from 9,880 to 10,088. They
move with each IMPC release, so treat them as examples and quote a run's own
`string_run.json`, not this page, in a report.

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
| MP:0000063 *decreased bone mineral density* | 348 | 451 | 346 | 4.02e-08 | 366 | 9.77e-06 |
| MP:0010119 *abnormal bone mineral density* | 492 | 856 | 691 | 7.32e-10 | 730 | 3.0e-06 |
| MP:0005390 *skeleton phenotype* | 1,544 | 7,789 | 6,913 | 3.04e-25 | 7,246 | 1.46e-10 |
| MP:0002160 *abnormal reproductive system morphology* | 453 | 545 | 517 | 0.113 | 502 | 0.029 |

The last row moves the other way, because expected edges fall under the
IMPC-tested background for that set.

All 8,546 genes with an IMPC phenotype call, tested as one list against the
proteome, return p=6.31e-57 (8,486 proteins, mapped as below). No phenotype
selection went into that list.

## Background definition

Genes in the `statistical-result` core with `status:Successful`: 10,088 genes,
9,996 proteins, mapped by the same rule as query genes. It includes genes tested
with no hit, so it is wider than the 8,546 in `genotype-phenotype`, all of which
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
| MP:0001259 *abnormal body weight*, with descendants | 192 | 0.00054 | 0.0064 |
| MP:0001262 *decreased body weight* | 168 | 0.0023 | 0.013 |
| MP:0001260 *increased body weight* | 24 | 0.27 | 0.33 |

`mp_term_name` in `02_impc_genes.csv` shows each row's own term, and
`02_term_breakdown.csv` counts genes per row-level term under each queried
term, so a user can see which children a parent merges and rerun them.

When a parent is queried with its own children, their union is the parent's
gene set. The script does not test `combined` again in that case: its rows say
`not tested: same genes as <term>`.

## Confidence score

`required_score` runs from 0 to 1000; 400 gave the same result as omitting it.
Results depend on it, shown here for MP:0000063 against the proteome:

| Score | Edges | Expected | p |
| ---: | ---: | ---: | ---: |
| 150 | 2,824 | 2,613 | 2.28e-05 |
| 400 | 451 | 346 | 4.02e-08 |
| 700 | 92 | 70 | 0.0072 |

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
| `status` | `worked`, or why the row has no result, such as `not tested: same genes as <term>` |
| `string_network_url` | Link to the set's interactive STRING network; same under both backgrounds |
| `network_view_status` | `link`, a dense or no-link note, or why there is no link or image |
| `network_image` | PNG path under `06_network_images/`, flattened onto white; empty without `--images` |

`p_value` is STRING's value for one test. Neither STRING nor this skill corrects
it across gene sets.

`03_string_mapping.csv`:

| Column | Meaning |
| --- | --- |
| `mapped_via` | `mgi_id`, `symbol` or `unmapped` |
| `name_differs` | STRING's preferred name differs from the IMPC symbol |
| `rejected_symbol_hit` | Name STRING offered for a symbol that was refused |

`requests` in `string_run.json` lists every request the script made, in
order: purpose, function, URL, parameters (identifier lists as counts) and
outcome (`worked`, `zero results`, `failed` or `not run`). After a crash the
file holds only `status: crashed`, the error and `requests`.

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

This maps 9,996 of 10,088 tested genes: 9,980 by MGI id and 16 by symbol.

`name_differs` flags 384 genes. For 168, the symbol reaches the same protein,
so the name is just different (Sars1 is Sars in STRING). For 203, the symbol
has no exact hit, so only the MGI id maps. For 13, the MGI id reaches a
different entry from the one carrying the gene's name, such as Cox5b →
Gm11273 or Hmga1 → Hmga1b. Those entries look like near-identical proteins,
and the MGI entry often holds the fuller protein annotation, so neither is
clearly wrong; review them if they matter to a result.

UniProt does not improve on this. Measured on the release before 2026-11-17,
with one accession per gene, it mapped fewer genes (9,534 of 9,880), rescued
none of the genes left unmapped, and reached an entry with another name for
11 of the 12 genes then in the last group.

STRING holds proteins only, so non-coding RNA genes (miRNA, snoRNA, lncRNA)
and pseudogenes never map. IMPC has few of them, but they do occur: Mir96,
Mir129-2 and Snord11 have heart morphology calls, and Krt74 is a pseudogene in
Ensembl. Reports list unmapped genes with that note, so a missing gene is not
mistaken for a mapping fault. Not every unmapped gene is non-coding: Anxa13 is
protein-coding but has no STRING entry.

## Network view

Each tested set gets a STRING `get_link` URL from the same proteins, species
and `required_score` as the test, so the view shows the tested network. STRING
suggests a higher score for large views; the script does not raise it, because
the view would no longer match the test.

STRING's own guidance (MCP `string_help`, topic `large_input`): under about 300
proteins is optimal, larger networks become hairballs, and past about 2,000 the
website disables the network view. The script follows that: over 300 is flagged
`dense`, over 2,000 gets no link, and the user is pointed to the Cytoscape
stringApp with ids from `03_string_mapping.csv`.

The API itself did not refuse any size tested, so the limit is readability.
A 1,554-protein link (MP:0005390) opened in a browser, slowly:

| Proteins | `get_link` | SVG image |
| ---: | --- | --- |
| 300 | 1.3 s | 10 MB, 3 s |
| 1,000 | 1.6 s | 36 MB, 11 s |
| 2,000 | 2.0 s | 8.5 MB, 14 s |
| 2,500 | 2.4 s | 12 MB, 22 s |

`--images` saves PNGs (`/api/image/network`) for sets of 300 proteins or fewer
only. It is off by default for the size and readability reasons above; a
17-protein PNG is about 70 KB and a 149-protein one about 500 KB. STRING's PNGs
have a transparent background, which shows as black in dark viewers, and the
API has no background option, so the script flattens each PNG onto white with
the standard library (about 1 second for a 1,279 × 1,258 image).

Only the network is linked. STRING's per-edge evidence channels (`escore`,
`dscore` and others from `/api/tsv/network`) are not retrieved, and STRING does
not record which experimental method (such as mass spectrometry) supports an
interaction.

## Limits

No size limit appeared up to 8,486 proteins, all IMPC phenotype genes in one
test. STRING asks for one
second between calls and no parallel scripts, which the script follows. STRING
describes its MCP server as under development, so a tool may change; the script
checks that `string_ppi_enrichment` is listed and otherwise uses REST.
