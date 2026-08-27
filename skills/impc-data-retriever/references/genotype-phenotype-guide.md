In the genotype-phenotype core:

1. Fields
Genotype-phenotype summaries (`genotype-phenotype`):

```python
fl = "marker_symbol,marker_accession_id,allele_symbol,allele_accession_id,colony_id,mp_term_id,mp_term_name,top_level_mp_term_name,procedure_name,procedure_stable_id,parameter_name,parameter_stable_id,p_value,effect_size,percentage_change,statistical_method,sex,zygosity,life_stage_name,phenotyping_center,pipeline_stable_id"
```

2. Core-specific rules:

3. Query patterns:
Gene to phenotypes:

```python
num_found, df = solr_request(
    core="genotype-phenotype",
    params={
        "q": "marker_symbol:Brca2",
        "rows": 100,
        "fl": "marker_symbol,allele_symbol,mp_term_name,top_level_mp_term_name,p_value,zygosity,sex",
        "sort": "p_value asc",
    },
    validate=True,
)
```

Phenotype or MP term to genes:

```python
num_found, df = solr_request(
    core="genotype-phenotype",
    params={
        "q": 'mp_term_name:"abnormal bone mineral density"',
        "rows": 50,
        "fl": "marker_symbol,allele_symbol,mp_term_id,mp_term_name,p_value,zygosity",
        "sort": "p_value asc",
    },
    validate=True,
)
```


Multiple genes, alleles, parameters or colonies:

```python
df = batch_solr_request(
    core="genotype-phenotype",
    params={
        "q": "*:*",
        "fl": "marker_symbol,mp_term_name,p_value,zygosity",
        "field_list": ["Brca2", "Trp53", "Pten"],
        "field_type": "marker_symbol",
    },
)
```
