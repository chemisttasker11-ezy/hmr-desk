"""Import official PBS API CSV bulk ZIP (not legacy drug.txt).

The publisher's monthly ZIP avoids hammering the shared public API. All source
CSV tables are retained for restrictions and future joins, not guessed from text.
"""
import csv
import datetime as dt
import io
import json
from pathlib import PurePosixPath
import zipfile
from .catalog import add_medicine, add_raw, snapshot

REQUIRED = {
    'items': {'li_item_id', 'pbs_code', 'program_code', 'drug_name', 'brand_name',
              'schedule_code', 'brand_substitution_group_id', 'originator_brand_indicator'},
    'schedules': {'schedule_code', 'effective_date'},
    'amt-items': {'li_item_id', 'concept_type_code', 'amt_code', 'non_amt_code', 'schedule_code'},
    'restrictions': {'res_code', 'schedule_code'},
    'item-restriction-relationships': {'pbs_code', 'res_code', 'benefit_type_code', 'schedule_code'},
}


def value(text):
    return None if text is None or str(text).strip().lower() in ('', 'null') else str(text).strip()


def indicator(text):
    if value(text) is None:
        return None
    if text not in ('Y', 'N'):
        raise ValueError(f'Unknown PBS indicator: {text!r}')
    return text == 'Y'


def load(db, path, release, url, today=None):
    today = today or dt.date.today()
    with zipfile.ZipFile(path) as z:
        members = {}
        for item in z.infolist():
            if item.is_dir() or not item.filename.lower().endswith('.csv'):
                continue
            if item.file_size > 250_000_000:
                raise ValueError('Oversized PBS CSV')
            name = PurePosixPath(item.filename).stem
            if name in members:
                raise ValueError(f'Duplicate PBS CSV {name}')
            members[name] = item
        if sum(i.file_size for i in members.values()) > 1_000_000_000:
            raise ValueError('Oversized PBS archive')
        if not REQUIRED.keys() <= members.keys():
            raise ValueError(f'Missing PBS CSV tables: {REQUIRED.keys() - members.keys()}')

        def rows(table):
            with z.open(members[table]) as stream:
                reader = csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig', newline=''))
                missing = REQUIRED.get(table, set()) - set(reader.fieldnames or [])
                if missing:
                    raise ValueError(f'{table}: missing columns {missing}')
                for row in reader:
                    if None in row:
                        raise ValueError(f'{table}: malformed CSV row')
                    yield row

        schedules = list(rows('schedules'))
        codes = {r['schedule_code'] for r in schedules}
        # Public ZIP metadata can still say EMBARGO after publication. Check the
        # effective date rather than blindly interpreting that metadata as access.
        if not schedules or any(dt.date.fromisoformat(r['effective_date']) > today for r in schedules):
            raise ValueError('Missing or future-effective PBS schedule')
        if release not in codes:
            raise ValueError(f'--release must be one of schedule_code values: {sorted(codes)}')
        links = {}
        for row in rows('amt-items'):
            if row['schedule_code'] == release:
                links.setdefault(row['li_item_id'], []).append(row)
        with snapshot(db, 'pbs', release, path, url):
            for table in sorted(members):
                for number, row in enumerate(rows(table), 1):
                    if row.get('schedule_code', release) != release:
                        continue
                    add_raw(db, 'pbs', table, number, row)
                    if table != 'items':
                        continue
                    details = dict(row)
                    details['amt_links'] = links.get(row['li_item_id'], [])
                    details['pbs_listed'] = True
                    details['originator_for_price_disclosure'] = indicator(row['originator_brand_indicator'])
                    # A negative price-disclosure flag does NOT establish generic status.
                    details['generic_status'] = 'unknown'
                    form = value(row.get('schedule_form')) or value(row.get('li_form'))
                    display = ' | '.join(filter(None, [value(row['brand_name']), form, row['pbs_code']]))
                    code = ':'.join((row['program_code'], row['pbs_code'], row['li_item_id']))
                    add_medicine(db, 'pbs', code, display, 'pbs_listing',
                                 generic=value(row['drug_name']), brand=value(row['brand_name']),
                                 # schedule_form includes strength/pack, not an isolated dose-form field.
                                 details=details)
