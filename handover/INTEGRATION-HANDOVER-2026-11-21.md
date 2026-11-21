# Integration handover: combined clinical safeguards and optional original Word builder

Date: 21 November 2026 (Australia/Brisbane). Status: **PARTIALLY COMPLETED. Source integrated. On Linux, plain `pytest` now passes with nothing excluded (905 passed, 1 skipped at the head named in section 9; the older 2-failure and 5-collection-error figures below are historical and superseded). Windows build, installed-app and clinical-matrix evidence for the final head is still being collected by the operator and is NOT recorded here. No clinical acceptance.**
Not merged to main. No deployment. Clinical release approval stays with the application owner.

## 1. Purpose and scope
The owner asked for one coherent candidate from three independent lines of work, not three competing implementations: PR #32 (clinical and report safety), PR #33 (optional original Word builder and template-review aid) and PR #34 (audit only). Standalone report generation (automatic, no installed Word, no AI, no internet) stays primary. The original Word builder is a separate optional route.

## 2. Starting state
- Base: main `46d7df2457a34a866413c3dd8e6166fc0c823fe6`.
- PR #32 head `102605a` (functional commit `08262a8`), based on main.
- PR #33 head `8b166d2`, based on main.
- Developer branches (read only, untouched): `wip/pr29-candidate-nov21` `cb6f14e`, `handover-renderer-review-aid` `e7b9514`, `wip/local-m2-divergent-snapshot` `a67d4bc`.
- Integration branch (local until the operator publishes it): `integration/hmr-combined-nov21`. It is PR #32 head, merged with PR #33 head, plus three commits listed in section 9.

## 3. What actually exists today (stage of the application)
Three evidence levels, kept apart. Nothing in the second or third level should be read as accepted.

**A. Implemented in source (code read, Linux tests only)**
- Optional blank fifth GP Plan column (Settings, default off), GP provider and practice details through referral review to the report, schema migration, safer medicine-recommendation refresh, held pharmacist Actions with build and sign-off blocking, snapshot contract compatibility, duplicate-patient DOB comparison across date formats, atomic export (PR #32).
- Optional original Word builder through a pinned-asset adapter, opt-in setting, atomic no-overwrite publication, pinned frozen worker, template-review "Check first" aid (PR #33).
- Combination rules added in this integration (section 5).

**B. Built and run on Windows (operator evidence, earlier builds, NOT this commit)**
- The operator built a packaged candidate (PR29 head `5c9b486` + compat + held-actions + renderer wording) and launched it in an isolated profile. It started its own engine, showed the Today view, and a synthetic started report persisted after restart.
- Baseline C07 (GP Plan four/five-column layout) and C08 (GP metadata mismatch and update) passed narrowly in the actual app. Their DOCX pixels were checked through LibreOffice, not Word.
- Native Word open and save work for a person. Word COM automation currently fails on the test machine (`Documents.Open` returns null, `SaveAs2` fails 0x800A1066). Cause unknown. An identical earlier standalone run had succeeded.
- These results belong to earlier commits. They do not prove this integration commit.

**C. Unverified**
- Medicine Action refresh and held-panel on a packaged build (C09), including restart, backup and restore of the held record.
- Installer, non-administrator install, first launch, offline run, scanned and searchable referral PDFs, migration of an older encrypted database, sign-off acceptance, for this commit.
- Original builder against the real approved template with Word and the private assets. Layout comparison with the approved report.
- Portal tabs (eMIMS, My Health Record via PRODA, PPA, AMH) end to end. AMH has no helper script. Only mocked-page node tests exist.
- The ten-case pharmacist acceptance matrix.

**Intended clinical workflow (owner, 11:05 on 21 Nov, replaces earlier garbled transcripts).** Before the interview: fetch the patient's pathology and tests from My Health Record. After the interview, once the medicines actually taken are confirmed: run the eMIMS Interaction Checker on that confirmed list, before the report is written. The owner says this works on his own working machine today. That is user-reported, not tested by us.

What the source does for that sequence (code read; Linux logic tests only; no live portal run):
- Step order in `steps.py`: collect pathology (MHR), interview sheet, confirm medicines, check interactions (eMIMS), report assist, report start, report build.
- Pathology is offered only before the visit (states confirmed, pathology_ready, sheet_ready) and needs surname, DOB, sex and Medicare or IHI. Results come back through `/api/pathology/queue` and `/api/pathology/result`.
- The eMIMS list is built from the confirmed medicines only. It refuses to build if the confirmed list is stale. A result file is bound by SHA-256 to the confirmed list, so a changed list makes the check "not current". Report start, report assist and report draft refuse until the check is current.
- **Gaps found in source:** (1) `report_build` and sign-off readiness do not require a current interaction check or current confirmed medicines; `interaction_scope.py` states it deliberately adds no gate so the pharmacist can document uncertainty. Whether to enforce one is a clinical policy decision for the owner; we did not change it. (2) The eMIMS list generator `MIMS Interaction Helper/make-lists.py` (also `PPA Claim Helper/make-claims.py` and `record_report.py`) is not in the repository. Without it `mims_lists` returns an empty queue ("licensed portal integration unavailable"), so on a clean build the eMIMS step has nothing to run on. The helper `content.js` that drives the portal is in the repository. The owner's working machine presumably has these files; a narrow comparison (file names and SHA-256 only, no contents) would settle it. (3) Nothing orders "MHR before interview" as a hard gate: a patient can reach the interview without pathology.
- Not verified live: portal sign-in, My Health Record fetch, eMIMS run, helper behaviour against current portal pages.

**Missing-helper diagnostics (added after the first Windows build started; separate small delta).** `/api/mims/lists` and `/api/claims` keep their `lists` and `claims` keys and now also return `helper_available` and, when false, a plain `message`. `build-windows.ps1` prints a warning (no failure) when `make-lists.py`, `make-claims.py` or `record_report.py` are missing. Linux test: `test_offline_helpers`. Desktop: when an eMIMS or claims queue is empty and the engine says `helper_available: false`, the tab's results line shows the engine's message instead of "Nothing to run" (`emptyQueueMessage` in `desktop/src/browser-queue.js`, used in `arm()` in `main.js`; an older engine without the field still gives "Nothing to run"). Tests: `browser-queue.test.js`. Visual evidence: `helper-missing-results.png`, the app's real index.html and style.css rendered in headless Chrome with the message placed in the results box by hand. It is NOT the running Electron app and does not prove the toggle path end to end. UNVERIFIED: the PowerShell build lines were not run (no PowerShell here), and the Electron toggle path was not run on Windows.

## 4. Chronology of the preceding work (for collaborators)
1. Baseline: main `46d7df2` contains PR #27 (development baseline) and PR #28 (screenshot staleness check, tool failure).
2. PR #29 (`5c9b486`) added GP Plan, practice details and safer refresh. PR #30 and #31 were closed as folded into it.
3. A snapshot-digest compatibility fix, held medicine Actions and a renderer wording fix were built on that head and kept as a candidate (`wip/pr29-candidate-nov21`). These exist in PR #32 in cleaned form.
4. The wired original-builder adapter and template-review aid were built on main (`handover-renderer-review-aid`).
5. Word automation regressed on the test machine (see 3B). Standalone rendering is unaffected by it.
6. The owner asked for all local work to be published. The inventory is in `handover/inventory/LOCAL-WORK-ACCOUNTING.md` on the developer branches. All other local clones were ancestors of origin or historical.
7. Independent review produced PR #32, #33, #34. This document starts from them.

## 5. Decision record
| Item | Disposition | Reason | Our existing alternative | Combined behaviour | Evidence or limit |
|---|---|---|---|---|---|
| PR32 GP Plan option, GP/practice details, migration | Accepted | Same behaviour as our candidate (the candidate's own tests pass against this code) | Candidate branch had the same | Unchanged from PR32 | PR32 tests, passed here. Real template layout unverified. |
| PR32 held Actions, refresh preservation | Accepted | Content-identical to our held design (verified line for line against the candidate tree) | Candidate held-actions patch | Build and sign-off blocked while unresolved | Existing tests plus new test: blocked on the Word route too. Installed-app journey unverified. |
| PR32 snapshot contract compat | Accepted | Same as ours | Candidate compat patch | Unmarked old reports compare with legacy digest | Linux tests. No encrypted legacy round trip yet. |
| PR32 DOB format comparison, atomic export | Accepted | Real defects (split identity, truncated export) our candidate lacked | None | Replaces main's plain string and `xb` write | `test_handover_safety.py`. Hard-link export fails closed on FAT or network shares. |
| PR33 opt-in setting (default off) | Accepted | Presence of private files must not replace the standalone renderer | Our adapter used the files if present | `report_use_original_builder` default off | New test: standalone stays default with assets present. |
| PR33 atomic publication, pinned frozen worker, CI lists | Accepted | Real partial-output and bypass risks | Our adapter copied straight to target | Used unchanged | PR33 tests, passed here. Not a sandbox. |
| Template-review aid | Accepted | Merged cleanly | Ours (same code) | "Check first" list only | Keyword limits: false negatives and positives remain. |
| Original builder with GP Plan on | **Adapted (new)** | Owner's rule: never silently ignore GP Plan. PR33's review says the private template cannot be assumed to honour it, and the adapter has no GP Plan input. We therefore refuse. Whether the real template could honour it is NOT tested (no asset or layout test) | None | Build refuses with an explicit message and writes nothing | New test. |
| Held Actions vs original builder | **Adapted (verified)** | The gate must not depend on the renderer | None | Gate runs before either renderer | New test. |
| Original builder sign-off | Kept as in PR33 | Approval rule for its template is undecided | Same | `template_approved` false, so sign-off stays blocked | PR33 tests. |
| Flaky adapter test | **Fixed here** | `test_timeout_with_concurrent_unrelated_automation_word_ends_only_the_worker` hard-coded timestamps near 01:00 UTC on 21 Nov, so it began failing at that time of day on PR33 itself | None | Test now pins the worker-start stamp | Passes (892 passed). |
| PR34 historical M2 audit | Rejected as code, read as audit | No shared ancestry. Its improvements already exist. Not imported. | Current main lines | None | Not re-audited line by line here. |
| Local-only Brainstorm tables | Excluded | Private, licensed | None | Never published | Metadata only in the inventory note. |
| package-lock peer-flag diff | Excluded | Metadata churn | None | Not applied | Diff kept in inventory. |

## 6. Findings
- PR #32 contains our candidate. The only differences are its own fixes plus PR #28 items our candidate lacked. No unique candidate behaviour was found missing.
- Defect: the adapter timeout test depended on the wall clock (see decision record). Fixed.
- The original builder path would have ignored the GP Plan setting. Now refused.
- Cause of the 2 failures (`test_full_flow_integrity::test_referral_to_report_flow_stays_consistent`, `test_offline_helpers::test_missing_browser_helper_code_does_not_prevent_manual_api_import`): both pass alone. They fail only when plain pytest also imports legacy script-style files (`test_consent_sign.py`, `test_engine.py` found by bisection), because those assert and change global state at import. Same names fail on unmodified main. This is a test-isolation artefact, not a product defect. It is not fixed here. CI avoids it by running those files through `test_legacy_scripts.py`.
- HISTORICAL (superseded by `b184b95` and `2453b11`): the 5 collection errors (`test_actions`, `test_api`, `test_api_presignoff`, `test_independent_repairs`, `test_manual_workflow`) came from import-time legacy scripts. They now run to their end in their own interpreters, the `*_presignoff` files are deleted, and the sign-off gate runs unchanged on real hash-bound synthetic evidence. Sign-off gating is also covered by `test_report_auth` and `test_report_signoff_consent`.

## 7. Testing (Linux with an msvcrt stub; NOT Windows proof). Each line names the commit it ran on.
Update after commit `68847ac`: the legacy-script harness was repaired (see section 6). Results below are for the commit that carries this text (its SHA is in section 9); the older numbers are superseded.
- Plain `python -m pytest -q -p no:cacheprovider` from `HMR Desk/engine`, nothing excluded by hand: **895 passed, 1 skipped, 0 failed, 0 collection errors.**
- The legacy script files (older complete tests) still all run, each in its own interpreter, through `test_legacy_scripts.py` (25 runs). `conftest.py` only keeps them out of in-process import, where they corrupted other tests.
- `test_api`, `test_manual_workflow`, `test_independent_repairs` and `test_actions` now run through sign-off, send and claim. The sign-off gate runs unchanged on real hash-bound synthetic evidence (`legacy_signoff_support.py`). The old `*_presignoff` copies were deleted because the full scripts replace them.
- Stale expectations were updated to current, source-read behaviour: records now live in the record store, medicines must be confirmed before findings, AI assist is opt-in, follow-ups from 1 Nov 2026 need documented delivery choice, the database is SQLCipher.
- `test_api.py` now runs to its end (no env flag, no skipped tail). Its stale parts were replaced, not hidden:
  - The retired BUILD_SCRIPT report job (stub builder, state to report_drafted, "already exists" refusal) is gone as a product path. The real renderer is covered by `test_synthetic_patient_journey` (jobs.report_build, real Word and PDF files inspected) and `test_original_builder_publication` / `test_template_report_builder` (no overwrite). The api script itself no longer asserts the build job.
  - The CLI, skill and developer-default AI agent checks (seeded Claude/Codex/agy agents, stub agents run over raw referral and case text) test behaviour removed on purpose (commit 2aa2171 removed default agents; `jobs.agent_step` now raises PrivacyBlocked). Replaced by: `report_draft` must fail with "disabled", write no spec, `default_route` and route validation still checked, fresh installs have no agents.
  - Claim assertions on `reasons` and `outcomes` were dropped because those come from the absent PPA helper. Engine-owned claim fields (medicare, gpProvider, dates) are still asserted.
- **Still not covered (Linux):** (1) The licensed MIMS and PPA helpers are absent, so the scripts use synthetic doubles (`legacy_mims_double.py`, `legacy_ppa_double.py`). They prove engine wiring only, not the real helpers' parsing. (2) API-key storage uses Windows DPAPI, so the HTTP-agent and key-redaction block in `test_api.py` runs only on Windows (guarded by `sys.platform == 'win32'`). It is unverified on this Linux run. (3) `test_manual_workflow` no longer uses the old external build script; its build output is a synthetic Word and PDF pair with hand-built evidence, distinct from real renderer output. (4) The HTTP token check in `test_api.py` now uses the handler without a static directory.
- HISTORICAL (kept for the record): the 2 failures and 5 collection errors under plain pytest came from import-time legacy scripts. Same names fail on unmodified main. Superseded: see the addendum on the harness fix.
- Candidate cross-check: the 9 backend test files changed by the developer candidate `cb6f14e`, run unmodified against this integration: 61 passed. The changed desktop GP Plan test is byte-identical.

### 7b. Desktop (run on the final code head; see the result line below)
`node --test` in `desktop/` on commit `6f416c9` (code identical to the final head): 504 tests, 503 passed, 0 failed, 1 skipped. Mocked pages only. Not Windows proof.

## 8. Verification limits
No Windows run of this commit. No Word. No installer. No migration test on an older encrypted database. No real template, no real patient data. No browser portals. Visual layout (GP Plan on and off, long reports) not inspected.

## 9. Compatibility and commits
Commits on the integration branch after the PR #33 merge: the merge itself `49085b2` (conflicts resolved in `jobs.py`, `settings.py`, `desktop/renderer/settings.js` and both workflow test lists), then combined-behaviour tests, then the wall-clock test fix (`6f416c9`). Existing data is untouched. The Settings screen now carries both Reports settings and explains that they cannot both be on for building.

## 10. Outstanding work, in priority order
1. Build the exact commit on Windows and install as a standard user without Word. Run: first launch, offline referral to report, interview save and reopen, medication reconciliation, pathology, Word and PDF output, refresh with held Actions, backup, restart and recovery.
2. Migration test on a copy of an older encrypted database, with rollback.
3. Visual check of the GP Plan column on and off in the approved template and PDF.
4. Original builder with Word and the private assets: separate run, compared against the approved layout. Decide template approval rules and the Word COM failure.
5. The ten-case pharmacist matrix with commit and template version recorded.
6. DONE (historical item): the 5 collection errors and 2 failures on Linux were fixed by `b184b95` and `2453b11`. The remaining Linux gap is the Windows-only DPAPI block, which must run on Windows.
7. Portal end-to-end tests listed in the earlier handover.

## 11. Completion status
Partially completed. Integration and Linux tests done. Windows evidence and clinical acceptance outstanding. Engineering completion is not claimed.

## 12. Reproduce
Branch `integration/hmr-combined-nov21` at commit `6f416c9175f8e85b53d1cb6eedd3f6eaf02416c6` on main `46d7df2`. PR link: to be added when the operator publishes the branch.

## Addendum: build script path and Python discovery

- Finding (source reading, same on origin/main): `scripts/build-windows.ps1` and `scripts/bundle-libreoffice.ps1` used single-quoted PowerShell paths with literal doubled backslashes, which PowerShell keeps as two separators. The script also assumed the `py -3.12` launcher.
- Change: paths use one separator and `Join-Path`; one `$venvPython` is reused. `Find-BuildPython` tries `HMR_PYTHON` (full path to a python.exe), then `py -3.12`, then `python3.12` and `python` on PATH, and accepts only version 3.12. If none qualifies it stops with a message naming `HMR_PYTHON`. No host path is in the repo.
- Tests: `test_build_script_contract.py` (static text checks, 3 tests). Plain pytest 899 passed, 1 skipped at this commit.
- Unverified: PowerShell was not run here. Whether the doubled separators alone caused the reported ObjectNotFound is not confirmed. An unmodified run of the committed script on the Windows host is still required.

## Addendum: recovered helper review and helper-mode tests

Source of the recovery: a ZIP supplied by Es from his working machine, with a README written by his recovery assistant. Provenance in that README is a report, not independent proof: the helpers are not under Git, whether the installed app matches commit 90b2419 is unknown, the spec-JSON writer was not traced, no clean-machine run was made.

Review (private scratch copy of d8c54f7 with the files dropped in; nothing from the ZIP is committed):
- Archive is text-only code. No patient data or credentials found; lists.js was left out by the sender and claims.js is an empty list.
- New to the repo: `make-lists.py`, `make-claims.py`, `record_report.py` (plus `background.js`, `file-results.ps1`, two READMEs). The recovered `content.js` and manifests are older and looser than the hardened repo versions and are rejected: MIMS content.js selects ambiguous or first-option matches and drops the incomplete-result errors; PPA content.js always ticks written consent held and carries the pharmacist's name and accreditation number. Es's working machine therefore runs pre-hardening extension scripts.
- The engine loader works with the real scripts (stops at the `lists`/`claims` assignments).
- With the real scripts present the full suite gave 7 failures. Cause: tests silently depended on whether a helper file exists on the machine. Two assumed the helper is absent; five pinned manual-mode names. This was a test-isolation defect, not a product defect.

Decision record:
- Accepted (test change): every helper-dependent test now sets its mode explicitly. `test_helper_modes.py` covers a synthetic resource folder with no helper, a synthetic helper file (loader stops at the data assignment), a dose-stripping stand-in (contract only, not the licensed helper), and spacing. `test_stopped_overlap_contract.py` pins manual mode by fixture. `test_offline_helpers.py` uses an empty resource folder and patched absent helpers.
- Rejected: making reconciliation use the application's whole-name identity in helper mode too. It would stop a stopped 10 mg and a taking 5 mg of the same ingredient from needing the pharmacist's explicit resolution, a less cautious result, and it contradicts the existing helper-mode test in test_report.py. Behaviour stays: manual mode compares whole normalised names (different strength = different record); with a dose-stripping helper the same ingredient at different strengths needs explicit resolution. Both are now pinned.
- Adapted (code): `external_helpers.ingredient_names` wraps the helper's names with spacing normalised, because the real helper leaves doubled spaces ("synthmed  a") that can defeat a match. medicine_review.py and interaction_scope.py call it.
- Not adopted: `record_report.py` command line writes Consent = Yes unconditionally and defaults Referral Reason to polypharmacy. The engine imports only its `outcomes()` and `reasons()`. Both would need removing before any publication. `make-claims.py` self-check names a doctor. The ZIP README has local account names and paths. Publication of the three scripts is therefore held pending sanitisation and Es's explicit approval.

Testing (Linux, exact tree = this commit): plain pytest 905 passed, 1 skipped, 0 failed with no helpers; also 905 passed, 1 skipped, 0 failed in a scratch copy with the three real helper scripts present. Not run: Windows, packaged app, real eMIMS, real helper on the host.

## Addendum: C09 UI hang, build stall check and helper output contract (documentation only, no code change)

- C09 UI hang, cause confirmed on the Windows candidate window (operator observation): the report Refresh button handler opens a native confirm() first (`desktop/renderer/report-editor.js`). It had been open since the 11:43 automated click. While it is open the renderer cannot run JavaScript, so `ui/snapshot` and `ui/click` (executeJavaScript, no time cap in `src/control.js`) time out, although the engine, app-control `/identity` and a direct API refresh all answered. Answering OK at 12:00 let the refresh run, the held-actions banner showed 2 held entries, the API state matched (A kept, changed B and duplicate C held), and the snapshot returned 87 controls without any restart. It was not an engine, lock or MCP fault. Engineer first suspected a lock holder; the lock probe (400 held-not-found in 378 ms) and direct refresh (200) ruled that out.
- Not known: whether the earlier 11:00 refresh dialog was answered by a person or the refresh was done by API.
- Source gap, not fixed here: the automation refusal list (`UI_BLOCKED` in `src/control.js`) lacks "refresh" and other confirm-guarded controls, and the snapshot/click handlers have no time cap. Any fix keeps the human confirmation (no auto-confirm, no bypass), is tested first, and is a separate stage after the current candidate build.
- Build stall check: a silent log at the npm summary was the in-process LibreOffice MSI download and extraction (windows PowerShell hides progress), not a hang.
- Helper output contract (private pack, synthetic tests, nothing committed): standalone `make-lists.py` writes `lists.js` beside the script with each entry's folder taken from its spec's `out` path and produces no interaction results; the legacy `file-results.ps1` trusts a first-line folder and overwrites. In the app, each list entry carries the patient's id and folder_path from the patient record, and results are filed as `MIMS interactions generated <meds-revision> <sha256>.txt` in that patient folder without overwriting, only when the name matches exactly one queued patient. Generated lists are not real interaction results; those need the logged-in service. Unverified: real files on the host, the Scheduled folder examples, Windows run of the helpers.

## Addendum: reconciliation with the PR #35 review comments (21 Nov, 12:07)

Two comments on PR #35 (https://github.com/chemisttasker11-ezy/hmr-desk/pull/35#issuecomment-7055480036 and https://github.com/chemisttasker11-ezy/hmr-desk/pull/35#issuecomment-7055489678), both posted by the repository owner's account, which is also the account the operator pushes from. They are treated as external evidence, checked against the source, not as instructions.
- Documentation hygiene (valid, fixed here): the top status and three section 6/10 lines still described the old 2-failure and 5-error state; they are now marked historical. The `test_legacy_scripts.py` docstring still said the `test_api` tail is not run and named `HMR_RUN_STALE_API_TAIL`; that switch no longer exists and the docstring is corrected.
- Handover location: an earlier set of addenda was appended to `SENIOR-REVIEW-RENDERER-2026-11-21.md` by mistake (the PR #33 stack file). They are moved here and that file is restored to its PR #33 content.
- Clinical interaction gate, missing clean-machine helpers, exact-head Windows acceptance, real Word COM failure, encrypted migration: already open items in this handover. No source change; owner decisions (gate policy) and the operator's Windows evidence remain the route.
- Test counts: the reviewer reports CI counts (686 backend passed, 3 skipped, 496 desktop passed, 9 skipped at 97db47b). They differ from the local counts (905 passed, 1 skipped; 504 passed, 1 skipped). The reviewer's CI runs are not reconciled with the local runs here (different selection or platform skips); the CI run pages were not inspected.
- Commit mapping: the product code under test is unchanged from `6f416c9` except the engine changes in `b184b95` (tests), `eef1580`/`90b6479` (helper status), `5ea2fdc` (desktop message), `d8c54f7` (build scripts) and `97db47b` (helper names and tests). The head of PR #35 is the commit that carries this addendum; read it from the PR, not from this file.

## Addendum: CI whole-suite coverage (source change, not yet run on Windows)

Finding: the CI backend steps name an explicit file list. Of 138 backend test files, 86 are named in a workflow pytest command and 52 are not (for example test_api.py, test_actions.py, test_manual_workflow.py, test_interaction_scope.py, test_mims_binding.py, test_helper_modes.py, test_build_script_contract.py). Those had Linux-local evidence only.
Change: the fast-regression backend job (windows-2022, Python 3.12) now also runs plain `python -m pytest -q` after the curated step, so a new test file cannot be left out. The curated steps stay.
Status: implemented in source only. Not run on a Windows runner. Tests that were only run locally with an msvcrt stand-in may fail or behave differently on real Windows; the first CI run will show it, and any failure is to be fixed, not excluded. Tests set helper mode explicitly, so a runner without the private helper files is the case they cover.
Unverified: the CI step log counts (reviewer cited 686 backend and 496 desktop); logs need authenticated access.

## Addendum: journey coverage matrix (21 Nov, 12:25) - what each stage has actually proven

Levels: S = implemented in source; L = Linux tests (msvcrt stand-in, not Windows proof); C = GitHub Windows runner at 97db47ba (synthetic, exact commit, step result only, logs not read); H = operator run on the Windows test candidate (named evidence only); U = unverified. Nothing here is clinical acceptance.

| Stage (Es's workflow order) | S | L | C | H | Remaining gate |
|---|---|---|---|---|---|
| Referral and patient setup | yes | yes | synthetic referral-to-signed-and-sent step succeeded | not recorded in this stream | run on the Scheduled ready files |
| Pathology from My Health Record before the interview | yes (PRODA tab, pathology helper, local SMS code receiver) | synthetic only | no | U | Es signs in to PRODA himself on the host; code mechanism and phone bridge state unchecked |
| Interview, confirmed medicines | yes | yes | partly (journey step) | held-medicine refresh preserved clinical text on two refreshes | none beyond Windows matrix cases |
| Held medicine actions | yes | yes | no | unresolved held survived app and engine restart; Build blocked with count 2; both held items marked handled through the UI | editor still said 2 held and "reconciliation not done" after resolve and Save: stale panel or gate defect, under test; resolved state across restart not yet shown |
| AMH per-medicine button | yes (generic name, search route) | navigation tests | no | U | cloud browser only: signed-in search route works and lands on search results; installed app tab, packaged button and Back position unverified |
| eMIMS on the confirmed list, before the report | yes (private helper absent from public source) | helper-present and helper-absent tests | no | U | cloud browser only: signed in, Interaction Checker page present; no check run; helper output and filing into the patient folder unverified on the host |
| Report build and sign-off protections | yes | yes | synthetic journey | Build gate dialog seen; Copy exact text failed in that environment (clipboard, app versus remote not separated) | interaction-evidence policy at build and sign-off awaits Es (visible optional offline exception; no code written) |
| Original Word builder (opt-in) | yes | yes | not exercised on the runner | real Word COM failure reported earlier | separate run, never a silent replacement |
| Delivery and claiming | existing | yes | partly | U | Scheduled-file run |
| Offline manual path | yes | yes | no | U | host run with eMIMS unavailable |
| Save, quit, restart | yes | yes | DPAPI crash/restart step succeeded | restart persistence shown once (held unresolved) | resolved state across restart |

Reading rule: a green count is not a row above. Only the H column from the operator and exact-commit C results count towards acceptance, and C is synthetic. The installer the host built is from the operator's equivalent driver at b184b95; the committed script build at 97db47b is still to come.

## Stage: per-patient results area and later-online refresh (source only)

Implemented in source (Linux tests only, not Windows-run, not clinically accepted):
- `GET /api/patients/<id>/results` (engine/results.py): pathology records, pathology PDFs, last collection, re-check pending, interaction evidence state and files, and whether the latest built report used them. Display only; no gate or sign-off policy changed.
- New patient action `pathology_recheck` (allowed before and after the visit, including after sign-off). A pending re-check keeps the pathology step available; a result clears it. A signed version is never changed.
- `interactions` is repeatable: the Run-again button is never disabled by an earlier result. The automatic flow still skips a done step, so there are no automatic duplicate checks.
- Build records `interactions_evidence_sha256`; report status can say "the interaction results changed" only for builds that recorded it. Older builds read `not_recorded`, never outdated.
- Wording: "used by the report" refers to the whole saved record, not single rows.
- Held-action resolve now refreshes the status panel (fixes the stale "2 held" line).
- Desktop: Results tab in the patient workspace with "Re-check pathology online" and "Run interactions again".

Evidence at this stage: engine plain pytest 912 passed, 1 skipped (baseline 905 plus 7 new); desktop node 507 passed, 1 skipped, 0 failed (508 tests). Visual: headless Chrome render of the results markup with the app stylesheet inspected (content, table, buttons legible; the tab strip in that image is a test harness, not the real layout). Not verified: the real Electron window, the buttons' click path, Windows.

Unverified: whether the online-later flow works in the installed app; whether report build/sign-off should hard-gate on stale interactions (Es's answer pending, no gate written).

Wording note: the Interactions section separates "does the saved result match the current confirmed medicine list" from "which result the built report used"; the second line states it is report provenance and not an all-clear. The 2025 date in the screenshot came from a wrong epoch in the render fixture; the app shows the real file modified time.

Coverage added (synthetic, Linux): the synthetic journey now performs a pathology re-check, saves a later manual interaction note and records a new pathology result after sign-off, and asserts the signed Word and PDF bytes and the pharmacist's saved report text are byte-identical, state stays signed_off and the signed version stays intact. A separate test covers the same state rule. This is a synthetic simulation, not a real sign-off or clinical acceptance.

Reconciliation acknowledge hint: a blank pharmacist name now shows an inline instruction instead of a bare 400. The name is never auto-filled, because the acknowledgement is a named pharmacist attestation. Node-tested helper only; not Windows-run.

Build script PS5.1 fix (source, static-tested only, no PowerShell run available here): the Python 3.12 probe used a double-quoted format string that Windows PowerShell 5.1 strips when passing to a native command, so detection failed for a known 3.12 exe. The probe is now quote-free. Each native call (venv, pip, PyInstaller, npm ci/test/dist) runs through Invoke-Native, which relaxes the error preference only around that call, shows the output, and throws on a non-zero exit code. No blanket Continue. Needs a fresh-venv run of the committed script on Windows before it counts as proven.

CI whole-backend failures (Windows, runs 44858026330 and 44858286334: 909 passed, 3 skipped, 2 failed), diagnosed from the operator's authenticated logs and fixed in source:
1. test_medicine_grouping::test_search_route_grouped_flag_is_opt_in left a database connection open, so Windows could not delete the temporary hmr.db (WinError 32). The test now closes the connection. Test hygiene only.
2. The synthetic referral-to-sent journey needs the offline PDF converter, which the whole-backend job does not bundle. It now skips with a stated reason only when no converter exists, and fails instead when HMR_REQUIRE_PDF_CONVERTER=1. The standalone Windows job, which bundles the pinned converter, sets that variable, so real-converter coverage cannot silently become a skip there.
Verified on Linux only: skip path, fail path, and the full suite (915 passed, 1 skipped). The Windows result needs the next CI run.

Files open and acknowledgement entry (source, node-tested only, not Windows-run):
- Files tab lists now show an Open button for pdf, txt and docx. New IPC open-patient-file (desktop/src/patient-file-open.js): sender check, exact file name from the patient folder or its Pathology subfolder, realpath containment, regular files only, allow-list of types, PDFs in the bundled viewer, nothing executed. Other types (json, lock, exe) show no button and are refused if forced. Tests cover traversal, wrong list, symlink escape and type refusal.
- Correction: the earlier hint pointed at an interview "pharmacist field" that does not exist in the UI (the engine fills the header from Settings and overwrites it on load). The acknowledgement now has its own Reviewing pharmacist box, prefilled from Settings as a visible suggestion, with a blank refused and the box focused. The name is only recorded when the pharmacist clicks Acknowledge; nothing is acknowledged automatically.
