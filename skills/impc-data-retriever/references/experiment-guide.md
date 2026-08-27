In the experiment core:

1. Fields
Raw observations (`experiment`):

```python
fl = "experiment_id,specimen_id,observation_id,biological_sample_group,pipeline_stable_id,procedure_stable_id,procedure_name,phenotyping_center,production_center,external_sample_id,strain_name,sex,zygosity,date_of_birth,date_of_experiment,age_in_weeks,life_stage_name,gene_symbol,allele_symbol,allele_accession_id,colony_id,parameter_stable_id,parameter_name,data_point,observation_type,metadata_group,metadata,weight,weight_date,weight_days_old,weight_parameter_stable_id"
```

2. Core-specific rules:

3. Query patterns:

Raw observations by procedure, parameter, centre, colony or sample group:

```python
df = batch_solr_request(
    core="experiment",
    params={
        "q": 'procedure_stable_id:*OFD* AND life_stage_name:"Late adult" AND biological_sample_group:experimental',
        "fl": "observation_id,specimen_id,gene_symbol,allele_symbol,colony_id,sex,zygosity,phenotyping_center,parameter_stable_id,parameter_name,data_point,metadata,weight,life_stage_name",
    },
    batch_size=10000,
)
```

Controls for the same assay:

```python
df = batch_solr_request(
    core="experiment",
    params={
        "q": 'procedure_stable_id:*OFD* AND biological_sample_group:control',
        "fl": "observation_id,specimen_id,sex,zygosity,phenotyping_center,parameter_stable_id,parameter_name,data_point,metadata,weight,life_stage_name",
    },
    batch_size=10000,
)
```

Query by confirmed triplets:

```python
triplet_clauses = [
    '(pipeline_stable_id:"IMPC_001" AND procedure_stable_id:"IMPC_BWT_001" AND parameter_stable_id:"IMPC_BWT_001_001")',
    '(pipeline_stable_id:"HMGU_001" AND procedure_stable_id:"HMGU_BWT_001" AND parameter_stable_id:"HMGU_BWT_001_001")',
]

df = batch_solr_request(
    core="experiment",
    params={
        "q": "(" + " OR ".join(triplet_clauses) + ") AND biological_sample_group:experimental",
        "fl": "pipeline_stable_id,procedure_stable_id,parameter_stable_id,parameter_name,observation_id,specimen_id,gene_symbol,allele_symbol,sex,zygosity,data_point,life_stage_name",
    },
    batch_size=10000,
)
```

Facets for discovery:

```python
num_found, df = solr_request(
    core="experiment",
    params={
        "q": 'procedure_stable_id:*OFD* AND life_stage_name:"Late adult"',
        "rows": 0,
        "facet": "on",
        "facet.field": "phenotyping_center",
        "facet.limit": 50,
        "facet.mincount": 1,
    },
    silent=True,
)
```