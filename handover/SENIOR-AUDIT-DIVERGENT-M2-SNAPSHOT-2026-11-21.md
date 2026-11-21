# Senior handover — divergent local M2 snapshot reconciliation

**Date:** 21 November 2026, Australia/Brisbane  
**Repository:** `chemisttasker11-ezy/hmr-desk`  
**Historical source:** `wip/local-m2-divergent-snapshot` at `a67d4bccb09570cc2d2bed1c09f0243556c648a3`  
**Actual source-code commit:** `09545eee1e4c634163c9f6f80fd2b765777a25f9`  
**Historical root:** `b0a0a86ddeecf735d51798d6a3839978b5a948b7`  
**Comparison baseline:** `main` at `46d7df2457a34a866413c3dd8e6166fc0c823fe6`  
**Other review candidates:** PR #32 `review/hmr-senior-integration-main-nov21`, PR #33 `review/hmr-renderer-safety-nov21`  
**Status:** Source-preservation reconciliation complete to the extent possible from GitHub; **NO code port, no merge, no deployed clinical application, no new test run for this old branch.** This is a review-only draft handover.

## 1. Why this source must not be merged

- GitHub Compare returns `No common ancestor` between the historical snapshot and **each** of `main`, PR32 and PR33. That is not a merge conflict to resolve by overwriting files: it is unrelated Git history.
- Historical root has 300 tracked blobs and historical snapshot has 305; current `main` has 438. The 305 historical paths also exist in current `main`; there are **zero old-only tracked file paths**. Exactly 201 corresponding blobs are byte-identical; 104 have changed since the old baseline. Current `main` has 133 additional tracked files absent from the historical branch, including clinical routes, medication reconciliation, consent evidence, report status, sign-off checks and tests.
- The substantive work under review is the **19-file change between the old root `b0a0a86` and old source commit `09545ee`**, *not* every difference between the old full tree and the much newer `main`.
- The later `a67d4bc` commit adds three handover inventory paths and nothing to executable source. No historical patch or full tree was applied to main in this audit.

## 2. File-by-file disposition of the 19 source patches

The table records concrete GitHub code and blob comparisons. An identical *added-line set* is strong evidence of prior integration; it does not mean the complete file is identical or that new clinical acceptance has been performed.

| # | Historical changed path | Finding against current `main` | Decision |
|---|---|---|---|
| 1 | `.github/workflows/m2-fast-regressions.yml` | Historic test command is outdated. Current workflow already lists the historical report actual-use, saved-AI-assist, empty-POST, medicine-reference, reference-library, report and identity suites; PR32 and PR33 separately extend their focused test lists. | **Do not copy old workflow**; preserve current expanded gate |
| 2 | `HMR Desk/engine/jobs.py` | Historical fix `if manual.get('saved') is False` is present verbatim in main; protects a saved manual report from being restarted by AI assist. | **Already integrated** |
| 3 | `HMR Desk/engine/medicine_reference.py` | Historic `had_previous` logic is present in main's more advanced installer. Main additionally adds derived search indexes, separate content hashes, source/installed provenance and disk-space checks. Main returns `previous_retained` together with further metadata. | **Already integrated and extended**; reject older replacement |
| 4 | `HMR Desk/engine/report.py` | All 20 nontrivial added lines from the historical source patch occur in main, including `actual(...)` direction-confirmation behaviour. PR32 adds new held Action and GP/practice contract safeguards. | **Already integrated; PR32 continues it** |
| 5 | `HMR Desk/engine/service.py` | All six nontrivial added lines in the old empty-body POST handler occur in main. | **Already integrated** |
| 6 | `HMR Desk/engine/test_medicine_reference.py` | The old newly added install/rollback assertions are in main; main's tests are substantially expanded for indexed search and source/content integrity. | **Already integrated and extended** |
| 7 | `HMR Desk/engine/test_reference_library.py` | All seven nontrivial added lines are present in main, including refusal of an unregistered reference and symlink safety coverage. | **Already integrated** |
| 8 | `HMR Desk/engine/test_report.py` | ~98% of 273 nontrivial added historical lines appear in main. Remaining differences largely reflect newer module boundaries (e.g. `medicine_review` instead of `api`), new follow-up-decision policy, and additional PDF cleanup tests. The current file is not interchangeable with the old one. | **Do not overwrite**; verify newer test equivalents in CI |
| 9 | `HMR Desk/engine/test_report_actual_use.py` | **Identical Git blob** old vs main: `4ed5bf4f8a069636629e7e2c0bfe8c4746d689e8`. | **Already integrated exactly** |
| 10 | `HMR Desk/engine/test_report_assist_saved.py` | **Identical blob** `2789fc2992efb21f0160e6dbf61d6f59681aaa73`. | **Already integrated exactly** |
| 11 | `HMR Desk/engine/test_service_empty_post.py` | **Identical blob** `34c2f30fd419c6282bdb4c9c86372bef6930024a`. | **Already integrated exactly** |
| 12 | `desktop/main.js` | All eight substantive added lines from old activation-recovery patch are present in main. | **Already integrated** |
| 13 | `desktop/renderer.js` | Both substantive old UI layout/engine-state additions are present in main. | **Already integrated** |
| 14 | `desktop/renderer/settings.js` | All 13 nontrivial old medicine-reference install/status additions appear in main. PR32 adds GP Plan settings; PR33 adds an independently optional Word renderer. | **Already integrated; do not replace newer settings** |
| 15 | `desktop/src/restore-activation.js` | All 74 nontrivial historical added lines occur in main. Handles BOM config parsing, activation diagnostics/failure record and rollback safeguards. | **Already integrated** |
| 16 | `desktop/test/activation-diagnostics.test.js` | All 119 nontrivial added lines occur in main. | **Already integrated** |
| 17 | `desktop/test/restore-activation.test.js` | **Identical full-file blob** `e67d46cad0573ced13a8441ea5a57a1fbedd943e`. | **Already integrated exactly** |
| 18 | `desktop/test/settings-medicine-reference.test.js` | 65 of 66 added nontrivial lines occur in main; one remaining difference is the changed `setup` helper signature because main extended timer-testing support. | **Already integrated and extended** |
| 19 | `docs/m2-acceptance-matrix.md` | Most old added context is already present; the sole unmatched historical line is an obsolete pin to older candidates `bb3ea45`/`0db2612`. | **Do not regress acceptance tracking** |

**Important qualification:** The initial additive-line comparison is a *textual* reconciliation, not a complete semantic proof that every historical test passes in the present application. Main's newer code and tests should be treated as authoritative; an intentionally isolated targeted test on the present branch is a useful release gate, not a reason to import stale files.

## 3. Two unique older-root files

The developer's inventory identifies `HMR Desk/engine/db.py` and `HMR Desk/engine/test_referral_identity.py` as the two blobs at unrelated root `b0a0a86` not previously identical to origin. They are preserved in the historical branch.

**`db.py`:** the older version lacks later Windows lock-file PermissionError retry handling; key-rotation locking; safe interrupted encryption recovery; protection from creating an empty database when an encrypted migration is unfinished; and safer backup rotation/replacement. Its replacement would be a significant security and data-loss regression. **Keep current main.**

**`test_referral_identity.py`:** its functional test cases and all function names match the current counterpart. The visible difference is an old fictional test name versus the newer fictional name. **Do not replace current main.** PR32 independently fixes an actual same-name DOB-normalisation weakness.

These are historical source-preservation items, not evidence of two missing features.

## 4. Additional local inventory / dependency lock diff

- `handover/inventory/LOCAL-WORK-ACCOUNTING.md` is now in the historical branch. It enumerates local candidate worktrees, tracks which code was already published, distinguishes the divergent root and records private dependencies.
- `handover/inventory/rebuild-297e780-desktop-package-lock-peer-flags.diff` is preserved with UTF-8 BOM and CRLF line endings. Its hunks add/remove only `"peer": true` package metadata flags at numerous lockfile entries. It does not add a named dependency, version, source URL or integrity hash. Do **not** apply churn blindly: `desktop/package-lock.json` is currently byte-identical between the historical snapshot and main (`01f079348d6ddb9edba08887fefa5f5b39e9f473`). Re-generate the lock only if a deliberate npm version/dependency update demands it.
- A 2-line `handover/MANIFEST.sha256` now exists for the inventory note and peer-flags diff. The hashes listed have not independently been computed in this connector-only review; do not misstate them as cryptographically verified.
- The developer's inventory also reports two local private brainstorm-derived tables (500,687-byte JSON plus 138-byte manifest). They are **not published**, and their omission is intentional. Keep them local and never introduce patient-derived data or proprietary reference material into the repository.
- The earlier two-branch `handover/HANDOVER-HMR-DESK-WIP.md` manifest still refers to `patches/` and `pr29-stack/` that were not included in the published branch. Avoid claiming its source patch archive is complete until the developer verifies that separately.

## 5. Reviews and tests actually performed here

**Verified using the private GitHub connector:**
1. Read current and historical branch heads, the two source commits, and their exact original-root relationship.
2. Confirmed no shared ancestry between the historical snapshot and main/PR32/PR33; the only valid commit comparison is to root `b0a0a86`.
3. Listed all 19 changed code paths and the later three inventory paths.
4. Compared complete reachable Git tree blob paths/SHA identifiers: 305 historical and 438 current blobs, zero old-only paths, 201 same SHA, 104 changed.
5. Inspected individual old patch hunks and searched their added lines in the current file counterparts.
6. Read current medicine-reference installer and earlier original implementation; current report, service, UI and restore changes; the 2 older-root unique files; inventory accounting and package-lock diff.
7. Checked that three historical synthetic test files and the restore activation regression are fully identical to main.
8. Verified the current Windows fast workflow already explicitly includes all three older new report/POST suites and relevant catalogue/reference suites.

**Not done:** no checkout or test execution of the incompatible historical branch, no local Windows application installation, no original private assets, no medicinal catalogue licence verification, no interpretation of private patient reports, and no combined PR32/33 merge. This review-only PR intentionally changes only this Markdown document, not executable code.

## 6. Recommendation to the lead developer

**Disposition: archive and do not merge the divergent historical branch.** It has preserved the older work and lockfile diff, but the new baseline already contains its functional source additions. Porting files would revert newer privacy, clinical sign-off, key rotation, migration, report and desktop protections.

1. Continue PR32's clinic/GP Plan/held-Action review and PR33's optional original Word renderer review independently, with their own detailed `handover/` documents.
2. Complete the exact-head Windows installer+installed-app smoke tests, and pharmacist-owned synthetic end-to-end report acceptance before merging either.
3. Avoid a mandatory Word dependency in the default path; original Word COM integration is a separate optional capability and must not silently ignore GP Plan settings.
4. Compare the original renderer's private Word and PDF outputs visually and document signature/template approval before allowing sign-off.
5. Maintain the current package lock; treat the peer-flag diff as provenance only.
6. Use the historical snapshot as an archived reference for any future investigation of a specific bug; work from current main for implementation, and rerun current tests after every targeted change.

**Release decision:** Nothing in this historical handover establishes an outstanding missing source-code feature or warrants a merge. Main and the two active senior review PRs remain subject to their own clinical release gates.

**Handover is complete as a GitHub-source audit; source recovery from the user's local machine was not attempted.**
