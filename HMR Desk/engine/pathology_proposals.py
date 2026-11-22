"""Read-only unverified pathology PDF cell proposals, tied to original geometry.

Only explicitly labelled digital-text tables are supported in this candidate.
There is no clinical interpretation, unit conversion, verification or AI export.
"""
import datetime as dt
import hashlib
from pathlib import Path
import re
import uuid

import fitz

import jobs
import pathology_import
import pathology_records

SCHEMA = 'pathology-proposals-v1'
EXTRACTOR = 'digital-geometry-v1'
MAX_PROPOSALS = 300
NUMBER = re.compile(r'^(?:[<>]=?|=)?\s*-?\d+(?:\.\d+)?$')
VALUE_MARK = re.compile(r'^((?:[<>]=?|=)?\s*-?\d+(?:\.\d+)?)(?:\s+|\s*\()([HL])\)?$', re.I)
DATE = re.compile(r'\b(?:\d{1,2}[/-]\d{1,2}[/-](?:\d{4}|\d{2})|\d{4}-\d{1,2}-\d{1,2})\b')
COLLECTION = re.compile(r'(?i)^\s*(?:collected|collection\s+date|sample\s+date|specimen\s+date)\s*[:\-]?\s*')
HEADERS = {'test': {'test', 'analyte', 'analysis', 'investigation'},
           'value': {'result', 'results', 'value'},
           'unit': {'unit', 'units'},
           'reference_interval': {'reference', 'range', 'interval'},
           'sample_date': {'collected', 'sample'}}


def _date(text):
    if not isinstance(text, str):
        return ''
    found = DATE.search(text)
    if not found:
        return ''
    raw = found.group()
    for pattern in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y', '%d-%m-%y'):
        try:
            return dt.datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            pass
    return ''


def _bbox(words):
    if not words:
        return []
    return [round(min(w[0] for w in words), 2), round(min(w[1] for w in words), 2),
            round(max(w[2] for w in words), 2), round(max(w[3] for w in words), 2)]


def _lines(page):
    """Physical baselines, not flattened multi-column reading order."""
    words = [w for w in page.get_text('words', sort=False) if len(w) >= 5 and str(w[4]).strip()]
    lines = []
    for word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        center = (word[1] + word[3]) / 2
        if lines and abs(lines[-1]['y'] - center) <= 3.0:
            line = lines[-1]
            line['words'].append(word)
            line['y'] = (line['y'] * (len(line['words']) - 1) + center) / len(line['words'])
        else:
            lines.append({'y': center, 'words': [word]})
    for line in lines:
        line['words'].sort(key=lambda w: w[0])
        line['text'] = ' '.join(str(w[4]) for w in line['words'])
    return lines


def _header(line):
    anchors = []
    for word in line['words']:
        raw = str(word[4]).strip()
        name = raw.casefold().strip(':.')
        field = next((key for key, names in HEADERS.items() if name in names), None)
        if field:
            # "Reference Interval" or "Sample Date" is one column, not two.
            if field != 'value' and any(a['field'] == field and
                                        0 <= word[0] - a['x'] < 115 for a in anchors):
                continue
            anchors.append({'field': field, 'x': word[0], 'label': raw})
        elif _date(raw):
            # Result column associated with an explicitly printed date header.
            anchors.append({'field': 'value', 'x': word[0], 'label': raw,
                            'date': _date(raw)})
    names = [a['field'] for a in anchors]
    if not all(n in names for n in ('test', 'unit', 'reference_interval', 'value')):
        return None
    anchors.sort(key=lambda a: a['x'])
    if any(names.count(k) != 1 for k in ('test', 'unit', 'reference_interval')):
        return None
    values = [a for a in anchors if a['field'] == 'value']
    dated = [a for a in values if a.get('date')]
    if len(values) > 1 and (len(values) != len(dated) or
                            len(set(a['date'] for a in dated)) != len(values)):
        return None
    if len(values) > 8 or len(anchors) > 12 or anchors[0]['field'] != 'test':
        return None
    return anchors


def _cells(line, columns):
    output = {i: [] for i in range(len(columns))}
    for word in line['words']:
        x = (word[0] + word[2]) / 2
        index = min(range(len(columns)), key=lambda i: abs(x - columns[i]['x']))
        output[index].append(word)
    return output


def _text(words):
    return ' '.join(str(w[4]) for w in words).strip()


def _sample_date(lines, before):
    found = set()
    for line in lines[:before]:
        if COLLECTION.match(line['text']):
            d = _date(line['text'])
            if d:
                found.add(d)
            else:
                return '', 'Collection label has no valid unambiguous date'
    if len(found) == 1:
        return found.pop(), ''
    if len(found) > 1:
        return '', 'Multiple different collection dates on this page'
    return '', 'No explicitly labelled collection date'


# Exact printed units only; never infer missing units.
PRINTED_UNIT = re.compile(
    r'(?i)^(?:mmol/L|umol/L|µmol/L|μmol/L|nmol/L|pmol/L|mg/L|g/L|U/L|IU/L|'
    r'mL/min(?:/1\.73m(?:2|²))?|mmol/mol|%|fL|pg|10\^?(?:9|12)/L|'
    r'10\*\*(?:9|12)/L|mEq/L|ng/mL|mg/dL)$')
NUMERIC_RANGE = re.compile(
    r'^\(\s*(?:[<>]=?\s*)?-?\d+(?:\.\d+)?\s*(?:-|–|to)?\s*-?\d*(?:\.\d+)?\s*\)$')

PANEL_TITLE = re.compile(
    r'(?i)\b(?:full blood count|diabetic testing|lipid studies)\b')
COLLECTION_ROW = re.compile(r'(?i)^\s*(?:coll(?:ection)?|sample|specimen)\s*date\s*:')
EXCLUDED_ANALYTES = {'date', 'time', 'lab no', 'lab number', 'random',
                     'fasting', 'status', 'clinical notes'}


def _proposal(source_id, digest, page, column_label, names, original,
              processed, issues, notes):
    """One PDF location, independent of clinical record identity."""
    full = [w for group in names.values() for w in group]
    identity = '|'.join((EXTRACTOR, digest, str(page.number + 1),
                         repr(_bbox(names['test'])), repr(_bbox(names['value'])),
                         column_label))
    return {
        'id': hashlib.sha256(identity.encode('utf-8')).hexdigest(),
        'source_id': source_id, 'source_sha256': digest,
        'page': page.number + 1, 'method': 'digital_text',
        'source_column_label': column_label,
        'row_bbox': _bbox(full),
        'cell_bbox': {key: _bbox(names.get(key, [])) for key in
                      ('test', 'value', 'unit', 'reference_interval', 'sample_date')},
        'raw_text': original,
        'fields': processed,
        'field_uncertainty': issues,
        'warnings': ['UNVERIFIED digital text; compare PDF pixels and patient identity'] + notes,
    }


def _cumulative_proposals(page, lines, source_id, digest):
    """Cumulative biochemistry: 'Date' plus dated results, printed units/ranges.

    Strictly requires a cumulative heading and explicit columns. It never
    interprets a report/print date or a clinical-risk target as a lab interval.
    """
    heading = any('cumulative' in line['text'].casefold() and
                  any(word in line['text'].casefold() for word in ('biochemistry', 'lipid'))
                  for line in lines[:35])
    if not heading:
        return None
    candidates = []
    for i, line in enumerate(lines[:35]):
        if not re.match(r'(?i)^\s*date\s+', line['text']):
            continue
        dates = [(w, _date(str(w[4]))) for w in line['words']
                 if DATE.fullmatch(str(w[4]).strip())]
        if 1 <= len(dates) <= 8 and all(date for _, date in dates):
            candidates.append((i, dates))
    if len(candidates) != 1:
        return [], ['Cumulative date-header association is not unique']
    start, columns = candidates[0]
    xs = [(float(w[0]) + float(w[2])) / 2 for w, _ in columns]
    if xs != sorted(xs) or min(xs) < 80:
        return [], ['Cumulative result date-column geometry is ambiguous']
    result = []
    target_only = any('target if' in l['text'].casefold() and
                      'risk' in ' '.join(a['text'] for a in lines[max(0,i-1):i+3]).casefold()
                      for i, l in enumerate(lines[:start+10]))
    for line in lines[start+1:]:
        words = line['words']
        units = [w for w in words if PRINTED_UNIT.fullmatch(str(w[4]).strip())
                 and (w[0] + w[2]) / 2 > xs[-1] + 14]
        if len(units) != 1:
            continue
        unitword = units[0]
        # Analyte is strictly to the left of the leftmost dated result.
        analyte = [w for w in words if (w[0] + w[2]) / 2 < xs[0]-20]
        name = _text(analyte)
        if (not name or len(name) > 48 or name.casefold().strip(' :.') in EXCLUDED_ANALYTES
                or not re.search('[A-Za-z]', name)):
            continue
        # Only numeric result-column words are eligible. Do not use trailing
        # lab IDs, notes, ranges or numbers outside the result-column area.
        value_area = [w for w in words
                      if xs[0]-20 <= (w[0]+w[2])/2 < unitword[0]-8]
        reference_words = [w for w in words if w[0] >= unitword[2]+2]
        printed_reference = _text(reference_words)
        unit = str(unitword[4])
        for j, (header, date) in enumerate(columns):
            left = xs[j]-min(26.0, (xs[j]-xs[j-1])*0.42) if j else xs[j]-24.0
            right = xs[j]+min(26.0, (xs[j+1]-xs[j])*0.42) if j+1<len(xs) else unitword[0]-6
            val_words = [w for w in value_area if left <= (w[0]+w[2])/2 < right]
            raw = _text(val_words)
            if not raw:
                continue  # empty historical result column is not a zero
            match = VALUE_MARK.fullmatch(raw)
            value, flag = (match.group(1), match.group(2).upper()) if match else (raw, '')
            field_issues = {}
            if not NUMBER.fullmatch(value):
                value = ''
                field_issues['value'] = ['Ambiguous cumulative value, inspect original cell']
            if len(str(header[4]).split('/')[-1]) == 2:
                field_issues['sample_date'] = ['Two-digit printed year, verify century against original report']
            raw_fields = dict(test=name, value=raw, unit=unit,
                              reference_interval=printed_reference, sample_date=str(header[4]))
            clinical_reference = '' if target_only else printed_reference
            fields = dict(test=name, value=value, unit=unit,
                          reference_interval=clinical_reference, sample_date=date)
            if target_only:
                field_issues['reference_interval'] = [
                    'Printed range is conditional high-risk target, not a general lab reference']
            if not printed_reference:
                field_issues.setdefault('reference_interval', []).append(
                    'Laboratory reference not printed for this analyte')
            if flag:
                field_issues.setdefault('value', []).append('Printed H/L flag: '+flag)
            box = {'test': analyte, 'value': val_words, 'unit': [unitword],
                   'reference_interval': reference_words, 'sample_date': [header]}
            result.append(_proposal(source_id, digest, page, str(header[4]), box,
                                    raw_fields, fields, field_issues,
                                    ['Cumulative dated column; dates are not inferred from position']))
    if not result:
        return [], ['Cumulative heading found but no safely aligned analyte/value/unit rows']
    return result, []


def _parenthesised_range(words):
    """Return (start, end) of exactly one numeric parenthesised range."""
    spans = []
    for start in range(len(words)):
        if not str(words[start][4]).startswith('('):
            continue
        for end in range(start, min(start+4, len(words))):
            candidate = ' '.join(str(w[4]) for w in words[start:end+1])
            if not candidate.endswith(')'):
                continue
            if NUMERIC_RANGE.fullmatch(candidate):
                spans.append((start, end))
            break
    return spans[0] if len(spans) == 1 else None


def _single_panel_proposals(page, lines, source_id, digest):
    """Collected-date FBC, HbA1c and lipid layouts with interval BEFORE unit."""
    titles = [i for i, line in enumerate(lines) if PANEL_TITLE.search(line['text'])]
    if not titles:
        return None
    # More than one recognised panel per page requires explicit page review:
    # cross-panel date and result associations must not be guessed.
    if len(titles) != 1:
        return [], ['Multiple recognised pathology panels on one page: manual association required']
    title = titles[0]
    collected = [(i, w) for i, line in enumerate(lines[title+1:title+14], title+1)
                 if COLLECTION_ROW.match(line['text'])
                 for w in line['words'] if DATE.fullmatch(str(w[4]).strip())]
    if len(collected) != 1:
        return [], ['No unique labelled specimen collection date in panel']
    collection_index, sample_word = collected[0]
    sample = _date(str(sample_word[4]))
    if not sample:
        return [], ['Cannot parse printed specimen date in panel']
    rows = []
    for line in lines[collection_index+1:]:
        words = line['words']
        range_cell = _parenthesised_range(words)
        if not range_cell:
            continue
        a, b = range_cell
        # The unit is printed after the reference interval in these panels.
        unit_candidates = [w for w in words[b+1:] if PRINTED_UNIT.fullmatch(str(w[4]).strip())]
        if len(unit_candidates) != 1:
            continue
        unit_word = unit_candidates[0]
        nums = [i for i, w in enumerate(words[:a]) if NUMBER.fullmatch(str(w[4]).strip())]
        if len(nums) != 1:
            continue
        value_index = nums[0]
        test_words = words[:value_index]
        test = _text(test_words)
        if (not test or len(test)>50 or not re.search('[A-Za-z]', test) or
                test.casefold().strip(' :.') in EXCLUDED_ANALYTES):
            continue
        raw_value_words = words[value_index:a]
        raw_value = _text(raw_value_words)
        flag_tokens = [str(w[4]).upper() for w in raw_value_words[1:]]
        if any(w not in ('H', 'L') for w in flag_tokens):
            continue
        value = str(words[value_index][4])
        range_words = words[a:b+1]
        raw_ref = _text(range_words)
        field_issues = {}
        if flag_tokens:
            field_issues['value'] = ['Printed H/L flag: '+','.join(flag_tokens)]
        if re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2}\b', str(sample_word[4])):
            field_issues['sample_date'] = ['Two-digit printed year, verify century against original report']
        names = {'test': test_words, 'value': raw_value_words, 'unit': [unit_word],
                 'reference_interval': range_words, 'sample_date': [sample_word]}
        original = dict(test=test, value=raw_value, unit=str(unit_word[4]),
                        reference_interval=raw_ref, sample_date=str(sample_word[4]))
        fields = dict(test=test, value=value, unit=str(unit_word[4]),
                      reference_interval=raw_ref, sample_date=sample)
        rows.append(_proposal(source_id, digest, page, str(sample_word[4]),
                              names, original, fields, field_issues,
                              ['Panel date explicitly printed; no clinical interpretation']))
    if not rows:
        return [], ['Panel recognised but no safely aligned values with printed ranges and units']
    # Notes and conditional references are not result rows. The literal parenthesised
    # reference stays as printed; clinical-target interpretation is separate.
    return rows, []


def _page_proposals(page, source_id, digest):
    lines = _lines(page)
    candidates = [(i, _header(line)) for i, line in enumerate(lines)]
    candidates = [(i, h) for i, h in candidates if h]
    if len(candidates) != 1:
        for alternate in (_cumulative_proposals, _single_panel_proposals):
            parsed = alternate(page, lines, source_id, digest)
            if parsed is not None:
                return parsed
        return [], ['No unique supported table header (test, result/date, unit, reference)']
    header_index, columns = candidates[0]
    common_date, common_note = _sample_date(lines, header_index)
    results, issues = [], []
    last_y = lines[header_index]['y']
    for line in lines[header_index + 1:]:
        if line['y'] <= last_y + 2.5:
            continue
        cells = _cells(line, columns)
        grouped = {k: [] for k in ('test', 'value', 'unit', 'reference_interval', 'sample_date')}
        for j, col in enumerate(columns):
            grouped[col['field']].append((col, cells[j]))
        test_words = grouped['test'][0][1]
        test = _text(test_words)
        if not test:
            continue
        if not grouped['value'] or not any(_text(w) for _, w in grouped['value']):
            if any(_text(w) for _, w in grouped['unit'] + grouped['reference_interval']):
                issues.append('A row with no explicit result was not offered')
            continue
        unit_words = grouped['unit'][0][1]
        range_words = grouped['reference_interval'][0][1]
        for col, value_words in grouped['value']:
            raw_value = _text(value_words)
            if not raw_value:
                continue
            field_issues, flag, value = {}, '', raw_value
            marked = VALUE_MARK.fullmatch(raw_value)
            if marked:
                value, flag = marked.group(1), marked.group(2).upper()
            if not NUMBER.fullmatch(value):
                value = ''
                field_issues['value'] = ['Ambiguous/non-numeric result: compare original cell']
            raw_date = _text(grouped['sample_date'][0][1]) if grouped['sample_date'] else ''
            if col.get('date'):
                sample = col['date']
                if raw_date:
                    field_issues['sample_date'] = ['Result column date and row collection date both present: review association']
                    sample = ''
            elif raw_date:
                sample = _date(raw_date)
                if not sample:
                    field_issues['sample_date'] = ['Row collection date is not valid or not unambiguous']
            else:
                sample = common_date
                if not sample:
                    field_issues['sample_date'] = [common_note]
            unit, reference = _text(unit_words), _text(range_words)
            for key, txt in (('test', test), ('unit', unit), ('reference_interval', reference)):
                if not txt:
                    field_issues.setdefault(key, []).append('Field not printed in its expected column')
            if flag:
                field_issues.setdefault('value', []).append('Printed lab flag %s separated from numeric text' % flag)
            row_boxes = [test_words, value_words, unit_words, range_words]
            if grouped['sample_date']:
                row_boxes.append(grouped['sample_date'][0][1])
            all_words = [w for group in row_boxes for w in group]
            seed = '|'.join((EXTRACTOR, digest, str(page.number + 1),
                             repr(_bbox(test_words)), repr(_bbox(value_words)),
                             col.get('date', '') or col['label']))
            proposal_id = hashlib.sha256(seed.encode('utf-8')).hexdigest()
            results.append({
                'id': proposal_id, 'source_id': source_id, 'source_sha256': digest,
                'page': page.number + 1, 'method': 'digital_text',
                'source_column_label': col['label'], 'row_bbox': _bbox(all_words),
                'cell_bbox': {'test': _bbox(test_words), 'value': _bbox(value_words),
                              'unit': _bbox(unit_words), 'reference_interval': _bbox(range_words),
                              'sample_date': _bbox(grouped['sample_date'][0][1]) if grouped['sample_date'] else []},
                'raw_text': {'test': test, 'value': raw_value, 'unit': unit,
                             'reference_interval': reference, 'sample_date': raw_date},
                'fields': {'test': test, 'value': value, 'unit': unit,
                           'reference_interval': reference, 'sample_date': sample},
                'field_uncertainty': field_issues,
                'warnings': ['Unconfirmed digital text; visually compare original PDF and cell location'],
            })
    return results, issues


def _source_path(patient, source):
    root = jobs.patient_folder(patient).resolve()
    folder = root / 'Pathology'
    name = source.get('name')
    if not isinstance(name, str) or name != Path(name).name or not name.lower().endswith('.pdf'):
        raise ValueError('Invalid pathology source filename')
    target = folder / name
    if folder.is_symlink() or target.is_symlink() or target.resolve().parent != folder.resolve():
        raise ValueError('Unsafe pathology source location')
    if not target.is_file():
        raise ValueError('Pathology source missing; reload original PDF')
    return target


def _extract(conn, patient, source_id):
    if not isinstance(source_id, str) or not re.fullmatch(r'[a-f0-9]{32}', source_id):
        raise ValueError('Invalid pathology source ID')
    source = next((x for x in pathology_import.sources(conn, patient)['sources']
                   if x.get('id') == source_id), None)
    if source is None:
        raise ValueError('Pathology source not found for this patient')
    path = _source_path(patient, source)
    contents = path.read_bytes()
    digest = hashlib.sha256(contents).hexdigest()
    if digest != source['sha256']:
        raise ValueError('Pathology source bytes changed; reimport and re-review')
    try:
        with fitz.open(stream=contents, filetype='pdf') as doc:
            if doc.needs_pass or doc.page_count != source['page_count']:
                raise ValueError('Pathology source is encrypted or changed')
            proposals, pages = [], []
            for page in doc:
                if len(page.get_text('text').strip()) <= 20:
                    pages.append({'page': page.number + 1, 'status': 'unavailable',
                                  'reasons': ['Image-only/scanned; pathology geometry OCR not validated']})
                    continue
                rows, issues = _page_proposals(page, source_id, digest)
                pages.append({'page': page.number + 1,
                              'status': 'proposed' if rows else 'unparsed', 'reasons': issues})
                proposals.extend(rows)
                if len(proposals) > MAX_PROPOSALS:
                    raise ValueError('Too many pathology proposals: review PDF in smaller files')
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        raise ValueError('Pathology PDF damaged; review original') from exc
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Pathology source changed during extraction')
    return {'schema_version': SCHEMA, 'extractor_version': EXTRACTOR,
            'source_id': source_id, 'source_sha256': digest,
            'records_revision': pathology_records.revision(conn, patient),
            'pages': pages, 'proposals': proposals, 'verification': 'UNVERIFIED',
            'limitations': 'Supported digital-text table headers only; image-only pages unavailable; clinical targets are not inferred'}


def for_source(conn, patient, source_id):
    """Pure read-only proposal path: does not change patient records."""
    return _extract(conn, patient, source_id)


def accept(conn, patient, source_id, body):
    """Revision-checked single-proposal acceptance, always unverified."""
    required = {'proposal_id', 'source_sha256', 'revision', 'fields'}
    if not isinstance(body, dict) or set(body) != required:
        raise ValueError('Invalid pathology proposal acceptance')
    if not isinstance(body['fields'], dict) or set(body['fields']) != {
            'test', 'value', 'unit', 'reference_interval', 'sample_date'}:
        raise ValueError('Invalid accepted pathology fields')
    if not all(isinstance(v, str) and len(v) <= 1000 for v in body['fields'].values()):
        raise ValueError('Invalid accepted pathology field text')
    if not body['fields']['test'].strip() or not body['fields']['value'].strip():
        raise ValueError('Test and result must be entered before acceptance')
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    try:
        response = _extract(conn, patient, source_id)
        if body['source_sha256'] != response['source_sha256']:
            raise ValueError('Source hash changed; regenerate proposals')
        prop = next((x for x in response['proposals'] if x['id'] == body['proposal_id']), None)
        if prop is None:
            raise ValueError('Source proposal is stale; regenerate proposals')
        current = pathology_records.load(conn, patient)
        if body['revision'] != current['revision']:
            raise ValueError('Pathology changed; reload before saving')
        rid = uuid.uuid5(uuid.NAMESPACE_URL, f"hmr-pathology:{patient['id']}:{prop['id']}").hex
        if any(x['id'] == rid for x in current['records']):
            raise ValueError('This source result was already accepted')
        source = next(s for s in pathology_import.sources(conn, patient)['sources']
                      if s['id'] == source_id)
        new_row = {'id': rid, **body['fields'],
                   'source': f"{source['name']} page {prop['page']} sha256:{response['source_sha256']} cell:{prop['id']}",
                   'verified': False,
                   'comment': 'UNVERIFIED PDF proposal; compare original cells before verification'}
        pathology_records.validate(current['records'] + [new_row])
        saved = pathology_records.save(conn, patient,
                                      {'revision': current['revision'], 'records': current['records'] + [new_row]})
        return {'record': new_row, 'records': saved}
    except Exception:
        conn.rollback()
        raise
