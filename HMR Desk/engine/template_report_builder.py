"""Template-bound, deterministic HMR DOCX rendering; never creates its own layout.

The owner-approved DOCX must supply placeholders and established layout. A
checksum-bound approval manifest prevents accidentally using unrelated patient
reports or a developer example as the clinical template. This module contains
no drug rules and performs no clinical assertion generation.
"""
import hashlib
import datetime as dt
import os
import shutil
import uuid
import json
import re
from pathlib import Path

from copy import deepcopy

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.shared import Emu

TEXT_FIELDS = {
    'ASSESS_DATE': 'assess_date', 'REPORT_DATE': 'report_date',
    'PATIENT': 'patient', 'DOCTOR': 'doctor', 'DEAR': 'dear',
    'THANKS': 'thanks', 'REASON': 'reason', 'INTRO': 'intro',
    'CONDITIONS': 'conditions', 'ALLERGIES': 'allergies',
    'OBS': 'obs', 'FOLLOWUP': 'followup',
}
# Optional text markers: filled when present in the approved layout, never required.
OPTIONAL_TEXT_FIELDS = {'PATIENT_NAME': 'patient_name', 'PATH_DATE': 'path_date', 'INTERACTION_SCOPE': 'interaction_scope_note',
                        'PHARMACIST': 'pharmacist_details'}
ISSUES_END = '{{HMR_ISSUES_END}}'
LINE_PROTO = '{{HMR_LINE}}'
ISSUE_FIELDS = {
    '{{HMR_ISSUE_TITLE}}': lambda n, f: str(n) + '. ' + f['title'],
    '{{HMR_ISSUE_REC}}': lambda n, f: f['rec'],
    '{{HMR_ISSUE_RATIONALE}}': lambda n, f: f['rationale'],
}
TABLE_FIELDS = {
    'MEDS_TABLE': ('meds', ('Medicine', 'Actual use', 'Notes', 'Review')),
    'OTC_TABLE': ('otc', ('Medicine', 'Use', 'Notes')),
    'CEASED_TABLE': ('ceased', ('Medicine', 'Referral directions', 'Notes')),
    'PATH_TABLE': ('path', ('Test', 'Result', 'Unit', 'Reference range', 'Source / notes')),
}
ISSUES_ANCHOR = '{{HMR_ISSUES}}'
MARKER = re.compile(r'\{\{HMR_[A-Z_]+\}\}')


def active_template_root():
    """User-approved template supersedes read-only bundle, never a patient report."""
    import app_paths
    import db
    local = Path(db.DATA_DIR) / 'templates'
    if (local.joinpath('approved-hmr.docx').exists() or local.joinpath('approved-hmr.json').exists()):
        return local
    return app_paths.engine_assets() / 'templates'


def validate_layout(template):
    """Require complete named placeholders before accepting a new owner template."""
    doc = Document(template)
    occurrences = {}
    for paragraph in _paragraphs(doc):
        for marker in MARKER.findall(paragraph.text):
            occurrences[marker] = occurrences.get(marker, 0) + 1
    required = {'{{HMR_' + key + '}}' for key in TEXT_FIELDS} | {
        '{{HMR_' + key + '}}' for key in TABLE_FIELDS} | {ISSUES_ANCHOR}
    missing = required - occurrences.keys()
    if missing:
        raise ValueError('Template needs the following HMR placeholders: ' + ', '.join(sorted(missing)))
    for marker in TABLE_FIELDS:
        name = '{{HMR_' + marker + '}}'
        if occurrences[name] != 1:
            raise ValueError('Table placeholder must occur exactly once: ' + name)
    if occurrences[ISSUES_ANCHOR] != 1:
        raise ValueError('HMR_ISSUES placeholder must occur exactly once')
    if ISSUES_END in occurrences:
        _require_finding_fields(''.join(p.text + '\n' for p in _paragraphs_between(doc)))
    return True


def _require_finding_fields(text):
    missing = [m for m in ISSUE_FIELDS if m not in text]
    if missing:
        raise ValueError('The finding block must contain ' + ', '.join(ISSUE_FIELDS) + '; missing: ' + ', '.join(missing))


def _paragraphs_between(doc):
    inside = False
    for paragraph in _paragraphs(doc):
        text = paragraph.text.strip()
        if text == ISSUES_ANCHOR:
            inside = True
        elif text == ISSUES_END:
            return
        elif inside:
            yield paragraph


def register(source_path, version, approved_by, owner_authorised):
    """Local-only owner-authorised template installation with revision history."""
    import db
    if owner_authorised is not True:
        raise ValueError('Explicit owner authorisation and permission to use template required')
    if not isinstance(version, str) or not 1 <= len(version.strip()) <= 80:
        raise ValueError('Template version is required')
    if not isinstance(approved_by, str) or not 3 <= len(approved_by.strip()) <= 150:
        raise ValueError('Approving owner name is required')
    source = Path(source_path)
    if not source.is_absolute() or source.is_symlink() or not source.is_file() or source.suffix.lower() != '.docx':
        raise ValueError('Select an editable regular HMR DOCX template')
    if source.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('Template is too large')
    validate_layout(source)
    original = source.read_bytes()
    sha = hashlib.sha256(original).hexdigest()
    template_dir = Path(db.DATA_DIR) / 'templates'
    template_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if template_dir.is_symlink():
        raise ValueError('Unsafe template folder')
    active = template_dir / 'approved-hmr.docx'
    manifest = template_dir / 'approved-hmr.json'
    old_template = active.read_bytes() if active.is_file() else None
    old_meta = manifest.read_bytes() if manifest.is_file() else None
    if old_template is not None and old_meta is not None:
        history = template_dir / 'history'
        history.mkdir(mode=0o700, exist_ok=True)
        old_sha = hashlib.sha256(old_template).hexdigest()
        prior = history / (old_sha + '.docx')
        prior_meta = history / (old_sha + '.json')
        if not prior.exists():
            prior.write_bytes(old_template)
        if not prior_meta.exists():
            prior_meta.write_bytes(old_meta)
    info = {
        'version': version.strip(), 'sha256': sha, 'approved_by': approved_by.strip(),
        'approved_on': dt.date.today().isoformat(),
        'approved_for': 'HMR Desk manual AI-off report layout',
        'approval_method': 'explicit local owner attestation; external release sign-off still required',
    }
    token = uuid.uuid4().hex
    pending_doc = template_dir / ('.approved-' + token + '.docx')
    pending_json = template_dir / ('.approved-' + token + '.json')
    try:
        with pending_doc.open('xb') as file:
            file.write(original)
            file.flush()
            os.fsync(file.fileno())
        with pending_json.open('x', encoding='utf-8') as file:
            json.dump(info, file, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        if hashlib.sha256(pending_doc.read_bytes()).hexdigest() != sha:
            raise ValueError('Template changed while being copied')
        validate_layout(pending_doc)
        os.replace(pending_doc, active)
        os.replace(pending_json, manifest)
        approved_template(template_dir)
    finally:
        pending_doc.unlink(missing_ok=True)
        pending_json.unlink(missing_ok=True)
    return {'registered': True, 'version': info['version'], 'sha256': sha,
            'approved_by': info['approved_by'], 'previous_version_preserved': old_template is not None}


def approved_template(root):
    """An explicit owner approval record is essential; no guessing from case files."""
    root = Path(root)
    template = root / 'approved-hmr.docx'
    manifest = root / 'approved-hmr.json'
    if not template.is_file() or not manifest.is_file():
        raise FileNotFoundError('Owner-approved HMR DOCX template and manifest are not installed')
    info = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(info, dict) or not all(
        isinstance(info.get(k), str) and info[k].strip()
        for k in ('version', 'sha256', 'approved_by', 'approved_on')
    ):
        raise ValueError('HMR template approval manifest is incomplete')
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    if not re.fullmatch(r'[a-f0-9]{64}', info['sha256']) or digest != info['sha256']:
        raise ValueError('HMR template checksum mismatch; cannot use an unapproved layout')
    return template, info


def _paragraphs(doc):
    """Yield all paragraphs including body, tables, headers and footers."""
    def from_table(table):
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p
                for nested in cell.tables:
                    yield from from_table(nested)
    for p in doc.paragraphs:
        yield p
    for table in doc.tables:
        yield from from_table(table)
    for section in doc.sections:
        for part in (section.header, section.footer):
            for p in part.paragraphs:
                yield p
            for table in part.tables:
                yield from from_table(table)


def _paragraphs_in_table(table):
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                yield paragraph
            for nested in cell.tables:
                yield from _paragraphs_in_table(nested)


def _set_text(paragraph, text):
    # Keep original paragraph and first-run formatting, not default document style.
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ''
    else:
        paragraph.add_run(text)


def _apply_owner_table_format(doc, table):
    """Legacy path (no prototype table in the template): reuse a named table style.

    Only a table with an explicit named style (not the default "Normal Table") counts as
    the owner's table format. Layout tables such as a title banner carry no such style, so
    they are never copied. A template with a prototype table at the marker uses
    `_fill_prototype_table` instead, which keeps header and row formatting exactly.
    """
    existing = [t for t in doc.tables if t._tbl is not table._tbl]
    named = [t for t in existing if t.style is not None and t.style.name not in ('Normal Table', 'Normal')]
    if named:
        table.style = named[0].style
        return 'template-style'
    try:
        table.style = 'Table Grid'
    except KeyError:
        return 'none'
    return 'fallback-grid'


def _set_cell_text(cell, text):
    """Replace a cell's text, keeping the first paragraph and its first run formatting."""
    paragraphs = cell.paragraphs
    for extra in paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    _set_text(paragraphs[0], text)


def _paginate_rows(table):
    """Repeat the header row on each page and keep every row whole (idempotent; adds only what is missing)."""
    for index, row in enumerate(table.rows):
        properties = row._tr.get_or_add_trPr()
        wanted = ['cantSplit'] + (['tblHeader'] if index == 0 else [])
        for name in wanted:
            if properties.find(qn('w:' + name)) is None:
                properties.append(OxmlElement('w:' + name))


def _adapt_gp_plan_prototype(table, include_gp_plan):
    """Adjust only the optional trailing GP Plan column; preserve the template and other report fields.

    When adding the column, take its width from the existing table rather than expanding
    beyond the page. The source DOCX is never modified; the pharmacist reviews the
    resulting Word/PDF before clinical sign-off.
    """
    count = len(table.columns)
    if include_gp_plan and count == 4:
        original = [int(col.width or Emu(800000)) for col in table.columns]
        total = sum(original)
        extra = max(1, total // 6)
        table.autofit = False
        for col, width in zip(table.columns, original):
            col.width = Emu(max(1, round(width * (total - extra) / total)))
        table.add_column(Emu(extra))
        for row in table.rows:
            new_cell, source_cell = row.cells[-1], row.cells[-2]
            if source_cell._tc.tcPr is not None:
                old_props = new_cell._tc.tcPr
                if old_props is not None:
                    new_cell._tc.remove(old_props)
                new_cell._tc.insert(0, deepcopy(source_cell._tc.tcPr))
            for cell, col in zip(row.cells, table.columns):
                cell.width = col.width
        _set_cell_text(table.rows[0].cells[-1], 'GP Plan')
    elif not include_gp_plan and count == 5:
        # Remove only a clearly labelled GP Plan column. Never discard an unrelated
        # fifth column from an approved template.
        if not table.rows or ''.join(table.rows[0].cells[-1].text.casefold().split()) not in ('gpplan', 'gpplan/feedback'):
            raise ValueError('Five-column owner template must label its last column GP Plan to turn it off')
        for row in table.rows:
            row._tr.remove(row.cells[-1]._tc)
        table._tbl.tblGrid.remove(table._tbl.tblGrid[-1])
    elif count not in (4, 5):
        raise ValueError('Owner medication table needs four columns or a fifth GP Plan column')


def _fill_prototype_table(prototype, rows, labels):
    """Clone the template's own header and sample row; keep its shading, borders, fonts."""
    if len(prototype.rows) < 2:
        raise ValueError('Prototype table needs a header row and one sample data row')
    if len(prototype.columns) != len(labels):
        raise ValueError('Prototype table has %d columns; this report needs %d' % (len(prototype.columns), len(labels)))
    sample = prototype.rows[1]._tr
    for values in rows:
        if len(values) != len(labels):
            raise ValueError('Report row does not match the table columns')
        clone = deepcopy(sample)
        prototype._tbl.append(clone)
        row = prototype.rows[-1]
        for cell, value in zip(row.cells, values):
            _set_cell_text(cell, str(value))
    for old in list(prototype.rows)[1:len(prototype.rows) - len(rows)]:
        prototype._tbl.remove(old._tr)
    _paginate_rows(prototype)


def _table(doc, rows, labels):
    table = doc.add_table(rows=1, cols=len(labels))
    _apply_owner_table_format(doc, table)
    for cell, label in zip(table.rows[0].cells, labels):
        cell.text = label
    for values in rows:
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    _paginate_rows(table)
    return table


def has_marker(template, name):
    """True when the approved layout carries the optional {{HMR_<name>}} placeholder."""
    marker = '{{HMR_' + name + '}}'
    return any(marker in p.text for p in _paragraphs(Document(Path(template))))


def render(data, target, template, include_gp_plan=False):
    """Fill approved layout in place, preserving letterhead, margins and footer."""
    target, template = Path(target), Path(template)
    if target.exists():
        raise FileExistsError('Never overwrite existing or signed HMR report')
    doc = Document(template)
    occurrences = {}
    all_paragraphs = list(_paragraphs(doc))
    note = data.get('interaction_scope_note', '')
    if isinstance(note, str) and note.strip() and not any('{{HMR_INTERACTION_SCOPE}}' in p.text for p in all_paragraphs):
        # The approved layout has no marker for the interaction scope. Never drop the warning and never change the
        # layout: it is appended to the intro paragraph (same formatting), which sits above the medicine tables.
        data = dict(data, intro=(data.get('intro', '').rstrip() + '\n\n' if data.get('intro', '').strip() else '') + note)
    for paragraph in all_paragraphs:
        original = paragraph.text
        matches = list(MARKER.finditer(original))
        if not matches:
            continue
        for match in matches:
            marker = match.group(0)
            occurrences[marker] = occurrences.get(marker, 0) + 1
        changed = original
        for marker in {m.group(0) for m in matches}:
            name = marker[len('{{HMR_'):-2]
            if name in OPTIONAL_TEXT_FIELDS:
                default = str(data.get('patient', '')).split('\n')[0] if name == 'PATIENT_NAME' else ''
                value = data.get(OPTIONAL_TEXT_FIELDS[name], default)
                if not isinstance(value, str):
                    raise ValueError('Invalid text field in report data')
                changed = changed.replace(marker, value)
            elif name in TEXT_FIELDS:
                value = data.get(TEXT_FIELDS[name], '')
                if not isinstance(value, str):
                    raise ValueError('Invalid text field in report data')
                changed = changed.replace(marker, value)
        if changed != original:
            nxt = paragraph._p.getnext()
            if (paragraph._p.getparent().tag.endswith('}tc') and nxt is not None and nxt.tag.endswith('}p')
                    and ''.join(nxt.xpath('.//w:t/text()')).strip() == LINE_PROTO):
                # The approved cell carries a line prototype: first line keeps this paragraph's
                # formatting, every further line is a clone of the prototype paragraph.
                lines = changed.split('\n')
                _set_text(paragraph, lines[0])
                for line in lines[1:]:
                    clone = deepcopy(nxt)
                    nxt.addprevious(clone)
                    _set_text(Paragraph(clone, paragraph._parent), line)
                nxt.getparent().remove(nxt)
            else:
                _set_text(paragraph, changed)
    for name, (key, labels) in TABLE_FIELDS.items():
        marker = '{{HMR_' + name + '}}'
        if occurrences.get(marker) != 1:
            raise ValueError('Approved template must contain exactly one ' + marker)
        anchor = next(p for p in all_paragraphs if marker in p.text)
        if anchor.text.strip() != marker or anchor._p.getparent().tag.endswith('}tc'):
            raise ValueError('Table placeholder must occupy its own body paragraph: ' + marker)
        rows = data[key]
        if name == 'MEDS_TABLE' and include_gp_plan:
            labels = (*labels, 'GP Plan')
            rows = [list(row) + [''] for row in rows]
        if not isinstance(rows, list):
            raise ValueError('Invalid table rows')
        following = anchor._p.getnext()
        if following is not None and following.tag.endswith('}tbl'):
            # The approved layout carries its own prototype table right after the marker.
            prototype = Table(following, anchor._parent)
            if name == 'MEDS_TABLE':
                _adapt_gp_plan_prototype(prototype, include_gp_plan)
            if rows:
                _fill_prototype_table(prototype, rows, labels)
            else:
                following.getparent().remove(following)
        elif rows:
            table = _table(doc, rows, labels)
            anchor._p.addprevious(table._element)
        anchor._element.getparent().remove(anchor._element)
    if occurrences.get(ISSUES_ANCHOR) != 1:
        raise ValueError('Approved template must contain exactly one ' + ISSUES_ANCHOR)
    anchor = next(p for p in all_paragraphs if ISSUES_ANCHOR in p.text)
    if anchor.text.strip() != ISSUES_ANCHOR or anchor._p.getparent().tag.endswith('}tc'):
        raise ValueError('Finding placeholder must occupy its own body paragraph')
    block = []
    end_anchor = None
    sibling = anchor._p.getnext()
    while sibling is not None:
        if sibling.tag.endswith('}p') and ''.join(sibling.xpath('.//w:t/text()')).strip() == ISSUES_END:
            end_anchor = sibling
            break
        block.append(sibling)
        sibling = sibling.getnext()
    if end_anchor is not None and data['issues']:
        block_text = ''.join(''.join(element.xpath('.//w:t/text()')) + '\n' for element in block)
        _require_finding_fields(block_text)  # otherwise the findings would silently render as nothing
    if end_anchor is not None:
        # Approved layout supplies one prototype finding (title, recommendation, rationale,
        # Plan/Feedback box). Clone it per finding so every finding looks like the owner's.
        for index, finding in enumerate(data['issues'], 1):
            for element in block:
                clone = deepcopy(element)
                anchor._p.addprevious(clone)
                if clone.tag.endswith('}p'):
                    paragraphs = [Paragraph(clone, anchor._parent)]
                else:
                    paragraphs = list(_paragraphs_in_table(Table(clone, anchor._parent)))
                for paragraph in paragraphs:
                    text = paragraph.text
                    changed = text
                    for marker, make in ISSUE_FIELDS.items():
                        if marker in changed:
                            changed = changed.replace(marker, make(index, finding))
                    if changed != text:
                        _set_text(paragraph, changed)
        for element in block + [end_anchor]:
            element.getparent().remove(element)
    else:
        for index, finding in enumerate(data['issues'], 1):
            for paragraph_text, style in (
                (str(index) + '. ' + finding['title'], 'Heading 3'),
                ('Recommendation: ' + finding['rec'], 'Normal'),
                ('Rationale: ' + finding['rationale'], 'Normal'),
            ):
                p = doc.add_paragraph(paragraph_text)
                p.style = style
                anchor._p.addprevious(p._p)
    anchor._element.getparent().remove(anchor._element)
    required = {'{{HMR_' + k + '}}' for k in TEXT_FIELDS} | {
        '{{HMR_' + k + '}}' for k in TABLE_FIELDS} | {ISSUES_ANCHOR}
    missing = sorted(required - set(occurrences))
    if missing:
        raise ValueError('Required approved template placeholders missing: ' + ', '.join(missing))
    unresolved = sorted({m.group(0) for p in _paragraphs(doc) for m in MARKER.finditer(p.text)})
    if unresolved:
        raise ValueError('Unresolved HMR placeholders: ' + ', '.join(unresolved))
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(target)
    return target
