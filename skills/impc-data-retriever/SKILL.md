---
name: impc-data-retriever
description: "You MUST use this when the user requests data retrieval from the IMPC."
---

# IMPC Data Retrieval
## Prerequisites
1. `uv`: Read the `uv` skill and follow its setup instructions to ensure proper configuration.  
2. All Python commands for this skill must run
through the local uv project:

```bash
uv run python - <<'PY'
# retrieval code
PY
```

Do not assume that `pyproject.toml`, `uv.lock`, or `.venv` ship with the skill.
Before the first query, verify that `uv run python -c "import impc_api"`
succeeds. If it does not, initialize the current working directory only when it
does not already contain `pyproject.toml`, then add the dependency:

```bash
uv init --bare       # only when pyproject.toml is absent
uv add 'impc-api>=1.0.7'
```

These commands create or update the user's local `pyproject.toml`, `uv.lock`,
and `.venv`. Subsequent `uv run` commands reuse that environment and uv's
normal cache. Do not use `--no-cache` or reinstall the dependency for every
query. Keep retrieval, post-processing, and README generation in one `uv run`
invocation where practical.

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

2. Understand the function contracts.

Both functions take:

- `core` (`str`): the Solr core to query.
- `params` (`dict`): Solr query parameters. For normal queries, include `q`; use `"*:*"` for all records or `"field:value"` for a specific match. `fl` is optional, but should normally be set to a narrow comma-separated field list for performance.

For `solr_request`:

- Set `params["rows"]` to control the number of returned documents; use `rows: 0` for counts or facets.
- Other useful `params` entries include `start`, `sort`, `facet`, `facet.field`, `facet.limit`, and `facet.mincount`.
- Pass function options such as `validate=True`, `silent=True`, `url_only=True`, or `timeout=<seconds>` separately from `params`.
- A normal request returns `(num_found, dataframe)`. With `url_only=True`, it returns `(url, None)`.

For `batch_solr_request`:

- Set the function argument `batch_size` to control page size. Do not use `params["rows"]`; the function overrides it while batching.
- For a file download, pass `download=True` and `filename=<name>` to the function. Set `params["wt"]` to `"csv"` or `"json"`; `wt` is not a function argument.
- For list queries, put `field_list` and `field_type` in `params`.
- The function returns a DataFrame and, with `download=True`, also writes the requested file.

3. Choose the Solr core.

| User wants | Use core | Notes |
| --- | --- | --- |
| Raw observations, controls, metadata, weights, specimen-level rows | `experiment` | Use for observed data points. Filter with `biological_sample_group:experimental` or `biological_sample_group:control` when needed. |
| Phenotype associations by gene, MP term, procedure, parameter or p-value | `genotype-phenotype` | Best concise gene-to-phenotype summary. |
| Statistical model output, significant calls, sex-specific effects, counts and p-values | `statistical-result` | Best for `significant:true`, `mp_term_id_options`, effect sizes, model methods and procedure-level statistics. |
| Images or media links | `impc_images` | Return `download_url`, `jpeg_url`, `thumbnail_url`, `omero_id` where useful. |
| Disease models and Phenodigm matches | `phenodigm` | Include `type:...` in `q`, for example `type:disease_model_summary`. |

Once a core is selected follow appropriate references to identify FIELDS, CORE-SPECIFIC RULES and QUERY PATTERNS:

Follow rules according to the requested solr core
- [genotype-phenotype](./references/genotype-phenotype-guide.md)
- [experiment](./references/experiment-guide.md)
- [impc_images](./references/impc_images-guide.md)
- [phenodigm](./references/phenodigm-guide.md)
- [statistical-result](./references/statistical-result-guide.md)
<!-- Placeholder routes for future supported cores. Follow the active route pattern above when enabling them.
- [gene](./references/gene-guide.md)
- [mp](./references/mp-guide.md)
- [pipeline](./references/pipeline-guide.md)
- [product](./references/product-guide.md)

TODO (MP ontology expansion): Ask the responsible developer whether the unvalidated `mp` core should be supported for descendant expansion. The working-group repository used `core="mp"` for this purpose, followed by a `statistical-result` query using `mp_term_id_options`. If this route is approved, keep the core-selection condition and `validate=False` caveat in this entrypoint, and put the fields and query examples in `references/mp-guide.md`.
-->

When the biological question requires evidence from more than one core, read
[the multi-core query guide](./references/multi-core-query-guide.md) as well as
each selected core guide. A multi-core query is a coordinated set of
independent Solr requests; neither `solr_request` nor `batch_solr_request`
accepts multiple cores in one call.

General guides for FIELDS AND QUERY PATTERNS
## Fields
Use these core-specific field sets provided under each reference guide as defaults, then add or remove fields to match the request.

## Query patterns
Use exact stable identifiers when available. Quote values containing spaces. Combine clauses with `AND` and grouped `OR`.

4. Identify filters.

Common filters:

- identifiers: `marker_symbol`, `gene_symbol`, `marker_accession_id`, `allele_accession_id`, `allele_symbol`, `colony_id`, `specimen_id`, `observation_id`
- assay metadata: `pipeline_stable_id`, `procedure_stable_id`, `procedure_name`, `parameter_stable_id`, `parameter_name`
- study design: `phenotyping_center`, `production_center`, `life_stage_name`, `sex`, `zygosity`, `biological_sample_group`
- ontology/statistics: `mp_term_id`, `mp_term_name`, `mp_term_id_options`, `top_level_mp_term_name`, `p_value`, `effect_size`, `statistical_method`, `significant`
- anatomy/images: `anatomy_term`, `top_level_anatomy_term`, `download_url`, `image_link`, `file_type`

5. For named data kinds, discover stable-id triplets before downloading rows.

IMPC observation data are defined by the triplet `pipeline_stable_id`, `procedure_stable_id`, `parameter_stable_id`. When the user asks for a data kind by name, such as "locomotor activity", "body weight", "grip strength", "startle response" or similar, first produce a table of matching triplets from the `experiment` core and ask the user to confirm if multiple meanings are present.

Use the bundled helper when a term needs discovery:

```bash
uv run skills/impc-data-retriever/scripts/find_stable_id_triplets.py \
  "body weight" --out body_weight_triplets.csv
```

The helper uses a Solr pivot facet with `rows=0`, searches parameter/procedure names and stable IDs with capitalization variants, then returns distinct triplets plus names. Keep the name columns in the table: the same code fragment can mean different things in different pipelines or procedures, for example `CSD_008` has appeared as both "Coat - color pattern - back" and "Startle response". Also treat capitalization as non-authoritative: both `Body weight` and `Body Weight` can appear.

TODO: Need to clarify whether wildcard procedure queries such as `procedure_stable_id:*OFD*` are intended only for discovery or may also be used for final observation downloads. The current examples use wildcard procedure queries for batch retrieval, which conflicts with the requirement to retrieve named data kinds using confirmed full pipeline/procedure/parameter triplets. Once clarified, label wildcard queries as discovery-only or revise the affected examples and triplet rule.


6. Use the right function.

- Use `solr_request(..., validate=True)` for small queries, previews, counts, facets and URL generation.
- Use `batch_solr_request(...)` for large result sets, list queries and downloads.
- Use `url_only=True` when the user wants a shareable Solr URL.

7. Run a preview or count and apply the bounded stopping rule.

Before a batch request or download, run a small validated preview or a `rows: 0` count:

```python
count_params = params.copy()
count_params["rows"] = 0

num_found, _ = solr_request(
    core,
    count_params,
    silent=True,
    validate=True,
)
```

- If the request fails because of a timeout or another transient transport error, retry it at most once. If it still fails, stop and report the request failure; do not describe it as a zero-result query.
- If `num_found` is greater than zero, continue with the requested retrieval.
- If `num_found` is zero, inspect validation warnings and the query locally before making another request.
- Make at most one additional `rows: 0` request. Use that single request either to rerun a query after correcting an evident core, field or syntax error, or to diagnose a valid query:
  - for a name or free-text query, broaden only the name-matching clause;
  - for a query with several filters, keep the primary identifier and remove the secondary filters.
- Skip the diagnostic query when the original request already uses one exact stable identifier against the correct core and field.
- If the additional query also returns zero, stop and report that no matching IMPC data were found.
- If a corrected query returns records for the original request, continue with the requested retrieval. If a broadened diagnostic query finds nearby records, stop before downloading them, show the nearby entities or the filters that excluded the original result, and ask the user which option to use.

Do not continue broadening filters, searching additional cores or retrying zero-result queries automatically. A zero-result investigation is limited to the initial request and one diagnostic request.

For a planned multi-core query, apply this stopping rule independently to each
core. A failure or zero result in one core does not establish that the entity is
absent from another core. Continue independent branches that can still answer
part of the question, stop branches that depend on a missing upstream
identifier, and report every core's status without claiming the answer is
complete.

8. Return or save the result in the requested format.

## Output

Prefer returning a pandas DataFrame.

TODO: Ask the responsible developer what returning a pandas DataFrame should mean in the skill's execution environment: display a preview, retain an in-memory object, save a file artifact, or provide reusable Python code. Once clarified, define the default behavior for small and large results.

If requested, save results as CSV or JSON with `batch_solr_request`, passing `download=True` and `filename=<name>` to the function and setting `params["wt"]` to the requested format.

For multi-core results, keep heterogeneous core outputs separate by default and
return a short synthesis plus a per-core result/provenance table. Do not append
or join core DataFrames merely because fields have similar names. Combine them
only through verified stable identifiers and at a cardinality appropriate to
the biological question, following the multi-core query guide.

`batch_solr_request(download=True)` supports only `params["wt"] = "json"` and `params["wt"] = "csv"`. For Parquet or Excel, first retrieve a DataFrame or CSV, then convert with pandas only if the data size is reasonable.


## Examples
Example 1

User

Download Open Field data.

Use `experiment` for raw data. Start with a facet or count if the user has not specified life stage, sample group or centre; otherwise use `batch_solr_request` with `procedure_stable_id:*OFD*`.

Example 2

User

Get all data for Trp53.

Ask whether they want summaries or raw observations. If they say all, use the
multi-core guide to retrieve `genotype-phenotype`, `statistical-result`,
`experiment`, and `impc_images` separately with gene fields appropriate to each
core (`marker_symbol` for summaries/statistics, `gene_symbol` for
observations/images). Include `phenodigm` only when disease relevance is in
scope.

Example 3

User

Download all significant genotype-phenotype associations.

Use `statistical-result` with `q: "significant:true"` when the user asks for significant calls. Use `genotype-phenotype` with `p_value` ranges when the user asks for association summaries.

Example 4

User

Export Clinical Chemistry parameters as CSV.

If the user needs observed data, use `experiment` with the Clinical Chemistry procedure or parameter stable IDs and call `batch_solr_request` with `download=True` and `params["wt"] = "csv"`. If they need parameter metadata only, facet `experiment` by `parameter_stable_id` or query a small field list of `procedure_name,procedure_stable_id,parameter_name,parameter_stable_id,pipeline_stable_id`.

Example 5

User

Download body weight data.

First run the triplet discovery helper for `"body weight"` and show the `pipeline_stable_id`, `procedure_stable_id`, `parameter_stable_id`, `procedure_name` and `parameter_name` table. Then query `experiment` by confirmed full triplets, not by `parameter_name` alone.

Example 6

User

Compare late adult and early adult activity data for centres with late adult OFD.

Facet `experiment` by `phenotyping_center` for late adult OFD, build a grouped centre query, retrieve late/middle adult experimental rows, then retrieve early adult rows for the same `allele_accession_id` values. Retrieve controls separately with `biological_sample_group:control`.

## General Guidelines
- Prefer `solr_request` and `batch_solr_request` rather than manually constructing Solr URLs.
- Use `validate=True` for normal queries against validated cores.
- Use `fl` aggressively; do not retrieve all fields unless the user asks for all fields.
- Use facets to discover available centres, procedures, parameters, methods, sex or zygosity before large downloads.
- Use exact stable IDs over names. Prefer `procedure_stable_id`, `parameter_stable_id`, `mp_term_id`, `allele_accession_id`.
- For data kinds named in ordinary language, discover and use complete `pipeline_stable_id`/`procedure_stable_id`/`parameter_stable_id` triplets before retrieving observations.
- Do not query observations by `parameter_stable_id` alone when a code fragment or name may be ambiguous.
- Preserve original IMPC identifiers.
- Return informative error messages if no matching data are found.
- If multiple datasets match the request, explain the options and ask the user to choose.
- For very large downloads, use `batch_solr_request` with `download=True` and `params["wt"]` set to `"csv"` or `"json"`; warn that reading the downloaded file into memory may still fail.
- For metadata columns that contain lists like `"key = value"`, expand them after retrieval only if the user asks for analysis-ready columns.
- Do not infer biological annotations beyond what IMPC returns.
- Select cores from the biological subquestions before querying. Do not add a
  core merely because another core returned zero results.

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
- The triplet discovery helper calls Solr directly because `impc-api` does not expose pivot facets.
- Current validated Solr cores in the package are `experiment`, `genotype-phenotype`, `impc_images`, `phenodigm`, and `statistical-result`.
- `batch_solr_request` ignores `params["rows"]`; set `batch_size` instead.
- `batch_solr_request` mutates the `params` dictionary by setting `start`, `rows`, `wt`, and sometimes `fq`; pass a copy if reusing params.
- Parameter units and IMPReSS schedule timepoints are not exposed as first-class helpers in `impc-api`; only call IMPReSS REST endpoints directly when the user explicitly needs those metadata.
- Preserve IMPC stable identifiers exactly as returned by the API.
- When possible, return data as a pandas DataFrame to facilitate downstream analysis.
