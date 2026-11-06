# Phenotype ↔ trait similarity with the OLS MCP server

Endpoint: `https://www.ebi.ac.uk/ols4/api/mcp` (Streamable HTTP, public, no auth).
Add it to the client as `ols` if you want to call tools interactively; the bundled
`scripts/ols_similarity.py` talks to the same endpoint directly and needs no client setup.

## What the server can do for this task

| Tool | Use it for | Notes |
| --- | --- | --- |
| `getClassSimilarity(classIri1, classIri2, model)` | The score. Cosine similarity (0–1) of two classes' precomputed embeddings. | Works for any two IRIs OLS has embedded (MP, EFO, OBA, HP, MONDO all present). This is the tool behind `scripts/ols_similarity.py`. |
| `listEmbeddingModels()` | Discover model names. | Four today; see "Choosing the model" below. The `can_embed` flag is irrelevant for pair scoring: stored class embeddings exist for every listed model. |
| `getSimilarClasses(classIri, model, pageSize)` | Nearest neighbours of one class across *all* OLS ontologies. | No score in the response and no ontology filter, so it is a browsing aid, not a scoring tool. For per-ontology neighbours with scores, the script uses the REST endpoints below. |
| `searchClasses(query, ontologyId)` | Label lookup (lexical). | Only to look up a label or definition for an id you already have; the skill does not use it to assign new terms to studies. |
| `getAncestors` / `getDescendants` / `getChildren` | Hierarchy context. | Helpful to explain a match (e.g. both terms sit under a "blood metabolite level" branch) or to expand a broad EFO trait to its measurement descendants. |

## IRI forms

`getClassSimilarity` needs full IRIs. The script converts common id forms; when calling the MCP tool by hand use:

| Id as you get it | IRI |
| --- | --- |
| `MP:0005566` (IMPC `mp_term_id`) | `http://purl.obolibrary.org/obo/MP_0005566` |
| `EFO_0001360` (Open Targets) / `EFO:0001360` | `http://www.ebi.ac.uk/efo/EFO_0001360` |
| `MONDO_0005148`, `HP_0000924`, `OBA:VT0005265`, `GO_0061476` | `http://purl.obolibrary.org/obo/<PREFIX>_<local>` |
| `Orphanet_558` | `http://www.orpha.net/ORDO/Orphanet_558` |

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
leave the judgement to the reader. With the top-K filter on (default), the
filter is the selection rule and no similarity cutoff is applied: every pair
that passes is shown, ranked, top 10 in the chat table. Only with `--top-k 0`
does the user-facing table use a display cutoff (default 0.60, or whatever the
user asks for), stated as a display choice.

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
| **precision** (default) | `text-embedding-3-large_pca512` | Tighter distribution. For "closest single trait" questions, which is what the top-20 neighbourhood filter asks per ontology. |
| **breadth** | `harrier-oss-v1-27b_pca512` | Broader ontology coverage, more scores above the floor. For "deep cuts": traits a phenotype relates to that a tighter model would leave at background. Too broad for the top-20 filter. |

On the same 2,162 Robinow pairs: harrier min 0.47 / median 0.63 / max 0.85;
large min 0.48 / median 0.59 / max 0.82; neither failed a pair. Ordering at
the top agreed on the pairs checked (e.g. decreased BUN ↔ BUN amount: 0.87 vs
0.86); the middle of the distribution differs, which is where breadth shows.

Give the user the choice; default to precision and say so. Running both
(`--model harrier-oss-v1-27b_pca512 text-embedding-3-large_pca512`) yields one
row per pair per model with per-model ranks, for side-by-side reading.

The other two models OLS lists (`text-embedding-3-small_pca512`,
`llama-embed-nemotron-8b_pca512`) also score class pairs but are not used by
this skill. `listEmbeddingModels` shows the live list; check it when a run
happens long after this was written.

## Running the batch script

```bash
uv run skills/impc-human-evidence-explorer/scripts/ols_similarity.py \
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
- `--min-score` filters the written rows but ranks are computed before
  filtering, so `rank_within_phenotype == 1` still means "best trait for this
  phenotype" among the rows the mode produced.

### Top-K neighbourhood filter (default, `--top-k 20`)

For each MP term (and each model):

1. `GET /api/v2/classes/{iri}/llm_embedding?model=…` fetches the MP term's
   stored vector (512 numbers).
2. `POST /api/v2/ontologies/{onto}/classes/llm_embedding?model=…&size=…&isDefiningOntology=true&includeCurations=false`,
   with that vector as the body, returns the nearest classes defined in
   `onto`, with a `score`. This runs for each of `--ontologies` (default
   `efo mondo oba hp go`). Because of `isDefiningOntology=true`, the EFO list holds
   only classes EFO defines, not the MONDO/OBA/HP classes it imports, so the
   lists do not overlap.
3. Obsolete classes (`isObsolete`) and excluded branches are dropped. With
   `--top-k-scope per-ontology` (default), the K best in each ontology are
   kept (up to K × number of ontologies neighbours); with `pooled`, the K best
   across all ontologies.
4. A GWAS trait (matched by IRI) is kept for the MP term only if it is among
   those neighbours, i.e. in the top K of its own ontology under the default.
   Kept pairs are scored with `getClassSimilarity`.

Outputs: `--out` has only the kept pairs, with the usual columns plus
`knn_rank` (1…K, within `knn_ontology` under the default), `knn_score` and
`knn_ontology`. `<out>_neighbours.csv` (or `--neighbours-out`) lists all
neighbours per MP term with `is_gwas_trait`; it shows what the traits
competed against. An MP term whose embedding OLS lacks gets an `error` row in
both files.

Why per-ontology is the default: in a pooled run, MONDO (many fine-grained
disease classes) and HP (built to mirror MP, so its nearest classes are
near-copies of the MP term: decreased BUN → "Reduced blood urea nitrogen",
0.94) take most slots. On Robinow (measured at K = 10), pooled kept 0 pairs,
with MONDO holding 266 of 470 slots even without HP; per-ontology kept 8 (e.g.
abnormal placenta morphology → placental retention, EFO rank 1). Giving each
ontology its own K means a trait competes only with classes of the same kind.

#### Why K = 20

Measured 2026-11-05 with the precision model: one `--top-k 100` run per gene
set, then pairs counted by `knn_rank`. Inputs were the CYP2C19 (via Cyp2c38),
AARS1, Tyk2 + Ldlr and Mtor runs: 37 MP terms, 171 trait ids.

| K | Pairs kept | MP terms with a pair | Traits with a pair | Min similarity | Median |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 15 | 7 | 10 | 0.73 | 0.79 |
| 20 | 25 | 8 | 16 | 0.71 | 0.79 |
| 30 | 36 | 10 | 23 | 0.68 | 0.79 |
| 50 | 46 | 14 | 28 | 0.68 | 0.78 |
| 100 | 82 | 22 | 48 | 0.63 | 0.74 |

The 10 pairs at ranks 11–20 are of the same kind as ranks 1–10: enlarged
heart ↔ heart disorder (MONDO rank 11, 0.83) and ↔ heart failure (14, 0.82),
increased HDL cholesterol ↔ Hypercholesterolemia (HP 12, 0.86), abnormal
inspiratory capacity ↔ FEV/FVC ratio (EFO 15, 0.71), increased circulating
sodium ↔ primary aldosteronism (MONDO 11, 0.77). From about rank 25,
unrelated pairs start to appear next to related ones: increased lean body
mass ↔ hypertensive disorder (MONDO 24), increased bone mineral content ↔
hypertensive disorder (MONDO 29), abnormal spleen morphology ↔ aneurysm
(EFO 61), thrombocytopenia ↔ factor VIII measurement (EFO 93). MONDO supplies
most hits (20 of 25 at K = 20); GO and OBA supply none before rank 50.

The sample is small: 8 of the 10 added pairs come from Tyk2 + Ldlr, 2 from
Mtor. A larger K does not rescue a gene whose traits are far from its
phenotypes: CYP2C19's drug-response and cancer traits gain nothing at K = 20.

Things that were checked against the live API (2026-11) and shape the code:

- `knn_score` is not the same number as `getClassSimilarity` for the same
  pair, because the search index holds label/synonym embeddings, not the
  class embedding. With `includeCurations=false` the two differ by up to about
  0.02 (decreased BUN ↔ OBA BUN amount: 0.895 vs 0.879). With curations on,
  curated text-to-term mappings lift unrelated classes (↔ "metabolite
  measurement": 0.834 vs 0.692), so the script turns curations off. Use
  `knn_score` only to decide membership of the top K; report `similarity`.
- `getClassSimilarity` equals `(1 + cos) / 2` of the two stored vectors (checked
  to 4 decimals on two models). That is why scores sit in roughly 0.45–0.90:
  raw cosines of biomedical terms are roughly −0.1 to 0.8.
- The search's `page` parameter returns page 0 again, so the script asks for
  one bigger page (≥ 3K, doubled while obsolete classes leave fewer than K).
  Near-ties come back in varying order, so hits are re-sorted by score, then IRI.
- MONDO's non-human animal disease branch (`MONDO:0005583`, ~8,300
  descendants: "…, cattle", "…, non-human animal") is dropped by default
  (`--exclude-branch`). The check uses each hit's `hierarchicalAncestor`,
  which the search returns, so it costs no extra calls. Pass
  `--exclude-branch` with no value to keep the branch, or add other roots.
Cost: 1 + len(ontologies) REST calls per MP term per model, ~0.5–2.5 s each
(47 MP terms × 4 ontologies → ~45 s with 6 workers), plus one
`getClassSimilarity` per kept pair. Trait list size does not affect the cost,
and neither does K: K sets the page size of each search (`max(3K, 30)`, so 60
at K = 20), not the number of searches.

### All pairs (`--top-k 0`)

Scores every phenotype × trait pair with `getClassSimilarity`, with no
neighbourhood filter. ~30 pairs/second with 4 workers. A few hundred pairs is
fine; for thousands, reduce the trait list first (e.g. keep only traits from
credible sets where the gene is in the top 3 L2G genes).
