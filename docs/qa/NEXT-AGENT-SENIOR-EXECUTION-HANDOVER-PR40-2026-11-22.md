# HMR Desk - NEXT AGENT SENIOR ENGINEERING EXECUTION HANDOVER

Prepared: 22 November 2026, Australia/Brisbane
Owner-authorised scope: HMR Desk whole-flow engineering and source-fidelity validation
Repository: https://github.com/chemisttasker11-ezy/hmr-desk
PR #40 (continue, remain Draft): https://github.com/chemisttasker11-ezy/hmr-desk/pull/40
Working branch: qa/full-flow-source-report-20261122
Base: integration/hmr-reviewed-nov22-v8 at a579f3cce10921e8fe5246b1109d28197d0d9f9c
Last verified PR #40 product-code SHA: 3275356c30f40e7c86a27eb41463b1011d1d1c1f
Related but separate pathology PR #39: https://github.com/chemisttasker11-ezy/hmr-desk/pull/39
Release and merge decision: HOLD. Engineering candidate only; no clinical acceptance.

**CRITICAL: This file is a handover and execution plan, NOT a statement that the missing tests or clinical acceptance have been completed.** A documentation-only commit may advance PR #40 HEAD after the product-code SHA above; check live Git metadata and the exact commit tested in each CI run.

## 0. READY-TO-PASTE MISSION FOR THE NEXT AGENT

You are the accountable senior engineer responsible for completing the HMR Desk whole-flow engineering acceptance mission in the existing Draft PR #40. Do not start with a high-level review or create a competing pull request. Begin by reading this document, the current PR #40 diff, original senior handovers and acceptance matrix, PR #39 pathology handover, all relevant implementation and test files and the latest exact-head CI logs. Verify current GitHub state; previous green tests do not prove the current SHA.

Your job is to IMPLEMENT, REPRODUCE, REPAIR, TEST and DOCUMENT, not to produce another unexecuted proposal. Start with the two confirmed failing CI workflows detailed below. Preserve the actual safety contract: changed interaction evidence after sign-off makes the prior approval stale. The test must be reconciled with this policy, rather than weakening check_sent just to achieve green CI. Correct the unrelated Linux-only teardown import fault without skipping privacy assertions.

Then execute the full original-referral-PDF -> reviewed intake -> patient interview (prescribed versus actual medicines) -> reconciliation -> pathology -> pharmacist-authored SAMP findings -> owner-approved DOCX and PDF -> hash-bound sign-off and safe sent-state journey. Use the real production Python routes, Electron renderer handlers and genuine offline installed Windows workflow, not only helper function simulations. Test save, close, reopen, refresh, failure, concurrent edits, duplicate/uncertain values, patient-switch race and report integrity. Preserve all original PDFs and existing pharmacist text. Clinical verification must be explicit; never infer an allergy absence, pathology normality, actual medicine use or patient preference.

Inspect the owner-authorised Chemist 11 Google Drive folders HMR Ongoing / Scheduled and Visited / SEP-OCT / zzz Not sent to Islam in a private, access-controlled workspace. Do not place source patient PDFs, interview JSON, identifiable filenames, pathology values, licensed references or screenshots in git, Actions or public tools. Build a patient-separated independent field-by-field gold standard from original rendered PDF pixels. Use at least 12 development and 8 untouched holdout cases, and report counts with real denominators and abstentions. Historical proposal counts are not clinical accuracy.

Keep pathology extractor changes in Draft PR #39, not PR #40. Coordinate only through tested, stable schemas; do not silently merge experimental extractors or change laboratory targets. Continue in PR #40 until code changes, synthetic CI and appropriate private source checks are evidenced. Document genuine external blockers such as non-admin Windows 11 user-machine and pharmacist clinical approval without pretending those were passed. Do not merge, release or send anything to a real patient. Finish by updating the PR handover with exact SHA, commits, tests including failures/skips, reproducible case evidence, coverage, remaining risks and final HOLD/PASS gates.

## 1. EXACT CURRENT STATE - CHECKED FROM LIVE GITHUB

### 1.1 Pull requests

- PR #40 open and Draft; same base as PR #39. At verification, 21 commits, 13 changed files, head 3275356c30f40e7c86a27eb41463b1011d1d1c1f.
- PR #39 open and Draft, branch feature/pathology-evidence-and-targets-nov22, head 2cb34c5b0b5a512d4f260034304791de71f1c9b6 at verification. Its substantive code and release evidence are tracked independently. The specialised pathology handover last identified a known tested code checkpoint 460311838576b555d8af03fff92eb24844684ec4; do not confuse this with the current PR HEAD or with PR #40's tests.
- Both PRs derive from integration/hmr-reviewed-nov22-v8, not main. Do not merge, retarget or force-push without an explicit integration review.

### 1.2 Current PR #40 CI at product-code SHA 3275356c30

| Workflow | Run | Observed result |
| --- | --- | --- |
| M2 fast synthetic backend regressions | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44982302723 | PASS: backend job, Electron desktop job and UI-visual synthetic job. Backend whole suite 1080 passed / 13 skipped. Curated isolated backend 695 passed / 3 skipped; additional intake tests passed. |
| Electron tests within Windows standalone workflow | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44982302713 | Step PASS: 555 passed / 8 skipped. |
| Clinical privacy contract | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44982302755 | FAIL: 21 tests passed but 21 teardown errors; Linux-only Windows-module import via conftest fixture. This is a failed CI gate, not evidence of a PHI breach. |
| M2 Windows standalone engineering verification | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44982302713 | FAIL at synthetic referral-to-signed-and-sent journey; frozen engine, bundled converter, DOCX/PDF and other earlier steps passed. NSIS installer, packaged desktop and installed smoke were not reached. |

The earlier successful fast regression run at 7e76ef0 is historical. Do NOT claim it validates the final product code. A subsequent docs-only commit need not change product behaviour, but re-check its changed-file list, workflow triggers and exact commit SHA.

### 1.3 Engineering work implemented in PR #40

1. HMR Desk/engine/records.py: linked-path refusal in legacy import_folder / import_file, protection status and removable-files preview; related tests in test_legacy_import_link_isolation.py. Still vulnerable in principle to an adversarial check-then-open race; Windows reparse-point semantics unproven.
2. desktop/renderer/interview.js: async pathology source-reload response/error is bound to captured patient ID and request generation. Tests in desktop/test/pathology-source-reload-patient-isolation.test.js.
3. HMR Desk/engine/report_auth.py: preserve interaction evidence digest in signed-off proof and revalidate at check_sent; tests in test_signed_interaction_evidence_freshness.py. Historical signed events without digest remain supported; no retroactive claim that an old interaction check occurred.
4. HMR Desk/engine/clinical_snapshot.py and jobs.py: new source-review contract 3 for newly generated report evidence, field-specific conditions review, legacy contract 1/2 digests preserved. Tests in test_snapshot_field_review_contract.py, test_snapshot_contract_compat.py and test_build_snapshot.py. Audit all other callers that assume CONTRACT_CURRENT=2; do not silently rewrite old events.

Neither the new security checks nor clinical contract 3 is equivalent to real-patient end-to-end acceptance.

## 2. DO THESE TWO P0 CI REPAIRS FIRST

### P0-A: Clinical privacy CI fails at teardown - reproduce and correct without skipping checks

Run: https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44982302755
Failed job: privacy / Privacy projection and local server regression tests.
Observed: tests ran, 21 passed, then 21 errors at teardown. Traceback: HMR Desk/engine/conftest.py, autouse fixture _restore_legacy_signoff_overrides, unconditionally imports legacy_signoff_support; the import chain reaches inbox -> outbox -> Android_SMS_Integration/sms_bridge.py, which imports Windows-only msvcrt on ubuntu-latest. Error is ModuleNotFoundError: No module named 'msvcrt'. The workflow uses Python 3.12 on Ubuntu.

Required investigation and fix:
- Check whether the fixture truly needs to import the legacy helper if none of the privacy tests has loaded it. A guarded cleanup of an already-loaded module (for example inspecting sys.modules) may avoid the unrelated import; prove it restores overrides when helper actually ran. Do not make the global fixture silently cease cleaning up legacy test overrides.
- Keep the privacy workflow exercising its original privacy, static-file service and manual-foundation tests. Do not skip 21 tests, add a fictitious msvcrt on Linux, remove a security assertion or disable the job just to turn it green.
- Add a portable regression verifying teardown does not import unrelated Windows modules and a legacy test that actually uses overrides still gets proper cleanup.
- Re-run the exact Linux privacy workflow and the full Windows backend. Record passing count and full job link.

Exit: privacy tests pass with zero setup/teardown errors; intended test isolation preserved on Linux and Windows. If any genuine privacy test fails after harness repair, treat it as a new defect and fix independently.

### P0-B: Windows standalone synthetic journey contradicts new signed-interaction provenance contract

Run: https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44982302713
Failure: HMR Desk/engine/test_synthetic_patient_journey.py, around line 256:
after initial sign-off, the test requests pathology recheck, adds a new manual interaction result and saves a later pathology result. The files and report-spec hashes remain the same, but the test asserts report_status.report_status(... )['signed_version_intact'] is True. Actual is False. The new report_auth.check_sent contract deliberately rejects changes in interaction evidence after signing. The run stops before installer packaging.

Do NOT remove the sign-off digest validation. Distinguish:
- historical signed DOCX/PDF bytes remain immutable and hashes match;
- the prior approval is no longer current after material interaction evidence changes;
- a later "report sent" transition must be blocked until a new reviewed report/sign-off is generated, per existing safe app workflow;
- original old signed evidence remains in history; a new revision is a separate auditable event, not an overwrite.

Precise repair procedure:
1. Reproduce the focused test using the actual built Word/PDF pair and bundled offline converter on Windows.
2. Call report_auth.check_sent directly after each transition (before and after pathology_recheck, new interaction note, pathology_result), and capture the exact ValueError category without patient content.
3. Compare report_status._reasons with the signed evidence; determine whether interaction change, source change or pathology revision separately causes stale authorisation.
4. Adjust the synthetic journey's assertions to expect unchanged bytes AND staleness of the earlier signed authorisation after new material clinical evidence; assert a later send is safely refused.
5. If the scenario requires a successful "sent" journey, add a separate path that builds a NEW report from current evidence, confirms current reconciliation/consent, signs that exact new DOCX/PDF pair, then marks that revision sent. Do not silently edit the old version or erase prior audit.
6. Add separate tests for no-change later-online refresh, change-after-sign and successful re-sign; ensure report_status wording does not confuse "files intact" with "clinical approval still current". Consider a separate non-authoritative output_integrity field rather than weakening signed_version_intact.
7. Re-run all source-drift and signed-report invariants, full backend suite, Windows standalone packaging and post-install smoke.

Exit: explicit tests prove file immutability, staleness on changed evidence, rejection of sending under stale authorisation, and successful newly reviewed send; Windows standalone workflow reaches and passes NSIS/package/installed-smoke stages. If product policy about re-sign is genuinely ambiguous, document it and use the more conservative behaviour; do not invent pharmacist consent.

## 3. MANDATORY READING ORDER BEFORE ANY WIDER CHANGE

Read these fully; check exact HEAD and PR discussion, not summaries or old local branches:

1. docs/qa/independent-full-flow-handover-2026-11-22.md on PR #40 - complete previous engineer's findings, commits and private inventory.
2. docs/qa/full-flow-real-case-acceptance-2026-11-22.md on PR #40 - case-by-case acceptance contract and scope.
3. PR #40 diff and comments; HMR Desk/engine/records.py, report_auth.py, clinical_snapshot.py, jobs.py, referral_entry.py, referral_geometry.py, interview.py, medicine_review.py, reconciliation.py, report.py, report_status.py, template_report_builder.py; desktop/renderer/interview.js, report-editor.js and navigation/autosave helpers.
4. handover/INTEGRATION-HANDOVER-2026-11-21.md, handover/ACCEPTANCE-SAFETY-REVIEW-2026-11-21.md and handover/SENIOR-REVIEW-PR32-2026-11-21.md. They document previous branch reconciliation, missing licensed helpers, Word COM and offline acceptance limits.
5. docs/m2/issues.md and docs/m2/evidence/index.md; read earlier original Milestone 2 Standalone Implementation Plan if authorised and available. Historical evidence is not automatically evidence on current HEAD.
6. PR #39's docs/pathology-pr39-detailed-engineering-handover-2026-11-22.md and its test/CI links. Never assume the unmerged experimental broader extractor was accepted.
7. Owner-authorised original Full Flow Real Data Online Agent Prompt (22 Nov), Pathology Online Agent Execution Plan, Real-World Pathology Audit, current registered owner report template and real source examples. If some private asset is unavailable, state explicitly which asset and what verification is blocked; do not substitute a guessed synthetic template and claim visual fidelity.

Historical PR #38 correction: manually entered slash-separated medicine lines in an earlier Windows test were not automatically emitted by the PDF parser. Do not resurrect that false root cause. Geometry pairing on the original synthetic PDF had worked; narrow PR #38 evidence applies only to its actual matched case.

## 4. WHOLE-FLOW ARCHITECTURE AND INVARIANTS

Production path:
original referral PDF -> referral_entry.review -> pharmacist-confirmed referral_entry.commit -> patient folder original source and source hash -> interview.load / interview.save -> confirmed actual medicine list + reconciliation digest -> pathname/verified pathology records -> report.start/save/refresh, held Actions -> jobs.report_build, template_report_builder, bundled offline pdf_export -> report_build event -> report_auth.check_approval -> signed_off event -> report_auth.check_sent -> report_sent event.

Interface:
Electron desktop renderer talks to authenticated local Python API. SQLCipher stores structured patient records keyed to the patient identity. The original PDFs, pathology PDFs, exported DOCX/PDF and some transitional files may be plaintext in the workspace; database encryption does not encrypt those files. Portal / MIMS / PPA helpers are optional or licensed and must never silently become prerequisites for the entire AI-off/manual offline path.

Safety invariants (reject a change that violates any):
- No mistaken patient/source association across imports, API endpoints, asynchronous UI, file opening, report build, backup or signed evidence. Zero wrong-patient incidents.
- Referral prescribed medicine name, ingredient/brand, strength, form, directions and source page stay independently reviewable. Patient actual-use dose is separate. Never turn "unknown" into "taking".
- Allergy "unknown" is different from explicit no-known-allergies. Condition missing from one reviewed field is not confirmed empty by review of another field.
- Pathology proposals are UNVERIFIED; actual verified results require dated, named pharmacist/source confirmation. Do not infer lab range, sample date, accession, diagnosis or therapeutic target.
- Editing pharmacist-authored SAMP findings, medicine Action text or table data cannot be silently lost on refresh, simultaneous save, failed build, crash or upgrade.
- Build and sign-off must fail closed on stale patient source, pathology evidence, interview revision, report spec, medicine reconciliation, original source files, held medicine Actions, missing approved template, altered Word/PDF and post-sign-off evidence changes.
- Signature and sent state are human-directed, not automatic. A status chip is not a clinical authorisation; reports are never transmitted or claimed during test runs.
- Offline AI-off operation is a supported first-class workflow without installed Python, Node, Word or separately installed LibreOffice on final Windows.
- No real patient content or licensed MIMS data in commits, Actions logs, fixtures, screenshot artifacts, prompts sent to outside AI or issue comments.

## 5. PHASED IMPLEMENTATION PLAN WITH DELIVERABLES AND STOP CONDITIONS

### Phase 0 - Re-baseline and CI recovery (P0)

Tasks: checkout existing PR #40; verify base/branch/diff, establish tested product-code commit; fix P0-A and P0-B; run all CI at exact code head; update PR handover with true status.
Deliverables: synthetic regression commits, green privacy/full backend/desktop/visual/Windows package and installed-smoke runs, precise report of test counts/skips/runner OS/build manifest.
Exit: no failing or unexplained skipped critical gate; no weakening security controls to appease outdated tests.

### Phase 1 - Private corpus and reproducible ground truth (P0)

Source: Chemist 11 Google Drive HMR Ongoing / Scheduled (23 case folders) and Visited / SEP-OCT / zzz Not sent to Islam (28 case folders). Previous direct-child inventory: 51 patient folders, 94 root PDFs, 114 root Word files, 59 images, 183 other files, 43 immediate subfolders, 41 dedicated Pathology subfolders. Separate earlier pathology-only audit counted 293 nested pathology PDFs (109 Scheduled and 184 Visited); do NOT add these into referral counts or call them all independent patients.

Read-only privately select >=12 development cases and >=8 never-used-before holdout cases, patient-separated (and avoid document duplicates from the same patient). Cover digital PDF, scan/text layer disagreement, ambiguous medicine table, multiple pages, handwriting, scanned rotations, different GP layouts, DOB/date ambiguity, duplicate name, OTC/ceased/PRN, DAA, pathology positive/negative and complex report revisions. Consent and confidentiality rules apply.

Build an encrypted/private ledger with random aliases, original SHA256/page count, actual referral date and original source page per field; independent pharmacist-reviewed gold labels from source page pixels, original text layer, OCR output, parser output, interview and final report. Preserve conflicting historical report versions separately; never match a document to another by similar filename alone. Only aggregate, de-identified counts may be shared in PR.
Exit: signed/reviewed source-annotation methodology, frozen holdout before tuning, case-by-case provenance; no clinical accuracy claimed yet.

### Phase 2 - Intake and identity fidelity (P0)

Execute production referral_entry.review -> commit using real original PDFs on a disposable authorised workspace with actual API. Verify:
identity name/sex/DOB/phone/address, clinic/GP provider and referral date; original bytes and hash; duplicate patient and same-name DOB checks; clinical review source_pages; scanned OCR/geometry and uncertain/unsupported layout fallback; source-page pixel crops and warnings. Test 1/2/5/15/50-page samples separately and report page processing time and failure reasons. Never infer that apparent text-layer spelling is correct if original PDF is image-heavy.

Success requires exact values where supported, explicit abstention elsewhere, no dropped medicine line or invented directions, no wrong patient, no false negative allergies. Do not hide false positives in a "parser recognised PDF" count.
Output: per-field source-to-intake diff, parser layout matrix and reproducible fictional regression for each real issue.

### Phase 3 - Interview and medicines (P0)

Go through the actual renderer as well as API: medicine names, strengths, formulations, exact prescribed directions, "actually taking", not using, stopped, OTC, PRN frequency, adverse reactions, missed doses, DAA, allergies, measurements, bowel/sleep/mobility/social circumstances. Check explicit source confirmation and manual changes.
Verify controlled autosaves, version token/expected_revision, stale two-window conflict, offline draft recovery, power loss, switch patient during async requests, source image/row review, note-preserving refresh, no accidental duplicate medicines.
Run medicine reconciliation acknowledgement against the exact current interview digest; changes must invalidate prior acknowledgement and any dependent report currency. Confirm the held Actions logic carries recommendations only for exactly matching unambiguous rows and preserves changed/duplicate text as held with a build block.
Output: original->parsed->UI->saved->reopened field-by-field matrix, focus/keyboard checks and no silent clinical text loss.

### Phase 4 - Pathology consumption, not parser duplication (P0/P1)

PR #39 owns extraction/OCR/therapeutic targets. Inspect its stable exact code and schema, then test PR #40's cross-module path without blind merges. Preserve source file hash, page/row bounding boxes, true sample date/time and accession, test/value/unit/printed lab interval, uncertainty, correction, provenance, unverified/verified status, revision conflict and patient identity. Distinguish current and historical samples, same-day accession duplicates, qualitative results and HbA1c alternative units. Show lab reference interval separately from individual therapeutic targets. Unsupported source or word-level OCR must abstain, not fabricate. Verified clinical data only enters reports under existing validated policies.

PR #39's older 36-original PDF pilot measured parser recognition/proposals, NOT test-level clinical accuracy: strict starting parser 0/36; bounded 5/36, 159 proposals; experimental wider variant 22/36, 265 proposals with unsafe associations, not merged. Do not use those as per-field precision scores.
Output: contract/integration test and private per-lab pixel-linked proposal/acceptance scorecard, coordinated with PR #39 owner. Any feature contract change requires cross-PR CI and separate review.

### Phase 5 - Source-to-report clinical and template fidelity (P0)

Use the currently approved owner DOCX and recorded SHA/version, not a visually similar sample. Check:
- Patient/GP/pharmacist details, referral and report dates, contact/provider information.
- Brief professional patient introduction in the owner's accepted style without unsupported diagnoses or treatment claims; relevant sleep, bowel and mobility observations.
- Current conditions and allergies accurately qualified.
- Medicines table: actual dose as reported, comments, pharmacist recommendations; optional GP Plan fifth column remains blank unless a human explicitly enters it. Check default GP Plan OFF and enabled ON, old four-column records and compatibility with the opt-in original Word builder.
- Separate currently used, not used/ceased and OTC medicines.
- Pharmacist-authored SAMP findings in one issue paragraph each, with reason, evidence, action and limitations; no automatic overwriting by optional AI or template suggestions.
- Pathology table includes collection date, value, unit, printed interval and safe interpretation; no wrong sample date/column or unsupported result.
- Correct closing, version, MBS wording if template policy requires it; no blank trailing page, clipped tables or duplicated footer/signature.

Inspect docx paragraph/table XML and rendered PDF page images; compare 100% of relevant clinical table cells to current reviewed record, and compare short, long, multi-page, difficult punctuation and scale 125/150% layouts. Visual comparison against owner-approved examples requires human review, not text overlap percentages. Word COM original builder remains opt-in and a separate host-specific test; the default standalone renderer must operate without Word.
Output: source->saved report->DOCX cell->PDF pixel mapping and named template SHA, screenshots only for synthetic cases in CI.

### Phase 6 - Security, migration, privacy and resilience (P0)

Threats: linked files and NTFS reparse paths, TOCTOU file swap, path traversal and archive/backup restore, document symlinks, cross-patient API ID denial, stale token, localhost auth, unsafe Electron IPC, secondary windows, plaintext patient PDFs, unencrypted exports, missing PHI-safe log redact, temporary folders, crashes, external AI traffic while AI-OFF.
Exercise a disposable copy of an older encrypted workspace: schema v1->v2, restore/backup checksums, held recommendation record, versioned snapshot contracts 1/2/3, template versions, crash rollback, hard-kill during save and disk-full. Test zero secret/PHI exfiltration in offline mode and no change to original source on failure.

Use file-handle/no-follow protections and Windows reparse checks for hostile filesystem cases where feasible; current _linked_component check is not fully race-safe. Do not delete the only copy of any clinical record. A failed migration should be reported and remain recoverable.
Output: threat matrix with mitigations, adversarial synthetic tests, data-retention and rollback evidence.

### Phase 7 - Real Windows 11 non-admin installed workflow (P0)

On a clean Windows 11 x64 standard-user profile, use an exact Git SHA installer with manifest and SHA256. Disconnect internet; ensure no installed developer Python/Node/Word/LibreOffice. Install -> open -> import fictional searchable AND scanned referral -> source preview/correction -> interview and medicine reconciliation -> manual verified pathology -> manually written findings -> standalone DOCX/PDF -> close/reopen -> signoff (fictional consent/test) -> integrity check -> backup/restore -> upgrade/rollback. Exercise window widths, 125/150% scaling, keyboard-only interactions, slow/offline/error/denied states.

Record synthetic-only screenshots/video, step outcome, environment, app/engine version, original PDF hash, generated DOCX/PDF hashes, service recovery, PASS/FAIL and exact path to reproducible fixtures. Do not infer Windows 11 user acceptance from a Windows Server hosted CI runner. Signed installer or deployment is a separately authorised release decision.

### Phase 8 - Private clinical acceptance and release dossier (P0)

After engineering regressions and real-source benchmarks, an accredited pharmacist independently reviews field-by-field source truth, medication discrepancies, pathology units/dates, recommendation preservation, reporting style and clinical appropriateness. Record sample counts, false-positive/false-negative, abstentions, severity, reviewer, date, unresolved cases and approvals in a secure non-public ledger. Acceptance thresholds for clinical errors must be explicitly agreed; zero wrong-patient data, zero silent source-field substitution, zero automatic false verification and zero undetected signed-file tampering are non-negotiable invariants.
Only then present a release recommendation. Keep PR Draft and release HOLD until owner expressly approves; green CI alone is insufficient.

## 6. CROSS-LAYER ACCEPTANCE MATRIX (ALL REQUIRED)

| ID | Gate | Required proving action | Outcome now |
| --- | --- | --- | --- |
| G00 | Latest exact-head CI | Full backend, desktop, visual, privacy, Windows package and installed smoke | OPEN: privacy and Windows package fail |
| G01 | Original referral identity | Original PDF pixel to committed patient fields, all cases, duplicates | OPEN |
| G02 | Medicine names and directions | Name/strength/form/directions original -> interview -> reopen | OPEN |
| G03 | Actual use and PRN | Taking vs not using vs OTC, clinician confirmation | OPEN |
| G04 | Allergy and source-state semantics | Unknown vs explicit none; contract 1/2/3 continuity | PARTIAL code, original cases open |
| G05 | Pathology provenance | Exact date/accession/unit/value/lab range, source boxes, abstention | PR #39 ongoing; integration open |
| G06 | Autosave and conflict | Multiwindow, patient switch, crash, revision stale and recovery | PARTIAL synthetic; native open |
| G07 | Pharmacist recommendation preservation | Held Actions on changed/duplicate rows, no silent loss | PARTIAL synthetic; native open |
| G08 | Report layout | Actual approved DOCX/PDF and optional blank GP Plan | OPEN |
| G09 | Interaction and sign-off integrity | Change after sign-off blocks send; rebuild/re-sign works | NEW invariant, failing old synthetic journey |
| G10 | Privacy/PHI/backup | No wrong-patient reads, sources/logs, encrypted DB/backup | PARTIAL; Linux CI teardown failing |
| G11 | Windows installed app | Non-admin Windows 11, fully offline, no dev tools, restart | OPEN |
| G12 | Clinical acceptance | Held-out source-pixel review and pharmacist decision | OPEN |

Mark an item PASS only with code SHA + exact test/protocol + source denominator and reviewer + link to deidentified evidence. Test count alone is insufficient.

## 7. REPRODUCIBLE TEST COMMANDS AND OPERATING RULES

From repository root on a supported Python 3.12 development environment:

~~~text
cd "HMR Desk/engine"
python -m pytest -q test_legacy_import_link_isolation.py test_records.py
python -m pytest -q test_signed_interaction_evidence_freshness.py test_report_auth.py test_report_status.py test_synthetic_patient_journey.py
python -m pytest -q test_snapshot_field_review_contract.py test_snapshot_contract_compat.py test_clinical_snapshot.py test_build_snapshot.py
python -m pytest -q test_clinical_privacy.py test_service_static_security.py test_manual_foundation.py
python -m pytest -q
cd ../../desktop
npm ci
npm test
~~~

Commands may require the repository's pinned dependencies, platform setup or bundled PDF converter. Do not hide missing requirements with unchecked skips. Use the Windows package CI job for the real offline-converter path, and the separate Linux privacy job. Read .github/workflows for authoritative commands and test selection. CI on GitHub is more reliable than asserting local success without a checked-out repository.

Every defect work unit:
1. Produce a failing synthetic regression that exercises the real code path.
2. Identify and document exact precondition, state, expected vs observed and clinical risk.
3. Make the narrowest safe implementation fix.
4. Re-run focused tests, full backend, desktop/visual, privacy and Windows standalone when affected.
5. Inspect output artifacts or real original source pixels where relevant.
6. Push one small reviewable commit, include acceptance evidence and updated status. No broad unexplained parser refactor.
7. Re-check the head commit's Actions, not an older green ancestor.
8. Never make actual patient data a GitHub fixture.

CI labels: PASSED; FAILED; SKIPPED (with explicit reason); NOT RUN; REQUIRES HOST; REQUIRES PHARMACIST. Never replace these with a single vague "done".

## 8. PRIVATE EVALUATION LEDGER FORMAT

Keep the private source map encrypted and inaccessible outside the authorised workspace. An example SCHEMA ONLY, no patient values:

~~~text
case_alias: random non-identifiable ID
source_pdf_sha256: <private>
source_kind: referral/pathology/notes
page_count, lab_layout, source_version, report_version: <private>
source_cell: {page, bounding_box, row, column, collection_date, accession}
gold: {field, original_text, canonical_value, units, printed_interval, explicit_unknown}
automatic: {raw_text, raw_value, parser_status, proposal_id, confidence_or_abstained}
ui: {reviewer_correction, source_page, confirmed_or_unverified, saved_revision}
report: {docx_field_cell, pdf_page_region, exact_match, discrepancy_severity}
decision: {pass, fail, abstain, unsupported, clinical_review_required}
evidence: {test_commit, timestamp, tool_version, reviewer, independent_holdout}
~~~

Report aggregate-only scorecards:
- Cases attempted / cases reviewed / held-out cases; PDFs/pages eligible.
- Source fields counted; exact matches and mismatch denominator by identity, each medicine subfield, allergy, conditions, each pathology subfield, each report output cell.
- False positives, false negatives, duplicate/missed rows, wrong-patient/source leaks, unreviewed text, incorrect units/date/accessions, unsupported/abstained cells.
- Clinical severity of each discrepancy, correction path, test gate and final disposition.
- Per-lab family and document category; never substitute proposal/document coverage for result-cell accuracy.

## 9. PR #39 COORDINATION / RELEASE CONFLICT CONTROL

PR #39 is a separate specialised pipeline with its own architecture and acceptance gates. Its handover identifies unresolved source-cell identity across extractor versions, sample accession/time/method provenance, low-quality scanned OCR, split scientific units, broader QML/Sonic/4Cyte/Pathology Queensland layouts and clinically unsafe target inference. PR #40 should test consuming a stable unverified proposal/verified record interface, not silently incorporate unmerged parser code.

Before integration: compare full diffs and common base, identify overlapping files/routes, choose a reviewed integration branch only after both own focused tests pass, and run production API + Electron + exact private holdout after combination. Do not copy any private patient source or licensed reference into a branch. Preserve manual entry if pathology parser is unavailable.

## 10. HIGH-RISK EDGE AND NEGATIVE TEST SUITE (REQUIRED)

- A PDF contains names and directions in different column-order text, or an OCR text layer misreads one name; original pixel differs. Flag uncertainty, never assert confidence from same-row text match alone.
- Two patients have same first/last name; DOB strings in different formats. No wrong-person merge; duplicate review explicit.
- Referral source changes while intake OCR is in progress; original hash check refuses stale data.
- Patient B opens while patient A pathology reload/observation/request is in flight; late results/errors never display for B.
- Same medicine name appears twice, one ceased, one taking, with different strengths. Action carry and interaction scope do not conflate them.
- User types a note while save is running; response must not overwrite new text. Reopen after crash must preserve unresolved draft.
- Archived signed report Word/PDF bytes remain unchanged if later pathology or interaction evidence arrives; send is blocked if approval stale.
- Signed source changes, PDF missing, template hash changes, GP demographics change, held Action unresolved: sign-off/sent fail closed.
- 24-hour medication exposure vs intended maximum is never computed by silently treating PRN as regular or inferring actual administration.
- Pathology cumulative columns have 2-5 dates, repeated specimen date with different accessions, corrected vs uncorrected calcium, HbA1c alternative units, FBC flag vs result, lab reference vs target. Never bind wrong cell or assert normality from a guess.
- Image-only scanned PDF with no word geometry returns explicit unavailable/needs manual verification.
- The approved template has a blank GP Plan field; rendering and refresh do not fill it from suggestions.
- Migration sees linked parent, linked leaf, changing link target, native Windows junction/reparse, low disk and locked copy; never retire files prematurely.
- Localhost API/IPC wrong patient ID/path traversal, PDF opening, network offline and manual-not-sent outcome are verified as negative cases.
- Clean Windows user account has no Python, Node, Word or independently installed LibreOffice and app still completes manual path.

## 11. REQUIRED NEXT-AGENT PR AND COMMIT HANDOVER FORMAT

Create/append a dated handover in PR #40 using the following fields, with evidence rather than narration:

~~~text
HMR DESK / PR #40 - CHECKPOINT
Timestamp / timezone:
Working branch / base / product-code HEAD:
PR #39 latest head (read-only integration awareness):
Changes made: [file, reason, regression and commit SHA]
Failure reproduced before fix: [scenario and failure evidence]
Post-fix unit/API/renderer tests: [run URL, pass/fail/skip]
Privacy CI: [run URL, test count, environment]
Windows standalone CI and installer: [run URL, step reached, hash]
Private source evaluation: [cases, eligible fields, exact matches,
  mismatches, abstentions, source-pixel evidence held privately]
DOCX/PDF: [template version/hash, short/long output, visual reviewer]
Safety and compatibility: [contracts 1/2/3, legacy reports, patient isolation]
What remains FAIL/OPEN: [severity, reproducible next action, owner]
Release: HOLD or explicitly approved by owner after pharmacist gates
No PHI/secret/licensed content shared: yes/no
~~~

Escalate only truly external dependencies: explicit owner template choice or clinical policy, physical Windows 11 host/access, portal authentication, proprietary helper entitlement, accredited pharmacist source-pixel adjudication and release approval. Do not present a test defect, missing import, stale assertion or misconfigured CI as an unavoidable owner dependency.

## 12. ROLLBACK AND DO-NOT-DO LIST

- Do NOT merge PR #40/39 into main, publish an installer for clinical use, perform live claims, transmit patient reports or overwrite existing real patient files.
- Do NOT fix a test by disabling check_sent, skipping privacy checks or weakening original-source review. Avoid "green by exclusion".
- Do NOT ship a broad experimental pathology extractor as if 22/36 recognised PDFs means accuracy.
- Do NOT silently rewrite signed contract 1/2 evidence; new build contract 3 must be additive/compatible.
- Do NOT assume Word COM works or registered template is aesthetically/clinically approved just because a synthetic DOCX has the right text.
- Do NOT allow a newer reporter/assistant to replace a pharmacist's manually typed recommendations.
- Do NOT expose PHI, credentials or proprietary helper scripts to CI, GitHub, external OCR or cloud AI.
- For faulty changes, revert only the relevant new commit after comparing current heads and respecting another agent's active PR; no force push or broad reset. Keep original encrypted backup, source PDFs and immutable signed reports.

## 13. DEFINITION OF COMPLETED MISSION

The mission is complete ONLY when all of the following have named evidence at the same code/installer SHA:
- All current PR #40 CI jobs green without ignored critical failures: privacy Linux, whole Windows Python, Electron, visual, frozen engine and offline converter, NSIS/package and installed smoke.
- Production real intake and UI interview paths checked against originals; >=12 development and >=8 untouched patient-separated holdout cases privately adjudicated, each with source-page truth and report tracing.
- Source, medicine and pathology high-risk field errors fully reconciled or explicitly safely abstained; no wrong patient, no fabricated verification or invisible clinical text loss.
- Both existing and new report contracts remain version-compatible; changed evidence after signing is handled by auditable re-review/re-sign, not erased.
- Owner-approved DOCX and converted PDF short/long layouts and exact clinical cells visually checked with template SHA and qualified reviewers.
- Clean Windows 11 x64 standard-user OFFLINE full manual path proven, including restart, migration/restore/recovery and no developer runtime dependency.
- Security/PHI and licensed-material review complete; pharmacist clinical acceptance recorded; owner approves promotion.
- A final handover states exact tests, counts, hashes, errors, artifacts, remaining risks, version and release decision.

If external clinical acceptance is unavailable, complete all engineering work possible and mark only the external acceptance gate BLOCKED, leaving PR Draft and release HOLD. Do not claim DONE or ask the owner to re-explain already documented requirements.

**Current truthful conclusion at this handover:** backend/desktop/visual synthetic gates passed on code SHA 3275356c; Linux privacy and Windows synthetic journey/packaging gates FAILED. No original-source end-to-end clinical field accuracy, clean Windows 11 non-admin installation, owner-template visual fidelity or pharmacist clinical acceptance has been established. Release HOLD.
