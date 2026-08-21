In the `impc_images` core:

1. Fields:
Images (`impc_images`):

```python
fl = "gene_symbol,allele_symbol,allele_accession_id,colony_id,procedure_name,procedure_stable_id,parameter_name,parameter_stable_id,sex,zygosity,life_stage_name,phenotyping_center,download_url,jpeg_url,thumbnail_url,omero_id,file_type"
```

2. Core-specific rules:

3. Query patterns:

Images:

```python
num_found, df = solr_request(
    core="impc_images",
    params={
        "q": "gene_symbol:Akt2",
        "rows": 20,
        "fl": "gene_symbol,parameter_name,procedure_name,download_url,jpeg_url,thumbnail_url",
    },
    validate=True,
)
```
