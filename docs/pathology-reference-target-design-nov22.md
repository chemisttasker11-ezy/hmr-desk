# HMR Desk pathology reference / clinical target architecture

**Status:** design and implementation requirements; not an approved clinical target engine. 22 November 2026.

## Separate three truths

1. **Laboratory observation** - verbatim analyte, result, unit, original lab interval, qualifiers, flags, specimen date, method, original page/cell and hash. Never alter imported values or replace missing fields with a plausible estimate.
2. **Guideline evidence** - independently maintained, versioned, licensed or publicly permitted source with publisher, publication/update date, URL, recommendation section, patient-population qualifiers, units, contraindicating conditions, and date last reviewed.
3. **Patient-specific therapeutic target** - explicit clinician-reviewed and accepted goal with indication, eligibility, review date, provenance and override rationale. A numeric lab interval must never silently become a care goal.

## Source hierarchy (Australia)

- The individual laboratory's printed reference interval is the first reference for its specific assay; use RCPA Manual and laboratory-specific assay guidance to resolve test nomenclature/limitations, not replace the laboratory interval wholesale.
- Kidney Health Australia / CARI / KDIGO for renal interpretation; keep eGFR, uACR, creatinine and calculated estimates separate. Persistent CKD assessment needs time/context; one reading is insufficient. Avoid automatic medicine-dose guidance.
- RACGP diabetes management for HbA1c and glucose targets; targets depend on frailty, hypoglycaemia risk, comorbidities, prognosis, pregnancy and individual goals.
- Australian CVD risk guideline and current disease-specific lipid guidance for cardiovascular goals; do not make an isolated lipid reading equal a risk-stratified patient target.
- Australian Medicines Handbook and licensed eMIMS for drug-specific monitoring (do not bundle or upload copyrighted content without permission).
- Thyroid, anaemia, electrolyte, bone-mineral and anticoagulant targets: source- and indication-specific; do not hardcode universal normal/optimal values.

## Future schema (separate from existing accepted pathology row)

```json
{
  "test_code": null,
  "test_name_raw": "",
  "result_raw": "",
  "unit_raw": "",
  "lab_interval_raw": "",
  "specimen_date": "",
  "laboratory": "",
  "assay_or_method": "",
  "source_document_sha256": "",
  "source_page": 1,
  "source_cells": {},
  "review_state": "unverified",
  "clinical_context": {
    "conditions": [],
    "medicines": [],
    "age": null,
    "pregnancy_status": "unknown",
    "frailty": "unknown"
  },
  "target_candidate": null,
  "target_selection": {
    "status": "not_selected",
    "selected_by": null,
    "selected_at": null,
    "reason": null
  },
  "guideline_reference": {
    "publisher": "",
    "title": "",
    "version_date": "",
    "url_or_licensed_id": "",
    "section": ""
  }
}
```

## Gate checks before any clinical target implementation

- Cite actual up-to-date source content and verify guideline rights, expiry, section, applicability and exception clauses. Show the quoted source or a link, not a fabricated reference.
- Use explicit test terminology and code mapping only after pharmacist confirmation (e.g., total and corrected calcium are distinct).
- Make laboratory reference, condition-dependent guideline objective, and agreed patient target visually separate.
- Ambiguous units, unknown assay, mixed result dates, unknown sex or pregnancy status, severe frailty or inconsistent diagnoses => no numeric target inference.
- No change to current report, findings or external AI payload. Targets only after explicit pharmacist review of matched source and patient context, with source revisions guarded.
- Every proposed result and target stores reviewer trail; editing invalidates the corresponding verification.
- Native Windows and authorised private real-case acceptance are required before clinical release.

## Private real-world accuracy assessment

Use the owner's prior pathology reports, when original bytes can be securely accessed, as **private evaluation data**, not unrestricted model-training uploads. Never copy patient PDFs, identifiers, screenshots, raw values, licensed lab assets, or descriptions identifying a patient into GitHub, Actions, issues or third-party services.

Report per layout: test exact-match %, value exact-match %, unit %, printed interval %, sample-date %, column association %, extraction abstention %, wrong-field errors, and source-cell match %. Deduplicate patients and report versions. Create only fictional, non-identifying reproductions of discovered failure patterns for committed regression fixtures. A text-layer OCR match cannot substitute for pixel-side validation.

**Current branch scope:** bounded digital PDF proposals and unverified acceptance. Scanned pathology OCR and patient-specific numerical therapeutic targets remain future stages pending separately documented evidence and authorisation.
