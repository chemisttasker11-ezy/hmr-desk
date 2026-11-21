# Senior handover — PR #32: report safety, GP Plan and clinical-source compatibility

Date: 21 November 2026 (Australia/Brisbane)  
Owner: HMR Desk pharmacist / clinical product owner  
Author: independent senior-developer review  
Repository: `chemisttasker11-ezy/hmr-desk`  
Review PR: https://github.com/chemisttasker11-ezy/hmr-desk/pull/32  
Source baseline: merged `main` `46d7df2457a34a866413c3dd8e6166fc0c823fe6`  
Tested functional commit: `08262a8c2bd5f14b5abddf209cb38f6cecf3457c`  
Developer source: `wip/pr29-candidate-nov21` (initial `07a6f38`) and owner-requested PR #29 (`5c9b486`)  
Status: **DRAFT — ENGINEERING REGRESSIONS PASSED, NOT CLINICALLY ACCEPTED. NO MERGE OR RELEASE.**

## 1. Scope and integration mechanics

- Opened a separate senior branch based directly on the merged `main`, rather than merging the old PR29 base into production. The resulting diff contains only the intended feature changes, not the many already-merged baseline commits.
- Preserved the current `main` baseline including the screenshot-staleness and tool-failure corrections that arrived through merged PR28.
- Incorporated GP Plan option, clinic and GP details, safer medicine recommendation refresh, held medicine Actions, and source snapshot contract compatibility from developer handover.
- Conflicts and user-specific behaviour are reviewed as changes against current main. No patient data, unlicensed catalogue files or private report templates were committed.

## 2. Features and clinical safety contracts reviewed

### Optional GP Plan column
- Settings option is disabled by default.
- When on, a blank fifth GP Plan column is added to new owner-template or provisional DOCX medication tables.
- Four-column saved medication schema and existing report versions remain unchanged.
- Owner-template prototype tables must clearly label a genuine GP Plan column; unknown fifth-column layouts fail closed.
- **Outstanding:** visual inspection in the actual owner template and converted PDF at long report length and normal/large UI scaling.

### GP provider and practice contact details
- Added nullable `gp_provider`, `clinic_address`, `clinic_phone` via schema v2 migration.
- Reviewer-confirmed contact fields pass through referral review and patient edit form to report doctor section.
- Current clinical snapshot includes GP/practice detail coverage.
- **Outstanding:** non-destructive migration and restore on an encrypted copy of an older workspace, plus real template page acceptance.

### Medicine refresh and held pharmacist-written Actions
- Identical, unambiguous medicine rows retain the pharmacist's typed Action.
- Changed directions/source notes, removed medicines, or duplicate ambiguous rows do not silently inherit clinical recommendations.
- Developer added `report_spec.held_actions.json` as a separate encrypted, strictly validated record, with an explicit UI list and resolution action.
- Build and sign-off block while unresolved medicine Actions remain; text persists over saves and refreshes.
- **Outstanding:** actual installed-app HTTP journey of three medicines, change/duplicate, refresh, hold, review/re-enter, mark handled, restart and build; check backup/restore of held record.

### Snapshot digest compatibility
- Developer introduced contract marker 2 for new reports and legacy comparison for unmarked historical evidence.
- Tests cover added, changed or removed GP details and signed/unsigned legacy reports.
- **Outstanding:** encrypted legacy report round trip on a disposable prior-version database; do not auto-rewrite signed build evidence.

## 3. Senior fixes performed independently

### P1 — Same-name duplicate-patient DOB comparison
File: `HMR Desk/engine/referral_entry.py`.

**Failure:** `01/02/1940` and `1940-02-01` were both individually valid yet compared as different strings. A split acknowledgement could create a second patient identity with the same DOB.

**Fix:** parse supported DOB representations to a canonical ISO date for comparison only, preserve legacy stored strings, reject equivalent DOBs as a split, and require genuinely comparable identifiers when permitting a distinct same-name patient. Placeholder/non-numeric identifiers and unparseable legacy DOBs do not establish difference.

**Tests:** `test_handover_safety.py` covers supported DOB formats, same-person collision, unparseable legacy records, and valid different-person case. The broader baseline identity regressions also ran.

### P2 — Clinical export can be left truncated after failure
File: `HMR Desk/engine/records.py`.

**Failure:** an `xb` target is visible before writing and `fsync` finishes. When disk I/O fails, the target is left behind, and a later export can report that the incomplete file already exists.

**Fix:** fully write and flush a sibling temporary file, then publish atomically with no-overwrite hard link, and always remove the scratch file. The unencrypted export warning is published through the same routine.

**Trade-off:** hard links are unsupported on some remote, FAT or nonstandard filesystems; this version fails safely rather than returning an incomplete export. Before release consider a documented, separately audited cross-filesystem export strategy that retains atomic publication.

**Tests:** simulated sync failure, hard-link denial, retry, complete-file verification and signed-file preservation in `test_handover_safety.py`.

### CI completeness
The developer's WIP source contained two substantive new suites that were absent from the workflow's explicit test list: `test_report_held_actions.py` and `test_snapshot_contract_compat.py`. Added those and `test_handover_safety.py` to the fast and standalone Windows CI test lists, instead of accepting old green checks that never ran them.

## 4. Verification with evidence

Functional commit under test: `08262a8c2bd5f14b5abddf209cb38f6cecf3457c`.

- **Clinical privacy contract:** PASS — GitHub Actions run `44844398447`.
- **Fast synthetic backend regressions:** PASS — run `44844398511`; `643 passed, 3 skipped`; 11 additional backend tests passed.
- **Desktop regression:** PASS — 495 passed, nine skipped.
- **Synthetic UI visual check:** PASS.
- **Windows standalone packaging:** run `44844398439` was still running when this handover was written. Its frozen engine build and startup and synthetic Windows DPAPI draft crash/restart had passed. Do not mark the installer and installed-app gates complete until the final run result is recorded.
- No actual patient document, personal Windows 11 workstation, licensed medical portal or original owner's Word template was used for acceptance.

Test evidence: https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/44844398511

## 5. Known limitations, risks and follow-up priority

1. Run the ten synthetic acceptance cases in `docs/clinical-acceptance-matrix-nov21.md` in the final Windows build and collect hashes and screenshots of fictional output.
2. Validate the approved DOCX layout with GP Plan OFF and ON: row width, page breaks, running headers, blank plan cells, GP details, and exported PDF.
3. Validate v1→v2 encrypted migration on a *copy* with restart/rollback and verify all existing patient records and report revisions.
4. Exercise full pharmacist Action workflow and check that a clinical note never disappears silently.
5. Resolve a clear product policy for the separate **original Word builder** branch: it requires private assets, Microsoft Word and a separate approval contract, and must not silently replace the optional GP Plan or offline standard rendering.
6. Validate real reference data only where the operator has appropriate legal rights; do not ship MIMS or patient-derived case indexes in source.
7. Do not call an engineering test pass clinical acceptance. Consent and sign-off stay under an accredited pharmacist's control.

## 6. What was deliberately not done

- No merge into `main`, no deployment to the owner's installed Windows app, no automated clinical transmission.
- Did not broaden the AI data boundary or introduce unsourced dosing/deprescribing rules.
- Did not include the separate original Word renderer and template-review aid here: that work is independently tracked in the renderer handover branch and requires careful compatibility validation.

## 7. Continuation for the next agent

Start from PR32 head and review any new pushes to `main` before cherry-picking. Run the three named test suites and the exact full CI jobs. Compare the current branch with its tested functional SHA after any documentation-only changes. Record the final installed smoke result, then conduct Word/PDF visual and pharmacist acceptance. Do not fast-forward a draft merge solely because checks are green.

**Signed status:** Independent code review + synthetic engineering tests. **NOT** clinical validation or owner approval.
