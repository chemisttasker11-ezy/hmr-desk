"""HMR Desk database: the single source of truth for patient state.
Location: %USERPROFILE%\\HMR-Desk-data\\hmr.db (see DATA_DIR); override with env HMR_DB (tests).
Run `python db.py` for a self-check."""
import datetime, json, os, re, sqlite3
import app_paths

BASE = str(app_paths.workspace_root())


# Not under AppData: Claude Desktop is a packaged app, so programs it launches get a private redirected copy of
# AppData and a database there splits into two copies. Not under OneDrive either.
DATA_DIR = str(app_paths.data_root())


def db_path():
    return os.environ.get('HMR_DB') or os.path.join(DATA_DIR, 'hmr.db')


SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,          -- patient_key(name): stable match across files
  name TEXT NOT NULL,
  phone TEXT, address TEXT, suburb TEXT, postcode TEXT,
  gp TEXT, clinic TEXT, referral_date TEXT,
  dob TEXT, sex TEXT, medicare TEXT, irn TEXT, ihi TEXT,
  state TEXT NOT NULL DEFAULT 'new',  -- state machine, see STATES
  status_text TEXT,                   -- wording shown on the dashboard (plan JSON "Status")
  visit_date TEXT, visit_time TEXT, visit_end TEXT, visit_group TEXT,  -- current slot (ISO date, HH:MM)
  offered_date TEXT,                  -- day an offer was for, kept after a decline/hold
  note TEXT, reply TEXT,
  contact_id TEXT,                    -- id in the SMS connector's contact store
  folder TEXT,                        -- path relative to BASE
  has_pathology INTEGER DEFAULT 0, has_sheet INTEGER DEFAULT 0,
  plan_order INTEGER,                 -- position in the plan JSON; NULL = not on the current plan (e.g. old declines)
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS day_plans (
  date TEXT PRIMARY KEY, start_time TEXT, start_place TEXT, end_place TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
  title TEXT NOT NULL, place TEXT, note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visits (
  id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
  kind TEXT NOT NULL CHECK(kind IN ('hmr','followup1','followup2')),
  visit_date TEXT, report_sent TEXT, claimed TEXT, folder TEXT,
  source TEXT NOT NULL CHECK(source IN ('import','app')), note TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,                -- out: fixed client id sent to the gateway; in: gateway inbox id
  patient_id INTEGER REFERENCES patients(id),
  direction TEXT NOT NULL CHECK (direction IN ('out','in')),
  body TEXT NOT NULL,
  kind TEXT,                          -- out: invitation/offer/follow-up/confirmation/reply/test; in: YES/DECLINE/OTHER
  state TEXT NOT NULL,                -- out: queued/submitting/Pending/Sent/Delivered/Failed/unknown; in: received
  recipient TEXT,                     -- out only: number actually used
  offer_ref TEXT,                     -- in: the out message id this reply answers
  created_at TEXT NOT NULL, sent_at TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS events (   -- append-only audit trail: nothing is overwritten silently
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, patient_id INTEGER, type TEXT NOT NULL, detail TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, patient_id INTEGER REFERENCES patients(id), step TEXT NOT NULL,
  state TEXT NOT NULL, waiting_for TEXT, output TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL, started TEXT, finished TEXT, flow INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS tasks_active ON tasks(COALESCE(patient_id, -1), step)
  WHERE state IN ('queued','running','waiting');
"""

# state -> states it may move to. hold/declined/expired are reachable from any pre-visit state.
_PRE = ('new', 'pooled', 'offered', 'confirmed', 'pathology_ready', 'sheet_ready', 'hold')
STATES = {
    'new': ('pooled',), 'pooled': ('offered',), 'offered': ('confirmed', 'pooled'),
    'confirmed': ('pathology_ready', 'sheet_ready', 'visited', 'offered', 'pooled'),
    'pathology_ready': ('sheet_ready', 'visited', 'offered', 'pooled'),
    'sheet_ready': ('visited', 'offered', 'pooled'),
    'visited': ('report_drafted',), 'report_drafted': ('signed_off',), 'signed_off': ('sent',),
    'sent': ('claimed',), 'claimed': (),
    'hold': ('pooled', 'offered', 'confirmed'), 'declined': ('pooled',), 'expired': ('pooled',),
}


def connect(path=None):
    path = path or db_path()
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')  # the service and one-off commands may open it together
    conn.executescript(SCHEMA)
    if 'format' not in {row[1] for row in conn.execute('PRAGMA table_info(tasks)')}:
        conn.execute("ALTER TABLE tasks ADD COLUMN format TEXT NOT NULL DEFAULT 'docx'")
    for table, column, definition in [('patients', 'is_test', 'INTEGER NOT NULL DEFAULT 0'), ('patients', 'call_list', 'INTEGER NOT NULL DEFAULT 0'), ('patients', 'archived_at', 'TEXT'), ('patients', 'hold_from', 'TEXT'), ('messages', 'visit_date', 'TEXT'), ('messages', 'visit_time', 'TEXT'), *[('messages', name, typ) for name, typ in [('ai_intent','TEXT'), ('ai_summary','TEXT'), ('ai_confidence','REAL'), ('ai_reply','TEXT'), ('ai_draft_id','TEXT')]]]:
        if column not in {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    conn.commit()
    import_meetings(conn)
    return conn


def import_meetings(conn):
    from pathlib import Path
    from places import MEET
    if conn.execute("SELECT 1 FROM meta WHERE key='meetings_imported'").fetchone():
        return
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM meta WHERE key='meetings_imported'").fetchone():
            return
        plan = max(Path(BASE).glob('Appointment_Plan_*.json'), key=lambda p: p.stat().st_mtime, default=None)
        if plan:
            data = json.loads(plan.read_text(encoding='utf-8-sig'))
            for day, start, end, title in data.get('meetings', []):
                if day < datetime.date.today().isoformat():
                    continue
                conn.execute('''INSERT INTO appointments(date,start,end,title,place,note,created_at)
                    SELECT ?,?,?,?,?,?,? WHERE NOT EXISTS
                    (SELECT 1 FROM appointments WHERE date=? AND start=? AND title=?)''',
                    (day, start, end, title, MEET.get(title), '', now(), day, start, title))
        conn.execute("INSERT INTO meta(key,value) VALUES ('meetings_imported','1')")


def now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def patient_key(name):
    """'Mr Alex Quinn Example' and 'alex example' -> 'alex example' (first + last word, letters only)."""
    w = re.sub(r"[^a-z' -]", ' ', re.sub(r'^(mr|mrs|ms|miss|dr)\.?\s+', '', (name or '').strip().lower())).split()
    return f'{w[0]} {w[-1]}' if len(w) > 1 else (w[0] if w else '')


def log(conn, patient_id, type_, detail=None, source='engine'):
    conn.execute('INSERT INTO events (ts, patient_id, type, detail, source) VALUES (?,?,?,?,?)',
                 (now(), patient_id, type_, json.dumps(detail, ensure_ascii=False) if detail is not None else None, source))


def can_move(old, new):
    return new == old or new in STATES.get(old, ()) or (new in ('hold', 'declined', 'expired') and old in _PRE)


def set_state(conn, patient_id, new, status_text=None, source='engine', force=False):
    """Move a patient through the state machine and log it. force=True is for the importer and manual fixes."""
    row = conn.execute('SELECT state, status_text, is_test FROM patients WHERE id=?', (patient_id,)).fetchone()
    if row['is_test'] and status_text and not status_text.startswith('TEST'):
        status_text = 'TEST - ' + status_text
    if new not in STATES:
        raise ValueError(f'unknown state {new}')
    if not force and not can_move(row['state'], new):
        raise ValueError(f"{row['state']} -> {new} is not allowed")
    if row['state'] == new and (status_text is None or status_text == row['status_text']):
        return False
    conn.execute('UPDATE patients SET state=?, status_text=COALESCE(?, status_text), updated_at=? WHERE id=?',
                 (new, status_text, now(), patient_id))
    log(conn, patient_id, 'state', {'from': row['state'], 'to': new, 'text': status_text}, source)
    return True


def _first_sunday(year, month):
    d = datetime.date(year, month, 1)
    return d + datetime.timedelta(days=(6 - d.weekday()) % 7)


def utc_offset_hours(postcode, when=None):
    """Patient-local UTC offset. QLD has no daylight saving (+10). NSW/ACT/VIC/TAS add an hour from the first
    Sunday of October to the first Sunday of April. shortcut: no tzdata on this PC and 3 am edge hours ignored;
    upgrade to zoneinfo if patients outside the east coast are added."""
    when = when or datetime.datetime.now()
    pc = str(postcode or '')[:1]
    if pc in ('2', '3', '7'):
        d = when.date() if isinstance(when, datetime.datetime) else when
        if d >= _first_sunday(d.year, 10) or d < _first_sunday(d.year, 4):
            return 11
    return 10


def in_sending_window(postcode, when=None):
    """08:00-20:00 in the patient's own clock; `when` is this PC's clock (Queensland time)."""
    when = when or datetime.datetime.now()
    local = when + datetime.timedelta(hours=utc_offset_hours(postcode, when) - 10)
    return datetime.time(8, 0) <= local.time() < datetime.time(20, 0)


def backup(conn=None):
    """Copy the database next to itself as hmr-backup-<weekday>.db (7 rolling copies)."""
    own = conn is None
    conn = conn or connect()
    target = os.path.join(os.path.dirname(db_path()), f'hmr-backup-{datetime.date.today():%a}.db')
    out = sqlite3.connect(target)
    try:
        conn.backup(out)
    finally:
        out.close()
    if own:
        conn.close()
    return target


if __name__ == '__main__':
    import tempfile
    assert patient_key('Mr Alex Quinn Example') == patient_key('alex example') == 'alex example'
    assert patient_key("Patricia D'Agostino") == "patricia d'agostino"
    assert utc_offset_hours('2486', datetime.datetime(2026, 11, 11, 9)) == 11   # NSW summer
    assert utc_offset_hours('2486', datetime.datetime(2026, 6, 1, 9)) == 10     # NSW winter
    assert utc_offset_hours('4216', datetime.datetime(2026, 11, 11, 9)) == 10   # QLD
    assert in_sending_window('4216', datetime.datetime(2026, 11, 11, 19, 30))
    assert not in_sending_window('2486', datetime.datetime(2026, 11, 11, 19, 30))  # 20:30 in NSW
    assert not in_sending_window('4216', datetime.datetime(2026, 11, 11, 7, 59))
    assert in_sending_window('2486', datetime.datetime(2026, 11, 11, 7, 30))       # 08:30 in NSW
    with tempfile.TemporaryDirectory() as t:
        c = connect(os.path.join(t, 'x.db'))
        c.execute("INSERT INTO patients (key, name) VALUES ('a b', 'A B')")
        assert set_state(c, 1, 'pooled') and set_state(c, 1, 'offered') and set_state(c, 1, 'confirmed')
        assert not set_state(c, 1, 'confirmed')            # no change, no event
        try:
            set_state(c, 1, 'claimed'); raise SystemExit('should have refused confirmed -> claimed')
        except ValueError:
            pass
        assert set_state(c, 1, 'declined') and set_state(c, 1, 'pooled')
        assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 5
        c.close()
    print('db self-check ok')

