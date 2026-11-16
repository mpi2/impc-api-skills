# impc-human-evidence-explorer architecture

```mermaid
flowchart LR
    Q[/"Query: matching trait–phenotypes for gene X"/]

    subgraph Skill["impc-human-evidence-explorer"]
        direction LR
        subgraph P1["1. Get IMPC gene phenotypes"]
            direction TB
            S1["IMPC genotype–phenotype data<br/><i>MP terms, p-values, effect size</i>"]
            R1[impc-data-retriever skill]
            S1 ~~~ R1
        end
        subgraph P2["2. Get human orthologs"]
            direction TB
            S2["Human one-to-one ortholog<br/><i>MGI → HGNC</i>"]
            R2["impc-orthology MCP*<br/>scripts/orthologs.py"]
            S2 ~~~ R2
        end
        subgraph P2b["2b. Tissue expression context"]
            direction TB
            S2b["HPA tissue specificity per human gene<br/><i>category, tau, enriched + top tissues (nTPM)</i>"]
            R2b["Human Protein Atlas API<br/>scripts/hpa_tissue_expression.py"]
            S2b ~~~ R2b
        end
        subgraph P2c["2c. Reactome pathways"]
            direction TB
            S2c["Lowest-level pathways per human ortholog<br/><i>HGNC → reviewed UniProt accession → Reactome; reactions with gene / total, pathway size</i>"]
            R2c["UniProt REST + Reactome REST<br/>scripts/reactome_pathways.py"]
            S2c ~~~ R2c
        end
        subgraph P3["3–4. Find candidate gene-trait with OT"]
            direction TB
            S3["L2G causal gene → credible sets → GWAS studies → study traits<br/><i>L2G score, lead allele, lead-variant β, EFO/MONDO/HP/OBA ids from the OT study index</i>"]
            R3["Open Targets MCP*<br/>scripts/ot_gene_to_gwas.py"]
            S3 ~~~ R3
        end
        subgraph P5["5. Get trait-phenotype similarity"]
            direction TB
            S5["Phenotype–trait similarity<br/><i>MP × EFO/MONDO/HP/OBA cosine, model stated</i>"]
            R5["OLS MCP*<br/>scripts/ols_similarity.py"]
            S5 ~~~ R5
        end
        subgraph P6["6. Join and rank"]
            direction TB
            S6["IMPC call × own gene's credible sets × study traits × similarity<br/><i>main: gene × MP term × trait, best credible set by L2G; detail: unfiltered</i>"]
            R6["local<br/>scripts/join_gene_trait.py"]
            S6 ~~~ R6
        end
        P1 --> P2 --> P3 --> P5 --> P6
        P2 -.-> P2b
        P2 -.-> P2c
    end

    OUT[("06_impc_gene_to_gwas_trait.csv<br/>02_hpa_tissue_expression.csv<br/>02_reactome_pathways.csv<br/>README.md")]

    Q --> Skill --> OUT

    classDef source fill:#dc8cbb,stroke:#a0527c,color:#1a1a1a
    classDef skill fill:#8ecdf0,stroke:#0072b2,color:#1a1a1a
    classDef step fill:#ffffff,stroke:#525252,color:#1a1a1a
    classDef output fill:#5cc4a3,stroke:#00664a,color:#1a1a1a
    classDef input fill:#e5e5e5,stroke:#737373,color:#1a1a1a
    classDef group fill:none,stroke:#94a3b8
    class Q input
    class S1,S2,S2b,S2c,S3,S5,S6 step
    class R1,R2,R2b,R2c,R3,R5,R6 source
    class OUT output
    class Skill,P1,P2,P2b,P2c,P3,P5,P6 group
```

\* Script listed under the MCP is a fallback; the skill uses whichever is available.

## Current drawbacks
- Reminder: These matches have not undergone statistical testing