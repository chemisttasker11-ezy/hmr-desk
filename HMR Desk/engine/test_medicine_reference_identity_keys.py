"""Optional catalogue-owned generic/brand on a stored medicine reference (synthetic names only)."""
import interview

BASE = {'source': 'amt', 'code': '1', 'display': 'Synthetic Brandex 20 mg tablet', 'release': 'r1'}


def test_saved_references_without_identity_stay_valid():
    assert interview.valid_reference(dict(BASE))
    assert interview.reference_identity({'reference': dict(BASE)}) == {'generic_name': None, 'brand_name': None}


def test_optional_identity_keys_are_accepted_and_returned():
    ref = dict(BASE, generic_name='syntheticgeneric', brand_name='Synthetic Brandex')
    assert interview.valid_reference(ref)
    assert interview.reference_identity({'reference': ref}) == {'generic_name': 'syntheticgeneric', 'brand_name': 'Synthetic Brandex'}
    assert interview.reference_identity({'reference': dict(BASE, generic_name='syntheticgeneric')})['brand_name'] is None


def test_unknown_blank_or_non_text_keys_are_still_refused():
    assert not interview.valid_reference(dict(BASE, extra='x'))
    assert not interview.valid_reference(dict(BASE, generic_name=''))
    assert not interview.valid_reference(dict(BASE, brand_name=None))
    assert not interview.valid_reference(dict(BASE, generic_name='x' * 401))
    bare = dict(BASE); del bare['code']
    assert not interview.valid_reference(bare)


def test_reference_text_is_unchanged_by_identity_keys():
    plain = interview.reference_text({'reference': dict(BASE)})
    assert interview.reference_text({'reference': dict(BASE, generic_name='g', brand_name='b')}) == plain
    assert interview.reference_identity({'reference': 'garbage'}) == {'generic_name': None, 'brand_name': None}


def _proposal(monkeypatch, details):
    import medicine_review, records
    data = {'meds': [['Synthetic Brandex 20 mg tablet', 'x', 'y']], 'other_meds': [], 'allergies': '', 'details': {'meds': [details], 'other_meds': []}}
    monkeypatch.setattr(records, 'get_json', lambda conn, pid, name: data)
    monkeypatch.setattr(interview, 'validate', lambda d: None)
    monkeypatch.setattr(medicine_review, 'interview_usage', lambda conn, p: [])
    monkeypatch.setattr(medicine_review.external_helpers.mims, 'ingredients', lambda text: [text])
    return medicine_review.proposal(None, {'id': 1})['meds']


def test_proposal_uses_catalogue_names_only_when_the_reference_has_them(monkeypatch):
    ref = dict(BASE, generic_name='syntheticgeneric', brand_name='Synthetic Brandex')
    assert _proposal(monkeypatch, {'use_status': 'taking', 'reference': ref}) == [['syntheticgeneric', 'Synthetic Brandex']]


def test_proposal_without_catalogue_names_keeps_the_row_text_unparsed(monkeypatch):
    assert _proposal(monkeypatch, {'use_status': 'taking', 'reference': dict(BASE)}) == [['Synthetic Brandex 20 mg tablet', '']]
    assert _proposal(monkeypatch, {'use_status': 'taking'}) == [['Synthetic Brandex 20 mg tablet', '']]
    only_brand = dict(BASE, brand_name='Synthetic Brandex')
    assert _proposal(monkeypatch, {'use_status': 'taking', 'reference': only_brand}) == [['Synthetic Brandex 20 mg tablet', 'Synthetic Brandex']]
