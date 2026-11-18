"""Synthetic-fixture tests for the packaged Brainstorm tables lookup.

No real reference content: the fixture is a tiny synthetic structure with
synthetic page numbers and a synthetic source hash.
"""
import hashlib
import json

import pytest

import brainstorm_tables
import brainstorm_tables_lookup as lookup


def make_entry(ordinal, title, page_start, page_end, fields):
    entry = {'ordinal': ordinal, 'title': title, 'page_start': page_start,
             'page_end': page_end, 'fields': fields}
    entry['content_sha256'] = brainstorm_tables._entry_digest(entry)
    return entry


SYNTHETIC = {
    'citation_version': 1,
    'source': {'pdf_sha256': 'ab' * 32, 'page_count': 9, 'size_bytes': 12345,
               'edition': 'SYNTHETIC edition T0'},
    'entries': [
        make_entry(0, 'Synthetic Alpha Card', 3, 4, [
            {'label': 'Issue to Consider', 'text': 'synthetic renal alpha issue text'},
            {'label': 'Suggested Action', 'text': 'synthetic alpha action spanning pages three and four'},
        ]),
        make_entry(1, 'Synthetic Beta Card', 5, 5, [
            {'label': '', 'text': 'synthetic beta unlabelled prose body'},
        ]),
        make_entry(2, 'Synthetic Gamma Card', 6, 6, [
            {'label': 'Crushable', 'text': 'synthetic gamma crushable yes'},
        ]),
    ],
    'extraction_report': {'section_count': 3, 'entries_without_labels': 1,
                          'unknown_label_lines': {}, 'roundtrip_problems': []},
}


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    assets = tmp_path / 'assets'
    assets.mkdir()
    raw = json.dumps(SYNTHETIC, ensure_ascii=False).encode('utf-8')
    (assets / lookup.DATA_FILENAME).write_bytes(raw)
    manifest = {'file': lookup.DATA_FILENAME, 'sha256': hashlib.sha256(raw).hexdigest()}
    (assets / lookup.MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(lookup.app_paths, 'engine_assets', lambda: assets)
    monkeypatch.setattr(lookup, '_cache', None)
    yield assets
    lookup.reset_cache()


def test_packaged_search_shape_and_pages(packaged):
    result = lookup.search('synthetic alpha')
    assert result['reference']['packaged'] is True
    assert result['reference']['page_reverified'] is False
    assert result['reference']['edition'].endswith('(packaged tables)')
    (hit,) = result['results']
    assert hit['title'] == 'Synthetic Alpha Card'
    assert hit['page'] == 3 and hit['section_page'] == 3 and hit['section_page_end'] == 4
    assert hit['page_verified'] is False
    assert hit['openable'] is False
    assert 'not re-verified' in hit['source']
    assert 'alpha action' in hit['snippet']


def test_search_matches_title_and_labelled_fields(packaged):
    assert [h['title'] for h in lookup.search('crushable')['results']] == ['Synthetic Gamma Card']
    assert [h['title'] for h in lookup.search('beta prose')['results']] == ['Synthetic Beta Card']
    assert lookup.search('absent-nowhere')['results'] == []
    assert lookup.search('')['results'] == []


def test_openable_only_when_registered_pdf_matches_source(packaged, monkeypatch):
    class FakeLibrary:
        @staticmethod
        def current():
            return {'pdf_sha256': SYNTHETIC['source']['pdf_sha256']}
    monkeypatch.setitem(__import__('sys').modules, 'reference_library', FakeLibrary)
    (hit,) = lookup.search('synthetic alpha')['results']
    assert hit['openable'] is True
    assert hit['page_verified'] is False  # opening shows the original; the excerpt stays unverified


def test_tamper_and_version_fail_closed(packaged):
    (packaged / lookup.MANIFEST_FILENAME).write_text(json.dumps({'file': lookup.DATA_FILENAME, 'sha256': '00' * 32}), encoding='utf-8')
    lookup.reset_cache()
    with pytest.raises(lookup.TablesUnavailable):
        lookup.load()

    raw = json.loads((packaged / lookup.DATA_FILENAME).read_bytes().decode('utf-8'))
    raw['citation_version'] = 999
    data = json.dumps(raw).encode('utf-8')
    (packaged / lookup.DATA_FILENAME).write_bytes(data)
    (packaged / lookup.MANIFEST_FILENAME).write_text(json.dumps({'file': lookup.DATA_FILENAME, 'sha256': hashlib.sha256(data).hexdigest()}), encoding='utf-8')
    lookup.reset_cache()
    with pytest.raises(lookup.TablesUnavailable):
        lookup.load()


def test_missing_tables_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(lookup.app_paths, 'engine_assets', lambda: tmp_path)
    lookup.reset_cache()
    with pytest.raises(lookup.TablesUnavailable):
        lookup.search('synthetic')


def test_search_limits(packaged):
    with pytest.raises(lookup.TablesUnavailable):
        lookup.search(' '.join(['w'] * 13))
