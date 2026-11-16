# HMR Desk — Milestone 2 engineering and recovery notes

**Current status:** engineering work in draft [PR #1](https://github.com/chemisttasker11-ezy/hmr-desk/pull/1), not a certified release. Refer to `m2-acceptance-matrix.md`; no file existence or passing unit test alone establishes clinical or installer approval.

## Target runtime
A Windows x64 NSIS installer must include the Electron application and `resources/engine/hmr-engine/hmr-engine.exe` plus its PyInstaller `_internal` directory, bundled scripts, fonts/approved templates and PDF converter once available. The user must **not** need Python, Node, Git, Word, LibreOffice or Claude installed.

The application owns a single engine subprocess. It selects an ephemeral loopback port and session authentication token; the patient workspace is not served via unauthenticated HTTP. On application exit, the subprocess is terminated. The default patient workspace for a new installation is `%USERPROFILE%\\HMR-Desk-data\\workspace`, and app/engine state remains in `%USERPROFILE%\\HMR-Desk-data`. Existing `app-config.json` values, including legacy `base`, are retained; the app does not silently move or overwrite a user's previous patient data.

### Windows build (engineering only)
From Windows PowerShell in the repository checkout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-windows.ps1
```

This creates a local Python build virtual environment, freezes the engine and runs Electron tests, then constructs the NSIS package. These development tools are required on the **build machine**, not on the eventual installed machine. The pull-request workflow `.github/workflows/m2-standalone.yml` also tests the frozen engine and stores an **unsigned engineering artifact** when successful. Installer signing and clean Windows VM validation remain distinct release gates.

## Existing data and migration
Before upgrading an existing patient workstation:
1. Close the current Electron application and service processes. Back up **both** the entire configured patient workspace and `%USERPROFILE%\\HMR-Desk-data\\hmr.db` (include JSON, PDFs, signed documents, audit and original referral documents). Do not move only the SQLite database.
2. Preserve the existing `%USERPROFILE%\\HMR-Desk-data\\app-config.json` and note its `base` value. On upgrade the existing location remains configured, even if it is on OneDrive. Avoid syncing a live SQLite database using OneDrive.
3. Validate files and database integrity before changing paths; never merge folders based only on patient names. Retain a rollback copy before a schema upgrade.
4. For new installations the default workspace is local and independent of the source checkout. Migration from legacy paths must be deliberate and separately verified; **not yet accepted as automatic**.

## Encrypted manual backup
Open Settings, choose **Back up now**, enter a passphrase of at least 12 characters, then select an encrypted `.hmrbak` output outside the active workspace and app-data folder. The backup includes a consistent SQLite snapshot and all non-symlink regular workspace files, encrypted with a unique AES-256-GCM key derived via scrypt with a random salt. No password or key is stored beside the backup. Record the passphrase separately in an approved secure place.

**Restore into a separate folder** asks for the backup, passphrase and a parent directory. The engine verifies the GCM authentication tag, manifest SHA-256 checksums and SQLite integrity before publishing a newly restored `data/hmr.db` and `workspace/` tree. It refuses overwrite and will not replace an active patient database. A wrong passphrase, corrupted backup or invalid manifest fails closed. Do not treat the isolated restore folder as active until its contents have been checked and migration/activation is intentionally performed by an administrator with the app fully closed.

Known limits: encryption protects the backup file; the operational local database and workspace rely on Windows account permissions and local disk protection such as BitLocker. Backup files must be stored off-device to protect against disk loss. Restore activation and routine automated encrypted backup are **not yet acceptance-tested**.

## Current manual AI-OFF clinical workflow

1. Import a source PDF through Intake. Use **Open original PDF** beside the unconfirmed page text; confirm identity, DOB, GP, dates and possible duplicate comparisons. For conditions, prescribed medicines, observations and allergies, enter the reviewed source page and pharmacist name. Keep allergies **Unknown** unless the original explicitly states no known allergies or lists them. The original and `referral_source.json` preserve page/source provenance.
2. Open the resulting patient, prepare and edit the clinical interview. The prescribed/referral medicine directions remain independent of **actual use**. Confirm regular, ceased, PRN, OTC/complementary products and DAA status. Review the reconciliation flags; acknowledgement binds to the exact medicine digest and is invalidated by future changes.
3. Under pathology, use **Import a local pathology PDF**, open and visually check the retained original, link a blank unverified pathology row to the source page/hash, then enter the result, unit, reference range, date and source. A named pharmacist must verify. Amending a verified value requires saving it **unverified** first and explicitly re-verifying; version 2 retains the amendment history.
4. Write/edit findings manually. The Brainstorming V2 PDF is a phrasing aid, never an automatic dose calculator or authority for patient-specific prescribing. The report snapshot includes source file SHA256 values, medicine-review digest and structured pathology revision.
5. Under Settings, **register the owner-approved editable DOCX** with version, owner identity and explicit layout/font permission. The DOCX must include the required `{{HMR_*}}` placeholders. Earlier approved layouts are preserved in the local template history. Without a legitimate approved layout, output is explicitly **provisional** and cannot be authorised as final.
6. Generate Word and matching offline PDF, visually compare with the owner's approved short and long reference outputs. Use the report-signoff modal to open the **exact hash-verified version**, confirm you reviewed it and enter the named pharmacist. The backend refuses mismatched source revision, stale reconciliation, modified report files, or unapproved template. It never sends a report automatically.
7. From Settings, **Back up now** to encrypt a complete SQLite/workspace snapshot. You can **Verify and preview** a backup without changing live records. Restoring creates a **new isolated folder**. Activation requires a separate explicit action, a fresh encrypted backup of active data, shutdown of the engine, checksum+SQLite revalidation, preservation of previous SQLite/workspace and a recoverable startup journal.
8. **Migrate current workspace safely** is a separate operation. It creates an encrypted pre-migration backup and verified staged copy, changes the active configuration only after byte-level checks, and retains the original workspace for rollback. Do not merge same-name patients automatically.

### Template placeholder contract

The editable owner layout must provide each named marker exactly once for clinical content. Text placeholders: `HMR_ASSESS_DATE`, `HMR_REPORT_DATE`, `HMR_PATIENT`, `HMR_DOCTOR`, `HMR_DEAR`, `HMR_THANKS`, `HMR_REASON`, `HMR_INTRO`, `HMR_CONDITIONS`, `HMR_ALLERGIES`, `HMR_OBS`, and `HMR_FOLLOWUP`. Single body-paragraph region anchors: `HMR_MEDS_TABLE`, `HMR_OTC_TABLE`, `HMR_CEASED_TABLE`, `HMR_PATH_TABLE`, and `HMR_ISSUES`. Placeholders must be wrapped as `{{HMR_NAME}}`. The renderer preserves the supplied DOCX header/footer and margins; owner visual/clinical review is required to approve actual line breaks, fonts, tables and pagination. The format contract is deliberately strict: ordinary patient reports **cannot** be silently registered as templates.

### Windows 11 release acceptance, separate from hosted CI

Build the unsigned engineering candidate through the current Actions workflow and download its installer plus `SHA256SUMS.txt` and `installer-manifest.json`. Verify the EXE's actual SHA256, not only its artifact ZIP digest. On a fresh **Windows 11 x64 workstation VM**, use a local non-admin account without installed Python/Node/Git/Office/LibreOffice. Install and use the app with network disconnected, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/collect-windows11-evidence.ps1 -InstallerPath "C:\\QA\\HMR Desk Setup.exe" -EvidenceDirectory "C:\\QA\\evidence"
```

Replace the example installer path with the actual file. This command does **not** install or modify the candidate or touch clinical file contents. It records Windows product/build, account status, resource availability, installed app presence, checksum, signing status, default route and ACL summaries. Run every scenario E01–E32 and record synthetic-only screenshot/video evidence in `docs/m2/evidence/synthetic-e2e-results.md`; a script alone is not a full UI acceptance test.

For **short and long approved HMR visual references**, compare only synthetic/de-identified PDFs locally:

```powershell
python scripts/compare-hmr-visual.py --approved "C:\\QA\\short-approved.pdf" --generated "C:\\QA\\short-rendered.pdf" --output "C:\\QA\\short-diff" --label short
python scripts/compare-hmr-visual.py --approved "C:\\QA\\long-approved.pdf" --generated "C:\\QA\\long-rendered.pdf" --output "C:\\QA\\long-diff" --label long
```

These commands are **on a separate QA/build machine with Python**, not a dependency installed on the pharmacist's standalone machine. PNG images remain private. A visual diff score never substitutes for owner/pharmacist approval. The final release decision records the exact SHA and acceptance signatures at one build.

### Backup portability and limitations

Portable `.hmrbak` contains the SQLite database and all files under the **configured patient workspace**: originals, consent, interview, pathology provenance, report specs and draft/final/signed versions. It does **not** port Windows user DPAPI-bound saved sign-ins, encrypted unsaved draft vault or every app setting automatically. Reauthorise external portal sign-ins and recover locally unsaved drafts on the same Windows user profile before cross-machine migration. Device-bound credentials must not be promised to restore on another machine. The operational workspace/SQLite relies on NTFS ACL and device encryption, while portable backups are AES-GCM encrypted.

## Privacy / clinical use
Clinical agent request data passes the structured, de-identified boundary and requires opt-in; interview/report AI defaults off. Authorised SMS replies are a separate intentionally identifying workflow and are not reclassified as clinical agent content. Do not put patient names, raw PDFs, DOB, IHI, Medicare, clinical narratives, tokens or passwords into CI logs, screenshots or GitHub issues.

MIMS, AMH, My Health Record/PRODA, PPA and SMS may require authenticated external subscriptions/services. Do not claim licensed resources are embedded offline.

## Troubleshooting
- Engine missing: verify `resources/engine/hmr-engine/hmr-engine.exe` and bundled `_internal` files exist; reinstall the full installer instead of installing Python.
- Engine readiness timeout: inspect only the local redacted `startup-failure.txt` and `engine.log`, not patient documents. Verify writable data and workspace folders and that antivirus has not quarantined packaged assets.
- Port issue: startup chooses a new loopback port; a session token guards ownership. No firewall opening or public server configuration should be necessary.
- Referral scan unreadable: inspect the original PDF locally, correct extracted fields manually and do not infer missing allergies or medicines. OCR is unconfirmed input.
- Pathology unknown: enter units, collection date and document/page source; an unverified entry is not a dose-adjustment basis.
- Backup fails: ensure destination is outside active workspace/data folders, sufficient disk space, correct passphrase and no symlinks.
- Restore fails: preserve the encrypted original and never try to fix it by silently overwriting active data.
- PDF or report template missing: do not claim the generic draft DOCX meets the owner's approved HMR layout.

## Required release evidence
Actual Windows 11 clean VM without separate runtimes; text and scanned referral import; manual interview and reconciliation; pharmacist-verified dated pathology; source-bound findings; approved template rendering and matching standalone PDF; signed document history; backup and restore; privacy regression; offline operation; installer SHA256 and appropriate owner/pharmacist sign-off. The currently supplied Brainstorm V2 PDF is a clinical writing guide, **not** the approved layout template.
