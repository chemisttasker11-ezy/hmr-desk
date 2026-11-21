# HMR Desk: acceptance safety follow-up (21 November 2026)

Status: **engineering changes proposed for review; NOT merged; NOT clinically accepted.**
Base PR #35 at `39fc703a9a79eb555826340ca864ae1656b8fd66`. No production patient data, proprietary helper sources or credentials included.

## Verified baseline evidence

- GitHub Actions Windows fast regression 44882674045: **success**, whole Python backend **947 passed, 11 skipped**, desktop **504 passed, 9 skipped**. These figures refer to the PR #35 base, not to this follow-up branch.
- GitHub Actions clinical privacy 44882674024: **success**.
- GitHub Actions Windows standalone 44882674032: **success**, including frozen engine, bundled LibreOffice offline conversion, synthetic referral-to-signed-and-sent report, NSIS installer and packaged-app smoke. Artifacts: `hmr-m2-isolated-acceptance-app` and `hmr-m2-windows-unsigned-engineering-build`. Artifacts are unsigned engineering builds, **not** approved patient-use releases.
- The Windows runner is not a non-admin Windows 11 end-user machine. Real owner template and licensed helper workflows remain outside this CI.

## Changes in this review branch

1. `desktop/src/control.js`: add explicit refusal keywords for report Refresh, demographic keep/replace, restore and reset operations that can raise native dialogs. Snapshot requests now time out with a clear instruction when a native dialog blocks the renderer. **Only read-only snapshot requests are timed out**; never race click/fill actions because a queued write could run unexpectedly after timeout. This does not dismiss human confirmation or bypass safeguards.
2. `engine/report_auth.py`: a report carrying `interactions_evidence_sha256` is not signable when the saved interaction evidence digest changes after build. Older builds without a recorded hash retain their existing legacy behaviour; this change is **not** a clinical interaction-check policy and does not assert eMIMS was run. A changed evidence digest requires rebuild and pharmacist re-review.
3. Synthetic regression tests cover both controls and current-build interaction evidence change.

## Work remaining (do not mark PASS without named evidence)

| Item | Current evidence | Exact acceptance / next owner-host check |
|---|---|---|
| Non-admin Windows 11 install | CI Windows Server package smoke success | Install signed/unsigned engineering build in disposable standard-user profile; disconnect network; launch without Python/Node/Word; create, save, restart and reopen synthetic case. Record installer SHA, EXE manifest and screenshots containing **fictional identities only**. |
| C01 / C02 referral quality | Synthetic parsing and PDF-coordinate tests; operator noticed source text-layer OCR misreads and previously mis-paired directions | Re-import the affected referral in an isolated workspace; **line-by-line compare all names, strengths, form and directions against rendered source pages**, including row 21. Confirm Clarify warnings; do not assume text-layer spelling is clinically accurate. A referral with personal information must stay on the authorised host. |
| C03 / C04 / C05 | Unit and synthetic API tests | Confirm duplicate identity, actual/PRN/ceased/OTC, pathology provenance, values and missing units on the *installed app*. |
| C06 / C07 / C08 | Synthetic layout and earlier narrow host tests | Render short and long owner-approved DOCX and PDF; compare fonts, page breaks, borders, practitioner details and GP Plan OFF/ON, including no blank final page, in **Word and the PDF viewer**. Record approved template digest. |
| C09 held Actions | Operator previously observed two held entries and a stale panel; source now contains a panel refresh fix | Update one unchanged medicine, one changed dose and a duplicate; refresh after **human OK**; verify exact unchanged recommendation carried, two changed/ambiguous texts held, Build/sign blocked until individually handled; Save/restart/restore and recheck no old clinical text silently returns. Avoid automation clicking a native confirm. |
| C10 encrypted migration | Synthetic schema migration tests | On a **disposable copy** of an older SQLCipher workspace verify v1->v2, source attachments/hashes, restart, encrypted backup and restore, deliberate rollback via original backup. Do not run on sole production copy. |
| Original Word builder | Optional off-by-default adapter; Word COM fault `Documents.Open` null / `SaveAs2` 0x800A1066 previously reported | Separately reproduce with pinned authorised assets; do not enable/approve sign-off until resolved and Word/PDF matches approved template. Default standalone renderer must work without Word. |
| My Health Record / PRODA | Source integration, no live host proof | Patient pathology lookup before interview, user-controlled sign-in, safe no-results/unavailable flow, source provenance and later recheck. No credentials or identifying screenshots in GitHub. |
| eMIMS / PPA helpers | Helper presence/absence synthetic contracts; private scripts recovered; older browser scripts rejected as unsafe | Verify actual authorised helper versions on host, confirmed-list SHA, real interaction output filing to exactly one patient, rerun after medicine list changes, unavailable messaging and zero silent claims of successful checking. No licensed helper scripts published without rights review. |
| Ten-case clinical matrix | `docs/clinical-acceptance-matrix-nov21.md` | C01-C10 must each identify operator, exact commit, template checksum, DOCX/PDF SHA, PASS/FAIL/BLOCKED, pharmacist line-by-line check, issues and corrective actions. No inference from test counts. |

## Clinical policy decision still required

The current engine lets `report_build` and sign-off proceed without requiring an `automated_current` eMIMS result, while `report_start` normally requires interaction evidence. The hash change check above prevents **post-build evidence drift**, but does **not** close that workflow bypass.

Proposed policy for pharmacist approval:
- After actual medication confirmation, normally require an eMIMS result tied to the exact confirmed-list SHA and result-file SHA before report authoring and final approval.
- If eMIMS is unavailable/offline, allow an **explicit pharmacist-owned, dated and reasoned manual interaction review** (method, medicines covered, limitations, identity and confirmed-list digest); never assume an ordinary unverified note constitutes a complete check.
- Reject a stale or changed confirmed-list hash; invalidate any override when medicines change. Provide separate display of eMIMS result versus manual override and persist immutable event evidence.
- My Health Record pathology should be *attempted before interview when possible*, but unavailable/no-results and emergency visit paths need an explicit documented exception rather than fabricating results or silently preventing all offline care.
- These are **proposals, not implemented gates or approved clinical policy**. Do not auto-merge or silently change user workflow without pharmacist approval.

## Independent reviewer disposition

This branch reduces two definite hazards. It is intentionally not represented as completion of the entire acceptance matrix. Run Windows CI on the exact follow-up head and reconcile any failures. Then owner-host acceptance and pharmacist clinical review are the release conditions. No release or merge to main is authorised by this file.
