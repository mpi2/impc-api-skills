# Phenotype ↔ trait similarity with the OLS MCP server

Endpoint: `https://www.ebi.ac.uk/ols4/api/mcp` (Streamable HTTP, public, no auth).
Add it to the client as `ols` if you want to call tools interactively; the bundled
`scripts/ols_similarity.py` talks to the same endpoint directly and needs no client setup.

## What the server can do for this task

| Tool | Use it for | Notes |
| --- | --- | --- |
| `getClassSimilarity(classIri1, classIri2, model)` | The score. Cosine similarity (0–1) of two classes' precomputed embeddings. | Works for any two IRIs OLS has embedded (MP, EFO, OBA, HP, MONDO all present). This is the tool behind `scripts/ols_similarity.py`. |
| `listEmbeddingModels()` | Discover model names. | Four today; see "Choosing the model" below. The `can_embed` flag is irrelevant for pair scoring: stored class embeddings exist for every listed model. |
| `getSimilarClasses(classIri, model, pageSize)` | Nearest neighbours of one class across *all* OLS ontologies. | No score in the response and no ontology filter, so it is a browsing aid, not a scoring tool. Useful to sanity-check that an MP term's neighbourhood contains the EFO/OBA/HP terms you expect. |
| `searchClasses(query, ontologyId)` | Label lookup (lexical). | Only to look up a label or definition for an id you already have; the skill does not use it to assign new terms to studies. |
| `getAncestors` / `getDescendants` / `getChildren` | Hierarchy context. | Helpful to explain a match (e.g. both terms sit under a "blood metabolite level" branch) or to expand a broad EFO trait to its measurement descendants. |

## IRI forms

`getClassSimilarity` needs full IRIs. The script converts common id forms; when calling the MCP tool by hand use:

| Id as you get it | IRI |
| --- | --- |
| `MP:0005566` (IMPC `mp_term_id`) | `http://purl.obolibrary.org/obo/MP_0005566` |
| `EFO_0001360` (Open Targets) / `EFO:0001360` | `http://www.ebi.ac.uk/efo/EFO_0001360` |
| `MONDO_0005148`, `HP_0000924`, `OBA:VT0005265` | `http://purl.obolibrary.org/obo/<PREFIX>_<local>` |
| `Orphanet_558` | `http://www.orpha.net/ORDO/Orphanet_558` |
| GWAS Catalog `efoTraits[].uri` | already an IRI |

## What the score is

`getClassSimilarity` returns the cosine similarity of two classes' precomputed
embeddings (label plus definition text) under the chosen model, in 0–1. It is a
property of the two term descriptions and of the model. Example values on the
precision model (`text-embedding-3-large_pca512`), shown only to give a sense of
the scale:

| Pair | Similarity |
| --- | ---: |
| MP decreased blood urea nitrogen level ↔ OBA blood urea nitrogen amount | 0.86 |
| MP increased circulating sodium level ↔ OBA blood urea nitrogen amount | 0.67 |
| MP decreased blood urea nitrogen level ↔ EFO type 2 diabetes | 0.60 |
| MP preweaning lethality ↔ EFO ankylosing spondylitis | 0.50 |

Two facts about the scale that hold for embedding models in general:

- values compress into a narrow band (here roughly 0.45–0.90 for any two
  biomedical terms), so 0 is never observed and the ordering within a run
  carries more information than the absolute value;
- absolute values differ between models (`llama-embed-nemotron-8b_pca512`
  gave 0.84 for the top pair above, same ordering), so a score is only
  meaningful together with the model name.

There is no validated threshold. The bands used in earlier drafts of this skill
came from about twenty hand-picked pairs and were removed. Report the number,
the two labels, the model, and the run's distribution (min / median / max), and
leave the judgement to the reader. The user-facing table uses a display cutoff
(default 0.60, or whatever the user asks for), stated as a display choice.

Two things to keep in mind when reading a score: similarity compares concept
descriptions, so a measurement trait ("BUN amount") and a directional phenotype
("decreased BUN") can score high although the trait carries no direction; and
a high score says the two terms describe similar biology, not that the mouse
phenotype and the human GWAS association share a mechanism, nor that the L2G
gene assignment is causal. Keep the three layers (IMPC evidence, L2G evidence,
semantic similarity) visible and separate in the report.

## Choosing the model

Two models are used for phenotype ↔ trait scoring, chosen on empirical
experience with these ontologies:

| Offer it as | Model | When |
| --- | --- | --- |
| **breadth** (default) | `harrier-oss-v1-27b_pca512` | Broader ontology coverage, more scores above the floor. For "deep cuts": traits a phenotype relates to that a tighter model would leave at background. |
| **precision** | `text-embedding-3-large_pca512` | Tighter distribution. For "closest single trait" questions. |

On the same 2,162 Robinow pairs: harrier min 0.47 / median 0.63 / max 0.85;
large min 0.48 / median 0.59 / max 0.82; neither failed a pair. Ordering at
the top agreed on the pairs checked (e.g. decreased BUN ↔ BUN amount: 0.87 vs
0.86); the middle of the distribution differs, which is where breadth shows.

Give the user the choice; default to breadth and say so. Running both
(`--model harrier-oss-v1-27b_pca512 text-embedding-3-large_pca512`) yields one
row per pair per model with per-model ranks, for side-by-side reading.

The other two models OLS lists (`text-embedding-3-small_pca512`,
`llama-embed-nemotron-8b_pca512`) also score class pairs but are not used by
this skill. `listEmbeddingModels` shows the live list; check it when a run
happens long after this was written.

## Running the batch script

```bash
uv run skills/impc-gwas-trait-mapper/scripts/ols_similarity.py \
  --phenotypes 01_impc_phenotypes.csv --phenotype-id-col mp_term_id --phenotype-label-col mp_term_name \
  --traits 04_gwas_traits.csv --trait-id-col trait_id --trait-label-col trait_label \
  --out 05_phenotype_trait_similarity.csv
```

- Input rows are deduplicated on the id column, so the raw genotype-phenotype
  table can be passed straight in.
- Output is long format: one row per phenotype × trait with `similarity`,
  `rank_within_phenotype`, `rank_within_trait`, `model` and an `error` column
  for pairs OLS could not score (for example an obsolete or unembedded class).
  Keep the failed pairs in the report; do not silently drop them.
- ~30 pairs/second with 4 workers. A few hundred pairs is fine; for thousands,
  reduce the trait list first (e.g. keep only traits from credible sets where
  the gene is in the top 3 L2G genes).
- `--min-score` filters the written rows but ranks are computed before
  filtering, so `rank_within_phenotype == 1` still means "best trait for this
  phenotype".
