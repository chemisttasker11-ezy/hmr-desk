"""Synthetic reproductions of common Australian lab table geometry.

Every name/value is invented. No patient screenshots, real identifiers or
reference PDF files belong in CI. Must assert values/columns, not just counts.
"""
import hashlib

import fitz

import pathology_proposals as ex


def _text(p, x, y, value, size=9):
    p.insert_text((x, y), value, fontsize=size)


def _extract(doc):
    with fitz.open(stream=doc.tobytes(), filetype='pdf') as pdf:
        return ex._page_proposals(pdf[0], 'a'*32, 'b'*64)


def test_cumulative_biochemistry_five_distinct_dates_with_missing_values():
    doc = fitz.open()
    p = doc.new_page(width=900, height=600)
    _text(p, 50, 35, 'CUMULATIVE SERUM BIOCHEMISTRY')
    positions = [50, 220, 310, 400, 490, 580]
    for x, entry in zip(positions, ['Date','25/03/26','01/04/26','24/06/26','16/07/26','26/08/26']):
        _text(p, x, 65, entry)
    rows = [
      ('Sodium', ['130','133','138','139','138'], 'mmol/L', '(135-145)'),
      ('Creat', ['67','71','58','48','52'], 'umol/L', '(65-135)'),
      ('eGFR', ['78','76','83','90','87'], 'mL/min', '(over 59)'),
      ('Corrected Ca', ['2.20','2.32','2.30','2.29','2.35'], 'mmol/L', '(2.15-2.60)'),
      ('ALT', ['12','<10','<10','14','20'], 'U/L', '(< 41)'),
      ('D. Bili', ['4','','','8',''], 'umol/L', ''),
    ]
    for i, (name, values, unit, rng) in enumerate(rows):
        y=130+i*30
        _text(p, 50, y, name)
        for x,v in zip(positions[1:],values):
            if v: _text(p,x,y,v)
        _text(p,680,y,unit)
        if rng:_text(p,765,y,rng)
    try:
        rows,issues=_extract(doc)
    finally: doc.close()
    assert not issues, issues
    # Six analytes and five dated columns, with two present direct bilirubin values.
    assert len(rows)==27, [r['fields'] for r in rows]
    assert [(r['fields']['sample_date'],r['fields']['value']) for r in rows if r['fields']['test']=='Creat'] == [
      ('2026-03-25','67'),('2026-04-01','71'),('2026-06-24','58'),
      ('2026-07-16','48'),('2026-08-26','52')]
    assert [r['fields']['value'] for r in rows if r['fields']['test']=='ALT'] == ['12','<10','<10','14','20']
    assert all(r['fields']['reference_interval']=='' for r in rows if r['fields']['test']=='D. Bili')
    assert len({r['id'] for r in rows})==len(rows)


def test_single_panel_full_blood_count_handles_flags_and_units():
    doc=fitz.open()
    p=doc.new_page(width=880,height=600)
    _text(p,50,40,'HAEMATOLOGY')
    _text(p,50,85,'Full Blood Count (Whole Blood)')
    _text(p,50,125,'Coll Date:'); _text(p,240,125,'14/10/26')
    for y, cells in [
       (170,('HAEMOGLOBIN','124','L','(130-180)','g/L')),
       (200,('RBC','4.2','L','(4.3-6.5)','10^12/L')),
       (230,('MCV','99.5','','(80.0-100.0)','fL')),
       (260,('WCC','7.4','','(4.0-11.0)','10^9/L')),
       (290,('Eosinophils','0.1','','(< 1.2)','10^9/L')),
    ]:
        for x,text in zip((50,300,352,520,700),cells):
            if text:_text(p,x,y,text)
    try: rows,issues=_extract(doc)
    finally:doc.close()
    assert not issues, issues
    assert len(rows)==5, [(r['fields'],r['field_uncertainty']) for r in rows]
    assert rows[0]['fields']==dict(test='HAEMOGLOBIN',value='124',unit='g/L',
                   reference_interval='(130-180)',sample_date='2026-10-14')
    assert rows[1]['fields']['unit']=='10^12/L'
    assert rows[0]['raw_text']['value']=='124 L'
    assert rows[4]['fields']['reference_interval']=='(< 1.2)'


def test_hba1c_dual_reporting_preserves_two_separate_unit_results():
    doc=fitz.open()
    p=doc.new_page(width=880,height=600)
    _text(p,55,45,'HAEMATOLOGY')
    _text(p,55,100,'Diabetic Testing (Whole Blood)')
    _text(p,55,130,'Coll Date:');_text(p,250,130,'24/07/26')
    for y, vals in [
        (200,('HbA1c (NGSP)','6.4','H','(4.0-5.9)','%')),
        (230,('HbA1c (IFCC)','46','H','(20-41)','mmol/mol')),
    ]:
        for x,txt in zip((55,320,365,520,710),vals): _text(p,x,y,txt)
    _text(p,55,300,'Generally target HbA1c <7.0%, but individualise')
    try:rows,issues=_extract(doc)
    finally:doc.close()
    assert not issues,issues
    assert len(rows)==2, [r['fields'] for r in rows]
    assert [(r['fields']['test'],r['fields']['value'],r['fields']['unit']) for r in rows] == [
      ('HbA1c (NGSP)','6.4','%'),('HbA1c (IFCC)','46','mmol/mol')]


def test_lipid_conditional_high_risk_targets_not_silent_lab_ranges():
    doc=fitz.open()
    p=doc.new_page(width=880,height=500)
    _text(p,50,40,'CHEMISTRY')
    _text(p,50,90,'Lipid Studies (Serum)')
    _text(p,50,125,'Coll Date:');_text(p,250,125,'04/09/26')
    for y,n,v,ran in [(170,'Cholesterol','2.4','(< 5.6)'),
                      (200,'LDL-C','1.0','(< 3.1)')]:
        _text(p,55,y,n);_text(p,260,y,v);_text(p,520,y,ran);_text(p,700,y,'mmol/L')
    try:rows,issues=_extract(doc)
    finally:doc.close()
    assert not issues,issues
    assert len(rows)==2
    assert rows[0]['fields']['reference_interval']=='(< 5.6)'
    assert rows[1]['fields']['reference_interval']=='(< 3.1)'


def test_repeated_calendar_day_abstains_without_unique_accession_mapping():
    doc = fitz.open()
    page = doc.new_page(width=900, height=500)
    _text(page, 50, 35, 'CUMULATIVE SERUM BIOCHEMISTRY')
    for x, v in [(50, 'Date'), (220, '02/11/26'), (350, '02/11/26')]:
        _text(page, x, 65, v)
    for x, v in [(50, 'Sodium'), (220, '139'), (350, '141'),
                 (680, 'mmol/L'), (780, '(135-145)')]:
        _text(page, x, 130, v)
    try:
        rows, issues = _extract(doc)
    finally:
        doc.close()
    assert rows == []
    assert any('accession/time' in reason for reason in issues)


def test_rotated_table_abstains_instead_of_misplacing_cells():
    doc = fitz.open()
    page = doc.new_page()
    _text(page, 45, 35, 'Collected: 10/11/2026')
    for x, v in [(45, 'Test'), (200, 'Result'), (350, 'Units'),
                 (470, 'Reference')]:
        _text(page, x, 100, v)
    for x, v in [(45, 'Sodium'), (200, '139'), (350, 'mmol/L'),
                 (470, '135-145')]:
        _text(page, x, 130, v)
    page.set_rotation(90)
    try:
        rows, issues = _extract(doc)
    finally:
        doc.close()
    assert rows == []
    assert any('Rotated' in reason for reason in issues)


def test_searchable_text_overlay_on_page_sized_raster_is_unverified():
    original = fitz.open()
    original.new_page(width=595, height=842).insert_text(
        (30, 100), 'SYNTHETIC IMAGE BASE')
    with fitz.open(stream=original.tobytes(), filetype='pdf') as source:
        pixels = source[0].get_pixmap().tobytes('png')
    original.close()
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=pixels)
    for x, value in [(45, 'Test'), (200, 'Result'), (350, 'Units'),
                     (470, 'Reference')]:
        _text(page, x, 150, value)
    for x, value in [(45, 'Sodium'), (200, '139'), (350, 'mmol/L'),
                     (470, '135-145')]:
        _text(page, x, 180, value)
    try:
        rows, issues = _extract(doc)
    finally:
        doc.close()
    assert rows == []
    assert any('raster' in reason for reason in issues)


def test_cumulative_si_units_description_has_no_invented_test_name():
    doc = fitz.open()
    page = doc.new_page(width=900, height=500)
    _text(page, 50, 35, 'CUMULATIVE SERUM BIOCHEMISTRY')
    for x, v in [(50, 'Date'), (220, '02/11/26')]:
        _text(page, x, 65, v)
    for x, v in [(50, 'in SI units'), (220, '46'), (680, 'mmol/mol'),
                 (770, '(20-41)')]:
        _text(page, x, 130, v)
    try:
        rows, issues = _extract(doc)
    finally:
        doc.close()
    assert not issues
    assert len(rows) == 1
    assert rows[0]['raw_text']['test'] == 'in SI units'
    assert rows[0]['fields']['test'] == ''
    assert 'test' in rows[0]['field_uncertainty']
