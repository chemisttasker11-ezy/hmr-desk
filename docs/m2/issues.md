# Milestone 2 — issue register (Wave 0)

Updated 2026-11-16. Statuses refer to verified baseline `860a3b689a3c19ea9594969c0410721f9a52891f` except the targeted identity fix committed afterward. This is **not** release approval.

Severity: **P0** blocks standalone clinical release or may risk patient records; **P1** blocks a required workflow/fidelity/privacy acceptance scenario; **P2** is lower-priority polish, instrumentation or non-essential improvement. Close only with a reproducible test, exact commit and evidence link.

| ID | Severity | Problem / reproduction | Owner / fix | Required closure evidence | Status |
| --- | --- | --- | --- | --- | --- |
| M2-I01 | P0 | No approved editable HMR Word template, nor short/long exemplar documents. Current `local_report_builder.py` uses a generic new Word document. | Owner provides assets; engineer maps template; pharmacist visually reviews | Approved DOCX and 2 comparison reports; exact short/long DOCX + PDF page checks and owner sign-off | BLOCKED (ASSET) |
| M2-I02 | P0 | No clean Windows 11 x64 non-admin standalone install/offline HMR E2E; Windows Server 2022 CI smoke is insufficient. | QA/release engineer | Machine manifest, video/screenshots synthetic only, offline workflow logs, pass/fail matrix, installer SHA-256 | OPEN |
| M2-I03 | P0 | Existing OneDrive/legacy data lacks guided inventoried, backed-up, checked, atomic activation and rollback migration. | Data/storage engineer | Historical workspace fixture, interrupt/duplicate/read-only/full-disk tests, byte-level before/after checks | OPEN |
| M2-I04 | P0 | `db.connect` performs additive schema changes at startup without versioned migration contract/rollback acceptance. | Database engineer | Versioned migration journal, transactional tests, historical fixtures, crash recovery | OPEN |
| M2-I05 | P1 | Intake text snippets cannot substitute for original-page image preview and complete claim source linkage; scanned/rotated/OCR and damaged PDFs under-tested. | Intake engineer | Synthetic source-image review, OCR languages/rotation, limits, uncertainty and duplicate E2E | OPEN |
| M2-I06 | P1 | Same-name patient matching used an incorrectly escaped non-digit regex, risking missed matches when identifier formatting differs. | Intake engineer | `test_referral_identity.py` formatted-number regression plus PR-head CI | FIX COMMITTED / CI PENDING |
| M2-I07 | P1 | Reconciliation/pathology still require persisted UI whole-case, conflict and stale derived-output validation. | Clinical workflow engineer | End-to-end actual-use/OTC/ceased/PRN, dated units, source, edit/invalidation tests | OPEN |
| M2-I08 | P1 | Backup/restore tested synthetically but Windows ACL/DPAPI, complete scope, true recovery activation and concurrent writers not accepted. | Storage/security engineer | Off-device and cross-user synthetic restore, corrupted archive, power-loss, permissions audit | OPEN |
| M2-I09 | P1 | Operational data in local workspace/database relies on NTFS permissions and device encryption, not per-file encryption; no real Windows ACL audit. | Security engineer | Standard Windows user ACL evidence, PHI-free log scan, penetration/local HTTP tests | OPEN |
| M2-I10 | P1 | No owner/pharmacist acceptance or formal security/release sign-off; unsigned engineering artifact is not clinical release. | Owner / clinical reviewer / release engineer | Signed checklist, SHA, approved reports, PR review and no P0/P1 defects | OPEN |
| M2-I11 | P1 | Offline bundled PDF conversion validated on generic DOCX only, not long/short HMR layout on a clean Windows 11 host. | Report engineer | Template-bound DOCX and PDF cross-page comparison with fonts | OPEN |
| M2-I12 | P1 | Multiple instances, stale config, late startup failure, lock contention and hard-kill mid-save lack complete installed-app checks. | Desktop engineer | Fault matrix, restart/uninstall/upgrade logs and no orphan processes | OPEN |
| M2-I13 | P2 | Engineering artifact expires after 7 days; installer SHA-256 and release provenance not yet durably recorded. | Release engineer | Downloaded EXE checksum, manifest, versions, archived evidence index | OPEN |
| M2-I14 | P2 | Build uses direct requirements and npm lockfile, but complete immutable hashes and licensing for converter and dependencies need release review. | Release/security engineer | Dependency/SBOM version manifest, hashes and redistribution notices | OPEN |

## Execution order

1. Lock baseline and evidence, regenerate acceptance matrix and dependency map (Wave 0).
2. Protect migration/versions and identity correctness, then complete intake/OCR/source validation (Wave 1).
3. Finish canonical interview/pathology and invalidation, with reviewed UI E2E (Wave 2).
4. Map exact owner template and report PDF, preserve signoff/history (Wave 3; template dependent).
5. Exercise packaged offline workflow and backup disaster recovery on non-admin Windows 11, sign and accept (Wave 4).

Do not implement shortcuts that auto-confirm extracted allergies, medicines or pathology. Follow the owner/pharmacist consent boundary and retain original files and clinical decisions.
