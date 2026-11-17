# Brainstorm MMR V2.0 - structured tables

`brainstorm-mmr-v2.0-tables.json` is the extracted, field-structured content
of the privately supplied "Brainstorming | Medication Management Report"
reference, **edition V2.0, November 2025**.

## Source and attribution

- The source document's cover credits **Karim Nouman, Consultant Pharmacist**
  as its writer.
- Source PDF: 207 pages, 5,191,503 bytes,
  SHA256 `a09b0592bf3c994070b3bd5ffd3d196b86a38fa8b028374cc04025b3dff93b62`.
  The PDF itself is **not** included in this repository.
- Included here on Es Abas's confirmation (2026-11-17) that the credited
  author gave permission for its use and that the tables carry no
  restrictions. Underlying third-party sources cited inside the document
  (it references eTG and AMH) keep their own terms; this file does not
  grant any further rights over them.

## Clinical status - read before use

- This is a **writing guide**, not validated current clinical rules. The
  document's own notice (page 4) states the clinician remains responsible
  and recommendations must be checked against current sources.
- Extraction preserves the source text verbatim (raw strings, including
  line breaks). No clinical interpretation, validation, currency or
  correctness check has been applied, and a text match never implies
  medical relevance or endorsement.
- Review status for any use in the app remains
  `pharmacist_review_required`.

## Structure

- `source`: PDF hash, page count, byte size, edition.
- `entries[]`: 448 marker-headed sections in document order. Each has
  `ordinal`, `title`, `page_start`/`page_end` (physical PDF pages),
  `content_sha256` (change detection), and `fields[]`.
- `fields[]`: labelled partitions of the section text. The label vocabulary
  (`Issue to Consider`, `Suggested Action`, `Reference`, the renal-card
  fields `Clinical Use`, `Dose in Normal Renal Function`, `Metabolism`,
  `Dose in Renal Impairment (eGFR)`, `Dose in RRT`,
  `Important Drug Interactions`, `Other Information`, and others) was
  observed in this edition and is defined in
  `HMR Desk/engine/brainstorm_tables.py` (`KNOWN_LABELS`). Labels may
  appear with or without a trailing colon in the source. A leading field
  with label `""` holds text before the first label; sections that are
  prose or phrase lists (111 of 448) keep their full text unlabelled.
  Colon-led lines outside the known vocabulary stay inline in the
  surrounding field and are counted under
  `extraction_report.unknown_label_lines` - nothing is dropped.

## Extraction and verification

- Extracted by `HMR Desk/engine/brainstorm_tables.py` (PyMuPDF), which
  builds on the marker-heading parser in `brainstorm.py`.
- Verified by an exact round-trip check: rebuilding each entry from its
  fields reproduces the source section text after whitespace
  normalisation, for all 448 sections (`roundtrip_problems: []`).
  Spot-checked visually against rendered source pages.
- `to_sqlite()` writes the same structure to a private local SQLite
  database (tables `brainstorm_source`, `brainstorm_entry`,
  `brainstorm_entry_field`) for the app's private installer path, and
  refuses to store an extraction that fails verification.
- Tests use synthetic fixtures only (`test_brainstorm_tables.py`); no real
  reference content appears in tests.
