"""Synthetic: confirmed intake medicine list outranks parser rows on first preparation only."""
import json

import db
import interview
import records

FOUND = {'meds': [['Synthetic Parsed P', 'daily'], ['Synthetic Parsed Q', 'nightly']], 'conditions': [], 'allergies': [],
         'obs': {'height': '', 'weight': '', 'bmi': '', 'bp': ''}, 'renal': '', 'alcohol': '', 'smoking': '', 'social': '',
         'unparsed': [], 'reason': '', 'ceased': ['Synthetic Ceased C'], 'medicine_source_lines': [['a'], ['b']]}


def setup(tmp_path, monkeypatch, lines):
    folder = tmp_path / 'workspace' / 'TO SORT' / 'Synthetic'
    folder.mkdir(parents=True)
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    monkeypatch.setattr(interview, 'referral_text', lambda f: ('text', []))
    monkeypatch.setattr(interview.referral, 'parse', lambda t: json.loads(json.dumps(FOUND)))
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with conn:
        pid = conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)", ('s', 'Synthetic Patient', 'TO SORT/Synthetic')).lastrowid
    patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    rev = {'confirmed': True, 'source_page': 1, 'reviewed_by': 'Synthetic Pharmacist', 'allergies_status': 'unknown',
           'conditions': '', 'allergies': '', 'observations': '', 'medicines': '\n'.join(lines)}
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review': rev}))
    return conn, patient


def test_reviewed_list_replaces_conflicting_parser_rows(tmp_path, monkeypatch):
    lines = ['Synthetic Reviewed X 5 mg', 'Synthetic Reviewed Y 10 mg', 'Synthetic Reviewed Z']
    conn, patient = setup(tmp_path, monkeypatch, lines)
    rec = interview.blank(conn, patient)
    names = [r[0] for r in rec['meds']]
    assert all(l in names for l in lines)
    assert not any('Parsed' in n for n in names)
    assert 'Synthetic Ceased C' in names
    assert len(rec['details']['meds']) == len(rec['meds'])
    for r, meta in zip(rec['meds'], rec['details']['meds']):
        if r[0] in lines:
            assert not meta.get('use_status') and not meta.get('checked') and 'source_evidence' not in meta
        else:
            assert meta['use_status'] == 'not_using'
    assert any('Parser read' in x and 'Synthetic Parsed P' in x for x in rec['clarify'])
    interview.validate(rec)


def test_matching_parser_rows_are_kept_with_evidence(tmp_path, monkeypatch):
    conn, patient = setup(tmp_path, monkeypatch, ['Synthetic Parsed P', 'Synthetic Parsed Q'])
    rec = interview.blank(conn, patient)
    assert [r[0] for r in rec['meds']][:2] == ['Synthetic Parsed P', 'Synthetic Parsed Q']
    assert 'source_evidence' in rec['details']['meds'][0]


def test_saved_interview_is_not_overwritten(tmp_path, monkeypatch):
    conn, patient = setup(tmp_path, monkeypatch, ['Synthetic Reviewed X'])
    spec = interview.jobs.interview_spec_path(patient)
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(json.dumps({'meds': [['Synthetic Edited E', 'as edited', 'x']]}), encoding='utf-8')
    rec = interview.blank(conn, patient)
    assert [r[0] for r in rec['meds']][0] == 'Synthetic Edited E'
    assert not any(r[0] == 'Synthetic Reviewed X' for r in rec['meds'])
