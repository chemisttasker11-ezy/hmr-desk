"""Visual evidence for pathology proposals; original PDF is authoritative.

Only a source ID / proposal ID from the patient's protected source list can
select a crop. Never accept a filesystem path, page or arbitrary rectangle
from a renderer. Nothing is saved to disk or sent externally.
"""
import base64
import hashlib

import fitz

import pathology_proposals


def for_proposal(conn, patient, source_id, proposal_id, expected_sha256):
    if not isinstance(proposal_id, str) or not isinstance(expected_sha256, str):
        raise ValueError('Invalid original-cell review request')
    proposal_set = pathology_proposals.for_source(conn, patient, source_id)
    if expected_sha256 != proposal_set['source_sha256']:
        raise ValueError('Source changed; reload before comparing original')
    row = next((item for item in proposal_set['proposals'] if item['id'] == proposal_id), None)
    if row is None:
        raise ValueError('Source cell no longer matches the proposal')
    source = next(item for item in __import__('pathology_import').sources(conn, patient)['sources']
                  if item['id'] == source_id)
    path = pathology_proposals._source_path(patient, source)
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError('Pathology source changed during original-cell preview')
    try:
        with fitz.open(stream=content, filetype='pdf') as pdf:
            page = pdf[row['page']-1]
            rect = row['row_bbox']
            if (not isinstance(rect, list) or len(rect) != 4 or
                    any(not isinstance(n, (int,float)) for n in rect)):
                return {'kind': 'none', 'note': 'Cell location could not be established. Open the original PDF.'}
            region = fitz.Rect(rect)
            clip = (region + (-8, -5, 8, 5)) & page.rect
            if clip.is_empty or clip.width < 10 or clip.height < 4 or clip.height > page.rect.height * .5:
                return {'kind': 'none', 'note': 'Original cell region not safe to display; open the full PDF.'}
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
            data = pix.tobytes('png')
            if len(data)>2*1024*1024:
                return {'kind': 'none', 'note': 'Original crop too large; open full PDF.'}
            return {'kind': 'row', 'page': row['page'],
                    'png': base64.b64encode(data).decode('ascii'),
                    'note': 'Unverified PDF row evidence, with neighbouring cells for visual comparison. Confirm patient, sample date, value, unit and laboratory interval against the full original report.'}
    except (fitz.FileDataError, fitz.EmptyFileError, IndexError) as exc:
        raise ValueError('Original PDF is damaged, changed or missing the selected page') from exc
