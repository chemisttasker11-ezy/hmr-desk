"""Synthetic-fixture tests for brainstorm_tables. No real reference content."""
import sqlite3

import fitz
import pytest

import brainstorm_tables


MARKER = (0, 0xA6 / 255, 0xED / 255)  # coloured square glyph colour (42733)


def _write(page, lines, y=72):
    for kind, text in lines:
        color = MARKER if kind == 'heading' else (0, 0, 0)
        page.insert_text((72, y), text, fontsize=12, color=color)
        y += 16
    return y


def _fixture_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    y = _write(page, [
        ('heading', ' Fictionalin '),
        ('body', 'Issue to Consider: synthetic drowsiness warning for tests'),
        ('body', 'spans two lines here'),
        ('body', 'Suggested Action'),
        ('body', 'Review the fictional indication first.'),
        ('body', 'Reference: Synthetic Formulary 2026'),
        ('body', 'Mystery Label: kept inline because it is not a known label'),
        ('heading', ' Placebomycin '),
        ('body', 'Clinical Use: fictional test-only indication'),
    ])
    page2 = doc.new_page()
    _write(page2, [
        ('body', 'Dose in RRT: no real dosing, synthetic continuation text'),
        ('body', 'Other Information: second page of the same entry'),
    ])
    doc.save(path)
    doc.close()
    return path


def test_extract_partitions_fields_and_pages(tmp_path):
    pdf = _fixture_pdf(tmp_path / 'synthetic-reference.pdf')
    structure = brainstorm_tables.extract(pdf, edition='Synthetic Test Edition')
    assert structure['source']['page_count'] == 2
    assert structure['extraction_report']['roundtrip_problems'] == []
    entries = structure['entries']
    assert [e['title'] for e in entries] == ['Fictionalin', 'Placebomycin']
    fields = entries[0]['fields']
    assert [f['label'] for f in fields] == ['Issue to Consider', 'Suggested Action', 'Reference']
    assert fields[0]['text'] == 'synthetic drowsiness warning for tests\nspans two lines here'
    assert fields[1]['text'] == 'Review the fictional indication first.'
    assert fields[2]['text'] == 'Synthetic Formulary 2026\nMystery Label: kept inline because it is not a known label'
    assert entries[1]['page_start'] == 1 and entries[1]['page_end'] == 2
    assert [f['label'] for f in entries[1]['fields']] == ['Clinical Use', 'Dose in RRT', 'Other Information']
    assert entries[1]['fields'][1]['text'] == 'no real dosing, synthetic continuation text'
    assert structure['extraction_report']['unknown_label_lines'] == {'Mystery Label': 1}


def test_verify_detects_tampering(tmp_path):
    pdf = _fixture_pdf(tmp_path / 'synthetic-reference.pdf')
    structure = brainstorm_tables.extract(pdf, edition='x')
    section_texts = ['\n'.join(['Issue to Consider: synthetic drowsiness warning for tests',
                                'spans two lines here', 'Suggested Action',
                                'Review the fictional indication first.',
                                'Reference: Synthetic Formulary 2026',
                                'Mystery Label: kept inline because it is not a known label']),
                     '\n'.join(['Clinical Use: fictional test-only indication',
                                'Dose in RRT: no real dosing, synthetic continuation text',
                                'Other Information: second page of the same entry'])]
    assert brainstorm_tables.verify(structure, section_texts) == []
    structure['entries'][0]['fields'][0]['text'] = 'altered text'
    structure['entries'][0]['content_sha256'] = brainstorm_tables._entry_digest(structure['entries'][0])
    problems = brainstorm_tables.verify(structure, section_texts)
    assert any('coverage mismatch' in p for p in problems)


def test_to_sqlite_rows_and_rejects_unverified(tmp_path):
    pdf = _fixture_pdf(tmp_path / 'synthetic-reference.pdf')
    structure = brainstorm_tables.extract(pdf, edition='Synthetic Test Edition')
    db_path = tmp_path / 'tables.db'
    brainstorm_tables.to_sqlite(structure, db_path)
    db = sqlite3.connect(db_path)
    try:
        assert db.execute('SELECT count(*) FROM brainstorm_entry').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM brainstorm_entry_field').fetchone()[0] == 6
        row = db.execute('SELECT title, page_start, page_end FROM brainstorm_entry WHERE ordinal=0').fetchone()
        assert row == ('Fictionalin', 1, 1)
        label, text = db.execute('SELECT label, text FROM brainstorm_entry_field f '
                                 'JOIN brainstorm_entry e ON e.id=f.entry_id WHERE e.ordinal=1 AND f.ordinal=1').fetchone()
        assert (label, text) == ('Dose in RRT', 'no real dosing, synthetic continuation text')
        source = db.execute('SELECT edition, page_count FROM brainstorm_source').fetchone()
        assert source == ('Synthetic Test Edition', 2)
    finally:
        db.close()
    structure['extraction_report']['roundtrip_problems'] = ['forced problem']
    with pytest.raises(ValueError):
        brainstorm_tables.to_sqlite(structure, tmp_path / 'never.db')
