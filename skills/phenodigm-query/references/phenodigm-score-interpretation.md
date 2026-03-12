
# Phenodigm Interpretations
Use the phenodigm-interpretation skills to respond to the user when they ask about the interpretation of a phenodigm score. 


## Workflow 
1. Consider the following documentation to interpret PhenoDigm scores: 

Interpretation of Phenodigm Scores

Phenodigm scores measure how well the phenotypes of a mouse model replicate those of a human disease.
A high score indicates that many disease phenotypes are captured by the model, whereas a low score suggests that several disease phenotypes are not observed in the mouse.

As a general guide:

The mean Phenodigm score for DR23 is 32.37

Scores above 40 can be considered high.
Scores close to 100 should be inspected carefully. 
Scores below 30 still provide useful insights, depending on context.
Several factors influence how to interpret Phenodigm scores. Below are general guidelines and examples to help users understand what different scores may indicate.

General Guidelines

Review both the Phenodigm Score represented in the “Similarity of phenotypes” column and the “Matching Phenotypes” column that shows the matched disease phenotypes.

Compare the Matching Phenotypes with the full set of human disease phenotypes. The Phenogrid tool can assist in visualizing and assessing these matches.

Regardless of the score, evaluate the quality and relevance of the matched phenotypes.
The usefulness of a phenotypic match depends on the user’s research goals:

Finding a model that captures a specific, high-priority phenotype of interest, even if not all disease phenotypes are represented.
Identifying a model that recapitulates a broad range of disease phenotypes.
Interpreting very high scores (above 90)

If the Phenodigm score exceeds 90 but only 1–2 phenotypes are matched, the corresponding human disease may have only a few annotated phenotypes.
In such cases, assess whether those matched phenotypes accurately represent the key features of the disease.
If the number of matched phenotypes is higher (e.g., 5+), the model likely recapitulates most of the disease’s annotated phenotypes.
However, a very high score does not always mean high relevance—check whether the matched phenotypes reflect the critical or characteristic features of the disease that are relevant to your research.
Interpreting low scores (below 30)

If the Phenodigm score is below 30 but the number of matched phenotypes is high, this may indicate that the human disease has many annotated phenotypes.
These matches can still be useful for identifying candidate models that capture specific disease features.
If both the score and the number of matched phenotypes are low (e.g., 1–2), this usually reflects a poor phenotypic match.
Even for low-scoring models, a few strong and biologically relevant matches may still make the model valuable—particularly if those phenotypes align closely with the user’s research priorities.

2. Retrieve the model matching phenotypes and disease matching phenotypes to inform your interpretation. Present them to the user.

3. From the PhenoDigm score information retreived before this query, provide a consice interpretation based on the documentation above. 
It should include if it is a good score, normal or bad score and a short justification. 

