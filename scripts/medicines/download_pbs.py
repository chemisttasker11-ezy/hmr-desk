#!/usr/bin/env python3
"""Download ONE official PBS API CSV ZIP selected from PBS publications.

No guessed endpoint versions, no parallel requests, no polling. A 429 stops the
run; honour Retry-After and the shared public API's >=20 second spacing before
manually retrying. Prefer this bulk ZIP to API calls per medicine.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
import zipfile


def allowed(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == 'https' and parsed.hostname in ('pbs.gov.au', 'www.pbs.gov.au', 'data.pbs.gov.au') and not parsed.username


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise ValueError('Unexpected download redirect host; inspect publisher link')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, output):
    if not allowed(url):
        raise ValueError('Use the HTTPS ZIP link from the official PBS publications page')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_suffix(output.suffix + '.part')
    if part.exists():
        raise ValueError('Partial download exists; inspect/remove it before retrying')
    opener = urllib.request.build_opener(OfficialRedirect())
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'HMR-Desk-reference-import/1.0'})
        with opener.open(request, timeout=120) as response, part.open('xb') as dest:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > 200_000_000:
                    raise ValueError('Unexpectedly large PBS download')
                dest.write(block)
        with zipfile.ZipFile(part) as archive:
            if archive.testzip():
                raise ValueError('Corrupt PBS ZIP')
        os.replace(part, output)
    finally:
        if part.exists():
            part.unlink()
    return {'url': url, 'bytes': output.stat().st_size,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    print(json.dumps(download(args.url, args.output), indent=2))
