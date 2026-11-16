"""Read-only history planning and explicit, idempotent database application."""
from collections import Counter, defaultdict
import datetime as dt
from pathlib import Path
import re
from openpyxl import load_workbook
import db


def iso(value):
    if isinstance(value, (dt.datetime, dt.date)): return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try: return dt.datetime.strptime(str(value).strip(), fmt).date().isoformat()
        except ValueError: pass
    return None


def plan(conn):
    base = Path(db.BASE)
    workbooks = list((base / 'old booking excel').glob('*.xlsx'))
    dates = defaultdict(set)
    if workbooks:
        book = load_workbook(max(workbooks, key=lambda p: p.stat().st_mtime), read_only=True, data_only=True)
        try:
            for sheet in book:
                rows = sheet.iter_rows(values_only=True)
                headers = [str(x or '').strip().lower() for x in next(rows, ())]
                if 'name' not in headers: continue
                for row in rows:
                    values = dict(zip(headers, row)); key = db.patient_key(str(values.get('name') or ''))
                    record = tuple(iso(values.get(k)) for k in ('interview date', 'report sent date', 'claimed'))
                    if key and any(record): dates[key].add(record)
        finally: book.close()
    records = []
    for root, stage in [('Visited','visited'), ('To CLAIM','sent'), ('Completed & Claimed','claimed')]:
        folder = base / root
        if not folder.is_dir(): continue
        for path in folder.rglob('*'):
            if not path.is_dir(): continue
            match = re.fullmatch(r'(.+?)_\s*([A-Za-z]{1,5})', path.name)
            if not match: continue
            name = match[1].strip(); key = db.patient_key(name)
            if not key: continue
            actual_stage = stage
            if root == 'Visited':
                parts = [p.lower() for p in path.relative_to(folder).parts[:-1]]
                if 'claimed' in parts: actual_stage = 'claimed'
                elif 'to claim' in parts: actual_stage = 'sent'
            visit, sent, claimed = next(iter(dates[key])) if len(dates[key]) == 1 else (None, None, None)
            source = 'workbook' if any((visit, sent, claimed)) else 'unknown'
            if not sent:
                docs = [p for p in path.rglob('*.docx') if 'report' in p.name.lower() or p.name.lower().startswith('hmr')]
                if docs:
                    sent = dt.date.fromtimestamp(max(p.stat().st_mtime for p in docs)).isoformat()
                    if source == 'unknown': source = 'file date'
            records.append(dict(name=name, key=key, folder=str(path.relative_to(base)), stage=actual_stage,
                                visit_date=visit, report_sent=sent, claimed=claimed, date_source=source))
    counts = Counter(r['key'] for r in records)
    for r in records: r['ambiguous'] = counts[r['key']] > 1
    return records


def summary(records):
    good = [r for r in records if not r['ambiguous']]
    return {'stages': dict(Counter(r['stage'] for r in good)),
            'date_sources': dict(Counter(r['date_source'] for r in good)),
            'unknown_visit_dates': sum(not r['visit_date'] for r in good),
            'ambiguous_names': sorted({r['name'] for r in records if r['ambiguous']})}


def apply(conn, records):
    added = 0
    with conn:
        for r in records:
            if r['ambiguous']: continue
            conn.execute('INSERT OR IGNORE INTO patients(key,name,state,folder,plan_order,updated_at) VALUES (?,?,?,?,NULL,?)',
                         (r['key'],r['name'],r['stage'],r['folder'],db.now()))
            pid = conn.execute('SELECT id FROM patients WHERE key=?', (r['key'],)).fetchone()[0]
            if conn.execute("SELECT 1 FROM visits WHERE patient_id=? AND folder=? AND source='import'", (pid,r['folder'])).fetchone(): continue
            conn.execute("INSERT INTO visits(patient_id,kind,visit_date,report_sent,claimed,folder,source,note) VALUES (?,'hmr',?,?,?,?, 'import',?)",
                         (pid,r['visit_date'],r['report_sent'],r['claimed'],r['folder'],'date source: '+r['date_source']))
            added += 1
    return added
