---
name: impc-gwas-trait-mapper
description: Link IMPC mouse knockout phenotypes to human GWAS traits, in either direction. Given IMPC genes or MP phenotypes, it retrieves the IMPC phenotypes, maps mouse genes to human one-to-one orthologs (IMPC orthology MCP), follows Open Targets locus-to-gene (L2G) evidence through credible sets to GWAS studies, resolves each study's EFO/MONDO/HP/OBA traits (Open Targets study index, GWAS Catalog MCP/API) and scores every mouse phenotype against every trait with OLS embedding similarity (MP vs EFO). Use it whenever a user mentions IMPC, mouse knockouts or MP terms together with GWAS, GWAS Catalog, human traits, credible sets, L2G, Open Targets genetics or EFO, or asks whether a mouse phenotype "translates", "matches", "is consistent with" or "supports" a human association, even if they never say "map". Also use it for the reverse question: which IMPC phenotypes or knockout genes support a GWAS trait or study.
---

# IMPC phenotypes ↔ GWAS traits

## Why this skill exists

The IMPC measures what breaks when a mouse gene is knocked out. GWAS measure
which human loci shift a trait. Joining the two answers "does the mouse model
support this human association?", but it takes five hops across five services,
each with its own identifiers, and an unguided attempt spends most of its effort
on plumbing: paging 2,600 Open Targets diseases, guessing EFO IRIs, retyping
GraphQL, or trying `credibleSets(regions:)` which can never return GWAS sets.
This skill fixes the route, ships the plumbing as scripts, and leaves your
effort for the biology and the report.

```
IMPC gene / phenotypes (MGI, MP)               impc-data-retriever skill
  → human one-to-one ortholog (HGNC)            impc-orthology MCP · scripts/orthologs.py
  → L2G evidence → credible set → GWAS study    Open Targets MCP · scripts/ot_gene_to_gwas.py
  → study traits (EFO/MONDO/HP/OBA ids)         Open Targets study index · GWAS Catalog MCP/API
  → MP ↔ trait cosine similarity (0–1)          OLS MCP · scripts/ols_similarity.py
  → (on request) mouse disease models           phenodigm core · references/impc-model-search-strategy.md
```

Every hop keeps its identifiers, so the final table audits back to the IMPC
statistical call on one side and the GWAS study accession on the other.

## Prerequisites

1. `uv`: read the `uv` skill and follow its setup. Run all Python through the
   local uv project (`uv run …`). The bundled scripts need only the standard
   library; `impc-api` (with pandas) must import for step 1:
   `uv run python -c "import impc_api"`. If that fails, follow the install
   steps in `impc-data-retriever`.
2. The `impc-data-retriever` skill, used as-is for step 1 and, when the user
   asks for disease models, for step 7 (`phenodigm` core).
3. MCP servers, each optional because each has a script fallback that hits the
   same public endpoint:

   | Server | Tools you'd use | Fallback |
   | --- | --- | --- |
   | Open Targets | `query_open_targets_graphql`, `search_entities` | `scripts/ot_gene_to_gwas.py` (public GraphQL) |
   | `impc-orthology` `https://www.ebi.ac.uk/mi/impc/mcp/orthology/` | `find_orthologs_by_mgi_ids`, `find_orthologs_by_mouse_genes`, `find_orthologs_by_human_genes` | `scripts/orthologs.py` |
   | OLS `https://www.ebi.ac.uk/ols4/api/mcp` | `getClassSimilarity` (pair scores), `listEmbeddingModels` | `scripts/ols_similarity.py` |
   | GWAS Catalog `https://www.ebi.ac.uk/gwas/mcp` | `gwascatalog_get_studies`, `gwascatalog_get_traits` | `scripts/gwas_catalog_traits.py` (REST v2) |

   Check which tools are actually loaded in this session. When a server is
   missing or times out, use the script and say so in the README; do not stall
   the run to install servers. If the user wants the IMPC orthology server
   installed, invoke `impc-mcp-setup` naming only that server.

## Inputs this skill accepts

- one or more mouse genes (symbol or MGI id), optionally with a phenotype focus
  ("Mtor kidney phenotypes → GWAS");
- an MP term ("genes with decreased BUN → human traits");
- the reverse: a GWAS trait, EFO/MONDO id or GCST study, asking which IMPC
  phenotypes or knockouts support it.

Ask only when the species is ambiguous (follow the gene-identifier rules in
`impc-data-retriever`) or when "top genes" needs a ranking rule the user has
not given. Otherwise choose a sensible default, state it, and proceed.

## Workflow

Create a descriptive result directory (e.g. `mtor_impc_to_gwas/`) and number
files in hop order. Keep an attempt log from the first request; the README is
built from it (see Output). Scripts print row counts to stderr; capture them.

### 1. IMPC genes and phenotypes

Follow `impc-data-retriever`. One query, whichever way the user starts:
`genotype-phenotype` core, filtered by gene (`marker_symbol:Mtor`,
`marker_accession_id:"MGI:1928394"`) or by phenotype (`mp_term_id:"MP:0005566"`),
with `marker_accession_id, marker_symbol, mp_term_id, mp_term_name, p_value,
effect_size, sex, zygosity`.

The first four are what the later hops read: the MGI id feeds orthology, the
MP id and name feed similarity. The other four describe the statistical call
and ride through to the final table so the reader can weigh the IMPC evidence
next to L2G and similarity. They split one gene × MP term into one row per
call (Tyk2: 24 rows for 19 MP terms); that is fine, the similarity script
dedupes on `mp_term_id` itself. Leave out procedure, parameter, centre and
top-level MP fields: nothing downstream uses them.

Write `01_impc_phenotypes.csv`. Keep `mp_term_id` and `mp_term_name` even when
the user asked only about genes: they are the left side of the similarity step.

For many genes, do not use `batch_solr_request` list mode
(`field_list`/`field_type`) with `MGI:` ids: the helper does not quote the
values, Solr reads `MGI` as a field name and returns HTTP 400
`undefined field MGI`. Build a quoted grouped query instead, in chunks of
~50: `marker_accession_id:("MGI:1928394" OR "MGI:1347521" ...)`.

### 2. Human orthologs

Use one-to-one orthologs only. A one-to-many family would spread one GWAS
locus over several mouse genes and make the final table unreadable.

- MCP: `find_orthologs_by_mgi_ids` (ids are stable; symbols drift). Max 600 per call.
- Script: `uv run skills/impc-gwas-trait-mapper/scripts/orthologs.py --from-csv 01_impc_phenotypes.csv --id-col marker_accession_id --out 02_orthologs.csv`

Keep `mgiGeneAccId, mouseGeneSymbol, hgncAccId, humanGeneSymbol, supportCount`.
Genes with no one-to-one ortholog stop here; list them under limitations
rather than substituting a paralog.

### 3. Open Targets: L2G → credible set → GWAS study → mapped traits

Read `references/open-targets-guide.md` before writing any GraphQL. Then:

```bash
uv run skills/impc-gwas-trait-mapper/scripts/ot_gene_to_gwas.py --orthologs 02_orthologs.csv \
  --out-evidence 03_ot_l2g_evidence.csv --out-links 03_l2g_gwas_links.csv --out-traits 04_gwas_traits.csv
```

The script maps the `hgncAccId` column to Ensembl ids with Open Targets
`mapIds` (an exact identifier lookup, so a symbol that is an alias or prefix of
another gene cannot pull in the wrong target; ids with anything other than one
hit are skipped and named on stderr), runs the two tested queries (filtered
`associatedDiseases` → `evidences` with nested `credibleSet.study`), and writes:

- `03_ot_l2g_evidence.csv`: one row per credible set × mapped disease (raw);
- `03_l2g_gwas_links.csv`: one row per gene × credible set, deduplicated on
  `study_locus_id`, with `hgnc_id`, `l2g_score`, `l2g_rank_in_locus`,
  `top_l2g_gene_in_locus`, lead variant, p-value, `finemapping_method` and
  `confidence` (how the credible set was built), the trait effect of the lead
  variant (`ref_allele`, `alt_allele`, `alt_allele_freq`, `beta_alt`, `beta_se`,
  `trait_direction_alt`, `variant_consequence`), `gwas_study_id`, `gwas_source`
  (`GCST` = GWAS Catalog, `FINNGEN_R12` = FinnGen), `trait_from_source`,
  `study_trait_ids`/`study_trait_labels`;
- `04_gwas_traits.csv`: one row per study × mapped trait id, ready for step 5.

Interpretation rules that belong in the report:

- L2G is the probability the gene is causal at that locus, not a p-value.
  Rows with L2G ≥ 0.5 and rank 1 are the strong links; show lower rows but say
  which gene outranks yours.
- Open Targets emits evidence only above an L2G floor of 0.05, so weak
  assignments are absent, not zero.
- `finemapping_method` and `confidence` say how the credible set was built:
  SuSiE with in-sample LD (best), SuSiE with out-of-sample LD, PICS from
  summary statistics, or PICS from a reported top hit (no summary statistics,
  LD-approximated, often no `beta_alt`). Carry them into the final table as
  credible-set resolution. They are not independent evidence for the gene:
  credible-set confidence is already one of the L2G model's features, so a
  PICS set with a high L2G has been scored with that handicap included.
- FinnGen studies are real GWAS but are not GWAS Catalog entries; keep and label them.
- `beta_alt` is Open Targets' signed effect per copy of the **alternate** allele
  (log-odds for binary traits), taken from the credible set itself, so it covers
  every credible set that has one (MTOR: 27 of 30; some PICS sets have none).
  `trait_direction_alt` is just its sign: `increase` means the alt allele raises
  the trait or risk. This is the direction of the *human trait* for that allele.
  It says nothing about whether the allele means more or less of the gene, so it
  is not by itself a knockout-concordance statement; report it as trait
  direction and stop there. Magnitudes are study-specific (often inverse-
  normalised units), so compare signs, not sizes, across studies. The GWAS
  Catalog's curated per-association beta/OR is not joined: it covers only the
  reported top hits and its rsIDs are often not the Open Targets lead variants.

### 4. Trait ids: GWAS Catalog, always, and compare with Open Targets

Step 3 yields mapped trait ids from the Open Targets study index. The GWAS
Catalog is the primary source for `GCST` studies, so fetch its mapping for
every study and compare the two (`references/gwas-catalog-guide.md`). MCP
(`gwascatalog_get_studies`) if connected, otherwise:

```bash
uv run skills/impc-gwas-trait-mapper/scripts/gwas_catalog_traits.py \
  --from-csv 03_l2g_gwas_links.csv --id-col gwas_study_id \
  --compare-ot 04_gwas_traits.csv --out 04_gwas_catalog_traits.csv
```

`--compare-ot` writes `04_gwas_catalog_traits_vs_open_targets.csv`, one row per
study with status `agree` / `catalog_extra` / `ot_extra` / `differ` /
`not_in_catalog`, and prints every disagreement. On 86 test studies: 80 agreed,
one had a Catalog-only extra trait (`EFO_0000493 family history` on a UKB
sibling-history study), five were FinnGen and not in the Catalog. Treat each
non-`agree` study as something to tell the user: list it in the synthesis and
in the README limitations with both id sets. Build the trait table for step 5
as the **union** of both sources, tagging `trait_source` per row
(`open_targets_study.diseases`, `gwas_catalog`), so a similarity hit can be
traced to whichever service supplied the id. FinnGen studies keep their Open
Targets ids and the `not_in_catalog` flag.

Score only the ontology terms the two services assign to each study. Some of
those mappings are coarse at the source (UKB "Impedance of arm" studies map to
`HP_0000924 Abnormality of the skeletal system` in both services): keep
`trait_from_source` in the trait table so the reader can see it, and mention
such cases in the README, but do not substitute or add terms of your own. Never
type an ontology id from memory.

### 5. Similarity between MP phenotypes and traits

Read `references/ols-similarity-guide.md` for the tool inventory, IRI forms and
what the score does and does not mean. Then:

```bash
uv run skills/impc-gwas-trait-mapper/scripts/ols_similarity.py \
  --phenotypes 01_impc_phenotypes.csv --phenotype-id-col mp_term_id --phenotype-label-col mp_term_name \
  --traits 04_gwas_traits.csv --trait-id-col trait_id --trait-label-col trait_label \
  --out 05_phenotype_trait_similarity.csv
```

It calls OLS `getClassSimilarity` for every pair (cosine similarity of the two
classes' embeddings) and ranks within phenotype and within trait. For two or
three pairs the MCP tool by hand is fine; beyond that, the script (~30 pairs/s).

The model is a user choice between two, offered in these terms:

- **breadth** — `harrier-oss-v1-27b_pca512` (default). Broader coverage of
  the ontologies and more scores; the model to use when looking for "deep
  cuts", i.e. traits a narrower model would leave near the floor.
- **precision** — `text-embedding-3-large_pca512`. Tighter; the model to use
  when the question is "which single trait is closest to this phenotype".

If the user does not say, use breadth and state that. If they name a model,
pass `--model <name>`; if they want both, pass `--model harrier-oss-v1-27b_pca512
text-embedding-3-large_pca512` and the output has one row per pair per model
with per-model ranks. `--list-models` (or the MCP tool `listEmbeddingModels`)
shows what OLS offers today. Always state the model next to the scores, because
values are not comparable across models (on the same 741 Tyk2 pairs the
medians were 0.64 for harrier and 0.60 for large).

Report the score as a number next to the two labels and the model name. Do not
translate it into words such as "match", "related", "strong" or "background":
the scale is model-specific and has not been calibrated against curated
MP↔trait mappings. What can be said is that the model compresses cosine
values into a narrow range, so the ordering within a run is informative while
absolute values are not comparable across models. Show the per-run
distribution (min / median / max) so the reader can place each score.

Display cutoff: by default list pairs with similarity ≥ 0.60 in the
user-facing table, say that this cutoff is a display choice and that the full
table is in `05_…similarity.csv`. Use whatever cutoff the user asks for.

If the trait list is long, restrict it before scoring, typically to traits from
credible sets where the gene ranks top-3 by L2G, and say which filter you used.

### 6. Join and rank

Two files, two grains.

`06_impc_gene_to_gwas_trait.csv`, the main table: one row per MP term × GWAS
trait. This is what the synthesis and the chat table are built from.

`marker_accession_id, marker_symbol, mp_term_id, mp_term_name, hgnc_id, human_symbol, trait_id, trait_label, similarity, n_credible_sets, n_lead_variants, best_cs_l2g_score, best_cs_l2g_rank, best_cs_l2g_n_genes, best_cs_l2g_top_gene, best_cs_confidence, best_cs_lead_variant, best_cs_beta_alt, best_cs_direction_alt, best_cs_study_id, best_cs_study_locus_id`

What the derived columns mean, because readers will not know the data:

- `n_credible_sets`: credible sets (GWAS signals) where this gene has L2G
  evidence and whose study maps to this trait. Tyk2 × skin disorder: 6, from
  six studies.
- `n_lead_variants`: distinct lead variants among those sets. Same pair: 3,
  because 19_10352442_G_C (rs34536443) leads the set in three studies. Several sets on one
  variant is replication, not several loci.
- `best_cs_*`: fields of the one credible set, among those, where the gene's
  L2G score is highest. L2G is scored per credible set × gene, never per
  variant: `best_cs_l2g_score` says how likely the gene is causal for that
  whole set, and `best_cs_lead_variant` is the set's highest-posterior variant,
  a label for the set, not the thing scored. `best_cs_l2g_rank` and
  `best_cs_l2g_n_genes` give "rank 1 of 1" or "rank 4 of 5";
  `best_cs_l2g_top_gene` names the winner when the rank is not 1.
- `best_cs_beta_alt` and `best_cs_direction_alt`: the lead variant's effect on
  the trait per copy of its alternate allele, sign only for direction.

The IMPC side carries its own direction in `mp_term_name` (increased/decreased
…); the per-call fields (`p_value`, `effect_size`, `sex`, `zygosity`) are not
in this table because one MP term aggregates several calls. Add `impc_calls`
(e.g. `homozygote:female,male`) and `impc_min_p_value` only when the user asks.
Show the mouse and human directions side by side but leave the comparison to
the reader: the GWAS direction is per allele, the IMPC direction is per loss of
the gene, and the two are only comparable when the allele's effect on the gene
is known, which this table does not establish.

`06_detail_impc_call_x_credible_set.csv`, the audit table the main table is
computed from: one row per IMPC call × credible set × trait, unfiltered.

`marker_accession_id, marker_symbol, mp_term_id, mp_term_name, impc_p_value, effect_size, zygosity, sex, hgnc_id, human_symbol, l2g_score, l2g_rank_in_locus, top_l2g_gene_in_locus, study_locus_id, confidence, lead_variant, beta_alt, trait_direction_alt, gwas_study_id, trait_id, trait_label, similarity`

Everything else from the earlier files stays in those files: Ensembl id,
fine-mapping method, alleles, beta SE, study source, free-text trait,
trait-id source. The similarity model is stated once in the README; add a
`similarity_model` column only when two models share one file.

Sort both by `similarity` desc, then L2G desc. A row is only as strong as its
weakest link: a high similarity on an L2G-0.1 set still rests on a weak gene
assignment; show both numbers and let the reader weigh them.

Default the main table to rows where `best_cs_l2g_rank` ≤ 3 **or**
`similarity` ≥ 0.60, state that filter in the README, and keep the detail
table unfiltered (Tyk2: 741 pairs, 4,949 detail rows).

### 7. Mouse disease models (only when the user asks)

Offered, never assumed. After the step 6 table is on screen, ask one
question: *"Want mouse disease models (IMPC/MGI, PhenoDigm) for the top
candidates? Which trait(s)?"* and list the top three or four traits by
similarity as choices. A user who came for the trait mapping can say no and
lose nothing; a user who says yes gets a fourth evidence layer that would
otherwise double the output for everyone.

When they name traits, follow `references/impc-model-search-strategy.md`.
That file owns the search recipe: which MP terms and disease keywords to
propose for each trait, the one confirmation turn with the user, the two
`phenodigm` queries (curated associations unfiltered; predicted associations
filtered on `disease_term` keywords), the ranking by chosen-MP hits then
PhenoDigm score, the chat table, `07_disease_models.csv` and the README hop.
Edit that file, not this section, to change how models are searched.

The reason it is a separate strategy: `type:disease_model_summary` returns
every disease a model's phenotypes resemble (Tyk2: 2,375 rows, 2,366
predicted, top scores for erythroleukemia and MODY). Without a trait-side
constraint the answer is noise, and the right constraint is still being
tuned.

## Output

In the conversation: a short synthesis, then a table of the pairs above the
display cutoff, with the model and the run's score distribution stated once.
Example:

| IMPC phenotype | GWAS trait | Similarity | L2G score (rank, top gene) | Signals | Best set: fine-mapping, lead variant, β | Study |
| --- | --- | ---: | --- | --- | --- | --- |
| abnormal skin morphology (MP:0002060) | skin disorder (MONDO_0005093) | 0.87 | 0.96 (1/2) | 6 sets, 3 lead variants | SuSiE out-of-sample · 19_10352442_G_C · β −0.010 | GCST90475274 |
| abnormal inspiratory capacity (MP:0002311) | respiratory failure (MONDO_0021113) | 0.84 | 0.84 (1/2) | 4 sets, 2 lead variants | PICS top hit · 19_10355447_C_T · β 0.104 | GCST90278684 |
| enlarged spleen (MP:0000691) | sclerosing cholangitis (MONDO_0018646) | 0.78 | 0.09 (4/5, RAVER1) | 1 set, 1 lead variant | PICS top hit · 19_10317045_T_A · no beta in source | GCST005537 |

Rows from the Tyk2 run (model `harrier-oss-v1-27b_pca512`; 741 pairs, min
0.53, median 0.64, max 0.88). Cells are built from the main-table columns:

- "L2G score (rank, top gene)": `best_cs_l2g_score` then, in parentheses,
  `best_cs_l2g_rank`/`best_cs_l2g_n_genes`. When the rank is 1 the gene is the
  top gene and naming it would be redundant, so stop at `0.96 (1/2)`. When the
  rank is above 1, add `best_cs_l2g_top_gene` after a comma, `0.09 (4/5, RAVER1)`,
  so the reader sees at once which gene the locus actually points to.
- "Signals": `n_credible_sets` and `n_lead_variants`.
- "Best set": the fine-mapping short form from `best_cs_confidence`
  (`SuSiE in-sample` / `SuSiE out-of-sample` / `PICS sumstats` /
  `PICS top hit`), then `best_cs_lead_variant` as the Open Targets variant id
  (`chrom_pos_ref_alt`, e.g. `19_10352442_G_C`), then `β` with the signed
  `best_cs_beta_alt` to three decimals, or `no beta in source` when it is empty.
  The variant id already spells out the alleles, and the sign of β already gives
  the direction, so do not add the rsID, "alt C" or the words increase/decrease
  to the cell; they repeat what the id and the sign say. The rsID stays in
  `03_l2g_gwas_links.csv` (`rsids`) for readers who want it.

The synthesis describes what the table shows (which traits, their scores,
which loci carry a strong L2G assignment for the gene) and stops there. It
does not declare pairs matched or unmatched. When no pair reaches the display
cutoff, say that and show the highest few anyway so the reader sees the scale.
End with the step 7 offer (disease models, which traits?) as a question, not
an action; run step 7 only on a yes.

In the result directory:

- the numbered CSVs (CSV by default, JSON only on request, no empty files for
  zero-result hops); `07_disease_models.csv` only when step 7 ran;
- `README.md` following `skills/impc-data-retriever/references/output-report.md`,
  extended so every hop is a numbered query subsection with its service, tool
  or function, exact query or command, and status (`worked` / `zero results` /
  `failed` / `not run`). Non-IMPC hops use `Service:` where IMPC hops use
  `Core:`. Include the process log with rows in and out of each join, the
  similarity model and display cutoff you used, and the limitations: genes without orthologs,
  FinnGen studies, the L2G floor, coarse trait mappings, and any MCP server
  that was down and what replaced it.

## Reverse direction (GWAS trait or study → IMPC)

Same scripts, opposite order:

1. trait → studies: `gwas_catalog_traits.py --efo MONDO_0005306 --child-traits`
   (resolves stale EFO ids first; obsolete ids return 0 rows silently otherwise);
2. studies → L2G genes: `ot_gene_to_gwas.py --study-ids GCST… --out-links …`,
   then filter to rank-1 or L2G ≥ 0.5 genes (two studies gave 562 gene rows);
3. human genes → mouse: `find_orthologs_by_human_genes` (MCP) or
   `orthologs.py --from-csv <links> --id-col human_symbol --human`;
4. mouse genes → `genotype-phenotype` rows, same fields as step 1, with a
   quoted grouped `marker_accession_id:(...)` query in chunks (see step 1 for
   why not `field_list`). Report three groups: genes with significant phenotypes,
   genes phenotyped with no hit, genes not yet phenotyped by the IMPC;
5. similarity of those MP terms against the starting trait.

## Stopping rules and honesty

- A transport failure (MCP timeout, HTTP 5xx, "Query is too expensive") is not
  a zero result. Retry once, then fall back to the script or report the failure.
- Zero IMPC phenotypes, no one-to-one ortholog, or zero credible sets each end
  that gene's branch. Continue the other genes and say which branches stopped.
- Numbers in the synthesis (p-values, L2G, counts of "strong loci") come from
  the written CSVs, read back with pandas, not from memory of the run. Two
  runs misrounded IMPC p-values and one miscounted its own rank-1 loci.
- Similarity, L2G and IMPC significance are three independent pieces of
  evidence. Never collapse them into one score, and never let a high similarity
  imply that the mouse phenotype and the human association share a mechanism.
