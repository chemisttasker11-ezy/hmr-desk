"""Export the current plan in the legacy JSON format."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import db
from importer import FIELDS


def export(conn, out_path=None, render=True):
    meta = dict(conn.execute('SELECT key,value FROM meta WHERE key IN (?,?)', ('plan_meta', 'plan_file')))
    data = json.loads(meta['plan_meta'])
    data['patients'] = []
    required = {'Name', 'Suburb', 'Address', 'Phone', 'GP', 'Referral date', 'Status'}
    for row in conn.execute('SELECT * FROM patients WHERE plan_order IS NOT NULL ORDER BY plan_order'):
        data['patients'].append({key: row[col] for key, col in FIELDS.items() if key in required or row[col] is not None})
    path = Path(out_path or meta['plan_file']).resolve()
    if path.exists():  # an empty or partial database must never wipe the real plan
        on_file = len(json.loads(path.read_text(encoding='utf-8-sig')).get('patients', []))
        if len(data['patients']) < 0.8 * on_file:
            raise RuntimeError(f'Refusing to export: database has {len(data["patients"])} plan patients, file has {on_file}')
    content = json.dumps(data, ensure_ascii=False, indent=1)
    changed = not path.exists() or path.read_text(encoding='utf-8-sig') != content
    if changed:
        path.write_text(content, encoding='utf-8')
        if render:
            base = Path(meta['plan_file']).parent
            for script in (base / 'render_appointment_calendar.py', base / 'scripts' / 'dashboard' / 'build_day_maps.py'):
                subprocess.run([sys.executable, str(script), str(path)], cwd=base, check=True)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--out'); parser.add_argument('--no-render', action='store_true'); args = parser.parse_args()
    conn = db.connect(); print(export(conn, args.out, not args.no_render)); conn.close()
