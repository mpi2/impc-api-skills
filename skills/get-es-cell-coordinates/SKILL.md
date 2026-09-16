---
name: get-es-cell-coordinates
description: Retrieve an IMPC ES-cell or corresponding targeting-vector GenBank file and extract its 5′ and 3′ homology-arm coordinates to report the predicted construct interval between their inner boundaries. Use for ES-cell coordinate requests that provide an MGI gene ID and allele name, an IMPC allele-page URL, or a GenBank file/URL.
---

# Get ES Cell Coordinates

Return the interval `x2..y1`, where the GenBank feature annotated `5 arm`
is `x1..x2` and the feature annotated `3 arm` is `y1..y2`.

## Prerequisites

- `uv` must be installed and available on `PATH`; verify with `uv --version`.
- Resolving an allele to a GenBank URL requires the `impc-allele` MCP server.
  A local file or direct GenBank URL does not require MCP.

## Retrieve the GenBank file

If the user supplies a local GenBank file or a direct GenBank URL, use it.

Otherwise extract the MGI gene accession and allele name from the request or
allele-page URL, then call
`mcp__impc_allele__get_es_cell_products(mgi_gene_accession_id=...,
allele_name=...)`. Use the exact identifiers; do not guess an allele. For each
ES-cell product, read `associatedProductVectorName`,
`otherLinks.vectorGenbankFile`, and `otherLinks.genbankFile`. Group products by
targeting-vector name and URL, and use the corresponding targeting-vector
GenBank (`vectorGenbankFile`) as the coordinate source whenever it is present;
this is the authoritative construct for all clones sharing that vector (for
example, PGS00017_A_B02 for Nxn tm1a). Do not parse a clone's `genbankFile`
when its targeting vector has a GenBank link. Fall back to `genbankFile` only
for a product with no targeting-vector GenBank link. Deduplicate identical
source URLs, and report the targeting-vector name and which ES-cell clones
share each result.

If the Allele MCP tool is unavailable, stop and ask whether to install or
configure the `impc-allele` server with the `impc-mcp-setup` skill. If the
query has no ES-cell result or neither a targeting-vector nor ES-cell GenBank
link, say so; do not substitute an unrelated targeting-vector file.

## Extract coordinates

Run the bundled standard-library parser:

```bash
uv run --script scripts/extract_es_cell_coordinates.py <GenBank-path-or-URL>
```

The parser accepts plain or gzipped local files and HTTP(S) URLs. It matches
the GenBank `/note` annotations `5 arm` and `3 arm`, tolerating apostrophes,
case, spaces, underscores, and hyphens. Treat missing or duplicate arm
annotations, or overlapping/reversed arm boundaries, as errors rather than
choosing a feature silently.

Return at least:

| Field | Value |
| --- | --- |
| 5′ arm (`x1..x2`) | parser result |
| 3′ arm (`y1..y2`) | parser result |
| Predicted ES-cell interval (`x2..y1`) | parser result |

These are **1-based, inclusive, construct-relative GenBank coordinates** for
the selected ES-cell or targeting-vector construct. Do not present them as
mouse genomic coordinates. If genomic/browser coordinates
are requested, explain that IMPC's IKMC browser track is on GRCm39 and its
track-hub starts are 0-based; use an explicitly mapped browser track or align
the homology-arm sequences to the requested assembly. `get_htgt_design` can
provide design oligos and their assembly, but those oligos alone must not be
relabeled as the GenBank arm boundaries.

Official context:

- https://www.mousephenotype.org/help/data-visualization/genome-browser/
- https://www.mousephenotype.org/help/mcp-services/mcp-allele-server/
