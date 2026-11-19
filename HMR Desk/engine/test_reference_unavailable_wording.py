"""The unavailable-reference message names the Brainstorm guide and where to register it (synthetic, no PDF needed)."""
import pytest

import db
import reference_library
import routes_reference


def test_message_names_the_brainstorm_guide_and_the_registration_place():
    text = reference_library.UNAVAILABLE_MESSAGE
    assert 'Brainstorm' in text and 'report editor' in text and 'Private local reference' in text
    assert 'original PDF' not in text  # that wording read as the patient's referral


def test_missing_registry_gives_the_message_and_http_409(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'empty'))
    with pytest.raises(reference_library.ReferenceUnavailable) as caught:
        reference_library.current()
    assert str(caught.value) == reference_library.UNAVAILABLE_MESSAGE
    status, payload = routes_reference.handle(None, 'GET', '/api/reference/local', {}, None)
    assert status == 409 and payload == {'error': reference_library.UNAVAILABLE_MESSAGE}
