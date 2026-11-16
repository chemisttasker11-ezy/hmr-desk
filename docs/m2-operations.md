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
