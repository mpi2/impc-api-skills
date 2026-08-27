In the `statistical-result` core:

1. Fields:
Statistical results (`statistical-result`):

```python
fl = "marker_symbol,allele_symbol,allele_accession_id,colony_id,procedure_name,procedure_stable_id,parameter_name,parameter_stable_id,statistical_method,significant,p_value,effect_size,mp_term_id,mp_term_name,mp_term_id_options,top_level_mp_term_name,sex,zygosity,phenotype_sex,life_stage_name,phenotyping_center,pipeline_stable_id,male_ko_effect_p_value,female_ko_effect_p_value,genotype_effect_p_value,weight_effect_p_value,weight_effect_parameter_estimate,male_mutant_count,female_mutant_count,male_control_count,female_control_count"
```

2. Core-specific rules:

3. Query patterns:

Significant statistical results:

```python
num_found, df = solr_request(
    core="statistical-result",
    params={
        "q": "marker_symbol:Dclk1 AND significant:true",
        "rows": 100,
        "fl": "marker_symbol,parameter_name,procedure_name,top_level_mp_term_name,effect_size,p_value,zygosity,statistical_method",
        "sort": "p_value asc",
    },
    validate=True,
)
```


MP ontology-linked statistical results:

```python
df = batch_solr_request(
    core="statistical-result",
    params={
        "q": 'mp_term_id_options:"MP:0004738" OR mp_term_id_options:"MP:0011967"',
        "fl": "marker_symbol,allele_symbol,colony_id,mp_term_id_options,parameter_stable_id,significant,p_value,pipeline_stable_id",
    },
)
```
