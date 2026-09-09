# PhenoDigm Score Interpretation

Use this guide when the user asks for an interpretation of a PhenoDigm score.

## Required Data

Before interpreting a score, follow the same-core, multi-request workflow in
[the PhenoDigm guide](phenodigm-guide.md) and retrieve:

1. The selected `type:disease_model_summary` record, including
   `disease_id`, `model_id`, the server-derived `phenodigm_score`,
   `disease_matched_phenotypes`, and `model_matched_phenotypes`.
2. The corresponding `type:disease` record, selected by the exact returned
   `disease_id`, including `disease_phenotypes` as the complete human disease
   phenotype profile.
3. The corresponding `type:mouse_model` record, selected by the exact returned
   `model_id`, including `model_phenotypes` as the complete phenotype profile
   for that mouse model.

If either profile lookup fails or returns zero records, follow the bounded
validation and retry rules in the main skill. Because the summary record
references both identifiers, treat a still-unresolved lookup as a likely query
or transport problem, not as evidence that the disease or model has no
phenotype data. Stop the profile-based interpretation, report the exact
`disease_id` or `model_id` and the failed query, and ask the user to review the
lookup. Do not substitute another core or infer phenotype coverage.

## Interpretation Guidance

PhenoDigm scores summarize ontology-based similarity between the phenotypes of
a mouse model and a human disease. Higher scores indicate stronger overall
phenotypic similarity, but the score alone does not establish whether a model
is useful for a particular research goal.

Use these DR24 reference bands for a general interpretation:

- High: above 40.
- Intermediate: 30–40, around the DR24 mean of 31.70.
- Low: below 30; these matches can still be useful in context.

Review `phenodigm_score`, `disease_matched_phenotypes`, and
`model_matched_phenotypes`. Compare the matched phenotypes with the complete
`disease_phenotypes` and `model_phenotypes` profiles to understand the match's
context.

Count distinct, non-empty values in the matched and complete arrays and derive:

- matched disease phenotype count and total disease phenotype count;
- matched model phenotype count and total model phenotype count.

Use these counts as descriptive context only. They do not reproduce or replace
the ontology-based PhenoDigm score, and a simple matched-to-total ratio does not
capture phenotype specificity or semantic similarity.

Regardless of the score, evaluate the quality and relevance of the matched
phenotypes. If the user stated a research goal, interpret the match against that
goal. Otherwise, provide a general interpretation, explain that usefulness is
goal-dependent, and offer these options for a more specific interpretation:

- Targeted: whether the model captures a particular high-priority phenotype.
- Breadth: whether the model recapitulates a broad range of disease phenotypes.

Do not infer the user's goal. Ask which option they want if they would like a
goal-specific follow-up.

### Interpreting very high scores (above 90)

Inspect a score above 90 carefully, especially when only one or two phenotypes
are matched. Use the matched and total counts to distinguish a strong match to
a sparsely annotated disease from broader phenotype coverage. Even with broad
coverage, check whether the matched phenotypes include the critical or
characteristic disease features relevant to the user's goal.

### Interpreting low scores (below 30)

If the score is below 30 but several relevant phenotypes are matched, the model
may still be useful for studying specific disease features. If both the matched
count and its context within the complete profile indicate limited coverage,
describe the model as a weak broad phenotypic match. A few biologically relevant
matches may still make it useful for a targeted goal.

## Response Requirements

Present the server-derived score, its general reference band, the distinct
matched and total counts for both disease and model phenotypes, and the most
relevant matched phenotypes. Use the complete profiles during analysis, but do
not reproduce them by default. Include a complete list only when it is short or
the user explicitly requests it.

Provide a concise interpretation using the score's position relative to the
release mean, the number and relevance of matched phenotypes, and the disease
and model profile context. Then assess usefulness against the user's stated
goal. If no goal was provided, give only a general assessment, state that the
practical interpretation is goal-dependent, and offer the targeted and breadth
options above. Do not interpret the numeric score without profile context.
