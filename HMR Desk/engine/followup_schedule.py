"""Follow-up and claim deadline rules (moved verbatim from api.py)."""
import calendar
import datetime as dt


def meta(conn, key, default):
    row = conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


LEGACY_FIRST_DAYS, LEGACY_END_DAYS = 30, 270
RULE_SOURCE = 'PPA HMR Program Rules, October 2026, s5.9 and s8'


def add_months(day, months):
    """Calendar-month arithmetic. A day that does not exist in the target month moves to its last day
    (31 Jan + 1 month = 28 Feb). The PPA rules do not state month-end handling: this is a provisional
    interpretation, shown as such, never a certified eligibility date."""
    n = day.month - 1 + int(months)
    year, month = day.year + n // 12, n % 12 + 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def claim_deadline(interview_day):
    """Informational only: PPA s8 says claims are due by the end of the next calendar month after the interview."""
    nxt = add_months(interview_day.replace(day=1), 1)
    return nxt.replace(day=calendar.monthrange(nxt.year, nxt.month)[1])


def followup_overrides(conn):
    """Day-based overrides a user explicitly stored (a value other than the old 30/270 defaults).
    Without an override the calendar-month reading of the rules applies."""
    first, end = meta(conn, 'followup_first_after_days', None), meta(conn, 'followup_window_end_days', None)
    first = int(first) if first is not None and int(first) != LEGACY_FIRST_DAYS else None
    end = int(end) if end is not None and int(end) != LEGACY_END_DAYS else None
    return first, end


def followups(visit, first=None, end=None, months=24, today=None):
    """first/end are day overrides; None means the calendar-month rule (1 and 9 months after the initial interview)."""
    if not visit:
        return None
    day = dt.date.fromisoformat(visit[:10])
    new = add_months(day, months)
    start = day + dt.timedelta(days=int(first)) if first is not None else add_months(day, 1)
    finish = day + dt.timedelta(days=int(end)) if end is not None else add_months(day, 9)
    today = today or dt.date.today()
    custom = first is not None or end is not None
    return {'visit_date': str(day), 'first_due': str(start), 'window_end': str(finish),
            'new_hmr': str(new), 'due': start <= today <= finish,
            'rule_basis': 'custom-days-override' if custom else 'calendar-months-provisional',
            'rule_source': RULE_SOURCE,
            'initial_claim_by': str(claim_deadline(day))}


def second_followup_due(conn, first_date):
    """Second follow-up: no earlier than one month after the first (calendar month unless a day override is stored)."""
    if not first_date: return None
    day = dt.date.fromisoformat(first_date)
    first_days, _ = followup_overrides(conn)
    return str(day + dt.timedelta(days=first_days) if first_days is not None else add_months(day, 1))


def patient_followups(conn, pid, today=None):
    row = conn.execute("SELECT * FROM visits WHERE patient_id=? AND kind='hmr' AND visit_date IS NOT NULL ORDER BY visit_date DESC,id DESC LIMIT 1", (pid,)).fetchone()
    if not row: return None
    today = today or dt.date.today()
    first_days, end_days = followup_overrides(conn)
    result = followups(row['visit_date'], first_days, end_days, meta(conn, 'new_hmr_after_months', 24), today)
    done = list(conn.execute("SELECT kind,visit_date,claimed FROM visits WHERE patient_id=? AND kind IN ('followup1','followup2') AND visit_date>=? ORDER BY visit_date DESC,id DESC", (pid,row['visit_date'])))
    first = next((x for x in done if x['kind'] == 'followup1'), None)
    second = next((x for x in done if x['kind'] == 'followup2'), None)
    first_date = first['visit_date'] if first else None
    due2 = second_followup_due(conn, first_date)
    alerts = []
    import followup
    gaps = {n: followup.readiness(conn, {'id': pid}, n, v['visit_date']) if v else [] for n, v in ((1, first), (2, second))}
    for number, visit in ((1, first), (2, second)):
        if visit and gaps[number]: alerts.append(f'follow-up {number} documentation incomplete')
        elif visit and not visit['claimed']: alerts.append(f'follow-up {number} to claim')
    next_action = next_due = None
    if first and gaps[1]: next_action = 'followup1_document'
    elif second and gaps[2]: next_action = 'followup2_document'
    elif first and not first['claimed']: next_action = 'followup1_claimed'
    elif second and not second['claimed']: next_action = 'followup2_claimed'
    elif str(today) <= result['window_end']:
        if not first: next_action, next_due = 'followup1', result['first_due']
        elif not second: next_action, next_due = 'followup2', due2
    clinical_action, clinical_due = (('followup1', result['first_due']) if not first else ('followup2', due2) if not second else (None, None))
    if clinical_due and clinical_due <= str(today) <= result['window_end']:
        alerts.append('follow-up ' + clinical_action[-1] + ' due')
    if str(today) >= result['new_hmr']: alerts.append('new HMR possible')
    result.update(due=bool(alerts), alerts=alerts, followup1=first_date, followup2=bool(second),
                  followup1_claimed=first['claimed'] if first else None,
                  followup2_claimed=second['claimed'] if second else None,
                  followup1_claim_by=str(claim_deadline(dt.date.fromisoformat(first_date))) if first_date else None,
                  followup2_claim_by=str(claim_deadline(dt.date.fromisoformat(second['visit_date']))) if second else None,
                  followup2_due=due2, readiness_scope='documentation only: PPA paid prerequisites are not modelled, so this does not mean payable', followup1_documentation_gaps=gaps[1], followup2_documentation_gaps=gaps[2],
                  next_action=next_action, next_due=next_due)
    return result
