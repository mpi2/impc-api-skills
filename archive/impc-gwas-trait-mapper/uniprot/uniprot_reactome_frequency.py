#!/usr/bin/env python3
"""Reactome pathway frequency for a set of mouse genes, from UniProt Reactome cross-references (draft).

EXPERIMENTAL (step 2c, gene sets only): suggested from outside the project and kept so its output can be
judged on a real run; output columns and the chart may change; not covered by evals.

Gene set: the `is_primary` (reviewed) accessions in 02_uniprot_accessions.csv. Background: every reviewed
mouse UniProt entry with a Reactome link, downloaded once with the UniProt stream endpoint and cached
(--background). Mouse Reactome pathways are Reactome's human pathways inferred by orthology.

Per pathway: k = set genes in it, K = background genes in it, n = set genes with any Reactome link,
N = background genes. p = P(X >= k) for X ~ Hypergeometric(N, K, n); FDR = Benjamini-Hochberg over the
pathways with k >= 1. Counted per MGI gene, so a gene with several accessions counts once.

--out: one row per pathway with k >= 1, sorted by k then p.
--png (needs matplotlib: run with `uv run --with matplotlib`): two panels, the top pathways by k and by
p, with the count expected by chance marked on each bar.

Example:
  uv run --with matplotlib skills/impc-gwas-trait-mapper/scripts/uniprot_reactome_frequency.py \
    --accessions 02_uniprot_accessions.csv --background 02_uniprot_mouse_reactome_background.json \
    --out 02_uniprot_reactome_frequency.csv --png 02_uniprot_reactome_frequency.png --title "MP:0005178 genes"
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

STREAM = ("https://rest.uniprot.org/uniprotkb/stream?query=organism_id:10090%20AND%20reviewed:true%20AND%20"
          "database:reactome&fields=accession,xref_mgi,xref_reactome&format=json")
FIELDS = ["pathway_id", "pathway_name", "k_genes_in_set", "K_pathway_genes", "n_set_annotated", "N_background",
          "expected", "fold", "p_value", "fdr", "genes"]


def download(path: str, retries: int = 4) -> None:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(STREAM, timeout=300) as r, open(path, "wb") as f:
                f.write(r.read())
            return
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def upper_tail(k: int, K: int, n: int, N: int) -> float:
    return sum(math.comb(K, i) * math.comb(N - K, n - i) for i in range(k, min(K, n) + 1)) / math.comb(N, n)


def plot(rows: list[dict], path: str, title: str, n: int, N: int, n_set: int, top: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    ink, ink2, muted, grid, surface, sig = "#0b0b0b", "#52514e", "#b9b8b2", "#e6e5e0", "#fcfcfb", "#2a78d6"
    by_k = sorted(rows, key=lambda r: (-r["k_genes_in_set"], r["p_value"]))[:top]
    by_p = sorted(rows, key=lambda r: r["p_value"])[:top]
    fig, axes = plt.subplots(1, 2, figsize=(15, 1.6 + 0.37 * top), facecolor=surface, sharex=True)
    xmax = max(r["k_genes_in_set"] for r in rows) + 2.2
    for ax, data, sub in [(axes[0], by_k, "A. Most frequent: sorted by genes in set"),
                          (axes[1], by_p, "B. Most enriched: sorted by p-value")]:
        ax.set_facecolor(surface)
        y = list(range(len(data)))[::-1]
        ax.barh(y, [r["k_genes_in_set"] for r in data], height=0.6, edgecolor=surface, linewidth=2,
                color=[sig if r["fdr"] < 0.05 else muted for r in data])
        for yi, r in zip(y, data):
            ax.plot([r["expected"]] * 2, [yi - 0.36, yi + 0.36], color=ink, lw=1.5)
            ax.text(r["k_genes_in_set"] + 0.15, yi, f"{r['k_genes_in_set']}/{r['K_pathway_genes']}  ·  FDR {r['fdr']:.2g}",
                    va="center", fontsize=8.5, color=ink2)
        names = [r["pathway_name"] if len(r["pathway_name"]) <= 52 else r["pathway_name"][:51] + "…" for r in data]
        ax.set_yticks(y, names, fontsize=9, color=ink)
        ax.set_xlim(0, xmax)
        ax.set_title(sub, loc="left", fontsize=11, color=ink, fontweight="bold")
        ax.xaxis.grid(True, color=grid, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(grid)
        ax.tick_params(axis="x", colors=ink2, labelsize=8.5)
        ax.tick_params(axis="y", length=0)
        ax.set_xlabel("genes from the set in the pathway", fontsize=9, color=ink2)
    fig.legend(handles=[Patch(color=sig, label="FDR < 0.05"), Patch(color=muted, label="FDR ≥ 0.05"),
                        plt.Line2D([], [], color=ink, lw=1.5, label="expected by chance (n·K/N)")],
               loc="lower center", ncol=3, frameon=False, fontsize=9, labelcolor=ink2)
    fig.suptitle(f"Reactome pathways (via UniProt): {title}", x=0.01, ha="left", fontsize=12.5, color=ink,
                 fontweight="bold")
    fig.text(0.01, 1 - 0.75 / fig.get_figheight(),
             f"{n} of {n_set} genes have a reviewed mouse UniProt entry with Reactome links; background {N:,} mouse "
             f"genes. Label: genes in set / genes in pathway · Benjamini–Hochberg FDR (hypergeometric, "
             f"{len(rows)} pathways tested).", fontsize=8.5, color=ink2)
    fig.tight_layout(rect=(0, 0.6 / fig.get_figheight(), 1, 1 - 0.95 / fig.get_figheight()))
    fig.savefig(path, dpi=150, facecolor=surface)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--accessions", required=True, help="02_uniprot_accessions.csv (from uniprot_mapping.py)")
    ap.add_argument("--background", required=True, help="Cached UniProt JSON; downloaded when missing (~6 MB)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--png", help="Chart path (needs matplotlib)")
    ap.add_argument("--title", default="gene set", help="Set description for the chart title")
    ap.add_argument("--top", type=int, default=15, help="Pathways per chart panel (default 15)")
    ap.add_argument("--min-genes", type=int, default=10,
                    help="Set genes with Reactome links needed to run (default 10); with Tyk2 + Ldlr (n=2) all 20 "
                         "of their pathways came out at FDR < 0.05, which says nothing")
    args = ap.parse_args()

    if not os.path.exists(args.background):
        download(args.background)
    modified = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(args.background)))
    gene_paths, names = defaultdict(set), {}
    for e in json.load(open(args.background, encoding="utf-8"))["results"]:
        xrefs = e.get("uniProtKBCrossReferences", [])
        paths = [x for x in xrefs if x["database"] == "Reactome"]
        for mgi in (x["id"] for x in xrefs if x["database"] == "MGI"):
            for p in paths:
                gene_paths[mgi].add(p["id"])
                names[p["id"]] = next((q["value"] for q in p.get("properties", []) if q["key"] == "PathwayName"), "")
    path_genes = defaultdict(set)
    for mgi, ps in gene_paths.items():
        for p in ps:
            path_genes[p].add(mgi)

    with open(args.accessions, newline="", encoding="utf-8") as f:
        acc = list(csv.DictReader(f))
    symbol = {r["mgi_id"]: r.get("uniprot_gene") or r["mgi_id"] for r in acc if r["is_primary"] == "True"}
    n_set = len({r["mgi_id"] for r in acc})
    annotated = {m for m in symbol if m in gene_paths}
    n, N = len(annotated), len(gene_paths)
    if n < args.min_genes:
        sys.exit(f"{n} set gene(s) with Reactome links, fewer than --min-genes {args.min_genes}: not run")

    rows = []
    for p, members in path_genes.items():
        hits = members & annotated
        if hits:
            k, K = len(hits), len(members)
            rows.append({"pathway_id": p, "pathway_name": names[p], "k_genes_in_set": k, "K_pathway_genes": K,
                         "n_set_annotated": n, "N_background": N, "expected": round(n * K / N, 2),
                         "fold": round(k * N / (n * K), 2), "p_value": upper_tail(k, K, n, N),
                         "genes": "; ".join(sorted(symbol[m] for m in hits))})
    rows.sort(key=lambda r: r["p_value"])
    prev = 1.0
    for i in range(len(rows) - 1, -1, -1):
        prev = min(prev, rows[i]["p_value"] * len(rows) / (i + 1))
        rows[i]["fdr"] = prev
    rows.sort(key=lambda r: (-r["k_genes_in_set"], r["p_value"]))
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"background {args.background} (modified {modified}): {N} genes, {len(path_genes)} pathways; set: {n_set} "
          f"genes, {len(symbol)} reviewed, {n} with Reactome; {len(rows)} pathways with >= 1 set gene, "
          f"{sum(r['fdr'] < 0.05 for r in rows)} at FDR < 0.05 -> {args.out}", file=sys.stderr)
    if args.png:
        plot(rows, args.png, args.title, n, N, n_set, args.top)
        print(f"chart -> {args.png}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
