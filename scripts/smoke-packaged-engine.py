"""Windows CI smoke test of the real frozen executable (synthetic workspace only)."""
import json
import hashlib
import fitz
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def main():
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise RuntimeError('Packaged engine not found')
    mapping = executable.parent / '_internal' / 'drug_classes.json'
    assert mapping.is_file() and isinstance(json.loads(mapping.read_text(encoding='utf-8')), dict), 'Application-owned medicine class mapping was not packaged'
    with tempfile.TemporaryDirectory(prefix='hmr-m2-smoke-') as d:
        workspace = Path(d) / 'workspace with spaces'
        data = Path(d) / 'userdata'
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        token = secrets.token_hex(32)
        env = {**os.environ, 'HMR_SESSION_TOKEN': token}
        cmd = [str(executable), '--data-dir', str(data), '--workspace',
               str(workspace), '--port', str(port)]
        process = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            health = None
            last_error = 'not yet attempted'
            until = time.monotonic() + 35
            while time.monotonic() < until:
                if process.poll() is not None:
                    raise RuntimeError('Engine exited before ready')
                try:
                    req = Request(f'http://127.0.0.1:{port}/api/health',
                                  headers={'X-HMR-Token': token})
                    with urlopen(req, timeout=1.5) as resp:
                        health = json.load(resp)
                    break
                except (OSError, ValueError) as exc:
                    last_error = type(exc).__name__ + ': ' + str(exc)[:120]
                    time.sleep(0.25)
            if not health:
                log = data / 'engine.log'
                print('Engine process state:', process.poll(), 'Last health error:', last_error)
                print('Token file exists:', (data / 'api_token').is_file())
                if log.is_file():
                    print('Synthetic engine log tail:', '\\n'.join(log.read_text(errors='replace').splitlines()[-18:]))
                raise AssertionError('No authenticated health response')
            assert health['ready']
            assert health['engine_version'] == '0.1.0'
            assert (data / 'hmr.db').is_file()
            assert (data / 'api_token').is_file()
            assert (data / 'api_token').read_text() == token
            try:
                urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2)
                raise AssertionError('Unauthenticated health route is open')
            except HTTPError as exc:
                assert exc.code == 403
            try:
                urlopen(f'http://127.0.0.1:{port}/a-patient/referral.pdf', timeout=2)
                raise AssertionError('Patient files exposed over HTTP')
            except HTTPError as exc:
                assert exc.code == 404
            def reference_call(method, path, body=None):
                request = Request(f'http://127.0.0.1:{port}'+path,
                    headers={'X-HMR-Token': token, 'Content-Type': 'application/json'},
                    data=json.dumps(body).encode() if body is not None else None, method=method)
                with urlopen(request,timeout=10) as response: return json.load(response)
            synthetic_pdf=Path(d)/'synthetic-private-reference.pdf'
            document=fitz.open()
            first=document.new_page()
            first.insert_text((72,72),'Brainstorm synthetic acceptance heading',fontname='hebo',fontsize=16)
            first.insert_text((72,110),'Synthetic first physical page context only, no clinical reference or patient data.')
            second=document.new_page()
            second.insert_text((72,100),'Continuation synthetic-marker-alpha for checking the original physical PDF page.')
            document.save(synthetic_pdf);document.close()
            expected_hash=hashlib.sha256(synthetic_pdf.read_bytes()).hexdigest()
            registered=reference_call('POST','/api/reference/local',{'path':str(synthetic_pdf),
                'edition':'Synthetic package smoke V1','local_use_confirmed':True})
            assert registered['pdf_sha256']==expected_hash and registered['page_count']==2
            assert 'path' not in registered, 'Reference status unnecessarily exposes filesystem path'
            assert reference_call('GET','/api/reference/local')['edition']=='Synthetic package smoke V1'
            found=reference_call('GET','/api/reference/search?q=synthetic-marker-alpha')['results']
            assert len(found)==1 and found[0]['page']==2 and found[0]['section_page']==1
            assert found[0]['pdf_sha256']==expected_hash and found[0]['review_status']=='pharmacist_review_required'
            original=reference_call('POST','/api/reference/open',{'pdf_sha256':expected_hash,'page':2})
            assert original['page']==2 and Path(original['path'])==synthetic_pdf
            synthetic_pdf.write_bytes(synthetic_pdf.read_bytes()+b'\nchanged')
            try:
                reference_call('POST','/api/reference/open',{'pdf_sha256':expected_hash,'page':2})
                raise AssertionError('Changed reference opened with a stale hash')
            except HTTPError as exc: assert exc.code==409
            print('PASS: frozen private local-reference registration, physical-page search and stale-original refusal (synthetic PDF only)')
            req = Request(f'http://127.0.0.1:{port}/api/engine/stop',
                          headers={'X-HMR-Token': token, 'Content-Type': 'application/json'},
                          data=b'{}', method='POST')
            with urlopen(req, timeout=3) as response:
                assert json.load(response)['stopping']
            process.wait(timeout=8)
            assert process.returncode == 0, 'Engine did not exit cleanly after authenticated stop'
            print('PASS: frozen engine startup, session auth, isolated workspace, static-file denial and graceful shutdown')
        finally:
            process.terminate()
            try:
                process.wait(timeout=7)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=7)


if __name__ == '__main__':
    main()
