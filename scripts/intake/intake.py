import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import fitz
from docx import Document
from openpyxl import Workbook

FIELDS = ('name', 'sex', 'dob', 'medicare', 'irn', 'address', 'suburb', 'phone', 'gp', 'gp_initials', 'gp_provider', 'clinic', 'referral_date')
DATE = r'\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}'


def _completed_report(text):
    """A report date label plus Findings and Recommendations headings. Single words like Assessment or Plan never count:
    genuine referral forms use them as headings."""
    lines = [re.sub(r'\s+', ' ', line).strip().lower() for line in text.splitlines() if line.strip()]
    dated = any(re.match(r'^(?:report date|date of report|date report completed|date of review report)\s*[:\-]', line) for line in lines)
    head = lambda word: any(re.fullmatch(r'(?:\d+[.)]\s*)?(?:summary of |key )?' + word + r'\s*:?', line) for line in lines)
    combined = any(re.fullmatch(r'(?:\d+[.)]\s*)?(?:findings and recommendations|recommendations and findings)\s*:?', line) for line in lines)
    return dated and ((head('findings') and head('recommendations')) or combined)


def _gp_reply_markers(lower):
    return any(x in lower for x in ('gp comments', 'gp response', 'gp feedback', 'feedback on recommendations')) or bool(
        re.search(r'\b(?:your pharmacist|your practice)\b', lower) and re.search(r'\b(?:gp notes|gp comments|feedback)\b', lower))


def classify(text):
    lower = text.lower()
    response = [x for x in ('medication management plan', 'gp feedback', 'gp comments', 'gp response', 'feedback on recommendations') if x in lower]
    if re.search(r'\b(?:plan|feedback)\s*[:|]\s*\S+', lower):
        response.append('filled plan/feedback')
    if re.search(r'\b(?:your pharmacist|your practice)\b', lower) and re.search(r'\b(?:gp notes|gp comments|feedback)\b', lower):
        response.append('review with GP notes')
    for pattern in (r'copy of (?:the )?(?:recent|completed|previous)\s+(?:dmmr|hmr|(?:home medicines |medication )?review)', r'(?:review|assessment|dmmr|hmr)\s+(?:was|has been)\s+(?:already\s+)?completed'):
        match = re.search(pattern, lower)
        if match:
            response.append(match.group())
    referral = [x for x in ('referral', 'request', 'home medicines review', 'medication management review', 'hmr') if x in lower]
    if _completed_report(text) and not _gp_reply_markers(lower):
        # The pharmacist's own finished report quotes the referral reason and lists medicines, so it matches the referral
        # test below. It is neither a referral nor a GP reply: send it to manual review with a plain flag.
        return 'other', referral, ['Looks like a completed HMR report (report date with findings and recommendations), not a referral. Inspect the original PDF']
    if response:
        return 'gp_response', response + referral, []
    if referral and re.search(r'\b(?:patient|dob|date of birth)\b', lower) and re.search(r'\b(?:medications?|medicines?|prescriptions?)\b', lower):
        return 'referral', referral, []
    return 'other', referral, ['Insufficient or conflicting classification signals']


def build_sms(patient, gp, gp_sms, clinic):
    return (
        f"Dear {patient},\n \n"
        f"I am the consultant pharmacist working with Dr {gp} at {clinic}. \n"
        f"Dr {gp_sms} has requested that a Home Medicines Review (HMR) be conducted to ensure your current medications are safe, effective, and continue to meet your health needs.\n \n"
        "This review is a free service funded under Medicare and is designed to optimise your medication therapy, identify any potential side effects or interactions, and support your ongoing treatment plan.\n \n"
        "The review can be conducted in your home or at another convenient location of your choice.\n"
        "Please let me know a suitable time for your appointment. \n"
        "You are also welcome to contact me directly by phone or email if that is more convenient.\n \n"
        "Kind regards,\n"
        "Credentialed Consultant Pharmacist\n"
    )


def extract_fields(text):
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]
    candidates = {key: [] for key in FIELDS}
    flags = []

    def add(key, value):
        if value and value not in candidates[key]:
            candidates[key].append(value)

    def heading(pattern, start=0):
        return next ( (i for i in range(start, len(lines)) if re.fullmatch(pattern, lines[i], re.I)), None)

    def labelled(block, labels):
        pattern = re.compile(r'^(?:' + labels + r')\s*[:#.-]\s*(.*)$', re.I)  # "Provider. 1234567J" on some forms
        for i, line in enumerate(block):
            match = pattern.match(line)
            # OCR also puts a bare label on its own line.
            if not match and re.fullmatch(labels, line, re.I):
                value = ''
            elif match:
                value = match.group(1).strip()
            else:
                continue
            if not value and i + 1 < len(block) and not re.search(r':\s*$', block[i + 1]):
                value = block[i + 1]
            if value:
                yield value

    patient_heading = heading(r'patient(?:\s+details)?\s*:?')
    gp_heading = heading(r'general practitioner(?:\s+details)?\s*:?')
    re_heading = heading(r're\s*:')
    letter = re_heading is not None and patient_heading is None
    patient, gp_block, letterhead = [], [], []
    title_pattern = r'^(?:Mr|Mrs|Ms|Miss|Master)\.?\s+\S+'
    if letter:
        closing = next((i for i in range(re_heading + 1, len(lines)) if re.match(r'^(?:yours sincerely|kind regards|yours faithfully)\b', lines[i], re.I)), len(lines))
        patient = lines[re_heading + 1:closing]
        gp_block = lines[closing + 1:]
        letterhead = lines[:re_heading]
    elif patient_heading is not None and gp_heading is not None and patient_heading < gp_heading < patient_heading + 4:
        # Best Practice prints all three headings before their corresponding blocks.
        starts = [i for i in range(gp_heading + 1, len(lines)) if re.match(title_pattern, lines[i], re.I)]
        if starts:
            first = starts[0]
            second = starts[1] if len(starts) > 1 else None
            doctor = next((i for i in range((second + 1) if second is not None else first + 1, len(lines)) if re.match(r'^Dr\.?\s+', lines[i], re.I)), None)
            patient = lines[first:second if second is not None else (doctor if doctor is not None else len(lines))]
            gp_block = lines[doctor:] if doctor is not None else []
    elif patient_heading is not None:
        end = next((i for i in range(patient_heading + 1, len(lines)) if re.match(r'^(?:community pharmacy|general practitioner|issues that may influence|medical history)', lines[i], re.I)), len(lines))
        patient = lines[patient_heading + 1:end]
        if gp_heading is not None:
            gp_block = lines[gp_heading + 1:patient_heading] if gp_heading < patient_heading else lines[gp_heading + 1:]
    else:
        # A labelled, non-sectioned referral can still identify its patient and GP.
        end = next((i for i, line in enumerate(lines) if re.match(r'^(?:referring\s+)?(?:GP|doctor)\s*:', line, re.I)), len(lines))
        patient, gp_block = lines[:end], lines[end:]
        # OCR may lose section headings but retains titled patient and doctor names.
        patient_start = next((i for i, line in enumerate(lines) if re.search(r'(?i)(?:^|\b(?:name|ame)\s*[:.])\s*(?:Mr|Mrs|Ms|Miss|Master)\.?\s+', line)), None)
        doctor_start = next((i for i, line in enumerate(lines) if re.match(r'(?i)^(?:name\s*[:.]\s*)?Dr\.?\s+\S+', line)), None)
        if patient_start is not None and doctor_start is not None:
            patient_end = next((i for i in range(patient_start + 1, len(lines)) if i == doctor_start or re.match(r'(?i)^(?:patient/carer|atien.y?carer|issues that|current medication|medical history)', lines[i])), len(lines))
            patient = lines[patient_start:patient_end]
            gp_end = next((i for i in range(doctor_start + 1, len(lines)) if i == patient_start or re.match(r'(?i)^(?:preferred|patient/carer|atien.y?carer|issues that|current medication|medical history)', lines[i])), len(lines))
            gp_block = lines[doctor_start:gp_end]
            if doctor_start < patient_start:
                tail_end = next((i for i in range(patient_end, len(lines)) if re.match(r'(?i)^(?:preferred|issues that|current medication|medical history)', lines[i])), len(lines))
                gp_block += lines[patient_end:tail_end]

    for i, line in enumerate(gp_block):
        if re.match(r'(?i)^(?:timing for the pharmacist|medical history|current medications?|relevant (?:progress|pathology)|allergies)', line):
            gp_block = gp_block[:i]
            break
    names = list(labelled(patient, r'patient(?:\s+name)?|name|ame'))
    if not names:  # "RE: Mrs Jane Doe." lines and scans with clipped labels ("ame: Mrs ...")
        names = [m.group(1).rstrip('. ') for m in (re.search(r'\b((?:Mr|Mrs|Ms|Miss|Master)\.?\s+[A-Za-z].*)$', line) for line in patient) if m][:1]
    for line in lines:
        match = re.search(r'(?i)arranged to conduct a DMMR for\s+((?:Mr|Mrs|Ms|Miss|Master)\.?\s+[A-Za-z][A-Za-z\' -]+?)\s+on\b', line)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    for value in names:
        match = re.fullmatch(r'(?:(Mr|Mrs|Ms|Miss|Master|Dr)\.?\s+)?([A-Za-z][A-Za-z\' -]*\s+[A-Za-z][A-Za-z\' -]*)', value, re.I)
        if match and not re.search(r'\b(?:pharmacy|pharmacist|Consultant Pharmacist|your practice)\b', match.group(2), re.I):
            add('name', person_case(match.group(2).strip()))
            # The title is not evidence of sex, so sex is left blank for the pharmacist to enter from a source.
    for value in labelled(patient, r'D?\.?O\.?B\.?|date of birth|birth date'):
        match = re.search(DATE, value)
        if match:
            add('dob', normal_date(match.group()))
    if not candidates['dob']:  # clipped/garbled DOB label: use the patient block's only pre-2010 date
        old = {normal_date(m.group()) for line in patient for m in re.finditer(DATE, line) if re.search(r'(?:19\d\d|200\d)$', m.group())}
        if len(old) == 1:
            add('dob', old.pop())
    for value in labelled(patient, r'(?:medicare|ledicare)(?:\s+(?:no|number)\.?)?'):
        match = re.search(r'(?<!\d)((?:\d[ -]*){10})(?:\s*[/ -]?\s*([0-9lI]))?(?!\d)', value)
        if match:
            add('medicare', re.sub(r'\D', '', match.group(1)))
            if match.group(2):
                add('irn', match.group(2).replace('l', '1').replace('I', '1'))
    for line in patient:
        for match in re.finditer(r'(?i)\b(?:IRN|line\s*(?:no|number)\.?)\s*[:#.-]\s*([0-9lI])\b', line):
            add('irn', match.group(1).replace('l', '1').replace('I', '1'))
    for value in labelled(patient, r'IRN|line\s*(?:no|number)'):
        match = re.match(r'([0-9lI])\b', value)
        if match:
            add('irn', match.group(1).replace('l', '1').replace('I', '1'))
    addresses = list(labelled(patient, r'address|ddress|street address'))
    if not addresses and patient and re.match(title_pattern, patient[0], re.I) and len(patient) > 1 and re.match(r'^(?:\d|(?:U|Unit|Lot)\s*\d)', patient[1], re.I):
        addresses = [patient[1]]
    for address in addresses:
        add('address', address.title())
    for i, line in enumerate(patient):
        match = re.fullmatch(r'([A-Za-z][A-Za-z -]*?)\s+(?:(?:QLD|NSW|VIC|SA|WA|TAS|NT|ACT)\s+)?(\d{4})', line, re.I)
        reverse = re.fullmatch(r'(\d{4})\s+([A-Za-z][A-Za-z -]*)', line, re.I)
        if match:
            add('suburb', match.group(2) + ' ' + match.group(1).strip().title())
        elif reverse:
            add('suburb', reverse.group(1) + ' ' + reverse.group(2).strip().title())
        elif re.fullmatch(r'\d{4}', line) and i and re.fullmatch(r'[A-Za-z][A-Za-z -]*', patient[i - 1]):
            add('suburb', line + ' ' + patient[i - 1].title())
    phones = []
    for i, line in enumerate(patient):
        if re.search(r'\b(?:fax|clinic|practice|surgery)\b', line, re.I):
            continue
        for match in re.finditer(r'(?<!\d)(?:\+?61[ -]?)?0?[47](?:[ ()-]*\d){8}(?!\d)', line):
            digits = re.sub(r'\D', '', match.group())
            if digits.startswith('61'):
                digits = '0' + digits[2:]
            if len(digits) == 10:
                number = f'{digits[:4]} {digits[4:7]} {digits[7:]}' if digits.startswith('04') else f'{digits[:2]} {digits[2:6]} {digits[6:]}'
                label = line if re.search(r'\b(?:mob(?:ile)?|phone|telephone)\b', line, re.I) else (patient[i - 1] if i else '')
                phones.append((number, bool(re.search(r'\bmob(?:ile)?\b', label, re.I))))
    phones.sort(key=lambda item: (not item[0].startswith('04'), not item[1]))
    for number, _ in phones:
        add('phone', number)
    if phones and not any(re.search(r'\b(?:phone|telephone|mob(?:ile)?)\b', line, re.I) for line in patient):
        flags.append('Phone attribution uncertain; check by hand')
    gp_names = list(labelled(gp_block, r'name|(?:referring\s+)?(?:GP|doctor)'))
    if not gp_names:
        gp_names = [line for line in gp_block if re.fullmatch(r'Dr\.?\s+[A-Za-z][A-Za-z\' .-]+', line, re.I)]
        if letter:
            gp_names = gp_names[:1]
    for value in gp_names:
        value = re.sub(r'^Dr\.?\s+', '', value, flags=re.I).strip().rstrip('.,;:')
        if re.fullmatch(r'[A-Za-z][A-Za-z\' .-]*\s+[A-Za-z][A-Za-z\' .-]*', value) and not re.search(r'\b(?:pharmacy|pharmacist|Consultant Pharmacist|your practice)\b', value, re.I):
            add('gp', person_case(value))
    for gp in candidates['gp']:
        add('gp_initials', ''.join(part[0].upper() for part in gp.split()))
    for value in labelled(gp_block, r'provider(?:\s+(?:no|number))?'):
        match = re.search(r'\b\d{6,7}[A-Za-z]+\b', value)
        if match:
            add('gp_provider', match.group().upper())
    if letter and candidates['gp']:
        for gp in candidates['gp']:
            pattern = r'\bDr\.?\s+' + r'\s+'.join(re.escape(part) for part in gp.split()) + r'\s+(\d{6,7}[A-Za-z]+)\b'
            for line in letterhead:
                for match in re.finditer(pattern, line, re.I):
                    add('gp_provider', match.group(1).upper())
    try:
        clinics = json.loads(Path(__file__).with_name('gp_clinics.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        clinics = {}
    def gp_key(name):
        words = name.casefold().replace('.', '').split()
        return ' '.join(word for i, word in enumerate(words) if i in (0, len(words) - 1) or len(word) > 1)
    for gp in candidates['gp']:
        for name, clinic in clinics.items():
            if gp_key(gp) == gp_key(name):
                add('clinic', clinic)
    if not candidates['clinic'] and letter and letterhead and re.search(r'\b(?:practice|medical|clinic|surgery|health|doctors?)\b', letterhead[0], re.I):
        add('clinic', letterhead[0])
    if not candidates['clinic']:
        flags.append('Clinic unknown: add to gp_clinics.json')
    dates = []
    for value in labelled(lines, r'(?:referral|request|letter)\s+date|date'):
        match = re.search(DATE, value)
        if match:
            dates.append(normal_date(match.group()))
    if not dates:
        limit = re_heading if letter else (patient_heading if patient_heading is not None else 0)
        dates = [normal_date(line) for line in lines[:limit] if re.fullmatch(DATE, line)]
    for value in dates:
        add('referral_date', value)
    fields = {}
    for key, values in candidates.items():
        fields[key] = values[0] if values else None
        if not values and key != 'irn':
            flags.append(f'Missing {key}')
        elif len(values) > 1:
            flags.append(f'Multiple candidates for {key}: ' + ', '.join(values))
    if not fields['gp'] or not fields['clinic'] or not fields['name']:
        flags.append('SMS unavailable: missing patient, GP or clinic')
    return fields, flags


def person_case(name):
    # Title-case only words written all upper or all lower, so "McNamara" keeps its capital N.
    return ' '.join(w.title() if w.isupper() or w.islower() else w for w in name.split())


def normal_date(value):
    parts = re.split(r'[/.\-]', value)
    return f'{int(parts[0]):02d}/{int(parts[1]):02d}/{parts[2]}'


def ocr_pdfs(paths):
    if not paths:
        return {}
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
        listing = Path(temp) / 'paths.txt'
        listing.write_text('\n'.join(str(p) for p in paths), encoding='utf-8-sig')
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(Path(__file__).with_name('ocr_pdf.ps1')), '-List', str(listing), '-Out', temp], check=True, stdout=subprocess.DEVNULL)
        return json.loads((Path(temp) / 'ocr.json').read_text(encoding='utf-8-sig'))


def known_patients(base, name):
    if not name or len(name.split()) < 2:
        return []
    first, last = name.split()[0].casefold(), name.split()[-1].casefold()
    matches = []
    for folder in ('on Excel', 'Scheduled', 'Visited', 'Declined-Exp', 'Completed & Claimed', 'To CLAIM'):
        root = base / folder
        if root.is_dir():
            for current, dirs, files in os.walk(root):
                for entry in dirs + files:
                    if first in entry.casefold() and last in entry.casefold():
                        matches.append(str((Path(current) / entry).relative_to(base)))
    return sorted(matches)


def target_name(name, initials, extension):
    return re.sub(r'[<>:"/\\|?*]', '', f'{name}_ {initials}{extension}').rstrip(' .')


def move_file(source, target):
    created = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents overwriting even if a target appears concurrently.
        with open(target, 'xb') as output:
            created = True
            with open(source, 'rb') as input_file:
                shutil.copyfileobj(input_file, output)
        source.unlink()
        return 'moved'
    except FileExistsError:
        return 'target exists'
    except OSError as exc:
        if created:
            try:
                target.unlink()
            except OSError:
                pass
        return f'move failed: {exc}'


def flag_same_patients(records):
    """Several referrals for one patient: the latest goes on the sheet, older ones are marked and left off."""
    def age(record):
        d = (record['fields'] or {}).get('referral_date') or '00/00/0000'
        return d[6:] + d[3:5] + d[:2], record['file']  # BP file names grow with send time
    for record in records:
        name = (record.get('fields') or {}).get('name')
        if not name:
            continue
        same = [r for r in records if r is not record and ((r.get('fields') or {}).get('name') or '').casefold() == name.casefold()]
        if same:
            latest = max(same + [record], key=age)
            record['older'] = latest is not record
            record['flags'].append(f'Older referral, not on sheet; latest is {latest["file"]}' if record['older'] else 'Latest of several referrals: ' + ', '.join(r['file'] for r in same))


def apply_corrections(record, fix):
    """Fields the user corrected by hand (intake_corrections.json) replace extracted ones and clear their flags."""
    f = record['fields']
    for key, value in fix.items():
        if key == 'notes':
            record['flags'].append(value)
            continue
        f[key] = value
        record['flags'] = [x for x in record['flags'] if not re.match(rf'(?:Missing|Multiple candidates for) {key}\b', x)]
        if key == 'phone':
            record['flags'] = [x for x in record['flags'] if not x.startswith('Phone attribution')]
        if key == 'gp':
            f['gp_initials'] = ''.join(p[0].upper() for p in value.split())
            record['flags'] = [x for x in record['flags'] if 'gp_initials' not in x]
    if f.get('ihi'):
        record['flags'] = [x for x in record['flags'] if x != 'Missing medicare']
    if f.get('name') and f.get('gp') and f.get('clinic'):
        record['flags'] = [x for x in record['flags'] if not x.startswith(('SMS unavailable', 'Clinic unknown'))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--out', type=Path, help='report output folder (default: input folder)')
    args = parser.parse_args()
    folder = args.folder.resolve()
    # Files already named "<Name>_ <GP initials>" were processed in an earlier run.
    paths = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith('~$') and p.suffix.lower() in ('.pdf', '.docx', '.doc') and not re.search(r'_ [A-Z]{1,4}$', p.stem))
    pages, errors, needs_ocr = {}, {}, []
    for path in paths:
        try:
            if path.suffix.lower() == '.pdf':
                with fitz.open(path) as doc:
                    pages[path] = [page.get_text() for page in doc]
                if any(len(page.strip()) < 200 for page in pages[path]):
                    needs_ocr.append(path)
            elif path.suffix.lower() == '.doc':  # old Word format: let Word export it to PDF, read-only
                with tempfile.TemporaryDirectory() as temp:
                    pdf = Path(temp) / 'doc.pdf'
                    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(Path(__file__).with_name('word2pdf.ps1')), str(path), str(pdf)], check=True, capture_output=True, timeout=120)
                    with fitz.open(pdf) as doc:
                        pages[path] = [page.get_text() for page in doc]
            elif path.suffix.lower() == '.docx':
                doc = Document(path)
                pages[path] = ['\n'.join([p.text for p in doc.paragraphs] + [cell.text for table in doc.tables for row in table.rows for cell in row.cells])]
        except Exception as exc:
            errors[path] = f'Read failed: {exc}'
    try:
        ocr = ocr_pdfs(needs_ocr)
    except Exception as exc:
        ocr = {}
        for path in needs_ocr:
            errors[path] = f'OCR failed: {exc}'
    corrections_file = folder / 'intake_corrections.json'
    corrections = json.loads(corrections_file.read_text(encoding='utf-8')) if corrections_file.exists() else {}
    records = []
    for path in paths:
        flags = []
        if path in errors:
            kind, keywords, flags = 'other', [], [errors[path]]
        else:
            texts = pages[path]
            if path in needs_ocr:
                scanned = ocr.get(str(path), [])
                if len(scanned) != len(texts):
                    kind, keywords, flags = 'other', [], ['OCR output missing pages; check by hand']
                else:
                    texts = [text if len(text.strip()) >= 200 else scanned[i] for i, text in enumerate(texts)]
            if not flags:
                kind, keywords, flags = classify('\n'.join(texts))
        record = dict(file=path.name, kind=kind, keywords=keywords, fields=None, flags=flags, known=[], planned=None, applied=None)
        if kind == 'referral':
            record['fields'], more = extract_fields('\n'.join(texts[:3]))
            flags.extend(more)
            f = record['fields']
            whole = '\n'.join(texts)
            ihi = re.search(r'\bIHI\b\D{0,12}((?:\d[ -]?){16})', whole)
            f['ihi'] = re.sub(r'\D', '', ihi.group(1)) if ihi else None
            if not f['phone']:  # attached results repeat the patient's mobile on every page
                mobiles = [re.sub(r'\D', '', m) for m in re.findall(r'(?<!\d)04\d{2}[ ]?\d{3}[ ]?\d{3}(?!\d)', whole)]
                if mobiles:
                    top = max(set(mobiles), key=mobiles.count)
                    f['phone'] = f'{top[:4]} {top[4:7]} {top[7:]}'
                    flags[:] = [x for x in flags if x != 'Missing phone'] + ['Phone from attached pages']
            if not f['referral_date']:  # some forms date only the GP signature, on a later page
                signed = re.search(r'(?i)signature[^\n]*?(?:\n[^\n]*?)?date\s*:\s*(' + DATE + ')', whole)
                if signed:
                    f['referral_date'] = normal_date(signed.group(1))
                    flags[:] = [x for x in flags if x != 'Missing referral_date'] + ['Referral date from GP signature']
            fix = corrections.get(path.name)
            if fix:
                record['flags'] = flags
                apply_corrections(record, fix)
                flags = record['flags']
            record['known'] = known_patients(folder.parent, f['name'])
            if record['known']:
                # Still approached as a new referral; the history goes in the Notes column.
                tops = [k for k in record['known'] if not any(k.startswith(o + os.sep) for o in record['known'])]
                flags.append('Seen before: ' + '; '.join(tops))
            if f['name'] and f['gp_initials'] and not any(x.startswith(('Multiple candidates for name:', 'Multiple candidates for gp:', 'Multiple candidates for gp_initials:')) for x in flags):
                # Renamed in place; it moves to "on Excel" only after its first SMS is sent.
                record['planned'] = str(folder / target_name(f['name'], f['gp_initials'], path.suffix))
            else:
                flags.append('Cannot rename: missing or ambiguous name or GP initials')
        elif kind == 'gp_response':
            name = extract_fields('\n'.join(texts[:3]))[0]['name']
            record['planned'] = str(folder / 'FEEDBACK' / (target_name(name, 'GP response', path.suffix) if name else path.name))
            if not name:
                flags.append('Patient name not found: moved with its original name')
        records.append(record)
    flag_same_patients(records)
    if args.apply:
        for record in records:
            if record['planned']:
                outcome = move_file(folder / record['file'], Path(record['planned']))
                record['applied'] = outcome
                if outcome != 'moved':
                    record['flags'].append(outcome)
            else:
                record['applied'] = 'left in place'
    stamp = date.today().strftime('%d-%m-%Y')
    # PPA claim fields filled later in the same row; consent is always held (user, 2026-11-09).
    CLAIM_COLUMNS = ['Report Sent Date', 'Referral Reason', 'Outcome', 'Outcome Other', 'Consent', 'Claimed']
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'New Patients ' + stamp
    sheet.append(['Name', 'Suburb', 'Address', 'Number', 'Appointment', 'Dr Name', 'Referral Date', 'Status', 'Notes', 'Interview Date', 'SMS', 'DOB', 'Sex', 'Medicare', 'IRN', 'IHI', 'Clinic', 'Provider No', 'Source file'] + CLAIM_COLUMNS)
    for record in records:
        if record['kind'] != 'referral' or record.get('older'):
            continue
        f = record['fields']
        sms = build_sms(f['name'], f['gp'], f['gp'].split()[-1], f['clinic']) if f['name'] and f['gp'] and f['clinic'] else ''
        sheet.append([f['name'], f['suburb'], f['address'], f['phone'], '', f['gp'], f['referral_date'], '', '; '.join(record['flags']), '', sms, f['dob'], f['sex'], f['medicare'], f['irn'], f.get('ihi'), f['clinic'], f['gp_provider'], record['file'], '', '', '', '', 'Yes', ''])
    for row in sheet:
        for cell in row:
            cell.number_format = '@'
            if cell.value is not None:
                cell.value = str(cell.value)
    out = args.out if args.out is not None else folder
    workbook.save(out / f'intake_rows_{stamp}.xlsx')
    (out / f'intake_report_{stamp}.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(', '.join(f'{kind}: {sum(r["kind"] == kind for r in records)}' for kind in ('referral', 'gp_response', 'other')))
    for record in records:
        if record['flags']:
            print(f'{record["file"]}: {record["kind"]}: ' + '; '.join(record['flags']))


if __name__ == '__main__':
    main()
