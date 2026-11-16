# Milestone 2 acceptance matrix — standalone manual HMR

Branch: `security/clinical-agent-privacy-boundary` · Existing draft PR #1 · 2026-11-16.

**Definition of finished:** A fresh Windows 11 x64 PC without Node, Python, Git, Office/LibreOffice, Claude or developer scripts must install HMR Desk, complete an AI-off synthetic HMR from referral (searchable + scanned PDF) to reviewed interview, reconciled actual medicine use, verified pathology, reviewed findings, owner-approved DOCX + matching PDF, signed version history, encrypted backup and restore. There must be independently reproducible test output, Windows VM evidence, checksums and pharmacist/template acceptance. No stubs, external profile dependencies, or mocked-only E2E results can satisfy a required gate.

Status key: **PASS** = verified evidence, **FAIL** = a test demonstrated a defect, **BLOCKED** = missing essential independent input, **NOT RUN** = not yet tested. Do not infer PASS from an implementation commit.

| Gate | Status at kickoff | Required evidence |
| --- | --- | --- |
| M2-00: inventory and synthetic regression fixtures | NOT RUN | Inventory, generated fixtures, baseline test outputs |
| M2-01: bundled engine, paths, secure lifecycle | NOT RUN | PyInstaller build, authenticated health and collision/restart tests |
| M2-02: offline text/scanned referral and field confirmation | NOT RUN | Real PDF fixtures and import/commit E2E |
| M2-03: actual use reconciliation and pathology provenance UI | NOT RUN | Automated scenarios + user-visible persisted results |
| M2-04A: exact approved Word template | BLOCKED | Owner-approved editable DOCX template plus short/long approved comparison reports; no template file exists in repository |
| M2-04B: bundled standalone PDF conversion | NOT RUN | PDF from packaged app on clean host without Word/LibreOffice |
| M2-05: manual UI end-to-end with AI disabled | NOT RUN | Packaged app workflow and screenshots |
| M2-06: encrypted backups, migration, recovery and privacy | NOT RUN | Corruption/rollback/restore and privacy regression |
| M2-07: NSIS Windows x64, offline clean VM E2E | NOT RUN | Installer, SHA-256, clean-VM run with no dependencies |
| M2-08: pharmacist/template/owner sign-off | BLOCKED | Explicit clinical and visual sign-off by owner |

The supplied `brainstorm V2.0.pdf` is a clinical writing guide, not evidence of approved Word page layout. Do not automatically embed its clinical dosing statements as validated rules. Clinical AI must stay optional and default-off; SMS messaging is a distinct authorised pathway. No real patient data goes into CI fixtures, logs or releases.

## Engineering execution log
- Baseline PR: `9c1fe971d2e1d78b2066a9588b35cc6e6d0048a2`.
- Repository is private; code changes target PR #1 only.
- The repository is source-only at baseline; `desktop/package.json` has no Python `extraResources`, `desktop/main.js` defaults workspace to a personal OneDrive path, and `jobs.py` references absent `engine/assets/scripts` assets.
- Update statuses only after reading concrete CI artifacts, tested output and owner approval.
