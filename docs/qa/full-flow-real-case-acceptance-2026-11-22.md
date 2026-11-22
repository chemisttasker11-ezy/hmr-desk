# HMR Desk — Independent whole-flow acceptance, 22 November 2026

**Branch:** `qa/full-flow-source-report-20261122`  
**Baseline:** `integration/hmr-reviewed-nov22-v8` @ `a579f3cce10921e8fe5246b1109d28197d0d9f9c`  
**PR #39:** `feature/pathology-evidence-and-targets-nov22` — separate extraction/target owner; not incorporated.  
**Release:** HOLD. This branch is engineering work only, not clinical validation.

## Baseline evidence and limitations

- The owner's independently supplied historical corpus inventory comprises **51 case folders** (23 Scheduled, 28 Visited), **41 dedicated pathology folders**, **293 pathology PDFs**. These numbers are *prior audit findings*, not a fresh verified extraction score.
- The pathology pilot inspected 36 real PDFs / 37 pages. Initial strict parser 0/36 documents, bounded PR #39 logic replica 5/36 and 159 **proposed** rows, unsafe experimental parser 22/36 and 265 **proposed** rows. No scanned OCR performance quantified. Proposals are **not** field accuracy.
- This independent PR has no new private pixel-annotated source-to-final-report adjudications yet. No claim of 12 development cases or 8 held-out cases passed.
- The application stores structured records in SQLCipher; original PDFs and exported DOCX/PDF can remain plaintext. The latter must not be treated as encrypted data.
- Current work is a narrow safety correction for legacy import links and fictional tests. It does *not* prove the whole flow.

## Verified engineering risk in source review

### Legacy migration cross-patient link ingestion — security, stop-ship when exploited

Before this change `records.import_folder` enumerated linked `interview.json` paths and `records.import_file` accepted an arbitrary path satisfying `is_file()`, both following links through `read_bytes()`. The import is then written under the target `patient_id`, so links can cross a patient boundary during legacy migration. Real patient files were **not** used to reproduce this risk.

Fix: reject symlink leaves **and symlink path components** before opening legacy input files in both entry points. Fictional synthetic tests exercise regular import, a mocked symlink on non-privileged Windows, a real linked file and a linked parent. This fix does not purport to solve hostile path replacement races between the check and subsequent file open; race-hardening needs additional platform-specific file-handle protections and Windows verification.

**Test commands (synthetic only):**
```text
cd "HMR Desk/engine"
python -m pytest -q test_legacy_import_link_isolation.py test_records.py
python -m pytest -q
cd ../../desktop
npm ci
npm test
```

## Case-by-case acceptance flow (pending independent measurement)

1. Private read-only Drive inventory and original-byte acquisition. No PHI enters repository, Actions, PRs, screenshots, attachments, or external OCR/AI tools.
2. Identity match; referral PDF page/pixel and OCR-box exact comparisons; confirmed source text unchanged; source hash and original retained.
3. Prescribed medicine **name, strength, form, original directions** independent from actual patient dose, PRN, OTC, ceased, and allergies.
4. UI confirmation, interview save, navigation, process restart, reload and exact field diff; protect stale revisions, unsaved edits, duplicates and cross-patient access.
5. Pathology import through stable PR #39 integration only; otherwise unverified manual entry + original-page check. Lab interval distinct from conditional therapeutic target; same-day accessions distinguished.
6. AI-OFF SAMP authored by pharmacist; AI suggestions optional, explicit consent; never overwrite authored text or auto-verify source.
7. Report source-to-cell tracing, pharmacist-edited findings preserved, GP plan blank unless explicitly entered, DOCX/PDF exported and reopened. Compare against approved template and the source, not just a historical report.
8. Clean Windows 11 x64 non-admin offline installer run without developer tools, supported OCR and converter, followed by PDF page visual and save/reopen confirmation.

## Measurement and release gates

| Gate | State | Required evidence |
| --- | --- | --- |
| Corpus case isolation / source trace | RED — open | Real case-by-case original PDF field truth and patient-ID cross-check; 0 wrong-patient incidents |
| Intake / interview exact fidelity | RED — open | At least 12 private adjudicated representative cases + 8 patient-separated holdouts; original→UI→reopen diff |
| Clinical pathology | RED — open | Per-field values, units, interval/date/accession, provenance, abstention; PR #39 source-pixel acceptance |
| Report and GP plan | RED — open | Current approved template mapped and final DOCX/PDF cells/pixels reconciled with saved reviewed records |
| AI-OFF completeness / pharmacist authority | RED — open | Complete native UI execution offline; authored-text persistence; stale review invalidation |
| Security and PHI | YELLOW — partial | Link import guard added; all other endpoints, malicious races, output logs and plaintext artifacts still need audit |
| Windows clean non-admin install | RED — open | Standalone installed native offline workflow, including bundled OCR/converter and restart |
| Accredited pharmacist clinical sign-off | RED — open | Clinician reviews private gold standard, unresolved critical defects and report outputs |

## Public-safe evidence bookkeeping

Only record counts, error categories, fictional defects and CI SHA/run URLs in GitHub. Patient-level IDs, original filenames, pathology results, source screenshots and correspondence remain in a private, separately secured evaluation log.

Metrics must include numerators and denominators: case count, field-exact-match per stage, false-positive/false-negative results, abstentions, changed directions, patient conflicts, save/reopen mismatches, wrong-unit/date incidents, report cell mismatches, AI overwrite attempts, and actual UI/offline build proof.

## Coordination and remaining work

- **This branch:** legacy importer, app-level isolation; future intake/interview and report persistence validations, tested production routes and desktop screens.
- **PR #39:** pathology parser, source row geometry, OCR adapters, clinical targets. Consume only stable schema documented with the pathology owner.
- **Integration:** review both PRs separately, then run combined synthetic and private real-case holdout evidence, Windows clean install, and accredited pharmacist sign-off. Do not merge experimental parser or imply Windows cloud CI equals installed app.
- **Known unresolved risk:** filesystem path check cannot prevent a deliberately hostile race between `is_symlink` and `read_bytes`. Future improvement should use file-descriptor based no-follow semantics where available, Windows reparse-point protection, plus independent security tests.
