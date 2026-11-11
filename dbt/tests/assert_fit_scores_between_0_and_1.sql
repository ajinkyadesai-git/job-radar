-- Fit scores uploaded by jobradar fit-score must be probabilities.
select posting_key, fit_score
from {{ source('ml', 'fit_scores') }}
where fit_score < 0 or fit_score > 1
