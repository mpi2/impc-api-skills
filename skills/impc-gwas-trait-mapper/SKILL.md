---
name: impc-gwas-trait-mapper
description: >-
  Link IMPC mouse knockout phenotypes to human GWAS traits, in either direction. Given mouse or human genes, an MP phenotype, or a GWAS trait or study, it resolves one-to-one orthologs, retrieves IMPC phenotypes, follows Open Targets locus-to-gene (L2G) evidence through credible sets to GWAS studies, resolves each study's EFO/MONDO/HP/OBA traits from the Open Targets study index and scores every mouse phenotype against every trait with OLS embedding similarity (MP vs EFO). Each human ortholog also gets its Reactome pathways as gene-level context. Use it whenever a user mentions IMPC, mouse knockouts or MP terms together with GWAS, GWAS Catalog, human traits, credible sets, L2G, Open Targets genetics or EFO, or asks whether a mouse phenotype "translates", "matches", "is consistent with" or "supports" a human association, even if they never say "map". Also use it for the reverse question: which IMPC phenotypes or knockout genes support a GWAS trait or study.
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
    ↳ Reactome pathways (experimental)          UniProt + Reactome REST · scripts/reactome_pathways.py
  → L2G evidence → credible set → GWAS study    Open Targets MCP · scripts/ot_gene_to_gwas.py
  → study traits (EFO/MONDO/HP/OBA ids)         Open Targets study index (same script)
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

   Step 2c uses `scripts/reactome_pathways.py` (UniProt and Reactome REST, no
   key) even when a Reactome MCP is loaded: the script writes the CSV and runs
   the mis-map check; the MCP is fine for one-off checks of a gene or pathway.

   Check which tools are actually loaded in this session. When a server is
   missing or times out, use the script and say so in the README; do not stall
   the run to install servers. If the user wants the IMPC orthology server
   installed, invoke `impc-mcp-setup` naming only that server.

## Inputs this skill accepts

- **One or more genes** (mouse symbols or MGI ids, or human symbols),
  optionally with a phenotype focus ("Mtor kidney phenotypes → GWAS",
  "human MTOR → IMPC and GWAS").
- **An MP term**, by id or label ("genes with decreased BUN → human traits"):
  step 1 filters IMPC by that term, then steps 2–6 run for the genes it returns.
- **The reverse:** a GWAS trait (EFO/MONDO/HP id or label) or a GCST study,
  asking which IMPC phenotypes or knockouts support it (see "Reverse
  direction").

Ask when the species is ambiguous (follow the gene-identifier rules in
`impc-data-retriever`), when "top genes" needs a ranking rule the user has not
given, and when an MP term or trait is given by label (next section).
Otherwise choose a sensible default, state it, and proceed.

### Confirm MP terms and traits given by label

Labels are error-prone: near-identical labels carry different ids, and the
top search hit is often not the term meant. A wrong id silently changes every
downstream gene, study and score. So when an MP term or trait is given by
label, search OLS, show the top candidates as a table and ask the user which
id to use before step 1 (MP term) or the reverse search (trait). Wait for the
answer. `references/term-confirmation-guide.md` has the search, the cleaning
rules, the table and examples.

When the user gives an id, look it up once to show its label and check it is
not obsolete; ask only if it is obsolete or its label does not fit what the
user wrote. A GCST study id needs no confirmation. Never type an id from
memory. If the confirmed term returns no IMPC rows or no studies, follow the
stopping rules; do not switch to a parent or child term without asking.

## Workflow

Create a descriptive result directory (e.g. `mtor_impc_to_gwas/`) and number
files in hop order. Keep an attempt log from the first request; the README is
built from it (see Output). Scripts print row counts to stderr; capture them.

### 1. IMPC genes and phenotypes

For human gene input, first resolve the one-to-one mouse ortholog with
`find_orthologs_by_human_genes` or `scripts/orthologs.py --human`, then query
IMPC using the returned MGI id. For mouse gene input, step 2 resolves the human
ortholog for the GWAS lookup.

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

For many genes, do not use
`batch_solr_request` list mode (`field_list`/`field_type`) with `MGI:` ids:
the helper does not quote the values, Solr reads `MGI` as a field name and returns HTTP 400
`undefined field MGI`. Build a quoted grouped query instead, in chunks of
~50: `marker_accession_id:("MGI:1928394" OR "MGI:1347521" ...)`.

### 2. Human orthologs

Use one-to-one orthologs only. A one-to-many family would spread one GWAS
locus over several mouse genes and make the final table unreadable.

- MCP: `find_orthologs_by_mgi_ids` (ids are stable; symbols drift). Max 600 per call.
- Script: `uv run skills/impc-gwas-trait-mapper/scripts/orthologs.py --from-csv 01_impc_phenotypes.csv --id-col marker_accession_id --out 02_orthologs.csv`

Keep `mgiGeneAccId, mouseGeneSymbol, hgncAccId, humanGeneSymbol, supportCount`.
Genes with no one-to-one ortholog stop here; list them under limitations
rather than substituting a paralog. If the user then asks to continue, show
the pairs from `orthologs.py --mgi … --all-relationships` and let them choose;
write only the chosen pairs to `02_orthologs.csv` and label them
non-one-to-one in the README. One mouse gene may keep several human genes
(Slco1b2 → SLCO1B1 and SLCO1B3): the join in step 6 handles each pair
separately, so its phenotypes appear once per human gene.

### 2c. Reactome pathways per human ortholog (experimental)

Experimental: the output format may change and there are no evals for it yet.

For each human ortholog from step 2, its lowest-level Reactome pathways with
reactions involving the gene / reactions in the pathway. The HGNC id from the
IMPC orthology step is turned into the reviewed human UniProt accession, and
Reactome is queried by accession (release 98 resolves no HGNC ids). Read
`references/reactome-guide.md` for the lookup, the mis-map check, ranking and
report table. Then:

```bash
uv run skills/impc-gwas-trait-mapper/scripts/reactome_pathways.py \
  --from-csv 02_orthologs.csv --id-col hgncAccId --symbol-col humanGeneSymbol --out 02_reactome_pathways.csv
```

The output is a table only: no chart and no enrichment test.

Step 2c is gene context: it does not join into the step 6 table, and the skill
does not map phenotypes or traits to pathways. Report the source's own content
and never say a pathway or disease "matches", "explains" or "supports" a
phenotype or trait. The reader judges that.

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

### 4. Trait ids (Open Targets study index)

`04_gwas_traits.csv` from step 3 is the trait table: one row per study ×
ontology id that the Open Targets study index assigns, with
`trait_source = open_targets_study.diseases`. The GWAS Catalog cross-check
that used to run here is archived (`archive/impc-gwas-trait-mapper/gwas-catalog/`);
do not call the GWAS Catalog for trait ids. FinnGen studies keep their Open
Targets ids and are labelled as not in the GWAS Catalog.

Score only the ontology terms Open Targets assigns to each study. Some of
those mappings are coarse at the source (UKB "Impedance of arm" studies map to
`HP_0000924 Abnormality of the skeletal system`): keep
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

By default it applies a **top-20 neighbourhood filter, per ontology**: for each
MP term, OLS returns the term's 20 nearest classes in each of EFO, MONDO, OBA,
HP and GO (up to 100 neighbours; obsolete classes and MONDO's non-human animal
disease branch are dropped). A GWAS trait is kept for that MP term only if it
is among the 20 nearest classes of its own ontology. The trait list plays no
part in choosing the neighbours, so a trait has to beat every class in its
ontology, not just the other traits Open Targets returned. Kept pairs get the
usual `getClassSimilarity` score and are ranked within phenotype and within
trait. `knn_rank` (1–20) is the rank within `knn_ontology`.
`05_…_neighbours.csv` lists every MP term's neighbours with `is_gwas_trait`;
keep it as an output, since it shows what the traits competed against.

K changes how many neighbours each OLS search returns, not how many searches
run: every MP term costs 1 + 5 OLS calls at any K, plus one
`getClassSimilarity` per kept pair. K = 20 was chosen on CYP2C19, AARS1,
Tyk2 + Ldlr and Mtor (37 MP terms, 171 traits): K = 10 kept 15 pairs, K = 20
keeps 25, and the 10 added pairs are of the same kind (enlarged heart ↔ heart
failure, increased circulating sodium ↔ primary aldosteronism). From about
rank 25, unrelated pairs start to appear (increased lean body mass ↔
hypertensive disorder, abnormal spleen morphology ↔ aneurysm), which is why K
stops at 20. Numbers and examples: `references/ols-similarity-guide.md`.

The filter is still strict (CYP2C19: 0 pairs; Mtor: 4 pairs from 3 MP terms × 42 traits). An empty
result is a result: report it, with the neighbours file, and still
run step 6 on it (the join leaves similarity blank and keeps rows on the L2G
rank rule). Change the
filter only when the user asks, and say which option you used: `--top-k N`
(other K), `--top-k-scope pooled` (K slots shared across all ontologies,
stricter: Robinow → 0 at K = 10), or `--top-k 0` (score every pair, no filter). Trait
ids from ontologies outside `--ontologies` cannot pass the filter; the script
warns with a count, and the README should name them. GO is searched by
default because Open Targets maps drug-response studies to GO terms
(CYP2C19: 4 of 17 trait ids); its nearest classes are biological processes,
so a GO trait passes only when it sits close to the MP term's biology. See
`references/ols-similarity-guide.md` for details.

The model is a user choice between two, offered in these terms:

- **precision** — `text-embedding-3-large_pca512` (default). Tighter; the
  model to use when the question is "which single trait is closest to this
  phenotype". It suits the top-20 neighbourhood filter, which asks the same
  question of each ontology.
- **breadth** — `harrier-oss-v1-27b_pca512`. Broader coverage of the
  ontologies and more scores; the model to use when looking for "deep cuts",
  i.e. traits a narrower model would leave near the floor. Too broad for the
  top-20 filter: its nearest classes crowd out the GWAS traits.

If the user does not say, use precision and state that. If they name a model,
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

Selection rule: with the top-20 filter on (the default), the filter is the
quality cut, so the user-facing table shows every scored pair, ranked, capped
at the top 10 (see Output). No similarity cutoff is applied on top: in the
filtered runs so far (AARS1, Cyp2c38 + Cyp2d22 + Slco1b2: 7 pairs) every pair
that passed scored ≥ 0.76, so a 0.60 cutoff removed nothing and only suggested
a second, uncalibrated threshold. A pair that passes with a low score is still
shown; its number sits next to it. State the
filter (K, scope, ontologies) as the selection rule. Only with `--top-k 0`
(every pair scored, no filter) apply a display cutoff of similarity ≥ 0.60,
because then it is what keeps volume down (Tyk2 + Ldlr: 513 of 2,400 pairs
below 0.60), and state it as a display choice. The full table is in
`05_…similarity.csv`. Use whatever cutoff, K or row count the user asks for.

If the trait list is long, restrict it before scoring, typically to traits from
credible sets where the gene ranks top-3 by L2G, and say which filter you used.

### 6. Join and rank

```bash
uv run skills/impc-gwas-trait-mapper/scripts/join_gene_trait.py --phenotypes 01_impc_phenotypes.csv \
  --orthologs 02_orthologs.csv --links 03_l2g_gwas_links.csv --traits 04_gwas_traits.csv \
  --similarity 05_phenotype_trait_similarity.csv \
  --out 06_impc_gene_to_gwas_trait.csv --detail-out 06_detail_impc_call_x_credible_set.csv
```

Do not rebuild the join by hand: the script joins each IMPC call only to its
own gene's credible sets, breaks L2G ties at the best set by
`study_locus_id` (so reruns give the same row), copies values as written
(pandas rewrites float digits), and names on stderr every gene whose branch
stopped (no ortholog, no credible sets) and any row without a similarity.
`--max-rank` and `--min-similarity` change the main-table filter (by default
`--min-similarity` follows step 5: any score with the top-K filter, 0.60 with
`--top-k 0`); `--model`
keeps one model when step 5 scored several, otherwise rows repeat per model
with a `similarity_model` column.

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

The main table defaults to rows where `best_cs_l2g_rank` ≤ 3 **or** the pair
has a similarity score (it passed the top-K filter); with `--top-k 0` the
second condition becomes `similarity` ≥ 0.60. The script prints the rule it
used on stderr; state that filter in the README. The detail table is unfiltered (Tyk2 + Ldlr: 1,113 pairs, 8,560
detail rows).

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

In the conversation: a short synthesis, then a table of the top 10 scored
pairs (with `--top-k 0`: the top 10 at or above the 0.60 display cutoff), in
the main table's sort order (`similarity` desc, then L2G desc), with the model
and the run's score distribution stated once. An unfiltered run can put
hundreds of pairs above the cutoff (Pnpt1: 216 of 288);
printing them all fills the conversation and the README with rows the CSV
already holds, and the reader only needs the headline to decide where to look
next. Follow the table with one line saying how many rows are shown and where
the rest are, e.g. "Top 10 of 25 scored pairs (top-20 filter). Full table:
`06_impc_gene_to_gwas_trait.csv` (288 rows), loadable with `pandas.read_csv`."
(with `--top-k 0`: "Top 10 of 216 pairs with similarity ≥ 0.60 …"). When 10
or fewer pairs qualify, show them all and drop the "top 10" wording. Show more rows only when the user asks for them. Example:

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

After that line, the Reactome pathway table in the format given in
`references/reactome-guide.md` ("Report table").

The synthesis describes what the table shows (which traits, their scores,
which loci carry a strong L2G assignment for the gene) and stops there. It
does not declare pairs matched or unmatched. When no pair passes the filter
(or, with `--top-k 0`, reaches the cutoff), say that and point to the
neighbours file (or show the highest few pairs) so the reader sees the scale.
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
  similarity model and selection rule (filter, or cutoff with `--top-k 0`) you used, and the limitations: genes without orthologs,
  FinnGen studies, the L2G floor, coarse trait mappings, and any MCP server
  that was down and what replaced it.
  The `## Result summary` section always contains the same results table shown
  in the conversation: same columns, same selection rule, same top-10 cap and
  the same "Top 10 of N pairs … Full table: …" line after it. The README is
  read back into context by people and agents, so the cap matters there as
  much as in the chat. Precede the table with the model, the run's min /
  median / max and the selection rule with the count of pairs it keeps. Generate the
  table rows with pandas from `06_impc_gene_to_gwas_trait.csv`, not by copying
  the chat table, and fill every cell (no "same as above"). When no pair
  qualifies, say so (and with `--top-k 0` include the highest few rows). Follow it with
  the same Reactome pathway table, generated with pandas from its CSV, and the
  README notes from `references/reactome-guide.md`.

## Reverse direction (GWAS trait or study → IMPC)

Same scripts, opposite order:

1. trait → studies → L2G genes: confirm the trait id first (see "Confirm MP
   terms and traits given by label"), then
   `ot_gene_to_gwas.py --disease-ids MONDO_0005306 --out-links … --out-traits …`.
   It takes the GWAS studies Open Targets maps to that id or its descendants
   (`studies(diseaseIds:, enableIndirect: true)`; ankylosing spondylitis: 41
   studies, 555 credible sets, 1,194 L2G gene rows) and includes pleiotropy
   studies that list the trait among several, so say which those are. For a
   known study use `--study-ids GCST…` instead;
2. filter to rank-1 or L2G ≥ 0.5 genes;
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
