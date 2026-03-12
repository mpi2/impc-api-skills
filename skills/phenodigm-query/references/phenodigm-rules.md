When querying the phenodigm core:
1. ALWAYS include a type filter in "q". Never query phenodigm without a type.
           Valid types and when to use them:
               - type:disease_model_summary  → gene-disease associations
               - type:disease                → disease records
               - type:gene                  → gene records
               - type:gene_gene             → human-mouse gene mapping
               - type:ontology_ontology     → HPO-MP ontology mapping
               - type:ontology              → ontology records
               - type:mouse_model           → mouse model recrods
               - 
           Example: {"q": "type:disease_model_summary AND marker_symbol:Pparg"}

2. PHENODIGM SCORE: Never store or return raw score fields directly.
    Always calculate the phenodigm score using and include it as a field:
        phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)
    This expression can be used as a field alias or in a "sort" param.
    Example sort: "sort": "div(sum(disease_model_avg_norm,disease_model_max_norm),2) desc"

3. INTERPRETATION: When asked about interpretation, include following fields in the query: disease_matched_phenotypes and model_matched_phenotypes and follow [the phenodigm-score-interpretation guidelines](phenodigm-score-interpretation.md)


Example call:
        core="phenodigm"
        params={
            "q": "type:disease_model_summary AND marker_symbol:Pparg,
            "rows": 10,
            "fl": "marker_symbol,disease_term,association_curated,phenodigm_score:div(sum(disease_model_avg_norm,disease_model_max_norm),2)",
            "sort": "div(sum(disease_model_avg_norm,disease_model_max_norm),2) desc"
        }