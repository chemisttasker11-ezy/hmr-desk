# Milestone 2 dependency inventory (initial repository audit)

Baseline SHA: `9c1fe971d2e1d78b2066a9588b35cc6e6d0048a2`. Observed files are source only; no approved HMR DOCX template, portable PDF converter or bundled OCR binary appears in the repository tree.

| Seam | Implementation | Current external dependency / risk | M2 decision |
| --- | --- | --- | --- |
| Desktop packaging | `desktop/package.json`, `desktop/main.js` | NSIS currently packages JS only, no Python engine | PyInstaller on Windows runner; Electron extraResources includes engine; clean VM check required |
| User paths | `desktop/main.js`, `HMR Desk/engine/db.py` | OneDrive default, code-root workspace, USERPROFILE assumption | Writable per-user workspace selected by user; legacy migration only on consent |
| API/auth | `HMR Desk/engine/service.py`, `api.py` | Fixed ports 8766/8767 and persistent token; another listener can take API port | Loopback ownership, one child process, readiness/health, no patient file static route |
| PDF intake | `HMR Desk/engine/referral_entry.py`, `scripts/intake/intake.py` | PyMuPDF; OCR invokes external helper scripts | App-owned PDF/OCR in frozen runtime and source review |
| Interview | `HMR Desk/engine/interview.py`, `desktop/renderer/interview.js` | Legacy JSON tables; consent template external | Versioned compatible data, clear manual source review and confirmation |
| Medicine reconciliation | `reconciliation.py`, `api.py`, interview screen | Read-only checks not yet surfaced in UI | Persisted acknowledgement + invalidation on edit |
| Pathology | `interview.py`, `desktop/renderer/interview.js` | Legacy four-column rows no units or verification | Source/date/unit/verification metadata without destructive migration |
| Report editing | `report.py`, `desktop/renderer/report-editor.js` | Draft spec exists; generic output in `local_report_builder.py` | Approved-template-bound renderer; preserve manual author approval |
| PDF | `jobs.py` | Refers to absent asset PowerShell + installed Word | Independently licensed, packaged local converter |
| Output/reference | `report.library()` | absent `engine/assets/references` or licensed source | Graceful empty state, no unlicensed content |
| Backups | `db.backup()` | Rolling SQLite copies only; excludes PDFs/JSON | Encrypted full workspace snapshots, restore verification and migration |
| Privacy | `clinical_privacy.py`, `service.py`, `desktop/main.js` | AI opt-in and static denial already implemented | Preserve no-identifier clinical agent boundary, separate SMS path |
| Third-party portals | `MIMS Interaction Helper`, `PPA Claim Helper`, `Pathology Chrome Helper` | Licensed authenticated external websites | Optional; no embedded copies, bypasses or implied offline coverage |

## Data retained
SQLite `hmr.db` and `patients/events/tasks/meta` tables; patient relative folder; original PDFs; `interview.json`; `confirmed_meds.json`; `report_spec.json`; `report_spec.ai.json`; signed outputs; audit events. Backup/restore must preserve all, retaining compatibility and refusing ambiguous duplicate merges.

## Baseline tests
Run `python -m pytest -q` selectively for isolated synthetic clinical/privacy tests in `HMR Desk/engine`, `npm test` in `desktop`; use an isolated `HMR_DATA_DIR`, `HMR_DB`, and `HMR_WORKSPACE`. Windows build artifacts must be tested outside the source workspace with AI disabled. Record actual test status, not only commands.
