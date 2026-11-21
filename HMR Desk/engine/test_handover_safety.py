"""Synthetic-only senior handover safety regressions: identity and export integrity."""
import hashlib
import json
import uuid

import pytest

import db
import records
import referral_entry


@pytest.mark.parametrize('dob', ('1940-02-01', '01/02/1940', '01-02-1940', '01 Feb 1940', '01 February 1940'))
def test_canonical_dob_accepts_supported_formats(dob):
    assert referral_entry._canonical_dob(dob) == '1940-02-01'


def test_malformed_legacy_dob_is_not_positive_evidence_of_distinct_identity():
    assert referral_entry._canonical_dob('unknown') is None
    assert referral_entry._canonical_dob('31/02/1940') is None


def _review(conn, tmp_path):
    source = tmp_path / 'synthetic.pdf'
    payload = b'%PDF-1.4\n%SYNTHETIC ONLY'
    source.write_bytes(payload)
    token = uuid.uuid4().hex
    conn.execute('INSERT INTO meta(key,value) VALUES (?,?)', (
        'referral_review_' + token,
        json.dumps({'source': str(source), 'sha256': hashlib.sha256(payload).hexdigest(),
                    'fields': {}, 'kind': 'referral'})))
    conn.commit()
    return token


@pytest.mark.parametrize(('stored_dob', 'reviewed_dob'), (
    ('01/02/1940', '1940-02-01'),
    ('1940-02-01', '01 Feb 1940'),
    ('01-02-1940', '01 February 1940'),
))
def test_same_name_equivalent_dob_never_creates_duplicate(tmp_path, monkeypatch, stored_dob, reviewed_dob):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'data'))
    conn = db.connect(str(tmp_path / 'data' / 'test.db'))
    try:
        conn.execute('INSERT INTO patients(key,name,dob) VALUES (?,?,?)',
                     ('sam example', 'Sam Example', stored_dob))
        conn.commit()
        token = _review(conn, tmp_path)
        with pytest.raises(ValueError, match='Name and date of birth match'):
            referral_entry.commit(conn, token, {'name': 'Sam Example', 'dob': reviewed_dob}, distinct_person=True)
        assert conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0] == 1
    finally:
        conn.close()


def test_same_name_unparseable_legacy_dob_and_no_real_id_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'data'))
    conn = db.connect(str(tmp_path / 'data' / 'test.db'))
    try:
        conn.execute('INSERT INTO patients(key,name,dob,medicare) VALUES (?,?,?,?)',
                     ('sam example', 'Sam Example', 'uncertain', 'unknown'))
        conn.commit()
        token = _review(conn, tmp_path)
        with pytest.raises(ValueError, match='Different reliable identifiers'):
            referral_entry.commit(conn, token, {
                'name': 'Sam Example', 'dob': '1945-05-05',
                'medicare': 'unavailable'}, distinct_person=True)
        assert conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0] == 1
    finally:
        conn.close()


def test_same_name_genuinely_different_dates_permit_explicit_split(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'data'))
    conn = db.connect(str(tmp_path / 'data' / 'test.db'))
    try:
        conn.execute('INSERT INTO patients(key,name,dob) VALUES (?,?,?)',
                     ('sam example', 'Sam Example', '01/02/1940'))
        conn.commit()
        token = _review(conn, tmp_path)
        result = referral_entry.commit(conn, token, {
            'name': 'Sam Example', 'dob': '1945-02-20'}, distinct_person=True)
        assert result['patient_id'] > 0
        assert conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0] == 2
    finally:
        conn.close()


def test_export_failure_never_leaves_partial_clinical_file(tmp_path, monkeypatch):
    target = tmp_path / 'interview.json'
    original_fsync = records.os.fsync
    def fail_fsync(_):
        raise OSError('synthetic disk full')
    monkeypatch.setattr(records.os, 'fsync', fail_fsync)
    with pytest.raises(OSError, match='synthetic disk full'):
        records._export_one_atomic(target, b'{"important":"complete"}')
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(records.os, 'fsync', original_fsync)
    assert records._export_one_atomic(target, b'{"important":"complete"}') == 'written'
    assert target.read_bytes() == b'{"important":"complete"}'


def test_export_link_failure_and_retry_preserves_previous_exports(tmp_path, monkeypatch):
    target = tmp_path / 'report_spec.json'
    original_link = records.os.link
    def denied(*_args, **_kwargs):
        raise OSError('synthetic filesystem does not support atomic publish')
    monkeypatch.setattr(records.os, 'link', denied)
    with pytest.raises(OSError, match='atomic publish'):
        records._export_one_atomic(target, b'{"a":1}')
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(records.os, 'link', original_link)
    assert records._export_one_atomic(target, b'{"a":1}') == 'written'
    assert records._export_one_atomic(target, b'{"a":2}') == 'exists'
    assert target.read_bytes() == b'{"a":1}'
    assert not list(tmp_path.glob('.hmr-export-*'))
