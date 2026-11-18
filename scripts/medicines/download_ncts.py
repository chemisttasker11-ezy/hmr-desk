#!/usr/bin/env python3
"""Download the latest SNOMED CT-AU (AMT) RF2 Snapshot from the NCTS syndication API.

Flow: OAuth2 client-credentials token -> read the syndication feed -> pick the newest
SCT_RF2_SNAPSHOT entry -> download its ZIP with the bearer token -> verify size and
SHA-256 against the feed -> atomically save. One sequential run, no polling.

Credentials come from the environment (HMR_NCTS_CLIENT_ID / HMR_NCTS_CLIENT_SECRET) or
from a local env file (--env-file, or HMR_NCTS_ENV_FILE, default
~/HMR-Desk-data/secrets/ncts.env). An env file inside this repository is refused.
The secret is never printed, logged or put on a command line.
Use of the data is governed by your NCTS licence (recorded answers: no use outside Australia); check the current terms.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

TOKEN_URL = 'https://api.healthterminologies.gov.au/oauth2/token'
FEED_URL = 'https://api.healthterminologies.gov.au/syndication/v1/syndication.xml'
HOST = 'api.healthterminologies.gov.au'
CATEGORY = 'SCT_RF2_SNAPSHOT'
ATOM = '{http://www.w3.org/2005/Atom}'
NCTS = '{http://ns.electronichealth.net.au/ncts/syndication/asf/extensions/1.0.0}'
MAX_ZIP_BYTES = 3_000_000_000
DEFAULT_ENV_FILE = Path.home() / 'HMR-Desk-data' / 'secrets' / 'ncts.env'
REPO_ROOT = Path(__file__).resolve().parents[2]


class NctsError(Exception):
    pass


def allowed(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == 'https' and parsed.hostname == HOST and not parsed.username


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise NctsError('Unexpected redirect host; the bearer token is not sent elsewhere')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_opener():
    return urllib.request.build_opener(SameHostRedirect()).open


def parse_env_file(path):
    values = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_credentials(env=None, env_file=None):
    """Return (client_id, client_secret) from the environment or a local env file."""
    env = os.environ if env is None else env
    client_id = env.get('HMR_NCTS_CLIENT_ID')
    client_secret = env.get('HMR_NCTS_CLIENT_SECRET')
    if not (client_id and client_secret):
        path = Path(env_file or env.get('HMR_NCTS_ENV_FILE') or DEFAULT_ENV_FILE).expanduser()
        resolved = path.resolve()
        if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
            raise NctsError('Refusing a credentials file inside the repository; keep it outside the checkout')
        if not path.is_file():
            raise NctsError('No NCTS credentials: set HMR_NCTS_CLIENT_ID and HMR_NCTS_CLIENT_SECRET '
                            'or create the local env file (see docs/medicine-data.md)')
        values = parse_env_file(path)
        client_id = client_id or values.get('HMR_NCTS_CLIENT_ID')
        client_secret = client_secret or values.get('HMR_NCTS_CLIENT_SECRET')
    if not (client_id and client_secret):
        raise NctsError('NCTS credentials incomplete: both client id and client secret are required')
    return client_id, client_secret


def fetch_token(client_id, client_secret, opener, token_url=TOKEN_URL):
    if not allowed(token_url):
        raise NctsError('Token URL must be an https NCTS API URL')
    body = urllib.parse.urlencode({'grant_type': 'client_credentials', 'client_id': client_id,
                                   'client_secret': client_secret}).encode()
    request = urllib.request.Request(token_url, data=body, headers={
        'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json',
        'User-Agent': 'HMR-Desk-reference-import/1.0'})
    try:
        with opener(request, timeout=60) as response:
            payload = json.loads(response.read(65536).decode('utf-8'))
    except urllib.error.HTTPError as error:
        # Never echo the response body or request: it could contain credentials.
        raise NctsError(f'NCTS token request failed with HTTP {error.code}; check the client id/secret') from None
    token = payload.get('access_token')
    if not isinstance(token, str) or not token or str(payload.get('token_type', 'bearer')).lower() != 'bearer':
        raise NctsError('NCTS token response did not contain a bearer access token')
    return token


def _authorised(url, token):
    return urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + token, 'User-Agent': 'HMR-Desk-reference-import/1.0'})


def latest_snapshot(feed_xml):
    """Newest SCT_RF2_SNAPSHOT entry: dict(title, url, length, sha256, release, updated)."""
    root = ET.fromstring(feed_xml)
    found = []
    for entry in root.findall(ATOM + 'entry'):
        category = entry.find(ATOM + 'category')
        if category is None or category.get('term') != CATEGORY:
            continue
        link = entry.find(ATOM + 'link')
        if link is None or link.get('type') != 'application/zip':
            continue
        url = link.get('href', '')
        sha = (link.get(NCTS + 'sha256Hash') or '').lower()
        match = re.search(r'-(\d{8})-SNAPSHOT\.zip$', url)
        if not allowed(url) or not match or not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise NctsError('Feed entry is missing a trusted URL, release date or SHA-256')
        try:
            length = int(link.get('length', ''))
        except ValueError:
            raise NctsError('Feed entry has no usable length') from None
        updated = (entry.findtext(ATOM + 'updated') or '')
        found.append({'title': entry.findtext(ATOM + 'title') or '', 'url': url, 'length': length,
                      'sha256': sha, 'release': match.group(1), 'updated': updated})
    if not found:
        raise NctsError('No SCT_RF2_SNAPSHOT entry in the syndication feed')
    return max(found, key=lambda item: (item['release'], item['updated']))


def download_snapshot(entry, token, output, opener):
    if entry['length'] > MAX_ZIP_BYTES:
        raise NctsError('Feed length is larger than the supported RF2 Snapshot size')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_suffix(output.suffix + '.part')
    if part.exists():
        raise NctsError('Partial download exists; inspect or remove it before retrying')
    digest = hashlib.sha256()
    size = 0
    try:
        with opener(_authorised(entry['url'], token), timeout=300) as response, part.open('xb') as dest:
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > entry['length']:
                    raise NctsError('Download is larger than the length declared in the feed')
                digest.update(block)
                dest.write(block)
        if size != entry['length']:
            raise NctsError('Download size does not match the feed')
        if digest.hexdigest() != entry['sha256']:
            raise NctsError('SHA-256 mismatch: the download does not match the feed hash; file discarded')
        with zipfile.ZipFile(part) as archive:
            if archive.testzip():
                raise NctsError('Corrupt ZIP')
        os.replace(part, output)
    finally:
        if part.exists():
            part.unlink()
    return {'bytes': size, 'sha256': digest.hexdigest()}


def run(output_dir, opener=None, env=None, env_file=None, token_url=TOKEN_URL, feed_url=FEED_URL):
    opener = opener or default_opener()
    if not allowed(feed_url):
        raise NctsError('Feed URL must be an https NCTS API URL')
    client_id, client_secret = load_credentials(env, env_file)
    token = fetch_token(client_id, client_secret, opener, token_url)
    with opener(_authorised(feed_url, token), timeout=60) as response:
        entry = latest_snapshot(response.read(20_000_000))
    output = Path(output_dir) / f"ncts-sct-au-{entry['release']}-snapshot.zip"
    if output.exists():
        raise NctsError(f'{output.name} already exists; remove it to download again')
    result = download_snapshot(entry, token, output, opener)
    return {'release': entry['release'], 'title': entry['title'], 'output': str(output),
            'feed_sha256': entry['sha256'], 'verified': True, **result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Folder for the ZIP, outside the repository (reference-downloads)')
    parser.add_argument('--env-file', type=Path, help='Local credentials file outside the repository')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.output_dir, env_file=args.env_file), indent=2))
    except NctsError as error:
        print('Error: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
