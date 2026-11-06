# Confirming MP terms and traits given by label

Used by the MP-term and reverse (trait) paths before any IMPC or GWAS search.

## Why

Labels are error-prone: near-identical labels carry different ids, and the
top search hit is often not the term meant. A wrong id silently changes every
downstream gene, study and score. Examples from OLS (2026-11-05):

| User wrote | What OLS returns |
| --- | --- |
| "increased cholesterol" (MP) | An enzyme-activity term first (MP:0011599), then MP:0005178 *increased circulating cholesterol level* (blood) and MP:0003982 *increased cholesterol level* (whole body) |
| "decreased BUN" (MP) | MP:0005566 *decreased blood urea nitrogen level*, matched through a synonym, not the label |
| "hypercholesterolemia" (trait) | HP:0003124 *Hypercholesterolemia*, listed under hp, efo and mondo, plus MONDO familial forms (MONDO:0007750 *hypercholesterolemia, familial, 1*, MONDO:0011374, ...) |
| "ankylosing spondylitis" (trait) | MONDO:0005306, EFO:0022377 *ankylosing spondylitis disease activity score*, MONDO:0020655 *juvenile ankylosing spondylitis*, and veterinary forms (MONDO:1011150, dog) |

## Search

- MCP: OLS `searchClasses` or `search`.
- REST: `https://www.ebi.ac.uk/ols4/api/search?q=<label>&ontology=mp` for MP
  terms, `ontology=efo,mondo,hp` for traits; add
  `fieldList=obo_id,label,ontology_name,is_defining_ontology,is_obsolete,description`.

Clean the hits before showing them:

- drop obsolete terms (`is_obsolete`);
- keep each id once: OLS lists an imported id under every ontology that
  imports it (HP:0003124 appears under hp, efo and mondo); keep the row whose
  `is_defining_ontology` is true;
- keep the top 5.

## Candidate table

Columns: id, label, ontology, definition (first sentence), and whether the
label or a synonym matched. Name your best guess, ask which id to use, and
wait for the answer.
