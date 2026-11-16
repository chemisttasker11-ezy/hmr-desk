# Milestone 2 acceptance matrix — standalone manual HMR

Updated: 2026-11-16 (Australia/Brisbane). PR: https://github.com/chemisttasker11-ezy/hmr-desk/pull/1 (draft). Branch: `security/clinical-agent-privacy-boundary`.

## Baseline and evidence discipline

**Last fully passing baseline:** `860a3b689a3c19ea9594969c0410721f9a52891f`. The head has subsequently changed through targeted Wave 0 hardening commits. **Do not transplant green CI statuses to the new head.** Re-run both workflows and record results at the new SHA.

- [Windows standalone engineering run](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43796030183): SUCCESS at baseline SHA. Windows Server 2022 runner; frozen engine auth smoke; packaged desktop process/crash smoke; bundled LibreOffice real synthetic DOCX-to-PDF smoke; NSIS packaging; Electron unit tests (204 reported by reviewer).
- [Clinical privacy contract run](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43796030164): SUCCESS at baseline SHA.
- Engineering artifact ID `14193659931`, name `hmr-m2-windows-unsigned-engineering-build`, ZIP reported size `530385241` bytes; GitHub artifact digest `sha256:05d049100ed086c09b560e7bc8f7e8f25f424cadaea252fd9f96b056793a8abe`; expires 2026-11-23 03:14:20 UTC. The artifact digest is **not** proof of the EXE's SHA-256. An installer checksum must be computed separately after download.
- Current runtime package: desktop version `0.1.0`; Windows workflow uses Python 3.12 and Node 22; `requirements.txt` pins PyMuPDF 1.26.5, openpyxl 3.1.5, python-docx 1.2.0, cryptography 46.0.3; `requirements-build.txt` pins PyInstaller 6.16.0 and pytest 8.4.2. Lockfile in `desktop/package-lock.json`; supply-chain integrity and full machine inventory remain open.
- No approved editable HMR report DOCX or two owner-approved short/long report references in reviewed repository tree. `brainstorm V2.0.pdf` is a writing/clinical reference, **not** an approved Word layout. Its medication guidance must not be converted to automated prescribing rules without verification.

**Status labels:** CI VERIFIED (specified baseline checks only); BUILT / NEEDS E2E; PARTIAL; BLOCKED (ASSET); NOT ACCEPTED. No inferred PASS from source-file existence.

| Gate | Current status | Evidence at verified baseline | Outstanding acceptance |
| --- | --- | --- | --- |
| M2-00 Inventory, synthetic fixtures | BUILT / NEEDS E2E | Inventory, fixture register, synthetic regressions in repo | Fresh inventory, complete fixture provenance and scenario runs |
| M2-01 Bundled engine, secure lifecycle | CI VERIFIED (smoke only) | PyInstaller frozen engine, authenticated health, crash recovery, packaged smoke | True clean Windows 11 x64 VM, standard user, ACLs, upgrades, migration, failure matrix |
| M2-02 Offline referral extraction/confirmation | PARTIAL | PyMuPDF, WinRT OCR path, source hash, field review/duplicate candidate flow | Packaged OCR, rotated/scanned/mixed fixtures, source-page image preview, complete provenance |
| M2-03 Actual-use reconciliation, pathology | BUILT / NEEDS E2E | Review persistence and invalidation, pathology API/UI, synthetic tests | Whole-case UI, legacy adapters, conflict handling, stale downstream checks |
| M2-04A Approved template DOCX | BLOCKED (ASSET) | Generic `local_report_builder.py` still uses a new document | Owner-approved DOCX + signed-off short and long examples, visual/clinical checks |
| M2-04B Bundled PDF export | CI VERIFIED (generic DOCX only) | Checksum-verified portable LibreOffice, actual synthetic conversion | Exact HMR fidelity, long case, fonts, isolated Windows 11 non-admin run |
| M2-05 Full manual UI | PARTIAL | Intake, interview, reconciliation, pathology, backup Settings surfaces | Real packaged screen-to-screen offline workflow, preview, accessibility |
| M2-06 Backup, privacy, migration | BUILT / NEEDS E2E for backup; PARTIAL for migration | AES-GCM encrypted workspace/SQLite archive, isolated restore, privacy CI | Backup scope, concurrent edit, real Windows DPAPI/ACL, schema migrations, rollback/restore activation |
| M2-07 Windows standalone installer | CI VERIFIED (engineering build only) | Unsigned NSIS installer and resource checks | Fresh Windows 11 VM install/upgrade/uninstall, signed EXE, EXE SHA-256, complete offline HMR |
| M2-08 Pharmacist and owner acceptance | NOT ACCEPTED | No sign-off evidence | Owner template approval, clinical scenarios, security sign-off and PR review |

## Release stop conditions

1. No merging or production release while any P0/P1 or clinical acceptance gate is open.
2. No clean VM PASS from Windows Server 2022 runner with Node/Python removed from PATH.
3. No template PASS from generic DOCX/PDF conversion.
4. No silent patient merging, inferred clinical assertions, automatic medication changes, PRODA/PPA submissions, or unauthorised transmission.
5. Do not put PHI, credentials or clinical narratives in repository, logs, screenshots or synthetic fixtures; authorised identifying SMS remains separate from optional default-OFF clinical AI.

## Follow-on verification log

| Item | Result | Evidence |
| --- | --- | --- |
| PR #1 status and SHA | Verified live at `860a3b6` before Wave 0 edits | GitHub PR metadata |
| Windows baseline | SUCCESS | Run `43796030183` |
| Privacy baseline | SUCCESS | Run `43796030164` |
| Artifact metadata | Retrieved, not downloaded or locally hashed | Artifact `14193659931` |
| Formatted identity comparison | Code fix plus synthetic regression committed after baseline; **CI pending** | `referral_entry.py`, `test_referral_identity.py` |
| Clean Windows 11 VM | NOT RUN | Requires fresh non-admin VM and installation |
| Exact owner template | BLOCKED (ASSET) | Approved DOCX and examples absent |
| Clinical sign-off | NOT ACCEPTED | Owner/pharmacist approval required |
