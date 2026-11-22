"""Synthetic pathology fixtures for HMR Desk. ALL data invented: fictional lab, fictional patient,
fictional numbers. Not copied from any real report. Run: python3 generate.py  (needs PyMuPDF).
Writes PDFs plus expected.json next to this file. Deterministic."""
import json, os, fitz
OUT = os.path.dirname(os.path.abspath(__file__))
HDR = ["FICTIONAL PATH LAB (synthetic test document)", "Patient: TEST, EXAMPLE   DOB: 01/01/1900   Ph: 0400 000 000", "Lab address: 1 Example St, Nowhere 0000   Ref no: 000000"]

def page_doc(doc, header, cols, rows, notes=(), rotate=0, title_note=None):
    page = doc.new_page(width=595, height=842)
    y = 50
    for h in header:
        page.insert_text((40, y), h, fontsize=9); y += 14
    y += 10
    for x, t in cols:
        page.insert_text((x, y), t, fontsize=9, fontname="hebo")
    y += 6; page.draw_line((40, y), (555, y)); y += 14
    for r in rows:
        for (x, _), cell in zip(cols, r):
            for k, line in enumerate(str(cell).split("\n")):
                page.insert_text((x, y + 10 * k), line, fontsize=9)
        y += 14 + 10 * max(str(c).count("\n") for c in r)
    y += 8
    for n in notes:
        page.insert_text((40, y), n, fontsize=8); y += 12
    if rotate: page.set_rotation(rotate)

C1 = [(40, "Test"), (210, "Result"), (290, "Units"), (360, "Reference interval")]
def E(test, value, unit, ref, date, flags=()):
    return dict(test=test, value=value, unit=unit, reference_interval=ref, sample_date=date, flags=list(flags))

cases = {}
def case(cid, desc, build, expected, traps):
    cases[cid] = dict(description=desc, build=build, expected=expected, traps=traps)

def one(cid, desc, header, cols, rows, expected, traps, notes=(), rotate=0):
    def b(doc): page_doc(doc, header, cols, rows, notes, rotate)
    case(cid, desc, b, expected, traps)

D = "2026-02-14"
one("p01_single_column_basic", "One dated result column, plain units.", HDR + ["Collected: 14/02/2026"], C1,
    [["HbA1c", "5.9", "%", "<6.5"], ["Ferritin", "88", "ug/L", "30 - 400"], ["Magnesium", "0.82", "mmol/L", "0.70 - 1.10"], ["ALT", "27", "U/L", "<35"]],
    [E("HbA1c","5.9","%","<6.5",D), E("Ferritin","88","ug/L","30 - 400",D), E("Magnesium","0.82","mmol/L","0.70 - 1.10",D), E("ALT","27","U/L","<35",D)],
    ["header date is dd/mm/yyyy and not repeated per row"])

CT = [(40, "Test"), (190, "14/02/2026"), (270, "09/08/2024"), (350, "Units"), (410, "Reference interval")]
one("p02_two_dated_columns", "Current and older result columns. Older value must never be reported as current.", HDR, CT,
    [["ALT", "27", "44", "U/L", "<35"], ["AST", "24", "29", "U/L", "<40"], ["Ferritin", "88", "-", "ug/L", "30 - 400"]],
    [E("ALT","27","U/L","<35",D), E("ALT","44","U/L","<35","2024-08-09"), E("AST","24","U/L","<40",D), E("AST","29","U/L","<40","2024-08-09"), E("Ferritin","88","ug/L","30 - 400",D)],
    ["two dates, one analyte each: emit one row per (analyte, date), pharmacist picks current", "'-' means no result, not a value"])

one("p03_total_vs_corrected", "Total and albumin-corrected calcium are different analytes.", HDR + ["Collected: 14/02/2026"], C1,
    [["Calcium (total)", "2.31", "mmol/L", "2.10 - 2.60"], ["Calcium (corrected)", "2.38", "mmol/L", "2.10 - 2.60"], ["Albumin", "38", "g/L", "35 - 50"]],
    [E("Calcium (total)","2.31","mmol/L","2.10 - 2.60",D,[]), E("Calcium (corrected)","2.38","mmol/L","2.10 - 2.60",D), E("Albumin","38","g/L","35 - 50",D)],
    ["never merge or rename total/corrected", "no abnormal flag unless the report itself prints one"])

C4 = [(40, "Test"), (190, "Result"), (250, "Flag"), (290, "Units"), (385, "Reference interval")]
one("p04_flags_and_range_forms", "H/L flags, '<', '>', parenthesised and dash ranges.", HDR + ["Collected: 2026-02-14"], C4,
    [["CRP", "<0.5", "", "mg/L", "<5.0"], ["Potassium", "5.4", "H", "mmol/L", "(3.5 - 5.2)"], ["eGFR", ">90", "", "mL/min/1.73m2", ">59"], ["Sodium", "132", "L", "mmol/L", "135-145"]],
    [E("CRP","<0.5","mg/L","<5.0",D), E("Potassium","5.4","mmol/L","(3.5 - 5.2)",D,["report_flag_H"]), E("eGFR",">90","mL/min/1.73m2",">59",D), E("Sodium","132","mmol/L","135-145",D,["report_flag_L"])],
    ["inequality prefix is part of the value", "flag column is not a unit", "keep range text exactly as printed"])

one("p05_unit_variants", "Unit strings with symbols and superscripts as text.", HDR + ["Collected: 14/02/2026"], C1,
    [["White cell count", "6.1", "x10^9/L", "4.0 - 11.0"], ["Creatinine", "78", "umol/L", "60 - 110"], ["Haemoglobin", "142", "g/L", "130 - 180"], ["Haematocrit", "0.43", "L/L", "0.40 - 0.54"], ["Vitamin B12", "310", "pmol/L", ">150"]],
    [E("White cell count","6.1","x10^9/L","4.0 - 11.0",D), E("Creatinine","78","umol/L","60 - 110",D), E("Haemoglobin","142","g/L","130 - 180",D), E("Haematocrit","0.43","L/L","0.40 - 0.54",D), E("Vitamin B12","310","pmol/L",">150",D)],
    ["unit copied verbatim, never converted", "Haemoglobin vs Haematocrit vs HbA1c are distinct"])

one("p06_wrapped_analyte_names", "Analyte name wraps to a second line.", HDR + ["Collected: 14/02/2026"], C1,
    [["Alanine aminotransferase\n(ALT)", "27", "U/L", "<35"], ["Thyroid stimulating\nhormone", "2.1", "mU/L", "0.4 - 4.0"]],
    [E("Alanine aminotransferase (ALT)","27","U/L","<35",D), E("Thyroid stimulating hormone","2.1","mU/L","0.4 - 4.0",D)],
    ["second line belongs to the same row; do not emit '(ALT)' as its own analyte"])

one("p07_comment_lines_not_results", "Comment and footnote lines contain numbers but are not results.", HDR + ["Collected: 14/02/2026"], C1,
    [["Ferritin", "88", "ug/L", "30 - 400"]],
    [E("Ferritin","88","ug/L","30 - 400",D)],
    ["footnotes mention numbers (repeat 36, see 2024 result) that must not become rows"],
    notes=["Comment: Result repeated, second value 89 ug/L.", "See previous result dated 09/08/2024: 97 ug/L (not shown in table).", "Specimen 2 of 2. Page 1 of 1."])

one("p08_no_sample_date", "Only a 'Reported' date, no collection or sample date anywhere.", HDR + ["Reported: 16/02/2026"], C1,
    [["Ferritin", "88", "ug/L", "30 - 400"]],
    [E("Ferritin","88","ug/L","30 - 400","",["sample_date_missing_check_by_hand"])],
    ["reported date is not a sample date; leave sample_date blank and flag (verification would then be refused until typed)"])

one("p09_textual_date", "Date as 14-Feb-2026 in 'Sample date' label.", HDR + ["Sample date: 14-Feb-2026   Reported: 16-Feb-2026"], C1,
    [["Ferritin", "88", "ug/L", "30 - 400"]],
    [E("Ferritin","88","ug/L","30 - 400",D)],
    ["two dates in header: sample date, not reported date"])

one("p10_nonnumeric_results", "Text results stay text; none become numbers.", HDR + ["Collected: 14/02/2026"], C1,
    [["Hepatitis B surface Ag", "Not detected", "", "Not detected"], ["Urine protein", "Trace", "", "Negative"], ["H. pylori Ab", "Positive", "", "Negative"]],
    [E("Hepatitis B surface Ag","Not detected","","Not detected",D,["non_numeric"]), E("Urine protein","Trace","","Negative",D,["non_numeric"]), E("H. pylori Ab","Positive","","Negative",D,["non_numeric"])],
    ["empty unit is legitimate here but verification will still require a unit: leave blank, flag"])

one("p11_missing_unit", "Unit column empty for a numeric result.", HDR + ["Collected: 14/02/2026"], C1,
    [["Ferritin", "88", "", "30 - 400"], ["Magnesium", "0.82", "mmol/L", "0.70 - 1.10"]],
    [E("Ferritin","88","","30 - 400",D,["unit_missing_check_by_hand"]), E("Magnesium","0.82","mmol/L","0.70 - 1.10",D)],
    ["never infer ug/L from the analyte name"])

one("p12_sex_specific_ranges", "Reference text with sex-specific ranges stays one string.", HDR + ["Collected: 14/02/2026"], C1,
    [["Ferritin", "88", "ug/L", "M 30-400 F 15-150"], ["Haemoglobin", "142", "g/L", "M 130-180 F 115-165"]],
    [E("Ferritin","88","ug/L","M 30-400 F 15-150",D), E("Haemoglobin","142","g/L","M 130-180 F 115-165",D)],
    ["do not pick the sex-matching range; do not compute position"])

CG = [(40, "Test"), (190, "Result"), (270, "Units"), (330, "Reference interval")]
one("p13_similar_analytes", "Near-identical names that must stay separate.", HDR + ["Collected: 14/02/2026"], CG,
    [["Glucose (fasting)", "5.4", "mmol/L", "3.0 - 5.4"], ["Glucose (random)", "6.9", "mmol/L", "3.0 - 7.7"], ["HbA1c", "5.9", "%", "<6.5"], ["Haemoglobin", "142", "g/L", "130 - 180"], ["LDL cholesterol", "3.1", "mmol/L", "<3.5"], ["HDL cholesterol", "1.2", "mmol/L", ">1.0"]],
    [E("Glucose (fasting)","5.4","mmol/L","3.0 - 5.4",D), E("Glucose (random)","6.9","mmol/L","3.0 - 7.7",D), E("HbA1c","5.9","%","<6.5",D), E("Haemoglobin","142","g/L","130 - 180",D), E("LDL cholesterol","3.1","mmol/L","<3.5",D), E("HDL cholesterol","1.2","mmol/L",">1.0",D)],
    ["qualifier in brackets is part of the analyte identity"])

one("p14_result_with_embedded_unit", "Unit printed inside the result cell, no unit column.", HDR + ["Collected: 14/02/2026"], [(40, "Test"), (210, "Result"), (330, "Reference interval")],
    [["HbA1c", "5.9 %", "<6.5 %"], ["ALT", "27 U/L", "<35 U/L"]],
    [E("HbA1c","5.9","%","<6.5 %",D,["unit_taken_from_result_cell"]), E("ALT","27","U/L","<35 U/L",D,["unit_taken_from_result_cell"])],
    ["split only when the suffix is exactly a printed unit token; else keep whole text and flag"])

one("p15_duplicate_analyte_same_date", "Same analyte twice on one date with different values (repeat/corrected report).", HDR + ["Collected: 14/02/2026"], C1,
    [["Potassium", "5.4", "mmol/L", "3.5 - 5.2"], ["Potassium", "4.6", "mmol/L", "3.5 - 5.2"]],
    [E("Potassium","5.4","mmol/L","3.5 - 5.2",D,["duplicate_same_date_check_by_hand"]), E("Potassium","4.6","mmol/L","3.5 - 5.2",D,["duplicate_same_date_check_by_hand"])],
    ["emit both with flag, never choose one"])

one("p16_rotated_page", "Same table on a page with /Rotate 90. Either extract correctly or abstain; never garble.", HDR + ["Collected: 14/02/2026"], C1,
    [["Ferritin", "88", "ug/L", "30 - 400"], ["ALT", "27", "U/L", "<35"]],
    [E("Ferritin","88","ug/L","30 - 400",D), E("ALT","27","U/L","<35",D)],
    ["acceptable outcomes: exact rows OR zero rows with page flag"], rotate=90)

def multipage(doc):
    page_doc(doc, HDR + ["Collected: 14/02/2026   Page 1 of 2"], C1, [["Ferritin", "88", "ug/L", "30 - 400"], ["ALT", "27", "U/L", "<35"]])
    page_doc(doc, ["FICTIONAL PATH LAB (synthetic test document)", "Page 2 of 2 (date shown on page 1 only)"], C1, [["Magnesium", "0.82", "mmol/L", "0.70 - 1.10"]])
case("p17_multipage_date_on_first_page", "Header date only on page 1, table continues on page 2 with repeated header.", multipage,
     [E("Ferritin","88","ug/L","30 - 400",D), E("ALT","27","U/L","<35",D), E("Magnesium","0.82","mmol/L","0.70 - 1.10",D,["date_inherited_from_page_1"])],
     ["inheriting a date across pages must be flagged, not silent"])

one("p18_decoy_numbers_in_header", "Patient/lab header numbers (phone, ref no, Medicare-like) must never appear as results.", HDR + ["Medicare: 0000 00000 0   Request: 2026-0214-0042   Collected: 14/02/2026"], C1,
    [["Ferritin", "88", "ug/L", "30 - 400"]],
    [E("Ferritin","88","ug/L","30 - 400",D)], ["numbers outside the table area are not rows"])

def scanned(doc):
    tmp = fitz.open(); page_doc(tmp, HDR + ["Collected: 14/02/2026"], C1, [["Ferritin", "88", "ug/L", "30 - 400"], ["ALT", "27", "U/L", "<35"]])
    pix = tmp[0].get_pixmap(dpi=150)
    p = doc.new_page(width=595, height=842); p.insert_image(p.rect, pixmap=pix)
case("p19_scanned_image_only", "Image-only page, no text layer. Current import labels it unreadable_or_scanned.", scanned,
     [], ["expected: zero proposed rows and flag 'scanned: read original'; an OCR step may propose rows only if every field is flagged ocr_unverified and the exact-match rate is reported"])

SCAN_TRUTH_NOTE = "p19 ground truth (for OCR accuracy testing only): Ferritin 88 ug/L 30 - 400; ALT 27 U/L <35; date 2026-02-14"

def mixed(doc):
    page_doc(doc, HDR + ["Collected: 14/02/2026"], C1, [["Ferritin", "88", "ug/L", "30 - 400"]])
    tmp = fitz.open(); page_doc(tmp, HDR + ["Collected: 14/02/2026"], C1, [["ALT", "27", "U/L", "<35"]])
    p = doc.new_page(width=595, height=842); p.insert_image(p.rect, pixmap=tmp[0].get_pixmap(dpi=150))
case("p20_mixed_text_and_scanned_pages", "Page 1 text layer, page 2 scanned.", mixed,
     [E("Ferritin","88","ug/L","30 - 400",D)], ["page 2 yields no rows and a scanned flag; the document must not look complete"])


# Machine-readable expectations per case. date: raw text on page, proposed ISO (proposal stage), required flags.
# Proposal stage may carry a raw/assumed date; ACCEPTED rows still need a real ISO date (existing verify gate).
META = {
 "p01_single_column_basic": dict(date_raw="14/02/2026", date_proposed_iso="2026-02-14", date_flags=["date_format_assumed_dmy"]),
 "p02_two_dated_columns": dict(date_raw=["14/02/2026","09/08/2024"], date_proposed_iso=["2026-02-14","2024-08-09"], date_flags=["date_format_assumed_dmy"]),
 "p04_flags_and_range_forms": dict(date_raw="2026-02-14", date_proposed_iso="2026-02-14", date_flags=[]),
 "p08_no_sample_date": dict(date_raw=None, date_proposed_iso="", date_flags=["sample_date_missing_check_by_hand"], required_page_flags=[]),
 "p09_textual_date": dict(date_raw="14-Feb-2026", date_proposed_iso="2026-02-14", date_flags=[]),
 "p16_rotated_page": dict(alternative_outcomes=["exact_rows", "zero_rows_with_page_flag"], required_page_flags_if_zero_rows=["rotated_page_not_read"]),
 "p17_multipage_date_on_first_page": dict(date_raw="14/02/2026", date_proposed_iso="2026-02-14", date_flags=["date_format_assumed_dmy"], row_flags_page2=["date_inherited_from_page_1"]),
 "p19_scanned_image_only": dict(required_page_flags=["scanned_read_original"], expected_row_count=0),
 "p20_mixed_text_and_scanned_pages": dict(required_page_flags_by_page={"2": ["scanned_read_original"]}, document_flag=["incomplete_extraction"]),
}
SLASH_DMY = dict(date_raw="14/02/2026", date_proposed_iso="2026-02-14", date_flags=["date_format_assumed_dmy"])
for _cid in ["p01_single_column_basic","p03_total_vs_corrected","p05_unit_variants","p06_wrapped_analyte_names","p07_comment_lines_not_results",
             "p10_nonnumeric_results","p11_missing_unit","p12_sex_specific_ranges","p13_similar_analytes","p14_result_with_embedded_unit",
             "p15_duplicate_analyte_same_date","p16_rotated_page","p18_decoy_numbers_in_header","p20_mixed_text_and_scanned_pages"]:
    META[_cid] = {**SLASH_DMY, **META.get(_cid, {})}
META["p07_comment_lines_not_results"]["date_decoys_not_to_use"] = ["09/08/2024"]
META["p18_decoy_numbers_in_header"]["numeric_decoys_not_rows"] = ["0000 00000 0", "2026-0214-0042", "000000", "0400 000 000"]
META["p19_scanned_image_only"].update(date_raw=None, date_proposed_iso="", date_flags=["scanned_read_original"])
META["p20_mixed_text_and_scanned_pages"]["date_scope"] = "page 1 only; page 2 is a scan with no text layer"
META["p10_nonnumeric_results"]["row_flags_all"] = ["non_numeric"]
META["p11_missing_unit"]["row_flags_ferritin"] = ["unit_missing_check_by_hand"]
assert all("date_flags" in META[c] for c in META), "every case must declare date_flags"

DEFAULT_DATE_FLAG = "Each case declares meta.date_flags explicitly."

if __name__ == "__main__":
    expected = {}
    missing = [c for c in cases if "date_flags" not in META.get(c, {})]
    assert not missing, missing
    for cid, c in cases.items():
        doc = fitz.open(); c["build"](doc); doc.save(os.path.join(OUT, cid + ".pdf"))
        expected[cid] = dict(description=c["description"], traps=c["traps"], expected_rows=c["expected"], meta=META.get(cid, {}))
    expected["_notes"] = SCAN_TRUTH_NOTE + " | " + DEFAULT_DATE_FLAG + " | sample_date in expected_rows is the PROPOSED ISO date; empty string means blank plus the flag in meta or row flags."
    json.dump(expected, open(os.path.join(OUT, "expected.json"), "w"), indent=2)
    print(len(cases), "cases written")
