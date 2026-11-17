# Automatic saved-evidence reference retrieval

Preparation against frozen source `5cee22cd32cf917e25861248d80feeab39edbf22`.
This change is not packaged, deployed or accepted on Windows.

## Scope

GET `/api/patients/{id}/reference-matches` retrieves passages from the privately registered local Brainstorm PDF. It is independent of the existing past-case Suggestions endpoint. A missing past-case corpus stays unavailable; a PDF is not a substitute case corpus.

The Interview and report editor show automatic reading prompts after loading saved evidence. Interview edits and unsaved pathology invalidate the panel. A successful interview save refreshes the matches. Each original-page request rechecks current saved evidence, edition and exact PDF hash before using the existing sandboxed local viewer.

Nothing is inserted into an interview or report. No patient finding, recommendation, diagnosis, severity, laboratory threshold, synonym, clinical expiry or clinical currency is inferred. A match to negated or historical wording is still only a text match. The pharmacist must read the original evidence and source, assess relevance and cross-check current clinical references.

## Retrieval contract

- Uses the existing source-linked evidence context and its SHA-256 fingerprint. Preserves original evidence text, ID, source, dates, age, flags, units, reference interval, verification attribution and comment.
- Accepts saved notes, concerns, observations, conditions, mobility and interview detail. Structured pathology must already have named pharmacist verification with audit fields. Future-dated and superseded/ineligible rows, unverified/legacy pathology, medicines and eMIMS text do not drive matches.
- Uses literal heading phrases between adjacent significant heading words, retaining intervening grammatical words. A genuinely single-word heading needs at least four characters. Case and punctuation are normalized for text matching; no clinical vocabulary expansion is used. This intentionally misses synonyms and headings that are not repeated in the evidence.
- Requires the matching phrase in a body-page fragment. Quotes are bounded to one physical PDF page, with omitted-text markers, exact PDF hash, edition, heading page and section-page range. The quote and heading are checked against the original PDF, not merely a cached extraction.
- Rechecks original bytes and registration after retrieval, and saved evidence before returning the patient endpoint response. Changed/unavailable inputs fail closed. The existing viewer independently checks hash and page when opening.
- Checks at most 200 eligible rows and shows at most 20 passages. Reports eligible/processed rows, total matches and truncation explicitly. Ordering follows source section/evidence order, not clinical priority. No-match and unavailable are distinct, and neither means review complete.
- Existing local registration/cache storage rules are unchanged. This is not an all-data-encryption claim. No PDF bytes, patient data or licensed text are included in this source change.

## Verification completed locally

- Selected backend suite: 231 passed, one Windows-only skip. Existing suggestion self-check passed.
- Desktop suite: 300 passed, including saved-only/dirty blocking, correct patient routing, late responses/errors, changed context/reference refusal, escaping and no Insert control.
- Eleven new backend regressions cover original negation/history, physical-page continuation/repeated headings, original units/dates, excluded evidence, no synonym/threshold inference, changed bytes/context/registration, explicit truncation and the production route without a case corpus.
- Synthetic production-route data rendered at 1280 and 1440. The 1280 report-sidebar layout was also inspected. Quote, source, physical page, missing-date warning, hash wrapping and review-only wording were readable without horizontal overflow. The viewer request was a stub checked for the exact synthetic hash and physical page 2. This is Chromium fixture evidence, not packaged Windows acceptance.
- Local backend tests use a fail-if-used Windows-lock shim on Linux; the one Windows-only behavior is not claimed tested here. Native CI has not run for this preparation.

## Next acceptance

Review the separate patch, then run native CI before any package cycle. Exercise the normal packaged Interview save/dirty/pathology-verification flow, report sidebar, changed-reference failure and original physical-page viewer on synthetic data. Do not use actual patient data or redistribute the supplied private PDF.

Keep the medicine contract gap open: OCR-selected identity -> interview -> explicit medicine confirmation -> existing eMIMS queue payload -> report medicine table still needs an end-to-end synthetic contract. Legitimate interaction completion and normal report/Add gating remain unverified where the packaged eMIMS helper is absent. Do not bypass the gate or invent an interaction result.
