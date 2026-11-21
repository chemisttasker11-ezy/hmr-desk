# Senior handover — original report builder and template-review aid (independent stack)

Date: 21 November 2026 (Australia/Brisbane)  
Repository: `chemisttasker11-ezy/hmr-desk`  
Senior review PR: https://github.com/chemisttasker11-ezy/hmr-desk/pull/33  
Developer source: `handover-renderer-review-aid` at `6c3d87e0535984fc0ea3015c9a49c4ae9b9a1679`  
Base: merged `main` at `46d7df2457a34a866413c3dd8e6166fc0c823fe6`  
Companion clinical handover: PR #32 and `handover/SENIOR-REVIEW-PR32-2026-11-21.md` **on PR32**, not on this branch.  
Status: **DRAFT, UNFINISHED, NOT AUTHORISED FOR MERGE OR CLINICAL USE.**

## 1. Reconciliation of the actual push

- The developer's branch is three commits ahead of `main`, and does not contain the newer GP Plan/held Action work from PR #32. It must not be directly merged with PR32 without reconciling `jobs.py` and the report editor.
- The two branches share the identical 14,158-character `handover/HANDOVER-HMR-DESK-WIP.md` and identical `handover/MANIFEST.sha256`.
- That manifest references five files inside `handover/patches/` and `handover/pr29-stack/`. **Neither directory is in the published GitHub branch**, so the manifest is incomplete as a reproducible handover. The source code changes themselves are available through the branches, and were the basis of this review. Before declaring upload complete, the developer must reconcile the missing files against local dirty worktrees and verify actual byte hashes; do not invent their contents.
- The source handover itself cautions that a wider local candidate worktree and additional local changes have not yet been reconciled. Nothing in this PR claims to cover that unpublished local work.

## 2. Source features reviewed

### A. Original report builder
Files: `HMR Desk/engine/original_builder_adapter.py`, `jobs.py`, `engine_main.py`, `hmr-engine.spec`, and the original adapter and jobs tests.

- Existing report spec keys are mapped into an input for the owner's original Python builder, with unneeded internal keys omitted.
- Three locally held private assets are SHA-256 pinned: `build.py`, `Template - Copy.docx`, `word2pdf.ps1`. They are not in the repository. No real Word/template integration could be verified by reading source.
- A subprocess isolates the original builder (frozen engine uses an explicit CLI worker mode, source environment uses Python).
- The original builder's own Word-generated PDF is retained if requested; a second LibreOffice render is not substituted.
- Success checks include rendered files and the required Montserrat font in the Word PDF.
- The original path explicitly records `template_approved=False`, so **sign-off remains blocked** until owner approves an appropriate identity/template proof contract.
- The developer reported that Microsoft Word COM automation sometimes returns no document or a PowerShell failure even though manual Word opens succeed. No root cause was verified. This is a real-world stability gate before release.

### B. Template-review keyword aid
Files: `HMR Desk/engine/suggest.py`, synthetic tests, and `desktop/renderer/report-editor.js`.

- Adds a `Check first` list for medication-class or selected topic tokens mentioned in past-case recommendation templates but not found in the currently saved evidence context.
- It does not rewrite the wording, invent facts, validate doses or replace pharmacist review/sign-off.
- **False-negative risk:** vocabulary is deliberately small (e.g., CKD abbreviations, alcohol, nausea, reflux, dementia are not comprehensive). **False-positive risk:** synonyms and negation patterns can misclassify support. No flag does not mean verified.
- The UI shows the wording as a visible caution, not as clinical truth.

## 3. Senior safety and usability changes actually made

### C. Atomic no-clobber report publishing
File: `original_builder_adapter.py`.

**Failure found:** when the staged source and target are on different volumes or hard links fail, the developer's fallback copied bytes directly to `open(target, 'xb')`. An I/O failure or full disk could leave a partial final DOCX or PDF that looks like a completed clinical report. This resembled the separate P2 records export bug fixed in PR #32.

**Correction:** first try the direct no-overwrite hard link; otherwise copy to a private sibling temp file inside the *target destination directory*, flush + `fsync`, then publish with a no-overwrite hard link and delete the temporary file in all cases. Never fall back to streaming bytes into the final report path. Unsupported hard-link filesystems now fail visibly and do not leave partial final output.

**Synthetic tests:** cross-volume link error, completed sibling publish, unsupported hard links, disk-full/sync failure, no-clobber existing signed target and cleanup.

### D. Frozen report-builder CLI pin validation
File: `original_builder_adapter.py`.

**Risk found:** `hmr-engine.exe --original-builder-worker <script> <spec>` accepted a script pathname directly and executed it with `runpy`. The parent checks pinned assets, but a direct invocation of the frozen worker could bypass parent validation.

**Correction:** the frozen worker checks argument count, script name, symlink status and all three expected pinned hashes next to the builder before execution. Invalid assets return a fixed failure code without executing an untrusted script. Source-mode unit tests use an explicitly simulated frozen environment to check rejection and accepted pinned synthetic fixture.

**Remaining security caveat:** a locally runnable CLI and owner-controlled script have a different trust model from the user-facing Electron UI. The asset pins are a safety check, not a sandbox; a production hardened worker should also validate provenance of the spec input and parent/child invocation boundary, and the embedded original builder must be reviewed independently.

### E. Original Word renderer now explicitly opt-in
Files: `settings.py`, `jobs.py`, `desktop/renderer/settings.js`, `test_original_builder_jobs.py`.

**Problem found:** mere presence of `<DATA_DIR>/original-report-builder` silently replaced standalone report output with Word COM rendering, including an unsigned/unapproved report path. This conflicted with the primary promise that the manual workflow runs without Word.

**Correction:** new Settings → Reports boolean `report_use_original_builder`, default **OFF**. If OFF, retain current standalone owner-template/provisional renderer, even when private assets exist. If ON but private assets are missing, report an explicit error; never silently switch modes. Tests cover opt-in and absence.

**Product conflict still open:** PR #32 introduces another Reports setting for an optional fifth blank GP Plan column. The original builder's private template cannot be assumed to honour this option. During eventual integration, turn on original-builder mode only if the user explicitly selects it, and block with an explicit explanation if GP Plan is ON and the Word template cannot honour it. Do **not** silently ignore the GP Plan choice.

### F. CI coverage added
- Added `test_original_builder_adapter.py`, `test_original_builder_jobs.py`, `test_original_builder_publication.py`, `test_suggest_template_mentions.py` to both the fast Windows backend and Windows package workflow explicit test lists.
- Newly added publication tests do not use real clinical data, private assets or Microsoft Word. Other baseline regression tests remain unchanged.

## 4. Tests and evidence classification

Functional source baseline for this review: `handover-renderer-review-aid` `6c3d87e`.

**Developer claim, not independently rerun on the final branch:** 24 original adapter/jobs tests on Linux using fake workers and five keyword-aid tests; developer also reports that a true Word COM end-to-end run had *not* succeeded on the handover build.

**New senior tests:** focused on atomic publishing and pinned frozen-worker dispatch, triggered through the CI integration branch and tracked on PR33. Check the exact final PR33 SHA and both workflow result pages before recording PASS here. Until those workflows finish: **NOT VERIFIED GREEN on final candidate**.

Synthetic CI cannot establish Word COM reliability, Montserrat embed correctness in an actual report, licensing rights for local assets, fidelity of the owner's signature block, or approved clinical use.

## 5. Outstanding blockers and prioritised next actions

1. Resolve any CI failures introduced by the opt-in setting, adapter worker or new publication tests on the final PR33 head.
2. Verify clean non-admin Windows installation with no Word: choose the default OFF mode and finish an entirely offline fictional report. Record version and DOCX/PDF hashes.
3. On an isolated Windows PC *with Word*, install the owner's private pinned assets locally and explicitly enable original mode. Use a synthetic patient; verify Word COM launch, file creation, actual embedded Montserrat, long report pagination, graceful timeout and cleanup. No real patient details in CI.
4. Test repeated runs: no existing DOCX/PDF overwrite, recovery after failed Word COM, crashed process handling, successful build evidence and correct sign-off refusal.
5. Review the original owner template visually. Decide whether it is approved, who approves it and what template-version hash or in-app registration would permit clinical sign-off. Until then it must remain unapproved.
6. Reconcile the overlapping `jobs.py` and `report-editor.js` changes with PR #32, including held medicine Actions, snapshot contract 2, GP provider metadata, optional blank GP Plan and build-evidence fields. No unrelated behavioural changes.
7. Conduct a clinical review of keyword-aid false positives and negatives using only synthetic cases and accepted reference data; preserve the existing requirement to mark imported template wording reviewed.
8. Ask the original developer to complete local-folder reconciliation and publish a truthful list of files **not pushed**. Verify the original manifest's patch hashes only after the patch files exist.
9. Check the Windows-installed version rather than relying on GitHub Actions' Windows Server simulation alone. Conduct the owner-approved ten-case acceptance matrix with a pharmacist.

## 6. Merge and release policy

- Leave PR32 (clinical and data safeguards) and PR33 (Word builder and template aid) as **independent draft PRs** until explicit joint integration testing. Do not merge both blindly, and do not merge or deploy any draft without owner approval.
- The main manual app must remain offline and usable without installed Python, Node or Word. An optional Word plugin cannot weaken this contract.
- No user credentials, clinical records, private signature templates, licensed MIMS assets, or actual patient cases should be committed.
- This handover is source review + synthetic engineering work only; it is neither owner-approved visual fidelity nor a declaration that a product is ready for clinical work.

## 7. Continuation pointer

Review PR33 against `main`. Read its commit diff rather than replaying missing developer patch files. Confirm test CI on the exact head SHA. For later full integration, base a new branch on the accepted PR32 candidate and port only the original renderer and template-aid modules plus vetted changes to `jobs.py` and `report-editor.js`. Update evidence and tests for both renderer modes. Keep a detailed new handover of the merge decisions and failures.

## Addendum: build script path and Python discovery

- Finding (source reading, same on origin/main): `scripts/build-windows.ps1` and `scripts/bundle-libreoffice.ps1` used single-quoted PowerShell paths with literal doubled backslashes, which PowerShell keeps as two separators. The script also assumed the `py -3.12` launcher.
- Change: paths use one separator and `Join-Path`; one `$venvPython` is reused. `Find-BuildPython` tries `HMR_PYTHON` (full path to a python.exe), then `py -3.12`, then `python3.12` and `python` on PATH, and accepts only version 3.12. If none qualifies it stops with a message naming `HMR_PYTHON`. No host path is in the repo.
- Tests: `test_build_script_contract.py` (static text checks, 3 tests). Plain pytest 899 passed, 1 skipped at this commit.
- Unverified: PowerShell was not run here. Whether the doubled separators alone caused the reported ObjectNotFound is not confirmed. An unmodified run of the committed script on the Windows host is still required.
