---
name: impc-phenotype-string-network
metadata:
  version: "1.0.0"
description: >-
  Test whether the genes behind IMPC mouse phenotypes form a connected protein network. Retrieves genes for MP ids or labels, runs STRING PPI enrichment against both the proteome and IMPC-tested genes, provides interactive network links, and compares opposite phenotype directions where applicable. Use for STRING links, PPI enrichment, interaction enrichment or network connectivity for IMPC phenotypes or knockout gene sets, including whether genes sharing a phenotype interact more than expected. Not for functional (GO/KEGG) enrichment or single-gene interaction lookups.
---

# IMPC phenotypes → STRING PPI enrichment

**Experimental.**

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
        → network link per set              STRING REST get_link (image only with --images)
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

#### Compare opposite phenotype directions

For a parent phenotype such as abnormal bone mineral density, check OLS for
active descendants describing opposite changes in the same measurement, such
as decreased and increased bone mineral density. Verify their definitions and
ancestry; do not invent ids, infer direction from effect-size signs, or split
unrelated anatomical abnormalities into artificial opposites.

Look up to three levels below the parent (children, grandchildren and
great-grandchildren), one level at a time with OLS children;
`references/term-resolution.md` has the REST call. Count only top-most pairs:
once a pair is found, do not look below its terms, because pairs there refine
the same direction. Under abnormal bone mineral density, the femur and
vertebrae pairs sit below increased and decreased bone mineral density, so
that parent has one top-most pair.

| What you find | Action |
| --- | --- |
| Exactly one top-most pair | Keep the parent, add both terms to `terms` before step 2, and state which terms were added and why |
| No pair, and the tree ends within three levels | Continue with the parent only and say no pair exists |
| Anything else: several top-most pairs, a pair you are unsure is opposite, or a tree deeper than three levels with no pair found | Stop and ask |

Skip this whole check for exact-only requests, or when the user limits the
analysis to specified terms.

When you stop, check each candidate pair has IMPC data: run step 2's count
query (`rows: 0`) for both terms. Drop pairs where both terms have no rows, and
say how many were dropped. List the rest as numbered options, each showing
both ids, labels, the level below the parent and the row count per term. Mark
the pair with the most rows "(recommended)". Also offer "the parent only", and
"search further down" when the tree goes deeper. The user can also name terms
of their own. Wait for the answer, and never pick a pair silently: the choice
changes every gene set downstream.

Query each direction separately with the same sex, zygosity, life-stage and
other filters. Include its descendants under the usual matching rule. Keep
genes associated with both directions in both sets and report their overlap;
opposite calls can occur in different experimental contexts. Leave rows with
only a parent annotation in the parent set. Record zero-result directions in
`01_resolved_terms.csv`; do not interpret missing data as absence of biology.

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
import json
from pathlib import Path

import pandas as pd
from impc_api import solr_request, batch_solr_request

terms = {"MP:0010119": "abnormal bone mineral density"}  # confirmed in step 1
exact_only = False  # True only if the user asks for exact matches
result_dir = Path("<result dir>")
levels = ["exact", "intermediate", "top_level"]
fields = ("marker_accession_id,marker_symbol,mp_term_id,mp_term_name,intermediate_mp_term_id,"
          "p_value,effect_size,sex,zygosity,life_stage_name,phenotyping_center")
attempts = []  # request log; printed at the end for the README


def logged(purpose, function, **kwargs):
    """Record a request before sending it, then its outcome."""
    entry = {"order": len(attempts) + 1, "purpose": purpose, "function": function.__name__,
             "core": kwargs["core"], "params": dict(kwargs["params"]),  # copy before batching
             "options": {k: v for k, v in kwargs.items() if k not in ("core", "params")},
             "outcome": "not run"}
    attempts.append(entry)
    try:
        result = function(**kwargs)
    except Exception as e:
        entry.update(outcome="failed", error=f"{type(e).__name__}: {e}")
        raise
    n = result[0] if isinstance(result, tuple) else len(result)
    entry.update(outcome="failed" if n is None else "worked" if n else "zero results",
                 **{"num_found" if isinstance(result, tuple) else "rows": n})
    return result


resolved, frames = [], []
try:
    for term_id, label in terms.items():
        query = f'mp_term_id:"{term_id}"'
        if not exact_only:
            query = (f'({query} OR intermediate_mp_term_id:"{term_id}" '
                     f'OR top_level_mp_term_id:"{term_id}")')
        num_found, _ = logged(f"count rows for {term_id}", solr_request, core="genotype-phenotype",
                              params={"q": query, "rows": 0}, validate=True, silent=True)
        counts = dict.fromkeys(levels, 0)
        if num_found:
            df = logged(f"download rows for {term_id}", batch_solr_request,
                        core="genotype-phenotype", params={"q": query, "fl": fields},
                        batch_size=1000)
            df["match_level"] = [
                "exact" if row_term == term_id
                else "intermediate" if isinstance(ancestors, list) and term_id in ancestors
                else "top_level"
                for row_term, ancestors in zip(df["mp_term_id"],
                                               df.get("intermediate_mp_term_id", [None] * len(df)))
            ]
            rank = df["match_level"].map(levels.index)
            df["gene_match_level"] = (rank.groupby(df["marker_accession_id"]).transform("min")
                                      .map(levels.__getitem__))
            counts.update(df.drop_duplicates("marker_accession_id")["gene_match_level"].value_counts())
            attempts.append({"order": len(attempts) + 1, "function": "local", "outcome": "worked",
                             "purpose": f"{term_id}: label each row's match level, count each gene once",
                             "rows": len(df), "genes": int(sum(counts.values()))})
            frames.append(df.drop(columns="intermediate_mp_term_id", errors="ignore")
                          .assign(query_mp_term_id=term_id, query_mp_term_name=label))
        resolved.append({"mp_term_id": term_id, "mp_term_name": label, "rows": num_found,
                         **{key: int(counts[level]) for key, level in [
                             ("exact_genes", "exact"), ("intermediate_new_genes", "intermediate"),
                             ("top_level_new_genes", "top_level")]},
                         "total_genes": int(sum(counts.values()))})

    pd.DataFrame(resolved).to_csv(result_dir / "01_resolved_terms.csv", index=False)
    if frames:
        genes = pd.concat(frames, ignore_index=True)
        first = ["query_mp_term_id", "query_mp_term_name", "match_level", "gene_match_level"]
        genes[first + [c for c in genes.columns if c not in first]].to_csv(
            result_dir / "02_impc_genes.csv", index=False)
        # Which child terms each queried term's genes come from (a gene can count under several)
        (genes.groupby(["query_mp_term_id", "mp_term_id", "mp_term_name"])["marker_accession_id"]
         .nunique().rename("genes").reset_index()
         .sort_values(["query_mp_term_id", "genes"], ascending=[True, False])
         .to_csv(result_dir / "02_term_breakdown.csv", index=False))
finally:  # print the log even after a failed request
    print(json.dumps(attempts, indent=2, default=str))
```

Keep all zygosities, sexes and life stages unless the user filters; add a
filter such as `AND zygosity:homozygote` to the query. The code prints every
request and its outcome at the end, even after a failure; the README's Queries
section is written from that output.

### 3. Run enrichment

Run from this skill's directory, pointing at the result directory:

```bash
uv run --script scripts/string_ppi.py \
  --genes <result dir>/02_impc_genes.csv --out-dir <result dir>
```

For each term the script tests the mapped proteins against the proteome and
against IMPC-tested genes. With 2 or more terms it also tests their union as
`combined`, each gene once. Separate rows ask whether each phenotype's genes are
connected; `combined` asks about the network across phenotypes, and comparing
them shows whether one phenotype drives it. When `combined` holds the same genes
as a set already tested, such as a parent queried with its own children, it is
not tested again, and its rows name the set it repeats.

`--required-score` sets STRING's confidence threshold; the default, 400, matches
STRING's. Change it only on request, because results depend on it:
`references/string-ppi-guide.md` has the figures and each file's columns.

Each tested set also gets a link to its interactive STRING network, built from
the same proteins and score as the test. Sets over 300 proteins are flagged as
dense, and sets over 2,000 get no link because STRING's viewer stops there.

`--images` also saves a PNG of each network with 300 proteins or fewer to
`06_network_images/`, flattened onto white because STRING's PNGs are
transparent and turn black in dark viewers. Larger sets get no image, and
`network_view_status` says so. It is off by default because images are slow to
make and unreadable past a few hundred proteins (a 1,000-protein network came
to a 36 MB SVG). Run without it unless the user asks for images.

Genes map by MGI id, then by exact symbol match. If a test, link or image
request fails, or MCP falls back to REST, the script still writes all outputs
and exits 1: check `errors` in `string_run.json` and `status` in
`04_ppi_enrichment.csv`. If mapping or the IMPC-tested background download
fails, it stops with a traceback before writing `04_ppi_enrichment.csv`;
rerun, and report the error if it persists. Either way `string_run.json`
lists every request the script made, with its outcome.

STRING holds proteins only, so non-coding RNA genes (such as Mir or Snord
genes) and pseudogenes never map. IMPC has few of them; when genes do not map,
list them and say this may be why, without labelling any gene's type.

The script generates links for directional sets and `combined` as well; use
`string_network_url` from `04_ppi_enrichment.csv` without making duplicate
link requests or creating a separate links file. These links show STRING
functional associations, which need not be physical interactions. They do not
reproduce the custom IMPC-tested enrichment background; the saved enrichment
results remain the source for that test.

### 4. Report

Report in two layers: a short chat summary the user can skim, and `README.md`
with everything else. If the summary shows the run went well, the user opens
the README for a thorough inspection, so keep detail out of the chat.

**Chat summary.** In this order:

1. Terms analysed: the requested terms, any directional terms added and why,
   and any filters.
2. One table with a row per set: genes and proteins, observed edges, then
   expected edges and p-value under each background, side by side, and the
   set's `string_network_url` as a clickable Markdown link with the URL as its
   label, so it can be copied. Give the reason for any set not tested or
   without a link, and flag dense views, which load slowly.
3. Each number appears once, in the table; do not restate the rows in prose.
   Under the table, one line on how to read it, then the caveat: "Observed
   edges are STRING interactions among the set's proteins; expected edges are
   what the background predicts. These are STRING's p-values, uncorrected
   across sets, with no significance threshold applied. STRING interactions
   are functional associations, not necessarily physical binding." Do not call
   a network enriched, real or significant, even when the user asks a yes/no
   question: the observed and expected counts are the answer.
4. Images. With `--images`, say which sets have an image and which do not,
   and why: over 300 proteins, so use the set's network link instead.
   If the user asked for images and no set qualified, say so first and suggest
   narrower child terms. Without `--images`, say in one line that images are
   available on request and were left off, because they are slow to make,
   unreadable past a few hundred proteins and made only for sets of 300
   proteins or fewer.
5. Warnings: failed requests, MCP fallback, and unmapped genes, with the
   note that STRING holds proteins only, so non-coding RNA genes and
   pseudogenes cannot map.
6. The path to `README.md`, for images, the term breakdown and provenance.

**README.md.** Follow `impc-data-retriever/references/output-report.md`. Its
Queries section comes from the request log step 2 printed: give each request
its resolved call, with the term and query filled in, and the full step-2 code
once in a collapsed `<details>` block. Its Process log gives the script command
line and summarises `requests` from `string_run.json`. Include:

- the term resolution, and genes per level from `01_resolved_terms.csv`;
- for any term with descendants, that it merges them, possibly in opposite
  directions (see `references/string-ppi-guide.md`), with the top 10 rows per
  queried term from `02_term_breakdown.csv` and a link to the full file;
- the full results table from `04_ppi_enrichment.csv`, both backgrounds side by
  side, with `network_view_status` where there is no link or the view is dense;
- the background note from `references/string-ppi-guide.md`;
- that p-values are uncorrected across sets;
- unmapped genes with the same note, rejected symbol hits and sets not tested;
- each set's `string_network_url` as a clickable Markdown link with the URL as
  its label, so it can be copied, noting that dense views load slowly;
- each image embedded with `![<set> network](06_network_images/<file>.png)`,
  and the sets with no image and why, or that images are available with
  `--images` and why they were off;
- when opposite directions were compared, their gene counts and shared genes,
  pointing to their rows in the results table rather than repeating the
  p-values. Differences in p-values alone do not establish a statistical
  difference between directions. The parent may contain additional genes;
- values from `string_run.json`: STRING version, required score, background size.

Do not add network clustering, a cluster summary table or functional enrichment.
Do not test child terms separately unless the user asks: each extra set is
another small, uncorrected test. Show what a parent merges through
`02_term_breakdown.csv` instead. The one directional pair chosen in step 1
is the only exception.

## Output

| File | Contents |
| --- | --- |
| `01_resolved_terms.csv` | Term ids, labels, rows, and genes new at each level |
| `02_impc_genes.csv` | One row per IMPC statistical call, with queried term and match level |
| `02_term_breakdown.csv` | Genes per row-level MP term under each queried term |
| `03_string_mapping.csv` | One row per gene: STRING id, how it mapped, name differences |
| `04_ppi_enrichment.csv` | One row per gene set × background, with STRING's fields and a network link |
| `05_impc_tested_background.csv` | Proteins used as the IMPC-tested background |
| `06_network_images/` | PNG on white per set of 300 proteins or fewer; only with `--images` |
| `string_run.json` | Versions, parameters, mapping counts, errors, and every STRING-step request with its outcome |
| `README.md` | Report and provenance |

## Example prompt

> Find IMPC genes associated with abnormal bone mineral density, compare
> decreased versus increased bone mineral density, run PPI enrichment against
> both backgrounds, and give me clickable STRING network links.

## Stopping rules

- **No term resolves:** stop and show what OLS returned.
- **Opposite directions unclear:** several candidate pairs, an uncertain pair,
  or no pair within three levels of a deeper tree. Stop, list the options and
  wait (step 1).
- **A term has 0 rows:** keep it in `01_resolved_terms.csv` and continue with
  the others. If no term has rows, skip step 3 and write only the README and
  `01_resolved_terms.csv`.
- **Fewer than 2 mapped proteins:** the genes stay in `02_impc_genes.csv` and in
  `combined`, and `04_ppi_enrichment.csv` shows the set as not tested. One
  protein has no pairs to test, and STRING would add its neighbours and test
  those instead.
