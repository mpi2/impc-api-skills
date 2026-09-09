# Retrieval report

Write a `README.md` alongside the retrieved data for every run that sends one
or more requests to IMPC. The report is both a result summary and a compact
debugging record. Write it even when the run is partial, returns no rows, or
fails after making a request.

If a valid request returns zero results, do not create an empty result data
file such as CSV, JSON, Parquet, or Excel. Still write the `README.md` so the
zero-result request remains inspectable. The README is a report and provenance
file, not a result data file.

## Capture during execution

Maintain an ordered in-memory attempt log from the first preview or discovery
request onward. Record an entry before each request and update it with the
outcome. Also record material local transformations such as filtering,
deduplication, grouping, joining, and format conversion. Use a `finally` block
or an equivalent fallback so an exception after the first request does not
prevent the README from being written.

For each request, capture:

- its purpose and order;
- the API function or direct helper used;
- the Solr core and exact logical parameters supplied by the retrieval code;
- relevant function options such as `validate`, `batch_size`, `timeout`,
  `download`, and output filename;
- the exact Python used to construct the parameters and make the request;
- the outcome: `worked`, `zero results`, `failed`, or `not run`;
- `num_found`, rows written, or the error type and concise message;
- any correction or diagnostic change and why it was made.

For a batched request, record the original parameters before
`batch_solr_request` mutates them, plus batch size and the aggregate outcome.
Do not repeat every internal `start`/`rows` page as a separate query. Never
replace failed requests with only the final successful request.

Do not create `queries.json` for short or directly expressed queries. Record
those queries only in the README. Create `queries.json` only when the user
explicitly requests machine-readable query provenance or when dynamically
generated query inputs, such as a very large identifier list, would otherwise
make the README unwieldy.

When `queries.json` is created, treat it as a machine-readable companion, not
as a substitute for the README's debugging record. The README must contain the
request's exact Python construction and function call. Keep a large generated
query scannable by placing the exact code in a collapsed `<details>` block.
Before that block, state the construction rule, identifier count, source
artifact, and a relative link to `queries.json`. Do not replace the code with
an abbreviated query, ellipsis, or pseudocode.

## README structure

Use the following sections, omitting only fields that genuinely do not apply:

````markdown
# <short request title>

## Request

<What the user asked for and the interpreted scope.>

## Result summary

<Concise biological/data summary, including row/entity counts and whether the
answer is complete, partial, empty, or failed.>

## Output files

| File | Rows | Description |
| --- | ---: | --- |
| `result.csv` | 123 | ... |

<For a zero-result run, replace the table with: "No result data files were
written because the request returned zero rows.">

## Queries

### 1. <what was done> — `<status>`

<In one or two plain-language sentences, explain why this request was made and
what it selected, counted, diagnosed, or downloaded.>

- Core: `experiment`
- Function: `solr_request`
- Options: `validate=True`, `silent=True`
- Query: `gene_symbol:"Pax6"`
- Outcome: `num_found=123`

```python
from impc_api import solr_request

params = {
    "q": 'gene_symbol:"Pax6"',
    "fl": "gene_symbol,observation_id,parameter_stable_id",
    "rows": 0,
}

num_found, dataframe = solr_request(
    core="experiment",
    params=params,
    validate=True,
    silent=True,
)
```

## Process log

| Step | Action | Outcome | Details |
| ---: | --- | --- | --- |
| 1 | Counted matching records | Worked | `num_found=123` |
| 2 | Applied allele filter | Worked | 123 → 80 rows |
| 3 | Tried optional image branch | Failed | Timeout after one retry |

## Limitations and follow-up

<Missing branches, failed/zero-result queries, interpretation limits, or
`None` when the result is complete.>

## Provenance

- Generated: `<UTC ISO-8601 timestamp>`
- uv: `<version>` using the local uv project
- Package: `impc-api <version>`
- Python: `<version>`
````

Keep query parameters in valid JSON or a clearly labelled Python mapping. Use
relative links to output files. Do not include credentials, environment
variables, local cache paths, or unrelated host details.

For every numbered query subsection:

- use the exact status vocabulary: `worked`, `zero results`, `failed`, or
  `not run`;
- keep the entries in execution order and give each request its own subsection,
  including failed requests and retries;
- include the plain-language explanation plus the five labelled fields shown
  above: Core, Function, Options, Query, and Outcome;
- follow those fields with a `python` block containing the actual parameter
  construction and API call, including values that affect reproducibility;
- show the code that was attempted when the status is `failed`; for `not run`,
  label the block `Planned code (not executed)`;
- preserve dynamically constructed queries as their actual construction code
  and resolved inputs rather than rewriting them as a cleaner hypothetical
  query; and
- use a collapsed `<details>` block around the code only when its size would
  otherwise obscure the rest of the report.

## Reporting rules

- Reuse the skill's existing result synthesis; do not create a second,
  contradictory summary.
- Make the README sufficient for human inspection and debugging without
  requiring the reader to open `queries.json`.
- Do not write an empty result data file for a valid zero-result response; in
  the Output files section, state that no result data files were written.
- Distinguish a transport/request failure from a valid zero-result response.
- State which branches completed when a multi-core retrieval is partial.
- Give input and output row counts for local filters or joins when available.
- Document skipped steps only when they were part of the planned answer and
  explain the dependency or stopping rule that caused the skip.
- Do not claim a diagnostic query answered the original request when it only
  found nearby entities.
