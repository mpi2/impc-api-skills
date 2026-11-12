#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Fetch AlphaFold, GO and Reactome records for the UniProt accessions of IMPC genes.

Commands:
  alphafold  predicted structure entries, confidence figures and file links (AlphaFold DB API)
  go         GO annotations (EMBL-EBI GOA mouse file; QuickGO for accessions the file lacks)
  reactome   lowest-level pathways (Reactome's UniProt to pathway file)
  status     show the bulk files held in the cache

alphafold, go and reactome read the CSV written by impc-uniprot-mapper
(`uniprot_idmap.py map`), look up each distinct accession once and write one CSV
to --out. Progress goes to stderr and a JSON summary to stdout.

go and reactome work from bulk files that are downloaded on first use and then
reused from the cache, so a lookup takes seconds whatever the number of genes.
--refresh downloads a file again if its source has changed.

Exit codes: 0 every accession was answered; 1 some accessions failed, the CSV is
written and marks them `failed`; 2 nothing was written, because the input or an
option was wrong or a bulk file could not be downloaded.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zlib
from collections import Counter
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

# Reactome answers HTTP 403 to Python's default User-Agent.
USER_AGENT = "impc-protein-resources"
ATTEMPTS = 3
MAX_IDS_IN_SUMMARY = 25
PROGRESS_EVERY = 50

# Columns read from the mapper's CSV (impc-uniprot-mapper output contract, schema 1).
MAPPER_REQUIRED = ["mgi_id", "uniprot_accession", "mapping_status"]
MAPPER_SCHEMA = 1

# The first columns of every output file. `status` is per accession.
KEY_FIELDS = ["mgi_id", "gene_name", "uniprot_accession", "reviewed", "status"]
STATUSES = ["found", "no_entry", "failed"]

ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/api/prediction"
ALPHAFOLD_ENTRY = "https://alphafold.ebi.ac.uk/entry"
ALPHAFOLD_DELAY = 0.2
# Output column, then the field it is copied from in the AlphaFold DB response.
ALPHAFOLD_SOURCE = [
    ("entry_id", "entryId"),
    ("entry_uniprot_accession", "uniprotAccession"),
    ("uniprot_id", "uniprotId"),
    ("uniprot_description", "uniprotDescription"),
    ("sequence_start", "sequenceStart"),
    ("sequence_end", "sequenceEnd"),
    ("global_metric_value", "globalMetricValue"),
    ("fraction_plddt_very_low", "fractionPlddtVeryLow"),
    ("fraction_plddt_low", "fractionPlddtLow"),
    ("fraction_plddt_confident", "fractionPlddtConfident"),
    ("fraction_plddt_very_high", "fractionPlddtVeryHigh"),
    ("latest_version", "latestVersion"),
    ("model_created_date", "modelCreatedDate"),
    ("cif_url", "cifUrl"),
    ("pdb_url", "pdbUrl"),
    ("pae_doc_url", "paeDocUrl"),
    ("pae_image_url", "paeImageUrl"),
    ("plddt_doc_url", "plddtDocUrl"),
]
ALPHAFOLD_FIELDS = [column for column, _ in ALPHAFOLD_SOURCE] + ["entry_url", "downloaded_files"]
ALPHAFOLD_DOWNLOADS = {"cif": "cif_url", "pdb": "pdb_url", "pae": "pae_doc_url", "plddt": "plddt_doc_url"}

DEFAULT_CACHE = Path.home() / ".cache" / "impc-skills" / "protein-resources"
METADATA_NAME = "metadata.json"

GOA_URL = "https://ftp.ebi.ac.uk/pub/databases/GO/goa/MOUSE/goa_mouse.gaf.gz"
GOA_SOURCE_NAME = "goa_mouse.gaf"
GAF_VERSION = "2.2"
GAF_COLUMNS = 17
GO_ONTOLOGY_URL = "https://purl.obolibrary.org/obo/go/go-basic.obo"
QUICKGO = "https://www.ebi.ac.uk/QuickGO/services"
QUICKGO_SOURCE_NAME = "quickgo"
# QuickGO takes about a second per protein, so a batch is kept small enough to finish
# well inside the timeout and to lose little if it fails.
QUICKGO_BATCH = 25
QUICKGO_TIMEOUT = 300
QUICKGO_DOWNLOAD_LIMIT = 50000
QUICKGO_SELECTED = (
    "geneProductId,symbol,qualifier,goId,goName,goAspect,goEvidence,"
    "reference,withFrom,taxonId,assignedBy,extensions,date"
)
# The header QuickGO returns for QUICKGO_SELECTED, and the output column for each field.
QUICKGO_SOURCE = [
    ("gene_product_db", "GENE PRODUCT DB"),
    ("gene_product_id", "GENE PRODUCT ID"),
    ("symbol", "SYMBOL"),
    ("qualifier", "QUALIFIER"),
    ("go_term", "GO TERM"),
    ("go_name", "GO NAME"),
    ("go_aspect", "GO ASPECT"),
    ("go_evidence_code", "GO EVIDENCE CODE"),
    ("reference", "REFERENCE"),
    ("with_from", "WITH/FROM"),
    ("taxon_id", "TAXON ID"),
    ("assigned_by", "ASSIGNED BY"),
    ("annotation_extension", "ANNOTATION EXTENSION"),
    ("date", "DATE"),
]
# Both sources are written with these columns; `source` says which one a row came from.
GO_FIELDS = [column for column, _ in QUICKGO_SOURCE] + ["source"]
# Aspect names as the user gives them, and the letter GO annotation files use.
GO_ASPECTS = {"biological_process": "P", "molecular_function": "F", "cellular_component": "C"}
GO_EVIDENCE = re.compile(r"^[A-Z]{2,3}$")

REACTOME_URL = "https://reactome.org/download/current/UniProt2Reactome.txt"
REACTOME_VERSION_URL = "https://reactome.org/ContentService/data/database/version"
REACTOME_SPECIES = "Mus musculus"
# The columns of UniProt2Reactome.txt, in its order. The file has no header.
REACTOME_FILE_COLUMNS = ["uniprot_accession", "st_id", "reactome_url", "display_name", "evidence_code", "species_name"]
REACTOME_FIELDS = ["st_id", "display_name", "evidence_code", "species_name", "reactome_url"]


class ToolError(Exception):
    """Wrong input or options. Reported without a traceback; nothing is written."""


class RequestFailed(Exception):
    """A request that still failed after the retries."""


class BuildFailed(Exception):
    """A downloaded bulk file that is not in the expected format."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def http_get(url: str, accept: str, timeout: int = 60) -> bytes | None:
    """Return the response body, or None for HTTP 404. Retry server and network errors."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    last_error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as error:
            if error.code == 404:
                return None
            detail = error.read(300).decode("utf-8", "replace").strip()
            last_error = RequestFailed(f"HTTP {error.code} {detail}".strip())
            if error.code != 429 and error.code < 500:
                break
        except (OSError, HTTPException) as error:
            last_error = RequestFailed(f"{type(error).__name__}: {error}")
        if attempt < ATTEMPTS:
            time.sleep(2**attempt)
    raise last_error


def cell(value) -> str:
    """Render a source value for the CSV: booleans as in the mapper, missing as blank."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def download(url: str, destination: Path, etag: str | None) -> dict | None:
    """Download a bulk file. Return None when the server reports no change."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if etag:
        headers["If-None-Match"] = etag
    last_error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            sha256 = hashlib.sha256()
            size = 0
            with urlopen(Request(url, headers=headers), timeout=120) as response, destination.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    sha256.update(chunk)
                    size += len(chunk)
            expected = response.headers.get("Content-Length")
            if expected and int(expected) != size:
                raise OSError(f"received {size} of {expected} bytes")
            return {
                "size_bytes": size,
                "sha256": sha256.hexdigest(),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
            }
        except HTTPError as error:
            if error.code == 304:
                return None
            last_error = RequestFailed(f"HTTP {error.code}")
            if error.code != 429 and error.code < 500:
                break
        except (OSError, HTTPException) as error:
            last_error = RequestFailed(f"{type(error).__name__}: {error}")
        if attempt < ATTEMPTS:
            time.sleep(2**attempt)
    raise last_error


def build_go_annotations(raw: Path, built: Path) -> dict:
    """Check the GOA file and keep it as downloaded."""
    header: dict[str, str] = {}
    rows = 0
    accessions: set[str] = set()
    try:
        with gzip.open(raw, "rt", encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if line.startswith("!"):
                    key, separator, value = line[1:].partition(":")
                    if separator:
                        header.setdefault(key.strip(), value.strip())
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) != GAF_COLUMNS:
                    raise BuildFailed(f"unexpected format at line {line_number}: {line[:120]!r}")
                accessions.add(fields[1])
                rows += 1
    except (EOFError, zlib.error, gzip.BadGzipFile) as error:
        raise BuildFailed(f"file is truncated or corrupt: {error}") from error
    if header.get("gaf-version") != GAF_VERSION:
        raise BuildFailed(f"expected GAF {GAF_VERSION}, found {header.get('gaf-version')!r}")
    if not rows:
        raise BuildFailed("file holds no annotations")
    shutil.copyfile(raw, built)
    return {
        "gaf_version": header["gaf-version"],
        "date_generated": header.get("date-generated"),
        "go_version": header.get("go-version"),
        "rows": rows,
        "accessions": len(accessions),
    }


def build_go_terms(raw: Path, built: Path) -> dict:
    """Reduce the GO ontology file to term id and name."""
    version = None
    names: dict[str, str] = {}
    current = None
    with raw.open(encoding="utf-8") as source:
        for line in source:
            if line.startswith("data-version:") and version is None:
                version = line.split(":", 1)[1].strip()
            elif line.startswith("["):
                current = None
            elif line.startswith("id: GO:"):
                current = line[4:].strip()
            elif line.startswith("name: ") and current and current not in names:
                names[current] = line[6:].strip()
    if not names:
        raise BuildFailed("file holds no GO terms; its format may have changed")
    with gzip.open(built, "wt", encoding="utf-8", newline="") as output:
        output.write("go_term\tgo_name\n")
        for term, name in names.items():
            output.write(f"{term}\t{name}\n")
    return {"data_version": version, "terms": len(names)}


def build_reactome(raw: Path, built: Path) -> dict:
    """Keep the mouse rows of Reactome's UniProt to pathway file."""
    rows = 0
    accessions: set[str] = set()
    with raw.open(encoding="utf-8") as source, gzip.open(built, "wt", encoding="utf-8", newline="") as output:
        output.write("\t".join(REACTOME_FILE_COLUMNS) + "\n")
        for line_number, line in enumerate(source, 1):
            fields = line.rstrip("\n").split("\t")
            if len(fields) != len(REACTOME_FILE_COLUMNS):
                raise BuildFailed(f"unexpected format at line {line_number}: {line[:120]!r}")
            if fields[5] == REACTOME_SPECIES:
                output.write(line.rstrip("\n") + "\n")
                accessions.add(fields[0])
                rows += 1
    if not rows:
        raise BuildFailed(f"file holds no {REACTOME_SPECIES} rows; its format may have changed")
    try:
        release = (http_get(REACTOME_VERSION_URL, "text/plain") or b"").decode().strip() or None
    except RequestFailed:
        release = None
    return {"release_at_download": release, "species": REACTOME_SPECIES, "rows": rows, "accessions": len(accessions)}


# The bulk files: where each comes from, its name in the cache and how it is checked and stored.
DATASETS = {
    "go_annotations": (GOA_URL, "goa_mouse.gaf.gz", build_go_annotations),
    "go_ontology": (GO_ONTOLOGY_URL, "go_terms.tsv.gz", build_go_terms),
    "reactome": (REACTOME_URL, "uniprot2reactome_mouse.tsv.gz", build_reactome),
}


def read_metadata(cache: Path) -> dict:
    path = cache / METADATA_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_metadata(cache: Path, metadata: dict) -> None:
    temporary = cache / f".{METADATA_NAME}.tmp"
    temporary.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, cache / METADATA_NAME)


def ensure_dataset(cache: Path, name: str, refresh: bool) -> tuple[dict, str]:
    """Return a bulk file's metadata and what happened: cached, downloaded, up_to_date or refresh_failed."""
    url, filename, build = DATASETS[name]
    cache.mkdir(parents=True, exist_ok=True)
    metadata = read_metadata(cache)
    current = metadata.get(name) if (cache / filename).exists() else None
    if current and not refresh:
        return current, "cached"
    log(f"  downloading {url}")
    try:
        with tempfile.TemporaryDirectory(dir=cache, prefix=".download-") as work:
            raw = Path(work) / "download"
            fetched = download(url, raw, current["etag"] if current else None)
            if fetched is None:
                return current, "up_to_date"
            built = Path(work) / filename
            entry = {"url": url, "retrieved_at": utc_now(), **fetched, **build(raw, built)}
            # Without its metadata a file counts as absent, so a crash here cannot pair
            # a new file with the description of the old one.
            metadata.pop(name, None)
            write_metadata(cache, metadata)
            os.replace(built, cache / filename)
            metadata[name] = entry
            write_metadata(cache, metadata)
            return entry, "downloaded"
    except (RequestFailed, BuildFailed) as error:
        if current:
            log(f"  warning: could not refresh {name} ({error}); using the cached file retrieved {current['retrieved_at']}")
            return current, f"refresh_failed: {error}"
        raise ToolError(f"could not get {url}: {error}") from error


def describe(entry: dict, keys: list[str]) -> dict:
    """The parts of a bulk file's metadata that identify it in a report."""
    return {key: entry.get(key) for key in ["url", *keys, "last_modified", "sha256", "retrieved_at"]}


def show_status(cache: Path) -> int:
    metadata = read_metadata(cache)
    files = {
        name: metadata.get(name) if (cache / filename).exists() else None
        for name, (_, filename, _) in DATASETS.items()
    }
    print(json.dumps({"cache_dir": str(cache), "files": files}, indent=2))
    return 0


def read_mapping(path: Path) -> tuple[list[dict[str, str]], dict]:
    """Return the gene and accession pairs to query, and what was left out."""
    if not path.exists():
        raise ToolError(f"mapping file not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        missing = [name for name in MAPPER_REQUIRED if name not in columns]
        if missing:
            raise ToolError(
                f"{path.name} is not an impc-uniprot-mapper CSV (schema {MAPPER_SCHEMA}): "
                f"missing {', '.join(missing)}. Run impc-uniprot-mapper first."
            )
        rows = list(reader)

    pairs: dict[tuple[str, str], dict[str, str]] = {}
    without: dict[str, str] = {}
    genes: dict[str, None] = {}
    for row in rows:
        gene = (row.get("mgi_id") or "").strip()
        accession = (row.get("uniprot_accession") or "").strip()
        if not gene:
            continue
        genes[gene] = None
        if accession:
            pairs.setdefault((gene, accession), {
                "mgi_id": gene,
                "gene_name": (row.get("gene_name") or "").strip(),
                "uniprot_accession": accession,
                "reviewed": (row.get("reviewed") or "").strip(),
            })
        else:
            without.setdefault(gene, (row.get("mapping_status") or "").strip())
    mapped_genes = {gene for gene, _ in pairs}
    without = {gene: status for gene, status in without.items() if gene not in mapped_genes}
    if not pairs:
        raise ToolError(f"{path.name} has no rows with a uniprot_accession; nothing to query")
    left_out = {
        "count": len(without),
        "by_mapping_status": dict(Counter(without.values())),
        "ids": list(without)[:MAX_IDS_IN_SUMMARY],
        "truncated": len(without) > MAX_IDS_IN_SUMMARY,
    }
    return list(pairs.values()), {"genes_in_mapping": len(genes), "genes_without_accession": left_out}


# Each fetcher returns {accession: (status, records, error)}; records are dicts keyed by output column.
Result = dict[str, tuple[str, list[dict[str, str]], str]]


def per_accession(accessions: list[str], fetch_one, delay: float) -> Result:
    results: Result = {}
    for index, accession in enumerate(accessions, 1):
        try:
            records = fetch_one(accession)
            results[accession] = ("found", records, "") if records else ("no_entry", [], "")
        except RequestFailed as error:
            results[accession] = ("failed", [], str(error))
        if index % PROGRESS_EVERY == 0 or index == len(accessions):
            log(f"  {index}/{len(accessions)} accessions")
        if index < len(accessions):
            time.sleep(delay)
    return results


def fetch_alphafold(accessions: list[str], args: argparse.Namespace) -> tuple[Result, dict]:
    files_dir = Path(args.files_dir) if args.files_dir else Path(args.out).parent / "alphafold_files"
    downloads = list(dict.fromkeys(args.download or []))
    downloaded = 0
    isoforms_left_out = 0
    versions: Counter = Counter()

    def fetch_one(accession: str) -> list[dict[str, str]]:
        nonlocal downloaded, isoforms_left_out
        body = http_get(f"{ALPHAFOLD_API}/{quote(accession, safe='')}", "application/json")
        entries = json.loads(body) if body else []
        if not isinstance(entries, list):
            raise RequestFailed("unexpected response from AlphaFold DB")
        # AlphaFold DB also returns one entry per isoform (P12345-2). Keep the accession's own
        # entry, and the isoform entries only on request or when it has no entry of its own.
        entries.sort(key=lambda entry: (entry.get("uniprotAccession") != accession, str(entry.get("uniprotAccession"))))
        own = [entry for entry in entries if entry.get("uniprotAccession") == accession]
        if own and not args.isoforms:
            isoforms_left_out += len(entries) - len(own)
            entries = own
        records = []
        for entry in entries:
            record = {column: cell(entry.get(source)) for column, source in ALPHAFOLD_SOURCE}
            record["entry_url"] = f"{ALPHAFOLD_ENTRY}/{quote(accession, safe='')}"
            saved = []
            for kind in downloads:
                url = record[ALPHAFOLD_DOWNLOADS[kind]]
                if not url:
                    continue
                content = http_get(url, "*/*", timeout=120)
                if content is None:
                    raise RequestFailed(f"HTTP 404 for {url}")
                files_dir.mkdir(parents=True, exist_ok=True)
                name = url.rsplit("/", 1)[-1]
                (files_dir / name).write_bytes(content)
                saved.append(name)
            downloaded += len(saved)
            record["downloaded_files"] = ";".join(saved)
            versions[record["latest_version"]] += 1
            records.append(record)
        return records

    results = per_accession(accessions, fetch_one, ALPHAFOLD_DELAY)
    source = {
        "name": "AlphaFold Protein Structure Database",
        "endpoint": f"{ALPHAFOLD_API}/<accession>",
        "model_versions": dict(versions),
        "licence": "https://alphafold.ebi.ac.uk/",
    }
    options = {
        "isoforms": args.isoforms,
        "isoform_entries_left_out": isoforms_left_out,
        "download": downloads,
        "files_dir": str(files_dir) if downloads else None,
        "files_downloaded": downloaded,
    }
    return results, {"source": source, "options": options}


def quickgo_query(accessions: list[str]) -> list[dict[str, str]]:
    params = {
        "geneProductId": ",".join(accessions),
        "downloadLimit": QUICKGO_DOWNLOAD_LIMIT,
        # Without includeFields the GO NAME column comes back empty.
        "includeFields": "goName",
        "selectedFields": QUICKGO_SELECTED,
    }
    url = f"{QUICKGO}/annotation/downloadSearch?{urlencode(params, safe=',:')}"
    lines = (http_get(url, "text/tsv", QUICKGO_TIMEOUT) or b"").decode("utf-8").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    expected = [name for _, name in QUICKGO_SOURCE]
    if header != expected:
        raise RequestFailed(f"QuickGO returned columns {header}; expected {expected}")
    if len(lines) - 1 >= QUICKGO_DOWNLOAD_LIMIT:
        raise RequestFailed(f"reached the download limit of {QUICKGO_DOWNLOAD_LIMIT} rows")
    records = []
    for line in lines[1:]:
        values = line.split("\t")
        if len(values) != len(header):
            raise RequestFailed(f"unexpected QuickGO row: {line[:120]!r}")
        records.append({**dict(zip(GO_FIELDS, values)), "source": QUICKGO_SOURCE_NAME})
    return records


def quickgo_annotations(accessions: list[str]) -> tuple[dict[str, list[dict[str, str]]], dict[str, str]]:
    """Annotations per accession from QuickGO, and the accessions it failed on."""
    found: dict[str, list[dict[str, str]]] = {}
    failed: dict[str, str] = {}

    def store(batch: list[str], records: list[dict[str, str]]) -> None:
        for accession in batch:
            found[accession] = []
        for record in records:
            # Annotations on an isoform (P12345-2) belong to the accession that was queried.
            accession = record["gene_product_id"].split("-")[0]
            if accession in found:
                found[accession].append(record)

    done = 0
    for start in range(0, len(accessions), QUICKGO_BATCH):
        batch = accessions[start:start + QUICKGO_BATCH]
        try:
            store(batch, quickgo_query(batch))
        except RequestFailed as error:
            # One accession can sink a batch, so retry each alone before giving up on it.
            log(f"  batch failed ({error}); retrying its {len(batch)} accessions one by one")
            for accession in batch:
                try:
                    store([accession], quickgo_query([accession]))
                except RequestFailed as single_error:
                    failed[accession] = str(single_error)
        done += len(batch)
        log(f"  QuickGO: {done}/{len(accessions)} accessions")
    return found, failed


def quickgo_names(terms: list[str]) -> dict[str, str]:
    """Names of GO terms the ontology file lacks. Best effort."""
    names: dict[str, str] = {}
    for start in range(0, len(terms), QUICKGO_BATCH):
        batch = ",".join(terms[start:start + QUICKGO_BATCH])
        try:
            body = http_get(f"{QUICKGO}/ontology/go/terms/{quote(batch, safe=',:')}", "application/json")
            for term in json.loads(body or b"{}").get("results", []):
                if term.get("id") and term.get("name"):
                    names[term["id"]] = term["name"]
        except (RequestFailed, ValueError, AttributeError):
            continue
    return names


def quickgo_releases() -> dict:
    releases = {}
    for name, path, key in (("annotation_release", "annotation/about", "annotation"),
                            ("ontology_release", "ontology/go/about", "go")):
        try:
            about = json.loads(http_get(f"{QUICKGO}/{path}", "application/json") or b"{}")
            releases[name] = (about.get(key) or {}).get("timestamp")
        except (RequestFailed, ValueError, AttributeError):
            releases[name] = None
    return releases


def read_go_file(cache: Path, wanted: set[str]) -> dict[str, list[dict[str, str]]]:
    """Annotations for the wanted accessions from the cached GOA file, without term names."""
    found: dict[str, list[dict[str, str]]] = {}
    with gzip.open(cache / DATASETS["go_annotations"][1], "rt", encoding="utf-8") as source:
        for line in source:
            if line.startswith("!"):
                continue
            fields = line.rstrip("\n").split("\t")
            if fields[1] not in wanted:
                continue
            found.setdefault(fields[1], []).append({
                "gene_product_db": fields[0],
                "gene_product_id": fields[1],
                "symbol": fields[2],
                "qualifier": fields[3],
                "go_term": fields[4],
                "go_name": "",
                "go_aspect": fields[8],
                "go_evidence_code": fields[6],
                "reference": fields[5],
                "with_from": fields[7],
                # The file writes taxon:10090; QuickGO writes 10090.
                "taxon_id": fields[12].replace("taxon:", ""),
                "assigned_by": fields[14],
                "annotation_extension": fields[15],
                "date": fields[13],
                "source": GOA_SOURCE_NAME,
            })
    return found


def read_go_terms(cache: Path) -> dict[str, str]:
    with gzip.open(cache / DATASETS["go_ontology"][1], "rt", encoding="utf-8") as source:
        next(source)
        return dict(line.rstrip("\n").split("\t", 1) for line in source)


def fetch_go(accessions: list[str], args: argparse.Namespace) -> tuple[Result, dict]:
    evidence = [code.upper() for code in args.evidence or []]
    bad = [code for code in evidence if not GO_EVIDENCE.match(code)]
    if bad:
        raise ToolError(f"--evidence takes GO evidence codes such as IDA or IMP, not: {', '.join(bad)}")
    aspects = {GO_ASPECTS[name] for name in args.aspect or []}
    cache = Path(args.cache_dir)

    files: dict[str, dict] = {}
    outcomes: dict[str, str] = {}
    from_file: dict[str, list[dict[str, str]]] = {}
    if not args.api_only:
        annotations, outcomes["go_annotations"] = ensure_dataset(cache, "go_annotations", args.refresh)
        ontology, outcomes["go_ontology"] = ensure_dataset(cache, "go_ontology", args.refresh)
        files = {
            "annotations": describe(annotations, ["date_generated", "go_version"]),
            "ontology": describe(ontology, ["data_version"]),
        }
        from_file = read_go_file(cache, set(accessions))
        names = read_go_terms(cache)
        for records in from_file.values():
            for record in records:
                record["go_name"] = names.get(record["go_term"], "")

    # The file holds one protein per gene, so an accession it lacks may still be annotated.
    remaining = [accession for accession in accessions if accession not in from_file]
    from_api, failed = quickgo_annotations(remaining) if remaining else ({}, {})

    unnamed = sorted({r["go_term"] for records in from_file.values() for r in records if not r["go_name"]})
    late_names = quickgo_names(unnamed) if unnamed else {}
    for records in from_file.values():
        for record in records:
            if not record["go_name"]:
                record["go_name"] = late_names.get(record["go_term"], "")

    results: Result = {}
    for accession in accessions:
        if accession in failed:
            results[accession] = ("failed", [], failed[accession])
            continue
        records = [
            record for record in from_file.get(accession) or from_api.get(accession, [])
            if (not aspects or record["go_aspect"] in aspects)
            and (not evidence or record["go_evidence_code"] in evidence)
        ]
        results[accession] = ("found", records, "") if records else ("no_entry", [], "")

    source = {
        "name": "Gene Ontology annotations (EMBL-EBI GOA)",
        "files": files or None,
        "api": {"name": "QuickGO", "endpoint": f"{QUICKGO}/annotation/downloadSearch", **quickgo_releases()}
        if remaining or unnamed else None,
        "licence": "https://geneontology.org/docs/go-citation-policy/",
    }
    options = {
        "aspect": args.aspect or "all",
        "evidence": evidence or "all",
        "api_only": args.api_only,
        "bulk_files": outcomes,
        "accessions_from_bulk_file": len(from_file),
        "accessions_asked_of_quickgo": len(remaining),
        "accessions_found_in_quickgo": sum(bool(records) for records in from_api.values()),
        "go_terms_named_by_quickgo": len(late_names),
        "go_terms_without_name": len(unnamed) - len(late_names),
    }
    return results, {"source": source, "options": options}


def fetch_reactome(accessions: list[str], args: argparse.Namespace) -> tuple[Result, dict]:
    cache = Path(args.cache_dir)
    entry, outcome = ensure_dataset(cache, "reactome", args.refresh)
    wanted = set(accessions)
    found: dict[str, list[dict[str, str]]] = {}
    with gzip.open(cache / DATASETS["reactome"][1], "rt", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["uniprot_accession"] in wanted:
                found.setdefault(row["uniprot_accession"], []).append({field: row[field] for field in REACTOME_FIELDS})
    results: Result = {}
    for accession in accessions:
        records = sorted(found.get(accession, []), key=lambda record: record["st_id"])
        results[accession] = ("found", records, "") if records else ("no_entry", [], "")
    source = {
        "name": "Reactome",
        "files": {"pathways": describe(entry, ["release_at_download", "species"])},
        "licence": "https://reactome.org/license",
    }
    return results, {"source": source, "options": {"bulk_files": {"reactome": outcome}}}


RESOURCES = {
    "alphafold": (fetch_alphafold, ALPHAFOLD_FIELDS),
    "go": (fetch_go, GO_FIELDS),
    "reactome": (fetch_reactome, REACTOME_FIELDS),
}


def capped(ids: list[str]) -> dict:
    return {"count": len(ids), "ids": ids[:MAX_IDS_IN_SUMMARY], "truncated": len(ids) > MAX_IDS_IN_SUMMARY}


def run(args: argparse.Namespace) -> int:
    fetch, fields = RESOURCES[args.command]
    pairs, coverage = read_mapping(Path(args.mapping))
    accessions = list(dict.fromkeys(pair["uniprot_accession"] for pair in pairs))
    out = Path(args.out)
    if out.parent and not out.parent.exists():
        raise ToolError(f"output directory not found: {out.parent}")

    log(f"{args.command}: querying {len(accessions)} accessions for {len({pair['mgi_id'] for pair in pairs})} genes")
    retrieved_at = utc_now()
    results, details = fetch(accessions, args)

    rows_written = 0
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=KEY_FIELDS + fields, lineterminator="\n")
        writer.writeheader()
        for pair in pairs:
            status, records, _ = results[pair["uniprot_accession"]]
            for record in records or [dict.fromkeys(fields, "")]:
                writer.writerow({**pair, "status": status, **record})
                rows_written += 1

    def with_status(status: str) -> list[str]:
        return [accession for accession in accessions if results[accession][0] == status]

    failed = with_status("failed")
    status_counts = Counter(results[accession][0] for accession in accessions)
    summary = {
        "resource": args.command,
        "mapping": str(args.mapping),
        "output": str(out),
        **coverage,
        "accessions_queried": len(accessions),
        "status_counts": {status: status_counts[status] for status in STATUSES},
        "rows_written": rows_written,
        "no_entry": capped(with_status("no_entry")),
        "failed": {**capped(failed), "errors": {accession: results[accession][2] for accession in failed[:MAX_IDS_IN_SUMMARY]}},
        "options": details["options"],
        "source": {**details["source"], "retrieved_at": retrieved_at},
    }
    print(json.dumps(summary, indent=2))
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mapping", required=True, help="CSV written by impc-uniprot-mapper (uniprot_idmap.py map)")
    common.add_argument("--out", required=True, help="output CSV")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    alphafold = commands.add_parser("alphafold", parents=[common], help="AlphaFold DB entries, confidence and file links")
    alphafold.add_argument(
        "--isoforms", action="store_true",
        help="also return the entries AlphaFold DB holds for isoforms of each accession",
    )
    alphafold.add_argument(
        "--download", nargs="+", choices=sorted(ALPHAFOLD_DOWNLOADS),
        help="also save these files for every entry: cif and pdb (model), pae (predicted aligned error), "
        "plddt (per-residue confidence)",
    )
    alphafold.add_argument("--files-dir", help="where --download saves files; default: alphafold_files next to --out")

    cached = argparse.ArgumentParser(add_help=False)
    cached.add_argument("--cache-dir", default=str(DEFAULT_CACHE), help="where bulk files are kept; default: %(default)s")

    refreshable = argparse.ArgumentParser(add_help=False)
    refreshable.add_argument("--refresh", action="store_true", help="download the bulk files again if their source has changed")

    go = commands.add_parser("go", parents=[common, cached, refreshable], help="GO annotations")
    go.add_argument("--aspect", nargs="+", choices=sorted(GO_ASPECTS), help="keep only these GO aspects; default: all")
    go.add_argument(
        "--evidence", nargs="+", metavar="CODE",
        help="keep only annotations with these GO evidence codes, for example IDA IMP; default: all",
    )
    go.add_argument(
        "--api-only", action="store_true",
        help="skip the bulk file and ask QuickGO for every accession (about 1 second per protein)",
    )

    commands.add_parser("reactome", parents=[common, cached, refreshable], help="lowest-level Reactome pathways")
    commands.add_parser("status", parents=[cached], help="show the bulk files held in the cache")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "status":
            return show_status(Path(args.cache_dir))
        return run(args)
    except ToolError as error:
        log(f"error: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
