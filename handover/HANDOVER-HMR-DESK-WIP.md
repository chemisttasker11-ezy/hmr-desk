# HMR Desk: work-in-progress handover (Nov 21, 2026)

Status: UNFINISHED WORK, NOT READY TO MERGE. Nothing here is clinically accepted or approved for production use.
Nothing was merged to main by this handover. Each section says whether a claim was observed running or only read from code.

## 0. Completeness: NOT yet complete
This document covers only the patches the source engineer produced (two stacks below). The operator host holds broader unique local work (a dirty candidate worktree, a PR29 worktree, several candidate and rebuild branches, and a long git inventory) that has not yet been diffed or reconciled here. Do not treat this handover as the full local work. Before publishing, compare against live origin ancestry: some earlier work was already pushed or merged, so do not republish old commits.

## 1. What is in this handover

Two labelled stacks. They have different bases and must not be mashed together.

### Stack B: `handover-renderer-review-aid` (base: main 46d7df2457a34a866413c3dd8e6166fc0c823fe6)
Patches in `patches/` (git format-patch, apply with `git am`):
1. `0001` Wire the original report builder into `jobs.report_build` through `original_builder_adapter.py`.
2. `0002` Template-review aid: a keyword screen of past-case template wording against the saved record.

### Stack A: PR29 stack (base: PR #29 head 5c9b486, which is NOT based on main 46d7df2)
Patches in `pr29-stack/`, apply in this order on a PR29 checkout:
1. `0001-PR29-snapshot-contract-compat.patch` fixes a backward-compatibility break in the clinical snapshot digest.
2. `0002-PR29-held-medicine-actions.patch` is the held medicine Action list. It also carries a `desktop/renderer/report-editor.js` change against the real PR29 head. The same change is in `report-editor-held-hunks-against-PR29-head.diff`.

Superseded intermediate patches were deliberately NOT included (adapter-only, wired v1 and v2, early template-aid, held v1 to v5). Do not resurrect them.
`MANIFEST.sha256` lists every file's hash.

## 2. Project facts (code-read)
- `HMR Desk/engine/`: Python local service. Patient records live in an encrypted SQLite store (`records` table). Reports are a JSON spec (`report_spec.json`) rendered to DOCX and PDF. Key modules: `report.py` (spec, refresh, validation), `jobs.py` (`report_build`), `report_auth.py` (sign-off checks), `report_status.py`, `clinical_snapshot.py`, `suggest.py` and `suggestion_context.py` (suggestions), `records.py` (record-name allowlist), `routes_*.py` (HTTP routes).
- `desktop/`: Electron renderer (`renderer/*.js`, `main.js`). The engine starts only when the app is packaged and the env vars HMR_API, HMR_SMOKE_URL and HMR_SHOTS are unset (`desktop/main.js`).
- The external AI step is a restricted, minimal projection. The current schema is unchanged by this work. Adding conditions, allergies, lab values or dates to it WOULD widen what is disclosed and needs its own authorisation.
- Sign-off is blocked unless an owner-approved template and a matching PDF pair exist (`report_auth.check_approval`). The original-builder path records `template_approved=False`, so sign-off stays blocked by design.

## 3. What each patch does and its evidence level

### 0001 Original report builder wiring (Stack B)
- Active only if `<DATA_DIR>/original-report-builder/` holds `build.py`, `Template - Copy.docx` and `word2pdf.ps1`. Their SHA-256 values are pinned in `original_builder_adapter.PINNED`. The copies are hashed and then run, so what is hashed is what runs. No setting or HTTP route can enable or redirect it. There is NO fallback renderer.
- Failure handling: nonzero builder exit, a missing Word render (`r.pdf`), or a missing Montserrat embed all fail closed and leave no output. On timeout it stops only its own worker tree and never kills Word by name. A fixed warning is shown if a Word process lingers.
- Evidence: 24 adapter and jobs tests pass on Linux using fake runners. NOT run in a packaged app. NOT proven end to end with real Word by this patch.
- The three pinned assets are the owner's own files and are NOT in this repository. See section 6.

### 0002 Template-review aid (Stack B)
- `suggest.suggest()` now adds `template_mentions_not_in_record` and a "Check first" line when template wording names medicines, classes or a few topics that the patient's saved record does not contain. The record means current medicines, interview text and eligible evidence. Sentences with negation or stopped cues do not count as support. The UI shows "Check first" as a list.
- LIMITS (important): a keyword screen only. Anything outside its small vocabulary is never flagged (for example alcohol, the abbreviation CKD, nausea, reflux, dementia). It can wrongly flag synonyms and consequence topics. A missing flag does not mean a template fact is verified. The `template_review` gate is unchanged and still required. No clinical rules, doses or cutoffs were added.
- Evidence: 5 synthetic tests pass on Linux. The visible line was rendered in headless Chrome from the real HTML builder. It was not seen in Electron.

### Stack A 0001 Snapshot contract compat
- PR29 added GP/clinic fields to the canonical identity digest, which changed every stored digest. Fix: reports with no contract marker use the legacy canonical (clinic excluded, other keys only if non-empty). A marker equal to exactly the int 2 means all four keys are always digested. Any other marker fails. Legacy evidence also gets GP-block drift detection. `snapshot_coverage` is a response-only field.
- Evidence: 9 new tests on Linux only. No packaged Windows round trip of this patch has been run. Earlier packaged-app results on other builds do not prove this patch.

### Stack A 0002 Held medicine Actions
- Problem: refresh keeps a medicine row's typed Action text only when the first three cells (medicine, actual use, source note) match exactly and are unique in the old and new tables. Otherwise the text was silently dropped, and the one `.bak` copy is overwritten by later saves.
- Fix: the dropped text is written to a separate record `report_spec.held_actions.json` in the same transaction as the refresh. A panel under the Medicines table lists it with the reason, "Copy text" and "Mark handled". Nothing is auto-applied. `report_build` and `check_approval` refuse while unhandled entries exist. Report status shows a count. The record loader is strict (types, unique ids, bounded size, id equals content hash) and fails closed.
- Evidence: 11 tests on Linux (classification, persistence across saves and refreshes, rollback, patient isolation, route validation, build and sign-off refusals with the real `case` fixture, malformed-record refusal).
- NOT verified: the real UI flow on Windows or Electron, restart persistence, backup and restore round trip, and the route over HTTP. A packaged candidate build exists on the operator host, but the medicine-Action regression scenario had not been completed when this was written.

## 4. How to run the tests
- Python: from `HMR Desk/engine`, `python -m pytest -q -p no:cacheprovider`. On Linux the engine imports `msvcrt`, so a stub module `msvcrt.py` must be on `PYTHONPATH`, and APPDATA, LOCALAPPDATA and USERPROFILE must point to a scratch directory. Linux results with a stub are NOT Windows proof.
- Known baseline on unmodified main under that Linux setup: 2 failed (`test_full_flow_integrity.py::test_referral_to_report_flow_stays_consistent`, `test_offline_helpers.py::test_missing_browser_helper_code_does_not_prevent_manual_api_import`), and 5 files that error at collection (`test_actions.py`, `test_api.py`, `test_api_presignoff.py`, `test_independent_repairs.py`, `test_manual_workflow.py`). Causes were not investigated further. The baseline failures were observed on main before the patches. Stack B on main: 829 passed, 2 failed, 5 collection errors, 1 skipped. For this run the failing names were not diffed against the baseline list, so treat 'same as baseline' as unconfirmed. PR29 stack with all patches: 836 to 838 passed with the same 2 failed and 5 errors (counts from a locally reconstructed PR29 base).
- Do NOT read pass counts as completion. The collection errors hide the HTTP routes tests on Linux.
- Desktop node tests were not run for these patches (no node_modules in the engineering environment). Run them on Windows.

## 5. Genuine gaps and open work
1. Word automation on the Windows test machine. Native Word open and save work for a human. COM automation fails: `Documents.Open` returns null with no exception, and `SaveAs2` fails with 0x800A1066. The same standalone builder command succeeded earlier on the same machine and later failed. Cause unknown (hypotheses only: Protected View or File Block treatment, Word resiliency state, a session or identity difference). The frozen `word2pdf.ps1` exits 0 even when Open returns null, since it never checks, so the PDF's existence must always be the success test. `build.py` and the adapter both check it.
2. Renderer source versus app integration: Stack B 0001 is source only. It has not been proven in a packaged app, and no PDF recovery or clinical acceptance is claimed.
3. The medicine Action refresh regression on the packaged build is still to be run (scenario: three distinct medicines with typed Actions; unchanged refresh keeps all; then change one row and add a duplicate, re-confirm medicines, refresh; the unchanged row keeps its Action, the others go to the held panel; build is refused; handle them; restart persists).
4. Richer, evidence-linked clinical suggestions remain open. The AI step cannot see conditions, allergies, observation values or dated labs. There is no CrCl or check-library port. Both need a separately sourced clinical assessment and a disclosure decision. The phrasing standard (decisive versus soft wording) is unresolved.
5. Sign-off for original-builder output needs an owner decision on template approval semantics.
6. The original builder asserts a signature email that belongs to one pharmacist, so non-matching signatures would fail. Scope is currently single-user.
7. `report_status` readiness items do not include held entries (a separate field is used to avoid changing the existing exact-item contract).
8. Smaller notes: held-list resolved entries have no UI restore, a corrupt held record has no in-app repair (fails closed), and the packaged-app smoke has gaps listed by the operator.


## 5b. Built-in browser tabs and portal helper scripts (code-read; NO live end-to-end claim)
Source: `desktop/main.js` (site table), `desktop/src/tabs.js`, `sign-ins.js`, `proda-login.js`, `injection.js`, `browser-queue.js`, `autorun.js`, `helpers-run.js`, `desktop/view-preload.js`, and the helper content scripts in `MIMS Interaction Helper/`, `Pathology Chrome Helper/` and `PPA Claim Helper/` (plus `Android_SMS_Integration/` for SMS).

| Tab | Entry | Helper script | What source covers |
|---|---|---|---|
| My Health Record (via PRODA) | proda.humanservices.gov.au | Pathology Chrome Helper | PRODA login assist with OTP polling and validation, pathology queue |
| eMIMS | app.emims.plus/interactions | MIMS Interaction Helper | interaction list runs, completeness checks that fail closed |
| PPA | app.ppaonline.com.au | PPA Claim Helper | claim helper |
| Sheet | docs.google.com/spreadsheets | none | view only |
| AMH | amhonline.amh.net.au | NONE (comment in source: sign-in and reading only, no helper script yet) | search URL load only |

Each tab uses its own persistent session partition with permissions denied and non-http navigation blocked.

Test coverage that exists: node unit tests with mocked pages (`desktop/test/proda-login.test.js`, `mims-completeness.test.js`, `injection.test.js`, `browser-queue.test.js`, `autorun.test.js`, `helpers-run.test.js`, `proda-logout-recovery.test.js`, `control-mcp.test.js`). They prove the script logic against synthetic pages. They do NOT prove a live portal opens, signs in, or still matches the portal's current page structure. Portals are licensed or authenticated third-party services.

Missing end-to-end tests (none were verified in the current packaged build when this was written):
1. Each tab loads in the packaged app and shows the real portal (eMIMS, AMH, PRODA/MHR, PPA).
2. Sign-in per portal with the owner's own accounts, including PRODA OTP, saved-credential fill, and logout recovery. Credentials must never be logged or published.
3. eMIMS: a helper run on a synthetic medicine list against the live site, then comparing the saved result and its completeness status with what the site shows. Portal DOM drift is the main risk.
4. AMH: any helper behaviour does not exist yet. Only the tab and URL load exist.
5. MHR: pathology queue behaviour against a live (non-patient) test context. Never use real patient data in a test.
6. PPA: claim helper on a synthetic claim, with no submission.
7. Offline and unavailable behaviour: each tab fails clearly and never fakes a result.

## 6. Private dependencies (contents NOT published)
- The owner's report builder assets: `build.py`, `word2pdf.ps1` and `Template - Copy.docx`. The last carries the owner's signature block. Only their SHA-256 pins appear in source. Put them under `<DATA_DIR>/original-report-builder/`.
- Reference assets used by suggestions and the finding library: the case index, finding library and brainstorm PDF. They are third-party or patient-derived and must stay local. The code reads them from the project-configured local reference directory (see `docs/medicine-data.md` and `docs/local-reference-offline-prep.md`).
- Patient records, the encrypted database and its key, and any API token.
- Unit tests use fabricated fixtures and need none of the above. The full original-renderer end-to-end run DOES need the three pinned assets and Microsoft Word on Windows.

## 7. Rules for contributors
- No force-push and no history rewrites. Keep PR27, PR28 and PR29 separate.
- Do not weaken scanners or security policy, and do not add a fallback renderer.
- Keep the external AI projection unchanged unless the owner authorises widening.
- No clinical rules, doses or cutoffs without a sourced clinical assessment.
