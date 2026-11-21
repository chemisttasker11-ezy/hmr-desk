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


def _crosses(line, x): return any(w[0] < x < w[2] for w in line[2])


def split_columns(lines, min_gap=10.0):
    """Widest vertical channel that at most a tenth of the lines cross (word extents, not word starts). Returns (x, crossing lines)."""
    words = [w for l in lines for w in l[2]]
    if not words: return None
    lo, hi = int(min(w[0] for w in words)), int(max(w[2] for w in words)) + 1
    allowed = len(lines) // 10
    runs = []; start = None
    for x in range(lo, hi + 1):
        free = sum(1 for l in lines if _crosses(l, x)) <= allowed
        if free and start is None: start = x
        if (not free or x == hi) and start is not None:
            runs.append((start, x - 1)); start = None
    best = None
    for a, b in runs:
        if b - a + 1 < min_gap: continue
        mid = (a + b) / 2
        left = sum(1 for w in words if w[2] <= mid); right = sum(1 for w in words if w[0] >= mid)
        if left >= 3 and right >= 3 and (best is None or b - a > best[1] - best[0]): best = (a, b)
    if best is None: return None
    mid = (best[0] + best[1]) / 2
    return mid, [l for l in lines if _crosses(l, mid)]


def _fail(reason, split=None, extra=None):
    return {'ok': False, 'reason': reason, 'rows': [], 'split_x': split, 'excluded': extra or []}


def pair_table(words):
    """Returns {'ok': bool, 'reason': str, 'rows': [[name, directions]], 'split_x': float|None, 'excluded': [line text]}.
    A direction starts where a right-column line sits on the same row as a left-column line. A right line with no left line beside it
    continues the direction above; a left line with no right line beside it continues the name above unless it looks like a new
    medicine (then the page is ambiguous and nothing is returned)."""
    region = medicine_region(words)
    if not region: return _fail('no medicines heading or no words under it')
    lines = _lines(region)
    found = split_columns(lines)
    if found is None: return _fail('no two-column layout found')
    split, crossing = found
    height = statistics.median([b - a for a, b, _ in lines]) or 10.0
    tol = 0.5 * height
    pitch = statistics.median([lines[i + 1][0] - lines[i][0] for i in range(len(lines) - 1)]) if len(lines) > 1 else height
    table = [l for l in lines if l not in crossing]
    if not table: return _fail('only full-width lines found', split)
    last = max(l[0] for l in table)
    excluded = []
    for l in crossing:       # a line across both columns is only set aside when it is well clear of the table (footer or page number)
        if l[0] > last + 3 * pitch: excluded.append(_text(l[2]))
        else: return _fail('text crosses the column gap inside the table', split)
    while len(table) > 1 and table[-1][0] - table[-2][0] > 3 * pitch:   # trailing line well clear of the table: footer or page number
        excluded.append(_text(table.pop()[2]))
    cells = []               # (y, side, text) from words split at the channel; a line may hold both sides
    for y0, y1, ws in table:
        cells.append((y0, [w for w in ws if w[2] <= split], [w for w in ws if w[0] >= split]))
    for _, l, r in cells:
        if any(w[0] < split < w[2] for w in l + r): return _fail('a word crosses the column gap', split)
    # Words of one table row can sit a point or two apart vertically, so left and right cells are matched by y, not by line.
    left = _lines([w for _, l, _ in cells for w in l]); right = _lines([w for _, _, r in cells for w in r])
    if not left or not right: return _fail('one column empty', split)
    rows = []
    r_used = set(); last_left = -1e9
    for ly, _, lws in left:
        lt = _text(lws); previous = last_left; last_left = ly
        hits = [i for i, (ry, _, _) in enumerate(right) if abs(ry - ly) <= tol]
        if len(hits) > 1: return _fail('two direction lines on one row', split)
        if hits and not lt[:1].islower():
            r_used.add(hits[0]); rows.append([lt, _text(right[hits[0]][2])])
        elif hits:           # lowercase left text beside a right line: both are continuations
            if not rows: return _fail('continuation before the first row', split)
            r_used.add(hits[0]); rows[-1][0] += ' ' + lt; rows[-1][1] = (rows[-1][1] + ' ' + _text(right[hits[0]][2])).strip()
        elif referral.STRENGTH.search(lt) and not lt[:1].islower():
            return _fail('a left line looks like a new medicine but has no direction beside it (y=%d)' % round(ly), split)
        else:
            if not rows: return _fail('name text before the first row', split)
            if ly - previous > 2.2 * height: return _fail('name text far from any row (y=%d)' % round(ly), split)
            rows[-1][0] += ' ' + lt
    for i, (ry, _, rws) in enumerate(right):
        if i in r_used: continue
        if not rows: return _fail('direction text above the first row', split)
        # attach to the row whose own direction line is the nearest one above
        above = [k for k in r_used if right[k][0] < ry]
        if not above: return _fail('direction text above the first row', split)
        owner = max(above, key=lambda k: right[k][0])
        if ry - right[owner][0] > 2.2 * height: return _fail('direction text far from any row (y=%d)' % round(ry), split)
        for row in rows:
            if row[1].startswith(_text(right[owner][2])): row[1] += ' ' + _text(rws); break
    return {'ok': True, 'reason': '', 'split_x': split, 'rows': rows, 'excluded': excluded}


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
