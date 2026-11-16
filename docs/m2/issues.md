# HMR Desk M2 issue register — implementation and acceptance

Updated 2026-11-16. Branch `security/clinical-agent-privacy-boundary` / private draft [PR #1](https://github.com/chemisttasker11-ezy/hmr-desk/pull/1). These statuses describe **release acceptance**, not just source code; P0/P1 remain open until exact acceptance tests pass.

| ID | Severity | Implementation now present | Acceptance evidence required / unresolved | Status |
| --- | --- | --- | --- | --- |
| M2-I01 TEMPLATE-01 | P0 | Owner-local editable DOCX registration, strict named placeholders, SHA256 manifest/version history; layout-preserving renderer, report and source hash sign-off | **Actual owner-approved DOCX, accepted short/long examples, visual comparison, formal owner/pharmacist approval** | BLOCKED — OWNER ASSET |
| M2-I02 VM-02 | P0 | Frozen engine/NSIS, protected IPC, scripted `collect-windows11-evidence.ps1` | **Real clean Windows 11 standard-user install and full packaged AI-off HMR E2E**, not Server 2022 CI | NOT ACCEPTED |
| M2-I03 MIG-02 | P0 | Settings migration wizard, pre-migration AES backup, independent staged copy/hash, original retained, crash cleanup/rollback tests | Real legacy OneDrive/custom locked/unwritable/space/interrupted migration drill | BUILT / NEEDS VM |
| M2-I04 MIG-01 | P0 | Schema v1 transactional SQLite upgrade, future-schema reject, preupgrade SQLite snapshot, historical fixture tests, corrupt config recovery | Multi-version historical JSON adapter/upgrade and real Windows shutdown/reopen | PARTIAL |
| M2-I05 INTAKE-01 | P1 | Source original via token-scoped hash-verified OS PDF viewer, source page excerpts, mixed rotated/damaged tests; pharmacist data confirmation | Packaged WinRT OCR with scanned handwritten PDFs, original-vs-OCR comparison and performance | BUILT / NEEDS VM |
| M2-I06 INTAKE-02 | P1 | Same-name formatted identifiers, Unicode support, DOB/date validation, allergies unknown versus explicitly none, source-confirmed interview prep | Full packaged case comparison, duplicate identity same IHI/Medicare scenarios | BUILT / NEEDS VM |
| M2-I07 MED/PATH/MODEL | P1 | Canonical clinical snapshot v1, 10+ reconciliation cases, timed pathology amendment reviewer, local sourced pathology PDF importer, legacy de-duplication, stale-snapshot sign-off | Pharmacist reviews 10 real-world-equivalent synthetic cases, restart UI persistence and conflict reconciliation | BUILT / NEEDS CLINICAL E2E |
| M2-I08 BACKUP-01 | P1 | Full AES-GCM workspace backup, private temp, read-only preview, checksum+SQLite isolated restore, explicit activation with fresh encrypted backup, old DB/config recovery journal | Real Windows 11 concurrent writes, low disk, DPAPI/ACL and separate machine restore | BUILT / NEEDS VM |
| M2-I09 SECURITY-01 | P1 | Authenticated owned port, disallowed HTTP source file serving, path-scoped IPC, no arbitrary PDF opening, hash preview, source symlink checks | Actual NTFS ACL, local HTTP/IPC pen test, PHI-free log scan on installed workstation | PARTIAL |
| M2-I10 SIGNOFF-01 | P1 | Named pharmacist report approval UI tied to exact DOCX+PDF, original sources, reconciliation, pathology, canonical snapshot | **Owner, pharmacist, security and release approval with same candidate SHA and no P0/P1 defects** | NOT ACCEPTED |
| M2-I11 TEMPLATE-03/PDF | P1 | Portable LibreOffice, synthetic short+long template PDF smoke, page image/text comparison utility | Real owner-approved short/long multi-issue visual diff, fonts, Windows 11 final layout | BUILT / NEEDS OWNER |
| M2-I12 ENGINE/STATUS | P1 | Owned child engine lifecycle, first-run and corrupt config recovery, single instance and packaged crash smoke | Installed-app stale token/locked folder/uninstall/reinstall/upgrade/hard-kill matrix | PARTIAL |
| M2-I13 RELEASE-01 | P1 | `manifest-windows.ps1` produces engineering EXE/resource SHA256 and version manifest, `SHA256SUMS.txt` artifact upload configured | Complete successful latest-SHA packaging, installer/checksum downloaded and Windows 11 tested; signing decision | BUILT / NOT ACCEPTED |
| M2-I14 BUILD-01/REFS-01 | P1 | Pinned direct requirements, npm lockfile, pinned checksum LibreOffice with license checks, licensed portal empty states | Full transitive hash locks/SBOM, vendor notices and approved nonproprietary references | PARTIAL |
| M2-I15 A11Y-01 | P1 | Status/error roles and labelled source/clinical forms | Keyboard-only/screenreader at Windows 125%/150% and minimum 1280px width | NOT RUN |
| M2-I16 PERF-01 | P2 | Intake source size/page caps; 2/5+ page synthetic regressions | 5/15/50 page p50/p95 measurements on supported Windows 11 hardware | NOT RUN |
| M2-I17 PRIVACY/SMS | P0 | Clinical AI opt-in and deidentified privacy contract, distinct authorised identifying SMS pathway | Offline/no outbound clinical agent traffic and authorised SMS regression on installed app | CONTRACT CI PASS ONLY |

## Closing rules

An issue is closed only when the real required test, machine, exact Git SHA, synthetic fixture checksum, reviewer and evidence link are recorded. No CI smoke substitutes for clean Windows 11 E2E or an approved owner template. An unsigned installer is an engineering candidate, not an accepted clinical release.

Technical implementation is allowed to progress past owner/VM blockers, but the milestone release decision remains OPEN. Keep this PR draft, do not merge or send patient data, and do not silently downgrade failing checks.
