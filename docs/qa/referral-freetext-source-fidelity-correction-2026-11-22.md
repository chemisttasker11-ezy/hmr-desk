# PR #41 — FreeText preservation correction and fresh-referral pilot

**Date:** 2026-11-22 Australia/Brisbane  
**Status:** Draft; clinical release HOLD.  
**Scope:** original-referral data fidelity. Do not merge PR #39 or PR #40 into this branch.

## Confirmed defect and owner direction

Previous PR #41 implementation deleted **all** PDF FreeText annotations from an in-memory PDF copy before extracting text. This was unsafe: typed additions may have been made by the referring doctor, not necessarily by the pharmacist during an interview. This could omit material clinical content despite retaining the original PDF on disk.

The owner has explicitly identified the **Declined** and **Expired** folders under Chemist 11 Google Drive / HMR Ongoing / Declined-Exp as a source of relatively untouched referrals. Blue/red text elsewhere consists of **typed** PDF notes, not handwriting. No colour-based or handwriting-based classification is justified. Do not interpret a PDF annotation as a pharmacist interview note merely because it is typed, coloured or stored in a FreeText annotation object.

## Corrective implementation

- `referral_source_text.extract_original_pages`: preserves native `page.get_text()` including FreeText annotations. It does not delete annotations or modify the in-memory or on-disk original. Returns bounded, page-numbered FreeText metadata and unverified text previews separately.
- `referral_entry.review`: retains original text through classifier and demographics extraction, supplies annotation evidence to the review response, and displays a source-attribution warning. Source metadata remains bound to the original PDF SHA-256.
- `desktop/renderer/intake.js`: displays a separate expandable FreeText review list, escaped for HTML safety, with a direct original PDF open control and no claim of author or accuracy.
- `interview.referral_text` and `geometry_table`: no longer delete FreeText annotations before parsing and medicine geometry pairing. A source-attribution clarification is preserved. Ambiguous pairing still falls back to conservative review rather than inferred directions.
- `scripts/intake/intake.py`: returns all native text and includes the FreeText attribution warning in its generated intake report/notes.
- `scripts/qa/referral_corpus_eval.py`: counts FreeText annotations **preserved**, not excluded; flagged documents remain manual review candidates. The private manifest is encrypted and no document values are committed.
- Fictional synthetic regression tests demonstrate native annotation retention, separate review evidence, source byte/hash integrity, production referral review path and standalone intake-script warning. None is a real-document accuracy claim.

### Specific clinical guard

Annotation text is not itself proof of **GP authorship**, original prescribing directions, medication reconciliation or any clinical verification. Later pharmacist typed notes may still be present in other folders, so differences require pharmacist adjudication and exact original-page evidence. The current work does not attempt to recover information from page-sized raster images; unread image regions still create a warning.

## Fresh corpus available for PRIVATE evaluation

Live read-only Google Drive discovery, without publishing any patient identifiers:

| Folder | PDFs | Non-empty Drive text preview | Empty Drive preview | Medication heading keyword |
| --- | ---: | ---: | ---: | ---: |
| Declined | 65 | 53 | 12 | 52 |
| Expired | 49 | 45 | 4 | 44 |
| **Total** | **114** | **98** | **16** | **96** |

Three Expired PDF filenames were marked CLAIMED; metadata does not prove every item is unannotated or a unique patient. These counts reflect Drive provider previews and keyword screening, **not** native HMR Desk OCR, medicine-row fidelity, page-level gold truth or field accuracy.

**Remaining private execution:** run local encrypted corpus evaluator on an authorised copy of all 114 original PDFs, inspect rendered source pixels and native words, verify each identity, medicine strength/form/direction and GP provider/referral date against independent pharmacist gold truth, split patients into development/holdout without contamination, and convert verified failures into fictional regression fixtures. Zero of the 114 originals was processed by the installed app in this session. No real patient data, patient filenames or identifiers should enter GitHub or CI.

## Evidence and release gate

Previous code SHA `5c915ba819588e54099b40db7bc66a483af19f52` had Windows fast regression and standalone Windows CI success, but still contained the incorrect FreeText exclusion and therefore **must not** be treated as adequate evidence for this fix.

The final revised PR SHA and exact-head CI outcomes must be verified after new code lands. Run focused synthetic tests, full Windows Python suite, Electron unit tests, Windows installer and installed smoke. Keep PR Draft and clinical release on HOLD until those gates and independent real-source accuracy / accredited pharmacist signoff are complete. Do not merge.
