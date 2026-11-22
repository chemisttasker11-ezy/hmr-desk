"""Versioned, per-field referral review state; all identities and values are fictional.

Contract 1 and 2 hashes must remain byte-for-byte compatible with previous
signed report evidence. Contract 3 is for newly built reports only.
"""
import clinical_snapshot
import report_auth
from test_report_save_revision import _setup, _saved_report


def args():
    identity = {'name': 'Fictional Patient', 'gp': 'Dr Fiction', 'dob': '1950-01-01'}
    interview = {'conditions': '', 'allergies': 'Fictional allergy',
                 'meds': [], 'other_meds': [], 'details': {'meds': [], 'other_meds': []}}
    pathology = {'records': [], 'verification': {}}
    report = {'issues': []}
    review = {'clinical_review': {'confirmed': True, 'reviewed_by': 'Fictional Pharmacist',
              'allergies_status': 'listed', 'allergies': 'Fictional allergy',
              'conditions': '', 'medicines': '', 'observations': '',
              'source_pages': {'conditions': 0, 'allergies': 1, 'medicines': 0, 'observations': 0}}}
    return identity, interview, pathology, report, review


def test_only_allergies_reviewed_does_not_confirm_absent_conditions():
    identity, interview, pathology, report, source = args()
    old = clinical_snapshot.canonical(identity, interview, pathology, report, source, contract=2)
    assert old['conditions']['review'] == 'confirmed_empty'  # preserved historical defect
    current = clinical_snapshot.canonical(identity, interview, pathology, report, source, contract=3)
    assert current['allergies']['state'] == 'listed'
    assert current['conditions']['review'] == 'unknown'


def test_interview_edited_conditions_not_misrepresented_as_original_referral():
    identity, interview, pathology, report, source = args()
    source['clinical_review']['conditions'] = 'Fictional referral condition'
    source['clinical_review']['source_pages']['conditions'] = 2
    interview['conditions'] = 'Fictional interview-only revision'
    current = clinical_snapshot.canonical(identity, interview, pathology, report, source, contract=3)
    assert current['conditions']['narrative'] == 'Fictional interview-only revision'
    assert current['conditions']['review'] == 'unverified'
    interview['conditions'] = 'Fictional referral condition'
    source_exact = clinical_snapshot.canonical(identity, interview, pathology, report, source, contract=3)
    assert source_exact['conditions']['review'] == 'confirmed'
    assert clinical_snapshot.digest(source_exact) != clinical_snapshot.digest(current)


def test_existing_contract_2_digest_and_marker_remain_valid(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        old = report_auth.clinical_snapshot_hash(conn, patient, 2)
        assert report_auth.clinical_snapshot_matches(
            conn, patient, {'clinical_snapshot_contract': 2, 'clinical_snapshot_sha256': old})
        new = report_auth.clinical_snapshot_hash(conn, patient, 3)
        assert report_auth.clinical_snapshot_matches(
            conn, patient, {'clinical_snapshot_contract': 3, 'clinical_snapshot_sha256': new})
        assert not report_auth.clinical_snapshot_matches(
            conn, patient, {'clinical_snapshot_contract': 3, 'clinical_snapshot_sha256': old}) if new != old else True
