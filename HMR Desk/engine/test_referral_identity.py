"""Same-name referrals are candidates, not auto-merged or unconditionally rejected."""
import hashlib
import json
import uuid

import pytest
import db
import referral_entry


def test_same_name_requires_explicit_different_identifiers(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    data = tmp_path / 'userdata'
    workspace.mkdir()
    data.mkdir()
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(data))
    conn = db.connect(str(data / 'hmr.db'))
    folder = workspace / 'TO SORT' / 'Referral-old'
    folder.mkdir(parents=True)
    with conn:
        conn.execute('INSERT INTO patients(key,name,dob,medicare,folder) VALUES (?,?,?,?,?)',
                     ('sam example', 'Sam Example', '1940-04-10', '1234567890', 'TO SORT/Referral-old'))
    source = tmp_path / 'source.pdf'
    payload = b'%PDF-1.4\n%SYNTHETIC ONLY'
    source.write_bytes(payload)
    token = uuid.uuid4().hex
    with conn:
        conn.execute('INSERT INTO meta(key,value) VALUES (?,?)',
                     ('referral_review_' + token, json.dumps({
                         'source': str(source), 'sha256': hashlib.sha256(payload).hexdigest(),
                         'fields': {}, 'kind': 'referral'})))
    fields = {'name': 'Sam Example', 'dob': '1945-02-20', 'medicare': '9999999999'}
    with pytest.raises(ValueError, match='matches an existing record'):
        referral_entry.commit(conn, token, fields)
    with pytest.raises(ValueError, match='Name and date of birth'):
        referral_entry.commit(conn, token, {**fields, 'dob': '1940-04-10'}, distinct_person=True)
    with pytest.raises(ValueError, match='Identifier matches'):
        referral_entry.commit(conn, token, {**fields, 'medicare': '1234567890'}, distinct_person=True)
    result = referral_entry.commit(conn, token, fields, distinct_person=True)
    assert result['patient_id'] > 0
    people = conn.execute('SELECT key,dob,folder FROM patients ORDER BY id').fetchall()
    assert len(people) == 2
    assert people[0]['key'] == 'sam example'
    assert people[1]['key'].startswith('sam example @')
    assert people[0]['dob'] != people[1]['dob']
    assert (workspace / people[1]['folder'] / 'referral.pdf').read_bytes() == payload
    conn.close()
