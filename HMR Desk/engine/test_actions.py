import datetime as dt
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import api, db, importer, jobs, steps

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp); db.BASE = tmp
    conn = db.connect(str(base / 'test.db'))
    def patient(name, state='new', path=None):
        conn.execute('INSERT INTO patients(key,name,gp,state,folder,visit_date,visit_time,visit_end,visit_group) VALUES (?,?,?,?,?,?,?,?,?)', (db.patient_key(name), name, 'Doctor Example', state, path, '2020-01-01', '09:00', '10:00', 'A'))
        conn.commit()
        return conn.execute('SELECT * FROM patients WHERE id=last_insert_rowid()').fetchone()['id']
    def row(pid): return conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    def act(pid, name, **kwargs): return api.action(conn, row(pid), {'action':name, **kwargs})
    def item(path, directory=False):
        p = base / path; p.parent.mkdir(parents=True, exist_ok=True)
        if directory:
            p.mkdir(); (p / 'referral.pdf').write_text('referral')
        else: p.write_text('referral')
        return p
    def reject(pid, name, **kwargs):
        try: act(pid, name, **kwargs)
        except ValueError: return
        raise AssertionError('expected ValueError')

    source = item('on Excel/Alex Example_ Doctor.pdf')
    p = patient('Alex Example', path=str(source.relative_to(base)))
    assert act(p, 'decline_phone', reason='No') == {'ok':True, 'moved':True}
    assert not source.exists() and (base / row(p)['folder']).read_text() == 'referral'
    assert row(p)['state'] == 'declined' and row(p)['visit_date'] is None and row(p)['offered_date'] == '2020-01-01'
    assert act(p, 'move_declined') == {'ok':True, 'moved':False}
    register = (base / 'Declined-Exp/Declines register.csv').read_bytes()
    source = item('Scheduled/Bea Example_ Doctor', True)
    p2 = patient('Bea Example', 'declined', str(source.relative_to(base)))
    assert act(p2, 'move_declined')['moved'] and (base / row(p2)['folder'] / 'referral.pdf').exists()
    assert row(p2)['state'] == 'declined' and (base / 'Declined-Exp/Declines register.csv').read_bytes() == register
    source = item('Scheduled/Cal Example_ Doctor', True)
    p3 = patient('Cal Example', path=str(source.relative_to(base)))
    assert act(p3, 'expired', note='old referral')['moved']
    assert row(p3)['state'] == 'expired' and row(p3)['note'] == 'old referral' and row(p3)['visit_time'] is None
    source = item('on Excel/Dee Example_ Doctor.pdf'); target = item('Declined-Exp/Declined/Dee Example_ Doctor.pdf')
    p4 = patient('Dee Example', path=str(source.relative_to(base)))
    reject(p4, 'decline_phone')
    assert source.read_text() == target.read_text() == 'referral' and row(p4)['state'] == 'new'
    assert (base / 'Declined-Exp/Declines register.csv').read_bytes() == register
    p5 = patient('Eve Example', path='on Excel/missing.pdf')
    reject(p5, 'expired')
    assert row(p5)['folder'] == 'on Excel/missing.pdf' and row(p5)['state'] == 'new'
    reject(p5, 'move_declined')
    source = item('Scheduled/Failure Example_ Doctor', True)
    failed = patient('Failure Example', path=str(source.relative_to(base)))
    with patch('api.os.rename', side_effect=OSError('move failed')):
        try: act(failed, 'expired')
        except ValueError as exc: assert 'move failed' in str(exc)
        else: raise AssertionError('expected move failure')
    assert source.is_dir() and row(failed)['folder'] == str(source.relative_to(base)) and row(failed)['state'] == 'new'
    source = item('Scheduled/Stale Example_ Doctor', True)
    stale = patient('Stale Example', 'visited', str(Path('Visited/Nov') / source.name))
    assert jobs.patient_folder(row(stale)) == source.resolve()
    assert steps.exists(conn, row(stale), 'referral.pdf')
    assert row(stale)['folder'] == str(Path('Visited/Nov') / source.name)
    today = dt.date.today().isoformat(); p6 = patient('Fay Example')
    for visit, sent in [('bad', today), (today, 'bad'), (today, '2000-01-01'), (today, (dt.date.today()+dt.timedelta(days=1)).isoformat())]:
        reject(p6, 'claim_now', visit_date=visit, report_sent=sent)
    assert act(p6, 'claim_now', visit_date='2020-01-01', report_sent='2020-01-02') == {'ok':True, 'moved':False}
    assert row(p6)['state'] == 'sent' and row(p6)['status_text'] == 'Visited outside the app'
    visit = conn.execute('SELECT * FROM visits WHERE patient_id=?', (p6,)).fetchone()
    assert (visit['kind'], visit['visit_date'], visit['report_sent'], visit['source']) == ('hmr', '2020-01-01', '2020-01-02', 'app')
    claim = api.claim_list(conn)[0]
    assert (claim['interview'], claim['reportSent']) == ('2020-01-01', '2020-01-02')
    reject(p6, 'claim_now', visit_date=today, report_sent=today)
    conn.execute("UPDATE patients SET state='claimed' WHERE id=?", (p6,)); conn.commit()
    reject(p6, 'claim_now', visit_date=today, report_sent=today)
    source = item('on Excel/Gus Example_ Doctor.pdf')
    p7 = patient('Gus Example', path=str(source.relative_to(base)))
    conn.execute("CREATE TRIGGER fail_folder BEFORE UPDATE OF folder ON patients BEGIN SELECT RAISE(FAIL, 'test failure'); END")
    try:
        act(p7, 'expired')
        raise AssertionError('expected database failure')
    except __import__('sqlite3').IntegrityError:
        pass
    assert source.exists() and row(p7)['state'] == 'new' and row(p7)['folder'] == str(source.relative_to(base))
    conn.execute('DROP TRIGGER fail_folder')
    (base / 'Appointment_Plan_1.json').write_text(json.dumps({'patients':[]}))
    importer.run(conn, tmp)
    assert row(p2)['folder'] == str(Path('Declined-Exp/Declined/Bea Example_ Doctor')) and row(p2)['state'] == 'declined'
    # Lifecycle actions and undo eligibility use only the temporary database.
    held = patient('Hold Example', 'sheet_ready')
    act(held, 'hold', note='waiting')
    assert row(held)['hold_from'] == 'sheet_ready'
    assert __import__('lifecycle').stage(conn, row(held))['step'] == 'from sheet_ready'
    act(held, 'resume')
    assert row(held)['state'] == 'sheet_ready' and row(held)['hold_from'] is None
    empty = patient('Empty Example', 'hold'); act(empty, 'resume'); assert row(empty)['state'] == 'pooled'
    reject(empty, 'resume'); reject(empty, 'archive')
    archived = patient('Archive Example', 'claimed')
    act(archived, 'archive'); assert row(archived)['archived_at']
    assert conn.execute("SELECT count(*) FROM events WHERE patient_id=? AND type='archive'", (archived,)).fetchone()[0] == 1
    act(archived, 'unarchive'); assert row(archived)['archived_at'] is None
    for state, action, field in [('confirmed','visited','visit_date'), ('signed_off','report_sent','report_sent'), ('sent','claimed','claimed')]:
        pid = patient('Undo '+action, state)
        act(pid, action, date='2020-01-01')
        detail = api.handle(conn, 'GET', f'/api/patients/{pid}', {}, None)[1]
        assert detail['can_undo'] and detail['undo_label'].startswith('Undo: ')
        act(pid, 'undo_stage')
        assert row(pid)['state'] == state
        visit = conn.execute("SELECT * FROM visits WHERE patient_id=? AND source='app'", (pid,)).fetchone()
        assert visit and visit[field] is None
        assert conn.execute("SELECT 1 FROM events WHERE patient_id=? AND type='undo_stage'", (pid,)).fetchone()
    for state, action in [('visited','report_drafted'), ('report_drafted','signed_off')]:
        pid = patient('Undo '+action, state); act(pid, action); act(pid, 'undo_stage'); assert row(pid)['state'] == state
    pid = patient('Invalid Undo', 'visited'); reject(pid, 'undo_stage')
    db.log(conn, pid, 'state', {'from':'confirmed','to':'visited'}, 'engine'); reject(pid, 'undo_stage')
    db.log(conn, pid, 'state', {'from':'confirmed','to':'visited'}, 'app')
    conn.execute("UPDATE events SET ts=? WHERE id=(SELECT max(id) FROM events)", ((dt.datetime.now()-dt.timedelta(hours=24, seconds=1)).isoformat(),))
    reject(pid, 'undo_stage')
    db.log(conn, pid, 'state', {'from':'confirmed','to':'sent'}, 'app'); reject(pid, 'undo_stage')
    assert api.handle(conn, 'POST', f'/api/patients/{pid}/action', {}, {'action':'undo_stage'}) == (400, {'error':'Nothing to undo'})
    conn.close()
print('quick action checks passed')
