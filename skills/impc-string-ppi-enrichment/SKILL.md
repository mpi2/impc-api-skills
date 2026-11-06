---
name: impc-string-ppi-enrichment
description: >-
  Test whether the genes behind IMPC mouse phenotypes form a connected protein network. Takes a list of MP terms, as ids or labels, retrieves the IMPC genes with those phenotypes and runs STRING protein-protein interaction (PPI) enrichment, against both the proteome and IMPC-tested genes. Use it whenever a user wants STRING, PPI enrichment, interaction enrichment or network connectivity for IMPC phenotypes, MP terms or knockout gene sets, or asks whether genes sharing a mouse phenotype interact more than expected, even if they never say "enrichment". Not for functional (GO/KEGG) enrichment or single-gene interaction lookups.
---

# IMPC phenotypes → STRING PPI enrichment

**Experimental:** the output format may change and there are no evals yet.

## Why this skill exists

Genes sharing a phenotype may act together, and STRING's PPI enrichment tests
whether they have more known interactions than expected. Run naively, the
result misleads: STRING's default background is the whole proteome, and IMPC
genes are not a random sample of it. A phenotype can also resolve to the wrong
id, or to a parent term with no rows of its own. This skill fixes the route and
reports every number with its background.

```
phenotype ids or labels                     OLS · references/term-resolution.md
  → MP ids                                  impc-data-retriever (genotype-phenotype)
    → genes per term                        scripts/string_ppi.py
      → STRING proteins (mouse, 10090)
        → vs proteome                       STRING MCP string_ppi_enrichment
        → vs IMPC-tested genes              STRING REST (MCP has no background option)
```

## Prerequisites

1. The `impc-data-retriever` skill, used for step 2. Its `uv` and `impc-api`
   setup applies here. Follow it before the first query.
2. `scripts/string_ppi.py` needs only the standard library. It calls the hosted
   STRING MCP server directly, so nothing needs installing, and it uses STRING
   REST for the same test if that server fails.
3. OLS for labels: the OLS MCP when loaded, otherwise its REST API.

## Input

A list of phenotypes: MP ids, labels or a mix. Create a result directory named
after the request and number files in the order below.

## Workflow

### 1. Resolve terms

Look up every input in OLS. Read `references/term-resolution.md` for the lookup
and the rule on when to ask. In short: continue on an exact label match to one
active term, or an active id; otherwise show candidates and wait.

### 2. Get the genes

A term can sit at different levels across IMPC rows: as the row's own term, as
an ancestor, or as a top-level term. Of 1,473 terms, 661 have no exact rows at
all, so an exact search would miss them, and 227 appear at two levels. The level
cannot be known in advance, so search all three fields in one query and label
each row afterwards. Each gene counts once, at the first level it appears
(exact, then intermediate, then top level). `intermediate_mp_term_id` holds
ancestors and `top_level_mp_term_id` holds top-level terms, so OLS expansion is
unnecessary.

```python
import pandas as pd
from impc_api import solr_request, batch_solr_request

terms = {"MP:0010119": "abnormal bone mineral density"}  # confirmed in step 1
exact_only = False  # True only if the user asks for exact matches
levels = ["exact", "intermediate", "top_level"]
fields = ("marker_accession_id,marker_symbol,mp_term_id,mp_term_name,intermediate_mp_term_id,"
          "p_value,effect_size,sex,zygosity,life_stage_name,phenotyping_center")

resolved, frames = [], []
for term_id, label in terms.items():
    query = f'mp_term_id:"{term_id}"'
    if not exact_only:
        query = (f'({query} OR intermediate_mp_term_id:"{term_id}" '
                 f'OR top_level_mp_term_id:"{term_id}")')
    num_found, _ = solr_request(core="genotype-phenotype", params={"q": query, "rows": 0},
                                validate=True, silent=True)
    counts = dict.fromkeys(levels, 0)
    if num_found:
        df = batch_solr_request(core="genotype-phenotype", params={"q": query, "fl": fields},
                                batch_size=1000)
        df["match_level"] = [
            "exact" if row_term == term_id
            else "intermediate" if isinstance(ancestors, list) and term_id in ancestors
            else "top_level"
            for row_term, ancestors in zip(df["mp_term_id"], df["intermediate_mp_term_id"])
        ]
        rank = df["match_level"].map(levels.index)
        df["gene_match_level"] = (rank.groupby(df["marker_accession_id"]).transform("min")
                                  .map(levels.__getitem__))
        counts.update(df.drop_duplicates("marker_accession_id")["gene_match_level"].value_counts())
        frames.append(df.drop(columns="intermediate_mp_term_id")
                      .assign(query_mp_term_id=term_id, query_mp_term_name=label))
    resolved.append({"mp_term_id": term_id, "mp_term_name": label, "rows": num_found,
                     "exact_genes": counts["exact"],
                     "intermediate_new_genes": counts["intermediate"],
                     "top_level_new_genes": counts["top_level"],
                     "total_genes": sum(counts.values())})

pd.DataFrame(resolved).to_csv("01_resolved_terms.csv", index=False)
if frames:
    genes = pd.concat(frames, ignore_index=True)
    first = ["query_mp_term_id", "query_mp_term_name", "match_level", "gene_match_level"]
    genes[first + [c for c in genes.columns if c not in first]].to_csv("02_impc_genes.csv", index=False)
```

Keep all zygosities, sexes and life stages unless the user filters; add a
filter such as `AND zygosity:homozygote` to the query. Write the attempt log
from the first request, as the data retriever's output report requires.

### 3. Run enrichment

```bash
uv run skills/impc-string-ppi-enrichment/scripts/string_ppi.py \
  --genes 02_impc_genes.csv --out-dir .
```

For each term the script tests the mapped proteins against the proteome and
against IMPC-tested genes. With 2 or more terms it also tests their union as
`combined`, each gene once. Separate rows ask whether each phenotype's genes are
connected; `combined` asks about the network across phenotypes, and comparing
them shows whether one phenotype drives it.

`--required-score` sets STRING's confidence threshold; the default, 400, matches
STRING's. Change it only on request, because results depend on it:
`references/string-ppi-guide.md` has the figures and each file's columns.

Genes map by MGI id, then by exact symbol match. The script exits 1 if any
request failed or MCP fell back to REST, after still writing all outputs. Check `errors` in `string_run.json` and `status` in
`04_ppi_enrichment.csv`.

### 4. Report

Show `04_ppi_enrichment.csv` as a table, keeping both backgrounds for each set
side by side. Report what STRING returned and do not call a network enriched,
real or significant. Then write `README.md` following
`impc-data-retriever/references/output-report.md`. Include:

- the term resolution, and genes per level from `01_resolved_terms.csv`;
- for any term with descendants, that it merges them, possibly in opposite
  directions (see `references/string-ppi-guide.md`), and that `02_impc_genes.csv`
  shows which term each row came from;
- the background note from `references/string-ppi-guide.md`;
- that p-values are uncorrected across sets;
- unmapped genes, rejected symbol hits and sets not tested;
- values from `string_run.json`: STRING version, required score, background size.

## Output

| File | Contents |
| --- | --- |
| `01_resolved_terms.csv` | Term ids, labels, rows, and genes new at each level |
| `02_impc_genes.csv` | One row per IMPC statistical call, with queried term and match level |
| `03_string_mapping.csv` | One row per gene: STRING id, how it mapped, name differences |
| `04_ppi_enrichment.csv` | One row per gene set × background, with STRING's fields |
| `05_impc_tested_background.csv` | Proteins used as the IMPC-tested background |
| `string_run.json` | Versions, parameters, mapping counts, errors |
| `README.md` | Report and provenance |

## Stopping rules

- **No term resolves:** stop and show what OLS returned.
- **A term has 0 rows:** keep it in `01_resolved_terms.csv` and continue with
  the others. If no term has rows, skip step 3 and write only the README and
  `01_resolved_terms.csv`.
- **Fewer than 2 mapped proteins:** the genes stay in `02_impc_genes.csv` and in
  `combined`, and `04_ppi_enrichment.csv` shows the set as not tested. One
  protein has no pairs to test, and STRING would add its neighbours and test
  those instead.
