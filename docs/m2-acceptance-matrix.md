# HMR Desk Milestone 2 — live evidence-backed acceptance matrix

Updated 2026-11-16 (Australia/Brisbane). Release platform: **Windows 11 x64, standard user, AI OFF**. Private [draft PR #1](https://github.com/chemisttasker11-ezy/hmr-desk/pull/1), branch `security/clinical-agent-privacy-boundary`.

**Release is NOT ACCEPTED until every P0/P1 requirement, owner/pharmacist approval and clean Windows 11 E2E is proven.** No failing gate is silently waived. Continue independent engineering work despite blocked approvals.

## Verification evidence

- Original engineering baseline: `860a3b689a3c19ea9594969c0410721f9a52891f`, Windows Server 2022 engineering [run 43796030183](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43796030183) PASS; clinical privacy [run 43796030164](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43796030164) PASS. Neither is a clean Windows 11 release.
- Expanded fast Windows backend+desktop clinical regression and privacy [runs 43806054197](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43806054197) and [43806054099](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43806054099) PASS at `eccf1c7daeecd60c87ca59e0bbf995ee286344bc`.
- Expanded fast clinical regression and privacy [runs 43806523988](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43806523988) and [43806524004](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43806524004) PASS at `53060ef706e34a4e58028e952ab2f327fa889a55`.
- Latest template-import code test run [43806946766](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43806946766), Windows packaging [43806946704](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43806946704) and privacy [43806946735](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43806946735) target `058050deed9a124b25b95c5e1ba72913d187a206`. **Check the Actions outcome; pending at last documentation update except privacy PASS.** Subsequent documentation-only commits do not imply the application tests were rerun.
- Baseline unsigned ZIP `14193659931` had manifest digest `05d049100ed086c09b560e7bc8f7e8f25f424cadaea252fd9f96b056793a8abe`; this is **not** the EXE SHA. The new Windows workflow writes `SHA256SUMS.txt` and `installer-manifest.json` into the engineering artifact if successful.

## Held correction work (2026-11-18)

- Acceptance pins remain unchanged: frozen `bb3ea45` and operator integration candidate `0db2612`. The local correction tree is not a release and has not run Windows acceptance or CI.
- The earlier report "test-locked" claim was unsupported: the legacy `test_report.py` failed during import before its report assertions ran. The correction collects the relevant workflow as a real pytest test and updates its stale storage/API fixtures. No earlier successful report execution is inferred from that repair.
- Corrections held separately: truthful medicine-reference install/status UI; report actual-use wording that distinguishes explicit taking from missing directions; saved-manual-report AI assist no longer restarts or overwrites a manual report. Synthetic mocks authorize no external patient processing, and privacy/review gates are unchanged.
- The manual medicine chain is not proof of automatic OCR-to-AMT or a complete clinical workflow. Operator report content/identity and isolated restore evidence remain separate acceptance checks.
- Prior unsupported real-AMT machine evidence is withdrawn. Later operator evidence must identify the candidate, source database, and the exact search/link/save/restart checks; it must not be backdated to the frozen build. Licensed reference databases and the Brainstorm PDF remain outside source, CI, packages and artifacts.

## Scope: implementation versus acceptance

| Contract / ID | Implemented and regression-covered | Remaining release gate | Acceptance |
| --- | --- | --- | --- |
| M2-00 inventory, evidence, synthetic cases | Baseline, issue register, two Windows test workflows; clinical model, intake, backup and report tests | Current-head package evidence, full scenario fixture registry | PARTIAL |
| M2-01 engine, packaging, local workspace | Frozen PyInstaller engine and Electron owner, session token, crash recovery, config recovery, versioned SQLite and rollback snapshot | Windows 11 non-admin clean install, ACL, real offline recovery/lifecycle | ENGINEERING CI VERIFIED ONLY |
| M2-02 text/scanned/rotated intake | Original hashes and page excerpts, source PDF viewer, conservative duplicate/identity/date checks, explicit pharmacist clinical field/allergy review, source-linked interview preparation | Actual packaged Windows OCR and clinical page visual comparison, large/handwritten fixtures | BUILT / NEEDS E2E |
| M2-03 canonical clinical reconciliation/pathology | Canonical snapshot, 10+ medication scenarios, review hash invalidation, structured pathology v2 amendments, source PDF import, verified reviewer/time, legacy de-duplication | Full pharmacist-reviewed whole-case UI and historic compatibility acceptance | BUILT / NEEDS E2E |
| M2-04 approved DOCX template | Template-bound renderer, checksum manifest, explicit local owner import, old revision history, immutable document/source hash and approval guard | **Owner-supplied approved editable DOCX, short+long approved references, visual fidelity and clinical sign-off** | BLOCKED — EXTERNAL OWNER ASSET |
| M2-04 bundled PDF | Portable checksum-verified LibreOffice, no host Office requirement; synthetic short/long template PDF test in workflow | Passing workflow at final SHA, approved short/long layout page images, real Windows 11 | BUILT / NEEDS E2E |
| M2-05 complete AI-off screens | Source viewers, actual-use/path edit, findings/report editor, hash-bound sign-off modal, template import, backup/activation controls | Full packaged screen-to-screen keyboard/scaling E2E | PARTIAL |
| M2-06 privacy, backup and recovery | Encrypted archive preview, private staging, checksum restore, isolated SQLite validation, explicit activation and old-data rollback journal, legacy workspace migration, real-DPAPI smoke scripted | Windows 11 account ACL/DPAPI, forced-kill test, off-device/cross-user recovery and full user-run drill | BUILT / NEEDS E2E |
| M2-07 release installer | Windows engineering NSIS, versioned packaging with converter, planned installer and resource SHA256 manifest | Actual candidate hashes at release SHA, licence audit, Windows 11 install/upgrade/uninstall and code-sign decision | ENGINEERING ONLY |
| M2-08 owner/pharmacist approval | Software requires explicit named clinical authorisation; no silent prescribing/transmission | Ten clinician-reviewed synthetic cases, approved template, owner/clinical/security certificate | NOT ACCEPTED |

## Hard release prohibitions

1. **Do not mark the milestone DONE, merge PR, or call an unsigned engineering EXE a clinical release** until the owner-approved template and clean Windows 11 synthetic HMR chain are accepted together at the same code SHA.
2. Never conflate Windows Server 2022 Actions, even with Python/Node absent from PATH, with a fresh Windows 11 machine without those runtimes installed.
3. Keep missing allergies/medicines/results unconfirmed. Pathology units and dates must have explicit sources. No automatic prescription, medication change, PPA claim or report transmission.
4. Do not put PHI, actual template reports containing patient data, saved sign-ins or secrets into public CI logs/artifacts.
5. Authorised SMS replies may include identifiers as an independently authorised communications pathway. General clinical AI is opt-in and off by default; clinical-agent de-identification remains separate.
6. A synthetic test manifest signed by “Synthetic QA” demonstrates the renderer only; it is **not owner approval**.

See `docs/m2/issues.md`, `docs/m2/evidence/index.md`, `docs/m2-operations.md` and `docs/m2-release-decision.md` for the closure log.
