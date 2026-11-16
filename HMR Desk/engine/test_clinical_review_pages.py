"""Per-field PDF page provenance for referral clinical review (synthetic)."""
import json

import pytest

import clinical_review
import clinical_snapshot
import db
import interview
import referral_entry

PAGES = {'conditions': 1, 'allergies': 0, 'medicines': 3, 'observations': 2}


def review(**extra):
    base = {'confirmed': True, 'allergies_status': 'unknown', 'reviewed_by': 'Synthetic Pharmacist',
            'conditions': 'Synthetic condition', 'allergies': '', 'medicines': 'Synthetic medicine list',
            'observations': 'Synthetic BP 120/80', 'source_pages': dict(PAGES)}
    base.update(extra)
    return base


def test_each_populated_field_keeps_its_own_page():
    out = referral_entry.validate_clinical_review(review(), 5)
    assert out['version'] == 2
    assert out['source_pages'] == PAGES
    assert 'source_page' not in out


def test_populated_field_without_its_page_is_rejected():
    pages = {**PAGES, 'medicines': 0}
    with pytest.raises(ValueError, match='medicines'):
        referral_entry.validate_clinical_review(review(source_pages=pages), 5)


def test_page_for_empty_field_and_out_of_range_page_rejected():
    with pytest.raises(ValueError, match='empty clinical field'):
        referral_entry.validate_clinical_review(review(source_pages={**PAGES, 'allergies': 2}), 5)
    with pytest.raises(ValueError, match='Invalid PDF source page'):
        referral_entry.validate_clinical_review(review(source_pages={**PAGES, 'medicines': 6}), 5)
    with pytest.raises(ValueError, match='per-field'):
        referral_entry.validate_clinical_review(review(source_pages={'conditions': 1}), 5)


def test_allergy_negative_needs_its_own_page():
    pages = {**PAGES, 'allergies': 0}
    with pytest.raises(ValueError, match='allergies'):
        referral_entry.validate_clinical_review(review(allergies_status='explicit_none', source_pages=pages), 5)
    ok = referral_entry.validate_clinical_review(
        review(allergies_status='explicit_none', source_pages={**PAGES, 'allergies': 4}), 5)
    assert ok['source_pages']['allergies'] == 4


def test_version_1_single_page_still_reads_as_all_populated_fields():
    legacy = {'confirmed': True, 'source_page': 2, 'reviewed_by': 'Synthetic Pharmacist',
              'allergies_status': 'unknown', 'conditions': 'c', 'allergies': '', 'medicines': 'm',
              'observations': ''}
    assert clinical_review.is_reviewed(legacy)
    assert clinical_review.field_page(legacy, 'medicines') == 2
    assert clinical_review.field_page(legacy, 'observations') == 0
    out = referral_entry.validate_clinical_review(legacy, 3)
    assert out['source_pages'] == {'conditions': 2, 'allergies': 0, 'medicines': 2, 'observations': 0}


def test_is_reviewed_requires_every_populated_field_page():
    assert clinical_review.is_reviewed(review())
    assert not clinical_review.is_reviewed(review(source_pages={**PAGES, 'observations': 0}))
    assert not clinical_review.is_reviewed(review(confirmed=False))
    assert not clinical_review.is_reviewed(review(reviewed_by='ab'))


def test_interview_cites_a_different_page_for_each_fact(tmp_path, monkeypatch):
    folder = tmp_path / 'workspace' / 'TO SORT' / 'Synthetic'
    folder.mkdir(parents=True)
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    monkeypatch.setattr(interview, 'referral_text', lambda folder: (None, []))
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with conn:
        pid = conn.execute('INSERT INTO patients(key,name,folder) VALUES (?,?,?)',
                           ('synthetic', 'Synthetic Patient', 'TO SORT/Synthetic')).lastrowid
    patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    stored = referral_entry.validate_clinical_review(review(), 5)
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review': stored}))
    record = interview.blank(conn, patient)
    assert any('Conditions confirmed: referral.pdf page 1' in x for x in record['sources'])
    assert any('referral.pdf page 3' in x for x in record['clarify'])
    assert any(row[2] == 'referral.pdf page 2' for row in record['obs'])
    conn.close()


def test_snapshot_trusts_only_fully_page_supported_reviews():
    state = {'clinical_review': {**review(allergies_status='explicit_none',
                                          source_pages={**PAGES, 'allergies': 4}), 'allergies': ''}}
    assert clinical_review.is_reviewed(state['clinical_review'])
    bad = {'clinical_review': {**state['clinical_review'], 'source_pages': {**PAGES, 'allergies': 0}}}
    assert not clinical_review.is_reviewed(bad['clinical_review'])
    assert clinical_snapshot.clinical_review is clinical_review
