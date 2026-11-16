# Clinical record conversion - state (WIP, unverified, not installed)

Branch: wip/m3-records-unverified. Status: saved clinical records are NOT protected. Nothing here ships.

Done: engine/records.py (store, import, export, name patterns) + test_records.py (8 tests, local only);
documents-path fallback in desktop/main.js.

Scope (Es approved "saved clinical records"): patient-folder interview.json, report_spec(.ai).json, confirmed_meds.json,
followup1/2.json, pathology_sources.json, pathology_records.json, reconciliation_review.json (+ .bak), MIMS interactions*.txt.
Also patient-derived files outside the folder: history-import-plan.json, Scheduled/_interview specs/*.json,
TO SORT/intake_corrections.json (need their own identity key, not patient id).
Not records: templates, drug_classes.json, clinics.json, Word/PDF/consent/source documents (separate design, stay plain).

Next: thread conn into steps.exists and report_auth/jobs/report revision checks; convert interview.py load/save
(DB transaction replaces file lock and manual rollback); then report.py, consent_sign, api, suggest, followup, pathology_*;
startup migration (verify-then-mark, conflicts left alone, plain files kept until verified retirement, no secure-erasure claim);
backup bundle; export API/UI labelled "outside the app's encryption"; docs; run fast list + affected suites.
Release status stays "saved records not protected" until conversion, migration and retirement are verified on Windows CI.
