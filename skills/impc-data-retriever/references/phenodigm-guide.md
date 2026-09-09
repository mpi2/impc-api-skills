In the `phenodigm` core:

1. Fields:

Disease-model scores (`type:disease_model_summary`):

```python
fl = "disease_id,disease_term,marker_id,marker_symbol,model_id,model_source,model_description,model_genetic_background,association_curated,disease_matched_phenotypes,model_matched_phenotypes,phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)"
```

Gene identifier resolution with the human-mouse mapping
(`type:disease_gene_summary`; routing only):

```python
fl = "marker_id,marker_symbol,hgnc_gene_id,hgnc_gene_symbol"
```

Although these documents also contain disease fields, do not request, return,
or interpret those fields as disease results. Retrieve disease information from
`type:disease_model_summary`.

Fallback gene identifier resolution and direct ortholog mapping:

```python
gene_fl = "gene_id,gene_symbol,hgnc_gene_id,hgnc_gene_symbol"
gene_gene_fl = "gene_id,hgnc_gene_id"
```


2. Core-specific rules:
When querying the phenodigm core:
a. ALWAYS include a type filter in "q". Never query phenodigm without a type.
           Valid types and when to use them:
               - type:disease_model_summary  → mouse model-disease matches and scores
               - type:disease_gene_summary   → routing-only human-mouse gene identifier resolution
               - type:disease                → disease records
               - type:gene                  → gene records
               - type:gene_gene             → human-mouse gene mapping
               - type:ontology_ontology     → HPO-MP ontology mapping
               - type:ontology              → ontology records
               - type:mouse_model           → mouse model records

           Example: {"q": "type:disease_model_summary AND marker_symbol:Pparg"}

b. GENE SPECIES AND LOOKUP ROUTING:

   `type:disease_model_summary` is mouse-keyed. Query it with `marker_id` or
   `marker_symbol`, not `hgnc_gene_id` or `hgnc_gene_symbol`.

   Respect a species named by the user. When species is not stated,
   conventional capitalization can guide routing (`Pparg` for mouse and
   `PPARG` for human), but it is not a substitute for a stable identifier. If
   unsure whether the user means a human or mouse gene, ask the user to clarify
   the species before making any gene query. Do not guess from capitalization
   alone or silently rewrite a human symbol as a mouse symbol.

   IDENTIFIER-RESOLUTION ONLY: Always start an ortholog lookup with
   `type:disease_gene_summary`. Query it with the user's human or mouse gene
   identifier (`hgnc_gene_symbol`, `hgnc_gene_id`, `marker_symbol`, or
   `marker_id`, as appropriate) and use only its human and mouse gene identifier
   fields. Do not use, return, or interpret its `disease_id`, `disease_term`, or
   association fields as disease results, even though those fields may be
   present in the documents.

   For a pure ortholog request, the resolved gene identifiers answer the
   question. For any request about diseases, disease models, association
   status, or scores, always query `type:disease_model_summary` after resolving
   the distinct mouse `marker_id` values. All disease-facing output must come
   from `type:disease_model_summary`, with the requested
   associated/predicted/all scope applied there.

   Solr can return repeated `type:disease_gene_summary` documents for the same
   ortholog mapping. Before using the result, select the identifier fields and
   deduplicate by the stable human-mouse pair (`hgnc_gene_id`, `marker_id`). If
   one distinct pair remains, keep that one row and make only one downstream
   `type:disease_model_summary` query. Repeated rows are not multiple orthologs.
   If multiple distinct `marker_id` values remain after deduplication, do not
   discard them as duplicates; treat them as distinct mappings and query or
   report each one as appropriate.

   Only when `type:disease_gene_summary` returns zero records, use the fallback
   route: query `type:gene` to resolve the gene and its stable identifiers,
   then query `type:gene_gene` to obtain the ortholog mapping. Use each returned
   mouse `gene_id` as `marker_id` in a `type:disease_model_summary` query.

   Interpret fallback outcomes precisely:

   - If `type:gene` or `type:gene_gene` returns no record, do not claim that an
     ortholog exists.
   - If both return records but `type:disease_model_summary` returns no data,
     the gene exists and has a mouse ortholog, but PhenoDigm has no associated
     or predicted disease records for that ortholog. Do not report this as
     "no ortholog found."

c. PhenoDigm score: Every result-returning `type:disease_model_summary` query
    MUST ask Solr to calculate and return the combined PhenoDigm score. Include
    this exact field alias in `fl`:

    phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)

    Never store or return `disease_model_avg_norm` or
    `disease_model_max_norm` directly unless the user explicitly requests the
    component scores for debugging or analysis. The expression can also be
    used in a `sort` parameter.

    Example sort: "sort": "div(sum(disease_model_avg_norm,disease_model_max_norm),2) desc"

    `impc-api` may emit `InvalidFieldWarning` for this valid Solr
    pseudo-field because its validator splits `fl` on every comma. Warnings
    caused by the exact alias above are expected and do not justify removing
    the derived score. Investigate all other validation warnings normally.

d. ASSOCIATION STATUS: Every result-returning `type:disease_model_summary`
   query MUST include `association_curated` in `fl`. This boolean describes the
   disease–human ortholog gene association; it does not describe whether the
   mouse model or PhenoDigm score was manually curated:

   - `association_curated:true`: the disease–gene association is curated.
     Use this filter when the user asks for associated, curated, or established
     disease–gene associations. These results are useful for finding mouse
     models for diseases already associated with the human ortholog gene.
   - `association_curated:false`: the disease–gene association is predicted.
     Use this filter when the user asks for predicted or candidate associations.
     These results are useful for disease–gene discovery.
   - To retrieve all associations, omit the `association_curated` filter but
     still return the field so every result can be labelled as curated or
     predicted.

   In user-facing results, label `true` as **Associated (curated)** and `false`
   as **Predicted**. Retain the original boolean field in tables and downloads.

   If the user asks broadly for diseases or disease models for a gene without
   specifying associated, predicted, or all, do not silently choose a category.
   Explain the distinction and ask which of the three they want. If they are
   unsure, offer curated associations for established disease modelling,
   predicted associations for disease–gene discovery, or all for an inclusive
   search.

e. INTERPRETATION: When asked to interpret a score, use a same-core,
   multi-request workflow within `phenodigm`:

   1. Retrieve the selected `type:disease_model_summary` record with
      `disease_id`, `model_id`, `association_curated`, the derived `phenodigm_score`,
      `disease_matched_phenotypes`, and `model_matched_phenotypes`.
   2. Query `type:disease` by the returned `disease_id` and retrieve
      `disease_phenotypes`, the complete human disease phenotype profile.
   3. Query `type:mouse_model` by the returned `model_id` and retrieve
      `model_phenotypes`, the complete phenotype profile for that exact model.

   Join the three results only by the exact returned `disease_id` and
   `model_id`. Do not use `genotype-phenotype` to reconstruct the PhenoDigm
   input profiles: it has mouse MP associations but no human disease phenotype
   profile and may differ from the model and data snapshot used for the score.
   Follow the
   [PhenoDigm score interpretation guidelines](phenodigm-score-interpretation.md)
   when presenting the result.

3. Query patterns:

Preferred human symbol to mouse gene identifier resolution (routing only):

```python
num_found, routing_df = solr_request(
    core="phenodigm",
    params={
        "q": "type:disease_gene_summary AND hgnc_gene_symbol:PPARG",
        "rows": 50,
        "fl": "marker_id,marker_symbol,hgnc_gene_id,hgnc_gene_symbol",
    },
    validate=True,
)

orthologs = routing_df[
    ["marker_id", "marker_symbol", "hgnc_gene_id", "hgnc_gene_symbol"]
].drop_duplicates(subset=["hgnc_gene_id", "marker_id"])
```

When `num_found` is greater than zero, use only the returned gene identifiers;
do not also query `type:gene` or `type:gene_gene` merely to rediscover the
ortholog. If disease information is requested, use the distinct returned
`marker_id` values in a separate `type:disease_model_summary` query. The usual
single-ortholog case therefore produces one downstream query even when Solr
returned many repeated routing documents.

Fallback after a zero-result `type:disease_gene_summary` query:

```python
_, human_gene_df = solr_request(
    core="phenodigm",
    params={
        "q": "type:gene AND hgnc_gene_symbol:PPARG",
        "rows": 10,
        "fl": "hgnc_gene_id,hgnc_gene_symbol",
    },
    validate=True,
)

hgnc_gene_id = human_gene_df.iloc[0]["hgnc_gene_id"]
_, ortholog_df = solr_request(
    core="phenodigm",
    params={
        "q": f'type:gene_gene AND hgnc_gene_id:"{hgnc_gene_id}"',
        "rows": 10,
        "fl": "gene_id,hgnc_gene_id",
    },
    validate=True,
)

ortholog_df = ortholog_df[["gene_id", "hgnc_gene_id"]].drop_duplicates(
    subset=["hgnc_gene_id", "gene_id"]
)
# This example assumes one distinct mapping remains. If several remain, query
# every distinct gene_id rather than silently selecting only the first.
marker_id = ortholog_df.iloc[0]["gene_id"]
num_found, model_df = solr_request(
    core="phenodigm",
    params={
        "q": f'type:disease_model_summary AND marker_id:"{marker_id}"',
        "rows": 50,
        "fl": "disease_id,disease_term,marker_id,marker_symbol,model_id,model_description,association_curated,phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)",
    },
    validate=True,
)
```

If the `type:gene` and `type:gene_gene` lookups succeed but `num_found` is zero
for `type:disease_model_summary`, report that the gene and its mouse ortholog
exist but no associated or predicted diseases are present in PhenoDigm.

Disease-model lookup after identifier resolution when a disease is supplied:

```python
_, routing_df = solr_request(
    core="phenodigm",
    params={
        "q": "type:disease_gene_summary AND hgnc_gene_symbol:PPARG",
        "rows": 10,
        "fl": "marker_id,marker_symbol,hgnc_gene_id,hgnc_gene_symbol",
    },
    validate=True,
)

orthologs = routing_df[
    ["marker_id", "marker_symbol", "hgnc_gene_id", "hgnc_gene_symbol"]
].drop_duplicates(subset=["hgnc_gene_id", "marker_id"])
# This example assumes one distinct mapping remains. If several remain, query
# every distinct marker_id rather than silently selecting only the first.
marker_id = orthologs.iloc[0]["marker_id"]
disease_id = "OMIM:125853"
_, model_df = solr_request(
    core="phenodigm",
    params={
        "q": f'type:disease_model_summary AND marker_id:"{marker_id}" AND disease_id:"{disease_id}"',
        "rows": 50,
        "fl": "disease_id,disease_term,marker_id,marker_symbol,model_id,model_description,association_curated,phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)",
    },
    validate=True,
)
```

Disease models:

```python
num_found, df = solr_request(
    core="phenodigm",
    params={
        "q": 'type:disease_model_summary AND disease_term:"Usher syndrome"',
        "rows": 50,
        "fl": "disease_id,disease_term,marker_id,marker_symbol,model_id,model_description,association_curated,phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)",
    },
    validate=True,
)
```

Disease-model score interpretation data:

```python
# Start with one selected disease-model summary record. For multiple records,
# repeat the two typed profile lookups for each unique disease_id and model_id.
num_found, summary_df = solr_request(
    core="phenodigm",
    params={
        "q": 'type:disease_model_summary AND disease_id:"OMIM:105400" AND marker_symbol:Sod1',
        "rows": 10,
        "fl": "disease_id,disease_term,model_id,model_description,association_curated,disease_matched_phenotypes,model_matched_phenotypes,phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)",
    },
    validate=True,
)

selected = summary_df.iloc[0]
disease_id = selected["disease_id"]
model_id = selected["model_id"]

_, disease_df = solr_request(
    core="phenodigm",
    params={
        "q": f'type:disease AND disease_id:"{disease_id}"',
        "rows": 1,
        "fl": "disease_id,disease_term,disease_phenotypes",
    },
    validate=True,
)

_, model_df = solr_request(
    core="phenodigm",
    params={
        "q": f'type:mouse_model AND model_id:"{model_id}"',
        "rows": 1,
        "fl": "model_id,model_source,model_description,model_phenotypes",
    },
    validate=True,
)
```

Disease models with sorted phenodigm score:

``` python
num_found, df = solr_request(
    core="phenodigm",
    params={
        "q": "type:disease_model_summary AND marker_symbol:Pparg",
        "rows": 10,
        "fl": "marker_symbol,disease_term,association_curated,phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)",
        "sort": "div(sum(disease_model_avg_norm,disease_model_max_norm),2) desc"
    },
    validate=True,
)
```
