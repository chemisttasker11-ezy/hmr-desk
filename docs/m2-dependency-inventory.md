# Milestone 2 — implementation and dependency inventory

Reconciled 2026-11-16 against PR #1 verified baseline `860a3b689a3c19ea9594969c0410721f9a52891f`. **New commits after baseline require fresh CI.** This is a source-level + Actions-evidence inventory, not a completed clean-VM audit.

| Seam | Present implementation | Verified evidence | Remaining dependencies / acceptance |
| --- | --- | --- | --- |
| Desktop installer | Electron `desktop/package.json`, electron-builder NSIS x64 `perMachine: false`; frozen engine via `extraResources` | Windows engineering CI succeeded | Clean Windows 11 standard-user install, signed EXE/checksum, upgrade/uninstall |
| Engine | `engine_main.py`, `app_paths.py`, PyInstaller `hmr-engine.spec`, `desktop/src/engine-owner.js` | Frozen engine authenticated smoke and packaged process/crash smoke | Process failure matrix, user ACL, version skew/migration and real install |
| Runtime versions | `desktop/package.json` v0.1.0; Python 3.12, Node 22 on runner | Runner workflow metadata | Exact installed OS/build/Electron versions, lock hashes, release SBOM |
| Writable directories | `HMR-Desk-data` per-user and chosen `workspace`; existing config retained | Source and synthetic tests | Windows non-admin write/permissions, historical OneDrive migration, rollback |
| API boundary | Random 127.0.0.1 port, session token, authenticated health and restricted patient file serving | Privacy + packaged smoke | ACL of `api_token`, cross-process/local-user threat test |
| PDF intake | `local_referral_extraction.py`, `referral_entry.py`, PyMuPDF; WinRT/PowerShell OCR under `scripts/intake` | Synthetic extraction tests | Real packaged mixed, rotated, corrupted scanned PDFs, page-image UI and source confidence |
| Referral identity | Candidate-based duplicate logic; exact PDF hash and pharmacist distinct-person confirmation | Synthetic identity tests, formatted-number bug fixed after baseline | CI at new head; fuller reliable identifier comparison and provenance UI |
| Interview | Existing persisted interview JSON, prescribed-vs-actual-use model, desktop interview UI | Unit regressions | Historical schema/adapter, conflict and packaged UI test |
| Reconciliation | `reconciliation.py`, review digest/timestamp, UI acknowledgement | Synthetic regressions | Row-level conflict and downstream stale checks after material edits |
| Pathology | `pathology_records.py` with value/unit/date/source/verification and UI | Synthetic regressions | Real PDF import, legacy rows and amended result provenance |
| DOCX | `local_report_builder.py` creates generic document | Generic DOCX smoke only | **Owner's approved editable template and two comparison outputs missing** |
| PDF | `pdf_export.py`, bundled verified portable LibreOffice `vendor/libreoffice` in engineering packaging | Real synthetic DOCX-to-PDF smoke in Windows CI | Full HMR fidelity, fonts, converter licence notice, Windows 11 end-user runtime |
| Reference resources | `report.library()` empty when unavailable; no unlicensed MIMS content bundled | Source | Approved copyright/licence-safe reference selection with dates/versions |
| Backup | `backup_bundle.py`, AES-GCM passphrase-encrypted SQLite snapshot + workspace archive, isolated restore | Synthetic backup/corruption tests | Full data scope, no parallel mutation, live activation, disaster/ACL/DPAPI |
| Protected unsaved drafts | `desktop/src/draft-vault.js` uses Electron safeStorage + atomic file replace | Unit tests | Actual Windows DPAPI power-loss, cross-user recovery, backup inclusion policy |
| Database migrations | `db.connect()` incremental ALTER columns and meta table | Existing startup tests | Explicit `schema_version`, journal/rollback and historical fixture matrix |
| Clinical AI / SMS | Clinical AI default off with structured privacy projection; SMS separate identifying authorised path | Privacy CI | Actual offline no-external-AI-call E2E and SMS regression |
| External portals | PRODA/MHR, MIMS, AMH, PPA, SMS helpers remain optional | Source | Explicit offline unavailable status; no bypass, unlicensed assets or silent submissions |

## Runtime dependency classification

- **Bundled at engineering build:** Electron, PyInstaller onedir executable and `_internal`; PyMuPDF, openpyxl, python-docx, cryptography; scripts/intake; portable LibreOffice; browser helper extension files.
- **Windows operating system component:** PowerShell and WinRT OCR pathways; their availability and language support must be tested under non-administrator Windows 11.
- **Build-time only:** Python 3.12, Node 22, npm, PyInstaller, electron-builder and Git/GitHub Actions. They must not be required by the installed desktop.
- **Optional licensed/authenticated external integrations:** MIMS, AMH, MHR/PRODA, PPA and SMS gateway. The AI-off clinical core must remain usable without them.
- **Currently absent clinical asset:** owner-approved editable Word template and two approved example outputs. `brainstorm V2.0.pdf` is a clinical writing aid, not that template.

## Source and data handling rules

SQLite `hmr.db`, workspace referral PDFs, pathology PDFs, `interview.json`, reconciliation review, `pathology_records.json`, report specs and signed outputs require consistent backups, audited edits, strict no-overwrite migrations and recoverable version history. Preserve identifying SMS as its separate authorised workflow. No real patient records in CI or release artifacts.

## Reproducible evidence references

- PR: https://github.com/chemisttasker11-ezy/hmr-desk/pull/1
- Windows CI baseline: https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43796030183
- Privacy CI baseline: https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43796030164
- Baseline ZIP artifact ID 14193659931, expires 2026-11-23; ZIP digest recorded in `m2-acceptance-matrix.md`.
- P0/P1/P2 backlog and closure tests: `docs/m2/issues.md`.

**Evidence gaps:** no downloaded and independently SHA-256-hashed installer, actual Windows 11 machine inventory, clean-VM screenshots, migration fixture library or clinical sign-off. Do not mark them as passing.
