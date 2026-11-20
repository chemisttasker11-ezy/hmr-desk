"""Pre-sign-off part of test_independent_repairs.py (import, hold, resume, auto-visit, not-visited and built-report checks).

The rest calls signed_off and report_sent, which need an approved report pair; it stays excluded from the runner
(see test_legacy_scripts.py) and is not counted as passing."""
"""Offline regressions for app-owned lifecycle and follow-up obligations."""
import datetime as dt
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
import api, db, export_plan, importer, inbox, lifecycle, messaging, records, steps, timeline

with tempfile.TemporaryDirectory() as tmp:
    with closing(db.connect(str(Path(tmp) / 'test.db'))) as c:
        root = Path(tmp); db.BASE = tmp
        today = dt.date.today(); past = str(today - dt.timedelta(days=2))
        plan = root / 'Appointment_Plan_1.json'
        plan.write_text(json.dumps({'patients':[{'Name':'Test Patient','Status':'Suggested'}]}), encoding='utf-8')
        folder = root / 'Scheduled' / 'Test Patient_Doctor'; folder.mkdir(parents=True)
        importer.run(c, root)
        pid = c.execute("SELECT id FROM patients WHERE name='Test Patient'").fetchone()[0]
        def patient(): return c.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        def act(action, **kw): return api.action(c, patient(), {'action':action, **kw})
        act('book_phone', date=past, time='09:00', end='10:00')
        act('pathology_outcome', outcome='saved_by_hand')
        # Automatic cancellation stays unresolved; an explicit user decision cancels without moving files.
        c.execute("INSERT INTO patients(key,name,phone,state,visit_date,visit_time,visit_end,folder) VALUES ('cancel patient','Cancel Patient','0412345678','confirmed',?,'09:00','10:00',?)", (past, str(folder.relative_to(root))))
        cancel_id = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        with patch('inbox.append_decline'):
            message = inbox.ingest(c, 'cancel-in', '0412345678', 'Please cancel', dt.datetime.now(dt.timezone.utc).isoformat(), 'test')
            assert message['kind'] == 'OTHER' and messaging.waiting_replies(c, cancel_id)
            inbox.resolve(c, message, {'as':'decline'})
        cancelled = c.execute('SELECT * FROM patients WHERE id=?', (cancel_id,)).fetchone()
        assert cancelled['state'] == 'declined' and cancelled['visit_date'] is None and folder.is_dir()
        c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('q',?,'in','Can you call?','OTHER','received',?)", (pid, db.now()))
        c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,sent_at,created_at) VALUES ('reminder',?,'out','Reminder','reminder','Sent',?,?)", (pid, db.now(), db.now()))
        assert [x['id'] for x in messaging.waiting_replies(c, pid)] == ['q']
        inbox.resolve(c, c.execute("SELECT * FROM messages WHERE id='q'").fetchone(), {'as':'done'})
        assert not messaging.waiting_replies(c, pid)
        act('hold', note='waiting'); export_plan.export(c, plan, render=False)
        stale = json.loads(plan.read_text()); stale['patients'][0].update(Status='Confirmed', Date=past, Time='09:00')
        plan.write_text(json.dumps(stale), encoding='utf-8'); importer.run(c, root)
        assert patient()['state'] == 'hold' and patient()['has_pathology'] == 1
        with patch('lifecycle.db.backup'): assert not lifecycle.auto_visit(c, today)
        act('resume'); importer.run(c, root)
        assert patient()['state'] == 'confirmed' and patient()['visit_date'] == past
        with patch('lifecycle.db.backup'): lifecycle.auto_visit(c, today)
        assert patient()['state'] == 'visited'
        act('not_visited'); importer.run(c, root)
        with patch('lifecycle.db.backup'): assert not lifecycle.auto_visit(c, today)
        assert patient()['state'] == 'pooled' and patient()['visit_date'] is None
        assert timeline.build(c, patient())['milestones']['visit'] is None
        act('book_phone', date=past, time='09:00', end='10:00')
        act('visited', date=past)
        (folder / 'report.docx').write_bytes(b'synthetic')
        records.put(c, pid, 'report_spec.json', json.dumps({'out':str(folder / 'report.docx')}).encode('utf-8')); c.commit()  # the spec lives in the records store
        assert steps.built(c, patient())

print('independent repairs pre-sign-off checks passed')
