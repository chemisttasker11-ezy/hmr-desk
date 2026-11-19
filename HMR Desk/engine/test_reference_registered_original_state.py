"""The packaged-tier search says whether the user's own original was never registered or is registered but unavailable.
Labelling only: packaged hits stay unverified, are never openable without the exact registered PDF, and patient-linked
retrieval still fails closed. Synthetic fixtures only."""
import hashlib
import json
from pathlib import Path

import api
import brainstorm_tables_lookup as lookup
import reference_library as r
from test_reference_library import setup


def _packaged(tmp_path, monkeypatch):
    real = Path(__file__).resolve().parents[2] / 'references' / 'brainstorm-mmr-v2.0-tables.json'
    assets = tmp_path / 'assets'
    assets.mkdir()
    data = assets / 'brainstorm-mmr-v2.0-tables.json'
    data.write_bytes(real.read_bytes())
    (assets / 'brainstorm-tables-manifest.json').write_text(json.dumps(
        {'file': data.name, 'sha256': hashlib.sha256(data.read_bytes()).hexdigest()}), encoding='ascii')
    monkeypatch.setattr(api.app_paths, 'engine_assets', lambda: assets)
    lookup.reset_cache()
    word = lookup.load()['entries'][0]['title'].split()[0]
    return word


def _search(word):
    return api.handle(None, 'GET', '/api/reference/search', {'q': [word]}, None)


def test_never_registered_is_labelled_never_registered(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    word = _packaged(tmp_path, monkeypatch)
    try:
        status, body = _search(word)
        assert status == 200 and body['registered_original']['state'] == 'never_registered'
        assert body['results'] and all(h['page_verified'] is False and h['openable'] is False for h in body['results'])
    finally:
        lookup.reset_cache()


def test_registered_then_missing_is_labelled_unavailable_with_reason(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    word = _packaged(tmp_path, monkeypatch)
    try:
        assert api.handle(None, 'POST', '/api/reference/local', {}, {'path': str(p), 'edition': 't', 'local_use_confirmed': True})[0] == 200
        p.unlink()
        status, body = _search(word)
        assert status == 200
        assert body['registered_original']['state'] == 'registered_unavailable' and body['registered_original']['reason']
        assert body['reference']['packaged'] is True and body['reference']['page_reverified'] is False
        assert all(h['page_verified'] is False and h['openable'] is False for h in body['results'])
    finally:
        lookup.reset_cache()


def test_registered_then_changed_is_labelled_unavailable(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    word = _packaged(tmp_path, monkeypatch)
    try:
        api.handle(None, 'POST', '/api/reference/local', {}, {'path': str(p), 'edition': 't', 'local_use_confirmed': True})
        p.write_bytes(p.read_bytes() + b'\nchanged')
        status, body = _search(word)
        assert status == 200 and body['registered_original']['state'] == 'registered_unavailable'
    finally:
        lookup.reset_cache()


def test_intact_registered_original_search_has_no_packaged_label(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(api.app_paths, 'engine_assets', lambda: tmp_path / 'none')
    api.handle(None, 'POST', '/api/reference/local', {}, {'path': str(p), 'edition': 't', 'local_use_confirmed': True})
    status, body = api.handle(None, 'GET', '/api/reference/search', {'q': ['marker-alpha']}, None)
    assert status == 200 and 'registered_original' not in body and body['results'][0]['page'] == 2


def test_missing_original_and_no_tables_is_still_unavailable(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(api.app_paths, 'engine_assets', lambda: tmp_path / 'none')
    lookup.reset_cache()
    api.handle(None, 'POST', '/api/reference/local', {}, {'path': str(p), 'edition': 't', 'local_use_confirmed': True})
    p.unlink()
    status, body = api.handle(None, 'GET', '/api/reference/search', {'q': ['marker-alpha']}, None)
    assert status == 409 and 'unavailable' in body['error']
