# Milestone 2 — Manual HMR foundation

The non-AI route is intentionally independent of any configured clinical AI agent.

## Implemented

- `GET /api/patients/{id}/reconciliation`: read-only source-indexed
  checklist, with deterministic flags for unconfirmed medicine use, actual
  directions missing, referral-versus-actual discrepancies, undocumented
  cessation and potential duplicate medicine names.
- `manual_defaults.py`: local administrative text defaults. It deliberately
  does not fabricate the review indication or patient interview narrative.
- `local_report_builder.py`: bundled DOCX output from the reviewed report
  specification. Existing report outputs cannot be overwritten.
- The report-start and DOCX build paths no longer require the installed
  `australian-hmr-report` skill for template defaults or DOCX rendering.

## Clinical limitations and release checks

1. The reconciliation endpoint is advisory. The pharmacist must confirm the
   medicine name, strength, formulation, indication, dose, adherence, PRN use,
   cessation reasons and interactions; duplicate names are not proof of
   therapeutic duplication.
2. The built-in DOCX uses a **new generic layout**, not the pharmacist's
   historical Word template. Before production use, compare with an approved
   reference report for headings, tables, pagination, clinical style and
   professional sign-off.
3. Extraction from handwritten referrals, pathology import and optional PDF
   conversion still depend on existing helper workflows. They are **not**
   represented as fully self-contained.
4. Existing reports must be reviewed by a pharmacist before signing or
   sending. No automatic prescribing or claims submission is introduced.
5. Run the Windows desktop smoke suite, a synthetic complete patient
   lifecycle and an installation test before merging.
6. The reconciliation API currently exposes its checklist to the same
   authenticated local API client; UI integration remains to be done.

## Suggested acceptance scenario

Create a synthetic referral, enter a medicine as prescribed at 5 mg twice
daily but actually used at 2.5 mg twice daily, record an unconfirmed medicine,
mark another ceased without a reason, and record a duplicate name. Verify all
flags, confirm the list, create the manual report, enter pharmacist-authored
findings, generate the DOCX, and verify the report opens without an AI agent.
