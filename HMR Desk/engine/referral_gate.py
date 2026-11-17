"""Aggregate referral parser coverage without printing patient information."""
from collections import defaultdict
import json
from pathlib import Path
import referral

CACHE = Path(__file__).resolve().parent.parent / 'referral-cache'
FIELDS = ('meds', 'conditions', 'allergies', 'obs')

def main():
    totals = defaultdict(lambda: {'files': 0, 'unparsed': 0, **{k: [0, 0] for k in FIELDS}})
    cases = json.loads((CACHE / 'gate_cases.json').read_text(encoding='utf-8'))
    failures = []
    for path in sorted(CACHE.glob('[0-9][0-9][0-9].txt')):
        text = path.read_text(encoding='utf-8-sig'); parsed = referral.parse(text); sections = referral.sections(text)
        row = totals[parsed['layout']]; row['files'] += 1; row['unparsed'] += len(parsed['unparsed'])
        for key in FIELDS:
            if key in sections:
                row[key][0] += 1
                row[key][1] += bool(any(parsed[key].values()) if key == 'obs' else parsed[key])
        if path.stem in cases:
            expected = cases[path.stem]
            actual = {'meds': len(parsed['meds']), 'conditions': len(parsed['conditions'])}
            if actual != expected: failures.append((path.stem, expected, actual))
    print('Parsed means at least one value extracted; unparsed counts flag incomplete sections.')
    print('layout | files | meds present/parsed | conditions present/parsed | allergies present/parsed | obs present/parsed | unparsed')
    for name, row in sorted(totals.items()):
        fields = ' | '.join(f"{row[k][0]} / {row[k][1]}" for k in FIELDS)
        print(f"{name} | {row['files']} | {fields} | {row['unparsed']}")
    print(f'Provisional cases: {len(cases)-len(failures)}/{len(cases)} exact; expected counts need independent verification')
    for ident, expected, actual in failures: print(f'{ident}: expected {expected}, got {actual}')
    if len(cases) != 12 or any(not (CACHE / (i + '.txt')).is_file() for i in cases): raise SystemExit('Invalid gate cases')

if __name__ == '__main__': main()
