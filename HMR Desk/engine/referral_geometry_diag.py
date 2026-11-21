"""Run on the host against a referral PDF. Reads the file locally and writes nothing unless asked.

  python referral_geometry_diag.py REFERRAL.pdf            counts and reasons only (no medicine text)
  python referral_geometry_diag.py REFERRAL.pdf --show     also prints the paired rows on this console
  python referral_geometry_diag.py REFERRAL.pdf --geometry OUT.json
        writes word boxes with every letter and digit replaced by a shape (A, a, 9); safe to share, shows the layout only."""
import json
import sys

import referral_geometry as g


def main(argv):
    if not argv: print(__doc__); return 2
    path = argv[0]; show = '--show' in argv
    out = argv[argv.index('--geometry') + 1] if '--geometry' in argv else None
    import fitz
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, 1): print('page %d: text-layer words=%d images=%d' % (i, len(page.get_text('words')), len(page.get_images())))
    found = g.analyse_pdf(path)
    if not found: print('No page with a Current Medications heading was found.'); return 1
    for number, result, words in found:
        rows = result['rows']
        print('page %d: ok=%s reason=%r split_x=%s rows=%d with_directions=%d' % (number, result['ok'], result['reason'], None if result['split_x'] is None else round(result['split_x'], 1), len(rows), sum(1 for r in rows if r[1])))
        if show:
            for i, r in enumerate(rows, 1): print('  %2d | %s | %s' % (i, r[0], r[1]))
    if '--xhist' in argv:
        for number, result, words in found:
            region = g.medicine_region(words) or []
            lines = g._lines(region)
            print('page %d region: words=%d lines=%d' % (number, len(region), len(lines)))
            xs = {}
            for w in region: xs[round(w[0])] = xs.get(round(w[0]), 0) + 1
            print('  word x0 counts (x:count): ' + ' '.join('%d:%d' % kv for kv in sorted(xs.items())))
            for i, (y0, y1, ws) in enumerate(lines[:60]):
                print('  line %2d y=%4d h=%2d words=%2d x0=%s x1max=%d shape=%s' % (i, y0, y1 - y0, len(ws), ','.join(str(round(w[0])) for w in ws[:8]), max(w[2] for w in ws), ' '.join(g.shape(w[4]) for w in ws[:6])))
    if out:
        data = [{'page': n, 'ok': r['ok'], 'reason': r['reason'], 'split_x': r['split_x'], 'words': [[round(w[0], 1), round(w[1], 1), round(w[2], 1), round(w[3], 1), g.shape(w[4])] for w in ws]} for n, r, ws in found]
        with open(out, 'w', encoding='utf-8') as f: json.dump(data, f)
        print('wrote', out)
    return 0


if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
