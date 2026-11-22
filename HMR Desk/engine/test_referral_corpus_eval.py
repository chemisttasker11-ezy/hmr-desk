"""Fictional-only checks for the private corpus evaluator."""
import importlib.util
import json
from pathlib import Path

import fitz
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'qa' / 'referral_corpus_eval.py'
spec = importlib.util.spec_from_file_location('referral_corpus_eval', SCRIPT)
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


def _pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    for y, content in enumerate(('Home Medicines Review Referral', 'Patient Details',
                                  'Name: Ms Fictional Example', 'DOB: 01/01/1960',
                                  'Current Medications'), start=1):
        page.insert_text((40, y * 32 + 40), content)
    doc.save(path)
    doc.close()


def test_encrypted_census_is_read_only_and_aggregate_has_no_patient_fields(tmp_path):
    root, vault = tmp_path / 'sources', tmp_path / 'vault'
    root.mkdir()
    source = root / 'fictional-a.pdf'
    _pdf(source)
    (root / 'fictional-copy.pdf').write_bytes(source.read_bytes())
    before = source.read_bytes()
    password = 'fictional passphrase with sufficient length'
    report = evaluator.run(root, vault, password)
    assert report['candidate_files'] == 2
    assert report['exact_duplicate_extra_files'] == 1
    assert report['real_file_gold_labels'] == 0
    assert source.read_bytes() == before
    ciphertext = (vault / 'referral-corpus-private.enc').read_bytes()
    assert b'Fictional' not in ciphertext
    assert len(evaluator.decrypt(ciphertext, password)['records']) == 2
    assert evaluator.run(root, vault, password)['candidate_files'] == 2
    aggregate = json.loads((vault / 'referral-corpus-AGGREGATE.json').read_text())
    assert 'Fictional' not in json.dumps(aggregate)
    assert 'fictional-a.pdf' not in json.dumps(aggregate)
    with pytest.raises(Exception):
        evaluator.decrypt(ciphertext, 'invalid passphrase with length')


def test_rejects_output_inside_source_and_outside_link(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    with pytest.raises(ValueError, match='outside the source'):
        evaluator.run(root, root / 'output', 'fictional passphrase long enough')
    outside = tmp_path / 'outside.pdf'
    _pdf(outside)
    link = root / 'external.pdf'
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip('Symlink creation requires additional permissions')
    report = evaluator.run(root, tmp_path / 'vault', 'fictional passphrase long enough')
    assert report['candidate_files'] == 1
    assert report['status_counts']['linked_skipped'] == 1


def test_modified_source_invalidates_resumed_cache(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    file = root / 'fictional.pdf'
    _pdf(file)
    output = tmp_path / 'private'
    secret = 'fictional private secret with length'
    assert evaluator.run(root, output, secret)['pages_processed'] == 1
    file.write_bytes(b'invalid pdf')
    updated = evaluator.run(root, output, secret)
    assert updated['pages_processed'] == 0
    assert updated['status_counts']['unreadable_or_unsupported'] == 1
