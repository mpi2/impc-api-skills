#!/usr/bin/env python3
"""Plot the Reactome pathways from reactome_pathways.py: no enrichment, no p-values, only counts.

EXPERIMENTAL (step 2c): the chart may change; not covered by evals yet.

One annotated gene: one bar per lowest-level pathway, the share of the pathway's reactions that involve
the gene (labelled found/total), in the gene's rank order.
Several genes: one bar per lowest-level pathway, the number of genes in it, top --top pathways. With
--counts-out the full per-pathway table (genes listed) is written too.
Bar colour is the pathway's Reactome top-level category (Disease sub-branches folded into "Disease");
the seven most frequent categories on the chart get a colour, the rest are grey "Other".

Needs matplotlib:
  uv run --with matplotlib skills/impc-gwas-trait-mapper/scripts/reactome_plot.py \
    --pathways 02_reactome_pathways.csv --png 02_reactome_pathways.png --counts-out 02_reactome_pathway_gene_counts.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict

# Categorical slots 1-7 of the dataviz reference palette (validated, light mode); "Other" is neutral.
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
OTHER = "#a3a29c"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
COUNT_FIELDS = ["stable_id", "pathway_name", "top_level_category", "n_genes", "genes", "reactome_url"]


def category(raw: str) -> str:
    first = (raw or "").split("; ")[0]
    return "Disease" if first.startswith("Disease") else (first or "Uncategorised")


def shorten(name: str, n: int = 60) -> str:
    return name if len(name) <= n else name[: n - 1].rstrip() + "…"


def colours(cats: list[str], values: list[float]) -> dict[str, str]:
    """Colour the seven categories with the most weight on the chart (sum of bar values), grey the rest."""
    weight: Counter = Counter()
    for c, v in zip(cats, values):
        weight[c] += v
    order = [c for c, _ in sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {c: (SLOTS[i] if i < len(SLOTS) else OTHER) for i, c in enumerate(order)}


def draw(labels, values, texts, cats, title, xlabel, png, xmax=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    cmap = colours(cats, values)
    n = len(labels)
    fig, ax = plt.subplots(figsize=(10, 0.34 * max(n, 4) + 1.9), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    y = [max(n, 4) - 1 - i for i in range(n)]
    ax.barh(y, values, height=0.72, color=[cmap[c] for c in cats], edgecolor=SURFACE, linewidth=1.5, zorder=2)
    top = xmax or max(values)
    for yi, v, t in zip(y, values, texts):
        ax.text(v + top * 0.01, yi, t, va="center", ha="left", fontsize=9, color=INK)
    ax.set_yticks(y, [shorten(l) for l in labels], fontsize=9, color=INK)
    ax.set_xlim(0, top * 1.12)
    ax.set_ylim(-0.6, max(n, 4) - 0.4)  # few bars: keep bar thickness, leave the space below empty
    ax.set_xlabel(xlabel, fontsize=9, color=INK2)
    if all(isinstance(v, int) for v in values):
        from matplotlib.ticker import MaxNLocator
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.tick_params(axis="x", colors=INK2, labelsize=8, length=0)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    fig.suptitle(title, x=0.01, ha="left", fontsize=11, color=INK)
    legend, seen = [], set()
    for c in sorted(cmap, key=lambda c: (cmap[c] == OTHER, SLOTS.index(cmap[c]) if cmap[c] != OTHER else 0)):
        key = "Other" if cmap[c] == OTHER else c
        if key not in seen:
            seen.add(key)
            legend.append(Patch(facecolor=cmap[c], label=key))
    ax.legend(handles=legend, title="Reactome top-level category", fontsize=8, title_fontsize=8,
              loc="lower right", frameon=False, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(png, dpi=150, facecolor=SURFACE)
    print(f"wrote {png}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pathways", required=True, help="CSV from reactome_pathways.py")
    ap.add_argument("--png", required=True)
    ap.add_argument("--counts-out", help="Several genes: per-pathway gene counts, every pathway")
    ap.add_argument("--top", type=int, help="Bars to show (default 30 for one gene, 20 for several)")
    ap.add_argument("--title", help="Replaces the generated title")
    args = ap.parse_args()

    with open(args.pathways, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    all_genes = {r["hgnc_id"] for r in rows}
    hits = [r for r in rows if r.get("stable_id")]
    genes = {r["hgnc_id"] for r in hits}
    release = next((r["reactome_release"] for r in rows if r.get("reactome_release")), "?")
    if not genes:
        print("no gene has Reactome pathways; nothing to plot", file=sys.stderr)
        return 0

    if len(genes) == 1:
        hits.sort(key=lambda r: int(r["rank"]))
        top = args.top or 30
        shown = hits[:top]
        sym = shown[0]["human_symbol"] or shown[0]["hgnc_id"]
        scope = f"top {len(shown)} of {len(hits)}" if len(hits) > len(shown) else f"{len(hits)}"
        noun = "pathway" if len(hits) == 1 else "pathways"
        title = args.title or f"{sym}: {scope} Reactome {noun} (lowest level), release {release}"
        draw([r["pathway_name"] for r in shown], [float(r["reaction_coverage"] or 0) for r in shown],
             [f"{r['reactions_with_gene']}/{r['reactions_total']}" for r in shown],
             [category(r["top_level_category"]) for r in shown], title,
             "Share of the pathway's reactions that involve the gene", args.png, xmax=1.0)
        return 0

    by_pw: dict[str, dict] = {}
    members: dict[str, set[str]] = defaultdict(set)
    for r in hits:
        by_pw.setdefault(r["stable_id"], r)
        members[r["stable_id"]].add(r["human_symbol"] or r["hgnc_id"])
    counted = sorted(by_pw, key=lambda s: (-len(members[s]), by_pw[s]["pathway_name"]))
    if args.counts_out:
        with open(args.counts_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COUNT_FIELDS)
            w.writeheader()
            for s in counted:
                p = by_pw[s]
                w.writerow({"stable_id": s, "pathway_name": p["pathway_name"], "top_level_category": p["top_level_category"],
                            "n_genes": len(members[s]), "genes": ";".join(sorted(members[s])), "reactome_url": p["reactome_url"]})
        print(f"wrote {len(counted)} pathways -> {args.counts_out}", file=sys.stderr)
    shown = counted[: args.top or 20]
    tie = ""
    if len(counted) > len(shown):
        last = len(members[shown[-1]])
        if len(members[counted[len(shown)]]) == last:
            # the cut falls inside a tie: say how many tied pathways are left out instead of hiding it
            left = sum(len(members[s]) == last for s in counted[len(shown):])
            tie = f"; {left} more with {last} genes not shown (alphabetical cut)"
    title = args.title or (f"Genes per Reactome pathway (lowest level): top {len(shown)} of {len(counted)} pathways{tie}\n"
                           f"{len(genes)} of {len(all_genes)} genes have pathways, release {release}")
    draw([by_pw[s]["pathway_name"] for s in shown], [len(members[s]) for s in shown],
         [str(len(members[s])) for s in shown], [category(by_pw[s]["top_level_category"]) for s in shown],
         title, "Genes in the pathway", args.png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
