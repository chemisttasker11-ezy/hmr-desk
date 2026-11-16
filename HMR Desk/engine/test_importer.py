import json
import os
from pathlib import Path
import tempfile

import db
import importer
import export_plan


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); base = root / 'fixture'; base.mkdir()
    os.environ['HMR_DB'] = str(root / 'fixture.db')
    conn = db.connect()
    statuses = ['Confirmed visit', 'Offer sent', 'Suggested visit', 'Reply received', 'Hold', 'Declined', 'Likely declined', 'Completed', 'Referral expired', 'excluded', 'Other']
    names = [f'Test{chr(65+i)} Person' for i in range(len(statuses))]
    items = [{'Name': n, 'Suburb': '4216 Place' if i == 0 else 'Place', 'Address': '123 Road 2486', 'Phone': '0411111111', 'GP': 'Doctor', 'Referral date': '2026-01-01', 'Status': s} for i, (n, s) in enumerate(zip(names, statuses))]
    plan = base / 'Appointment_Plan_1.json'; write(plan, {'review_date': '2026-01-01', 'patients': items, 'notes': 'note'})
    folder = base / 'Scheduled' / (names[0] + '_ Doctor'); (folder / 'Pathology').mkdir(parents=True)
    (folder / 'Pathology' / 'result.pdf').write_bytes(b'pdf'); (folder / 'HMR Interview test.docx').write_bytes(b'doc')
    excel = base / 'on Excel'; excel.mkdir(); (excel / (names[1] + '_ Doctor.xlsx')).write_bytes(b'')
    visited = base / 'Visited'; visited.mkdir(); (visited / ('XX' + names[7] + '_ Doctor')).mkdir()
    declines = base / 'Declined-Exp'; declines.mkdir(); (declines / ('ZZ' + names[5] + '_ Doctor')).mkdir()
    (declines / 'Declines register.csv').write_text('Patient,GP,Declined on,How,Their words,Notes\n' + names[5] + ',Doctor,,,,\nOld Person,Doctor,,,,\n', encoding='utf-8-sig')
    sorting = base / 'TO SORT'
    write(sorting / 'intake_report_1.json', [{'kind': 'referral', 'file': 'a.pdf', 'fields': {'name': names[0], 'dob': '1950', 'sex': 'F', 'phone': 'wrong', 'clinic': 'Clinic'}}, {'kind': 'referral', 'file': 'b.pdf', 'fields': {'name': 'Extra Person'}}])
    write(sorting / 'intake_corrections.json', {'a.pdf': {'dob': '1951'}})
    write(sorting / 'sms_offers_1.json', [{'name': names[1], 'contact_id': '42', 'draft_id': 'out1', 'number': '0499999999', 'sms': 'offer', 'status': 'Delivered successfully', 'sent_at': '2026-01-01T10:00:00'}])
    write(sorting / 'sms_send_queue_1.json', [{'name': names[2], 'contact_id': '43', 'sms': 'invite', 'status': 'Sent', 'sent_at': '2026-01-01T09:00:00'}])
    write(sorting / 'sms_replies_sent_1.json', [{'name': names[1], 'contact_id': '42', 'draft_id': 'out2', 'sms': 'reply', 'kind': 'confirmation', 'status': 'Pending'}])
    write(sorting / 'sms_replies_log.json', [{'name': names[1], 'contact_id': '42', 'inbox_id': 'in1', 'text': 'yes', 'kind': 'YES', 'received': '2026-01-01T11:00:00'}, {'name': 'Unknown Person', 'inbox_id': 'in2', 'text': '?', 'received': '2026-01-01T11:00:00'}])
    report = importer.run(conn, base)
    rows = conn.execute('SELECT * FROM patients ORDER BY plan_order').fetchall()
    byname = {r['name']: r for r in rows}
    assert [byname[n]['state'] for n in names] == ['sheet_ready', 'offered', 'pooled', 'offered', 'hold', 'declined', 'declined', 'visited', 'expired', 'expired', 'new']
    assert byname[names[0]]['postcode'] == '4216' and byname[names[1]]['postcode'] == '2486'
    assert byname[names[0]]['dob'] == '1951' and byname[names[0]]['phone'] == '0411111111'
    assert byname[names[0]]['has_sheet'] and byname[names[0]]['has_pathology']
    assert byname['Old Person']['state'] == 'declined' and byname['Extra Person']['state'] == 'new'
    assert conn.execute("SELECT offer_ref FROM messages WHERE id='in1'").fetchone()[0] == 'out1'
    assert any('phone differs' in x for x in report['checks']) and any('unmatched' in x for x in report['checks'])
    counts = tuple(conn.execute('SELECT (SELECT count(*) FROM patients),(SELECT count(*) FROM messages),(SELECT count(*) FROM events)').fetchone())
    importer.run(conn, base)
    assert counts == tuple(conn.execute('SELECT (SELECT count(*) FROM patients),(SELECT count(*) FROM messages),(SELECT count(*) FROM events)').fetchone())
    items[0]['Phone'] = '0400000000'; write(plan, {'review_date': '2026-01-01', 'patients': items, 'notes': 'note'})
    importer.run(conn, base)
    assert any('phone' in json.loads(r[0]) for r in conn.execute("SELECT detail FROM events WHERE type='import_change'"))
    import lifecycle, datetime
    original_base = db.BASE
    db.BASE = str(base)
    conn.execute('UPDATE patients SET visit_date=? WHERE id=?', ('2020-01-02', byname[names[0]]['id']))
    conn.commit()
    auto = lifecycle.auto_visit(conn, datetime.date(2020, 1, 3))
    assert any(x['id'] == byname[names[0]]['id'] for x in auto)
    importer.run(conn, base)
    restored = conn.execute('SELECT state,visit_date,status_text FROM patients WHERE id=?', (byname[names[0]]['id'],)).fetchone()
    assert tuple(restored) == ('visited', '2020-01-02', 'Visited 02/01/2020 (auto)')
    db.BASE = original_base
    db.set_state(conn, byname[names[10]]['id'], 'visited', force=True); conn.commit()  # plan still says 'Other' (-> new)
    importer.run(conn, base)
    assert conn.execute('SELECT state FROM patients WHERE id=?', (byname[names[10]]['id'],)).fetchone()[0] == 'visited'
    conn.close()
    os.environ['HMR_DB'] = str(root / 'real.db'); conn = db.connect()
    importer.run(conn, db.BASE)
    out = export_plan.export(conn, root / 'export.json', render=False)
    original = importer.newest(Path(db.BASE).glob('Appointment_Plan_[0-9]*.json'))
    assert importer.read(out) == importer.read(original)
    empty = db.connect(str(root / 'empty.db')); empty.execute("INSERT INTO meta VALUES ('plan_meta','{}'),('plan_file',?)", (str(out),)); empty.commit()
    try:
        export_plan.export(empty, render=False); raise SystemExit('empty database overwrote the plan')
    except RuntimeError:
        pass
    empty.close()
    conn.close()
print('importer tests OK')


# A reply already stored by the phone check (other id, other time format) is not imported again from the old log
def _dup_reply_test():
    import sqlite3, tempfile, os, datetime as _dt
    import db as _db, inbox as _inbox
    conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE messages (id TEXT PRIMARY KEY, patient_id INTEGER, direction TEXT, body TEXT, created_at TEXT)')
    conn.execute("INSERT INTO messages VALUES ('text:1', 7, 'in', 'Yes,12.45pm is ok\nsee you', '2026-11-14T00:05:15+00:00')")
    when = _dt.datetime.fromisoformat('2026-11-14T10:05:15.000+10:00')
    assert _inbox.already_have(conn, 7, 'Yes,12.45pm is ok see you', when)
    assert not _inbox.already_have(conn, 7, 'No thanks', when)
    assert not _inbox.already_have(conn, 8, 'Yes,12.45pm is ok see you', when)
    print('duplicate reply checks passed')
_dup_reply_test()
