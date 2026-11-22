"""Synthetic: GP/clinic detail keys in the clinical snapshot digest stay backward compatible
without letting later edits or removals of those details go unnoticed."""
import clinical_snapshot
import report_auth
from test_report_save_revision import _setup, _saved_report

KEYS = clinical_snapshot.GP_DETAIL_KEYS


def _fresh(conn, pid):
    return conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()


def _set(conn, pid, **values):
    with conn:
        for key, value in values.items():
            assert key in KEYS
            conn.execute(f'UPDATE patients SET {key}=? WHERE id=?', (value, pid))


def _evidence(conn, patient, contract):
    ev = {'clinical_snapshot_sha256': report_auth.clinical_snapshot_hash(conn, patient, contract)}
    if contract == 2:
        ev['clinical_snapshot_contract'] = 2
    return ev


def _patient(conn):
    patient, _ = _saved_report(conn)
    _set(conn, patient['id'], **{k: '' for k in KEYS})
    return patient['id']


# Digest computed once with the pre-PR29 clinical_snapshot.py (main 46d7df2) for this exact
# synthetic input, which has a non-empty clinic. A legacy build recorded this value.
HISTORIC_DIGEST = '59584f943506d34dfe02787ba830b77fdde21265a3601a62a49bd597c4c6754e'
HISTORIC_IDENTITY = {'name': 'Synthetic Patient', 'dob': '01-Jan-1950', 'gp': 'Dr Synthetic',
                     'clinic': 'Synthetic Clinic', 'referral_date': '2026-11-01'}


def test_legacy_contract_reproduces_the_historic_digest_including_nonempty_clinic():
    legacy = clinical_snapshot.canonical(HISTORIC_IDENTITY, {}, {}, {}, contract=1)
    assert set(legacy['patient_identity']) == {'name', 'dob', 'gp', 'referral_date'}  # old canonical never held clinic
    assert clinical_snapshot.digest(legacy) == HISTORIC_DIGEST
    current = clinical_snapshot.canonical(HISTORIC_IDENTITY, {}, {}, {})
    assert set(KEYS) <= set(current['patient_identity'])
    assert clinical_snapshot.digest(current) != HISTORIC_DIGEST
    # Columns that did not exist before PR29 count in the legacy contract once they hold data.
    filled = clinical_snapshot.canonical(dict(HISTORIC_IDENTITY, gp_provider='Synthetic'), {}, {}, {}, contract=1)
    assert filled['patient_identity']['gp_provider'] == 'Synthetic'
    assert clinical_snapshot.digest(filled) != HISTORIC_DIGEST


def test_unedited_legacy_evidence_stays_current_and_new_evidence_is_marked(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        pid = _patient(conn)
        legacy = _evidence(conn, _fresh(conn, pid), 1)
        assert 'clinical_snapshot_contract' not in legacy
        assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), legacy)
        assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), _evidence(conn, _fresh(conn, pid), 2))


def test_legacy_evidence_with_nonempty_clinic_at_build_stays_current(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        pid = _patient(conn)
        _set(conn, pid, clinic='Synthetic Clinic')
        legacy = _evidence(conn, _fresh(conn, pid), 1)
        assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), legacy)
        # Digest level only: legacy evidence never digested clinic. The report-text check below covers it.
        _set(conn, pid, clinic='Edited clinic')
        assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), legacy)
        _set(conn, pid, clinic='')
        assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), legacy)
        # A detail the legacy digest could not hold still invalidates it.
        _set(conn, pid, clinic_phone='0700 000 000')
        assert not report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), legacy)
        # Contract 2 digests clinic: edit and removal are detected.
        _set(conn, pid, clinic='Synthetic Clinic', clinic_phone='')
        built = _evidence(conn, _fresh(conn, pid), 2)
        for value in ('Edited clinic', '', None):
            _set(conn, pid, clinic=value)
            assert not report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), built), repr(value)


def test_detail_added_after_legacy_build_invalidates_it(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        pid = _patient(conn)
        legacy = _evidence(conn, _fresh(conn, pid), 1)
        for key in clinical_snapshot.LEGACY_NEW_KEYS:
            _set(conn, pid, **{k: '' for k in KEYS})
            _set(conn, pid, **{key: 'Synthetic value'})
            assert not report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), legacy), key


def test_new_evidence_detects_added_changed_and_removed_details(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        pid = _patient(conn)
        empty_built = _evidence(conn, _fresh(conn, pid), 2)
        _set(conn, pid, gp_provider='Synthetic provider')
        assert not report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), empty_built)  # added
        built = _evidence(conn, _fresh(conn, pid), 2)
        assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), built)
        _set(conn, pid, gp_provider='Synthetic provider changed')
        assert not report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), built)  # changed
        _set(conn, pid, gp_provider='')
        assert not report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), built)  # nonempty -> empty
        _set(conn, pid, gp_provider=None)
        assert not report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), built)  # nonempty -> null
        for key in KEYS:
            _set(conn, pid, **{k: '' for k in KEYS})
            _set(conn, pid, **{key: 'Synthetic value'})
            built = _evidence(conn, _fresh(conn, pid), 2)
            assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), built), key
            for value in ('', None, 'Other value'):
                _set(conn, pid, **{key: value})
                assert not report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), built), (key, value)
            _set(conn, pid, **{key: 'Synthetic value'})  # restored -> matches again
            assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), built), key


def test_unknown_marker_and_malformed_evidence_fail_closed(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        pid = _patient(conn)
        patient = _fresh(conn, pid)
        good = _evidence(conn, patient, 2)
        for marker in (1, 4, 0, '2', '3', True, False, None, 2.5, [2]):
            assert not report_auth.clinical_snapshot_matches(
                conn, patient, dict(good, clinical_snapshot_contract=marker)), repr(marker)
        # A current-contract digest presented without a marker is read as legacy and does not match.
        assert not report_auth.clinical_snapshot_matches(
            conn, patient, {'clinical_snapshot_sha256': good['clinical_snapshot_sha256']})
        # A removed marker cannot validate through the legacy projection, empty or filled details alike.
        _set(conn, pid, clinic='C', gp_provider='P', clinic_address='A', clinic_phone='T')
        full = _evidence(conn, _fresh(conn, pid), 2)
        assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), full)
        assert not report_auth.clinical_snapshot_matches(
            conn, _fresh(conn, pid), {'clinical_snapshot_sha256': full['clinical_snapshot_sha256']})
        for bad in (None, {}, {'clinical_snapshot_sha256': None}, {'clinical_snapshot_sha256': ''}, 'x'):
            assert not report_auth.clinical_snapshot_matches(conn, patient, bad)


def _signoff_case(tmp_path, monkeypatch, legacy):
    import json
    import db
    from test_report_auth import case
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    pid = patient['id']
    _set(conn, pid, **{k: '' for k in KEYS})
    patient = _fresh(conn, pid)
    latest = conn.execute("SELECT id,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    detail = json.loads(latest['detail'])
    detail.update(_evidence(conn, patient, 1 if legacy else 2))
    if legacy:
        detail.pop('clinical_snapshot_contract', None)
    with conn:
        conn.execute('UPDATE events SET detail=? WHERE id=?', (json.dumps(detail), latest['id']))
    proof = report_auth.check_approval(conn, patient, body)  # real verification, evidence not rehashed afterwards
    assert ('clinical_snapshot_contract' in proof) is (not legacy)
    with conn:
        db.log(conn, pid, 'signed_off', proof, 'app')
    assert report_auth.check_sent(conn, _fresh(conn, pid))
    return conn, pid


def report_auth_evidence(conn, pid):
    import json
    row = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='signed_off' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    return json.loads(row['detail'])


def test_signed_legacy_report_verifies_until_a_new_detail_is_added(tmp_path, monkeypatch):
    import pytest
    conn, pid = _signoff_case(tmp_path, monkeypatch, legacy=True)
    import report_status
    assert report_status.report_status(conn, _fresh(conn, pid))['snapshot_coverage'] == 'legacy_gp_block_by_report_text'
    assert report_status.report_status(conn, _fresh(conn, pid))['status'] == 'current'
    _set(conn, pid, clinic='Edited clinic')  # digest never covered clinic; the signed report text did
    assert report_auth.clinical_snapshot_matches(conn, _fresh(conn, pid), report_auth_evidence(conn, pid))
    with pytest.raises(ValueError):
        report_auth.check_sent(conn, _fresh(conn, pid))
    status = report_status.report_status(conn, _fresh(conn, pid))
    assert status['status'] == 'outdated' and 'clinical_record_changed' in status['reasons']
    _set(conn, pid, clinic='')  # back to what was signed
    assert report_auth.check_sent(conn, _fresh(conn, pid))
    _set(conn, pid, clinic_address='1 Synthetic Street')
    with pytest.raises(ValueError):
        report_auth.check_sent(conn, _fresh(conn, pid))


def test_signed_new_report_fails_on_any_later_detail_change_or_removal(tmp_path, monkeypatch):
    import pytest
    conn, pid = _signoff_case(tmp_path, monkeypatch, legacy=False)
    _set(conn, pid, gp_provider='Synthetic provider')
    with pytest.raises(ValueError):
        report_auth.check_sent(conn, _fresh(conn, pid))
    _set(conn, pid, gp_provider='')  # back to the signed state verifies again
    assert report_auth.check_sent(conn, _fresh(conn, pid))
    _set(conn, pid, clinic='Edited clinic')
    with pytest.raises(ValueError):
        report_auth.check_sent(conn, _fresh(conn, pid))


def test_unsigned_legacy_build_with_clinic_edit_shows_outdated_without_false_positive(tmp_path, monkeypatch):
    import report_status
    conn, pid = _signoff_case(tmp_path, monkeypatch, legacy=True)
    with conn:
        conn.execute("DELETE FROM events WHERE type='signed_off'")
    status = report_status.report_status(conn, _fresh(conn, pid))
    assert status['status'] == 'current' and status['reasons'] == []
    _set(conn, pid, clinic='Edited clinic')
    status = report_status.report_status(conn, _fresh(conn, pid))
    assert status['status'] == 'outdated' and 'clinical_record_changed' in status['reasons']
    _set(conn, pid, clinic='')
    assert report_status.report_status(conn, _fresh(conn, pid))['status'] == 'current'
