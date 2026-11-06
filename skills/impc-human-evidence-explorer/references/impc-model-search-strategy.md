# IMPC model search strategy (step 7)

How the trait mapper picks the MP terms and disease keywords that constrain
the PhenoDigm query for one GWAS trait. Everything tunable lives in this file:
the term count, the keyword rules, the two queries, the ranking and the table.
`SKILL.md` step 7 only says *when* to run it.

Contents: 1 Why constrain · 2 Inputs · 3 Choose MP terms · 4 Derive keywords
· 5 Confirm with the user · 6 The two queries · 7 Rank · 8 Present · 9 Files
and README · 10 Tyk2 worked numbers · 11 Ideas not yet tried

## 1. Why constrain at all

`type:disease_model_summary` in the `phenodigm` core holds one row per mouse
model × human disease. For a gene like Tyk2 that is 2,375 rows: 9 curated
(all Immunodeficiency 35, OMIM:611521) and 2,366 predicted. Predicted rows
score up to 77 for erythroleukemia, MODY and tooth agenesis, because PhenoDigm
scores phenotype-profile similarity, not relevance to any trait. Without a
constraint the answer is a list of every disease the model's phenotypes
resemble.

Two constraints are available in the summary documents:

- `model_matched_phenotypes`: string array, entries like
  `MP:0002060 abnormal skin morphology`. These are the model's own MP
  annotations that contributed to the match. For an IMPC model they *are* the
  IMPC calls from step 1, so filtering on the trait's top MP terms keeps rows
  where the phenotype that scored well against the trait also drove the
  disease match. On its own this is weak: Tyk2 + `MP:0002060*` returns 379
  diseases (asbestos intoxication, choanal atresia), every disease whose HP
  profile maps to that MP.
- `disease_term`: text-searchable disease name. Tyk2 +
  `disease_term:(skin OR psoria* OR eczema OR dermat*)` returns 10 rows, and
  the top three are autoinflammation–panniculitis–dermatosis, generalized
  pustular psoriasis and palmoplantar hyperkeratosis. This is the constraint
  that brings the *trait* into the query.

So: keywords filter the predicted tier, MP terms rank it. ANDing both is too
strict (1 row for Tyk2 × skin disorder).

## 2. Inputs

- `06_impc_gene_to_gwas_trait.csv` from step 6 (main table).
- The trait(s) the user picked, as `trait_id` values from that table.
- `marker_accession_id` per gene from step 1. PhenoDigm summary docs are
  mouse-keyed, so query `marker_id:"MGI:…"` directly; the
  `disease_gene_summary` routing in `impc-data-retriever` is for callers who
  start from a human symbol and is not needed here.

## 3. Choose MP terms

For each chosen trait take the main-table rows with that `trait_id`, dedupe
on `mp_term_id`, sort by `similarity` desc, keep the top **5**. Five is a
ranking budget, not a truth claim: fewer and the "n/k matched" column stops
discriminating, more and low-similarity terms (0.60 "long tibia" for skin
disorder) dilute it. If the user named MP terms in the original request, put
those first regardless of similarity.

Tyk2 × skin disorder gives: abnormal skin morphology 0.86, enlarged spleen
0.69, abnormal spleen morphology 0.68, thrombocytopenia 0.67, abnormal ovary
morphology 0.67.

## 4. Derive keywords

Build 3–6 Solr terms for `disease_term` from, in order:

1. the trait label itself, split into content words, with the generic ones
   dropped (`disorder`, `disease`, `syndrome`, `abnormal`, `measurement`,
   `level`, `increased`, `decreased`);
2. common clinical synonyms and sub-conditions you know for that trait
   (skin disorder → `psoria*`, `eczema`, `dermat*`, `ichthyos*`);
3. stems with `*` where the word inflects (`dermat*` covers dermatitis,
   dermatosis, dermatological).

Do not add words from the MP labels: `spleen` for a skin trait would pull the
haematological diseases straight back in. Keep the list short; every keyword
is an OR branch and recall is not the problem.

## 5. Confirm with the user

Show both lists in one message and ask once:

> For **skin disorder** I will rank models by these IMPC phenotypes:
> abnormal skin morphology (0.86), enlarged spleen (0.69), abnormal spleen
> morphology (0.68), thrombocytopenia (0.67), abnormal ovary morphology (0.67)
> and filter predicted diseases whose name matches: `skin`, `psoria*`,
> `eczema`, `dermat*`. Edit either list, or say go.

One turn. If the user says go, run. If they edit, record the edited lists;
they go into the CSV and README so the run is reproducible.

## 6. The two queries

Both follow `impc-data-retriever` rules for the `phenodigm` core: a `type:`
filter in `q`, the `phenodigm_score` alias in `fl` (never the raw
`disease_model_avg_norm`/`max_norm`), `association_curated` in `fl`,
`validate=True`, and the expected `InvalidFieldWarning` on the alias ignored.
Run them inside one `uv run python - <<'PY'` block with `impc_api.solr_request`.

```python
from impc_api import solr_request

FL = ("disease_id,disease_term,marker_id,marker_symbol,model_id,model_source,"
      "model_description,model_genetic_background,association_curated,"
      "disease_matched_phenotypes,model_matched_phenotypes,"
      "phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)")
SORT = "div(sum(disease_model_avg_norm,disease_model_max_norm),2) desc"

marker_id = "MGI:1929470"
keywords = ["skin", "psoria*", "eczema", "dermat*"]
kw = " OR ".join(keywords)

# Tier A: curated disease-gene associations, unfiltered (usually one disease, a few models)
n_cur, curated = solr_request(core="phenodigm", params={
    "q": f'type:disease_model_summary AND marker_id:"{marker_id}" AND association_curated:true',
    "rows": 200, "fl": FL, "sort": SORT}, validate=True)

# Tier B: predicted associations whose disease name matches the trait keywords
n_pred, predicted = solr_request(core="phenodigm", params={
    "q": f'type:disease_model_summary AND marker_id:"{marker_id}" AND association_curated:false '
         f'AND disease_term:({kw})',
    "rows": 500, "fl": FL, "sort": SORT}, validate=True)
```

Tier A is unfiltered on purpose: the curated disease is what the gene is
*established* for, and the reader should see it even when it has nothing to
do with the trait (Tyk2: Immunodeficiency 35 vs skin disorder). Label
`association_curated` `true` as **Associated (curated)** and `false` as
**Predicted** in prose and tables, keep the boolean in the CSV.

If tier B returns zero rows, say so and show tier A alone. Do not widen the
keywords silently; offer one broader alternative (e.g. `disease_classes` is
not searchable on summary docs, but the user may accept `*skin*`, which for
Tyk2 raises 6 → 36 rows by matching inside longer words).

## 7. Rank

For every row compute `mp_hits`: how many of the chosen MP ids prefix an
entry in `model_matched_phenotypes` (`MP:0002060 abnormal skin morphology`
starts with `MP:0002060`). Sort tier B by `mp_hits` desc, then
`phenodigm_score` desc. Keep one row per `disease_id` for the chat table (the
best model); all rows go to the CSV. Compute `mp_hits` for tier A too, so the
reader sees whether the curated match rests on the same phenotypes as the
GWAS similarity (Tyk2: none of the five skin-disorder terms appear in any
curated row; those matches come from MGI-annotated immune phenotypes).

`phenodigm_score` bands (DR24, from `impc-data-retriever`): high > 40,
intermediate 30–40 around the mean 31.7, low < 30 and still usable in context.
Report the number; use the band word only when the user asks what a score
means.

## 8. Present

After the step 6 table, one short paragraph per trait, then:

| Trait | Disease | Status | Model (source) | PhenoDigm | Chosen MP matched |
| --- | --- | --- | ---: | ---: | --- |
| skin disorder | Immunodeficiency 35 (OMIM:611521) | Associated (curated) | Tyk2<E775K>/Tyk2<E775K> (MGI) | 73.2 | 0/5 |
| skin disorder | Autoinflammation, panniculitis and dermatosis syndrome (OMIM:621030) | Predicted | Tyk2<tm2b(EUCOMM)Hmgu> hom late (IMPC) | 59.9 | 2/5 · enlarged spleen, thrombocytopenia |
| skin disorder | Generalized pustular psoriasis (ORPHA:247353) | Predicted | Tyk2<tm1Shmd>/Tyk2<tm1Shmd> (MGI) | 51.4 | 0/5 |

Curated rows first, then predicted by rank, capped at about eight per trait.
Mark IMPC-produced models: those are the ones with a phenotyping data set the
user can go and download with `impc-data-retriever`. State once that
PhenoDigm scores phenotype-profile similarity between one model and one
disease; it says nothing about the GWAS locus, the L2G assignment or the
allele. This table is a fourth, independent layer next to IMPC significance,
L2G and MP–trait similarity, and is never folded into them.

## 9. Files and README

`07_disease_models.csv`, one row per gene × trait × disease × model, both
tiers:

`marker_accession_id, marker_symbol, trait_id, trait_label, tier, disease_id, disease_term, association_curated, model_id, model_source, model_description, model_genetic_background, phenodigm_score, mp_hits, mp_hit_terms, n_model_matched_phenotypes, n_disease_matched_phenotypes, search_mp_terms, search_keywords`

`search_mp_terms` and `search_keywords` repeat the confirmed lists (`;`
separated) so the row is reproducible without the chat.

README: one hop subsection, `Core: phenodigm`, both queries verbatim, rows in
and out per tier, the confirmed MP and keyword lists, and these limitations:
keyword recall depends on how OMIM/Orphanet name diseases; the MP filter is
model-side only; PhenoDigm similarity is not trait causality; curated
associations may concern a disease unrelated to the chosen trait.

## 10. Tyk2 worked numbers (2026-09, DR24)

| Query | Rows |
| --- | ---: |
| all summary rows, `marker_id:"MGI:1929470"` | 2,375 |
| curated | 9 (1 disease, 3 IMPC + 6 MGI models) |
| predicted ∧ `model_matched_phenotypes:MP\:0002060*` | 379 |
| predicted ∧ `disease_term:(skin OR psoria* OR eczema OR dermat*)` | 10 |
| both | 1 |

## 11. Ideas not yet tried

Kept here so the next person does not re-derive them.

- MONDO → OMIM/Orphanet cross-walk through Open Targets `disease.descendants`
  + `dbXRefs`, intersected with the gene's `disease_id`s. Tested: skin
  disorder → 1,110 ids → 114 Tyk2 diseases, dominated by lipodystrophies via
  the metabolic Tyk2<tm1Shmd> model. Precise on identity, poor on breadth for
  wide traits. Set aside for simplicity.
- `type:disease` carries `disease_classes` (`genetic`, `immunological`, …)
  and `disease_alts` (synonyms). Joining on `disease_id` would let keywords
  hit synonyms too. One extra query per candidate disease.
- Trait-wide search across all genes (`disease_term:(…)` without
  `marker_id`) to find *other* genes' models for the trait. Different
  question; out of scope for a gene-anchored run.
