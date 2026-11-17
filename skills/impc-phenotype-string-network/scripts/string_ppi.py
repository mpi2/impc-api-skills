#!/usr/bin/env python3
"""Run STRING PPI enrichment on IMPC phenotype gene sets (stdlib only).

Reads the gene table built in step 2 of the skill, maps genes to mouse STRING
proteins and tests each gene set twice: against the whole proteome (STRING MCP
`string_ppi_enrichment`) and against IMPC-tested genes (STRING REST, because
the MCP tool has no background parameter). When there are two or more sets,
their union is tested as well. Each tested set also gets a link to its
interactive STRING network, unless it is too large for STRING's viewer.

Writes 03_string_mapping.csv, 04_ppi_enrichment.csv,
05_impc_tested_background.csv and string_run.json to --out-dir, plus
06_network_images/ with --images. string_run.json lists every request the
script made, in order, with its outcome; it is written even after a crash.
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_client import McpClient  # noqa: E402

SPECIES = 10090
MCP_URL = "https://mcp.string-db.org/"
MCP_TOOL = "string_ppi_enrichment"
REST_URL = "https://string-db.org/api"
SOLR_URL = "https://www.ebi.ac.uk/mi/impc/solr/statistical-result/select"
CALLER = "impc-phenotype-string-network"
DELAY_SECONDS = 1  # STRING asks for one second between calls, never parallel
MAP_CHUNK = 2000
MIN_PROTEINS = 2  # STRING expands a single protein to its neighbours
RESULT_FIELDS = ["number_of_nodes", "number_of_edges", "average_node_degree",
                 "local_clustering_coefficient", "expected_number_of_edges", "p_value"]
# Network view limits, from STRING's own guidance (MCP string_help, large_input):
# under ~300 proteins reads well, larger networks become hairballs, and past
# ~2000 the website disables the network view.
VIEW_DENSE = 300
VIEW_MAX = 2000
IMAGE_MAX = 300  # a 1,000-protein network was a 36 MB SVG
IMAGE_DIR = "06_network_images"
REQUIRED_COLUMNS = ["query_mp_term_id", "query_mp_term_name", "marker_accession_id", "marker_symbol"]
REQUESTS: list[dict] = []  # this run's requests, in order, for string_run.json


class NothingFound(RuntimeError):
    """STRING answers 404, not an empty list, when no identifier matches."""


def log(message: str) -> None:
    print(message, file=sys.stderr)


def attempt(purpose: str, function: str, url: str, params: dict) -> dict:
    """Record a request before it is sent; the caller fills in the outcome.

    Identifier lists are logged as counts; the files hold the ids themselves.
    """
    shown = {key: (f"<{len(value.split(chr(13)))} identifiers>"
                   if key in ("identifiers", "background_string_identifiers") else value)
             for key, value in params.items()}
    entry = {"order": len(REQUESTS) + 1, "purpose": purpose, "function": function,
             "url": url, "params": shown, "outcome": "not run"}
    REQUESTS.append(entry)
    return entry


def string_post(method: str, data: dict, purpose: str, retries: int = 2, fmt: str = "json"):
    """POST to STRING REST; returns parsed JSON, or raw bytes for other formats."""
    url = f"{REST_URL}/{fmt}/{method}"
    payload = {**data, "caller_identity": CALLER}
    entry = attempt(purpose, "STRING REST POST", url, payload)
    body = urllib.parse.urlencode(payload).encode()
    for tries in range(retries + 1):
        entry["tries"] = tries + 1
        try:
            with urllib.request.urlopen(urllib.request.Request(url, body), timeout=280) as r:
                result = json.load(r) if fmt == "json" else r.read()
            entry["outcome"] = "worked"
            entry["returned"] = len(result) if fmt == "json" else f"{len(result)} bytes"
            time.sleep(DELAY_SECONDS)
            return result
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 404 and "nothing found" in detail:
                entry["outcome"] = "zero results"
                time.sleep(DELAY_SECONDS)
                raise NothingFound(detail) from e
            if e.code < 500 or tries == retries:
                entry.update(outcome="failed", error=f"HTTP {e.code}: {detail}")
                raise RuntimeError(f"STRING {method} HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if tries == retries:
                entry.update(outcome="failed", error=str(e))
                raise RuntimeError(f"STRING {method}: {e}") from e
        time.sleep(2 * (tries + 1))
    raise RuntimeError("unreachable")


def map_ids(ids: list[str], purpose: str) -> dict[str, dict]:
    """Map identifiers to one STRING protein each; missing ids stay absent."""
    mapped: dict[str, dict] = {}
    for start in range(0, len(ids), MAP_CHUNK):
        try:
            rows = string_post("get_string_ids", {
                "identifiers": "\r".join(ids[start:start + MAP_CHUNK]),
                "species": SPECIES, "limit": 1, "echo_query": 1,
            }, purpose)
        except NothingFound:
            continue
        for row in rows:
            mapped.setdefault(row["queryItem"], row)
    return mapped


def read_gene_sets(path: Path) -> tuple[OrderedDict, dict[str, str]]:
    """Return {term id: {label, genes}} and {MGI id: symbol}."""
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"{path}: missing columns {missing}")
        rows = list(reader)
    if not rows:
        raise SystemExit(f"{path}: no rows")
    sets: OrderedDict = OrderedDict()
    symbols: dict[str, str] = {}
    for row in rows:
        entry = sets.setdefault(row["query_mp_term_id"],
                                {"label": row["query_mp_term_name"], "genes": set()})
        entry["genes"].add(row["marker_accession_id"])
        symbols[row["marker_accession_id"]] = row["marker_symbol"]
    return sets, symbols


def same_name(hit: dict, symbol: str) -> bool:
    return hit.get("preferredName", "").casefold() == symbol.casefold()


def map_genes(symbols: dict[str, str], which: str) -> list[dict]:
    """Map by MGI id, which is stable, then by symbol on an exact name match.

    A symbol hit with another name is rejected, not used: STRING's best guess
    can be a different gene (Pla2g2a resolves to Itga5).
    """
    by_mgi = map_ids(sorted(symbols), f"map {which} by MGI id")
    leftover = {mgi: sym for mgi, sym in symbols.items() if mgi not in by_mgi}
    by_symbol = (map_ids(sorted(set(leftover.values())), f"map remaining {which} by symbol")
                 if leftover else {})
    table = []
    for mgi in sorted(symbols):
        symbol = symbols[mgi]
        hit, via, rejected = by_mgi.get(mgi), "mgi_id", ""
        if hit is None:
            candidate = by_symbol.get(symbol)
            if candidate and same_name(candidate, symbol):
                hit, via = candidate, "symbol"
            elif candidate:
                rejected = candidate.get("preferredName", "")
        table.append({
            "marker_accession_id": mgi,
            "marker_symbol": symbol,
            "string_id": hit["stringId"] if hit else "",
            "string_preferred_name": hit.get("preferredName", "") if hit else "",
            "mapped_via": via if hit else "unmapped",
            "name_differs": bool(hit) and not same_name(hit, symbol),
            "rejected_symbol_hit": rejected,
        })
    return table


def impc_tested_genes() -> dict[str, str]:
    """All genes with a successful IMPC analysis, including those with no hit.

    `impc-api` returns no facets, so this calls Solr directly.
    """
    pivot = "marker_accession_id,marker_symbol"
    params = {"q": "status:Successful", "rows": 0, "wt": "json", "facet": "true",
              "facet.pivot": pivot, "facet.limit": -1, "facet.mincount": 1}
    entry = attempt("list IMPC-tested genes for the background", "Solr GET (facet pivot)",
                    SOLR_URL, params)
    try:
        with urllib.request.urlopen(f"{SOLR_URL}?{urllib.parse.urlencode(params)}",
                                    timeout=180) as r:
            genes = json.load(r)["facet_counts"]["facet_pivot"][pivot]
    except Exception as e:
        entry.update(outcome="failed", error=f"{type(e).__name__}: {e}")
        raise
    entry.update(outcome="worked", returned=len(genes))
    return {gene["value"]: gene["pivot"][0]["value"] for gene in genes if gene.get("pivot")}


def proteome_run(client, name: str, proteins: list[str], score: int) -> tuple[dict, str, str]:
    """Prefer the MCP tool; the REST method returns the same numbers if it fails."""
    error = ""
    purpose = f"{name}: PPI enrichment vs proteome"
    if client is not None:
        params = {"identifiers": "%0d".join(proteins), "species": str(SPECIES),
                  "required_score": score}
        entry = attempt(purpose, f"STRING MCP {MCP_TOOL}", MCP_URL,
                        {**params, "identifiers": "\r".join(proteins)})
        try:
            result = client.call_json(MCP_TOOL, params)
            time.sleep(DELAY_SECONDS)
            entry["outcome"] = "worked"
            return result["results"][0], "mcp", ""
        except (RuntimeError, OSError, KeyError, IndexError, ValueError) as e:
            error = f"MCP failed: {e}"
            entry.update(outcome="failed", error=str(e))
            log(error)
    rows = string_post("ppi_enrichment", {"identifiers": "\r".join(proteins),
                                          "species": SPECIES, "required_score": score}, purpose)
    return rows[0], "rest", error


def background_run(name: str, proteins: list[str], background: list[str], score: int) -> dict:
    return string_post("ppi_enrichment", {
        "identifiers": "\r".join(proteins), "species": SPECIES, "required_score": score,
        "background_string_identifiers": "\r".join(background),
    }, f"{name}: PPI enrichment vs IMPC-tested genes")[0]


def png_on_white(data: bytes) -> bytes:
    """Flatten STRING's transparent PNG onto white, so it reads in dark viewers.

    STRING's image API has no background option. Handles the 8-bit RGBA,
    non-interlaced PNG STRING returns; anything else is returned unchanged.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return data
    pos, header, compressed = 8, b"", []
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if kind == b"IHDR":
            header = data[pos + 8:pos + 8 + length]
        elif kind == b"IDAT":
            compressed.append(data[pos + 8:pos + 8 + length])
        pos += 12 + length
    width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", header)
    if (depth, color, interlace) != (8, 6, 0):
        return data
    raw, stride, bpp = zlib.decompress(b"".join(compressed)), width * 4, 4
    prior, out = bytearray(stride), bytearray()
    for row in range(height):
        start = row * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if kind == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif kind == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, prior))
        elif kind == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prior[i]) >> 1)) & 0xFF
        elif kind == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b, c = prior[i], (prior[i - bpp] if i >= bpp else 0)
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        prior = line
        alpha = line[3::4]
        rgb = bytearray(stride // 4 * 3)
        for channel in range(3):
            rgb[channel::3] = bytes((v * a + 255 * (255 - a)) // 255
                                    for v, a in zip(line[channel::4], alpha))
        out += b"\x00" + rgb

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (data[:8] + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(out), 9)) + chunk(b"IEND", b""))


def network_view(name: str, proteins: list[str], score: int, images: bool,
                 out_dir: Path) -> tuple[dict, list[str]]:
    """Link to the set's interactive STRING network and, with --images, a PNG.

    Uses the same proteins, species and score as the test, so the view shows
    the network that was tested. Score is never raised to thin a dense view.
    """
    view = {"string_network_url": "", "network_view_status": "", "network_image": ""}
    errors: list[str] = []
    n = len(proteins)
    if n > VIEW_MAX:
        view["network_view_status"] = (
            f"no link: {n} proteins, over STRING's ~{VIEW_MAX} viewer limit; "
            "load the ids from 03_string_mapping.csv into Cytoscape stringApp")
        return view, errors
    request = {"identifiers": "\r".join(proteins), "species": SPECIES, "required_score": score}
    try:
        view["string_network_url"] = string_post("get_link", request, f"{name}: network link")[0]
        view["network_view_status"] = (
            f"link; dense: {n} proteins, over {VIEW_DENSE}" if n > VIEW_DENSE else "link")
    except (RuntimeError, IndexError) as e:
        view["network_view_status"] = f"link failed: {e}"
        errors.append(f"{name} network link: {e}")
    if images:
        if n > IMAGE_MAX:
            view["network_view_status"] += f"; no image: over {IMAGE_MAX} proteins"
        else:
            path = out_dir / IMAGE_DIR / f"{name.replace(':', '_')}.png"
            try:
                path.parent.mkdir(exist_ok=True)
                image = string_post("network", request, f"{name}: network image", fmt="image")
                try:
                    image = png_on_white(image)
                except (struct.error, zlib.error, IndexError, ValueError):
                    pass  # keep STRING's transparent PNG rather than lose the image
                path.write_bytes(image)
                view["network_image"] = str(path.relative_to(out_dir))
            except (RuntimeError, OSError) as e:
                view["network_view_status"] += f"; image failed: {e}"
                errors.append(f"{name} network image: {e}")
    return view, errors


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def result_row(name, label, set_type, genes, proteins, background, source, score, result, status):
    row = {"gene_set": name, "gene_set_label": label, "set_type": set_type,
           "background": background, "source": source, "required_score": score,
           "genes_in_set": genes, "proteins_mapped": proteins, "status": status}
    row.update({field: (result or {}).get(field, "") for field in RESULT_FIELDS})
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genes", type=Path, required=True, help="02_impc_genes.csv")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--required-score", type=int, default=400,
                        help="STRING interaction confidence, 0-1000 (default 400, STRING's own default)")
    parser.add_argument("--images", action="store_true",
                        help=f"also save a PNG of each network of {IMAGE_MAX} proteins or fewer "
                             f"to {IMAGE_DIR}/ (off by default: large images are slow and unreadable)")
    args = parser.parse_args()
    if not 0 <= args.required_score <= 1000:
        parser.error("--required-score must be between 0 and 1000")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        return run(args)
    except Exception as e:
        # Keep the request record when a crash stops the run before its summary
        (args.out_dir / "string_run.json").write_text(json.dumps({
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "crashed", "errors": [f"{type(e).__name__}: {e}"],
            "requests": REQUESTS}, indent=2, default=str) + "\n")
        raise


def run(args: argparse.Namespace) -> int:
    score = args.required_score
    sets, symbols = read_gene_sets(args.genes)
    log(f"{len(sets)} gene set(s), {len(symbols)} genes")

    mapping = map_genes(symbols, "query genes")
    protein_of = {row["marker_accession_id"]: row["string_id"] for row in mapping if row["string_id"]}
    log(f"mapped {len(protein_of)}/{len(symbols)} genes")
    write_csv(args.out_dir / "03_string_mapping.csv", mapping, list(mapping[0]))

    universe = impc_tested_genes()
    universe_mapping = map_genes(universe, "IMPC-tested genes")
    tested = {row["string_id"] for row in universe_mapping if row["string_id"]}
    query_proteins = set(protein_of.values())
    # STRING rejects a query protein missing from the background. Query genes
    # are tested genes, so this should stay empty; it guards against a failed run.
    added = sorted(query_proteins - tested)
    background = sorted(tested | query_proteins)
    write_csv(args.out_dir / "05_impc_tested_background.csv",
              [{"string_id": protein} for protein in background], ["string_id"])
    log(f"background: {len(universe)} tested genes, {len(background)} proteins")

    gene_sets = [(term, entry["label"], "single", entry["genes"]) for term, entry in sets.items()]
    if len(gene_sets) > 1:
        union = set().union(*(entry["genes"] for entry in sets.values()))
        gene_sets.append(("combined", " + ".join(sets), "combined", union))

    client, mcp_error = None, ""
    entry = attempt("connect to STRING MCP and list its tools", "MCP initialize + tools/list",
                    MCP_URL, {})
    try:
        client = McpClient(MCP_URL)
        if MCP_TOOL not in {tool["name"] for tool in client.list_tools()}:
            raise RuntimeError(f"{MCP_TOOL} not listed by server")
        entry["outcome"] = "worked"
    except (RuntimeError, OSError, ValueError, KeyError, IndexError) as e:
        client, mcp_error = None, str(e)
        entry.update(outcome="failed", error=str(e))
        log(f"STRING MCP unavailable, using REST: {e}")

    rows: list[dict] = []
    errors: list[str] = [mcp_error] if mcp_error else []
    for name, label, set_type, genes in gene_sets:
        proteins = sorted({protein_of[g] for g in genes if g in protein_of})
        common = (name, label, set_type, len(genes), len(proteins))
        # A parent queried with its children already holds their genes, so the
        # union can equal a set tested above; testing it again repeats that row.
        duplicate = next((term for term, entry in sets.items() if entry["genes"] == genes), None)
        if set_type == "combined" and duplicate:
            status = f"not tested: same genes as {duplicate}"
            view = {"network_view_status": f"not made: same network as {duplicate}"}
        elif len(proteins) < MIN_PROTEINS:
            status = (f"not tested: fewer than {MIN_PROTEINS} mapped proteins; "
                      "STRING would test its own neighbours instead")
            view = {"network_view_status": f"not made: fewer than {MIN_PROTEINS} mapped proteins"}
        else:
            status = ""
        if status:
            log(f"{name}: {status}")
            for bg in ("proteome", "impc_tested"):
                rows.append({**result_row(*common, bg, "", score, None, status),
                             "string_network_url": "", "network_image": "", **view})
            continue
        first = len(rows)
        try:
            result, source, warning = proteome_run(client, name, proteins, score)
            errors += [f"{name}: {warning}"] if warning else []
            rows.append(result_row(*common, "proteome", source, score, result, "worked"))
        except RuntimeError as e:
            errors.append(f"{name} proteome: {e}")
            rows.append(result_row(*common, "proteome", "", score, None, f"failed: {e}"))
        try:
            result = background_run(name, proteins, background, score)
            rows.append(result_row(*common, "impc_tested", "rest", score, result, "worked"))
        except RuntimeError as e:
            errors.append(f"{name} impc_tested: {e}")
            rows.append(result_row(*common, "impc_tested", "rest", score, None, f"failed: {e}"))
        view, view_errors = network_view(name, proteins, score, args.images, args.out_dir)
        errors += view_errors
        for row in rows[first:]:
            row.update(view)  # one network per set, the same under both backgrounds
        log(f"{name}: {len(proteins)} proteins done")

    fields = ["gene_set", "gene_set_label", "set_type", "background", "source", "required_score",
              "genes_in_set", "proteins_mapped", *RESULT_FIELDS, "status",
              "string_network_url", "network_view_status", "network_image"]
    write_csv(args.out_dir / "04_ppi_enrichment.csv", rows, fields)

    try:
        version = string_post("version", {}, "record STRING version")[0]
    except RuntimeError as e:
        version = {"error": str(e)}
    mapped_via = [row["mapped_via"] for row in mapping]
    (args.out_dir / "string_run.json").write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "string_version": version,
        "species": SPECIES,
        "required_score": score,
        "mcp": {"url": MCP_URL, "tool": MCP_TOOL, "used": client is not None},
        "rest": {"url": f"{REST_URL}/json/ppi_enrichment", "caller_identity": CALLER},
        "network_view": {
            "link_method": f"{REST_URL}/json/get_link",
            "dense_above_proteins": VIEW_DENSE,
            "no_link_above_proteins": VIEW_MAX,
            "images": args.images,
            "image_method": f"{REST_URL}/image/network" if args.images else None,
            "image_max_proteins": IMAGE_MAX,
        },
        "background": {
            "definition": "genes in the IMPC statistical-result core with status:Successful",
            "solr_query": "status:Successful",
            "genes": len(universe),
            "genes_mapped": sum(1 for row in universe_mapping if row["string_id"]),
            "proteins": len(background),
            "query_proteins_added": added,
        },
        "mapping": {"genes": len(mapping), "by_mgi_id": mapped_via.count("mgi_id"),
                    "by_symbol": mapped_via.count("symbol"), "unmapped": mapped_via.count("unmapped"),
                    "name_differs": sum(row["name_differs"] for row in mapping)},
        "status": "finished",
        "errors": errors,
        "requests": REQUESTS,
    }, indent=2, default=str) + "\n")
    log(f"wrote {len(rows)} result rows to {args.out_dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
