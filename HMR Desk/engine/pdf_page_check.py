"""Host check for a generated report PDF: body words per page, ignoring the repeated header and footer text.
  python pdf_page_check.py REPORT.pdf        prints counts only; exit 1 if any page has no body text (blank spill page)."""
import re
import sys

REPEAT = re.compile(r'(?i)^(provisional|local|layout|-|not|the|owner-?|approved|report|template|page|\d+)$')


def body_words(page): return [w for w in page.get_text().split() if not REPEAT.match(w)]


def check(path):
    import fitz
    with fitz.open(path) as doc: return [len(body_words(p)) for p in doc]


if __name__ == '__main__':
    if len(sys.argv) != 2: print(__doc__); sys.exit(2)
    counts = check(sys.argv[1])
    for i, c in enumerate(counts, 1): print('page %d: %d body words%s' % (i, c, '  <-- BLANK' if c == 0 else ''))
    sys.exit(1 if 0 in counts else 0)
