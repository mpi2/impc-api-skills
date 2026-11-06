# UniProt: mouse gene → UniProt accession

Experimental addition (step 2c). Not covered by evals until it is made definitive.

Step 2c translates the IMPC genes (MGI ids) into mouse UniProt accessions, so
that UniProt data can be attached to them. This guide covers that translation.
What is done with the accessions is added here section by section as each use
is settled.

## Sources

1. **Local IMPC → UniProt mapping file**, `results/uniprot/uniprot_mapping.tsv`
   (downloaded 2026-10-30). Local and gitignored (`results/` and `uniprot`
   are both in `.gitignore`); it does not ship with the skill. Only two
   columns are used: `UniProt ID` and `Link` (the MGI gene id).
2. **UniProt REST** for every MGI id the file does not have:
   `https://rest.uniprot.org/uniprotkb/search?query=xref:mgi-1929470 AND organism_id:10090`.

The file is not a complete mapping. It is IMPC's bibliography feed to UniProt
(it also has `PubMed ID` and an allele `Annotation` column, which the skill
does not use), so it holds only the 4,039 genes that have an IMPC-allele
paper. Tyk2 (MGI:1929470) is not in it. For a gene the file does have, its
accessions matched UniProt REST exactly on the gene checked (Agpat4: Q8K4X7
plus three TrEMBL fragments), and REST is not asked again, so TrEMBL
accessions added to UniProt after the download are not listed.

## Script

```bash
uv run skills/impc-gwas-trait-mapper/scripts/uniprot_mapping.py \
  --from-csv 01_impc_phenotypes.csv --id-col marker_accession_id --out 02_uniprot_accessions.csv
```

Selection: `--mgi`, `--from-csv` + `--id-col` (`mgiGeneAccId` for
`02_orthologs.csv`), or `--accessions` for the reverse direction. `--offline`
uses the file only (no fallback, no annotation, so no `is_primary`).
`--mapping` overrides the file path; when the file is missing the script uses
REST alone and says so.

Run it on `01_impc_phenotypes.csv`: the mapping is mouse-side, so genes
without a one-to-one human ortholog are kept.

`--out`, one row per gene × accession, reviewed first:

| Column | Meaning |
| --- | --- |
| `mgi_id` | Mouse gene |
| `uniprot_accession` | Mouse UniProt accession |
| `is_primary` | The reviewed (Swiss-Prot) accession to use downstream; none marked when a gene has no reviewed entry |
| `reviewed` | `reviewed` (Swiss-Prot) or `unreviewed` (TrEMBL) |
| `uniprot_gene`, `protein_name`, `length` | From UniProt REST; `uniprot_gene` is the current symbol |
| `source` | `mapping_file` or `uniprot_rest` |
| `uniprot_url` | Entry page |

stderr reports the file's gene count and modification date, how many genes
came from the file and how many from REST, MGI ids found nowhere, and any
accession UniProt no longer returns (merged or obsolete since the download).

## Quirks

- **Many accessions per gene.** Median 4, maximum 44 in the file, mostly
  TrEMBL fragments and isoforms (Tyk2: Q9R117 reviewed, five unreviewed of
  159–1,207 aa). Use `is_primary` for anything per gene; counting across all
  accessions counts one gene several times.
- **TrEMBL entries carry little.** E9Q2T9 (Agpat4 fragment) has no Reactome
  link and two automatic (IEA) GO terms; Q8K4X7, the reviewed entry, has a
  Reactome link and seven GO terms with experimental evidence.
- **Select by MGI id, never by symbol.** The allele symbols in the file are
  frozen at submission (28 MGI ids appear under two symbols: `Fam46c<…>` and
  `Tent5c<…>` on MGI:1921895).
- **The file is not UTF-8 throughout.** Three rows have cp1252 non-breaking
  spaces inside an allele name, so `pandas.read_csv` with default settings
  stops at line 42,758. The script decodes per line.
- **UniProt REST query syntax.** `xref:mgi-1929470` works;
  `xref:mgi-MGI:1929470` is a syntax error. Terms OR together, so the
  fallback asks for 20 genes per call (`(xref:mgi-1929470 OR xref:mgi-1915512)
  AND organism_id:10090`) and accessions go 100 per call.
- **UniProt REST is flaky at times** (read timeouts, HTTP 503 "Backend fetch
  failed" on 2026-10-30). The script retries with backoff.

## README

Record the mapping file's download date (stderr prints its modification date),
how many genes came from the file and how many from REST, MGI ids found
nowhere, and genes without a reviewed accession.

## Protein evidence: statements, diseases, coding GWAS variants (prototype)

Prototype of ideas 2-4 from the UniProt review (2026-10-30). Run after step 3,
because it reads the GWAS lead variants:

```bash
uv run skills/impc-gwas-trait-mapper/scripts/uniprot_evidence.py --accessions 02_uniprot_accessions.csv \
  --orthologs 02_orthologs.csv --links 03_l2g_gwas_links.csv --statements-out 02_uniprot_statements.csv \
  --diseases-out 02_uniprot_diseases.csv --variants-out 02_uniprot_gwas_variants.csv
```

- **Human accession:** Open Targets `target.proteinIds` (`uniprot_swissprot`),
  from the Ensembl id already in `03_l2g_gwas_links.csv`.
- **`02_uniprot_statements.csv`:** FUNCTION, DISEASE and DISRUPTION PHENOTYPE
  text from the mouse and human entries, each with its ECO codes and `origin`.
  The origin is read from the ECO ontology in OLS (ancestor ECO:0000006
  experimental, ECO:0000501 automatic, ECO:0000041 similarity), not from a
  code list. `by_similarity` statements name the accession they were copied
  from in `transferred_from`. On the test genes the mouse Ldlr FUNCTION is
  copied from human P01130 and the mouse Tyk2 entry is mixed (one FUNCTION text
  experimental, one copied from P29597). A statement copied across species is
  one observation, not two: never count mouse and human UniProt agreeing as
  independent support when one is `by_similarity` from the other.
- **`02_uniprot_diseases.csv`:** each human DISEASE comment with its MIM id and
  the MONDO id Open Targets uses for it. The id comes from
  `target.associatedDiseases` restricted to the `uniprot_literature` or
  `uniprot_variants` datasource (`required: true`), matched on the disease's
  `OMIM:` dbXRef: TYK2 IMD35 → MONDO_0012682, LDLR FHCL1 → MONDO_0007750. OT
  `mapIds("OMIM:611521")` returns nothing. Columns `trait_id` and
  `trait_label` feed `ols_similarity.py` directly.
- **`02_uniprot_gwas_variants.csv`:** every GWAS lead variant of the gene's
  credible sets. When UniProt lists the same change as a natural variant, the
  row also has the residue change, UniProt's note, the domain it falls in and
  the mutagenesis results in that domain. Matching is in two steps: dbSNP id
  first, then Open Targets' `aminoAcidChange` for that exact allele
  (`variant.transcriptConsequences`, canonical transcript of the gene) must
  equal UniProt's change. The rsid alone is wrong for multi-allelic sites:
  LDLR rs2228671 is a synonymous GWAS lead but UniProt files C27W under it,
  and the LDLR lead with rs139624145 is D482N while UniProt's is D482H. Both
  are rejected and noted. On the test genes: 6 of 112 lead variants are on
  the protein (TYK2 P1104A, V362F, I684S, R703W, A928V; LDLR P685L).

UniProt DISEASE comments cover about a quarter of reviewed human entries and
DISRUPTION PHENOTYPE about a quarter of reviewed mouse ones (mouse Ldlr has
none). An empty field is a coverage gap, not evidence of absence.

## Side by side: IMPC × GWAS × UniProt (prototype, step 6b)

```bash
uv run skills/impc-gwas-trait-mapper/scripts/ols_similarity.py \
  --phenotypes 01_impc_phenotypes.csv --phenotype-id-col mp_term_id --phenotype-label-col mp_term_name \
  --traits 02_uniprot_diseases.csv --trait-id-col trait_id --trait-label-col trait_label \
  --out 05b_phenotype_uniprot_disease_similarity.csv
uv run skills/impc-gwas-trait-mapper/scripts/uniprot_concordance.py --pairs 06_impc_gene_to_gwas_trait.csv \
  --trait-similarity 05_phenotype_trait_similarity.csv --disease-similarity 05b_phenotype_uniprot_disease_similarity.csv \
  --diseases 02_uniprot_diseases.csv --statements 02_uniprot_statements.csv --variants 02_uniprot_gwas_variants.csv \
  --concordance-out 06b_uniprot_concordance.csv --direction-out 06c_direction_evidence.csv
```

`06b_uniprot_concordance.csv` has one row per gene × MP term: the best GWAS
trait among sets where the gene is the top L2G gene, the best UniProt disease
of the same gene, each with its similarity, and whether the mouse entry has
a disruption phenotype. No combined score.

**A fixed similarity cutoff cannot decide agreement.** On Tyk2 + Ldlr the MP
terms scored a median 0.634 against their own gene's UniProt disease and 0.623
against the other gene's. One wrong-gene pair reached 0.83 (Tyk2 decreased HDL
cholesterol vs FHCL1). At the 0.60 display cutoff, 21 of 25 terms looked
"supported by all three". So each layer is compared with a null from the same
run: the same MP term scored against the other genes' top-L2G traits (GWAS)
or UniProt diseases (UniProt). `layers` names a layer only when its best
score beats that null's best. Result on the test genes: 9 terms reach both
layers, 5 GWAS only, 4 UniProt only, 7 neither. Ldlr increased cholesterol
clears both by a wide margin (GWAS 0.93 vs 0.74, UniProt 0.88 vs 0.62); many
Tyk2 margins are under 0.01. Show the margins. The null is weak with few
genes (two genes: one null disease) and absent with one, which `layers` then
states.

## Direction of effect (prototype)

`06c_direction_evidence.csv` lists the step-6 pairs whose best credible set's
lead variant is a UniProt natural variant. Each row has the MP term (the
knockout removes the gene), the trait and the allele's beta sign, the residue
change, UniProt's note, the domain and the mutagenesis results in it.

Whether the knockout and the GWAS allele point the same way is a reading, not
a column. Write it in the report labelled as such, and say what it rests on:

- the knockout is a complete loss of the gene;
- a UniProt DISEASE variant ("in FHCL1") is a loss of function the curators
  have tied to the disease;
- a variant inside a domain where mutagenesis abolishes activity is located,
  not characterised, so its effect is unknown from UniProt alone;
- a non-coding lead says nothing about direction here.

If none of these applies, say the direction is not established.

## Reactome pathway frequency (draft, gene sets only)

Suggested from outside the project; kept so the user can judge it on a real
run. Only for gene sets of at least 10 genes with Reactome links (MP-term
input, or a gene list). With Tyk2 + Ldlr (2 genes) all 20 of their pathways
came out at FDR < 0.05, which says nothing.

```bash
uv run --with matplotlib skills/impc-gwas-trait-mapper/scripts/uniprot_reactome_frequency.py \
  --accessions 02_uniprot_accessions.csv --background 02_uniprot_mouse_reactome_background.json \
  --out 02_uniprot_reactome_frequency.csv --png 02_uniprot_reactome_frequency.png --title "<set description>"
```

- **Background:** every reviewed mouse entry with a Reactome link (UniProt
  stream, about 8,600 proteins, downloaded once into `--background`). The
  open question of using IMPC-phenotyped genes instead is not settled.
- **Per pathway:** set genes in it out of pathway size, the count expected by
  chance, a one-sided hypergeometric p-value and a Benjamini-Hochberg FDR.
- **Chart:** two panels, top 15 pathways by count and by p-value. On the 242
  genes with increased circulating cholesterol (MP:0005178), panel A is led by
  large general pathways at about the expected count (antigen processing
  6/275, about 4.2 expected). Only Thyroxine biosynthesis reaches FDR < 0.05
  (4/10, 0.15 expected).
- **Caveats:** mouse Reactome pathways are inferred from human by orthology;
  pathways overlap, so their tests are not independent.
