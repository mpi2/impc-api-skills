---
name: impc-protein-resources
description: >-
  Retrieve protein-level records for IMPC mouse genes from resources keyed by UniProt accession: AlphaFold DB predicted structures (confidence figures, entry links, model and PAE files), GO annotations, and Reactome pathways. Takes MGI ids, an IMPC result CSV or a gene set defined by an IMPC query, gets UniProt accessions through impc-uniprot-mapper and returns one table per resource. Use it whenever a user wants AlphaFold structures or pLDDT, GO terms or annotations, or Reactome pathways for IMPC genes, knockouts or phenotype gene lists, asks what is known about the proteins behind an IMPC gene set, or wants to refresh or inspect the local GO and Reactome files, even if they never name UniProt. Not for enrichment or over-representation tests, and not for human GWAS or ortholog evidence (use impc-gwas-trait-mapper).
---

# IMPC genes → AlphaFold, GO and Reactome

**Experimental:** the output format may change and there are no evals yet.

## Why this skill exists

IMPC identifies genes by MGI id. AlphaFold DB, GO annotations and Reactome
identify proteins by UniProt accession. `impc-uniprot-mapper` makes that step
once, with one policy on reviewed and unreviewed accessions, and this skill
does the lookups after it. Every resource is read the same way and written the
same way, so a gene that returned nothing is always in the file, with the
reason.

GO and Reactome publish their mouse data as files, and their APIs take a second
or more per protein. So this skill downloads those files once, keeps them, and
looks genes up locally: a list of any size takes seconds. AlphaFold DB has no
such file and its API is fast, so it is asked per protein.

```
MGI ids, IMPC CSV, or gene set        impc-uniprot-mapper (it calls impc-data-retriever when needed)
  → local UniProt mapping             use it if built, otherwise build it through the mapper
  → UniProt accessions                uniprot_ids.csv, output contract schema 1
    → AlphaFold DB entries            protein_resources.py alphafold    AlphaFold DB API
    → GO annotations                  protein_resources.py go           GOA mouse file, QuickGO for accessions it lacks
    → Reactome pathways               protein_resources.py reactome     Reactome UniProt to pathway file
```

## Prerequisites

1. `uv`: read the `uv` skill and follow its setup. The script needs only the
   standard library.
2. The `impc-uniprot-mapper` skill, with output contract schema 1. This skill
   depends on it: every accession comes from its local UniProt mapping, and
   nothing here maps ids. It is installed beside this skill, at
   `../impc-uniprot-mapper/`. If it is not installed, stop and tell the user to
   install it; do not map ids another way.

Run the script from this skill's directory, or give its full path.

## Resources

Run only the resources the user asked for. If they asked for protein information
in general, ask which of the three they want. Read a resource's guide before
running it: it holds the columns, the options and what the values mean.

| Resource | Returns | Command | Guide |
| --- | --- | --- | --- |
| AlphaFold DB | One row per predicted structure: confidence figures, entry link, file links | `alphafold` | [alphafold-guide.md](references/alphafold-guide.md) |
| GO annotations | One row per annotation: term, aspect, qualifier, evidence, reference | `go` | [go-guide.md](references/go-guide.md) |
| Reactome | One row per lowest-level pathway | `reactome` | [reactome-guide.md](references/reactome-guide.md) |

## Workflow

### 1. Check the UniProt mapping

```bash
uv run --script ../impc-uniprot-mapper/scripts/uniprot_idmap.py status
```

- **`built` is `true`:** the mapping is on this machine. Use it as it is. Do
  not refresh or rebuild it unless the user asks, so that results stay tied to
  one UniProt release.
- **`built` is `false`:** read the `impc-uniprot-mapper` skill and build the
  mapping as it describes (its `build` command, about 30 MB, seconds). If the
  build fails, stop and report it. There is no other route to accessions.

### 2. Get the accessions

Run `impc-uniprot-mapper` on the user's genes, following its whole workflow and
not just its script, and keep its CSV as `uniprot_ids.csv` in the result
directory. Its rules apply here unchanged:

- Check that its summary says `output_schema: 1`. If it says another number,
  stop and say this skill was written for schema 1.
- If any gene is `no_reviewed_hit`, settle that with the user as the mapper
  describes before going on. Do not choose reviewed or unreviewed here.
- Never add an accession that the mapper did not return.

If the user already has a mapper CSV, use it and skip the mapping.

### 3. Query

```bash
uv run --script scripts/protein_resources.py alphafold --mapping uniprot_ids.csv --out alphafold.csv
uv run --script scripts/protein_resources.py go        --mapping uniprot_ids.csv --out go_annotations.csv
uv run --script scripts/protein_resources.py reactome  --mapping uniprot_ids.csv --out reactome_pathways.csv
```

The commands are independent. Each looks up every distinct accession once.

- `go` and `reactome` download their files on first use (about 85 MB in all, a
  few seconds) and then answer in under a second.
- `alphafold` takes about 0.4 seconds per protein. For more than about 500
  proteins, tell the user the expected time before starting.

Progress goes to stderr and a JSON summary to stdout. The exit code is 0 when
every accession was answered, 1 when some failed (the CSV is written and marks
them `failed`), and 2 when nothing was written: the input or an option was
wrong, or a file could not be downloaded.

### 4. Read the summary and act on it

- **`failed` is above zero:** the resource did not answer for those accessions.
  Run the command again once. If they still fail, report them as not retrieved.
  A failed accession is not a protein without data.
- **`no_entry`:** the resource holds nothing for that accession. Report the
  count and the genes. Each guide says what this usually means.
- **`genes_without_accession`:** genes the mapper returned no accession for.
  They were not looked up. Report them with their `mapping_status`.
- **`bulk_files` shows `refresh_failed`:** the update did not work and the run
  used the file already held. Say so, with that file's date.

Do not fill a gap from memory or from another source. A protein's structure
confidence, GO terms or pathways in the output must come from the resource in
that run, so the result traces to one retrieval.

### 5. Report

Create a result directory named after the request. Save the CSVs there and
write a `README.md` following
[the retrieval report guide](../impc-data-retriever/references/output-report.md),
with one entry per command run, the mapper's entry and any IMPC queries.

The summaries are printed once and not saved, so the README is where they are
kept. Someone who receives only the directory should read there what each
resource returned, without running anything again. For each command, copy from
its summary:

| README section | From the summary |
| --- | --- |
| Result summary | `genes_in_mapping`, `accessions_queried`, `status_counts`, `rows_written` |
| Queries, the command's entry | The command as run and `options`: filters, what happened to each bulk file, and the resource's own counts |
| Limitations and follow-up | `genes_without_accession` with its `by_mapping_status` counts and ids, the `no_entry` ids, and the `failed` ids with their errors |
| Provenance | The `source` block (file dates, releases and checksums, or the API endpoint, with the retrieval time) and the mapper's `source` block |

Copy the figures as printed; do not recount them from the CSV. A summary lists
at most 25 ids and sets `truncated` when there are more: give the count and say
where the full list is (the `status` column of the CSV, or `uniprot_ids.csv`
for genes without an accession). Leave local cache paths out of the report.

Show the user, per resource: the status counts, a short table of the data, and
the release or file date. Report what the resources returned. Do not say that a
structure is reliable, that a GO term or pathway explains an IMPC phenotype, or
that a gene set is enriched for anything; nothing here tests that.

### Attribution

Users share these CSVs, and the sources ask for credit. In the README and in
the first answer that shows the data, name each resource used, its release or
file date from the summary, and its licence and citation page as given in its
guide. Keep the mapper's UniProt attribution as well.

## Output

Every file starts with the same five columns, then the resource's own columns
as described in its guide.

| Column | Meaning |
| --- | --- |
| `mgi_id`, `gene_name`, `uniprot_accession`, `reviewed` | Copied from the mapper's CSV |
| `status` | `found`, `no_entry` (the resource holds nothing for the accession) or `failed` (the request failed) |

Every gene and accession pair in the mapper's CSV has at least one row. A
`no_entry` or `failed` row has blank resource columns. Genes without an
accession are not in the file; the summary counts them.

| File | Contents |
| --- | --- |
| `uniprot_ids.csv` | The mapper's output |
| `alphafold.csv` | One row per accession and AlphaFold DB entry |
| `alphafold_files/` | Structure files, only with `--download` |
| `go_annotations.csv` | One row per accession and GO annotation |
| `reactome_pathways.csv` | One row per accession and pathway |
| `README.md` | Report: each command's summary, limitations and provenance |

## Managing the bulk files

The GO and Reactome files live in `~/.cache/impc-skills/protein-resources/`, so
they survive across projects. `go`, `reactome` and `status` accept `--cache-dir`
to use another location.

| User asks | Command | Effect |
| --- | --- | --- |
| "What version do I have?", "how old is the GO data?" | `status` | Each file's source, dates, release and checksum |
| "Use the latest", "update it" | add `--refresh` to `go` or `reactome` | Downloads again if the source has changed, then runs |

A file is never updated unless asked, so two runs give the same answer. Every
summary gives the date of the file it used. If that file was retrieved more
than a month ago, tell the user its date and offer `--refresh`.

If a download fails and a file is already held, the run uses it and the summary
says `refresh_failed`. If no file is held, the command stops with exit code 2;
report that. For GO only, `--api-only` asks QuickGO for every accession
instead, at about 1 second per protein.

## Adding a resource

A resource belongs here when it is keyed by UniProt accession and is a lookup,
not an analysis. Add a fetcher and a command to `scripts/protein_resources.py`,
keep the five leading columns and the three statuses, and write
`references/<resource>-guide.md`. Prefer the resource's published file when it
has one, and register it in `DATASETS` so it is cached and described like the
others. Keep this file to the workflow.
