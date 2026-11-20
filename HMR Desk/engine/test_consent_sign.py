import base64, os, tempfile
from pathlib import Path
import records
import fitz, api, db, interview, steps, consent_sign
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Event

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); db.BASE = tmp; db.DATA_DIR = tmp; os.environ['HMR_DB'] = str(root / 'test.db')
    (root / 'TEMPLATES').mkdir()
    doc = fitz.open(); doc.new_page(); page = doc.new_page()
    rects = {'Patient signature': fitz.Rect(40, 80, 240, 120), 'Authorised Person Signature': fitz.Rect(40, 150, 240, 190)}
    for name, rect in rects.items():
        w = fitz.Widget(); w.field_name = name; w.field_type = fitz.PDF_WIDGET_TYPE_TEXT; w.rect = rect; page.add_widget(w)
    doc.save(root / 'TEMPLATES' / 'PPA Consent.pdf'); doc.close()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 10), False); pix.clear_with(0)
    png = base64.b64encode(pix.tobytes('png')).decode()
    conn = db.connect()
    try:
        def call(method, path, body=None): return api.handle(conn, method, path, {}, body)
        for index, by in enumerate(('patient', 'authorised'), 1):
            folder = root / str(index); folder.mkdir()
            conn.execute('INSERT INTO patients(key,name,state,folder,visit_date) VALUES (?,?,?,?,?)', (str(index), 'Test Person ' + str(index), 'confirmed', str(index), '2026-11-12')); conn.commit()
            patient = conn.execute('SELECT * FROM patients WHERE key=?', (str(index),)).fetchone()
            record = interview.load(conn, patient)
            if by == 'authorised': record['consent'].update(by=by, relationship=2, authorised_name='Representative')
            interview.save(conn, patient, record); conn.commit()
            url = '/api/patients/' + str(patient['id']) + '/consent/'
            unsigned = folder / ('PPA Consent - Test Person ' + str(index) + '.pdf')
            if index == 2: interview.fill_consent(conn, patient, record, unsigned)
            status, result = call('GET', url + 'preview'); assert status == 200 and result['by'] == by and result['signed_file'] == ''
            assert base64.b64decode(result['png']).startswith(b'\x89PNG\r\n\x1a\n') and unsigned.exists()
            original = unsigned.read_bytes()
            for bad in ('bad', base64.b64encode(b'\x89PNG\r\n\x1a\ninvalid').decode(), base64.b64encode(b'x' * (2 * 1024 * 1024 + 1)).decode()):
                assert call('POST', url + 'sign', {'png': bad, 'revision': record['revision']})[0] == 400
                assert not interview.signed_file(folder) and unsigned.read_bytes() == original
            if by == 'authorised':
                record['consent'].update(relationship=0, authorised_name=''); record['consent_signed_draft'] = True
                interview.save(conn, patient, record); conn.commit()
                assert call('POST', url + 'sign', {'png': png, 'revision': record['revision']})[0] == 400
                assert not interview.signed_file(folder)
                record['consent'].update(relationship=2, authorised_name='Representative'); record['consent_signed_draft'] = False
                interview.save(conn, patient, record); conn.commit()
            assert call('POST', url + 'sign', {'png': png, 'revision': 'missing'})[0] == 409
            assert not interview.signed_file(folder)
            status, result = call('POST', url + 'sign', {'png': png, 'revision': record['revision']}); assert status == 200, result
            signed = folder / result['file']; assert signed.is_file() and unsigned.read_bytes() == original
            with fitz.open(signed) as pdf:
                images = pdf[1].get_images(); assert len(images) == 1
                rect = pdf[1].get_image_rects(images[0])[0]
                expected = rects['Patient signature' if by == 'patient' else 'Authorised Person Signature']
                assert expected.contains(rect) and abs((rect.x0 + rect.x1) / 2 - (expected.x0 + expected.x1) / 2) < 1
                assert not pdf[0].get_images()
            saved = interview.load(conn, patient); assert saved['consent']['signed'] and saved['consent']['date'] == '2026-11-12'
            assert call('GET', url + 'preview')[1]['signed_file'] == signed.name
            before = signed.read_bytes(); assert call('POST', url + 'sign', {'png': png, 'revision': record['revision']})[0] == 400 and signed.read_bytes() == before
        # A preview holding the record lock cannot create an old form after a competing save.
        folder = root / 'race'; folder.mkdir()
        conn.execute("INSERT INTO patients(key,name,state,folder,visit_date) VALUES ('race','Race Person','confirmed','race','2026-11-12')"); conn.commit()
        race = conn.execute("SELECT * FROM patients WHERE key='race'").fetchone()
        initial = interview.load(conn, race); interview.save(conn, race, initial); conn.commit()
        entered, release, saving = Event(), Event(), Event()
        real_form = consent_sign.form
        def paused_form(c, p, r):
            entered.set(); assert release.wait(5); return real_form(c, p, r)
        def get_preview():
            c = db.connect()
            try: return consent_sign.preview(c, race)
            finally: c.close()
        def save_changed():
            c = db.connect()
            try:
                data = interview.load(c, race)
                data['consent'].update(by='authorised', relationship=2, authorised_name='New representative')
                saving.set(); interview.save(c, race, data); c.commit()
            finally: c.close()
        with patch.object(consent_sign, 'form', side_effect=paused_form):
            with ThreadPoolExecutor(max_workers=2) as pool:
                preview_future = pool.submit(get_preview); assert entered.wait(5)
                save_future = pool.submit(save_changed); assert saving.wait(5)
                assert not save_future.done()
                release.set(); old_preview = preview_future.result(timeout=5); save_future.result(timeout=5)
        current = interview.load(conn, race)
        assert old_preview['revision'] != current['revision']
        assert consent_sign.preview(conn, race)['revision'] == current['revision']
        # If audit/storage fails after JSON replacement, leave the old form and no new signature.
        before = records.get(conn, race['id'], 'interview.json')
        with patch.object(db, 'log', side_effect=RuntimeError('synthetic audit failure')):
            try: consent_sign.sign(conn, race, png, current['revision']); raise AssertionError('expected audit failure')
            except RuntimeError as exc: assert str(exc) == 'synthetic audit failure'
        conn.rollback()
        assert records.get(conn, race['id'], 'interview.json') == before and not interview.signed_file(folder)
        assert not interview.load(conn, race)['consent']['signed']
        class CommitFailure:
            def execute(self, *args): return conn.execute(*args)
            def commit(self): raise RuntimeError('synthetic commit failure')
            def rollback(self): return conn.rollback()
        try: consent_sign.sign(CommitFailure(), race, png, current['revision']); raise AssertionError('expected commit failure')
        except RuntimeError as exc: assert str(exc) == 'synthetic commit failure'
        assert records.get(conn, race['id'], 'interview.json') == before and not interview.signed_file(folder)
        # A disk error after creating the signature file must not leave a partial signed artifact.
        real_open = Path.open
        class PartialWrite:
            def __init__(self, path): self.path = path
            def __enter__(self): self.file = real_open(self.path, 'xb'); return self
            def write(self, content): self.file.write(content[:12]); raise OSError('synthetic disk full')
            def __exit__(self, *args): self.file.close()
        def failing_open(path, mode='r', *args, **kwargs):
            if mode == 'xb' and path.name.endswith(' signed.pdf'): return PartialWrite(path)
            return real_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', failing_open):
            try: consent_sign.sign(conn, race, png, current['revision']); raise AssertionError('expected write failure')
            except OSError as exc: assert str(exc) == 'synthetic disk full'
        assert records.get(conn, race['id'], 'interview.json') == before and not interview.signed_file(folder)
        # A real signed artifact locks its consent metadata but not interview notes.
        result = consent_sign.sign(conn, race, png, current['revision']); conn.commit()
        signed_record = interview.load(conn, race); signed_record['notes'] = 'additional notes'
        interview.save(conn, race, signed_record); conn.commit()
        before = (folder / result['file']).read_bytes()
        signed_record['consent']['authorised_name'] = 'Other person'
        try: interview.save(conn, race, signed_record); raise AssertionError('changed signed consent')
        except ValueError as exc: assert 'signed consent' in str(exc)
        assert (folder / result['file']).read_bytes() == before
        conn.execute("INSERT INTO tasks(id,patient_id,step,state,waiting_for,created,flow) VALUES ('abc',?,'pathology','waiting','mhr','now',0)", (patient['id'],)); conn.commit()
        assert call('POST', '/api/pathology/result', {'id':patient['id'], 'status':'no report to read', 'saved':[]})[0] == 200
        task = conn.execute("SELECT state,output FROM tasks WHERE id='abc'").fetchone(); assert tuple(task) == ('done', 'No pathology reports in My Health Record')
        patient = conn.execute('SELECT * FROM patients WHERE id=?', (patient['id'],)).fetchone()
        assert not patient['has_pathology'] and steps.done('pathology', conn, patient) and api.next_step(patient, conn) != 'collect pathology'
        assert call('POST', '/api/run/abc/result', {'state':'failed', 'output':'no report to read'})[0] == 200
        assert patient['id'] not in [p['id'] for p in call('GET', '/api/pathology/queue')[1]['patients']]
        conn.execute("INSERT INTO tasks(id,patient_id,step,state,waiting_for,created,flow) VALUES ('def',?,'pathology','waiting','mhr','now',0)", (patient['id'],)); conn.commit()
        assert call('POST', '/api/run/def/result', {'state':'failed', 'output':'no report to read'})[0] == 200
        assert tuple(conn.execute("SELECT state,output FROM tasks WHERE id='def'").fetchone()) == ('done', 'No pathology reports in My Health Record')
    finally: conn.close()
print('consent signing self-check ok')
