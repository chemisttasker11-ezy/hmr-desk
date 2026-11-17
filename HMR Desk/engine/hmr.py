"""HMR Desk command line."""
import argparse
import secrets
import socket
from urllib.parse import urlparse

import db
import inbox
import outbox
import service

EVENTS = ('sms:received', 'sms:sent', 'sms:delivered', 'sms:failed')


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('status', 'check', 'send-test', 'webhook-url'):
        sub.add_parser(name)
    window = sub.add_parser('window')
    window.add_argument('value', choices=('on', 'off'))
    mode = sub.add_parser('mode')
    mode.add_argument('value', choices=('test', 'live'))
    register = sub.add_parser('register-webhook')
    register.add_argument('--url', required=True)
    register.add_argument('--yes', action='store_true')
    unregister = sub.add_parser('unregister-webhook')
    unregister.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    with db.connect() as conn:
        if args.command == 'status':
            for label, table, where in (('Patients', 'patients', ''), ('Outbox', 'messages', " WHERE direction='out'")):
                print(label + ': ' + ', '.join(f'{r[0]}={r[1]}' for r in conn.execute(f'SELECT state,COUNT(*) FROM {table}{where} GROUP BY state')))
            print('Last inbox time:', service.get_meta(conn, 'inbox_since', 'never'))
            try:
                with socket.create_connection(('127.0.0.1', 8766), timeout=1):
                    print('Service: port answers')
            except OSError:
                print('Service: not reachable')
        elif args.command == 'webhook-url':
            print('/hook/' + service.token(conn))
        elif args.command == 'window':
            service.set_meta(conn, 'sending_window', args.value)
            print('Sending window 08:00-20:00 (patient time):', args.value)
        elif args.command == 'mode':
            service.set_meta(conn, 'outbox_mode', args.value)
            if args.value == 'live':
                print('WARNING: live mode permits messages to patients.')
            print('Mode:', args.value)
        elif args.command in ('register-webhook', 'unregister-webhook'):
            if args.command == 'register-webhook':
                parsed = urlparse(args.url)
                if parsed.scheme != 'https' or not parsed.hostname:
                    parser.error('--url must be an https URL')
                for event in EVENTS:
                    print(f'POST /webhooks hmr-desk-{event[4:]} {event} {args.url}')
                if args.yes:
                    client = outbox.make_client()
                    for event in EVENTS:
                        client._request('POST', '/webhooks', {'id': 'hmr-desk-' + event[4:], 'deviceId': None, 'url': args.url, 'event': event, 'source': 'Local'})
            else:
                for event in EVENTS:
                    print('DELETE /webhooks/hmr-desk-' + event[4:])
                if args.yes:
                    client = outbox.make_client()
                    for event in EVENTS:
                        client._request('DELETE', '/webhooks/hmr-desk-' + event[4:])
        else:
            try:
                client = outbox.make_client()
                if args.command == 'check':
                    import datetime
                    inbox.poll(conn, client)
                    seen = int(service.get_meta(conn, 'reported_rowid', '0'))
                    rows = conn.execute("SELECT m.rowid, m.*, p.name, p.status_text FROM messages m LEFT JOIN patients p ON p.id=m.patient_id "
                                        "WHERE m.direction='in' AND m.source IN ('poll','webhook') AND m.rowid>? ORDER BY m.rowid", (seen,)).fetchall()
                    for row in rows:
                        when = datetime.datetime.fromisoformat(row['created_at']).astimezone(datetime.timezone(datetime.timedelta(hours=10)))
                        print(f"{when:%Y-%m-%d %H:%M} | {row['name'] or 'test'} | {row['kind']} | {' '.join(row['body'].split())} | now: {row['status_text'] or '-'}")
                    if rows:
                        service.set_meta(conn, 'reported_rowid', rows[-1]['rowid'])
                    else:
                        print('No new replies')
                else:
                    cfg = outbox.config()
                    nonce = secrets.token_hex(3)
                    id_ = outbox.queue(conn, cfg['test_number'], f'HMR Desk test {nonce}. Please reply TEST {nonce}.', 'test')
                    outbox.process(conn, client, cfg)
                    print(id_, conn.execute('SELECT state FROM messages WHERE id=?', (id_,)).fetchone()[0])
            except (outbox.BridgeError, OSError, ValueError, KeyError) as e:
                print('GATEWAY NOT REACHABLE:', str(e))


if __name__ == '__main__':
    main()
