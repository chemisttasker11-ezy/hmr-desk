"""Regression tests: no patient files are served by the local HTTP listener.

Extract only the HTTP handler so this security regression remains runnable even
when optional PPA/MIMS helper modules are not installed.
"""
import ast
import http.server
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import urlopen
from urllib.parse import urlsplit


def test_local_http_never_serves_patient_files(tmp_path):
    source = Path(__file__).with_name("service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "QuietStatic")
    namespace = {"http": __import__("http"), "urlsplit": urlsplit}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), "service-handler", "exec"), namespace)
    patient = tmp_path / "patient-name"
    patient.mkdir()
    (patient / "referral.pdf").write_bytes(b"SECRET_PATIENT_CONTENT")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), namespace["QuietStatic"])
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for path in ("/", "/patient-name/referral.pdf", "/../patient-name/referral.pdf", "/index.html"):
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=3) as response:
                    assert response.status == 404
            except HTTPError as exc:
                assert exc.code == 404
                assert b"SECRET_PATIENT_CONTENT" not in exc.read()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_no_unprotected_static_server_configured():
    source = Path(__file__).with_name("service.py").read_text(encoding="utf-8")
    assert "('127.0.0.1', 8765)" not in source
    assert "super().do_GET()" not in source
