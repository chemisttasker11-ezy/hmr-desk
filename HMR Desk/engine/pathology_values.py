"""Deterministic structuring of pharmacist-entered pathology text.

Only parses explicit numeric forms already recorded by the pharmacist and the
laboratory's own stated reference interval. No clinical thresholds, units
inference, abnormality rules or interpretation are added by this module; an
unparseable string is left untouched rather than guessed.
"""
import re

# Explicit numeric forms only: "4.1", "<0.5", ">= 60". Free text stays free text.
VALUE = re.compile(r'^(<=|>=|<|>|=)?\s*(\d+(?:\.\d+)?)$')
# Laboratory-stated intervals: "3.5-5.2", "0.0 - 4.0", "< 60", ">=90".
BETWEEN = re.compile(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$')
BOUND = re.compile(r'^(<=|>=|<|>)\s*(\d+(?:\.\d+)?)$')


def parse_value(text):
    """Return (comparator, number) for an explicit numeric value, else None."""
    if not isinstance(text, str):
        return None
    m = VALUE.fullmatch(text.strip())
    if not m:
        return None
    return (m.group(1) or '=', float(m.group(2)))


def parse_interval(text):
    """Return (low, high) bounds from the lab's own stated interval, else None.

    Either bound may be None for one-sided intervals ("< 60").
    """
    if not isinstance(text, str):
        return None
    t = text.strip()
    m = BETWEEN.fullmatch(t)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        return (low, high) if low <= high else None
    m = BOUND.fullmatch(t)
    if not m:
        return None
    op, num = m.group(1), float(m.group(2))
    if op in ('<', '<='):
        return (None, num)
    return (num, None)


def position(value, interval):
    """Position of an explicit value within the lab's own stated interval.

    value/interval are results of parse_value/parse_interval. Returns one of
    'below', 'within', 'above' or 'undetermined' (any non-exact comparator,
    missing bound or unparseable input). This is arithmetic against the
    laboratory's stated interval, not a clinical judgment.
    """
    if value is None or interval is None:
        return 'undetermined'
    comparator, number = value
    if comparator != '=':
        return 'undetermined'
    low, high = interval
    if low is not None and number < low:
        return 'below'
    if high is not None and number > high:
        return 'above'
    return 'within'


def structure(value_text, interval_text):
    """Structured view of a recorded result, or None when not explicit."""
    value = parse_value(value_text)
    interval = parse_interval(interval_text)
    if value is None and interval is None:
        return None
    return {'value_comparator': value[0] if value else '',
            'value_number': value[1] if value else None,
            'interval_low': interval[0] if interval else None,
            'interval_high': interval[1] if interval else None,
            'range_position': position(value, interval),
            'basis': "arithmetic against the laboratory's stated interval; not a clinical interpretation"}
