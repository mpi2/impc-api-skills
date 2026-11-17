# GO annotations

`go` returns every GO annotation held for each accession. It reads two sources
and writes them with the same columns; `source` says which one a row came from.

| `source` | What it is | Used for |
| --- | --- | --- |
| `goa_mouse.gaf` | EMBL-EBI's GO annotation file for mouse (`ftp.ebi.ac.uk/pub/databases/GO/goa/MOUSE/goa_mouse.gaf.gz`), downloaded once and kept | Every accession the file holds |
| `quickgo` | QuickGO's API (`www.ebi.ac.uk/QuickGO`), which serves the same annotation set | Accessions the file does not hold |

The file is the fast route: 690,000 annotations, read in under a second. But it
holds one protein per gene, so it covers 99.5% of the reviewed accessions the
mapper can return and 1.8% of the unreviewed ones. An accession missing from it
can still be annotated: of 40 missing reviewed accessions, QuickGO had
annotations for 33, mostly second accessions of a gene such as Cux1's `P70403`.
So every accession the file lacks is asked of QuickGO, at about 1 second each.
With reviewed accessions that is a handful per list. With unreviewed ones
(the mapper's `include` policy) it is most of them, so say how long it will
take first.

The annotations bring together the work of several groups; `assigned_by` names
the group, and for mouse proteins many rows come from MGI. GO term names are
not in the annotation file, so they are read from the GO ontology file
(`go-basic.obo`), also downloaded once.

The direction is gene to terms. Finding every gene annotated to a term is a
different question, because it needs the term's descendants, and this command
does not answer it.

## Columns

After the five leading columns:

| Column | Meaning |
| --- | --- |
| `gene_product_db`, `gene_product_id` | Database and id the annotation is on |
| `symbol` | Gene symbol as the source holds it |
| `qualifier` | Relation between the protein and the term, such as `enables`, `involved_in`, `located_in` |
| `go_term`, `go_name` | GO id and label |
| `go_aspect` | `P` biological process, `F` molecular function, `C` cellular component |
| `go_evidence_code` | Evidence as a GO code, such as `IDA`, `IMP`, `ISO`, `IEA` |
| `reference` | Source of the annotation: a PubMed id or a `GO_REF` |
| `with_from` | What the evidence was inferred with or from, such as the ortholog for `ISO` |
| `taxon_id` | NCBI taxon of the gene product; a second taxon after a vertical bar is an interacting organism |
| `assigned_by` | Group that made the annotation |
| `annotation_extension` | Extra context, such as the cell type or anatomy the annotation applies to |
| `date` | Date of the annotation, `YYYYMMDD` |
| `source` | `goa_mouse.gaf` or `quickgo` |

One row is one annotation, not one term. The same term appears several times
for a protein when it is supported by different evidence or references: Kit
has 203 rows. To count terms per gene, count distinct `go_term`.

## Things to read before reporting

- **A qualifier that starts with `NOT`** (for example `NOT|enables`) says the
  protein does not have that role. Keep these rows, show the qualifier, and
  never count them as annotations to the term.
- **All evidence is returned by default**, including annotations inferred from
  orthologs (`ISO`) and electronic ones (`IEA`). Say which evidence the table
  holds. Do not drop evidence types unless the user asks.
- **`ND` evidence means no data.** A curator looked and found nothing, and the
  annotation is to the root term of the aspect. It is not a finding about the
  protein's function.
- **Annotations are direct.** A protein annotated to a specific term is not
  also listed under that term's ancestors.
- **The two sources can be from different releases.** In testing the file was
  dated 2026-11-04 and QuickGO's annotation set 2026-07-28; the same proteins
  differed by about 15% of rows, nearly all electronic (`IEA`) annotations.
  When a result holds `quickgo` rows, give both dates.

## Options

| Option | Effect |
| --- | --- |
| `--aspect biological_process molecular_function cellular_component` | Keep only these aspects |
| `--evidence IDA IMP ...` | Keep only annotations with these GO evidence codes |
| `--refresh` | Download the files again if their source has changed |
| `--api-only` | Skip the file and ask QuickGO for every accession |

`--evidence` takes the codes the user names; this skill keeps no list of which
codes count as experimental. If the user asks for "experimental evidence"
without naming codes, show them the codes present in the unfiltered result and
let them choose. When a filter is used, state it in the answer and the README,
because it changes every count.

## What `no_entry` means

Neither source holds an annotation for the accession under the options used.
With a filter, that means none of that kind.

## What to read in the summary

| Key | Meaning |
| --- | --- |
| `accessions_from_bulk_file` | Accessions answered from the file |
| `accessions_asked_of_quickgo`, `accessions_found_in_quickgo` | Accessions the file lacked, and how many of them QuickGO had annotations for |
| `go_terms_named_by_quickgo` | Terms newer than the ontology file, named through QuickGO instead |
| `go_terms_without_name` | Terms left with a blank `go_name` |
| `source.files` | Each file's URL, dates, version and checksum |
| `source.api` | QuickGO's annotation and ontology dates, when it was used |

## Licence and citation

GO annotations and the ontology are available under CC BY 4.0; the citation
policy is at https://geneontology.org/docs/go-citation-policy/. Report the
annotation file's `date_generated`, the ontology's `data_version` and, when
QuickGO was used, its `annotation_release`.
