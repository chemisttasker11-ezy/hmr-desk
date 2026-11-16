# Milestone 2 synthetic test fixture register

All examples are generated in temporary directories using **synthetic people, no real Medicare/IHI, no patient PDFs, no clinical credentials**. Actual source documents, original referral reports and the owner's Brainstorm V2 PDF are not copied into public CI.

| Scenario group | File(s) / fixture | Current automated evidence | Remaining requirement |
| --- | --- | --- | --- |
| New/legacy SQLite, rollback, future schema | `test_db_migrations.py` | Version 1, existing patient rows, single preupgrade rollback snapshot, atomic failure | On-device historical data and interrupted upgrade, Windows ACL |
| Legacy config and per-user workspace migration | `desktop/test/config-load.test.js`; `desktop/test/workspace-migration.test.js` | Corrupt config preserved, Unicode/spaced filesystem paths, hash-copy/rollback, symlink/nested folder rejection | User-run OneDrive/locked file/low disk and power failure |
| PDF variants and source uncertainty | `test_referral_variants.py`; `test_referral_identity.py`; `test_local_referral_extraction.py` | Searchable multi-page, mixed rotation 0/90/180/270, blank/damaged, batch limit, duplicate identity, original hash, explicit unknowns | Windows 11 actual OCR with scanned/handwriting sources and 50-page/large file measurement |
| Clinical referral source review and transfer | `test_interview_intake_review.py` | Separate unknown vs confirmed negative allergies, source page and pharmacist, confirmed-only preparation | Whole packed UI visual comparison to original pages |
| Medicine reconciliation and review invalidation | `test_medicine_scenarios.py`; `test_reconciliation_review.py`; `test_manual_foundation.py` | 10 synthetic scenarios including dose/frequency, PRN, ceased, OTC, DAA, duplicates, review hash invalidation | Pharmacist-reviewed ten full cases, UI persistence/restart |
| Pathology source PDF + verified results | `test_pathology_import.py`; `test_pathology_records.py` | 2-page PDF original/hash, scan uncertainty, duplicate refusal, verified reviewer/time, v1 compatibility, amendments | Actual scanned lab PDF review, historic/recent and clinical case signoff |
| Canonical v1 clinical snapshot | `test_clinical_snapshot.py` | Prescribed vs actual, unknown vs verified negative, legacy pathology, source/result digest | Whole-case cross-screen confirmation and source revision audit |
| Clinical route and localhost security | `test_clinical_routes.py`; `test_service_static_security.py` | Authenticated clinical API route syntax, unauthenticated document denial | Installed Windows API/IPC penetration, ACL and outbound traffic |
| Owner template and report authorisation | `test_template_report_builder.py`; `test_report_auth.py` | Required placeholders, layout headers/footer retention, checksum manifest, owner-attested registration, report file/source hash checks, stale sign-off rejection | **Approved owner DOCX and two real visual exemplars missing; clinical sign-off absent** |
| PDF visual/pagination evidence | `scripts/smoke-template-pdf.py`; `scripts/compare-hmr-visual.py`; `test_visual_compare.py` | Local short/long synthetic DOCX/PDF conversion test, per-page image/text comparisons | Approved short/long multi-page matched on Windows 11 and owner visual signoff |
| Encrypted backup, isolated restore/activation | `test_backup_bundle.py`; `desktop/test/restore-activation.test.js` | Wrong passphrase/corruption, complete workspace, non-destructive preview, manifest integrity, recoverable activation journal | Actual Windows 11 backup, restore, cross-user and crash hard kill |
| Protected DPAPI draft vault | `desktop/test/draft-vault.test.js`; `scripts/smoke-dpapi.ps1` | Unit tests; real Windows Electron hard-kill probe is in packaging CI | On-user Windows 11 DPAPI/unsaved editor recovery/legacy plaintext migration |
| Standalone installer/resources | `m2-standalone.yml`; `scripts/manifest-windows.ps1`; `scripts/smoke-packaged-desktop.ps1` | Prior Windows Server 2022 frozen smoke and signed-session process restart; candidate EXE/SHA manifest generated in newest workflow | Fresh Windows 11 standard-user install, signed/unsigned release decision, upgrade/uninstall |
| Clinical AI / authorised SMS | `test_clinical_privacy.py`; `clinical-privacy.yml` | Opt-in deidentified clinical agent contract; identifying SMS remains separate | Real offline Windows network and authorised SMS E2E |

## Fixture provenance requirements

For each final E01–E32 result, record in `docs/m2/evidence/synthetic-e2e-results.md`: scenario ID, exact Git SHA, actual Windows host/version/account, fixture SHA256, expected outcome, actual outcome, synthetic screenshot/video path and reviewer. Do not convert unit-test PASS to packaged-UI PASS. A single real patient record, identifying screenshot or sign-in file invalidates the release evidence and must not be uploaded.

The uploaded `brainstorm V2.0.pdf` is a clinical phrasing aid, **not** an approved HMR DOCX layout, independent prescribing evidence, or synthetic fixture.
