In the `phenodigm` core:

1. Fields:
Disease models (`phenodigm`):

```python
fl = "disease_id,disease_source,disease_term,gene_symbol,hgnc_gene_symbol,marker_symbol,mouse_model,model_id,model_source,model_description,impc_model,mp_id,mp_term,hp_id,hp_term,disease_model_avg_norm,disease_model_max_norm,association_curated,association_ortholog"
```


2. Core-specific rules:

3. Query patterns:

Disease models:

```python
num_found, df = solr_request(
    core="phenodigm",
    params={
        "q": 'type:disease_model_summary AND disease_term:"Usher syndrome"',
        "rows": 50,
        "fl": "disease_id,disease_term,gene_symbol,marker_symbol,mouse_model,mp_term,disease_model_avg_norm,disease_model_max_norm",
    },
    validate=True,
)
```
