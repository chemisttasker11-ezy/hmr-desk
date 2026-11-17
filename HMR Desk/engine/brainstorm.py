"""Local, cached sections of the Brainstorm reference."""
import json
import hashlib
from pathlib import Path
import re
import fitz
import db
import jobs


def sections(path):
    path = Path(path)
    if not path.is_file(): return []
    target = Path(db.DATA_DIR) / 'brainstorm-sections-v2.json'
    source_key = hashlib.sha256(b'brainstorm-sections-v2' + path.read_bytes()).hexdigest()
    if target.is_file():
        try:
            cached = json.loads(target.read_text(encoding='utf-8'))
            if cached.get('source_sha256') == source_key: return cached['sections']
        except (ValueError, OSError, AttributeError, KeyError): pass
    result = []
    current = None
    with fitz.open(path) as doc:
        pages = len(doc)
        for page in doc:
            lines = [line for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])]
            continuation = False
            for line in lines:
                spans = line['spans']
                text = re.sub(r'\s+', ' ', ''.join(s['text'] for s in spans)).strip()
                if not text or re.match(r'^Brainstorming \| Medication Management Report V2\.0 \|', text): continue
                # The original PDF uses a coloured marker rather than bold or larger type for headings.
                heading = any(s['color'] == 42733 for s in spans) or any('bold' in s['font'].lower() or s['size'] > 13 for s in spans if s['text'].strip())
                if continuation and current and not heading:
                    current['title'] += ' ' + text
                    continuation = current['title'].count('(') > current['title'].count(')')
                    continue
                if heading:
                    if current: result.append(current)
                    current = {'title': text, 'page': page.number + 1, 'text': ''}
                    continuation = text.count('(') > text.count(')')
                elif current:
                    current['text'] += text + '\n'
    if current: result.append(current)
    # pages 1-4 are the cover, contents and disclaimer: their 'Title'/'Refer To' rows matched every search
    result = [s for s in result if len(s['text'].strip()) >= 30 and (pages < 20 or s['page'] > 4) and s['title'] not in ('Title', 'Refer To')]
    for s in result: s['text'] = s['text'].strip()
    target.parent.mkdir(parents=True, exist_ok=True)
    jobs.atomic_json(target, {'source_sha256': source_key, 'sections': result})
    return result


def snippet(text, patterns):
    matches = [m.start() for pattern in patterns for m in [re.search(pattern, text, re.I)] if m]
    pos = min(matches, default=0)
    start = max(0, pos - 100)
    return text[start:start + 300].replace('\n', ' ').strip()
