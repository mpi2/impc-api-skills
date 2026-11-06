#!/usr/bin/env python3
"""Run STRING PPI enrichment on IMPC phenotype gene sets (stdlib only).

Reads the gene table built in step 3 of the skill, maps genes to mouse STRING
proteins and tests each gene set twice: against the whole proteome (STRING MCP
`string_ppi_enrichment`) and against IMPC-tested genes (STRING REST, because
the MCP tool has no background parameter). When there are two or more sets,
their union is tested as well.

Writes 03_string_mapping.csv, 04_ppi_enrichment.csv,
05_impc_tested_background.csv and string_run.json to --out-dir.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
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
CALLER = "impc-string-ppi-enrichment"
DELAY_SECONDS = 1  # STRING asks for one second between calls, never parallel
MAP_CHUNK = 2000
MIN_PROTEINS = 2  # STRING expands a single protein to its neighbours
RESULT_FIELDS = ["number_of_nodes", "number_of_edges", "average_node_degree",
                 "local_clustering_coefficient", "expected_number_of_edges", "p_value"]
REQUIRED_COLUMNS = ["query_mp_term_id", "query_mp_term_name", "marker_accession_id", "marker_symbol"]


class NothingFound(RuntimeError):
    """STRING answers 404, not an empty list, when no identifier matches."""


def log(message: str) -> None:
    print(message, file=sys.stderr)


def string_post(method: str, data: dict, retries: int = 2):
    url = f"{REST_URL}/json/{method}"
    payload = {**data, "caller_identity": CALLER}
    body = urllib.parse.urlencode(payload).encode()
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, body), timeout=280) as r:
                result = json.load(r)
            time.sleep(DELAY_SECONDS)
            return result
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 404 and "nothing found" in detail:
                time.sleep(DELAY_SECONDS)
                raise NothingFound(detail) from e
            if e.code < 500 or attempt == retries:
                raise RuntimeError(f"STRING {method} HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries:
                raise RuntimeError(f"STRING {method}: {e}") from e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def map_ids(ids: list[str]) -> dict[str, dict]:
    """Map identifiers to one STRING protein each; missing ids stay absent."""
    mapped: dict[str, dict] = {}
    for start in range(0, len(ids), MAP_CHUNK):
        try:
            rows = string_post("get_string_ids", {
                "identifiers": "\r".join(ids[start:start + MAP_CHUNK]),
                "species": SPECIES, "limit": 1, "echo_query": 1,
            })
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


def map_genes(symbols: dict[str, str]) -> list[dict]:
    """Map by MGI id, which is stable, then by symbol on an exact name match.

    A symbol hit with another name is rejected, not used: STRING's best guess
    can be a different gene (Pla2g2a resolves to Itga5).
    """
    by_mgi = map_ids(sorted(symbols))
    leftover = {mgi: sym for mgi, sym in symbols.items() if mgi not in by_mgi}
    by_symbol = map_ids(sorted(set(leftover.values()))) if leftover else {}
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
    query = urllib.parse.urlencode({
        "q": "status:Successful", "rows": 0, "wt": "json", "facet": "true",
        "facet.pivot": pivot, "facet.limit": -1, "facet.mincount": 1,
    })
    with urllib.request.urlopen(f"{SOLR_URL}?{query}", timeout=180) as r:
        genes = json.load(r)["facet_counts"]["facet_pivot"][pivot]
    return {gene["value"]: gene["pivot"][0]["value"] for gene in genes if gene.get("pivot")}


def proteome_run(client, proteins: list[str], score: int) -> tuple[dict, str, str]:
    """Prefer the MCP tool; the REST method returns the same numbers if it fails."""
    error = ""
    if client is not None:
        try:
            result = client.call_json(MCP_TOOL, {"identifiers": "%0d".join(proteins),
                                                 "species": str(SPECIES), "required_score": score})
            time.sleep(DELAY_SECONDS)
            return result["results"][0], "mcp", ""
        except (RuntimeError, OSError, KeyError, IndexError, ValueError) as e:
            error = f"MCP failed: {e}"
            log(error)
    rows = string_post("ppi_enrichment", {"identifiers": "\r".join(proteins),
                                          "species": SPECIES, "required_score": score})
    return rows[0], "rest", error


def background_run(proteins: list[str], background: list[str], score: int) -> dict:
    return string_post("ppi_enrichment", {
        "identifiers": "\r".join(proteins), "species": SPECIES, "required_score": score,
        "background_string_identifiers": "\r".join(background),
    })[0]


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
    args = parser.parse_args()
    if not 0 <= args.required_score <= 1000:
        parser.error("--required-score must be between 0 and 1000")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    score = args.required_score

    sets, symbols = read_gene_sets(args.genes)
    log(f"{len(sets)} gene set(s), {len(symbols)} genes")

    mapping = map_genes(symbols)
    write_csv(args.out_dir / "03_string_mapping.csv", mapping, list(mapping[0]))
    protein_of = {row["marker_accession_id"]: row["string_id"] for row in mapping if row["string_id"]}
    log(f"mapped {len(protein_of)}/{len(symbols)} genes")

    universe = impc_tested_genes()
    universe_mapping = map_genes(universe)
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
    try:
        client = McpClient(MCP_URL)
        if MCP_TOOL not in {tool["name"] for tool in client.list_tools()}:
            raise RuntimeError(f"{MCP_TOOL} not listed by server")
    except (RuntimeError, OSError, ValueError, KeyError, IndexError) as e:
        client, mcp_error = None, str(e)
        log(f"STRING MCP unavailable, using REST: {e}")

    rows: list[dict] = []
    errors: list[str] = [mcp_error] if mcp_error else []
    for name, label, set_type, genes in gene_sets:
        proteins = sorted({protein_of[g] for g in genes if g in protein_of})
        common = (name, label, set_type, len(genes), len(proteins))
        if len(proteins) < MIN_PROTEINS:
            status = (f"not tested: fewer than {MIN_PROTEINS} mapped proteins; "
                      "STRING would test its own neighbours instead")
            log(f"{name}: {status}")
            for bg in ("proteome", "impc_tested"):
                rows.append(result_row(*common, bg, "", score, None, status))
            continue
        try:
            result, source, warning = proteome_run(client, proteins, score)
            errors += [f"{name}: {warning}"] if warning else []
            rows.append(result_row(*common, "proteome", source, score, result, "worked"))
        except RuntimeError as e:
            errors.append(f"{name} proteome: {e}")
            rows.append(result_row(*common, "proteome", "", score, None, f"failed: {e}"))
        try:
            result = background_run(proteins, background, score)
            rows.append(result_row(*common, "impc_tested", "rest", score, result, "worked"))
        except RuntimeError as e:
            errors.append(f"{name} impc_tested: {e}")
            rows.append(result_row(*common, "impc_tested", "rest", score, None, f"failed: {e}"))
        log(f"{name}: {len(proteins)} proteins done")

    fields = ["gene_set", "gene_set_label", "set_type", "background", "source", "required_score",
              "genes_in_set", "proteins_mapped", *RESULT_FIELDS, "status"]
    write_csv(args.out_dir / "04_ppi_enrichment.csv", rows, fields)

    try:
        version = string_post("version", {})[0]
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
        "errors": errors,
    }, indent=2) + "\n")
    log(f"wrote {len(rows)} result rows to {args.out_dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
