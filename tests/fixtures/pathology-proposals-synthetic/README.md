# Synthetic pathology fixtures (HMR Desk)

Purpose: test material for a future "proposed unverified pathology rows from PDF" feature. NOT an implementation, NOT evidence the app extracts anything today (today it extracts no rows).

Everything is invented: fictional lab, patient, result values and dates (chosen for this pack and not copied from any real report or patient file; generic values may still coincide with values used in other synthetic tests). Reference-interval strings are generic textbook-style ranges, not copied from a lab report. No real report, patient file or proprietary layout was copied. Safe for the public repo. Real patient PDFs must never be added.

Files: `generate.py` (deterministic, needs PyMuPDF; regenerates PDFs and expected.json), 20 `pNN_*.pdf`, `expected.json`.

## expected.json
Per case: description, traps, `expected_rows` (test, value, unit, reference_interval, sample_date as ISO, flags). Empty-string field in expected output means "leave blank and flag", not "unknown but fine". Scoring should report, per field, exact-match rate, blank-with-flag rate and WRONG rate separately. The only acceptable wrong rate is zero. Do not collapse into one accuracy percentage.

## Decisions the implementer must make explicit (not decided here)
- D1 Dates: expected `sample_date` is the PROPOSED ISO date at proposal stage. Slash dates are read as dd/mm/yyyy and must carry the row flag `date_format_assumed_dmy`; every case declares `meta.date_flags` explicitly (generator refuses to write a case without it). That is a proposal only: an ACCEPTED row still needs a real ISO date and the existing verify gate is unchanged. Missing date: blank plus `sample_date_missing_check_by_hand`.
- D2 One row per (analyte, date) when several dated columns exist. Never decide which column is "current".
- D3 Only flags printed on the report are copied (`report_flag_H/L`). No derived below/above-range flags and no clinical thresholds.

## Machine-readable expectations
`expected.json` `meta` per case: date_raw, date_proposed_iso, date_flags, required_page_flags (e.g. `scanned_read_original`), alternative_outcomes for the rotated page (exact rows, or zero rows plus `rotated_page_not_read`), row_flags_page2 for inherited dates, document_flag `incomplete_extraction` for the mixed scan case. Tests should assert these flags, not just row counts.

## Coverage
p01 single column; p02 two dated columns (different current and historical ALT columns, "-" no result); p03 total vs corrected calcium; p04 H/L flags, `<`, `>`, parenthesised and dash ranges; p05 unit variants; p06 wrapped analyte names; p07 footnote numbers; p08 no sample date; p09 textual date and reported-vs-sample date; p10 non-numeric results; p11 missing unit; p12 sex-specific ranges; p13 look-alike analytes; p14 unit inside result cell; p15 duplicate analyte same date; p16 rotated page; p17 multipage with inherited date; p18 decoy header numbers; p19 scanned image-only; p20 mixed text and scanned.

## Limitations
- Machine-generated, clean fonts, one invented layout family (left-aligned columns). Real labs differ: merged cells, graphs, coloured flags, multi-column panels, cumulative reports, landscape pages. Synthetic pass does not predict real accuracy; real-sample testing must stay private and local.
- p19/p20 scans are pixmaps of clean text at 150 dpi, easier than real scans. Add noisy/skewed variants and the "10mg" to "1 omg" style misreads when testing OCR.
- Expected values were written by hand next to the generator; review them once against the PDFs.
