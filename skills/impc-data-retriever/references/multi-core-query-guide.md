# Multi-core query guide

Use this guide when one biological question requires two or more IMPC data
products. IMPC Solr cores are independent stores. Plan and execute one request
per core, then synthesize the evidence; do not pass a list of cores to
`solr_request` or `batch_solr_request`.

This skill currently supports validated multi-core plans using `experiment`,
`genotype-phenotype`, `statistical-result`, `impc_images`, and `phenodigm`.
Do not add `gene`, `mp`, `pipeline`, `product`, or `mgi-phenotype` to a plan
until that core has an active guide and its fields and validation behavior have
been verified.

## Requirements

The runtime needs `uv`, the repository's installed `impc-api` dependency,
network access to `https://www.ebi.ac.uk/mi/impc/solr/`, and a writable output
location when files are requested. Use the field schema shipped with the
installed package and the active core guides; do not assume that a field from
one core exists in another.

The query plan must establish the user's biological scope, the identifier used
to carry that scope between cores, and the grain of any integrated output. Ask
for clarification only when one of those choices would materially change the
answer. Otherwise keep per-core results separate and proceed.

Supporting additional cores requires an active core guide, verified fields and
example queries, a documented identifier mapping to the existing cores, and a
decision about validation. The package schema in this repository currently
validates only the five supported cores above even though the public IMPC Solr
service documents additional cores.

## Build the plan

Translate the request into biological subquestions and select only cores that
answer them:

| Subquestion | Core |
| --- | --- |
| Which phenotype calls are associated with a gene, allele, or MP term? | `genotype-phenotype` |
| What statistical evidence, effect sizes, counts, or sex-specific effects support a call? | `statistical-result` |
| What specimen-level measurements produced the evidence? | `experiment` |
| Which related images or media are available? | `impc_images` |
| Which mouse models match a human disease or phenotype profile? | `phenodigm` |

Before executing, record a plan with one row per core containing:

- the subquestion and core;
- the core-specific `q` and narrow `fl`;
- whether its inputs come from the user or an upstream core;
- the stable identifiers that will link its result to other evidence;
- the intended output: count, preview, complete result, or file.

Do not query overlapping summary cores without a reason. For example,
`genotype-phenotype` is the concise set of phenotype hits, while
`statistical-result` is appropriate when the user needs the full statistical
evidence behind those hits.

## Resolve and propagate identifiers

Prefer stable identifiers over display names. Field names differ by core, so
map them explicitly:

| Entity | `experiment` / `impc_images` | `genotype-phenotype` / `statistical-result` | `phenodigm` |
| --- | --- | --- | --- |
| Mouse gene | `gene_accession_id` (`gene_symbol`) | `marker_accession_id` (`marker_symbol`) | `marker_id` (`marker_symbol`) |
| Allele | `allele_accession_id` | `allele_accession_id` | not available as the same field |
| Assay | `pipeline_stable_id`, `procedure_stable_id`, `parameter_stable_id` | the same stable-ID fields | not applicable |
| MP term | not a general result field | `mp_term_id` or `mp_term_id_options` | `mp_id` |
| Specimen/observation | `specimen_id`, `observation_id` | not applicable | not applicable |
| Disease/model | not applicable | not applicable | `disease_id`, `model_id` |

Verify that values use the same namespace before treating mapped fields as the
same identifier. Preserve the original field names and values in each result.
A normalized presentation column such as `source_core` or `query_gene_id` may
be added, but it must not replace the source identifiers.

Use upstream results to narrow dependent requests when appropriate. Examples:

- carry the phenotype call's allele and full pipeline/procedure/parameter
  stable-ID context into statistical or raw-evidence requests;
- use a PhenoDigm `marker_id` only after verifying that it matches the MGI gene
  accession used by the other selected cores;
- use the full pipeline/procedure/parameter triplet when matching raw
  observations to an assay, not `parameter_name` or a code fragment alone.

Independent requests may be executed separately without waiting for one
another. Execute dependent requests only after their upstream identifiers are
known.

## Avoid false joins

Keep per-core DataFrames separate unless the user needs an integrated table.
Never concatenate heterogeneous core rows into one table.

For an integrated view, choose a declared grain first, such as one row per
gene, allele, phenotype call, disease model, or assay. Aggregate each core to
that grain before joining and inspect key cardinality. Raw observations and
statistical results normally have a many-to-many relationship unless the key
also includes the relevant allele, pipeline, procedure, parameter, zygosity,
sex, life stage, centre, and any required metadata grouping. If the available
fields do not establish the requested relationship, present linked sections
instead of asserting a row-level join.

Do not join on names or symbols alone when an accession exists. Do not infer
that a raw observation caused a phenotype call, or that a phenotype call
supports a disease match, beyond the relationships represented by the returned
identifiers.

## Counts, failures, and output

Apply the main skill's preview/count and bounded retry rule to every planned
core. Record for each core:

- purpose, `q`, `fl`, and generated URL when useful;
- `num_found` or batch row count;
- status: `complete`, `zero results`, `failed`, `skipped dependency`, or
  `not requested`;
- output artifact or DataFrame name.

If one core fails, continue only independent branches. A partial answer must
name the failed or skipped core and must not claim a comprehensive result. If
all cores are needed for the requested comparison, stop after the bounded
attempts and explain which evidence is missing.

Return a concise biological synthesis followed by the per-core results or
artifacts and the provenance/status table. Keep claims attributable to the
core that supports them.

## Example plan

For “For Pax6, show phenotype hits, their statistical support, relevant raw
measurements, and images”:

1. Query `genotype-phenotype` by `marker_symbol:Pax6`, returning MP, allele,
   parameter, pipeline, procedure, sex, zygosity, and life-stage identifiers.
2. Query `statistical-result` for the returned allele/parameter identifiers to
   retrieve p-values, effect sizes, methods, counts, and significance fields.
3. Query `experiment` using confirmed full assay triplets and relevant allele,
   sex, zygosity, and life-stage filters. Keep controls and mutants explicit.
4. Query `impc_images` by `gene_symbol:Pax6`, narrowed by returned allele or
   parameter identifiers when the question requires matching media.
5. Keep all four outputs separate; synthesize at phenotype-call or assay grain.

## Authoritative documentation

- [IMPC programmatic data access](https://www.mousephenotype.org/help/programmatic-data-access/)
- [IMPC Solr core and field documentation](https://www.ebi.ac.uk/mi/impc/solrdoc/)
- [`impc-api` package usage](https://github.com/mpi2/impc-api)
- [Solr query syntax](https://solr.apache.org/guide/solr/latest/query-guide/standard-query-parser.html)
- [Raw experimental data](https://www.mousephenotype.org/help/programmatic-data-access/raw-experimental-data/)
- [Statistical results](https://www.mousephenotype.org/help/programmatic-data-access/statistical-results/)
- [Phenotype calls](https://www.mousephenotype.org/help/programmatic-data-access/phenotype-calls/)
- [PhenoDigm results](https://www.mousephenotype.org/help/programmatic-data-access/phenodigm-results/)
- [Images](https://www.mousephenotype.org/help/programmatic-data-access/images/)
