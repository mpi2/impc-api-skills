# GWAS Catalog: study accessions → traits, and traits → studies

Tested 2026-09-22. `scripts/gwas_catalog_traits.py` wraps the REST API v2.

## Role of the Catalog in this skill

The GWAS Catalog is the primary source of the study→trait mapping for `GCST`
studies; Open Targets re-ingests it and normalises ids (`traitFromSourceMappedIds`
→ `diseases`). Fetch the Catalog mapping for every study and compare with the
Open Targets ids (`--compare-ot`). Agreement is the norm (80 of 86 test
studies), but not guaranteed: normalisation can drop or swap an id
(`EFO_0000493 family history` present in the Catalog only; `EFO_0000516` vs
`MONDO_0005041` glaucoma in FinnGen rows). Every disagreement goes into the
user-facing synthesis and the README, with both id sets. The Catalog also
supplies what Open Targets lacks: reported trait wording, ancestry breakdown,
initial/replication sample text, cohort, summary-statistics FTP path; and it is
the entry point for the reverse direction (trait → studies).

## Official MCP server

`https://www.ebi.ac.uk/gwas/mcp` (Streamable HTTP, stateless, no auth; use the
`www.` host — the bare domain 301-redirects and drops the POST body). Claude Code:

```bash
claude mcp add --transport http gwas-catalog https://www.ebi.ac.uk/gwas/mcp
```

Tools:

| Tool | Key parameters | Returns |
| --- | --- | --- |
| `gwascatalog_get_studies` | `accession_id` (one `^GCST\d+$` per call), `efo_id`, `efo_trait`, `disease_trait`, `mapped_gene`, `pubmed_id`, `ancestral_group`, `cohort_id`, `full_pvalue_set`, `show_child_trait`, `page`, `size` | study record with `efo_traits[]`, `bg_efo_traits[]`, `ancestries[].n` |
| `gwascatalog_get_traits` | `efo_id`, `efo_trait`, `mapped_gene`, `pubmed_id`, `uri` | `{efo_id, efo_trait}` (text search does not match synonyms) |
| `gwascatalog_get_associations` | `accession_id`, `efo_id`, `rs_id`, `mapped_gene`, … | association rows |

The claude.ai-hosted "GWAS Catalog" connector often fails with a connect
timeout while the EBI endpoint answers curl in about a second. Treat that as a
client-side failure: use the script, note it in the README, move on.

## REST API v2

Base `https://www.ebi.ac.uk/gwas/rest/api/v2`; documented limit 15 requests/s;
no batch lookup (comma lists and repeated params silently return 0 rows).

| Need | Call |
| --- | --- |
| Study with inline traits | `GET /studies/{GCST}` → `disease_trait`, `efo_traits[{efo_id, efo_trait}]`, `bg_efo_traits`, `pubmed_id`, `initial_sample_size`, `discovery_ancestry[]`, `cohort[]`, `full_summary_stats` |
| Per-ancestry N | `GET /studies/{GCST}/ancestries` |
| Trait record + URI | `GET /efo-traits/{EFO_or_MONDO_id}` → `{efo_trait, uri, efo_id}` |
| Studies for a trait | `GET /studies?efo_id=MONDO_0005306&show_child_traits=true&size=200&page=0` (HAL: `_embedded.studies`, `page.totalPages`) |
| Studies by reported text | `GET /studies?disease_trait=Ankylosing%20spondylitis` |
| Missing study | HTTP 404 `{"errorCode":404,"errorMessage":"Studies with Accession Id: X not found"}` |

v1 (`/gwas/rest/api/studies/{GCST}` + `/efoTraits`) still works but needs two
calls per study. The summary-statistics API is deprecated (HTTP 410).

## Gotchas

- **Trait id drift.** Many disease traits are now `MONDO_` not `EFO_` (celiac
  `EFO_0001060` → `MONDO_0005130`, SLE → `MONDO_0007915`). A trait→studies
  query with a stale id returns 0 rows, not an error. Resolve the current id
  with `GET /efo-traits/{id}` (the script does this and prints a warning) or
  `gwascatalog_get_traits` first.
- **Multiple mappings per study** are common (e.g. celiac disease + drug use
  measurement). Emit one row per mapping; keep `bg_efo_traits` separate.
- **Sample size** is free text plus per-ancestry integers; the script sums the
  leading numbers of `discovery_ancestry`.
- **IRIs.** `EFO_` → `http://www.ebi.ac.uk/efo/`, `Orphanet_` → `http://www.orpha.net/ORDO/`,
  everything else (`MONDO_`, `HP_`, `OBA_`) → `http://purl.obolibrary.org/obo/`.

## Script

```bash
# forward: studies from the Open Targets link table, compared with the Open Targets trait ids
uv run skills/impc-gwas-trait-mapper/scripts/gwas_catalog_traits.py \
  --from-csv 03_l2g_gwas_links.csv --id-col gwas_study_id --compare-ot 04_gwas_traits.csv --out 04_gwas_catalog_traits.csv
# reverse: all studies for a trait, including descendants
uv run skills/impc-gwas-trait-mapper/scripts/gwas_catalog_traits.py --efo MONDO_0005306 --child-traits --out studies.csv
```

Output columns: `study_id, reported_trait, trait_id, trait_label, trait_uri,
trait_role (mapped|background), pubmed_id, sample_size, initial_sample_size,
discovery_ancestry, cohort, full_summary_stats, note`. Non-Catalog ids and 404s
appear as rows with a `note`, so the README can list them.
