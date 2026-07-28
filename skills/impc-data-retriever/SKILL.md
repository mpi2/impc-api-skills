---
name: impc-data-retriever
description: "You MUST use this when the user requests data retrieval from the IMPC."
---

# IMPC Data Retrieval
## Purpose

Retrieve data from the International Mouse Phenotyping Consortium (IMPC) using the `impc-api` Python package.

This skill translates a user's request into the right `impc-api` Solr query and returns the requested data in a convenient format.

## When to use

Use this skill whenever a user wants to download or analyse IMPC data, for example:

- raw phenotype observations
- statistical results and significance calls
- genotype-phenotype associations
- genes, alleles, colonies, procedures, parameters or centres
- image records and download links
- disease models
- ontology-linked statistical results

Typical requests include:

- "Download Open Field data."
- "Get all phenotypes for Pax6."
- "Retrieve all significant genotype-phenotype associations."
- "Download IMPC data for procedure IMPC_OFD_001."
- "Get all parameters from the Clinical Chemistry pipeline."
- "Export results as a pandas DataFrame."

## Input

Accept natural language describing the required data.

If essential information is missing, ask concise follow-up questions.

Examples:

- Which gene?
- Which procedure?
- Which parameter?
- Which life stage?
- Do you want raw observations or statistical results?
- Should the data be returned as a DataFrame, CSV or JSON?

## Behaviour

1. Import the package API.

```python
from impc_api import solr_request, batch_solr_request
```

2. Choose the Solr core.

| User wants | Use core | Notes |
| --- | --- | --- |
| Raw observations, controls, metadata, weights, specimen-level rows | `experiment` | Use for observed data points. Filter with `biological_sample_group:experimental` or `biological_sample_group:control` when needed. |
| Phenotype associations by gene, MP term, procedure, parameter or p-value | `genotype-phenotype` | Best concise gene-to-phenotype summary. |
| Statistical model output, significant calls, sex-specific effects, counts and p-values | `statistical-result` | Best for `significant:true`, `mp_term_id_options`, effect sizes, model methods and procedure-level statistics. |
| Images or media links | `impc_images` | Return `download_url`, `jpeg_url`, `thumbnail_url`, `omero_id` where useful. |
| Disease models and Phenodigm matches | `phenodigm` | Include `type:...` in `q`, for example `type:disease_model_summary`. |

3. Identify filters.

Common filters:

- identifiers: `marker_symbol`, `gene_symbol`, `marker_accession_id`, `allele_accession_id`, `allele_symbol`, `colony_id`, `specimen_id`, `observation_id`
- assay metadata: `pipeline_stable_id`, `procedure_stable_id`, `procedure_name`, `parameter_stable_id`, `parameter_name`
- study design: `phenotyping_center`, `production_center`, `life_stage_name`, `sex`, `zygosity`, `biological_sample_group`
- ontology/statistics: `mp_term_id`, `mp_term_name`, `mp_term_id_options`, `top_level_mp_term_name`, `p_value`, `effect_size`, `statistical_method`, `significant`
- anatomy/images: `anatomy_term`, `top_level_anatomy_term`, `download_url`, `image_link`, `file_type`

4. Build `params` with Solr syntax.

- `q`: required query string. Use exact stable IDs where possible.
- `fl`: comma-separated fields to return. Keep it narrow for performance.
- `rows`: row count for `solr_request`; use `rows: 0` for counts/facets.
- `start`: offset for manual pagination.
- `sort`: for example `p_value asc` or `marker_symbol asc`.
- `facet`, `facet.field`, `facet.limit`, `facet.mincount`: counts by centre, method, sex, zygosity, procedure, parameter, etc.
- `wt`: `json` or `csv` for `batch_solr_request(download=True)`.

5. Use the right function.

- Use `solr_request(..., validate=True)` for small queries, previews, counts, facets and URL generation.
- Use `batch_solr_request(...)` for large result sets, list queries and downloads.
- Use `url_only=True` when the user wants a shareable Solr URL.

6. Return or save the result in the requested format.

## Output

Prefer returning a pandas DataFrame.

If requested, save results as CSV or JSON with `batch_solr_request(download=True)`.

`batch_solr_request(download=True)` supports only `wt="json"` and `wt="csv"`. For Parquet or Excel, first retrieve a DataFrame or CSV, then convert with pandas only if the data size is reasonable.

## Fields

Use these field sets as defaults, then add or remove fields to match the request.

Raw observations (`experiment`):

```python
fl = "experiment_id,specimen_id,observation_id,biological_sample_group,pipeline_stable_id,procedure_stable_id,procedure_name,phenotyping_center,production_center,external_sample_id,strain_name,sex,zygosity,date_of_birth,date_of_experiment,age_in_weeks,life_stage_name,gene_symbol,allele_symbol,allele_accession_id,colony_id,parameter_stable_id,parameter_name,data_point,observation_type,metadata_group,metadata,weight,weight_date,weight_days_old,weight_parameter_stable_id"
```

Genotype-phenotype summaries (`genotype-phenotype`):

```python
fl = "marker_symbol,marker_accession_id,allele_symbol,allele_accession_id,colony_id,mp_term_id,mp_term_name,top_level_mp_term_name,procedure_name,procedure_stable_id,parameter_name,parameter_stable_id,p_value,effect_size,percentage_change,statistical_method,sex,zygosity,life_stage_name,phenotyping_center,pipeline_stable_id"
```

Statistical results (`statistical-result`):

```python
fl = "marker_symbol,allele_symbol,allele_accession_id,colony_id,procedure_name,procedure_stable_id,parameter_name,parameter_stable_id,statistical_method,significant,p_value,effect_size,mp_term_id,mp_term_name,mp_term_id_options,top_level_mp_term_name,sex,zygosity,phenotype_sex,life_stage_name,phenotyping_center,pipeline_stable_id,male_ko_effect_p_value,female_ko_effect_p_value,genotype_effect_p_value,weight_effect_p_value,weight_effect_parameter_estimate,male_mutant_count,female_mutant_count,male_control_count,female_control_count"
```

Images (`impc_images`):

```python
fl = "gene_symbol,allele_symbol,allele_accession_id,colony_id,procedure_name,procedure_stable_id,parameter_name,parameter_stable_id,sex,zygosity,life_stage_name,phenotyping_center,download_url,jpeg_url,thumbnail_url,omero_id,file_type"
```

Disease models (`phenodigm`):

```python
fl = "type,disease_id,disease_source,disease_term,gene_symbol,hgnc_gene_symbol,marker_symbol,mouse_model,model_id,model_source,model_description,impc_model,mp_id,mp_term,hp_id,hp_term,disease_model_avg_norm,disease_model_max_norm,association_curated,association_ortholog"
```

## Query patterns

Use exact stable identifiers when available. Quote values containing spaces. Combine clauses with `AND` and grouped `OR`.

Gene to phenotypes:

```python
num_found, df = solr_request(
    core="genotype-phenotype",
    params={
        "q": "marker_symbol:Brca2",
        "rows": 100,
        "fl": "marker_symbol,allele_symbol,mp_term_name,top_level_mp_term_name,p_value,zygosity,sex",
        "sort": "p_value asc",
    },
    validate=True,
)
```

Phenotype or MP term to genes:

```python
num_found, df = solr_request(
    core="genotype-phenotype",
    params={
        "q": 'mp_term_name:"abnormal bone mineral density"',
        "rows": 50,
        "fl": "marker_symbol,allele_symbol,mp_term_id,mp_term_name,p_value,zygosity",
        "sort": "p_value asc",
    },
    validate=True,
)
```

Significant statistical results:

```python
num_found, df = solr_request(
    core="statistical-result",
    params={
        "q": "marker_symbol:Dclk1 AND significant:true",
        "rows": 100,
        "fl": "marker_symbol,parameter_name,procedure_name,top_level_mp_term_name,effect_size,p_value,zygosity,statistical_method",
        "sort": "p_value asc",
    },
    validate=True,
)
```

Raw observations by procedure, parameter, centre, colony or sample group:

```python
df = batch_solr_request(
    core="experiment",
    params={
        "q": 'procedure_stable_id:*OFD* AND life_stage_name:"Late adult" AND biological_sample_group:experimental',
        "fl": "observation_id,specimen_id,gene_symbol,allele_symbol,colony_id,sex,zygosity,phenotyping_center,parameter_stable_id,parameter_name,data_point,metadata,weight,life_stage_name",
    },
    batch_size=10000,
)
```

Controls for the same assay:

```python
df = batch_solr_request(
    core="experiment",
    params={
        "q": 'procedure_stable_id:*OFD* AND biological_sample_group:control',
        "fl": "observation_id,specimen_id,sex,zygosity,phenotyping_center,parameter_stable_id,parameter_name,data_point,metadata,weight,life_stage_name",
    },
    batch_size=10000,
)
```

Multiple genes, alleles, parameters or colonies:

```python
df = batch_solr_request(
    core="genotype-phenotype",
    params={
        "q": "*:*",
        "fl": "marker_symbol,mp_term_name,p_value,zygosity",
        "field_list": ["Brca2", "Trp53", "Pten"],
        "field_type": "marker_symbol",
    },
)
```

Facets for discovery:

```python
num_found, df = solr_request(
    core="experiment",
    params={
        "q": 'procedure_stable_id:*OFD* AND life_stage_name:"Late adult"',
        "rows": 0,
        "facet": "on",
        "facet.field": "phenotyping_center",
        "facet.limit": 50,
        "facet.mincount": 1,
    },
    silent=True,
)
```

Images:

```python
num_found, df = solr_request(
    core="impc_images",
    params={
        "q": "gene_symbol:Akt2",
        "rows": 20,
        "fl": "gene_symbol,parameter_name,procedure_name,download_url,jpeg_url,thumbnail_url",
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
        "fl": "disease_id,disease_term,gene_symbol,marker_symbol,mouse_model,mp_term,disease_model_avg_norm,disease_model_max_norm",
    },
    validate=True,
)
```

MP ontology-linked statistical results:

```python
df = batch_solr_request(
    core="statistical-result",
    params={
        "q": 'mp_term_id_options:"MP:0004738" OR mp_term_id_options:"MP:0011967"',
        "fl": "marker_symbol,allele_symbol,colony_id,mp_term_id_options,parameter_stable_id,significant,p_value,pipeline_stable_id",
    },
)
```

The working-group repository sometimes used `core="mp"` to expand MP descendants. This core is not in the current package validation list. Use it only when the user explicitly needs ontology expansion; call `solr_request(core="mp", ..., validate=False)` or use another ontology source, then query `statistical-result` with `mp_term_id_options`.

## Examples
Example 1

User

Download Open Field data.

Use `experiment` for raw data. Start with a facet or count if the user has not specified life stage, sample group or centre; otherwise use `batch_solr_request` with `procedure_stable_id:*OFD*`.

Example 2

User

Get all data for Trp53.

Ask whether they want summaries or raw observations. If they say all, retrieve `genotype-phenotype`, `statistical-result`, `experiment`, and `impc_images` separately with gene fields appropriate to each core (`marker_symbol` for summaries/statistics, `gene_symbol` for observations/images).

Example 3

User

Download all significant genotype-phenotype associations.

Use `statistical-result` with `q: "significant:true"` when the user asks for significant calls. Use `genotype-phenotype` with `p_value` ranges when the user asks for association summaries.

Example 4

User

Export Clinical Chemistry parameters as CSV.

If the user needs observed data, use `experiment` with the Clinical Chemistry procedure or parameter stable IDs and `batch_solr_request(download=True, wt="csv")`. If they need parameter metadata only, facet `experiment` by `parameter_stable_id` or query a small field list of `procedure_name,procedure_stable_id,parameter_name,parameter_stable_id,pipeline_stable_id`.

Example 5

User

Compare late adult and early adult activity data for centres with late adult OFD.

Facet `experiment` by `phenotyping_center` for late adult OFD, build a grouped centre query, retrieve late/middle adult experimental rows, then retrieve early adult rows for the same `allele_accession_id` values. Retrieve controls separately with `biological_sample_group:control`.

## Guidelines
- Prefer `solr_request` and `batch_solr_request` rather than manually constructing Solr URLs.
- Use `validate=True` for normal queries against validated cores.
- Use `fl` aggressively; do not retrieve all fields unless the user asks for all fields.
- Use facets to discover available centres, procedures, parameters, methods, sex or zygosity before large downloads.
- Use exact stable IDs over names. Prefer `procedure_stable_id`, `parameter_stable_id`, `mp_term_id`, `allele_accession_id`.
- Preserve original IMPC identifiers.
- Return informative error messages if no matching data are found.
- If multiple datasets match the request, explain the options and ask the user to choose.
- For very large downloads, use `batch_solr_request(download=True, wt="csv" or "json")`; warn that reading the downloaded file into memory may still fail.
- For metadata columns that contain lists like `"key = value"`, expand them after retrieval only if the user asks for analysis-ready columns.
- Do not infer biological annotations beyond what IMPC returns.

## Error handling
If the request is ambiguous:

- identify the ambiguity;
- ask only the minimum number of clarification questions needed to retrieve the correct data.

If no data exist:

- explain that no matching IMPC data were found;
- suggest nearby entities if appropriate.

If a field or core warning appears with `validate=True`, check the current package field schema and correct spelling. If the query intentionally uses a legacy/unvalidated core such as `mp`, rerun without validation and explain the limitation.

## Notes
- Always use the installed `impc-api` package rather than calling IMPC REST endpoints directly, unless the package does not support the requested functionality.
- Current validated Solr cores in the package are `experiment`, `genotype-phenotype`, `impc_images`, `phenodigm`, and `statistical-result`.
- `batch_solr_request` ignores `params["rows"]`; set `batch_size` instead.
- `batch_solr_request` mutates the `params` dictionary by setting `start`, `rows`, `wt`, and sometimes `fq`; pass a copy if reusing params.
- Parameter units and IMPReSS schedule timepoints are not exposed as first-class helpers in `impc-api`; only call IMPReSS REST endpoints directly when the user explicitly needs those metadata.
- Preserve IMPC stable identifiers exactly as returned by the API.
- When possible, return data as a pandas DataFrame to facilitate downstream analysis.
