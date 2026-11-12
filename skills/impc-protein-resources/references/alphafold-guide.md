# AlphaFold DB: predicted structures

`alphafold` asks the AlphaFold Protein Structure Database for the predicted
structure of each accession (`https://alphafold.ebi.ac.uk/api/prediction/<accession>`,
no key). These are computed predictions, not experimental structures. Say so
when reporting them.

## Columns

After the five leading columns, each value is copied from the AlphaFold DB
response. The source field is given where the name differs.

| Column | Meaning |
| --- | --- |
| `entry_id` | AlphaFold DB entry, for example `AF-Q9R117-F1` |
| `entry_uniprot_accession` | Accession the entry is for. Differs from `uniprot_accession` only on isoform entries (`P05532-2`) |
| `uniprot_id`, `uniprot_description` | UniProt entry name and protein name as AlphaFold DB holds them |
| `sequence_start`, `sequence_end` | Residues the model covers |
| `global_metric_value` | Mean pLDDT over the model, 0 to 100 (`globalMetricValue`) |
| `fraction_plddt_very_low`, `_low`, `_confident`, `_very_high` | Share of residues in AlphaFold DB's four pLDDT bands: below 50, 50 to 70, 70 to 90, above 90 |
| `latest_version` | Version of the model in AlphaFold DB |
| `model_created_date` | Date the model was created |
| `cif_url`, `pdb_url` | Model coordinates in mmCIF and PDB format |
| `pae_doc_url`, `pae_image_url` | Predicted aligned error as JSON and as an image |
| `plddt_doc_url` | Per-residue pLDDT as JSON |
| `entry_url` | The protein's page on the AlphaFold DB website |
| `downloaded_files` | File names saved by `--download`, `;`-separated |

## Options

| Option | Effect |
| --- | --- |
| `--isoforms` | Also return the entries AlphaFold DB holds for isoforms of each accession |
| `--download cif pdb pae plddt` | Save the named files for every entry returned |
| `--files-dir DIR` | Where `--download` saves; default `alphafold_files` next to `--out` |

**Isoforms.** AlphaFold DB can hold one entry per isoform as well as the entry
for the accession itself; Kit (`P05532`) has two isoform entries. By default
only the accession's own entry is written, so that one protein gives one row,
and the summary's `isoform_entries_left_out` counts the rest. If an accession
has isoform entries but none of its own, those are written. Use `--isoforms`
when the user asks about isoforms.

**Downloads.** Nothing is downloaded unless asked. Links are usually enough,
and a predicted aligned error file is several megabytes per protein (2.7 MB
for Kit, 6.8 MB for Cux1). Before downloading for a long list, tell the user
how many files that is. Per-residue pLDDT is in the `plddt` file and also in
the B-factor column of the model files.

## What `no_entry` means

AlphaFold DB has no prediction for the accession. This is expected for very
long proteins, which it leaves out: titin (`A2ASS6`) has no entry.

## How to report it

Give the mean pLDDT and the four fractions as returned, with the entry link.
The bands are AlphaFold DB's own and can be named as such. Do not turn them
into statements about the protein, such as "disordered" or "well folded", and
do not infer domains; this skill runs no analysis on the structures. If the
user wants that, say it is outside this skill.

## Licence and citation

AlphaFold DB data are available under CC BY 4.0. The citation it asks for is given
on https://alphafold.ebi.ac.uk/. Name the model version from
`latest_version` (the summary's `model_versions` counts them).
