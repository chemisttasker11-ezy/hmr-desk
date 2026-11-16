"""Synthetic NCTS download tests. No network, no real credentials, no licensed data."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'scripts' / 'medicines'))
import download_ncts as ncts

BASE = 'https://api.healthterminologies.gov.au/syndication/v1/au/x/'


def make_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('Snapshot/Terminology/synthetic.txt', 'synthetic')
    return buffer.getvalue()


def feed(entries):
    items = ''.join(
        f'<entry><title>{t}</title><link rel="alternate" type="application/zip" href="{u}" length="{n}" '
        f'ncts:sha256Hash="{h}"/><category term="{c}"/><updated>{d}</updated></entry>'
        for t, u, n, h, c, d in entries)
    return ('<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:ncts="http://ns.electronichealth.net.au/ncts/syndication/asf/extensions/1.0.0">'
            + items + '</feed>').encode()


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeOpener:
    def __init__(self, zip_bytes, entries=None, token_status=200):
        self.zip_bytes, self.calls, self.token_status = zip_bytes, [], token_status
        digest = hashlib.sha256(zip_bytes).hexdigest()
        self.entries = entries or [
            ('Aug', BASE + 'D-20260831-SNAPSHOT.zip', 10, 'a' * 64, 'SCT_RF2_SNAPSHOT', '2026-08-30T00:00:00Z'),
            ('Oct', BASE + 'D-20261031-SNAPSHOT.zip', len(zip_bytes), digest, 'SCT_RF2_SNAPSHOT', '2026-10-30T00:00:00Z'),
            ('Oct full', BASE + 'D-20261130-FULL.zip', 10, 'b' * 64, 'SCT_RF2_FULL', '2026-11-30T00:00:00Z'),
        ]

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append((url, request.get_header('Authorization'), request.data))
        if url == ncts.TOKEN_URL:
            if self.token_status != 200:
                raise urllib.error.HTTPError(url, self.token_status, 'denied', {}, io.BytesIO(b'secret-echo'))
            return Resp(json.dumps({'access_token': 'tok', 'token_type': 'bearer'}).encode())
        if url == ncts.FEED_URL:
            return Resp(feed(self.entries))
        return Resp(self.zip_bytes)


ENV = {'HMR_NCTS_CLIENT_ID': 'cid', 'HMR_NCTS_CLIENT_SECRET': 'csecret'}


class NctsTests(unittest.TestCase):
    def test_downloads_latest_snapshot_with_bearer_and_verifies_hash(self):
        data = make_zip()
        opener = FakeOpener(data)
        with tempfile.TemporaryDirectory() as tmp:
            result = ncts.run(tmp, opener=opener, env=ENV)
            self.assertEqual(result['release'], '20261031')
            self.assertTrue(result['verified'])
            self.assertEqual(Path(result['output']).read_bytes(), data)
            self.assertFalse(list(Path(tmp).glob('*.part')))
        token_call, feed_call, zip_call = opener.calls
        self.assertIn(b'grant_type=client_credentials', token_call[2])
        self.assertIsNone(token_call[1])
        self.assertEqual(feed_call[1], 'Bearer tok')
        self.assertEqual(zip_call[1], 'Bearer tok')
        self.assertIn('20261031', zip_call[0])

    def test_hash_mismatch_discards_file(self):
        data = make_zip()
        entries = [('Oct', BASE + 'D-20261031-SNAPSHOT.zip', len(data), '0' * 64, 'SCT_RF2_SNAPSHOT', '2026-10-30T00:00:00Z')]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ncts.NctsError, 'SHA-256 mismatch'):
                ncts.run(tmp, opener=FakeOpener(data, entries), env=ENV)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_size_mismatch_and_oversize_rejected(self):
        data = make_zip()
        digest = hashlib.sha256(data).hexdigest()
        for declared in (len(data) + 1, len(data) - 1):
            entries = [('Oct', BASE + 'D-20261031-SNAPSHOT.zip', declared, digest, 'SCT_RF2_SNAPSHOT', 'x')]
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ncts.NctsError):
                    ncts.run(tmp, opener=FakeOpener(data, entries), env=ENV)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_token_failure_does_not_leak_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ncts.NctsError) as caught:
                ncts.run(tmp, opener=FakeOpener(make_zip(), token_status=400), env=ENV)
        text = str(caught.exception)
        self.assertIn('400', text)
        self.assertNotIn('csecret', text)
        self.assertNotIn('secret-echo', text)

    def test_untrusted_feed_url_rejected(self):
        data = make_zip()
        entries = [('Oct', 'https://evil.example/D-20261031-SNAPSHOT.zip', len(data), hashlib.sha256(data).hexdigest(),
                    'SCT_RF2_SNAPSHOT', 'x')]
        with self.assertRaisesRegex(ncts.NctsError, 'trusted URL'):
            ncts.latest_snapshot(feed(entries))

    def test_no_snapshot_entry(self):
        with self.assertRaisesRegex(ncts.NctsError, 'No SCT_RF2_SNAPSHOT'):
            ncts.latest_snapshot(feed([('Full', BASE + 'D-20261031-FULL.zip', 1, 'a' * 64, 'SCT_RF2_FULL', 'x')]))

    def test_credentials_from_local_env_file_outside_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ncts.env'
            path.write_text('# comment\nHMR_NCTS_CLIENT_ID="abc"\nHMR_NCTS_CLIENT_SECRET=def\n', encoding='utf-8')
            self.assertEqual(ncts.load_credentials(env={}, env_file=path), ('abc', 'def'))

    def test_env_file_inside_repo_refused(self):
        inside = ncts.REPO_ROOT / 'scripts' / 'medicines' / 'ncts.env'
        with self.assertRaisesRegex(ncts.NctsError, 'inside the repository'):
            ncts.load_credentials(env={}, env_file=inside)

    def test_missing_credentials_message_names_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ncts.NctsError, 'No NCTS credentials'):
                ncts.load_credentials(env={}, env_file=Path(tmp) / 'absent.env')

    def test_redirect_to_other_host_blocked(self):
        handler = ncts.SameHostRedirect()
        with self.assertRaises(ncts.NctsError):
            handler.redirect_request(None, None, 302, 'Found', {}, 'https://other.example/file.zip')

    def test_existing_output_not_overwritten(self):
        data = make_zip()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'ncts-sct-au-20261031-snapshot.zip').write_bytes(b'old')
            with self.assertRaisesRegex(ncts.NctsError, 'already exists'):
                ncts.run(tmp, opener=FakeOpener(data), env=ENV)


if __name__ == '__main__':
    unittest.main()
