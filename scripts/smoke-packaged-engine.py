"""Windows CI smoke test of the real frozen executable (synthetic workspace only)."""
import json
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
