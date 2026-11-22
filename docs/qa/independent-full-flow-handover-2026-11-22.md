# Independent senior engineering handover — PR #40

**Date:** 22 November 2026 (Brisbane)  
**Repository:** `chemisttasker11-ezy/hmr-desk`  
**Base:** `integration/hmr-reviewed-nov22-v8`, `a579f3cce10921e8fe5246b1109d28197d0d9f9c`  
**Working branch:** `qa/full-flow-source-report-20261122`  
**Pathology specialist:** PR #39 remains independent  
**Overall decision:** HOLD — not a clinically authorised release.

This report is an honest accounting of work actually performed. All real patient files and patient-specific values remain outside the PR and Actions.

## 1. Primary source documents reviewed

- The attached **Full Flow Real Data Online Agent Prompt** (22 Nov) was read completely.
- The attached **Pathology Real-World Audit** (22 Nov) was read completely.
- The senior's earlier **HMR Desk Milestone 2 Standalone Implementation Plan** (514 lines, 16 Nov) was read completely from the owner's Library. Its original branch instructions were for PR #1; the latest owner instruction explicitly authorises this separate full-flow PR.
- Examined PR #35/#38/#39 status and scope, base integration checkpoint, .github workflows, Python engine modules, Electron renderer handlers, test suite, and clinical report/sign-off data flow.

### Architecture and important trust boundaries

`desktop/renderer/interview.js` and `report-editor.js` call the token-bound local `/api/patients/<id>/...` routes. Clinical records are stored per patient ID in the encrypted records database, while original source PDFs and output files are separate plain files in patient folders. `referral_entry.review -> commit` first preserves the original PDF and pharmacist clinical review, `interview.load/save` preserves distinct prescribed vs actual rows, reconciliation confirms current medicine snapshot, `pathology_records` stores verified/unverified rows, `report.refresh` builds derived report cells, `jobs.report_build` creates a new versioned DOCX/PDF, and `report_auth.check_approval/check_sent` enforces source hashes and explicit clinical sign-off. Report files are **not** assumed encrypted just because record JSON is.

Independent tests must cover both the production API and Electron UI event flow. The existing `test_full_flow_integrity.py` explicitly seeds clinical review and does **not** test referral OCR. The existing `test_synthetic_patient_journey.py` tests a broader generated synthetic source; neither substitutes for private source-to-pixel clinical adjudication.

## 2. Fresh owner-authorised read-only corpus inventory

Live Chemist 11 Google Drive was used; no patient file was modified or shared.

| Case-folder immediate children (NOT recursive pathology PDFs) | Scheduled (23) | Visited (28) | Total |
| --- | ---: | ---: | ---: |
| Patient folders actually listed | 23 | 28 | 51 |
| Root-level PDF files | 41 | 53 | 94 |
| Root-level Word documents | 59 | 55 | 114 |
| Root-level image files | 29 | 30 | 59 |
| Other root files | 101 | 82 | 183 |
| Immediate subfolders | 17 | 26 | 43 |
| Of those, dedicated Pathology subfolders | 15 | 26 | 41 |
| Total immediate entries | 247 | 246 | 493 |

All 51 folder list operations succeeded. These figures are deliberately **not** added to the prior pathology-specific figure of 293 PDFs as though all were the same cohort/class: 293 counts PDFs nested inside pathology subfolders in the earlier audit. Some root-level PDFs are referral or consent documents, not pathology; the 94 count must not be mislabelled. This latest inventory counts direct children, not every nested clinical file or patient-level gold-standard field.

### Private source samples examined without publication

1. **One Scheduled case:** authenticated original source PDF (4 digitally text-backed pages), saved `interview.json`, and an interview Word file were fetched into a local/private workspace. The saved interview had seven prescribed medicine rows. A read-only exact normalised text search found each of seven medicine names and each of seven prescribed direction strings in the source PDF text layer (**7/7 and 7/7 of this small sample**). All seven corresponding actual-use fields were blank; no evidence was fabricated to call these reconciled. Matching anywhere in source text proves presence, **not correct page/row pairing**, OCR performance, verified extraction, or end-to-end fidelity.
2. **One Visited case:** authenticated original 5-page text-backed PDF, two distinct Word artifacts, and one three-page PDF artifact were inspected for shape. The Word documents each contain 13 tables, including complex formatting. A simple document-text-to-PDF string search yielded 103 of 128 sizable text segments in one candidate and 87 of 127 in the other; these are **not correctness scores**. The documents may be different revisions, and PDF layout changes line order and wrapping. A real source-and-version-aligned visual adjudication remains required. No identifying text, values or screenshots were committed.

**Private byte handling:** downloaded patient sources were used read-only in a temporary local evaluation workspace. The results disclosed in this PR are counts and invented defect patterns only.

## 3. Production defects found and addressed

### S1: Legacy record migration could follow linked records into another patient slot

**Before:** `records.import_folder` checked `path.is_file()` then `read_bytes()`, and `records.import_file` did likewise. A link to another path could be read and written under the wrong `patient_id`. No PHI is required to reproduce.

**Fix:** shared `_linked_component` guard for the leaf and each parent; refuse linked paths in both migration entry points before reading any bytes. Regular imports unchanged. Files: `HMR Desk/engine/records.py`, `test_legacy_import_link_isolation.py`. Four fictional tests: ordinary import, mocked symlink without Windows privilege, real leaf symlink, real linked parent.

**Limitation:** path inspection then read is not race-free under a hostile concurrent filesystem replacement; native no-follow handle protection and reparse-point hardening remain separate security work.

### S1: Pathology source-list async response could cross patient UI state

**Before:** the `data-pathology-reload-sources` click action awaited the API using mutable `interviewId`, then installed the returned source list unconditionally into the current screen. If the pharmacist switched patients during the request, the first patient's source-list response (or error) could display under the second patient.

**Fix:** capture `interviewId` and `interviewRequest` before the await. Only install the result/error and re-render if both and the current page still match. Existing safe import handler uses the same guard design. Files: `desktop/renderer/interview.js`, `desktop/test/pathology-source-reload-patient-isolation.test.js`. Three fictional timing tests cover late success, late error and normal same-patient success.

### S1: Interaction source evidence lost between sign-off and send

**Before:** the report build records `interactions_evidence_sha256` and `check_approval` checks it, but the resulting signed-off event did not preserve that digest; `check_sent` therefore did not detect interaction evidence changing **after** sign-off.

**Fix:** propagate nonempty build interaction digest into the signed proof and compare to current interaction evidence at the `check_sent` gate. Historical signed events without the field retain compatibility; new ones fail closed if the signed digest changes. Files: `HMR Desk/engine/report_auth.py`, `test_signed_interaction_evidence_freshness.py`. Two invented regression tests cover changed evidence and legacy events.

**Scope warning:** preserving legacy compatibility is not the same as proving older signed events had contemporaneous interaction evidence; cannot infer data absent from a legacy proof.

## 4. Exact commits in this incremental PR

- `957bb6a` — fictional legacy-link RED regression tests
- `765152c` — guard legacy import links
- `7e76ef0` — initial full-flow acceptance matrix
- `8360859` — pathology async patient-switch RED tests
- `5d253c1` — guarded UI reload
- `2e6c5fe` — interaction digest stale-after-sign regression tests
- `32e8c18` — preserve and enforce interaction digest in signed events

The first three commits were separately checked through Windows CI before subsequent changes. Follow-up CI must be judged by the most recent head, **not** a previously green commit.

## 5. CI and test evidence

Initial PR head `7e76ef0`: `M2 fast synthetic backend regressions` run `44980823809` completed successfully. Its **backend, desktop, and UI-visual** jobs all completed successfully. Initial Windows standalone run `44980823801` passed frozen-engine smoke, bundled offline LibreOffice PDF, synthetic HMR journey and related steps, while later packaging stages remained running at time examined.

After further code changes, GitHub opened new run `44981759488` for fast regressions and run `44981759437` for Windows standalone at `32e8c18`. They had not completed when checked. Prior aborted runs after superseding pushes must not be reported as failing application tests or as passing checks.

Expected checks at the latest head:
```text
cd "HMR Desk/engine"
python -m pytest -q test_legacy_import_link_isolation.py test_signed_interaction_evidence_freshness.py test_report_auth.py test_records.py
python -m pytest -q
cd ../../desktop
npm ci
npm test
```

Node tests must run against actual `desktop/renderer/interview.js` imported via VM, and Python tests use production `report_auth.check_approval/check_sent` plus database events. CI tests are synthetic and do not establish private real-case or clean Windows installer acceptance. The local online environment could inspect original source PDFs and document structure but could not clone GitHub directly using system DNS; GitHub connector writes and Windows CI were used instead. Do not claim locally executed Python/Node repository tests that were not run.

## 6. Remaining must-do / precise next execution sequence

1. **Immediate:** inspect final CI at head, fix any failing regression, commit a tested repair; no merges. Revalidate the exact head and any new pathology PR #39 contract changes.
2. **Private clinical corpus:** create a patient-separated, encrypted manifest for 51 cases; select >=12 development and >=8 holdout cases, with original PDFs, referral OCR/geometry and pharmacist notes. Store expected/actual per-field coordinates and original hashes only in private workspace. Do not publish manifest, original files, or exact values. Maintain report/visit artifacts by version, not guessed matching filenames.
3. **Intake/Interview:** actual `referral_entry.review -> commit -> interview API/UI -> save/restart/reopen` with original source bytes and precise line-level medicine directions. Audit page, medicine name, strength, form, direction, actual use, DAA, PRN, ceased, OTC, allergies and referrer provider. Test clean vs dirty navigation, stale review and multi-patient asynchronous re-entry.
4. **Pathology interface:** allow PR #39 to own extractors and targets. Cross-module tests should require reviewable unverified imports, lab-vs-therapeutic separation, original source evidence, exact patient and sample date/accession, manual fallback and report preservation. Do not cherry-pick broad unsafe parser experiments.
5. **Report:** verify the true owner-approved template and actual Word-table cells, GP plan blanks, pharmacist SAMP text, pathology units/reference and dated results. Compare generated DOCX/PDF source-to-output and re-open after restarting.
6. **Security:** address non-atomic migration link TOCTOU, native Windows reparse points, source-folder symlinks, backup/restore, outward network requests in AI-OFF, PHI in logs/crash artifacts and non-admin permissions; test explicit cross-patient API denials.
7. **Windows:** non-admin clean installed app with internet disabled and no Python/Node/Word/LibreOffice. Test bundled OCR and PDF, critical UI interactions, crash recovery, upgrade, backup and rollback.
8. **Sign-off:** accredited pharmacist must adjudicate source-pixel mistakes, omissions, clinical applicability, report wording and template. Do not approve before these gates.

## 7. Engineering acceptance table

| Required release gate | Status | Rationale |
| --- | --- | --- |
| Branch isolation from PR #39 and synthetic-only code | PASS | Separate PR and files; no patient bytes in code commits |
| Linked legacy import prevention | IMPLEMENTED, CI recheck open | Path guard and synthetic regression; TOCTOU still open |
| Async pathology source patient isolation | IMPLEMENTED, CI open | Guard and 3 tests; native UI still open |
| Signed-to-sent interaction evidence freshness | IMPLEMENTED, CI open | Guard and 2 tests; historical marker absence remains |
| Real-source private structural inventory | PASS | 51 case folders, 493 immediate children measured |
| Real field-by-field intake-to-report truth | FAIL/OPEN | One 7-row text presence comparison is not accepted E2E |
| Private >=12 development and >=8 sealed holdouts | OPEN | Not completed |
| Pathology clinical source pixel truth | OPEN / PR #39 | 36 original-file prior pilot was coverage only, not clinical correctness |
| DOCX/PDF approved-template exact matching | OPEN | Two private Word revisions inspected only, no approved output adjudication |
| AI-OFF native application workflow | OPEN | Synthetic Windows CI engine path is insufficient |
| Clean non-admin Windows offline installer | OPEN | Only CI packaging evidence so far |
| Accredited pharmacist sign-off | OPEN | Owner/clinician approval absent |

**Clinical release remains HOLD.**

## 8. Privacy and limitations

Do not place patient PDFs, real reports, interview JSON, identifiable filenames, private pixel excerpts or MIMS licensed material in GitHub, CI or public issue attachments. Do not call broad extractor proposal counts clinical accuracy. Original sources were downloaded from the authorised Chemist 11 Drive solely for this private local read-only evaluation. Never submit or send reports to patients or external recipients during engineering tests.
