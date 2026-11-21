"""Table-aware pairing of referral medicine names and directions from PDF word boxes.

Text order alone can list every medicine name first and every direction afterwards. Here a direction is paired with a medicine only
when both sit on the same table row (same vertical position). If anything is ambiguous the result is not ok and the caller keeps the
fail-closed text path. Nothing is guessed by position in the text stream."""
import re
import statistics

import referral


def _lines(words):
    """words: (x0, y0, x1, y1, text). Returns [(y0, y1, [words sorted by x])] top to bottom."""
    out = []
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        h = max(w[3] - w[1], 1.0)
        if out and abs(w[1] - out[-1][0]) <= 0.5 * h:
            out[-1][2].append(w); out[-1][1] = max(out[-1][1], w[3])
        else: out.append([w[1], w[3], [w]])
    return [(a, b, sorted(ws, key=lambda w: w[0])) for a, b, ws in out]


def _text(ws): return ' '.join(w[4] for w in ws).strip()


def medicine_region(words):
    lines = _lines(words)
    start = None
    for i, (_, _, ws) in enumerate(lines):
        if referral.heading(_text(ws)) == 'meds': start = i; break
    if start is None: return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        key = referral.heading(_text(lines[j][2]))
        if key and key != 'meds': end = j; break
    return [w for _, _, ws in lines[start + 1:end] for w in ws]


def split_columns(words, min_gap=10.0):
    """Widest vertical channel that no word crosses (word extents, not word starts), with words on both sides."""
    spans = sorted((w[0], w[2]) for w in words)
    best = None; reach = spans[0][1] if spans else 0
    for x0, x1 in spans[1:]:
        if x0 - reach >= min_gap and (best is None or x0 - reach > best[1] - best[0]):
            left = sum(1 for w in words if w[2] <= reach + 0.01); right = sum(1 for w in words if w[0] >= x0 - 0.01)
            if left >= 3 and right >= 3: best = (reach, x0)
        reach = max(reach, x1)
    return None if best is None else (best[0] + best[1]) / 2


def pair_table(words):
    """Returns {'ok': bool, 'reason': str, 'rows': [[name, directions]], 'split_x': float|None}."""
    region = medicine_region(words)
    if not region: return {'ok': False, 'reason': 'no medicines heading or no words under it', 'rows': [], 'split_x': None}
    split = split_columns(region)
    if split is None: return {'ok': False, 'reason': 'no two-column layout found', 'rows': [], 'split_x': None}
    left = _lines([w for w in region if w[0] < split]); right = _lines([w for w in region if w[0] >= split])
    if not left or not right: return {'ok': False, 'reason': 'one column empty', 'rows': [], 'split_x': split}
    height = statistics.median([b - a for a, b, _ in left + right]) or 10.0
    tol = 0.5 * height

    def aligned(y, lines):
        hit = [l for l in lines if abs(l[0] - y) <= tol]
        return hit[0] if len(hit) == 1 else None

    dir_start = []                                   # indexes of right lines that begin a direction
    for i, (_, _, ws) in enumerate(right):
        if referral.DIRECTION.match(_text(ws)): dir_start.append(i)
    if not dir_start or 0 not in dir_start: return {'ok': False, 'reason': 'first direction line not recognisable', 'rows': [], 'split_x': split}
    rows = []                                        # [name_lines, direction_lines, y]
    used = set()
    for i, (y, _, ws) in enumerate(left):
        match = None
        for k in dir_start:
            if abs(right[k][0] - y) <= tol: match = k; break
        if match is not None:
            used.add(match); rows.append([[_text(ws)], [], y, match])
        elif referral.STRENGTH.search(_text(ws)):          # a new medicine that really has no direction on its row
            rows.append([[_text(ws)], [], y, None])
        elif rows: rows[-1][0].append(_text(ws))
        else: return {'ok': False, 'reason': 'name text before the first aligned row', 'rows': [], 'split_x': split}
    if used != set(dir_start): return {'ok': False, 'reason': 'a direction line has no medicine on its row', 'rows': [], 'split_x': split}
    starts = sorted(r[3] for r in rows if r[3] is not None)
    for i, (_, _, ws) in enumerate(right):               # continuation lines follow the nearest earlier direction start
        owner = max((k for k in starts if k <= i), default=None)
        if owner is None: return {'ok': False, 'reason': 'direction text above the first row', 'rows': [], 'split_x': split}
        next(r for r in rows if r[3] == owner)[1].append(_text(ws))
    return {'ok': True, 'reason': '', 'split_x': split, 'rows': [[' '.join(r[0]), ' '.join(r[1])] for r in rows]}


def analyse_pdf(path):
    import fitz
    pages = []
    with fitz.open(path) as doc:
        for number, page in enumerate(doc, 1):
            words = [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text('words')]
            if medicine_region(words) is not None: pages.append((number, pair_table(words), words))
    return pages


def shape(text):
    return re.sub(r'[a-z]', 'a', re.sub(r'[A-Z]', 'A', re.sub(r'\d', '9', text)))
