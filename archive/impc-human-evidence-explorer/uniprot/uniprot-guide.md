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

## UniProt statements and diseases (prototype)

Data only: what UniProt says about each gene, with where each statement
comes from. Nothing is matched to phenotypes or traits.

```bash
uv run skills/impc-gwas-trait-mapper/scripts/uniprot_evidence.py --accessions 02_uniprot_accessions.csv \
  --orthologs 02_orthologs.csv --statements-out 02_uniprot_statements.csv --diseases-out 02_uniprot_diseases.csv
```

- **Human accession:** UniProt REST,
  `xref:hgnc-<n> AND reviewed:true AND organism_id:9606`, 20 genes per call.
- **`02_uniprot_statements.csv`:** FUNCTION, DISEASE and DISRUPTION PHENOTYPE
  text from the mouse and human entries, each with its ECO codes and `origin`.
  The origin classes are read from the ECO ontology in OLS (ancestor
  ECO:0000006 experimental, ECO:0000501 automatic, ECO:0000041 similarity),
  not from a code list. When a statement has evidence of several classes, all
  are listed (`experimental; by_similarity`), so copied evidence is never
  hidden behind an experimental one. `transferred_from` names the accession a
  `by_similarity` statement was copied from.
- **`02_uniprot_diseases.csv`:** each human DISEASE comment as UniProt writes
  it: name, acronym, MIM id, description, origin. No mapping to MONDO or
  other disease ontologies.

## Side-by-side table (prototype, step 6b)

```bash
uv run skills/impc-gwas-trait-mapper/scripts/uniprot_side_by_side.py --pairs 06_impc_gene_to_gwas_trait.csv \
  --phenotypes 01_impc_phenotypes.csv --diseases 02_uniprot_diseases.csv --statements 02_uniprot_statements.csv \
  --out 06b_impc_gwas_uniprot.csv
```

One row per gene × IMPC MP term: the term's first row from step 6 (trait,
similarity, L2G, credible sets, lead variant, study), then the gene's UniProt
human diseases (name, MIM, origin) and mouse disruption phenotype (text,
origin). It is a data table: the skill does not label rows as agreeing or
disagreeing.

## Pitfalls

- **The GWAS columns inherit step 5's similarity ranking.** The "first row"
  per MP term is the highest-similarity trait, and OLS similarity is not yet
  good at picking top matches (to be fixed upstream).
- **UniProt columns are gene-level.** They repeat on every MP term of the
  gene; they are not evidence about that phenotype.
- **Not independent of Open Targets.** OT association scores already use
  UniProt (`uniprot_literature`, `uniprot_variants`) and IMPC/PhenoDigm data.
  The skill's L2G route uses only GWAS credible sets, but never present OT
  association scores next to these columns as separate support.
- **Copied annotation.** Mouse UniProt text is often copied from human
  (mouse Ldlr FUNCTION is entirely from P01130), and sometimes the other way
  (human AGPAT4 from mouse Q8K4X7). Mouse and human entries saying the same
  thing can be one observation.
- **Coverage.** DISEASE comments exist on about a quarter of reviewed human
  entries, DISRUPTION PHENOTYPE on about a quarter of reviewed mouse ones
  (mouse Ldlr has none). An empty cell is a gap, not absence.
- **Mixed species.** Mouse statements and human diseases sit in one row;
  the `species` column in `02_uniprot_statements.csv` keeps them apart.
- **Reliability.** UniProt REST and OLS time out or answer 503 at times;
  the scripts retry, and a failed call should be reported, not read as empty.

Tried and parked (2026-10-30, in `archive/impc-gwas-trait-mapper/uniprot-prototypes/`):
mapping UniProt diseases to MONDO through Open Targets, scoring them against
MP terms, an agreement label with an in-run null, and placing GWAS lead
variants on the protein for direction of effect.

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
