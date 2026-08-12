---
name: impress-procedure-links
description: Generate IMPReSS procedure links from natural-language requests by resolving procedure and pipeline identifiers in the IMPC Solr pipeline core. Use for requests to find, list, or generate all applicable IMPReSS procedure pages, including ambiguous or centre-specific pipeline variants.
---

# IMPReSS Procedure Links

Resolve procedure records before constructing links. Never guess, hard-code, or reuse identifiers from examples.

## Workflow

1. Interpret the requested procedure and retain meaningful qualifiers such as stage, specimen, assay, or centre.

2. Query the `impc-solr` MCP service with `mcp__impc_solr__solr_query` using `core: "pipeline"`. Search `procedure_name` with the request's meaningful terms. Build a wildcard clause for each meaningful token and combine the token clauses with `AND`; do not rely on an exact quoted phrase, since the pipeline field may not match phrase queries consistently. Include an `OR` variant for joined spellings when relevant (for example, `body weight` should search both `(procedure_name:*body* AND procedure_name:*weight*)` and `procedure_name:*bodyweight*`).

   Run supplementary queries for each meaningful token and an exact/case-preserving `procedure_name` query when the request resembles a procedure display name; union their results before filtering for the requested concept. A zero or incomplete result from one combined wildcard query is not proof that no record exists: Solr field analysis can make a combined wildcard query miss a record that a token, exact-name, or stable-key query finds. Query enough rows to include every match—prefer `rows: 10000`—and request at least:

   `pipeline_id,pipeline_name,pipeline_stable_id,procedure_name,procedure_stable_id,procedure_stable_key`

   Request additional centre/metadata fields only if they exist in the returned Solr schema.

3. Treat each exact `(pipeline_id, procedure_stable_key)` pair as one result. The pipeline core contains repeated parameter-level rows, so remove only duplicate rows with the same pair. Keep distinct pipeline/procedure pairs, including different ages, centres, alternative pipelines, and records with the same display name. Each distinct pair maps to its own procedure page.

4. Prefer records whose `procedure_name` and pipeline metadata best match the request. If a broad request such as “X-ray” matches several applicable pipelines, return all relevant pairs rather than selecting the first. A request phrased as one page may still map to multiple pages; do not collapse records merely because their display names are similar. Ask a clarification question only when the returned metadata cannot distinguish the intended procedure.

5. For every selected `(pipeline_id, procedure_stable_key)` pair, construct the procedure page using the parameter-page URL:

   `https://www.mousephenotype.org/impress/ProcedureInfo?action=list&procID=<procedure_stable_key>&pipeID=<pipeline_id>`

   Map `procID` only from `procedure_stable_key` and `pipeID` only from `pipeline_id`. URL-encode values if required, and do not emit a URL when the required identifier is missing.

6. Return only the applicable parameter-page URLs, labeling each as `procedure page`. For multiple pipeline pairs, return a complete list or table that includes `procedure_name`, `procedure_stable_id`, `pipeline_name`, `pipeline_stable_id`, and any useful centre or age metadata. If no record matches after the supplementary searches, say that no matching procedure was found; never invent IDs or URLs.
