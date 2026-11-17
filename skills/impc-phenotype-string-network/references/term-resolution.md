# Resolving phenotype input to MP ids

## Why

A wrong id silently changes every gene downstream, and near-identical labels
carry different ids. OLS turns each label into an id, but asking the user every
time adds friction when the match is plain. So ask only when the match is not
clean.

## Lookup

- MCP: OLS `searchClasses` with `ontologyId: "mp"`.
- REST fallback:
  `https://www.ebi.ac.uk/ols4/api/search?q=<label>&ontology=mp&fieldList=obo_id,label,is_defining_ontology,is_obsolete,description`
- Id lookup: search the id itself the same way, or call OLS `fetch`.
- Children, for the opposite-direction check: MCP `getChildren`, or REST
  `https://www.ebi.ac.uk/ols4/api/ontologies/mp/terms/<IRI>/children?size=500`,
  where `<IRI>` is the term IRI encoded twice, for MP:0010119
  `http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FMP_0010119`. Keep only
  `obo_id`, `label` and `has_children`, and expand only terms with
  `has_children` true.

Clean the hits: drop obsolete terms, keep terms defined by MP (`MP:` ids), keep
each id once and keep the top 5.

## When to ask

| Input | OLS result | Action |
| --- | --- | --- |
| Label | Exact label match (ignoring case) on one active term | Continue without asking |
| Label | Synonym match, several candidates, or no match | Show candidates and wait |
| Id | Active, and any label given with it fits | Continue without asking |
| Id | Obsolete, or the label given with it does not fit | Ask |

A single hit is not enough on its own. "low body weight" returns one term,
MP:0001262 *decreased body weight*, but only through a synonym, so ask.

## Candidate table

Columns: id, label, definition (first sentence), matched on (label or synonym).
Name your best guess, ask which id to use, and wait. Never type an id from
memory.
