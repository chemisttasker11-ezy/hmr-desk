"""Synthetic safety coverage for the optional original Word-builder adapter.

No Word, private templates, patient information or external processes required.
"""
import errno
import hashlib
from pathlib import Path
from unittest import mock

import pytest

import original_builder_adapter as adapter


def test_cross_volume_publish_uses_verified_sibling_and_cleans_it(tmp_path, monkeypatch):
    source = tmp_path / 'source' / 'report.docx'
    source.parent.mkdir()
    source.write_bytes(b'synthetic report document')
    target = tmp_path / 'destination' / 'report.docx'
    target.parent.mkdir()
    real_link = adapter.os.link
    attempts = []

    def cross_volume_link(left, right):
        attempts.append((Path(left), Path(right)))
        if Path(left) == source:
            raise OSError(errno.EXDEV, 'synthetic cross-volume link')
        return real_link(left, right)

    monkeypatch.setattr(adapter.os, 'link', cross_volume_link)
    adapter.claim(source, target)
    assert target.read_bytes() == source.read_bytes()
    assert len(attempts) == 2
    assert attempts[-1][0].parent == target.parent
    assert not list(target.parent.glob('.hmr-report-publish-*'))


def test_failed_publication_never_leaves_partial_clinical_document(tmp_path, monkeypatch):
    source = tmp_path / 'source.docx'
    source.write_bytes(b'synthetic complete')
    target = tmp_path / 'output.docx'
    def fail_link(left, right):
        if Path(left) == source:
            raise OSError(errno.EXDEV, 'cross-volume')
        raise OSError(errno.EOPNOTSUPP, 'no hard links on this filesystem')
    monkeypatch.setattr(adapter.os, 'link', fail_link)
    with pytest.raises(OSError, match='no hard links'):
        adapter.claim(source, target)
    assert not target.exists()
    assert not list(tmp_path.glob('.hmr-report-publish-*'))
    assert source.read_bytes() == b'synthetic complete'


def test_existing_report_never_overwritten_with_fallback(tmp_path, monkeypatch):
    source = tmp_path / 'source.docx'
    source.write_bytes(b'new report')
    target = tmp_path / 'report.docx'
    target.write_bytes(b'important previously signed report')
    def exists(*args):
        raise FileExistsError('already exists')
    monkeypatch.setattr(adapter.os, 'link', exists)
    with pytest.raises(FileExistsError):
        adapter.claim(source, target)
    assert target.read_bytes() == b'important previously signed report'
    assert not list(tmp_path.glob('.hmr-report-publish-*'))


def test_sync_failure_during_cross_volume_copy_cleans_private_temp(tmp_path, monkeypatch):
    source = tmp_path / 'source.docx'
    source.write_bytes(b'complete document')
    target = tmp_path / 'output.docx'
    real_link = adapter.os.link
    def cross_volume_link(left, right):
        if Path(left) == source:
            raise OSError(errno.EXDEV, 'cross-volume')
        return real_link(left, right)
    monkeypatch.setattr(adapter.os, 'link', cross_volume_link)
    monkeypatch.setattr(adapter.os, 'fsync', lambda _fd: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError, match='disk full'):
        adapter.claim(source, target)
    assert not target.exists()
    assert not list(tmp_path.glob('.hmr-report-publish-*'))


def test_frozen_worker_rejects_unpinned_script_without_executing(tmp_path, monkeypatch):
    marker = tmp_path / 'unexpected-execution.txt'
    script = tmp_path / 'build.py'
    script.write_text("from pathlib import Path\nPath(%r).write_text('BAD')\n" % str(marker))
    spec = tmp_path / 'spec.json'
    spec.write_text('{}')
    monkeypatch.setattr(adapter.sys, 'frozen', True, raising=False)
    assert adapter.worker_main([str(script), str(spec)]) == 6
    assert not marker.exists()


def test_frozen_worker_rejects_bad_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter.sys, 'frozen', True, raising=False)
    assert adapter.worker_main([]) == 6
    assert adapter.worker_main(['a', 'b', 'c']) == 6


def test_frozen_worker_runs_only_pinned_asset_set(tmp_path, monkeypatch):
    script = tmp_path / 'build.py'
    script.write_text('x = 1\n')
    template = tmp_path / 'Template - Copy.docx'
    template.write_bytes(b'synthetic template')
    powershell = tmp_path / 'word2pdf.ps1'
    powershell.write_bytes(b'synthetic command')
    spec = tmp_path / 'spec.json'
    spec.write_text('{}')
    hashes = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
              for name in ('build.py', 'Template - Copy.docx', 'word2pdf.ps1')}
    monkeypatch.setattr(adapter, 'PINNED', hashes)
    monkeypatch.setattr(adapter.sys, 'frozen', True, raising=False)
    original_argv = adapter.sys.argv[:]
    try:
        assert adapter.worker_main([str(script), str(spec)]) == 0
        template.write_bytes(b'tampered')
        assert adapter.worker_main([str(script), str(spec)]) == 6
    finally:
        adapter.sys.argv = original_argv
