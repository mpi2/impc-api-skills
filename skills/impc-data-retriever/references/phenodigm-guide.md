In the `phenodigm` core:

1. Fields:
Disease models (`phenodigm`):

```python
fl = "disease_id,disease_source,disease_term,gene_symbol,hgnc_gene_symbol,marker_symbol,mouse_model,model_id,model_source,model_description,impc_model,mp_id,mp_term,hp_id,hp_term,association_curated,association_ortholog,phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)"
```


2. Core-specific rules:
When querying the phenodigm core:
a. ALWAYS include a type filter in "q". Never query phenodigm without a type.
           Valid types and when to use them:
               - type:disease_model_summary  → gene-disease associations
               - type:disease                → disease records
               - type:gene                  → gene records
               - type:gene_gene             → human-mouse gene mapping
               - type:ontology_ontology     → HPO-MP ontology mapping
               - type:ontology              → ontology records
               - type:mouse_model           → mouse model records

           Example: {"q": "type:disease_model_summary AND marker_symbol:Pparg"}

b. PhenoDigm score: Every result-returning `type:disease_model_summary` query
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

c. ASSOCIATION STATUS: Every result-returning `type:disease_model_summary`
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

d. INTERPRETATION: When asked to interpret a score, use a same-core,
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

Disease models:

```python
num_found, df = solr_request(
    core="phenodigm",
    params={
        "q": 'type:disease_model_summary AND disease_term:"Usher syndrome"',
        "rows": 50,
        "fl": "disease_id,disease_term,gene_symbol,marker_symbol,mouse_model,mp_term,association_curated,phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)",
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
