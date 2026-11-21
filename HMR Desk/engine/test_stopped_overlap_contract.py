"""Pins the stopped-overlap contract in the manual medicine-name mode (synthetic names only).
In this mode an 'ingredient' is the whole name normalised for case and spacing, so an overlap exists only when a medicine in the
confirmed list has the same normalised name as a medicine marked not using. The alternative rule requires the chosen taking medicine
to have the row's name and a name different from every stopped one, so no alternative can resolve a manual-mode overlap."""
import pytest

import api
import external_helpers
import manual_medicine_names


@pytest.fixture(autouse=True)
def manual_mode(monkeypatch):
    # This file pins the manual mode, whatever helper files the machine holds (helper mode: test_helper_modes.py).
    monkeypatch.setattr(external_helpers, 'mims', manual_medicine_names)


def usage(name, status):
    return {'name': name, 'status': status, 'detail': '', 'source': 'Referral medicine', 'directions': ['', '']}


STOPPED = usage('Synthmed A 10 mg tablet', 'not_using')


def check(meds, items, pick):
    relevant = api.relevant_usage(items, meds)
    choice = None if pick is None else next(x for x in relevant if x['status'] == 'taking')
    return api.valid_alternatives(meds, relevant, [choice])


def test_ingredient_in_manual_mode_is_the_whole_normalised_name():
    assert manual_medicine_names.ingredients('Synthmed  A 10 MG tablet') == ['synthmed a 10 mg tablet']
    assert manual_medicine_names.ingredients('Synthmed A 20 mg tablet') == ['synthmed a 20 mg tablet']


def test_different_strength_is_not_an_overlap_and_needs_no_alternative():
    assert check([['Synthmed A 20 mg tablet', '']], [STOPPED, usage('Synthmed A 20 mg tablet', 'taking')], None) is True


def test_same_normalised_name_is_an_overlap_and_no_selection_resolves_it():
    items = [STOPPED, usage('synthmed  a 10 mg   TABLET', 'taking')]
    meds = [['synthmed  a 10 mg   TABLET', '']]
    assert check(meds, items, None) is False
    assert check(meds, items, 'taking') is False
    items = [STOPPED, usage('Synthmed A 10 mg tablet', 'taking')]
    assert check([['Synthmed A 10 mg tablet', '']], items, 'taking') is False


def test_a_stopped_medicine_not_in_the_confirmed_list_causes_no_overlap():
    assert check([['Synthmed B 5 mg tablet', '']], [STOPPED, usage('Synthmed B 5 mg tablet', 'taking')], None) is True


# ---- wording of the refusal, through the real request handler (synthetic patient, temporary database)
import pytest
import db
import interview


@pytest.fixture
def patient(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace')); monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    (tmp_path / 'workspace' / 'Visited' / 'Synthetic').mkdir(parents=True)
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    pid = conn.execute("INSERT INTO patients(key,name,state,folder) VALUES(?,?,?,?)", ('syn-overlap', 'Synthetic Overlap', 'visited', 'Visited/Synthetic')).lastrowid
    conn.commit(); p = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    d = interview.blank(conn, p)
    d['meds'] = [['Synthmed A 10 mg tablet', '', 'one daily', '', '']]
    d['other_meds'] = [['synthmed  A 10 mg   tablet', '', 'twice daily', ''], ['Synthmed A 20 mg tablet', '', 'once daily', '']]
    d['details']['meds'] = [{'packed': '', 'as_instructed': False, 'use_status': 'not_using', 'use_reason': 'stopped_gp', 'use_details': ''}]
    d['details']['other_meds'] = [{'checked': False, 'priority': 0, 'use_reason': '', 'use_details': '', 'kind': 'prescribed', 'use_status': 'taking'} for _ in range(2)]
    interview.validate(d); d['revision'] = 'missing'; interview.save(conn, p, d); conn.commit()
    yield conn, pid
    conn.close()


def save(conn, pid, name):
    got = api.handle(conn, 'GET', '/api/patients/%d/meds' % pid, {}, None)[1]
    body = {'meds': [[name, '']], 'allergies': [], 'interview_usage': got['interview_usage'], 'alternatives': [None]}
    if 'medicine_snapshot_sha256' in got: body['medicine_snapshot_sha256'] = got['medicine_snapshot_sha256']
    return api.handle(conn, 'POST', '/api/patients/%d/meds' % pid, {}, body)


def test_same_name_as_a_not_using_medicine_gets_an_accurate_refusal(patient):
    conn, pid = patient
    status, body = save(conn, pid, 'synthmed  A 10 mg   tablet')
    assert status == 400
    assert body['error'] == 'A listed medicine has the same name as one recorded as not using in the interview. Remove it from the list, or correct its use in the interview.'


def test_different_strength_is_accepted(patient):
    conn, pid = patient
    assert save(conn, pid, 'Synthmed A 20 mg tablet')[0] == 200


def test_helper_ignores_unrelated_names_and_non_stopped_items():
    items = [STOPPED, usage('Synthmed B 5 mg tablet', 'taking')]
    assert api.same_name_as_stopped([['SYNTHMED A 10MG TABLET', '']], items) == ['SYNTHMED A 10MG TABLET']
    assert api.same_name_as_stopped([['Synthmed B 5 mg tablet', '']], items) == []
