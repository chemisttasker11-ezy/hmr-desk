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

from docx import Document
from docx.table import Table

TEXT_FIELDS = {
    'ASSESS_DATE': 'assess_date', 'REPORT_DATE': 'report_date',
    'PATIENT': 'patient', 'DOCTOR': 'doctor', 'DEAR': 'dear',
    'THANKS': 'thanks', 'REASON': 'reason', 'INTRO': 'intro',
    'CONDITIONS': 'conditions', 'ALLERGIES': 'allergies',
    'OBS': 'obs', 'FOLLOWUP': 'followup',
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
    return True


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


def _set_text(paragraph, text):
    # Keep original paragraph and first-run formatting, not default document style.
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ''
    else:
        paragraph.add_run(text)


def _apply_owner_table_format(doc, table):
    """Use the approved template's own table formatting, not a generic grid.

    The template's first existing table supplies the style id and table properties
    (borders, widths, cell margins). Only a template with no table of its own falls
    back to the built-in grid, so a bare template still renders readable tables.
    """
    from copy import deepcopy
    existing = [t for t in doc.tables if t._tbl is not table._tbl]
    candidates = [t for t in existing if len(t.rows) >= 2 and len(t.columns) >= 2]
    reference = candidates[0] if candidates else next(iter(existing), None)
    if reference is not None:
        source_pr = reference._tbl.tblPr
        target_pr = table._tbl.tblPr
        if source_pr is not None and target_pr is not None:
            parent = target_pr.getparent()
            parent.replace(target_pr, deepcopy(source_pr))
            return 'template'
    try:
        table.style = 'Table Grid'
    except KeyError:
        return 'none'
    return 'fallback-grid'


def _table(doc, rows, labels):
    table = doc.add_table(rows=1, cols=len(labels))
    _apply_owner_table_format(doc, table)
    for cell, label in zip(table.rows[0].cells, labels):
        cell.text = label
    for values in rows:
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    return table


def render(data, target, template):
    """Fill approved layout in place, preserving letterhead, margins and footer."""
    target, template = Path(target), Path(template)
    if target.exists():
        raise FileExistsError('Never overwrite existing or signed HMR report')
    doc = Document(template)
    occurrences = {}
    all_paragraphs = list(_paragraphs(doc))
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
            if name in TEXT_FIELDS:
                value = data.get(TEXT_FIELDS[name], '')
                if not isinstance(value, str):
                    raise ValueError('Invalid text field in report data')
                changed = changed.replace(marker, value)
        if changed != original:
            _set_text(paragraph, changed)
    for name, (key, labels) in TABLE_FIELDS.items():
        marker = '{{HMR_' + name + '}}'
        if occurrences.get(marker) != 1:
            raise ValueError('Approved template must contain exactly one ' + marker)
        anchor = next(p for p in all_paragraphs if marker in p.text)
        if anchor.text.strip() != marker or anchor._p.getparent().tag.endswith('}tc'):
            raise ValueError('Table placeholder must occupy its own body paragraph: ' + marker)
        rows = data[key]
        if not isinstance(rows, list):
            raise ValueError('Invalid table rows')
        if rows:
            table = _table(doc, rows, labels)
            anchor._p.addprevious(table._element)
        anchor._element.getparent().remove(anchor._element)
    if occurrences.get(ISSUES_ANCHOR) != 1:
        raise ValueError('Approved template must contain exactly one ' + ISSUES_ANCHOR)
    anchor = next(p for p in all_paragraphs if ISSUES_ANCHOR in p.text)
    if anchor.text.strip() != ISSUES_ANCHOR or anchor._p.getparent().tag.endswith('}tc'):
        raise ValueError('Finding placeholder must occupy its own body paragraph')
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
