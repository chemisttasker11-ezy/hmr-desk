"""Structured tables from the privately supplied Brainstorm reference.

Builds on brainstorm.sections(marker_headings=True): the supplied guide marks
each heading with a coloured square glyph. This module partitions every
section's text into labelled fields. The label vocabulary below was observed
in the supplied V2.0 November 2025 edition; any other colon-led line stays
inside the surrounding field text and is counted in the extraction report,
never dropped or reclassified.

Raw source strings only. No clinical interpretation, validation, currency or
permission is implied by extraction. The reference is a writing guide; the
clinician remains responsible and must check current sources.
"""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

import fitz

import brainstorm

# Label lines observed in the supplied V2.0 (November 2025) edition. Labels
# may appear with a trailing colon ("Suggested Action: ...") or as a bare
# line ("Suggested Action"). Both forms are accepted for these labels only.
KNOWN_LABELS = frozenset({
    'Issue to Consider', 'Suggested Action', 'Reference', 'Clinical Use',
    'Dose in Normal Renal Function', 'Metabolism', 'Dose in RRT',
    'Important Drug Interactions', 'Other Information', 'Clarification',
    'Crushable', 'Alternative', 'Notes for Nurses', 'Purpose', 'Common Error',
    'Real Risk', 'Suggested Fix', 'Audit Prompts', 'Indication', 'Examples',
    'Recommendations Section', 'Haemodialysis', 'Peritoneal dialysis',
    'Immediate-release', 'Dose in Renal Impairment (eGFR)',
})

LABEL_RE = re.compile(r"^([A-Z][A-Za-z0-9 /&'\-()]{1,50}):(?:\s+|$)")

CITATION_VERSION = 1


def parse_fields(text, unknown=None):
    """Partition section text into labelled fields, preserving every line.

    Returns a list of {'label', 'text'} dicts in source order. Text before
    the first label, and sections without labels, keep label ''. Lines that
    look like an unknown label are kept as body text and counted in
    `unknown` when a dict is supplied.
    """
    fields = []
    current = {'label': '', 'lines': []}
    for line in text.split('\n'):
        match = LABEL_RE.match(line)
        bare = line.strip() in KNOWN_LABELS
        if bare or (match and match.group(1) in KNOWN_LABELS):
            fields.append(current)
            current = {'label': line.strip() if bare else match.group(1),
                       'lines': [] if bare else [match.string[match.end():]]}
        else:
            if match and unknown is not None:
                unknown[match.group(1)] = unknown.get(match.group(1), 0) + 1
            current['lines'].append(line)
    fields.append(current)
    return [{'label': f['label'], 'text': '\n'.join(f['lines']).strip()}
            for f in fields if f['label'] or '\n'.join(f['lines']).strip()]


def _canonical(value):
    return ' '.join(str(value).split())


def _entry_digest(entry):
    canonical = json.dumps({'title': entry['title'], 'page_start': entry['page_start'],
                            'page_end': entry['page_end'], 'fields': entry['fields']},
                           ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def extract(pdf_path, edition=''):
    """Extract labelled-entry structure from a supplied reference PDF.

    Provenance: source byte hash, page ranges per entry, and a per-entry
    content digest. `edition` is caller-reviewed (as in reference_library);
    it is never guessed from metadata.
    """
    path = Path(pdf_path)
    content = path.read_bytes()
    pdf_sha256 = hashlib.sha256(content).hexdigest()
    with fitz.open(stream=content, filetype='pdf') as doc:
        page_count = len(doc)
    unknown = {}
    sections = brainstorm.sections(path, marker_headings=True)
    entries = []
    for ordinal, section in enumerate(sections):
        fields = parse_fields(section['text'], unknown)
        entry = {'ordinal': ordinal, 'title': section['title'],
                 'page_start': section['page'], 'page_end': section['page_end'],
                 'fields': fields}
        entry['content_sha256'] = _entry_digest(entry)
        entries.append(entry)
    structure = {
        'citation_version': CITATION_VERSION,
        'source': {'pdf_sha256': pdf_sha256, 'page_count': page_count,
                   'size_bytes': len(content), 'edition': edition},
        'entries': entries,
        'extraction_report': {
            'section_count': len(entries),
            'entries_without_labels': sum(1 for e in entries if not any(f['label'] for f in e['fields'])),
            'unknown_label_lines': dict(sorted(unknown.items())),
        },
    }
    problems = verify(structure, [s['text'] for s in sections])
    structure['extraction_report']['roundtrip_problems'] = problems
    return structure


def verify(structure, section_texts):
    """Exact coverage check: every section's text is fully preserved.

    section_texts are the raw section texts in the same order as the
    structure's entries (titles may repeat across volumes, so pairing is by
    ordinal). Rebuilding each entry as 'Label: text' (or 'Label text' for
    the bare form) plus unlabelled text must reproduce the section text
    after whitespace normalisation; the colon/bare distinction is
    normalised away. Returns a list of problem descriptions; empty means
    exact.
    """
    if structure.get('citation_version') != CITATION_VERSION:
        return ['unsupported citation_version']
    problems = []
    for entry in structure.get('entries', []):
        ordinal = entry.get('ordinal')
        if type(ordinal) is not int or not 0 <= ordinal < len(section_texts):
            problems.append('entry ordinal out of range for ' + repr(entry.get('title')))
            continue
        original = section_texts[ordinal]
        rebuilt = ' '.join((f['label'] + ' ' + f['text']) if f['label'] else f['text']
                           for f in entry['fields'])
        if _canonical(rebuilt.replace(':', ' ')) != _canonical(original.replace(':', ' ')):
            problems.append('text coverage mismatch in ' + repr(entry['title']))
        if _entry_digest(entry) != entry.get('content_sha256'):
            problems.append('content digest mismatch in ' + repr(entry['title']))
    return problems


def to_sqlite(structure, db_path):
    """Write the extracted structure to a private SQLite database.

    Three tables: brainstorm_source, brainstorm_entry, brainstorm_entry_field.
    This is a derived local cache of the user's own registered reference, not
    a distributable knowledge base.
    """
    problems = structure.get('extraction_report', {}).get('roundtrip_problems')
    if problems:
        raise ValueError('refusing to store unverified extraction: ' + '; '.join(problems[:3]))
    source = structure['source']
    db = sqlite3.connect(str(db_path))
    try:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS brainstorm_source(
                pdf_sha256 TEXT PRIMARY KEY,
                edition TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                citation_version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS brainstorm_entry(
                id INTEGER PRIMARY KEY,
                source_sha256 TEXT NOT NULL REFERENCES brainstorm_source(pdf_sha256),
                ordinal INTEGER NOT NULL,
                title TEXT NOT NULL,
                page_start INTEGER NOT NULL,
                page_end INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS brainstorm_entry_field(
                entry_id INTEGER NOT NULL REFERENCES brainstorm_entry(id),
                ordinal INTEGER NOT NULL,
                label TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (entry_id, ordinal));''')
        db.execute('DELETE FROM brainstorm_entry_field WHERE entry_id IN '
                   '(SELECT id FROM brainstorm_entry WHERE source_sha256=?)', (source['pdf_sha256'],))
        db.execute('DELETE FROM brainstorm_entry WHERE source_sha256=?', (source['pdf_sha256'],))
        db.execute('INSERT OR REPLACE INTO brainstorm_source VALUES (?,?,?,?,?)',
                   (source['pdf_sha256'], source['edition'], source['page_count'],
                    source['size_bytes'], structure['citation_version']))
        for entry in structure['entries']:
            cursor = db.execute('INSERT INTO brainstorm_entry(source_sha256,ordinal,title,page_start,page_end,content_sha256) '
                                'VALUES (?,?,?,?,?,?)',
                                (source['pdf_sha256'], entry['ordinal'], entry['title'],
                                 entry['page_start'], entry['page_end'], entry['content_sha256']))
            for ford, field in enumerate(entry['fields']):
                db.execute('INSERT INTO brainstorm_entry_field VALUES (?,?,?,?)',
                           (cursor.lastrowid, ford, field['label'], field['text']))
        db.commit()
    finally:
        db.close()
    return db_path
