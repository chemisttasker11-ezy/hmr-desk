# Clinical record conversion - state (WIP, unverified, not installed)

Branch: wip/m3-records-unverified. Status: saved clinical records are NOT protected. Nothing here ships.
(The scope below comes from the owner's instruction relayed in the project conversation; this file records it, it does not grant it.)

## Done locally (Linux only; no Windows build, no CI, nothing installed)
- engine/records.py: encrypted record store (inside the SQLCipher database), name patterns, import, export, migrate_all, status.
- Call sites switched to the store with explicit connection-taking helpers: interview, steps, api, jobs, report,
  report_auth, followup, pathology_records, pathology_import, lifecycle, suggest, consent_sign, dev_seed.
- Startup migration (service.py): copies plain record files into the store, verified by read-back. Repeat-safe. A database
  record is never replaced by a file. A differing plain file is counted as a conflict and left alone. Plain files are NOT deleted.
- API: GET /api/records/status, POST /api/records/migrate, POST /api/records/export {patient_id, destination}.
  Export is a plain copy, labelled in a README as outside the app's encryption and as subject to the MIMS licence.
  It refuses relative paths and the app data / patient workspace folders.
- MIMS result from the desktop helper lands as a plain file first; the API copies it into the store when its name and
  sha256 match, then checks it as before.
- Backup bundle: the snapshot database already carries the records table, so backup and restore include them
  (test_backup_bundle_carries_records).
- Tests: the CI fast list plus test_records (12 tests) pass locally (111 passed). Updated for the store: test_report_auth,
  test_pathology_records, test_pathology_import, test_mims_binding, test_lifecycle, test_consent_sign, test_timeline,
  test_dev_seed. Older script-style suites (test_api, test_report, test_manual_workflow, test_independent_repairs,
  test_interview, test_actions) fail before and after for reasons unrelated to storage (sign-off review requirement,
  Word/PDF converter and licensed helper missing on Linux); they are not in CI.

## Draft vault (separate)
Report and interview drafts in the browser are encrypted with a DPAPI-backed key; first-launch guard in desktop code.
Draft vault documentation is still owed here.

## Not done
- Retirement of plain record files. Until a verified removal step exists they remain on disk and the app must say
  "unprotected". No secure-erasure claim: deleting a file does not guarantee the data is gone from an SSD; recoverability
  is kept through encrypted backups. No plain backup copy is kept as a safety net.
- Export UI (button) in the desktop app.
- Patient-derived files outside patient folders: history-import-plan.json, Scheduled/_interview specs/*.json (still read
  as file fallback by interview.load), TO SORT/intake_corrections.json. They need their own identity key.
- referral_source.json stays a source file.
- Word/PDF output continuity after conversion (reports are still built from the stored spec; verify on Windows).
- Windows verification and desktop tests for the new endpoints.
Release status stays "saved records not protected" until conversion, migration and retirement are verified on Windows CI.
