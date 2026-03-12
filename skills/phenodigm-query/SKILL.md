
---
name: phenodigm-query
description: Queries the IMPC API using the `impc_api` python package. Use when a user asks to query a gene, disease, phenotype, allele. 
--- 

# PHENODIGM QUERY

> EXECUTION ENVIRONMENT — READ FIRST
> All code must be executed using `uv`.
> Do NOT use any other execution method under any circumstances.
> A uv environment at `/.venv` has all dependencies pre-installed.

## Context
The IMPC Solr API should be queried only with `impc_api` python package. It contains cores and fields to query.

## Workflow

1. Find the existing cores and available fields per core:
    ``` uv run - <<EOF
    import httpx
    import json
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://raw.githubusercontent.com/mpi2/impc-api/refs/heads/main/impc_api/utils/core_fields.json")
            response.raise_for_status()
            return response.json()
    except Exception:
        return None
    EOF
    ```

2. Use the available cores and fields to craft a query as follows where both core and params are needed.

REQUIRED ARGUMENTS:
    To run the `impc-api` request package, you need to figure out:
    core (str): The Solr core to query.
    params (dict): Query parameters. Must include at minimum:
        - "q": query string. Use "*:*" for all records, or "field:value" 
               for specific matches. Example: "marker_symbol:Pparg"
        - "rows": number of results to return (int). Default to 10 unless 
                  the user specifies otherwise.
        - "fl": comma-separated string of fields to return. 
                Example: "marker_symbol,marker_name,marker_description"

CORE-SPECIFIC RULES and EXAMPLE CALLS:
    Follow rules according to the requested solr core
    genotype-phenotype:
    experiment: 
    impc_images:
    phenodigm: [phenodigm](./impc-api-query/references/phenodigm-rules.md)
    gene:
    mp:
    pipleine:
    product:
    statistical-result:

3. With the available cores and fields obtained previously, and with the core and params that you have gathered use the rules and example calls to execute the call. Always double-check you are using valid cores and fields from step 1. 

RUNNING A QUERY:    
``` uv run - <<EOF
    from impc_api import solr_request
    numFound, df = solr_request(core, params, silent=True)
    return df.to_dict(orient="records")
    EOF
```

4. Using `numFound` you can determine if no data was found. If no data is found, tell the user no data was found and STOP. Prompt the user to double check the request you crafted. 

5. Show the user the request URL, you can obtain it via:
``` uv run - <<EOF
    from impc_api import solr_request
    url, _ = solr_request(core, params, url_only=True)
    return url
    EOF
```

    
           
