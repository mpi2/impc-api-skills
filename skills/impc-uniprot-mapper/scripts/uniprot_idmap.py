#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Build and query a local MGI to UniProt mapping from UniProt's mouse idmapping file.

Commands:
  build    create the mapping if it does not exist yet
  refresh  replace the mapping only if UniProt has published a newer file
  rebuild  always download again and regenerate the mapping
  status   show what is cached and every download made so far
  map      look up MGI gene ids; reviewed accessions only unless asked otherwise

Lookups never touch the network. A failed download leaves any existing mapping intact.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

SOURCE_FILE = "MOUSE_10090_idmapping.dat.gz"
SOURCE_DIR = "https://ftp.uniprot.org/pub/databases/uniprot/knowledgebase/idmapping/by_organism"
SOURCE_URL = f"{SOURCE_DIR}/{SOURCE_FILE}"
METALINK_URL = f"{SOURCE_DIR}/RELEASE.metalink"
METALINK_NS = {"m": "http://www.metalinker.org/"}

DEFAULT_CACHE = Path.home() / ".cache" / "impc-skills" / "uniprot"
MAPPING_NAME = "mgi_uniprot.tsv.gz"
METADATA_NAME = "metadata.json"
HISTORY_NAME = "download_history.jsonl"
MAPPING_HEADER = ["mgi_id", "uniprot_accession", "entry_name", "gene_name", "reviewed"]
OUTPUT_FIELDS = [*MAPPING_HEADER, "mapping_status", "n_reviewed", "n_unreviewed"]

USER_AGENT = "impc-uniprot-mapper"
TIMEOUT_SECONDS = 60
DOWNLOAD_ATTEMPTS = 3
MAX_IDS_IN_SUMMARY = 25
MGI_ID = re.compile(r"^MGI:\d+$")


class ToolError(Exception):
    """An expected failure, reported to the user without a traceback."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url: str, headers: dict[str, str] | None = None):
    request = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urlopen(request, timeout=TIMEOUT_SECONDS)


def fetch_release() -> dict:
    """Return the UniProt release, data license and published md5. All are best effort."""
    try:
        with http_get(METALINK_URL) as response:
            root = ElementTree.fromstring(response.read())
    except (OSError, HTTPException, ElementTree.ParseError):
        return {"version": None, "md5": None, "license": None}
    md5 = None
    for entry in root.iterfind("m:files/m:file", METALINK_NS):
        if entry.get("name") == SOURCE_FILE:
            md5 = entry.findtext("m:verification/m:hash[@type='md5']", namespaces=METALINK_NS)
    license_name = root.findtext("m:license/m:name", namespaces=METALINK_NS)
    license_url = root.findtext("m:license/m:url", namespaces=METALINK_NS)
    return {
        "version": root.findtext("m:version", namespaces=METALINK_NS),
        "md5": md5,
        "license": {"name": license_name, "url": license_url} if license_name else None,
    }


def download(destination: Path, etag: str | None) -> dict | None:
    """Download the source file. Return None when the server reports no change."""
    headers = {"If-None-Match": etag} if etag else {}
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            sha256 = hashlib.sha256()
            md5 = hashlib.md5(usedforsecurity=False)
            size = 0
            with http_get(SOURCE_URL, headers) as response, destination.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    sha256.update(chunk)
                    md5.update(chunk)
                    size += len(chunk)
            expected = response.headers.get("Content-Length")
            if expected and int(expected) != size:
                raise OSError(f"received {size} of {expected} bytes")
            return {
                "size_bytes": size,
                "sha256": sha256.hexdigest(),
                "md5": md5.hexdigest(),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
            }
        except HTTPError as error:
            if error.code == 304:
                return None
            if error.code < 500:
                raise ToolError(f"download failed: HTTP {error.code} for {SOURCE_URL}") from error
            last_error = error
        except (OSError, HTTPException) as error:
            last_error = error
        if attempt < DOWNLOAD_ATTEMPTS:
            time.sleep(2**attempt)
    raise ToolError(f"download failed after {DOWNLOAD_ATTEMPTS} attempts: {last_error}")


def parse_source(path: Path) -> tuple[list[tuple[str, str, str, str, bool]], dict[str, int]]:
    """Extract every MGI to accession pair. Abort if the file is not in the expected format."""
    gene_to_accessions: dict[str, set[str]] = defaultdict(set)
    entry_names: dict[str, str] = {}
    gene_names: dict[str, list[str]] = defaultdict(list)
    source_rows = 0
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                fields = line.rstrip("\n").split("\t")
                if len(fields) != 3:
                    raise ToolError(f"unexpected format at line {line_number}: {line[:120]!r}")
                accession, id_type, value = fields
                source_rows += 1
                if id_type == "MGI":
                    if not MGI_ID.match(value):
                        raise ToolError(f"unexpected MGI id at line {line_number}: {value!r}")
                    gene_to_accessions[value].add(accession)
                elif id_type == "UniProtKB-ID":
                    entry_names[accession] = value
                elif id_type == "Gene_Name" and value not in gene_names[accession]:
                    gene_names[accession].append(value)
    except (EOFError, zlib.error, gzip.BadGzipFile) as error:
        raise ToolError(f"source file is truncated or corrupt: {error}") from error
    if not gene_to_accessions:
        raise ToolError("source file contains no MGI rows; its format may have changed")

    rows = []
    for gene, accessions in gene_to_accessions.items():
        for accession in accessions:
            entry = entry_names.get(accession, "")
            # TrEMBL entry names are "<accession>_MOUSE"; Swiss-Prot names are mnemonic.
            reviewed = bool(entry) and not entry.startswith(f"{accession}_")
            rows.append((gene, accession, entry, ";".join(gene_names.get(accession, [])), reviewed))
    rows.sort(key=lambda row: (int(row[0].split(":")[1]), not row[4], row[1]))

    reviewed_per_gene = Counter(row[0] for row in rows if row[4])
    genes_per_accession = Counter(row[1] for row in rows)
    unique_accessions = {row[1]: row[4] for row in rows}
    counts = {
        "source_rows_parsed": source_rows,
        "rows": len(rows),
        "genes": len(gene_to_accessions),
        "accessions": len(unique_accessions),
        "reviewed_accessions": sum(unique_accessions.values()),
        "unreviewed_accessions": sum(not value for value in unique_accessions.values()),
        "genes_with_reviewed_hit": len(reviewed_per_gene),
        "genes_with_multiple_reviewed_hits": sum(n > 1 for n in reviewed_per_gene.values()),
        "genes_without_reviewed_hit": len(gene_to_accessions) - len(reviewed_per_gene),
        "accessions_linked_to_multiple_genes": sum(n > 1 for n in genes_per_accession.values()),
        "accessions_without_entry_name": sum(not row[2] for row in rows),
    }
    return rows, counts


def write_mapping(path: Path, rows: list[tuple[str, str, str, str, bool]]) -> str:
    """Write the mapping reproducibly and return its sha256."""
    with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
            text.write("\t".join(MAPPING_HEADER) + "\n")
            for gene, accession, entry, name, reviewed in rows:
                text.write(f"{gene}\t{accession}\t{entry}\t{name}\t{str(reviewed).lower()}\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_metadata(cache: Path) -> dict | None:
    """Return the metadata, or None if no complete mapping exists."""
    metadata_path = cache / METADATA_NAME
    if not metadata_path.exists() or not (cache / MAPPING_NAME).exists():
        return None
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def read_history(cache: Path) -> list[dict]:
    path = cache / HISTORY_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def describe(metadata: dict) -> str:
    return f"UniProt {metadata['source']['uniprot_release']}, retrieved {metadata['retrieved_at']}"


def update_cache(cache: Path, action: str) -> int:
    """Run build, refresh or rebuild."""
    cache.mkdir(parents=True, exist_ok=True)
    current = read_metadata(cache)
    if action == "build" and current:
        print(json.dumps({"result": "already_built", "cache_dir": str(cache), **current}, indent=2))
        return 0

    etag = current["source"]["etag"] if action == "refresh" and current else None
    try:
        with tempfile.TemporaryDirectory(dir=cache, prefix=".build-") as work:
            source_path = Path(work) / SOURCE_FILE
            mapping_path = Path(work) / MAPPING_NAME
            source = download(source_path, etag)
            if source is None:
                print(json.dumps({"result": "up_to_date", "cache_dir": str(cache), **current}, indent=2))
                return 0
            release = fetch_release()
            if release["md5"] and release["md5"] != source["md5"]:
                raise ToolError("download does not match the md5 published by UniProt")
            rows, counts = parse_source(source_path)
            mapping_sha256 = write_mapping(mapping_path, rows)
            metadata = {
                "retrieved_at": utc_now(),
                "source": {
                    "url": SOURCE_URL,
                    "uniprot_release": release["version"],
                    "last_modified": source["last_modified"],
                    "etag": source["etag"],
                    "size_bytes": source["size_bytes"],
                    "sha256": source["sha256"],
                    "md5_verified_against_uniprot": release["md5"] is not None,
                    "license": release["license"],
                },
                "mapping": {"file": MAPPING_NAME, "sha256": mapping_sha256, **counts},
            }
            # Without metadata a cache counts as absent, so a crash here cannot pair
            # a new mapping with the description of the old one.
            (cache / METADATA_NAME).unlink(missing_ok=True)
            os.replace(mapping_path, cache / MAPPING_NAME)
            (cache / METADATA_NAME).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    except ToolError as error:
        if current:
            raise ToolError(f"{error}. Existing mapping kept: {describe(current)}") from error
        raise ToolError(f"{error}. No mapping is available.") from error

    with (cache / HISTORY_NAME).open("a", encoding="utf-8") as history:
        history.write(json.dumps({"action": action, **metadata}) + "\n")
    print(json.dumps({"result": "built", "action": action, "cache_dir": str(cache), **metadata}, indent=2))
    return 0


def show_status(cache: Path) -> int:
    downloads = [
        {
            "action": item["action"],
            "retrieved_at": item["retrieved_at"],
            "uniprot_release": item["source"]["uniprot_release"],
            "last_modified": item["source"]["last_modified"],
            "source_sha256": item["source"]["sha256"],
            "genes": item["mapping"]["genes"],
            "rows": item["mapping"]["rows"],
        }
        for item in read_history(cache)
    ]
    metadata = read_metadata(cache)
    print(json.dumps({"cache_dir": str(cache), "built": bool(metadata), "current": metadata, "downloads": downloads}, indent=2))
    return 0


def read_ids(args: argparse.Namespace) -> list[str]:
    ids = list(args.ids)
    if args.input:
        path = Path(args.input)
        if not path.exists():
            raise ToolError(f"input file not found: {path}")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            if args.column:
                reader = csv.DictReader(handle, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")
                columns = reader.fieldnames or []
                if args.column not in columns:
                    raise ToolError(f"column {args.column!r} not in {path.name}; columns are: {', '.join(columns)}")
                ids += [row[args.column] for row in reader]
            else:
                ids += handle.read().splitlines()
    ids = [value.strip() for value in ids if value and value.strip()]
    if not ids:
        raise ToolError("no ids given; pass MGI ids or --input")
    return ids


def load_hits(cache: Path, wanted: set[str]) -> dict[str, list[dict[str, str]]]:
    """Return the mapping rows for the requested genes, reviewed accessions first."""
    hits: dict[str, list[dict[str, str]]] = defaultdict(list)
    with gzip.open(cache / MAPPING_NAME, "rt", encoding="utf-8", newline="") as mapping:
        reader = csv.DictReader(mapping, delimiter="\t", quoting=csv.QUOTE_NONE)
        if reader.fieldnames != MAPPING_HEADER:
            raise ToolError("cached mapping has an unexpected layout; run rebuild")
        for row in reader:
            if row["mgi_id"] in wanted:
                hits[row["mgi_id"]].append(row)
    return hits


def select_rows(gene: str, hits: list[dict[str, str]], unreviewed: str) -> list[dict[str, str | int]]:
    """Apply the accession policy to one gene. Every gene yields at least one row."""
    reviewed_hits = [hit for hit in hits if hit["reviewed"] == "true"]
    unreviewed_hits = [hit for hit in hits if hit["reviewed"] != "true"]
    counts = {"n_reviewed": len(reviewed_hits), "n_unreviewed": len(unreviewed_hits)}

    if not hits:
        return [blank_row(gene, "not_found", counts)]
    if reviewed_hits:
        status = "reviewed" if len(reviewed_hits) == 1 else "multiple_reviewed"
        chosen = hits if unreviewed == "include" else reviewed_hits
    elif unreviewed == "exclude":
        # The accessions stay out until the user opts in; the name identifies the gene for them.
        names = sorted({name for hit in hits for name in hit["gene_name"].split(";") if name})
        return [{**blank_row(gene, "no_reviewed_hit", counts), "gene_name": ";".join(names)}]
    else:
        status = "unreviewed"
        chosen = hits
    return [{**hit, "mapping_status": status, **counts} for hit in chosen]


def blank_row(gene: str, status: str, counts: dict[str, int]) -> dict[str, str | int]:
    empty = dict.fromkeys(MAPPING_HEADER, "")
    return {**empty, "mgi_id": gene, "mapping_status": status, **counts}


def capped(ids: list[str]) -> dict:
    return {"count": len(ids), "ids": ids[:MAX_IDS_IN_SUMMARY], "truncated": len(ids) > MAX_IDS_IN_SUMMARY}


def map_ids(args: argparse.Namespace) -> int:
    cache = Path(args.cache_dir)
    metadata = read_metadata(cache)
    if not metadata:
        raise ToolError(f"no mapping in {cache}; run build first")

    inputs = read_ids(args)
    unique = list(dict.fromkeys(inputs))
    valid = {value for value in unique if MGI_ID.match(value)}
    hits = load_hits(cache, valid)

    rows: list[dict[str, str | int]] = []
    status_by_gene: dict[str, str] = {}
    for gene in unique:
        if gene in valid:
            gene_rows = select_rows(gene, hits.get(gene, []), args.unreviewed)
        else:
            gene_rows = [blank_row(gene, "invalid_id", {"n_reviewed": 0, "n_unreviewed": 0})]
        status_by_gene[gene] = str(gene_rows[0]["mapping_status"])
        rows += gene_rows

    output = open(args.out, "w", encoding="utf-8", newline="") if args.out else sys.stdout
    try:
        writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.out:
            output.close()

    def with_status(status: str) -> list[str]:
        return [gene for gene, value in status_by_gene.items() if value == status]

    summary = {
        "unreviewed_policy": args.unreviewed,
        "input_ids": len(inputs),
        "unique_ids": len(unique),
        "rows_written": len(rows),
        "output": args.out or "stdout",
        "status_counts": dict(Counter(status_by_gene.values())),
        "no_reviewed_hit": capped(with_status("no_reviewed_hit")),
        "not_found": capped(with_status("not_found")),
        "invalid_id": capped(with_status("invalid_id")),
        "source": {
            "uniprot_release": metadata["source"]["uniprot_release"],
            "last_modified": metadata["source"]["last_modified"],
            "retrieved_at": metadata["retrieved_at"],
            "source_sha256": metadata["source"]["sha256"],
            "mapping_sha256": metadata["mapping"]["sha256"],
            # Absent from mappings built before the license was recorded; rebuild to add it.
            "license": metadata["source"].get("license"),
        },
    }
    print(json.dumps(summary, indent=2), file=sys.stderr)
    if not valid:
        raise ToolError("no valid MGI ids in input; expected values like MGI:1929470")
    return 0


def parse_args() -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cache-dir", default=str(DEFAULT_CACHE), help="default: %(default)s")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", parents=[common], help="create the mapping if it does not exist")
    commands.add_parser("refresh", parents=[common], help="update only if UniProt published a newer file")
    commands.add_parser("rebuild", parents=[common], help="always download again and regenerate")
    commands.add_parser("status", parents=[common], help="show the cached mapping and download history")

    lookup = commands.add_parser("map", parents=[common], help="look up MGI gene ids")
    lookup.add_argument("ids", nargs="*", help="MGI gene ids, for example MGI:1929470")
    lookup.add_argument("--input", help="file of ids, one per line, or a CSV/TSV with --column")
    lookup.add_argument("--column", help="column holding MGI ids in a CSV/TSV input")
    lookup.add_argument("--out", help="output CSV; default stdout")
    lookup.add_argument(
        "--unreviewed",
        choices=["exclude", "fallback", "include"],
        default="exclude",
        help="exclude: reviewed only (default). fallback: unreviewed for genes with no reviewed hit. "
        "include: every accession for every gene.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "map":
            return map_ids(args)
        if args.command == "status":
            return show_status(Path(args.cache_dir))
        return update_cache(Path(args.cache_dir), args.command)
    except ToolError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
