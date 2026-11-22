# Integration candidate checkpoint, 22 November 2026

Draft engineering work only. Do not merge to main, release a production build, or treat this as clinical approval.

## Exact checkpoints

- Current code commit: `a579f3cce10921e8fe5246b1109d28197d0d9f9c`.
- Current draft integration PR: https://github.com/chemisttasker11-ezy/hmr-desk/pull/35
- Integration branch: `integration/hmr-combined-nov21`.
- Frozen current-code checkpoint: `integration/hmr-reviewed-nov22-v8`.
- Previous Windows simulation checkpoint: `integration/hmr-v7-acceptance-nov22` at `bdc6496e83b10c6b51f3500148fd304f6b872471`.
- This document is a later documentation-only commit. Test/build counts below belong to the current code commit above, not a claim that all tests were rerun on a later docs SHA.

## What was combined

The earlier integrated clinical safeguards and optional original Word-builder work are retained. The historical divergent M2 tree was not substituted. Subsequent Windows-driven fixes include medicine intake fidelity, narrow interview layouts, current-record action labels, report readiness and medicine reason edits, explicit conservative duplicate-entry confirmation with retained lapsed audit metadata, and the two latest corrections below.

1. Report pagination: keep the final content block, spacer, closing and pharmacist line together. Text, provisional labels and simulation labels are unchanged. This responds to a Windows simulation report whose pharmacist line was alone on the last page. Linux synthetic render evidence is not Windows proof. New Windows rerender remains pending at this checkpoint.
2. Interview display freshness: on focus/visibility, read saved data. A clean stale form reloads; a dirty form preserves its draft and uses the existing explicit conflict choice. No auto-save, auto-merge, or weakening of revision protection. Real-window wiring remains pending at this checkpoint.

## Current-code automated/build evidence

Native Windows, focused engine regression command:

```text
python -m pytest -q test_duplicate_confirmation.py test_interview.py test_job_readiness.py test_api.py test_manual_workflow.py test_report_save_revision.py test_route_ownership.py test_interaction_scope.py test_original_builder_jobs.py test_medicine_snapshot.py test_report.py test_local_report_style.py
```

Result: 196 passed, 2 skipped, 5 warnings. This is a focused suite, not the entire backend suite.

Desktop: `npm test`, 560 tests, 548 passed, 12 skipped, 0 failed.

PyInstaller engine build and Brainstorm asset verification passed. Desktop installer packaging was still running when this document was written. A package being built or generated does not prove installed acceptance.

The private MIMS list generator was locally hash-verified and excluded by Git ignore. It is not in this repository. Private clinical references, licensed medicine data, patient workspaces, generated clinical reports, credentials and installer binaries are not part of this code publication. A clean clone therefore still requires the documented private-asset setup; local overlay success is not a claim of clean-clone reproducibility.

## Actual Windows simulation evidence on the previous v7 code

- Local historical worked-answer simulations used private copies, not new clinical consultations.
- A second simulation saved/reopened interview and report data, generated DOCX and PDF, and all six PDF pages were visually inspected. A closing-line pagination defect was found, not accepted as finished polish. Six structured pathology rows were manually checked against original sources and carried into the report. Current and historical dates and total versus corrected results were kept distinct.
- Actual duplicate UI: matching same-strength target offered; different strength excluded; explicit target selection and checkbox required; save/reopen retained link and note, three rows and all medicine-use statuses were unchanged. Editing the confirmed row identity marked the link lapsed for audit; restoring the old identity did not reactivate confirmation.
- These are portable runs on a developer-equipped Windows account. USERPROFILE isolation is not a separate standard-user or clean machine.

## Important gaps, do not convert these into pass claims

- No full ten-case acceptance completion.
- New code's Windows pagination rerender and clean/dirty real-window freshness checks pending.
- Current candidate not yet installed and verified under a separate standard non-administrator Windows account without developer tools.
- Full offline/Word-free installed flow, migration/backup/recovery/restart and all sign-off gates need exact-candidate evidence.
- Owner-approved report-template acceptance and separate optional original Word automation remain unproved. Provisional local output is not owner approval.
- Current embedded eMIMS tab is logged out, with no saved sign-in in the isolated profile. The helper has not completed a live interaction list/check/result round trip in these two case runs. Historical manual notes, separate-browser login, packaged files and mocked tests do not prove that path. Do not loosen unique exact medicine matching or result/list hash checks to obtain a pass.
- No live My Health Record/PPA helper workflow or AMH button-to-monograph acceptance in these case runs. PRODA sign-in is the owner's own step. Do not auto-tick consent, submit claims, transmit reports or sign as the owner.
- Pathology PDF import currently stores source/text and supports manually entered source-linked rows. It does not auto-fill results, units, date columns or ranges, and has no pathology OCR/table extractor. The manual simulation is not extraction-accuracy evidence.
- Future pathology proposals must remain separate and unverified, preserve source page/cell evidence and longitudinal dates, and require pharmacist confirmation. Do not feed proposals into clinical suggestions, reports or external AI. The present external AI projection uses legacy pathology rows and needs its own verified-only/privacy review before any new structured proposal pathway.
- Small/tiny local AI helpers remain parked. No external AI activation or clinical benefit is established by configurable agent settings.

## Publication and next work

Before publication, the new source diff was checked for sensitive/binary paths and the 71 unpublished history blobs (1,859,896 bytes) were scanned for strong secret/binary signatures. Private local helper exclusion was confirmed. This audit is scoped evidence, not a claim that any automated scan can prove absence of all private information.

Continue from the frozen code checkpoint, use synthetic fixtures in GitHub only, preserve private source cases locally, and compare against the owner's separate working app before choosing any merge. Do not operate that separate working machine merely to reproduce this candidate. A comprehensive whole-project handover and a pathology-autofill implementation prompt are being prepared separately; this file is the exact current integration checkpoint, not a replacement for full project history.
