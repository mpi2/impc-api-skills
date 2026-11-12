# Reactome pathways

`reactome` returns the lowest-level pathways each accession takes part in. It
reads Reactome's own UniProt to pathway file
(`https://reactome.org/download/current/UniProt2Reactome.txt`), downloaded once
and kept with only its mouse rows. The accessions are mouse proteins, so the
pathways are Reactome's mouse pathways, with `R-MMU-` ids.

The file gives the same answer as Reactome's API, which takes about 1.5 seconds
per protein: for 41 accessions the pathways were identical, and 30 accessions
absent from the file were absent from the API too. So nothing is asked of the
API and no accession can fail.

## Columns

After the five leading columns, each value is copied from the file.

| Column | Meaning |
| --- | --- |
| `st_id` | Reactome stable id of the pathway |
| `display_name` | Pathway name |
| `evidence_code` | `IEA` when Reactome inferred the protein's place in the pathway computationally, by orthology; `TAS` when it was curated |
| `species_name` | Species of the pathway |
| `reactome_url` | The pathway in Reactome's pathway browser |

## Things to read before reporting

- **Mouse pathways are inferred.** Reactome curates human pathways and projects
  them onto mouse by orthology. Every mouse row in the file (32,793) has
  `evidence_code` `IEA`. Say this when reporting, and show the column.
- **"Lowest-level" is the most specific pathway**, not a top-level category
  such as Immune System. The file holds no hierarchy.
- **Nothing is ranked or tested.** The file has no reaction counts, no
  top-level category and no enrichment. A list of pathways for one gene says
  the protein takes part in them and nothing about how central it is.

For pathways of the human ortholog with reaction counts and top-level
categories, `impc-gwas-trait-mapper` has a Reactome step. This command stays
with the mouse protein.

## What `no_entry` means

Reactome has no pathway for the accession. This is common: the file holds 9,363
mouse accessions, and 17 of 41 reviewed accessions in a random test had none.
It means "not in Reactome", not "no known function".

## Options

| Option | Effect |
| --- | --- |
| `--refresh` | Download the file again if Reactome has changed it |

## Licence and citation

Reactome data are available under CC0; attribution is encouraged, not
required. The licence is at https://reactome.org/license and the citation
guidance at https://reactome.org/cite. Report the file's `last_modified` date
and `release_at_download` from the summary. The release is the one Reactome's
API reported when the file was downloaded.
