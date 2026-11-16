"""Print recognised, value-free headings and layout counts for the cache."""
from collections import Counter
from pathlib import Path
import referral

CACHE = Path(__file__).resolve().parent.parent / 'referral-cache'

def main():
    counts = Counter()
    for path in sorted(CACHE.glob('[0-9][0-9][0-9].txt')):
        text = path.read_text(encoding='utf-8-sig')
        counts[referral.layout(text)] += 1
        labels = []
        lines = text.replace('\f', '\n').splitlines()
        for i, line in enumerate(lines):
            if referral.heading(line) and any(x.strip() for x in lines[i+1:i+4]):
                label = ' '.join(line.strip().strip(':').split())
                if label not in labels: labels.append(label)
        print(path.stem + ': ' + ', '.join(labels))
    print('Layouts:')
    for name, count in sorted(counts.items()): print(f'{name}: {count}')

if __name__ == '__main__': main()
