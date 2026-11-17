# Automatic saved-evidence reference retrieval

Structured-table revision based on source `39100097bcc62ab4b6cf0fcb1462b4bb6395f457`.
Frozen `5cee22c` packaged Windows evidence covers manual search only, not this change.
No normal-app deployment or clinical acceptance is claimed.

## Scope and source

GET `/api/patients/{id}/reference-matches` retrieves passages from the privately registered original Brainstorm PDF. It is independent of the existing past-case Suggestions endpoint. A missing case corpus remains unavailable; the PDF is not a substitute case corpus.

The Interview and report editor show automatic reading prompts from saved evidence. Interview edits and unsaved pathology invalidate the panel; a successful interview save refreshes it. Each original-page request rechecks current saved evidence, source edition and exact PDF hash before using the existing sandboxed viewer.

Nothing is inserted into an interview or report. No patient finding, recommendation, diagnosis, severity, laboratory threshold, synonym, clinical expiry or clinical currency is inferred. A match to negated or historical wording is still only a text match. The pharmacist must read the original evidence/source, assess relevance and cross-check current references.

## Structured local tables

The old reference parser cached sections and page fragments as JSON. The retrieval path now builds an indexed SQLite database in the private application data directory, named by exact source hash. Tables are:

- `source`: exact PDF hash, user-reviewed edition, schema/parser versions and row counts.
- `sections`: original heading and physical start/end pages, with separate IDs for repeated headings.
- `fragments`: section ID, exact physical page and original extracted body text.
- `anchors`: section ID and literal heading phrase, with an index on its first word.

The PDF remains in its selected location and is never replaced or modified. These tables are a rebuildable search index, not clinical rules. An index is reused only for the same hash/edition/schema/parser and complete row counts. Invalid databases rebuild locally; missing originals and changed hashes still fail closed. Index creation is atomic. SQLite requires no added service or extension. Old source-hash indexes are retained rather than silently deleting local material.

The index is a separate ordinary SQLite file, not the encrypted clinical record database. It contains private reference text, no patient evidence. This does not add an encryption claim: the existing reference JSON cache/registry and original PDF storage rules are unchanged. The JSON parser cache remains an intermediate for the existing manual search path; automatic retrieval queries indexed tables. No actual PDF, extracted text or derived database is committed, bundled, uploaded to CI or redistributed.

This chooses database tables for scale, not a spreadsheet deliverable. It preserves source structure rather than flattening the guide into unverified clinical rules. Parser heading detection is heuristic, and pharmacist review remains necessary.

## Retrieval contract

- Uses the existing source-linked evidence context and SHA-256 fingerprint. Keeps original text, ID, source, dates, age, flags, units, reference interval, verification attribution and comment.
- Saved notes, concerns, observations, conditions, mobility and interview detail are eligible. Structured pathology needs named pharmacist verification and audit fields. Future-dated/superseded rows, unverified/legacy pathology, medicines and eMIMS text do not drive matches.
- Queries indexed heading phrases, then checks the entire literal token sequence. Phrases retain intervening grammatical words. A single-word heading needs at least four characters. Case/punctuation normalization is used, but no clinical vocabulary expansion. Synonyms and other wording can be missed.
- If heading words also occur in body text, retrieves that body passage. Otherwise retrieves the opening passage and labels it explicitly: heading matched, not a claim those words occur in the quote. Requiring title repetition in body text had excluded most sections in the actual supplied source and was corrected.
- Every quote is bounded to one physical page with omitted-text markers, exact PDF hash, edition, heading page and section-page range. Quote and heading are checked against original pages, not merely the index. Returned matches also revalidate heading terms against original evidence.
- Rechecks original bytes/registration and saved evidence before returning. Changed or unavailable inputs fail closed. The viewer independently checks hash/page.
- At most 200 eligible rows and 20 shown passages; total/processed counts and truncation are explicit. Order is source section/evidence order, not clinical priority. No-match and unavailable are distinct; neither means review complete.

## Actual supplied source validation, private only

The actual 207-page supplied PDF was registered in an isolated local test with synthetic saved evidence, not real patient records. It built 459 sections, 606 page fragments and 1,176 indexed heading phrases. One test returned eight passages across synthetic notes, observation and verified pathology text in about 0.83 seconds. All returned headings/quotes were checked against actual physical pages; saved-note edits invalidated old matches and an unavailable original failed closed. Original page80 and its displayed passage were visually compared privately. This is source/provenance verification, not medical validation or packaged Windows acceptance. No source text or derived database from that check is in this repository.

## Local tests and remaining acceptance

Backend regressions cover source-linked original wording, physical-page continuation/repeated headings, dates/units, excluded rows, no clinical inference, context/hash/registration changes, explicit truncation, heading-only opening passages, indexed-query use, corrupt/incomplete index rebuild and failure states. Desktop tests cover saved-only/dirty blocking, correct patient routing, delayed responses/errors, changed context/reference, escaping and no Insert.

Synthetic 1280/1440 panel and 1280 report-sidebar layouts were inspected. Actual-source private page/panel comparison was also inspected. Viewer requests in the local renderer are stubs, not packaged acceptance. Local backend testing uses a fail-if-used Windows-lock shim on Linux; native-only behavior is not claimed tested there.

Run native CI against the exact integrated table revision. Later packaged acceptance must exercise normal Interview saves/dirty state/pathology verification, source-table build/reuse, unavailable/changed original and exact physical-page opening on an isolated profile. Register the actual supplied PDF privately; do not bundle it in the installer or public artifacts.

Keep the medicine contract gap open: OCR-selected identity -> interview -> explicit medicine confirmation -> existing eMIMS queue payload -> report medicine table still needs a synthetic end-to-end contract. Legitimate interaction completion and normal report/Add gating remain unverified where the packaged helper is absent. Never bypass the gate or invent an interaction result.
