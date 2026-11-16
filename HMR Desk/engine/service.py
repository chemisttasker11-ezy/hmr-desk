"""Local HTTP receiver and periodic engine tasks."""
import datetime
import contextlib
import http.server
import json
import logging
import logging.handlers
import os
import secrets
import subprocess
import threading
import time
from urllib.parse import urlsplit, parse_qs

import api

STOP_EVENT = threading.Event()

import db
import inbox
import messaging
import outbox


def get_meta(conn, key, default=None):
    row = conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn, key, value):
    conn.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))
    conn.commit()


def token(conn):
    value = get_meta(conn, 'webhook_token')
    if not value:
        value = secrets.token_urlsafe(24)
        set_meta(conn, 'webhook_token', value)
    return value


def api_token(conn):
    value = os.environ.get('HMR_SESSION_TOKEN') or get_meta(conn, 'api_token')
    if os.environ.get('HMR_SESSION_TOKEN'):
        set_meta(conn, 'api_token', value)
    if not value:
        value = secrets.token_urlsafe(32)
        set_meta(conn, 'api_token', value)
    os.makedirs(db.DATA_DIR, exist_ok=True)
    with open(os.path.join(db.DATA_DIR, 'api_token'), 'w', encoding='utf-8') as f:
        f.write(value)
    if os.name != 'nt': os.chmod(os.path.join(db.DATA_DIR, 'api_token'), 0o600)
    return value


class HookHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if not secrets.compare_digest(self.path, '/hook/' + self.server.token):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('invalid length')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('invalid payload')
            with contextlib.closing(db.connect()) as conn:
                inbox.handle_webhook(conn, payload)
            self.send_response(200)
            self.end_headers()
        except (ValueError, UnicodeError):
            self.send_error(400)
        except Exception as exc:
            logging.error('Webhook processing failed (%s)', type(exc).__name__)
            self.send_error(500)

    def do_GET(self):
        self.send_error(404)

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_GET


def hook_server(port, hook_token):
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), HookHandler)
    server.token = hook_token
    return server


class QuietStatic(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # pythonw has no stderr
        pass

    def api_request(self):
        parsed = urlsplit(self.path)
        with contextlib.closing(db.connect()) as conn:
            expected = get_meta(conn, 'api_token', '')
            supplied = self.headers.get('X-HMR-Token', '')
            if not expected or not secrets.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8')):
                status, result = 403, {'error': 'forbidden'}
            else:
                try:
                    body = None
                    if self.command == 'POST':
                        if self.headers.get_content_type() != 'application/json':
                            raise ValueError('Content-Type must be application/json')
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 65536:
                            raise ValueError('invalid length')
                        body = json.loads(self.rfile.read(length))
                        if not isinstance(body, dict):
                            raise ValueError('body must be an object')
                    if self.command == 'POST' and parsed.path == '/api/engine/stop':
                        STOP_EVENT.set()
                        status, result = 200, {'stopping': True}
                    else:
                        status, result = api.handle(conn, self.command, parsed.path, parse_qs(parsed.query), body)
                except (ValueError, UnicodeError) as exc:
                    status, result = 400, {'error': str(exc)}
        data = json.dumps(result, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        if parsed.path.startswith('/api/auth/proda/'):
            self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlsplit(self.path).path.startswith('/api/'):
            self.api_request()
        else:
            self.send_error(404)

    def do_HEAD(self):
        self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path.startswith('/api/'):
            self.api_request()
        else:
            self.send_error(404)


def main():
    STOP_EVENT.clear()
    if os.name == 'nt':  # child tools (tailscale, the renderers) must not flash a console window every minute
        popen_init = subprocess.Popen.__init__
        def quiet(self, *a, **k):
            k.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
            popen_init(self, *a, **k)
        subprocess.Popen.__init__ = quiet
    log_dir = db.DATA_DIR
    os.makedirs(log_dir, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(os.path.join(log_dir, 'engine.log'), maxBytes=1000000, backupCount=1, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s', force=True)
    conn = db.connect()
    if os.environ.get('HMR_WORKSPACE') and not os.environ.get('HMR_IMPORT_LEGACY'):
        # Empty, app-owned workspaces must not silently import a former source checkout.
        pass
    elif not conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0]:  # empty database: rebuild from the source files first
        import importer
        logging.warning('Database empty at start: re-importing from the plan and logs')
        importer.run(conn)
    try:
        import records
        migrated = records.migrate_all(conn, lambda row: api.jobs.patient_folder(row), api.jobs.outside_files)
        logging.info('Record migration: %s', migrated)
    except Exception as exc:
        logging.error('Record migration failed (%s); plain files are untouched', type(exc).__name__)
    api_token(conn)
    hook = None
    try:
        hook = hook_server(int(os.environ.get('HMR_WEBHOOK_PORT', '8766')), token(conn))
    except OSError:
        # SMS webhook ingress is an optional authenticated integration, not a
        # dependency of the pharmacist's fully manual offline clinical workflow.
        logging.warning('Optional SMS webhook listener unavailable')
    api.jobs.ensure_worker(recover=True)
    if hook: threading.Thread(target=hook.serve_forever, daemon=True).start()
    # Never expose the patient workspace over an unauthenticated static HTTP server.
    # The app's API gets its own port, bound without address reuse: on Windows an old
    # `python -m http.server 8765` can share port 8765 and swallow API requests (seen 12 Nov).
    class ApiServer(http.server.ThreadingHTTPServer):
        allow_reuse_address = False
    try:
        api_server = ApiServer(('127.0.0.1', int(os.environ.get('HMR_API_PORT', '8767'))), QuietStatic)
        threading.Thread(target=api_server.serve_forever, daemon=True).start()
    except OSError:
        logging.error('API port is in use; refusing to start without an authenticated listener')
        if hook: hook.shutdown(); hook.server_close()
        conn.close()
        raise
    logging.info('Local clinical engine started')
    last_poll = 0
    online = None
    try:
        while not STOP_EVENT.is_set():
            try:
                client = outbox.make_client()
                cfg = outbox.config()
                outbox.process(conn, client, cfg)
                if time.monotonic() - last_poll >= 600:
                    inbox.poll(conn, client)
                    last_poll = time.monotonic()
                if online is not True:
                    logging.info('Gateway available')
                online = True
                set_meta(conn, 'gateway_online', 'true')
            except (outbox.BridgeError, OSError, ValueError, KeyError):
                if online is not False:
                    logging.info('Gateway unavailable')
                online = False
                set_meta(conn, 'gateway_online', 'false')
            try:
                messaging.autopilot(conn)
            except Exception as exc:
                conn.rollback()
                logging.error('Messaging autopilot failed (%s)', type(exc).__name__)
            try:
                import lifecycle
                lifecycle.auto_visit(conn)
            except Exception as exc:
                conn.rollback()
                logging.error('Automatic visit recording failed (%s)', type(exc).__name__)
            try:
                plan = get_meta(conn, 'plan_file')
                stamp = str(os.stat(plan).st_mtime_ns) if plan and os.path.isfile(plan) else None
                previous = get_meta(conn, 'plan_mtime_ns')
                if stamp and previous and stamp != previous:
                    import importer
                    importer.run(conn)
                    set_meta(conn, 'plan_mtime_ns', stamp)
                elif stamp and not previous:
                    set_meta(conn, 'plan_mtime_ns', stamp)
                highest = conn.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE patient_id IS NOT NULL").fetchone()[0]
                if highest > int(get_meta(conn, 'exported_event_id', '0')):
                    import export_plan
                    export_plan.export(conn)
                    plan = get_meta(conn, 'plan_file')
                    if plan and os.path.isfile(plan):
                        set_meta(conn, 'plan_mtime_ns', os.stat(plan).st_mtime_ns)
                    set_meta(conn, 'exported_event_id', highest)
                today = datetime.datetime.now()
                if today.hour >= 2 and get_meta(conn, 'backup_date') != str(today.date()):
                    db.backup(conn)
                    set_meta(conn, 'backup_date', today.date())
            except Exception as exc:
                logging.error('Engine maintenance failed (%s)', type(exc).__name__)
            STOP_EVENT.wait(60)
    except KeyboardInterrupt:
        pass
    finally:
        api_server.shutdown()
        api_server.server_close()
        if hook:
            hook.shutdown()
            hook.server_close()
        conn.close()


if __name__ == '__main__':
    main()
