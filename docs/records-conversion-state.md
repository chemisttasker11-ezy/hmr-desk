# Saved record conversion (WIP, unverified, not installed)

Branch: wip/m3-records-unverified. Saved records are NOT yet verified as protected. Do not merge or install.

## Implemented, tested locally with synthetic data only

- Saved interview, report spec, confirmed medicine, follow-up, pathology, reconciliation and MIMS text records use the SQLCipher database. Patient-derived interview specs, shared intake corrections and history-import plans use the same store. Free-text medicine entry remains valid.
- Startup migration copies recognized files and reads them back. Repeat-safe: it never replaces a differing stored record and never deletes files at startup.
- Settings shows tracked plain-copy counts. Export requires an explicit choice of patient or shared records. Shared records may cover multiple patients. A native dialog chooses the output folder. Exports are labelled outside the app's encryption; existing files are not overwritten. MIMS content stays under its licence.
- Explicit removal is separate from migration and export. A cancel-by-default native warning explains ordinary deletion, external editors, backups, synced copies and unchanged source documents. The generic page API cannot call this mutation.
- Removal reopens the committed SQLCipher database independently, checks integrity, and holds a writer lock while checking each file. Only exact byte matches are removed. Different/missing records, links, changed files and errors remain for review. Active tasks or unsaved database changes stop removal. There is no silent plain backup, no automatic conflict resolution and no secure-erasure claim.
- Synthetic regression tests cover removal followed by database reopen and readable export, shared files, conflicts, active tasks, unsaved changes, failed verification, links and a file changed during checking. The existing encrypted backup round-trip includes the records table.
- Medicine reference lookup is connected to the interview with an explicit pharmacist-selected link and an unlink action. Links carry source/code/display/release through saved records and report rows. Same-concept duplicate warnings do not change clinical use status. Editing a medicine name removes its stale reference link with a visible explanation; late lookup results are ignored when their record/row/name is no longer current. A read-only saved-interview medicine panel in follow-up shows links, referral vs interview directions and recorded use status, with an explicit warning that it is not a current medicine confirmation. It does not change follow-up fields or exported follow-up documents. No licensed medicine data is bundled.
- Latest local Linux engine run: 132 passed, 5 dependency warnings. Desktop node suite: 244 passed. CI fast list now includes records, medicine reference and pathology tests. These results are not Windows or clinical acceptance.

## Still unverified or out of this conversion

- This WIP has not had Windows CI, installed-app restart/migration/removal, native-dialog visual checks, or Word/PDF continuity testing. A separate earlier integration baseline passed CI; that does not verify this branch.
- Real AMT release installation and end-to-end lookup remain blocked on the data transfer. Synthetic lookup is not real-data acceptance. PBS/ARTG/signature interfaces, broader brand/generic relationships and deeper medicine-linked follow-up are not complete.
- Follow-up delivery-method fields still default to phone and lack video and structured patient preference. They have not been changed by this work. The PPA notice dated 29 October 2026 and October 2026 Program Rules describe new follow-up delivery choices effective 1 November 2026. This is a before-clinical-release compliance gap, not completed implementation. Sources: https://www.ppaonline.com.au/hmr-and-rmmr-follow-up-service-changes-from-1-november-2026 and https://www.ppaonline.com.au/wp-content/uploads/2019/01/HMR-Program-Rules.pdf
- Word/PDF, consent and original source/import files are still plain files. Legacy appointment plans, intake reports, SMS logs and referral_source.json are source/import files, not silently removed by this record conversion. Other backups, cloud copies, exports and disk remnants are outside the tracked-file check.
- A changed legacy record is deliberately retained rather than overwritten or deleted. Review/export of such conflicts remains a user task before claiming that tracked plain copies are gone.
- Linux renderer screenshots use a stub engine and synthetic data. They are not the packaged Windows application.
- Status remains conservative even after a synthetic removal succeeds. No clinical-ready, parity, all-data encryption or secure-erasure claim is made.

No PR, CI run, install or change to the test account is authorized by this file.
