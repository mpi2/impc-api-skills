---
name: get-impress-data
description: Generate IMPReSS links and downloadable triplet tables from natural-language requests by resolving pipeline, procedure, and parameter identifiers in the IMPC Solr pipeline core. Use for requests to find, list, or generate applicable IMPReSS parameter pages, including ambiguous or centre-specific variants.
---

# IMPReSS Procedure and Parameter Links

IMPC data are defined by the triplet `pipeline`, `procedure`, and `parameter`.
For any request about parameters or data, always resolve and return the full
triplet; never return a parameter without its pipeline and procedure context.
Resolve records before constructing links. Never guess, hard-code, or reuse
identifiers from examples.

By default, omit alternative pipelines from results. An alternative pipeline
is any record whose `pipeline_stable_id` starts with `ALT`. Warn the user that
this is the default behavior and that they can request alternative pipelines
explicitly.

## Workflow

1. Interpret the request as a triplet search. Infer omitted pipeline and
   procedure context from the requested phenotype/parameter and retain
   meaningful qualifiers such as stage, specimen, assay, or centre. A request
   such as “eye phenotype, cornea opacity, list of parameters” means search for
   parameters matching `cornea opacity` and include their pipeline and
   procedure for every result.

2. Query the `impc-solr` MCP service with `mcp__impc_solr__solr_query` using
   `core: "pipeline"`. Search the relevant `parameter_name`,
   `procedure_name`, and pipeline fields with the request's meaningful terms.
   Build a wildcard clause for each meaningful token and combine token clauses
   with `AND`; do not rely on an exact quoted phrase. Include an `OR` variant
   for joined spellings when relevant (for example, `body weight` should
   search both `(parameter_name:*body* AND parameter_name:*weight*)` and
   `parameter_name:*bodyweight*`). Run supplementary single-token and exact /
   case-preserving searches, plus stable-ID searches when the request contains
   an ID, and union their results before filtering. A zero or incomplete result
   from one query is not proof that no record exists. Query enough rows to
   include every match—prefer `rows: 10000`—and request at least:

   `pipeline_id,pipeline_name,pipeline_stable_id,procedure_name,procedure_stable_id,procedure_stable_key,parameter_name,parameter_stable_id,parameter_stable_key`

   Request additional centre/metadata fields only if they exist in the returned Solr schema.

3. Treat each exact `(pipeline_id, procedure_stable_key,
   parameter_stable_key)` triplet as one result. The pipeline core contains
   repeated rows, so remove only exact duplicate triplets. Keep distinct
   parameters and distinct pipeline/procedure pairs, including different ages,
   centres, and records with the same display name. Unless the user explicitly
   requests alternative pipelines, exclude records whose `pipeline_stable_id`
   starts with `ALT`. If requested, retain those alternative records alongside
   the standard pipelines.

4. If the request is ambiguous and the search finds several distinct
   parameter names / stable IDs (for example, “pupil parameters”), show the
   suggested parameter names and stable IDs and ask the user to pick one before
   producing the final triplet table. Do not silently choose one. Once a
   parameter is selected, retain all applicable pipeline/procedure variants.

5. Prefer records whose parameter, procedure, and pipeline metadata best match
   the request. If a broad request such as “X-ray” matches several applicable
   triplets, return all relevant triplets rather than selecting the first. A
   request phrased as one page may still map to multiple pages; do not collapse
   records merely because their display names are similar. Ask a clarification
   question only when the returned metadata cannot distinguish the intended
   parameter or procedure.

6. For every selected triplet, construct the IMPReSS parameter link:

   `https://www.mousephenotype.org/impress/OntologyInfo?action=list&procID=<procedure_stable_key>#<parameter_stable_key>`

   In this URL, map `procID` only from `procedure_stable_key` and the URL
   fragment after `#` only from `parameter_stable_key`. URL-encode values if
   required, and do not emit a URL when either required identifier is missing.
   The pipeline ID is represented in the table and CSV; it is not substituted
   into `procID` or the fragment. If a procedure-level link is also useful,
   construct it separately as:

   `https://www.mousephenotype.org/impress/ProcedureInfo?action=list&procID=<procedure_stable_key>&pipeID=<pipeline_id>`

7. Return a table with at least these columns:
   `pipeline_name`, `pipeline_stable_id`, `procedure_name`,
   `procedure_stable_id`, `procedure_stable_key`, `parameter_name`,
   `parameter_stable_id`, `parameter_stable_key`, and `IMPReSS link`. Include
   useful centre or age metadata when available. Offer a downloadable CSV
   containing the same columns (and metadata); when requested, create the CSV
   as a file and link it in the response. Use a stable column order and quote
   values according to CSV rules so it can be consumed downstream. If no record
   matches after the supplementary searches and the default alternative-pipeline
   filter, say that no matching triplet was found; never invent IDs or URLs.
   State that alternative pipelines were omitted by default and can be included
   if the user asks for them.
