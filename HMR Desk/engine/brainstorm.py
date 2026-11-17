"""Local, cached sections of the Brainstorm reference."""
import json
import hashlib
from pathlib import Path
import re
import fitz
import db
import jobs


def valid_cached_sections(items,pdf_hash):
    if not isinstance(items,list):return False
    for section in items:
        if not isinstance(section,dict) or section.get('pdf_sha256')!=pdf_hash or section.get('citation_version')!=1:return False
        if not isinstance(section.get('title'),str) or not isinstance(section.get('text'),str):return False
        if type(section.get('page')) is not int or type(section.get('page_end')) is not int or not 1<=section['page']<=section['page_end']:return False
        fragments=section.get('fragments')
        if not isinstance(fragments,list) or not fragments:return False
        previous=section['page']-1
        for fragment in fragments:
            if not isinstance(fragment,dict) or type(fragment.get('page')) is not int or not previous<fragment['page']<=section['page_end'] or not isinstance(fragment.get('text'),str) or not fragment['text'].strip():return False
            previous=fragment['page']
        if previous!=section['page_end']:return False
    return True


def sections(path, marker_headings=False):
    path = Path(path)
    if not path.is_file(): return []
    cache_version='brainstorm-sections-v4-marker' if marker_headings else 'brainstorm-sections-v3'
    target = Path(db.DATA_DIR) / (cache_version+'.json')
    pdf_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    source_key = hashlib.sha256((cache_version+':' + pdf_hash).encode()).hexdigest()
    if target.is_file():
        try:
            cached = json.loads(target.read_text(encoding='utf-8'))
            if cached.get('source_sha256') == source_key and valid_cached_sections(cached.get('sections'),pdf_hash): return cached['sections']
        except (ValueError, OSError, AttributeError, KeyError): pass
    result = []
    current = None
    with fitz.open(path) as doc:
        pages = len(doc)
        # The supplied Brainstorm guide uses coloured heading markers. Inline
        # bold words are body emphasis, not new sections. Keep legacy/manual
        # parsing unchanged unless the structured importer selects this mode.
        use_markers=marker_headings and any(span['color']==42733 for page in doc for block in page.get_text('dict')['blocks'] for line in block.get('lines',[]) for span in line['spans'])
        for page in doc:
            lines = [line for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])]
            continuation = False
            for line in lines:
                spans = line['spans']
                text = re.sub(r'\s+', ' ', ''.join(s['text'] for s in spans)).strip()
                if not text or re.match(r'^Brainstorming \| Medication Management Report V2\.0 \|', text): continue
                # The original PDF uses a coloured marker rather than bold or larger type for headings.
                heading = any(s['color'] == 42733 for s in spans) or (not use_markers and any('bold' in s['font'].lower() or s['size'] > 13 for s in spans if s['text'].strip()))
                if continuation and current and not heading:
                    current['title'] += ' ' + text
                    continuation = current['title'].count('(') > current['title'].count(')')
                    continue
                if heading:
                    if current: result.append(current)
                    current = {'title': text, 'page': page.number + 1, 'text': '', 'fragments': [], 'pdf_sha256': pdf_hash, 'citation_version': 1}
                    continuation = text.count('(') > text.count(')')
                elif current:
                    current['text'] += text + '\n'
                    fragments = current['fragments']
                    if not fragments or fragments[-1]['page'] != page.number + 1:
                        fragments.append({'page': page.number + 1, 'text': ''})
                    fragments[-1]['text'] += text + '\n'
    if current: result.append(current)
    # pages 1-4 are the cover, contents and disclaimer: their 'Title'/'Refer To' rows matched every search
    result = [s for s in result if len(s['text'].strip()) >= 30 and (pages < 20 or s['page'] > 4) and s['title'] not in ('Title', 'Refer To')]
    for s in result:
        s['text'] = s['text'].strip()
        for fragment in s['fragments']: fragment['text'] = fragment['text'].strip()
        s['page_end'] = s['fragments'][-1]['page'] if s['fragments'] else s['page']
    target.parent.mkdir(parents=True, exist_ok=True)
    jobs.atomic_json(target, {'source_sha256': source_key, 'sections': result})
    return result


def snippet(text, patterns):
    matches = [m.start() for pattern in patterns for m in [re.search(pattern, text, re.I)] if m]
    pos = min(matches, default=0)
    start = max(0, pos - 100)
    return text[start:start + 300].replace('\n', ' ').strip()


def passage(section, patterns):
    """Quote within one physical PDF page. Never label continuation text with its heading page.

    PDF byte hash identifies this exact supplied edition. citation_version versions this
    schema, not the clinical reference. Titles and section page ranges are kept separate.
    No medical relevance, currency or permission is implied by a text match.
    """
    if (not isinstance(section,dict) or not isinstance(section.get('title'),str) or
        type(section.get('page')) is not int or type(section.get('page_end')) is not int or
        not 1<=section['page']<=section['page_end'] or
        not re.fullmatch(r'[a-f0-9]{64}',str(section.get('pdf_sha256',''))) or section.get('citation_version')!=1): return None
    fragments = section.get('fragments')
    if not isinstance(fragments, list) or not fragments: return None
    choices = []
    for position, fragment in enumerate(fragments):
        if not isinstance(fragment,dict): return None
        text = fragment.get('text')
        page = fragment.get('page')
        if not isinstance(text, str) or not text.strip() or type(page) is not int or not section['page']<=page<=section['page_end']: return None
        matches = [m.start() for pattern in patterns for m in [re.search(pattern, text, re.I)] if m]
        if matches: choices.append((-len(matches), position, min(matches), fragment))
    if not choices: return None
    _, _, offset, fragment = min(choices, key=lambda row: row[:3])
    start = max(0, offset - 100)
    # An exact substring of extracted text; avoid splitting words at clip edges.
    text=fragment['text']
    if start and text[start-1:start].isalnum() and text[start:start+1].isalnum():
        boundary=re.search(r'\s',text[start:offset])
        if boundary: start+=boundary.end()
    end=min(len(text),start+300)
    if end<len(text) and text[end-1:end].isalnum() and text[end:end+1].isalnum():
        boundary=max(text.rfind(' ',start,end),text.rfind('\n',start,end))
        if boundary>offset: end=boundary
    quote = text[start:end]
    return {'title': section['title'], 'page': fragment['page'], 'snippet': quote,
            'section_page': section['page'], 'section_page_end': section['page_end'],
            'pdf_sha256': section['pdf_sha256'], 'citation_version': 1,
            'omitted_before':start>0,'omitted_after':end<len(text),
            'match_kind': 'reference_text_match', 'review_status': 'pharmacist_review_required'}
