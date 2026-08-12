---
name: impress-procedure-links
description: Generate IMPReSS procedure links from natural-language requests by resolving procedure and pipeline identifiers in the IMPC Solr pipeline core. Use for requests to find, list, or generate links for one or more IMPReSS procedures, including ambiguous or centre-specific pipeline variants.
---

# IMPReSS Procedure Links

Resolve procedure records before constructing links. Never guess, hard-code, or reuse identifiers from examples.

## Workflow

1. Interpret the requested procedure and retain meaningful qualifiers such as stage, specimen, assay, or centre.

2. Query the `impc-solr` MCP service with `mcp__impc_solr__solr_query` using `core: "pipeline"`. Search `procedure_name` with the request's meaningful terms; use Solr wildcards/OR variants when spelling or punctuation may vary. Query enough rows to include every match, and request at least:

   `pipeline_id,pipeline_name,pipeline_stable_id,procedure_name,procedure_stable_id,procedure_stable_key`

   Request additional centre/metadata fields only if they exist in the returned Solr schema.

3. Treat each exact `(pipeline_id, procedure_stable_key)` pair as one result. The pipeline core contains repeated parameter-level rows, so remove only duplicate rows with the same pair. Keep distinct pipeline/procedure pairs, including alternative or centre-specific pipeline variants.

4. Prefer records whose `procedure_name` and pipeline metadata best match the request. If a broad request such as “X-ray” matches several applicable pipelines, return all relevant pairs rather than selecting the first. Ask a clarification question only when the returned metadata cannot distinguish the intended procedure.

5. For every selected record, construct exactly:

   `https://www.mousephenotype.org/impress/ProcedureInfo?action=list&procID=<procedure_stable_key>&pipeID=<pipeline_id>`

   Map `procID` only from `procedure_stable_key` and `pipeID` only from `pipeline_id`. URL-encode values if required, and do not emit a URL when either identifier is missing.

6. Return one link for one relevant pair. For multiple pairs, return a complete list or table with the URL plus `procedure_name`, `procedure_stable_id`, `pipeline_name`, `pipeline_stable_id`, and any useful centre metadata. If no record matches, say that no matching procedure was found; never invent IDs or URLs.
