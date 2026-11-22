# HMR Desk — PR #39 Pathology Engineering: Detailed Implementation and Continuation Handover

**Document date:** 22 November 2026 (Australia/Brisbane)  
**Audience:** next senior developer / clinical safety reviewer / pharmacist owner  
**Repository:** https://github.com/chemisttasker11-ezy/hmr-desk  
**PR:** https://github.com/chemisttasker11-ezy/hmr-desk/pull/39  
**Branch:** feature/pathology-evidence-and-targets-nov22  
**Base:** integration/hmr-reviewed-nov22-v8 at a579f3cce10921e8fe5246b1109d28197d0d9f9c  
**Last tested CODE commit before this documentation-only handover:** 460311838576b555d8af03fff92eb24844684ec4  
**Release decision:** DRAFT; HOLD — NOT clinically accepted; NOT ready for general real-patient pathology use.  
**Do not merge into main, auto-verify results, issue treatment advice, or upload original patient data into GitHub/CI.**

## 0. Read this first — executive truth and provenance

The owner asked for implementation, not merely a plan: strengthen the pathology PDF-to-row proposal system against the original owner-authorised private corpus; verify every numeric field and source pixel; add fictional regression tests; preserve pharmacist review; and keep Draft PR #39 unmerged until explicit clinical acceptance.

This handover is explicit about what is **pre-existing on PR #39**, what was **implemented in the subsequent continuation**, what was **measured in the earlier private audit**, and what remains **untested or blocked**. A passed synthetic CI run establishes that a narrow code behaviour has not regressed, **not** that a laboratory result is accurate. The 293-document count is inventory, not a set of scored patient results.

Evidence sources reviewed for this continuation:
1. The user-supplied HMR Desk pathology autofill implementation prompt (DOCX; prepared 22 November 2026): geometry-first digital text, source hashes, idempotency, original-PDF review, unverified acceptance, no OCR before separate validation, preserve AI/report privacy and manual workflow.
2. The separate private-corpus audit titled HMR Desk Pathology Real-World Validation Audit (22 November 2026), including 51 folders, 293 PDFs, 36-original-PDF pilot, and detailed field-association failures. The audit and aggregate numbers were read. No identifying patient information or original patient PDF is reproduced here.
3. Live GitHub PR #39, code files, tests, PR comments, and Windows GitHub Actions logs for the precise commit given above.

**Important provenance limit:** no separately retrievable file titled "Pathology Online Agent Execution Plan" was verified in the available sources beyond the supplied autofill implementation prompt; locate any additional named execution-plan file before claiming every external plan requirement is fulfilled. The earlier private 36-PDF pilot was **not rerun** during this code continuation. Do not claim new real-world per-field accuracy or pixel-ground-truth findings from this work.

## 1. Work ownership, scope and safety rules

### 1.1 Scope of this engineering mission

* Consume local pathology PDFs that have been imported into the correct patient workspace.
* Propose only source-traceable, geometry-aligned, **unverified** laboratory rows.
* Read raw analyte name, result, printed unit, printed laboratory interval, specimen collection date (not print/report date), date-column identity and physical PDF row/cell coordinates. Never fill an uncertain field with a guess.
* Keep proposal generation separate from accepted structured rows, the older free-text interview pathology list, reports, clinical findings and outbound AI payloads.
* Show original PDF pixels, allow edits/rejection, and require a pharmacist to accept a specific proposal as unverified. Explicit subsequent pharmacist verification with reviewer identity remains separate.
* Enforce patient/source binding, SHA-256, record-revision checks, repeat-acceptance protection, source-path restrictions and transaction integrity.
* Use synthetic (fictional) fixtures for all GitHub commits and CI. Use original private patient PDFs only for authorised local evaluation, with aggregate non-identifying findings leaving the private environment.

### 1.2 Explicitly out of scope here

No automatic clinical interpretation, calculated/converted units, eGFR or renal dosing calculation, medication changes, abnormality-based treatment advice, automatic verification, expanded external AI schema, clinical target engine, live Medicare/MHR/PRODA/GP delivery, claims, SMS or working patient-data migration. The user can still enter pathology manually. Do not silently modify these boundaries to make a test pass.

## 2. Repo state and already-existing design before this continuation

At handover the base checkpoint was verified by the earlier PR author as integration/hmr-reviewed-nov22-v8 at a579f3c.... PR #39 was an open **Draft** against that checkpoint; main was not modified.

Pre-existing work already in PR #39 (do **not** claim it was newly implemented in this continuation):

| Existing component | Source / function | What it already does |
| --- | --- | --- |
| Local source import and index | HMR Desk/engine/pathology_import.py | Copies a selected PDF into the patient Pathology directory, records SHA-256, per-page excerpts and document metadata, limits size/pages/source count, rejects exact duplicate import and unsafe source path. |
| Independent parser/proposal envelope | HMR Desk/engine/pathology_proposals.py | Extracts bounded digital text geometry and candidate cells; provides raw and parsed text, field-level uncertainty, page and cell boxes, dated columns and deterministic IDs. |
| Original row visual | HMR Desk/engine/pathology_source_image.py | Recomputes a source-bound proposal and returns a small on-demand original PDF row crop; renderer cannot supply an arbitrary path or rectangle. |
| API integration | HMR Desk/engine/routes_clinical_records.py | Authenticated/authorised patient pathology source, proposal, image and record routes; acceptance creates an unverified row. |
| Accepted records | HMR Desk/engine/pathology_records.py | Validates row schema, 120-record limit, version/revision, explicit reviewer verification, edit-unverifies rule, immutable change history. |
| Frontend | desktop/renderer/interview.js | Import/source-page/manual-entry controls, table of proposals, editable field inputs, per-row original preview, accept as unverified, source reload, conflict/dirty guards, patient-switch response guards. |
| Parser/safety test suites | HMR Desk/engine/test_pathology_proposals.py, test_pathology_proposal_api_safety.py, test_pathology_realistic_layouts.py | Test source-linked geometry, dates, units, records and actual API unverified-accept path with invented PDFs. |
| Focused Windows CI | .github/workflows/pathology-safety.yml | PyMuPDF and pytest on Windows 2022, focused pathology tests and renderer syntax. |
| Reference architecture document | docs/pathology-reference-target-design-nov22.md | Separates laboratory observation, guideline evidence and clinician-approved patient-specific therapeutic goals. This is design only, not an operational target engine. |

Important wiring:
* API GET /api/patients/{patient_id}/pathology/sources/{source_id}/proposals calls pathology_proposals.for_source.
* API POST to the same proposals route requires exactly proposal_id, source_sha256, revision and fields. The accepted row is always verified:false through pathology_records.save.
* API POST /api/patients/{patient_id}/pathology/sources/{source_id}/proposal-image takes proposal_id and source_sha256, not an arbitrary path or crop box.
* Existing GET/POST /api/patients/{patient_id}/pathology-records controls structured results. Only this separate save path can explicitly verify with reviewer identity and valid source/units/date.
* Original PDF files are plaintext under the patient Pathology workspace even though structured database records are protected: **database encryption does not imply PDF-file encryption**. This remains a privacy/backup acceptance issue.

### 2.1 Current parser data contract (do not confuse proposal with accepted result)

Current envelope reports schema_version = pathology-proposals-v1, extractor_version = digital-geometry-v2, source_id, source_sha256, records_revision, pages (status and reasons), proposals, verification = UNVERIFIED and limitations.

An individual proposal has:
* id; source_id; source_sha256; page; method = digital_text; source_column_label.
* row_bbox and cell_bbox entries for test, value, unit, reference_interval and sample_date, in PDF page coordinates.
* raw_text (source-derived string fields) and fields (candidate result strings).
* field_uncertainty keyed to fields and warnings prompting visual patient/source review.

Accepted structured rows have only the separate pathology_records schema fields: id, test, value, unit, reference_interval, sample_date, source, verified, comment. Their verification trail is separate. There is **no current structured accession/time/method/laboratory field in accepted records**. The present proposal schema also does not preserve a validated per-column specimen accession/time. This missing metadata is a material blocker for repeated same-day specimens and method-specific reporting.

### 2.2 Existing safety boundaries to preserve during any future changes

* Source ID is a 32-hex ID in the relevant patient's indexed sources, not a filesystem location from the renderer.
* Original source bytes are re-hashed against recorded SHA-256; changed bytes or page count result in an error; source is rechecked after extraction.
* Preview recreates/locates the proposal by current source rather than trusting client-provided coordinates.
* Accept recalculates the proposal, checks hash/ID/revision, generates a patient-scoped record ID, rejects existing matching ID, and writes through the revision-checked record service.
* A verified row cannot be overwritten or silently amended as verified; editing requires unverified save followed by a separate verification.
* Pending responses in renderer are guarded against patient switching and request-generation changes.
* Import proposals are not automatically inserted into AI, report or older interview pathology arrays. Do not expand clinical_privacy.py projection.
* Missing scans and unsupported tables should be marked unavailable/unparsed; refusal is not a successful extraction.

## 3. Private real-world audit — existing evidence, NOT newly re-scored by this continuation

### 3.1 Owner-authorised inventory

| Folder cohort | Patient folders | With dedicated Pathology folder | PDF documents |
| --- | ---: | ---: | ---: |
| HMR Ongoing / Scheduled | 23 | 15 | 109 |
| HMR Ongoing / Visited / SEP-OCT / zzz Not sent to Islam | 28 | 26 | 184 |
| **TOTAL** | **51** | **41** | **293** |

These 293 are source PDFs, not individual laboratory result cells. Ten patient folders without a dedicated Pathology subfolder may contain additional PDFs, which were not counted. The corpus includes biochemistry, FBC and other numeric tests plus microbiology, histology and specialised/narrative reports.

### 3.2 Earlier original-PDF pilot

Earlier auditors privately downloaded 36 original PDF files (37 pages), from both cohorts, and used PyMuPDF geometry plus selected visual page rendering. **None of those 36 was a truly image-only scan**; scanned OCR fidelity is unmeasured.

| Version evaluated in earlier audit | PDFs returning at least one proposal | Count of proposed rows | Safe interpretation |
| --- | ---: | ---: | --- |
| Strict original labelled-header baseline | 0 / 36 | 0 | Actual common lab layouts unsupported |
| PR #39 digital implementation / local logic mirror after prior reference-interval fix | 5 / 36 | 159 | Narrow coverage, not a measured accuracy rate |
| Experimental generic cumulative + Sonic parser, private/local only | 22 / 36 | 265 | **Do not merge**: demonstrated wrong labels/field association and important omissions |

**Never present 22/36 or 265 rows as accuracy.** No independent true-positive/false-positive/false-negative/field-level ground truth was completed for all source analytes. These numbers must be treated as historical baseline and remeasured after every parser change. The unmerged experimental parser is not an accepted implementation.

### 3.3 Audit-discovered defects and their current treatment

1. Vertical/lateral watermark entering laboratory reference interval: earlier PR #39 restricted cumulative range recognition to parenthesised numeric source cells. Recheck all applicable originals and synthetic edge cases; not independently remeasured here.
2. Scientific-number FBC units printed as adjacent word objects (e.g. numeric-power prefix and /L): current parser still requires a complete PRINTED_UNIT word and can skip split units. No new complete unit adapter was shipped in this continuation.
3. HbA1c two-unit format: the lab can label a second row "in SI units"; do not invent a separate analyte name. This continuation blanks such a cumulative candidate test field and flags its identity, but **does not** implement fully supported two-form HbA1c matching.
4. Cumulative historical blank/misaligned cells and H/L flags: potential omission, wrong-column or wrong-value risks remain and need lab-adapter-specific tests. Blank historical cells must never be interpreted as zero.
5. Two distinct samples on the same calendar date: current continuation **abstains entire repeated-date cumulative layout** pending proved accession/time-to-value column mapping; this is intentionally conservative, not a supported multi-specimen parser.
6. Conditional high-risk lipid guidance printed near lab ranges: must not populate a general lab reference or trigger a patient target. Existing code has a narrow conditional-target heuristic, which is not general proof of classification.
7. Qualitative microbiology, susceptibility, histology, electrophoresis, gases and hospital specialist layouts are not supported by a generic numeric regex parser.
8. Different assay/methods or historic reference intervals require original laboratory identity and method association; do not normalise across eras.
9. Historic printed guideline targets must not become current therapeutic goals without independent dated Australian evidence and contextual pharmacist review.
10. Image-only, skewed, rotated, text-over-image, watermarked or hand-annotated scans require separately validated OCR and image-box mapping.

## 4. EXACT work executed in this continuation (new code only)

### 4.1 Reconciliation and initial engineering review

1. Read the attached pathology autofill handoff and full private real-world audit.
2. Connected to chemisttasker11-ezy/hmr-desk and confirmed PR #39 was open, Draft, based on integration/hmr-reviewed-nov22-v8, with head initially df168a9209354407389c578e13d0fd2a4e954b26.
3. Read the parser, record storage, source-image route, API, renderer interactions, existing unit tests and clinical privacy boundary. Verified requirements.txt pinned **PyMuPDF==1.26.5** and the Windows CI workflow was real rather than assumed.
4. Confirmed real source diversity and highlighted safety-first abstention rather than merging the unsafe larger experimental parser.
5. Edited ONLY the existing parser and the existing fictional PDF regression test file. No private PDF, raw result, identifying filename, screenshot, training corpus, licensed reference or patient copy was committed.

### 4.2 Final code change A — rotated page and large image/text overlay safeguard

**Location:** HMR Desk/engine/pathology_proposals.py, _page_proposals, immediately before geometry extraction.

* If the PDF page has nonzero page.rotation, return no proposals with a stated rotated-page reason, instead of risking boxes that point to different pixels.
* Obtain page.rect dimensions and page.get_image_info(xrefs=False).
* For each image, intersect its bounding box with the page; if a raster image covers **more than 70% of the page area**, abstain with a message that an OCR text overlay is not validated.
* Otherwise continue existing digital-text line/word geometry.

**What this is and is not:** a conservative scan-overlay heuristic for common page-sized scans. It does **not** prove small-image OCR overlays, multiple tiles, layered graphics or all altered texts are safely identified. It does **not** introduce OCR. The 70% criterion is engineering heuristics, not a clinical sensitivity threshold. The original PDF still requires pharmacist pixel comparison.

### 4.3 Final code change B — repeated specimen dates

**Location:** pathology_proposals.py, _cumulative_proposals after the explicit date-header/coordinate checks.

* Build parsed date strings from the supported cumulative date column headers.
* If two distinct result columns have the **same parsed calendar date**, return no proposals and a specific "Repeated specimen date without validated accession/time mapping" reason.
* Do not borrow accession/time from another column, choose a "latest" result based on position, deduplicate two samples, infer zeros or collapse the specimen.

**Implication:** true same-day samples currently abstain even when the PDF might display their accession numbers, because the parser has no validated association logic yet. This is a safety block and can reduce proposal coverage. Replace it only after synthetic and independently pixel-annotated private real-case proof of column-to-accession/time binding.

### 4.4 Final code change C — SI-unit descriptive labels are not analytes

**Location:** pathology_proposals.py, _cumulative_proposals after fields are assembled.

* For candidate analyte labels matching "in SI units", "SI units" or "in conventional units", preserve the exact source text in raw_text.test.
* Set fields.test to an empty string, with a visible field_uncertainty.test explaining that source analyte identity requires confirmation.
* Do not silently call this "HbA1c IFCC", "HbA1c" or any other inferred analyte just because the result is in mmol/mol.
* Existing acceptance requires a nonblank test and value; thus that proposed row must be corrected after review before it can be accepted.

**Scope limitation:** this targeted rule applies to the cumulative adapter. It is not a general method/assay identity classifier and does not itself associate two HbA1c output forms.

### 4.5 Final code change D — extractor version

EXTRACTOR was changed from digital-geometry-v1 to digital-geometry-v2. Proposal IDs include extractor version, source hash, page, test/value cell boxes and source column label.

**CRITICAL FOLLOW-UP:** this version change changes the deterministic proposal IDs for the same PDF cells compared with v1. Accepted record IDs are derived from patient ID + proposal ID. The current duplicate guard checks those record IDs; it has **not** been proved to stop the same source cell being accepted again under another extractor version, especially after a parser upgrade. Before clinical release, introduce a separately stable, source-location-based acceptance identity or equivalent version-agnostic deduplication, plus a v1-to-v2 upgrade test. Do **not** rewrite or silently migrate previously accepted records. Review source-column and accession/time identity explicitly.

### 4.6 Fictional regression tests added

**File:** HMR Desk/engine/test_pathology_realistic_layouts.py. Four tests were appended to the existing synthetic fixture suite, using in-memory PDFs generated with fitz:

1. test_repeated_calendar_day_abstains_without_unique_accession_mapping — duplicate printed day with two different numeric columns results in zero proposals and explicit accession/time reason.
2. test_rotated_table_abstains_instead_of_misplacing_cells — synthetic 90-degree rotated result table is not parsed.
3. test_searchable_text_overlay_on_page_sized_raster_is_unverified — a full-page PNG scan with a searchable text layer over it is refused, not trusted as original-pixel evidence.
4. test_cumulative_si_units_description_has_no_invented_test_name — retains raw "in SI units" but leaves proposed analyte empty with uncertainty.

Existing tests of the single- and multi-date digital layouts, FBC units/flags, HbA1c dual rows in explicitly labelled supported layouts, lipid ranges, API acceptance and source-hash checks also ran. No new synthetic test in this continuation demonstrates a newly supported Sonic, 4Cyte or Pathology Queensland layout, split scientific-number unit, or native OCR field association.

## 5. Commit-by-commit engineering history, including mistakes and rollback

The actual continuation commits are listed below so another engineer can trace **what was attempted** and what remains in the final tree.

| Commit | Action / outcome |
| --- | --- |
| df168a9209354407389c578e13d0fd2a4e954b26 | PR #39 head at start of continuation, before this engineer's edits. |
| da545a0b8b538fc5d12d4dd1384ce986450dd80f | **Bad intermediate text replacement**: duplicated a portion of pathology_proposals.py during a generated edit. This was identified immediately by multiple function definitions and abnormal file length. Do not use or cherry-pick this commit. |
| 249af95bd15cba98f1074cdc57c4849c22c86f7f | **Immediate restoration**: replaced pathology_proposals.py with its exact original content from df168a and rechecked that there was one _page_proposals definition. No bad duplicate remained in the final file. |
| e874842dd5908b57c66d2523dfe07d23f086313a | Narrow, source-anchored implementation of rotated-page abstention, large-image overlay abstention, duplicate-date abstention, SI-unit label uncertainty and extractor version bump. |
| 0b11e4ea54b8e924fa3616524da357a98ce13903 | Added the four fictional PDF regression tests above. The initial Windows focused CI run caught a failure. |
| 460311838576b555d8af03fff92eb24844684ec4 | **CI repair / last tested code head:** PyMuPDF fitz.Rect does not expose get_area() in the pinned runner; replaced with width * height of page/intersection rectangles. Verified against the exact pinned Windows CI version. |

The first new CI run associated with the test commit **44979080489** returned **13 failed, 10 passed, 5 warnings**, all cited failures caused by the incorrect Rect.get_area() call in the new guard. The succeeding run **44979170103** at 4603118 returned **23 passed, 5 warnings** and successful renderer syntax. Thus no outstanding focused-CI failure remains on the **tested code commit**. The earlier failed run is useful evidence of why pinning and CI matter, not acceptance evidence.

A documentation-only commit that adds this handover will produce a newer PR head. Distinguish its SHA from the code-validation checkpoint; do not claim the documentation commit itself went through a new Windows installed acceptance.

## 6. Verification performed — exact Windows CI links and counts

Test runner was Windows Server 2022 / Python 3.12.10 with pip-installed runtime requirements (PyMuPDF 1.26.5) and pytest 8.4.2. CI used synthetic/fake data, not the private owner corpus.

| CI workflow / job | Result on code commit 4603118 | Evidence |
| --- | --- | --- |
| Pathology safety focused synthetic verification | **23 passed, 5 warnings in 3.29s** across five focused pathology test files; renderer node --check passed | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44979170103 |
| M2 fast synthetic backend regressions — selected clinical/privacy suites | **695 passed, 3 skipped, 5 warnings** | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44979170089 |
| Same CI, **whole backend** suite | **1083 passed, 13 skipped, 5 warnings in 96.43s** | Same run |
| Same CI, targeted referral intake preparation | **12 passed, 5 warnings** | Same run |
| Same CI, desktop tests (Node TAP) | **560 total, 551 passed, 9 skipped, 0 failed** | Same run |
| Same CI, synthetic UI/visual job | **Job succeeded**, synthetic 125/150% layout audit artifact uploaded; not a native pharmacist pathology UAT | Same run |
| M2 Windows standalone engineering verification / installer | **Pending at last observed check; no job-level success established** | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44979170070 |
| Native Windows 11 x64 clean non-admin installed real-app workflow, offline | **Not performed** by this continuation | Manual acceptance gate remains open |
| Authorised private 36-original-PDF field/pixel-scored rerun after new changes | **Not performed** | Private gate remains open |

The five focused test modules run by the pathology workflow:

    cd "HMR Desk/engine"
    python -m pytest -q test_pathology_proposals.py test_pathology_realistic_layouts.py test_pathology_proposal_api_safety.py test_pathology_records.py test_pathology_import.py

Syntax:

    node --check desktop/renderer/interview.js

Broad backend CI ran its whole backend suite, plus separate selected suites. From the backend engine directory, a reproduction starting point is:

    python -m pytest -q

Desktop CI uses the desktop npm test script (Node --test). From the desktop package directory:

    npm ci
    npm test

First install the requirements at the repo root:

    python -m pip install -r requirements.txt
    python -m pip install pytest==8.4.2

Confirm the currently checked-out commit, working-tree status and branch before testing; do not run against a different PR or main.

    git fetch origin
    git switch feature/pathology-evidence-and-targets-nov22
    git status --short
    git rev-parse HEAD
    git diff integration/hmr-reviewed-nov22-v8...HEAD --stat

The focused workflow listens to pathology-specific code/tests/renderer/workflow paths, not every documentation path. A documentation-only commit may not retrigger the focused suite. Cite the tested code SHA and the run rather than stating "the latest head was installed."

### 6.1 Interpretation of warnings

The five pytest warnings were PyMuPDF/SWIG deprecation warnings, not five failed assertions. CI also warned that older Node 20 actions are being forced onto Node 24. They deserve dependency maintenance, but do not transform a passing test into a proof of source accuracy. Node synthetic visual logs include expected mock route failures; the job conclusion is success, not evidence of real clinical correctness.

### 6.2 Results explicitly NOT demonstrated

No independently established laboratory-extraction precision/recall by field or layout, no full 293-PDF evaluation, no OCR accuracy, no quality benchmark across Australian laboratories, no 100% cell-box-to-pixel check, no native installed offline Windows 11 report persistence/reopen, no real-world package privacy audit, and no pharmacist approval. Do not imply any of these from the 23/1083/551 CI counts.

## 7. Priority engineering backlog — actionable stages and precise exit criteria

Order matters: **do not widen parser coverage before proving identity and accepted-row deduplication**. Any discovered source bug should lead to a fictional regression test, not a private committed screenshot or real sample file.

### P0 — Prevent clinically dangerous silent errors (first)

**P0.1 Stable accession/time and specimen identity**
* Add a separately validated proposal provenance object for laboratory, source hash, source page, analyte raw text, cell positions, specimen date AND time, accession/request number, method and printed date-column label. Keep report/print/received dates disjoint from collection dates.
* Require a header-to-accession/time-to-result-column geometry proof for repeated same-day samples, including 2–5 columns, missing historic cells, unique accessions, time ties and overprinting. Prefer explicit unresolved fields and reasons over a best guess.
* Extend synthetic PDFs and source-pixel annotations. Exit: every supported candidate can be assigned to the correct specimen with exact date/time and accession; ambiguity abstains.

**P0.2 Cross-version duplicate-acceptance hazard**
* Because extractor v2 changes proposal IDs, acceptance IDs derived from the proposal ID may allow a v1-accepted physical cell to be reaccepted as a new v2 ID.
* Design a stable source-location/specimen-column identity independent of extractor version. Preserve existing row audit. Avoid requiring unsafe migrations.
* Add a v1 recorded row -> v2 re-extract -> duplicate accept rejection test using the actual API and record history. Also test source-byte edit, re-import, stale source_revision, same-test repeat dates and different patients.
* Exit: zero duplicate accepted rows from same source cell across versions, while truly distinct samples remain distinct.

**P0.3 Split FBC unit fidelity**
* Treat individual glyphs/words for printed 10^9 /L and 10^12 /L (including typographic superscripts/spacing) as one unit **only** if source coordinates prove contiguity. Preserve raw glyph order and unit boxes; do not infer /L when absent.
* Add clean, broken, wrapped, overprinted and OCR-layer synthetic fixtures. Exit: fully exact unit or blank/uncertain; no partial "10^9" silently labelled complete.

**P0.4 HbA1c dual-form identity**
* Preserve NGSP % and IFCC mmol/mol as two separate literal reported forms. If the second line says "in SI units" only, either prove the adjacent form's analyte/assay grouping with explicit page geometry or leave analyte blank.
* Preserve both raw forms, flags, reported dates and method; no unit conversion or invented values.
* Test numeric mismatch, intervening notes, unrelated SI line and date change. Exit: no invented analyte, wrong units or cross-specimen association.

**P0.5 False interval and treatment-target rejection**
* Remove decorative watermark contamination, suppress footnote and narrative-value collisions, and separate a printed laboratory interval from a high-risk or condition-specific therapeutic target.
* Test target-only lipid rows with no general range; if conditional text cannot be classified, blank reference_interval with explicit reason.
* Exit: no copied conditional therapeutic target into a generic laboratory reference or clinical auto-target.

**P0.6 Security, verification and report boundary**
* Regression-test actual API and renderer acceptance, not merely pure parser. Include switched-patient delayed requests, cancel/retry, manual dirty edits, multiple outstanding requests, stale revision and source replacement.
* Recheck verified-row overwrite prevention, reviewer requirement, edit-unverify history, and no unverified proposal in reports, findings or AI payloads.
* Address encryption exposure: original PDFs currently plaintext in patient workspace. Verify backup/restore/export and supportable protection-at-rest design without breaking existing workspaces.
* Exit: no bypass of source/patient/verification/privacy gates in adversarial tests.

### P1 — Lab-specific precision and measured coverage

Build **separate**, explicitly scoped adapters and version their contracts, using geometry rather than flattened string reading order:

1. QML cumulative serum biochemistry, lipids, thyroid panels and FBC, with explicit collection/accession headers and blank historical positions.
2. Sonic Dx layout families, including dual reporting and full reference/unit cells.
3. 4Cyte panel layouts.
4. Pathology Queensland cumulative/hospital multi-column tables.
5. Multi-page continued headers, wrapped analyte names, footnotes and assay/method changes only where cross-page association can be proved.

For each adapter document sample layout signature; field boundaries; columns/units/flags; supported date and accession formats; reasons for abstention; synthetic fixture coverage; and private validation results. Do not merge a generic higher-output parser only to improve coverage numbers.

### P2 — Separately validated local scan/OCR track

* Keep current image-only/rotated/unvalidated text-overlay pages **unavailable**.
* Only after digital acceptance, write a pathology OCR adapter with local processing and word/cell bounding boxes; no external OCR or AI service.
* Prove text characters AND numerical/source geometry against original pixels, including 0/O, 1/I, decimal dot, less-than/comparator, minus sign, superscript and multi-column date labels.
* Track an OCR-derived flag per field, do not equate OCR confidence or agreement of engines with actual correctness. Do not silently auto-correct ambiguous digits.
* Test rotated, low contrast, skewed, mixed searchable/scanned and multi-page; full source image remains available for human comparison.
* Separate native packaged offline dependency testing from parser unit tests.

### P3 — Qualitative reports and Australian clinical references

Qualitative microbiology, culture/antibiogram, histology, blood gases, electrophoresis and narrative reports need their own schema rather than forcing numeric row fields. This is future work, not licence to auto-summarise. Reference design must keep: (a) lab observation/range; (b) dated/valid Australian guideline evidence; (c) explicit patient-specific clinician-approved goal. RCPA Manual, individual lab assay details, RACGP, Kidney Health Australia/CARI/KDIGO and appropriate cardiovascular references may inform human interpretation; AMH and eMIMS remain licensed sources. **Do not** copy copyrighted/credentialled reference datasets into the repo or implement patient-specific target or dose rules in PR #39 without separately approved scope.

## 8. Private validation protocol — must be completed on original pixels

### 8.1 Source custody

Keep the private original PDFs in the owner's connected Chemist 11 Google Drive or an owner-approved local encrypted evaluation workspace, not GitHub or CI. Navigate privately to:
* HMR Ongoing / Scheduled;
* HMR Ongoing / Visited / SEP-OCT / zzz Not sent to Islam.

Do not export full patient folder trees, patient names, identifiers, actual lab values, raw PDF bytes, screenshots, audit ground truth sheets or paths containing identifiers to public logs/PR comments. Use local random aliases for evaluation IDs, store alias maps privately, and export **aggregate-only** results. The earlier inventory was 293 PDFs, not guaranteed exhaustive.

### 8.2 Ground truth before scoring

1. Freeze source PDF hash, page count, lab layout family, collection date/time and accession for each private original.
2. Independently transcribe **every eligible result cell** from rendered source pixels: literal test, value, comparator, H/L mark, unit, laboratory reference, specimen date/time/accession, method and column.
3. Record explicit unreadable/unavailable/unsupported cells and justified ambiguities. Label multi-page continuation and historical blanks.
4. Match each proposal to a unique original cell using source SHA/page/bbox/column/specimen identity. Manually inspect pixel overlay/crop for alignment, especially digits, superscripts and neighbouring columns.
5. Compare returned fields to that independent pixel ground truth, including missing proposals and incorrect proposals; measure edits needed before pharmacist can accept.
6. Validate using an untouched set, not only examples used to tune the parser. Keep development/test separation by document and patient. Do not call prompt-driven manual reasoning a reproducible automated accuracy test.

### 8.3 Mandatory per-layout metrics

Report for each lab/layout and for each collection date/column family:
* PDFs attempted and recognised; pages; eligible source cells; proposed rows; supported/unparsed/abstained fraction.
* Per-field **exact match numerator/denominator**: test/analyte, value/comparator/sign/decimal, unit, printed laboratory interval, collection date, collection time, accession, method where present.
* Source-page and cell-box pixel alignment exact match rate.
* Correct matching of multi-column historical values, separate same-day samples and H/L markers.
* False-positive proposals, false-negative missed cells, wrong-patient/wrong-source association attempts, false "critical" values, false normality/target classifications (target inference should be absent).
* Reviewer changes required and reasons for ambiguity.
* Confidence intervals where valid; sample counts; no single aggregate rate hiding a high-risk lab family.

Accuracy thresholds and tolerable abstention targets need explicit owner/pharmacist acceptance. The non-negotiable invariant is **zero silent verification or patient/source privacy bypass**; a parser that safely abstains is preferable to a plausible but wrong clinical field. Do not derive new percentages from the 5/36 or 22/36 proposal counts.

## 9. Native Windows acceptance (not yet done)

Run on the **exact tested installer candidate** in a clean non-admin Windows 11 x64 environment, without installed Python, Node, LibreOffice, external developer tools or network. Record installer/build commit and dependency hashes.

1. Start HMR Desk offline with a fictional test patient.
2. Import synthetic digital PDF, inspect imported source copy and SHA-256.
3. Generate proposals; compare each with the original PDF page at 1:1 and zoom, using the safe source-image route. Pixel-locate every printed field.
4. Accept one proposal as **unverified** only, reject/ignore another, and manually add a separate row.
5. Deliberately edit the accepted row; save, ensure it remains unverified; explicitly verify as named pharmacist; edit again to prove unverify rule. Inspect audit history.
6. Save, close app, reopen, confirm exact values, source hash, revision and audit persistence.
7. Build a report and inspect both DOCX and PDF visually, ensuring only the correct reviewed data enters any report under the existing report policy; no raw proposals or unauthorised AI payloads.
8. Test patient switching during slow extraction, missing/changed original, stale revision, duplicate accepted row, reconnect, cancellation, source-path traversal attempts.
9. Repeat on image-only synthetic scan and without an OCR component; observe explicit unavailable/unparsed and preserved manual workflow.
10. Verify backup/restore, privacy protections for PDFs as well as encrypted records, and rollback of installed build without overwriting source data.
11. Record synthetic-only screenshots/artifacts in CI if appropriate; real-patient screen images stay private. Obtain a pharmacist's signed/recorded acceptance only after accurate private source evaluation.

Until this is complete the feature is a **Draft engineering candidate**, not an installed clinically accepted product.

## 10. Definition-of-done matrix (what can actually be checked)

| Gate | Status on 22 Nov handover | Required evidence to close |
| --- | --- | --- |
| PR stays isolated from main and Draft | **Yes** | Branch/PR metadata |
| Existing manual pathway and verified-record safeguards preserved | **Code-level + synthetic tests passed** | Add adversarial API/UI and installed recheck |
| Conservative rotated and scan-overlay abstention | **Implemented + synthetic Windows pass** | Source-pixel and packaged validation |
| Repeated same-day sample safety | **Abstain implemented** | Proper accession/time parser and private scoring needed for support |
| Ambiguous "in SI units" label not invented | **Implemented + synthetic Windows pass** | Full real HbA1c dual-form association needed |
| Per-field provenance contains accession/time/method | **Not implemented** | Versioned schema, adapter and API UI proof |
| Cross-version accept idempotency | **Not demonstrated** | Real v1/v2 upgrade regression, permanent identity contract |
| Split scientific FBC units | **Not implemented** | Pixel-tested token merger / abstention and fictional regressions |
| Lab-specific QML/Sonic/4Cyte/Queensland coverage | **Partial and not independently scored** | Adapter matrix + per-field truth |
| 293-PDF independent evaluation | **Not performed** | Privately measured aggregate metrics |
| Image-only scan OCR | **Not implemented/accepted** | Offline word-level OCR provenance, separate tests |
| Focused Windows CI | **Passed at 4603118** | Re-run for any later relevant code change |
| Full Windows backend + desktop regression CI | **Passed at 4603118** | Retest exact final code candidate |
| Native Windows 11 packaged installed round-trip | **Not performed** | Installer artifact + offline walkthrough + DOCX/PDF |
| Patient-private PDF storage / backups audited | **Not closed** | At-rest and export security evidence |
| Pharmacist clinical sign-off | **Not given** | Dated pharmacist UAT signoff after all evidence |
| General clinical pathology release | **HOLD** | All above gates + explicit owner decision |

## 11. Specific instructions for the next developer / agent

**Do not create a competing PR. Continue PR #39 and keep it Draft. Do not merge main or blindly merge an older divergent branch.**

1. Check out branch, verify exact head and compare to integration/hmr-reviewed-nov22-v8. Read this handover, original implementation prompt, existing reference-target design, original PR discussion and source files. Read any additional independently available Online Agent Execution Plan before saying its stages are complete.
2. Reproduce the 23-test pathology Windows baseline and the whole backend/desktop regressions before changing semantics. The baseline code SHA was 4603118; docs may advance HEAD afterward.
3. Tackle **P0.2 cross-version duplicate acceptance** and **P0.1 accession/time provenance** first, because untrusted repeated historical cells cannot be accepted safely if identity is unstable.
4. For each discovered defect: inspect PRIVATE original pages/pixels, identify precise source coordinates/word geometry; create only a fictional minimal reproduction in repo tests; fix a narrow adapter; run focused + full privacy/report regressions; privately rescore independent cases; only then expand layout support.
5. Never "fix" a poor number by normalising units, inferring clinically plausible values, substituting report date for sample date, guessing year from chronology, choosing the rightmost/max column, or labelling targets as reference ranges.
6. Preserve _source_path, for_source/accept, authenticated API, immutable record history and renderer patient/dirty/conflict guards. Any change requires an adversarial test through the real API/renderer.
7. Record a rolling evidence ledger per adapter with version, source cohort counts, field-accuracy numerators, omissions, false-positive cell counts, unresolved reasons and commit/run IDs. Only aggregate information in GitHub.
8. Package for Windows and do offline installed UAT plus pharmacist review. Do not auto-advance from synthetic CI to "approved" status.
9. Publish a new dated handover section with exact change list, test result/skip counts, private-evaluation *aggregate* metrics, blockers and rollback each time work is handed off.

Suggested work-unit order (each in small reviewable commits):
* Work unit A: stable source-cell acceptance identity across v1/v2, actual API duplicate test and upgrade regression;
* Work unit B: specimen date/time/accession provenance contract + same-day cumulative source column association;
* Work unit C: split unit tokens, HbA1c dual-form identity, reported range/goal separation;
* Work unit D: independently scored QML adapters, then Sonic, 4Cyte, Pathology Queensland;
* Work unit E: continued headers/footnotes/method changes and uncertainty UI;
* Work unit F: image-only/offline OCR adapter **only after digital test gate**;
* Work unit G: Windows installer, private field/pixel scoring, report round-trip, security audit, pharmacist acceptance.

## 12. Rollback, continuity and non-destructive recovery

* **Known passing code checkpoint:** 460311838576b555d8af03fff92eb24844684ec4. Earlier initial PR state: df168a9209354407389c578e13d0fd2a4e954b26.
* For regression on a new commit, restore/revert only the specific new commit after inspecting changed files and coordinating with parallel developers; never force-push/reset a shared head without explicit review. Do not revert all of PR #39 to solve one parsing defect.
* The earlier accidentally duplicated parser file was fully restored before the final narrower changes. Do not cherry-pick da545a0.
* Keep original patient PDFs, existing accepted rows, verification history and private audit untouched. Never remove or reimport originals just to reconcile changed proposal IDs.
* If a new adapter or OCR is faulty, disable its route or return explicit unavailable/unparsed while preserving manual entry. Back out behind a version/feature gate rather than silently dropping or relabelling patient results.
* Do not install this unfinished candidate over the owner's working app or alter live clinical services.
* PR remains Draft; acceptance criteria, not deadline or proposal count, control promotion.

## 13. Final truthful status and release directive

**Implemented in this continuation:** three conservative source-association guards, extractor-version bump, four fictional PDF regressions, one pinned-PyMuPDF CI bug repair, focused Windows success and separate broad backend/desktop/visual synthetic CI success. All changes were committed directly on existing Draft PR #39; no main merge.

**Only synthetic-tested:** those specific guards and the existing bounded proposal and acceptance flow. **Not remeasured:** private original PDF field accuracy and source-pixel alignment after changes.

**Not native-Windows-installed-tested:** clean non-admin offline installer -> import -> original pixel comparison -> unverified accept -> edit -> explicit verify -> save/reopen -> report DOCX/PDF -> rollback. **Not pharmacist accepted.**

**Release decision: HOLD.** Better proposal coverage alone cannot justify calling pathology extraction correct. The next engineer's job is to obtain reliable source-pixel-linked specimen identity, exact units and dates, independently scored per-field precision/omissions, and installed pharmacist acceptance **without weakening the current protection boundary**.
