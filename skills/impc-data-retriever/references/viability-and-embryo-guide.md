# Viability and embryo data

## Translate the biological question first

For primary-screen lethal/subviable calls, start with **preweaning lethality**
IDs rather than free text. For explicitly embryonic, prenatal or postnatal
requests, preserve that timing constraint and select the corresponding branch
below. Preweaning covers fertilization through weaning; it does not establish
that death occurred before birth.

| User meaning | MP term | Interpretation |
| --- | --- | --- |
| Lethal / complete preweaning lethality | `MP:0011100` — preweaning lethality, complete penetrance | Primary-screen lethal call. |
| Subviable / partial preweaning lethality | `MP:0011110` — preweaning lethality, incomplete penetrance | Some mutants survive; keep separate from complete lethality. |
| Preweaning lethality broadly | `MP:0010770` — preweaning lethality | Broad term; an exact-ID query does not automatically include descendant annotations. |
| Viable | Explicit viability outcome | Do not infer this from absence of the above annotations. |
| Embryonic lethality / embryonic death | `MP:0008762` — embryonic lethality | Use the branch for stage-specific descendants; do not substitute all preweaning calls. |
| Prenatal lethality | `MP:0002080` — prenatal lethality | Broader prenatal scope than the embryonic term. |
| Postnatal lethality | `MP:0002082` — postnatal lethality | Keep separate from prenatal and generic preweaning calls. |

If the user supplies an MP ID, preserve it and state whether the query means
direct annotations or the term plus descendants. For “all phenotypes under” a
term, or a broad named phenotype, default to the branch. For primary-screen
“lethal” versus “subviable” classifications, use the two exact calls above.
Do not silently add “complete penetrance” to an embryonic lethality request.

The [IMPC embryo overview](https://www.mousephenotype.org/data/embryo)
describes lethal lines as having no homozygous null pups at weaning and
subviable lines as having fewer than 12.5% homozygous pups. Use the recorded
call rather than reclassifying from this summary: procedure versions have
sample-size, breeding-design, sex-linked and boundary rules. See the
[Viability Primary Screen protocol](https://www.mousephenotype.org/impress/ProcedureInfo?action=list&procID=1231)
and [outcome-to-MP mappings](https://web.mousephenotype.org/impress/OntologyInfo?action=list&procID=710).

## Retrieve phenotype associations

Use `genotype-phenotype` and the [core guide](genotype-phenotype-guide.md).
Select the clause matching the request:

```python
# Complete lethality only:
q = 'mp_term_id:"MP:0011100"'

# Subviability only:
q = 'mp_term_id:"MP:0011110"'

# Direct annotations to these three terms (not every descendant):
q = 'mp_term_id:("MP:0010770" OR "MP:0011100" OR "MP:0011110")'
```

For the broader ontology branch, the `genotype-phenotype` schema exposes
`intermediate_mp_term_id` for ancestor matching. Choose this up front for a
broad request; do not first query only the parent and mistake zero direct
annotations for absence of the phenotype:

```python
q = '(mp_term_id:"MP:0010770" OR intermediate_mp_term_id:"MP:0010770")'

# Embryonic lethality, including stage-specific descendants:
q = '(mp_term_id:"MP:0008762" OR intermediate_mp_term_id:"MP:0008762")'
```

Validate against the installed schema and retain the returned `mp_term_id` and
`mp_term_name`: a branch match is not necessarily a complete-lethality call.
Do not describe the three-ID query as exhaustive ontology expansion.
Use the same exact-or-ancestor pattern for another resolved branch ID. A zero
result for an explicitly requested penetrance-specific term must stay a zero
result; do not silently replace it with a broader penetrance-unspecified term.

Facet a branch by `mp_term_id` (`rows: 0`, `facet: "on"`,
`facet.field: "mp_term_id"`, `facet.limit: -1`, `facet.mincount: 1`) to see
which annotations it actually contains. Inspect names in returned records.
`validate=True` checks the package's core/return-field schema; it does not
prove query semantics or ontology coverage.

Preview the selected query before downloading, following the main skill's
bounded stopping and reporting rules:

```python
from impc_api import solr_request

num_found, df = solr_request(
    core="genotype-phenotype",
    params={
        "q": q,
        "rows": 20,
        "fl": "marker_accession_id,marker_symbol,allele_accession_id,"
              "allele_symbol,colony_id,mp_term_id,mp_term_name,zygosity,sex,"
              "phenotyping_center,pipeline_stable_id,procedure_stable_id,"
              "parameter_stable_id,life_stage_name,statistical_method,p_value",
    },
    validate=True,
)
```

Add requested gene/allele constraints with `AND` around a grouped phenotype
clause. Do not automatically restrict to an embryo life stage: primary viability
screening and embryo follow-up are different assays. Do not add an arbitrary
p-value cutoff to viability calls; annotations may be manual.

Use `statistical-result` when statistical evidence is requested. There,
`mp_term_id_options` identifies possible assay outcomes, not proof that a
particular phenotype was observed. Inspect the actual `mp_term_id`,
`significant` and `statistical_method` using the
[statistical-result guide](statistical-result-guide.md).

## Retrieve viable calls and supporting observations

For “which lines are viable?” or a complete viability classification, use
`experiment` to retrieve explicit primary-screen outcomes, following the
[experiment guide](experiment-guide.md). Discover the complete
pipeline/procedure/parameter triplets for **Viability Primary Screen**;
`IMPC_VIA_001` and `IMPC_VIA_002` are starting points for discovery, not an
exhaustive list of centre/version variants.

Inspect outcome parameters and their observed categories before filtering.
Include `category`, `data_point`, `parameter_name`, the triplet, gene and allele
accessions, `colony_id`, `phenotyping_center`, `sex` and `zygosity`. Categorical
outcomes need not be in numeric `data_point`. Preserve the original outcome and
distinguish viable, lethal, subviable, insufficient-data and unavailable calls.
Neither a nonsignificant statistical result nor a missing association is an
explicit viable outcome.

## Embryonic timing and interpretation

Stage-specific annotations observed in live IMPC queries:

| MP ID | Returned phenotype name |
| --- | --- |
| `MP:0013292` | embryonic lethality prior to organogenesis |
| `MP:0013293` | embryonic lethality prior to tooth bud stage |
| `MP:0013294` | prenatal lethality prior to heart atrial septation |

These are useful exact-ID starting points when the requested phenotype matches;
they are not an exhaustive list. Preserve their returned names and do not append
“complete penetrance”. The [E12.5 secondary-screen mapping](https://www.mousephenotype.org/impress/OntologyInfo?action=list&procID=178)
maps its lethal outcome to `MP:0013293`. A screening timepoint is not an exact
time of death.

For a **window of lethality**, retrieve stage-specific secondary viability
evidence; the three MP terms above alone cannot establish the time of death.
The embryo overview describes E12.5 assessment followed by earlier/later
investigation and links stage-specific results and imaging. Discover actual
stage values and assay triplets rather than assuming every line has all stages.
Use `impc_images` only when images are requested; image availability is not a
viability call. Follow the [multi-core guide](multi-core-query-guide.md) when
combining these evidence types.

Keep calls at their recorded allele/colony/centre and genotype context. Adult
heterozygote data do not contradict homozygous lethality. Preserve discordant
calls rather than forcing one status per gene. If a gene list is requested,
deduplicate by gene accession only after retaining supporting line-level calls;
report gene and line counts separately. Record query scope, source/release when
available and missing evidence in the retrieval report.
Treat zero matches as “no matching annotations in this core/query”, not as
evidence that the genotype is viable or that no animals died during that stage.

## Phenotype pages

- [MP:0011100 — complete penetrance](https://www.mousephenotype.org/data/phenotypes/MP:0011100)
- [MP:0011110 — incomplete penetrance](https://www.mousephenotype.org/data/phenotypes/MP:0011110)
- [MP:0010770 — preweaning lethality](https://www.mousephenotype.org/data/phenotypes/MP:0010770)
