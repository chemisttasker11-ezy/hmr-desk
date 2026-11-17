"""Conservative, offline extraction from referral text. All results require checking."""
import re

LABELS = {
    'meds': ('current medications', 'current medication', 'current medication/s', 'medications', 'medication list', 'medicines', 'current medicines', 'current medication as per the patient'),
    'ceased': ('ceased medications', 'medications ceased this admission', 'medication as per the referral ceased or not used'),
    'conditions': ('medical history', 'past medical history', 'active problems', 'current conditions', 'conditions'),
    'allergies': ('allergies', 'allergies/adverse reactions', 'adverse reactions', 'allergies or adverse reactions to medication'),
    'obs': ('measurements', 'observations', 'examination', 'examination findings'),
    'social': ('social history', 'social status'),
    'reason': ('reason for referral', 'reason for referral for dmmr'),
    'renal': ('renal function',),
    'other': ('immunisations', 'vaccinations', 'investigations', 'family history', 'assessment', 'plan', 'patient details', 'doctor details', 'medication administration', 'medication administration devices', 'clinical history', 'other information', 'medical conditions'),
}
_LOOKUP = {v: k for k, names in LABELS.items() for v in names}
DATE = re.compile(r'^(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{4}|(?:19|20)\d{2})$')
STRENGTH = re.compile(r'(?i)(?:\d|[OoIl])\s*(?:mg|mcg|microg|g|ml|units?)(?=\b|/|$)|(?:\d|[OoIl])\s*%')
DIRECTION = re.compile(r'(?i)^(?:[\d??]|[lI](?=\s|/)|take\b|apply\b|use\b|inject\b|inhale\b|as directed\b|once\b|twice\b|one\b|two\b|three\b|daily\b|weekly\b)')
NOISE = re.compile(r'(?i)^(?:page\s+\d+(?:\s+of\s+\d+)?|powered by medical objects|.*\b(?:copyright|medical objects)\b.*)$')

def heading(line):
    label = re.sub(r'\s+', ' ', line.strip().strip(':').strip()).casefold()
    return _LOOKUP.get(label)

def layout(text):
    if re.search(r'(?im)^medical history\s*$', text) and re.search(r'(?im)^current medications\s*$', text):
        return 'clinical summary'
    if re.search(r'(?i)current medication as per the patient|thank you for referring', text):
        return 'past HMR report'  # the pharmacist's own report to the GP, not a referral: never prefilled from
    if re.search(r'(?i)domiciliary medication management|home medication review\s*\(referral\)', text):
        return 'HMR referral form'
    return 'scan / other'

def sections(text):
    result = {}; current = None; page_start = True
    for raw in text.replace('\f', '\n__PAGE_BREAK__\n').splitlines():
        line = raw.strip()
        if line == '__PAGE_BREAK__':
            page_start = True; continue
        if page_start and re.fullmatch(r'\d{1,2}', line):
            page_start = False; continue
        if line: page_start = False
        if not line or NOISE.fullmatch(line) or re.match(r'^.{1,45}\s[-?]\s.{0,3}(?:19|20)\d{2}\s', line):
            continue
        key = heading(line)
        if key:
            current = key
            result.setdefault(key, [])
        elif re.fullmatch(r'[A-Za-z][A-Za-z /&()-]{2,65}:', line):
            if current == 'social' and line.casefold() in ('smoking:', 'alcohol:'):
                result[current].append(line)
            else: current = None
        elif current:
            result[current].append(line)
    return result

def clean(line):
    # Common bullet glyphs from PDF text extraction; keep the class exhaustive
    # for observed variants rather than interpreting document structure.
    return re.sub(r'^[\s\u2022\u25cf\u25a0\u00b7\u2219\u2023\u25aa\u2043*\-]+', '', line).strip()

def medicines(lines, source_rows=None):
    rows = []; leftovers = False
    for raw in lines:
        line = clean(raw)
        if not line or NOISE.fullmatch(line): continue
        if STRENGTH.search(line) and not DIRECTION.match(line):
            strength = STRENGTH.search(line)
            m = re.search(r'\s+(?=(?:take|apply|use|inject|inhale|\d+\s+(?:tablet|capsule|puff))\b)', line[strength.end():], re.I)
            cut = strength.end() + m.start() if m else None
            rows.append([line[:cut].strip(), line[cut:].strip()] if m else [line, ''])
            if source_rows is not None: source_rows.append([raw])
        elif rows and DIRECTION.match(line):
            rows[-1][1] = ' '.join(filter(None, (rows[-1][1], line)))
            if source_rows is not None: source_rows[-1].append(raw)
        elif rows and rows[-1][1] and not rows[-1][1].endswith('.') and not DATE.fullmatch(line) and len(line) < 90 and not re.match(r'(?i)^(?:dr|patient|name|dob|address|phone)\b', line):
            rows[-1][1] += ' ' + line
            if source_rows is not None: source_rows[-1].append(raw)
        else:
            leftovers = True
    return rows, leftovers

def parse(text):
    sec = sections(text)
    result = {'layout': layout(text), 'meds': [], 'ceased': [], 'conditions': [], 'allergies': [], 'obs': {'height': '', 'weight': '', 'bmi': '', 'bp': ''}, 'smoking': '', 'alcohol': '', 'social': '', 'reason': '', 'renal': '', 'unparsed': []}
    if result['layout'] == 'past HMR report': return result
    if result['layout'] == 'scan / other':
        result['unparsed'] = [k for k in sec if k != 'other']
        return result
    result['medicine_source_lines'] = []
    result['meds'], bad = medicines(sec.get('meds', []), result['medicine_source_lines'])
    if 'meds' in sec and (bad or not result['meds']): result['unparsed'].append('meds')
    ceased, bad = medicines(sec.get('ceased', [])); result['ceased'] = [' '.join(filter(None, row)) for row in ceased]
    if 'ceased' in sec and (bad or not ceased): result['unparsed'].append('ceased')
    for key in ('conditions', 'allergies'):
        lines = [clean(x) for x in sec.get(key, []) if not DATE.fullmatch(x) and not NOISE.fullmatch(x)]
        if key == 'allergies' and any(re.fullmatch(r'(?i)(?:nil|none|no(?:ne)? known|nil known|no known allergies|nkda)\.?', x) for x in lines):
            result[key] = ['nil known']
        else:
            result[key] = [x for x in lines if x and len(x) <= 100 and not re.search(r'(?i)\b(?:patient|phone|address|dob|medicare)\s*:', x)]
        if key in sec and len(result[key]) < len(lines): result['unparsed'].append(key)
        if key in sec and not result[key] and key not in result['unparsed']: result['unparsed'].append(key)
    lines = sec.get('obs', [])
    for i, line in enumerate(lines):
        match = re.fullmatch(r'(?i)(height|weight|bmi|bp|blood pressure)\s*:?\s*(.*)', line)
        if not match: continue
        value = match[2] or (lines[i+1] if i+1 < len(lines) else '')
        key = 'bp' if match[1].lower() in ('bp', 'blood pressure') else match[1].lower()
        if re.search(r'\d', value) and not result['obs'][key]: result['obs'][key] = value
    if 'obs' in sec and not any(result['obs'].values()): result['unparsed'].append('obs')
    for i, line in enumerate(lines):
        if re.fullmatch(r'(?i)(?:egfr|e-gfr|creatinine|serum creatinine)\s*:?', line):
            val = lines[i+1] if i+1 < len(lines) else ''
            date = lines[i-1] if i and DATE.fullmatch(lines[i-1]) else ''
            if re.search(r'\d', val): result['renal'] += ('; ' if result['renal'] else '') + ' '.join(filter(None, (line, val, date)))
    for key in ('social', 'reason'):
        if key in sec:
            result[key] = '\n'.join(sec[key]);
            if not result[key]: result['unparsed'].append(key)
    for key in ('smoking', 'alcohol'):
        social_lines = sec.get('social', [])
        for i, line in enumerate(social_lines):
            if re.match(r'(?i)^' + key + r'\s*:', line):
                result[key] = line.split(':',1)[1].strip() or (social_lines[i+1] if i+1 < len(social_lines) else ''); break
    if 'renal' in sec:
        result['renal'] = '\n'.join(sec['renal'])
        if not result['renal']: result['unparsed'].append('renal')
    return result
