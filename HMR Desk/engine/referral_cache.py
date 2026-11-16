"""Dump the text of real referral PDFs into HMR Desk\\referral-cache (local, real patient text: never ship or
copy it). Used to tune and measure the rule-based referral reader. Run: python referral_cache.py"""
import json, random, re, sys
from pathlib import Path

import fitz

import db

BASE = Path(db.BASE)
sys.path.insert(0, str(BASE / 'scripts' / 'intake'))
import intake  # noqa: E402  (its OCR helper)

OUT = BASE / 'HMR Desk' / 'referral-cache'
NAMED = re.compile(r'_ [A-Z]{2,4}\.pdf$')


def candidates():
    found = [p for p in (BASE / 'Scheduled').glob('*/*.pdf') if NAMED.search(p.name)]
    found += [p for p in (BASE / 'on Excel').glob('*.pdf') if NAMED.search(p.name)]
    visited = sorted(p for p in (BASE / 'Visited').rglob('*.pdf') if NAMED.search(p.name))
    random.Random(1).shuffle(visited)
    return found + visited[:60]


def main():
    OUT.mkdir(exist_ok=True)
    paths = candidates()
    pages, needs_ocr = {}, []
    for p in paths:
        try:
            with fitz.open(p) as doc:
                pages[p] = [page.get_text() for page in doc]
            if any(len(t.strip()) < 200 for t in pages[p]):
                needs_ocr.append(p)
        except Exception as exc:
            print('read failed', exc)
    scanned = {}
    for i in range(0, len(needs_ocr), 20):  # small batches: one bad file must not lose the rest
        try:
            scanned.update(intake.ocr_pdfs(needs_ocr[i:i + 20]))
        except Exception as exc:
            print('ocr batch failed', exc)
    index = {}
    for n, (p, texts) in enumerate(pages.items(), 1):
        ocr = scanned.get(str(p), [])
        if len(ocr) == len(texts):
            texts = [t if len(t.strip()) >= 200 else ocr[i] for i, t in enumerate(texts)]
        name = f'{n:03d}.txt'
        (OUT / name).write_text('\f'.join(texts), encoding='utf-8')
        index[name] = {'file': str(p.relative_to(BASE)), 'pages': len(texts), 'ocr': p in needs_ocr}
    (OUT / 'index.json').write_text(json.dumps(index, indent=1), encoding='utf-8')
    print(len(index), 'referrals cached,', len(needs_ocr), 'needed OCR')


if __name__ == '__main__':
    main()
