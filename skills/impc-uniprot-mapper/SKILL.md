---
name: impc-uniprot-mapper
description: >-
  Convert IMPC mouse gene MGI ids to UniProt accessions using a local mapping built from UniProt's mouse idmapping file, with no calls to the UniProt REST API. Takes MGI ids, an IMPC result CSV, or a gene set defined by an IMPC query, and returns reviewed (Swiss-Prot) accessions by default. Use it whenever a user wants UniProt ids, accessions or protein identifiers for IMPC genes, knockouts or phenotype gene lists, asks to map or translate MGI ids to UniProt, or wants to build, refresh, rebuild or inspect the local MGI to UniProt mapping, even if they never say "mapping".
---

# IMPC genes → UniProt accessions

**Experimental:** the output format may change and there are no evals yet.

## Why this skill exists

UniProt's REST API is unreliable and rate-limited, so gene lists of any size
stall on it. UniProt also publishes every mouse cross-reference as one file.
This skill turns that file into a small local mapping once, and lookups then
take under a second with no network. Do not fall back to REST when a lookup or
download fails: report the failure instead. For the same reason, never fill a
blank accession from memory or another source. Every accession in the output
must come from the mapping, so the result traces to one UniProt release.

```
MGI ids, IMPC CSV, or gene set        impc-data-retriever when genes must come from IMPC
  → local mapping                     scripts/uniprot_idmap.py build
    → reviewed accessions             scripts/uniprot_idmap.py map
      → genes with no reviewed hit    ask the user before using unreviewed
```

## Prerequisites

1. `uv`: read the `uv` skill and follow its setup. The script needs only the
   standard library.
2. The `impc-data-retriever` skill, when genes must be fetched from IMPC.

Run the script from this skill's directory, or give its full path.

## Accession policy

The mapping holds every accession, reviewed and unreviewed. Lookups use reviewed
accessions first, because a gene can have dozens of unreviewed TrEMBL entries
that would multiply every downstream result.

**Before running, tell the user you will use reviewed data first unless they ask
otherwise.** Then pick the flag:

| Situation | Flag |
| --- | --- |
| Default | `--unreviewed exclude` (or no flag) |
| User agreed to unreviewed for genes with no reviewed hit | `--unreviewed fallback` |
| User explicitly asked for unreviewed data | `--unreviewed include` |

When the user asks explicitly, do not ask again. `include` returns every
accession for every gene, and the `reviewed` column separates them, so filter on
`reviewed = false` if they want only unreviewed entries.

## Workflow

### 1. Get the MGI ids

- MGI ids or a file of them: use them directly.
- An IMPC result file: use its gene id column, which is `marker_accession_id`
  or `gene_accession_id` in most cores and `marker_id` in `phenodigm`.
- A symbol, phenotype, procedure or any other description of a gene set: run
  `impc-data-retriever` first and use the MGI ids it returns. Symbols are not
  accepted by the script because they are ambiguous across synonyms.

### 2. Make sure the mapping exists

```bash
uv run --script scripts/uniprot_idmap.py build
```

This does nothing if a mapping exists. The first run downloads about 30 MB and
takes seconds.

### 3. Map

```bash
uv run --script scripts/uniprot_idmap.py map MGI:1929470 MGI:96677 --out uniprot_ids.csv
uv run --script scripts/uniprot_idmap.py map --input ids.txt --out uniprot_ids.csv
uv run --script scripts/uniprot_idmap.py map --input impc.csv --column marker_accession_id --out uniprot_ids.csv
```

The CSV goes to `--out` and a JSON summary goes to stderr. Each distinct input
id appears in the output at least once. Input file columns are not carried over,
so join back on `mgi_id` if needed.

### 4. Read the summary and act on it

- **`no_reviewed_hit` is above zero and the user has not already decided:** stop
  and ask. Give the count and the gene names, then ask whether to use unreviewed
  accessions for those genes. The summary lists at most 25 ids, so read the full
  set from the CSV where `mapping_status` is `no_reviewed_hit`. If yes, rerun with `--unreviewed fallback`. If no,
  keep the rows as they are, with blank accessions. Do not continue to any
  downstream step on these genes before the user answers.
- **`not_found`:** report the ids. Most are genes with no protein product in
  UniProt, such as miRNAs, lncRNAs and pseudogenes, or transgenes and other
  non-gene markers.
- **`multiple_reviewed`:** the source links several reviewed entries to the
  gene. Return all of them; the file gives no basis for choosing one.
- **`invalid_id`:** the value is not an `MGI:<digits>` id. Resolve it with
  `impc-data-retriever` rather than editing it by hand.

### 5. Report

Create a result directory named after the request. Save the CSV there and write
a `README.md` following
[the retrieval report guide](../impc-data-retriever/references/output-report.md),
with one entry for the `map` command, its status counts, and any IMPC queries.
Under Provenance, record the `source` block from the summary (UniProt release,
last-modified date, retrieval date, checksums). That block is what ties a result
to a specific download. Leave local cache paths out of the report.

Show the user the status counts, the policy used and the UniProt release.

### Attribution

UniProt data are licensed under CC BY 4.0, which requires credit wherever they
are reused, and users often share these CSVs. So in the README and in the first
answer of a conversation that shows UniProt data, state that the accessions come
from UniProt, give the release and the license from the summary's `source`
block, and point to UniProt's citation guidance at
https://www.uniprot.org/help/publications. At the time of writing that is
The UniProt Consortium, "UniProt: the Universal Protein Knowledgebase in 2025",
*Nucleic Acids Research* 53(D1):D609–D617 (2025), doi:10.1093/nar/gkae1010.
If `license` is null, the mapping predates license recording: run `rebuild`, or
cite the license as given at https://www.uniprot.org/help/license.

## Output columns

| Column | Meaning |
| --- | --- |
| `mgi_id` | Input id |
| `uniprot_accession` | Accession; blank when none is returned |
| `entry_name` | UniProtKB entry name |
| `gene_name` | UniProt gene name; `;` separates several |
| `reviewed` | `true` Swiss-Prot, `false` TrEMBL, blank when no accession |
| `mapping_status` | Gene-level status, below |
| `n_reviewed`, `n_unreviewed` | Accessions available for the gene |

| `mapping_status` | Meaning |
| --- | --- |
| `reviewed` | One reviewed accession |
| `multiple_reviewed` | Several reviewed accessions |
| `no_reviewed_hit` | Unreviewed accessions exist but were withheld by the policy |
| `unreviewed` | Only unreviewed accessions exist and they were returned |
| `not_found` | MGI id absent from the UniProt file |
| `invalid_id` | Not an `MGI:<digits>` id |

## Managing the mapping

The mapping lives in `~/.cache/impc-skills/uniprot/`, so it survives across
projects. Every command accepts `--cache-dir` to use another location.

| User asks | Command | Effect |
| --- | --- | --- |
| "What version do I have?", "what have I downloaded?" | `status` | Current release, dates, checksums, counts, and every past download |
| "Is there a newer one?", "update it" | `refresh` | Downloads only if UniProt changed the file |
| "Rebuild the mapping" | `rebuild` | Always downloads and regenerates |

The directory holds `mgi_uniprot.tsv.gz` (the mapping), `metadata.json` (what the
current mapping came from) and `download_history.jsonl` (one record per download,
never rewritten). The raw UniProt file is deleted after parsing.

If `refresh` or `rebuild` fails, the existing mapping is untouched and the error
states its release and date. Continue with it if the user wants, and say that
the update failed. If there is no mapping and `build` fails, stop and report it.
