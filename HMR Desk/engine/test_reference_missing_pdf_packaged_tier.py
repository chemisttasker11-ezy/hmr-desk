"""When the user's local reference PDF is gone, search serves the packaged tables only if they are intact, clearly labelled
as an unverified extraction. With no intact packaged tables it is unavailable (409). Synthetic fixtures only."""
import hashlib
import json

import api
import brainstorm_tables_lookup as lookup
from test_reference_library import setup
import reference_library as r


def _tables(tmp_path):
    assets = tmp_path / 'assets'
    assets.mkdir()
    entry = {'title': 'Synthetic heading', 'page_start': 3, 'page_end': 3, 'ordinal': 1, 'text': 'synthetic marker-alpha context only'}
    return assets, entry


def test_missing_pdf_without_packaged_tables_is_unavailable(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(api.app_paths, 'engine_assets', lambda: tmp_path / 'none')
    lookup.reset_cache()
    assert api.handle(None, 'POST', '/api/reference/local', {}, {'path': str(p), 'edition': 't', 'local_use_confirmed': True})[0] == 200
    p.unlink()
    status, body = api.handle(None, 'GET', '/api/reference/search', {'q': ['marker-alpha']}, None)
    assert status == 409 and 'unavailable' in body['error']


def test_missing_pdf_with_intact_packaged_tables_is_labelled_unverified(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    real = __import__('pathlib').Path(__file__).resolve().parents[2] / 'references' / 'brainstorm-mmr-v2.0-tables.json'
    assets = tmp_path / 'assets'
    assets.mkdir()
    data = assets / 'brainstorm-mmr-v2.0-tables.json'
    data.write_bytes(real.read_bytes())
    (assets / 'brainstorm-tables-manifest.json').write_text(json.dumps(
        {'file': data.name, 'sha256': hashlib.sha256(data.read_bytes()).hexdigest()}), encoding='ascii')
    monkeypatch.setattr(api.app_paths, 'engine_assets', lambda: assets)
    lookup.reset_cache()
    try:
        api.handle(None, 'POST', '/api/reference/local', {}, {'path': str(p), 'edition': 't', 'local_use_confirmed': True})
        p.unlink()
        # Use a word taken from the packaged entries themselves so the result is not empty by accident.
        structure = lookup.load()
        word = structure['entries'][0]['title'].split()[0]
        status, body = api.handle(None, 'GET', '/api/reference/search', {'q': [word]}, None)
        assert status == 200
        assert body['results'], 'expected a packaged-tier hit for a title word'
        for hit in body['results']:
            assert hit['page_verified'] is False
            assert 'not re-verified' in hit['source']
    finally:
        lookup.reset_cache()
