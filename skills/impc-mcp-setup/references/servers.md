# IMPC MCP servers and their tools

Four hosted servers, all public, all Streamable HTTP, all versioned together by EBI. Use this to answer "what do I get?" and to route a task to the right server before setup.

---

## impc-solr

`https://www.ebi.ac.uk/mi/impc/mcp/solr/`

| Tool | Purpose |
| --- | --- |
| `solr_query` | Query the IMPC Solr cores directly |

The broadest of the four and the one to reach for when nothing more specific fits. It queries the IMPC Solr cores directly — `experiment`, `genotype-phenotype`, `statistical-result`, `impc_images` and `phenodigm` — covering raw observations, phenotype associations, statistical calls, images and disease models.

Route here: phenotype data for a gene, significant calls, raw measurements, procedure/parameter lookups, image records.

---

## impc-publications

`https://www.ebi.ac.uk/mi/impc/mcp/publication/`

| Tool | Purpose |
| --- | --- |
| `by_search_query` | Search IMPC-linked publications by free text |
| `by_publication_date` | Retrieve publications within a date range |
| `get_database_stats` | Summary statistics for the publication database |

Covers papers that cite or use IMPC data and resources.

Route here: literature on an IMPC gene or allele, recent IMPC-linked papers, publication counts.

---

## impc-orthology

`https://www.ebi.ac.uk/mi/impc/mcp/orthology/`

| Tool | Purpose |
| --- | --- |
| `find_orthologs_by_mouse_genes` | Mouse gene symbols → human orthologs |
| `find_orthologs_by_human_genes` | Human gene symbols → mouse orthologs |
| `find_orthologs_by_mgi_ids` | MGI accession IDs → orthologs |
| `find_orthologs_by_hgnc_ids` | HGNC IDs → orthologs |
| `find_all_orthologs_paginated` | Page through the full ortholog set |
| `find_all_orthologs_by_mgi_ids` | Bulk lookup by a list of MGI IDs |

Note the pairing of symbol-based and accession-based tools. Prefer the accession forms (`_by_mgi_ids`, `_by_hgnc_ids`) when the user already has stable IDs, since gene symbols are ambiguous across species and change over time.

Route here: translating between mouse and human genes, cross-species comparison, mapping a human disease gene to its mouse model.

---

## impc-allele

`https://www.ebi.ac.uk/mi/impc/mcp/allele/`

| Tool | Purpose |
| --- | --- |
| `get_allele` | Allele record details |
| `get_mice_products` | Live mouse line availability |
| `get_es_cell_products` | ES cell clone availability |
| `get_crispr_products` | CRISPR product details |
| `get_targeting_vectors` | Targeting vector availability |
| `get_intermediate_vectors` | Intermediate vector availability |
| `get_htgt_design` | High-throughput gene targeting design |

The product tools answer ordering and availability questions — "can I get a mouse for this allele?" — rather than phenotype questions.

Route here: allele records, mouse/ES cell/vector ordering, CRISPR reagents, targeting design.
