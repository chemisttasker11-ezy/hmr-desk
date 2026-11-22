# Referral OCR / source fidelity — detailed senior engineering handover

**Date:** 22 November 2026, Australia/Brisbane  
**PR:** [#41](https://github.com/chemisttasker11-ezy/hmr-desk/pull/41), branch `feature/referral-corpus-ocr-source-fidelity-20261122`, base `integration/hmr-reviewed-nov22-v8`.  
**Status:** **DRAFT, CLINICAL HOLD**. This handover must not be mistaken for release approval.

## 1. Scope and source custody

The owner explicitly authorised read-only assessment of the fresh originals in Chemist 11 Drive, `HMR Ongoing / Declined-Exp / Declined` and `Expired`. Their prior blue/red interview notes are **typed PDF overlays**; they were not assumed to be handwritten or automatically stripped. Any FreeText annotation could have been added by the GP and must remain readable. A real 500+ referral folder on the owner's separate Windows machine is **not mounted** here.

All **114** private originals (65 Declined, 49 Expired) were fetched by the authenticated Drive connector and inspected in a local private directory under hashed, non-identifying filenames. This included **706 pages**. Original bytes were preserved. **Zero** original patient PDFs, text, screenshots, source hashes, per-file outputs, provider lists or patient identifiers were published to GitHub or CI. All real per-document outputs and OCR trials remained private and are **not** reusable synthetic gold standards.

### Native full-corpus metrics, source-date provenance

- PDFs opened successfully: **114/114**.
- Pages: **706**; pages with at least 25 native PDF text chars: **569**; text-sparse: **137**, all containing images.
- Raster-dominant pages (>=60% image coverage): **184**; image-present pages: **203**; nonzero native text plus >=20% image coverage: **47**; rotated PDF pages: **0**.
- Detectable FreeText annotation pages: **0** in this cohort (does not prove flattened notes absent).
- Heuristic document groups: **97** source referral candidates / **17** manual/unclassified, not independently adjudicated.
- Production parser classifications: **94 referral, 3 GP response, 17 other**; layout: **67 clinical summary, 22 HMR form, 24 scan/other, 1 old report**.
- Current parser generated **847 unverified medicine row proposals** in **87 documents**; **463** proposed rows contained directions; **41 documents** triggered unattributed-directions warnings; **80** triggered unparsed-section warnings; strict geometry whole-table pairing succeeded in only **6**.
- Identity proposals from production parser in 114 docs: name **92**, DOB **89**, GP **91**, GP provider **89**, Medicare **87**, phone **88**, referral date **78**, address **83**. These are output availability, **not correct-field recall**.
- A deliberately bounded 12 text-sparse-page offline OCR diagnostic returned some text on **4/12**, and no adequate text/error on **8/12**. The complete 137-page OCR diagnostic exceeded runtime; this is an open performance/robustness limitation, not a successful batch OCR benchmark.
- No independent pharmacist page-pixel truth, per-field exact scores, dual-reader agreement or sealed patient holdout yet.

## 2. Real-corpus defect reproduced and engineering changes

**Root cause:** `referral_page_audit.inspect_page` previously treated a large raster image as risky *only* if five or fewer PDF words overlapped it. Searchable scanned images with OCR-overlaid native words could therefore be incorrectly treated as complete text extraction. In the **47** private mixed-image/native-text pages, that old safeguard triggered **0**. The updated detector triggers on **47/47**, retaining distinct counters for unread image regions versus text-layer-over-image regions.

**Code changes on PR #41:**
1. `HMR Desk/engine/referral_page_audit.py`: every substantial raster region on a native-text page prompts source image review, even with many overlapping text words; emits counts for text-overlay and unread-image regions. This does not prove OCR correctness.
2. `HMR Desk/engine/referral_entry.py`: adds explicit searchable-scan warning. On a mixed PDF of **at most 10 pages**, executes the existing local OCR adapter for an **independent comparison preview**; sparse-text fallback retains its prior role. The OCR comparison string never flows into classification, identity, prescribed-medicine row pairing, or clinical review confirmation automatically. Changed source hashes are rejected. Larger mixed PDFs or unavailable OCR remain visual-review-only.
3. `desktop/renderer/intake.js`: escapes and displays supplementary OCR under a separate, unverified expandable review panel alongside the native text and open-original-PDF action.
4. FreeText safety from earlier PR #41 remains: GP-added or unknown-origin FreeText text is preserved with unverified page/rectangle metadata and pharmacist review, rather than deleted.
5. Fictional mixed-page regressions cover both un-overlaid image with native heading and searchable image with many overlapping native text words, plus conflicting OCR directions not being promoted into the patient proposal.

**Design tradeoff:** Unverified OCR comparison duplicates text in the browser but gives the pharmacist a second reading of the image. It does **not** solve table cell geometry for Windows OCR, scan skew/rotation, low-resolution failure, missing or truncated sections, or end-to-end report fidelity. The 10-page cap prevents uncontrolled supplementary OCR work but leaves larger cases with manual review. No external OCR service is called.

## 3. Existing PR boundaries

- Pathology PR #39 owns clinical laboratory row parsing and therapeutic reference targets. No pathology engine or clinical interpretation was changed here.
- Full-flow PR #40 owns patient isolation, interactions provenance, report authorization and hash-bound sign-off. No weakening of its checks or direct merge performed.
- PR #38's geometry row pairing remains conservative. An earlier slash-separated medicine-list example was entered manually, **not proven parser output**; do not repeat that attribution.
- Base remains stable integration branch. Clinical release must NOT merge until independently signed off.

## 4. Testing, exact evidence and important failures

Fictional-only Windows test workflow `referral-source-fidelity.yml` runs source preservation, real production referral entry, geometry, private runner and standalone intake synthetic tests, plus Electron intake renderer syntax. It does not upload patient data. Current exact-head test logs must be checked separately when marking the PR ready.

**Explicit preceding CI failure:** At code SHA `fc9c2482f197456bba2b005a4da0073acd2b66bb`, the full Windows backend suite failed `test_interview_intake_review.py::test_real_intake_four_medicine_source_to_saved_interview[image_layer]` because the test expected method `text`, whereas production correctly now marks `text+unread_image`. The test was updated to assert the stronger safety warning; do not revert the safeguard. Earlier focused runs passed, but are NOT current-head full release evidence. Verify current SHA, all run results, test counts and installer stage before declaring any CI result final.

## 5. Required work before clinical acceptance

1. In a protected local environment, label original rendered pages, identify **patient-level duplicates and revisions**, then split development, validation and sealed holdout **by patient**, never random page/file.
2. Independently adjudicate **at least 120 real referrals** across 500+ corpus where available (60 development, 30 validation, 30 sealed holdout as planned). The 114 Drive candidates cannot by themselves satisfy that target. Two readers should verify critical exact medicine/direction, patient and GP identity, allergy negation, pathology dates and units.
3. Improve OCR geometry from currently text-only Windows bridge; render and pixel-check mixed scans and OCR comparison. Isolate corrupted images and timeouts by page. Record proper word-/field-level denominators.
4. Fix source-proven bugs using original private pages + strictly fictional public regression PDFs; freeze parser before sealed holdout and do not re-tune against it.
5. Run true production referral->clinical review->commit->interview prescribed-vs-actual->save/close/reopen->reconciliation->DOCX/PDF comparison and clinical sign-off, not just helper tests.
6. Install on a clean **non-admin Windows 11 x64** user device, completely offline without separate tools; verify original image crop, OCR, failure handling and report/template. Cloud Windows CI is necessary but not sufficient.
7. Audit PDF source file confidentiality and Windows symlink/junction/reparse behaviour, and confirm secure handling of private locally cached reports, ZIPs and rendered pages.

**Final decision: HOLD.** The real-file layout census and the narrow source-detector repair are reproducible. No reliable field-level clinical acceptance is substantiated yet.
