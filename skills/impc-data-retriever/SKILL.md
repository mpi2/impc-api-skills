---
name: impc-data-retriever
description: "You MUST use this when the user requests data retrieval from the IMPC."
---

# IMPC Data Retrieval
## Purpose

Retrieve data from the International Mouse Phenotyping Consortium (IMPC) using the impc-api Python package.

This skill translates a user's request into the appropriate impc-api function calls and returns the requested data in a convenient format.

## When to use

Use this skill whenever a user wants to download or analyse IMPC data, for example:

- phenotype data
- statistical results
- genotype-phenotype associations
- genes
- alleles
- procedures
- parameters
- experiments
- ontology annotations
- disease models

Typical requests include:

- "Download Open Field data."
- "Get all phenotypes for Pax6."
- "Retrieve all significant genotype-phenotype associations."
- "Download IMPC data for procedure IMPC_OFD_001."
- "Get all parameters from the Clinical Chemistry pipeline."
- "Export results as a pandas DataFrame."

## Input

Accept natural language describing the required data.

If essential information is missing, ask concise follow-up questions.

Examples:

- Which gene?
- Which procedure?
- Which parameter?
- Which release?
- Do you want raw observations or statistical results?
- Should the data be returned as a DataFrame, CSV or Parquet?

## Behaviour
1. Determine what IMPC entity the user is requesting.

Possible entities include:
- genes
- phenotypes
- procedures
- parameters
- observations
- statistical results
- ontology terms
- disease models

2. Identify any filters such as:
- gene
- allele
- strain
- procedure
- parameter
- phenotype
- sex
- zygosity
- pipeline
- centre

3. Select the most appropriate impc-api function.
4. Download the data.
5. Return the result in the format requested by the user.

## Output

Prefer returning a pandas DataFrame.

If requested, save the results as:

- CSV
- Parquet
- JSON
- Excel

Large datasets should be streamed or downloaded in chunks where supported.

## Examples
Example 1

User

Download Open Field data.

The skill should determine that the user wants observations or statistical results for the Open Field procedure and retrieve them using the appropriate impc-api function.

Example 2

User

Get all data for Trp53.

The skill should retrieve all available datasets related to the Trp53 gene.

Example 3

User

Download all significant genotype–phenotype associations.

The skill should retrieve only statistically significant associations.

Example 4

User

Export Clinical Chemistry parameters as CSV.

The skill should retrieve the parameter metadata and save it as a CSV file.

## Guidelines
- Prefer the highest-level impc-api function rather than manually constructing API URLs.
- Use filtering within the package whenever available.
- Download only the data requested.
- Preserve original IMPC identifiers.
- Return informative error messages if no matching data are found.
- If multiple datasets match the request, explain the options and ask the user to choose.
- For very large downloads, warn the user that retrieval may take some time.

## Error handling
If the request is ambiguous:

- identify the ambiguity;
- ask only the minimum number of clarification questions needed to retrieve the correct data.

If no data exist:

- explain that no matching IMPC data were found;
- suggest nearby entities if appropriate.

## Notes
- Always use the installed impc-api package rather than calling IMPC REST endpoints directly, unless the package does not support the requested functionality.
- Preserve IMPC stable identifiers exactly as returned by the API.
- Do not modify or infer biological annotations beyond what is provided by IMPC.
- When possible, return data as a pandas DataFrame to facilitate downstream analysis.
