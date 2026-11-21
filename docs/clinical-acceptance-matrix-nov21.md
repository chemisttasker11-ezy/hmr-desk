# HMR Desk — pharmacist acceptance matrix (synthetic data only)

**Candidate:** integrated clinical-workflow amendments based on draft PR #27.  
**Platform:** Windows 11 x64, non-administrator account, installed unsigned engineering build.  
**Release status:** NOT CLINICALLY ACCEPTED. Nothing here authorises production use or merging.

## Test discipline

Use fictional, uniquely labelled patient records and de-identified layouts only. Record actual app commit SHA, installed EXE and asset manifest SHA256, Windows version, operator, tester, report template version/checksum, test start/end and document hashes for every case. Do not use identifiable referrals, portal credentials or patient screenshots in CI, issue comments or public artifacts. Test AI OFF and network disconnected first. A synthetic renderer pass is *not* clinical approval.

Each case requires: intact original referral, accurate interview/history snapshot, saved and reopened clinical data, expected DOCX, independently opened matching PDF, and a failure screenshot only if fully fictional. Pharmacist must check generated text against the fictional source *line by line* before marking the case pass. Log time and manual corrections; compare the original main app and integrated build on the **same** inputs and same machine.

## Ten clinician-review cases

| ID | Synthetic scenario | Non-negotiable clinical/UX acceptance |
|---|---|---|
| C01 | Two-page searchable referral; complete demographics, five prescriptions, normal pathology | First import preserves original; documented referral and GP data are correct; DOCX and PDF match; case can reopen after restart |
| C02 | Scanned, rotated PDF; damaged OCR; unknown allergy status | Original page remains visible; unverified text is never silently confirmed; no false 'no known allergies' |
| C03 | Same name as existing fictional patient but distinct DOB/Medicare | Explicit duplicate review; no unsafe patient merge or overwriting a different record |
| C04 | Prescribed versus actual use differs; PRN use; one ceased drug; an OTC medicine and DAA | Each medicine goes to the correct current/ceased/OTC section; unknown directions stay unconfirmed; no stopped medicine implicitly treated as active |
| C05 | Complex pathology: missing units, dates, duplicate results, renal impairment requiring clinical interpretation | Source date, units, interval and verification state remain explicit; no invented result, eGFR, dose or clinical interpretation |
| C06 | Multi-issue long report; report formatting across multiple pages | Approved owner DOCX layout, bordered tables, header repetition, readable PDF, no clipped findings, no unresolved placeholders |
| C07 | Identical report with optional GP Plan OFF then ON | OFF has exactly four medicine columns; ON has a blank fifth 'GP Plan'; clinical row text and recommendations are unchanged; original files retained |
| C08 | Referral with GP provider number, clinic name/address/phone, then a corrected provider number | User can confirm/edit each field; doctor block reflects the saved source; changes invalidate stale report; blank source values remain blank |
| C09 | Handwritten review in medicine row, then refresh with one unchanged medicine, one changed use and one duplicate | Only exact unique unchanged recommendation survives; changed/ambiguous recommendation flagged for re-entry; old version remains accessible; no silent clinical carry-over |
| C10 | Offline restart, database backup/restore, interview consent and signoff after post-build correction | No external service needed; exact report source revision checked at sign-off; missing/invalid consent rejected; restored prior record preserved |

## Additional release gates

1. **Migration safety.** On a *copy* of schema v1, v2 upgrade adds nullable GP/practice fields, leaves old rows/attachments/hashes intact, tolerates restart, and recovers after forced stop. Do not downgrade v2 to v1 without restoring the old encrypted backup.
2. **Report accuracy.** Verify GP number/address/phone, referral date and patient phone in the actual approved owner layout. A code-level mapping test does not establish visual layout fidelity.
3. **GP Plan formatting.** Inspect both owner-template prototype and provisional renderers, Word and PDF, for 4/5 columns at A4 normal margins and 125%/150% screen scaling. Approval is not implied by passing synthetic tests.
4. **Privacy.** Verify encrypted records, protected backups, no PHI in logs or diagnostics, no internet traffic during AI-off manual mode, and no unintended SMS send or clinical report transmission.
5. **Real reference imports.** Test AMT/PBS/ARTG import and lookup with sources the operator can legally use; unknown or missing catalogue never implies a clinical match.
6. **Usability measurement.** Capture per-case total operator minutes, clicks/fields corrected, report document defects and recovery attempts. Claim a productivity improvement only if independently measured against `main`.
7. **Approval and deployment.** GitHub Windows CI is Windows Server runner evidence, not a clean Windows 11 end-user release. Obtain signed clinical template visual approval and pharmacist review on the exact candidate SHA. No automated transmission or clinical sign-off.

## Recording format

For each case, record ID, result PASS/FAIL/BLOCKED, exact commit SHA, installed application version, test evidence ID, report template checksum, DOCX/PDF SHA256, operator time, number of corrections, issue IDs and clinical reviewer decision.

**Stop-ship conditions:** invented clinical details, missing consent at sign-off, mistaken patient identity, silently discarded pharmacist recommendations, lost patient data, inaccurate GP identity, report file stale yet displayed current, invalid DOCX/PDF pair, unexpected network transmission, or unrecoverable Windows install/restore failures.
