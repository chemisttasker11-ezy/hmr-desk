"""Deterministic structuring of pharmacist-entered pathology text.

Only parses explicit numeric forms already recorded by the pharmacist and the
laboratory's own stated reference interval. No clinical thresholds, unit
inference, abnormality rules or interpretation are added by this module; an
unparseable or ambiguous string is left untouched rather than guessed.

A range position produced here is arithmetic against the laboratory's stated
interval in the laboratory's reported unit only. It is not a renal dosing,
abnormality or any other clinical finding.
"""
import math
import re
from decimal import Decimal, InvalidOperation

# Explicit numeric forms only: "4.1", "<0.5", ">= 60". Free text stays free
# text. Digit strings are length-capped so float conversion cannot overflow.
MAX_DIGITS = 20
VALUE = re.compile(r'^(<=|>=|<|>|=)?\s*(\d{1,%d}(?:\.\d{1,%d})?)$' % (MAX_DIGITS, MAX_DIGITS))
# Laboratory-stated intervals: "3.5-5.2", "0.0 - 4.0", "< 60", ">=90".
BETWEEN = re.compile(r'^(\d{1,%d}(?:\.\d{1,%d})?)\s*-\s*(\d{1,%d}(?:\.\d{1,%d})?)$' % ((MAX_DIGITS,) * 4))
BOUND = re.compile(r'^(<=|>=|<|>)\s*(\d{1,%d}(?:\.\d{1,%d})?)$' % (MAX_DIGITS, MAX_DIGITS))


def _number(text):
    """Exact decimal for comparison, or None when not finite/representable."""
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _display(number):
    """JSON-safe float form of an exact decimal; never NaN/Infinity."""
    if number is None:
        return None
    converted = float(number)
    return converted if math.isfinite(converted) else None


def parse_value(text):
    """Return (comparator, exact decimal) for an explicit numeric value, else
    None. Comparisons use the exact decimal; only display output is float."""
    if not isinstance(text, str):
        return None
    m = VALUE.fullmatch(text.strip())
    if not m:
        return None
    number = _number(m.group(2))
    return (m.group(1) or '=', number) if number is not None else None


def parse_interval(text):
    """Return ((low, low_inclusive), (high, high_inclusive)) from the lab's own
    stated interval, else None. Either bound may be None for one-sided
    intervals. Between-bounds ("3.5-5.2") follow lab reporting convention and
    are inclusive at both ends; strict comparators keep their strictness."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    m = BETWEEN.fullmatch(t)
    if m:
        low, high = _number(m.group(1)), _number(m.group(2))
        if low is None or high is None:
            return None
        return ((low, True), (high, True)) if low <= high else None
    m = BOUND.fullmatch(t)
    if not m:
        return None
    op = m.group(1)
    num = _number(m.group(2))
    if num is None:
        return None
    if op in ('<', '<='):
        return (None, (num, op == '<='))
    return ((num, op == '>='), None)


def position(value, interval):
    """Position of an explicit value within the lab's own stated interval.

    value/interval are results of parse_value/parse_interval. Returns one of
    'below', 'within', 'above' or 'undetermined'. Only exact values ('='
    comparator) against explicit bounds can be positioned; anything else is
    'undetermined'. Bound inclusivity is honoured: 60 against "<60" is above,
    60 against "<=60" is within. This is arithmetic against the laboratory's
    stated interval, not a clinical judgment.
    """
    if value is None or interval is None:
        return 'undetermined'
    comparator, number = value
    if comparator != '=':
        return 'undetermined'
    low, high = interval
    if low is not None:
        bound, inclusive = low
        if number < bound or (number == bound and not inclusive):
            return 'below'
    if high is not None:
        bound, inclusive = high
        if number > bound or (number == bound and not inclusive):
            return 'above'
    return 'within'


def structure(value_text, interval_text, unit=''):
    """Structured view of a recorded result, or None when nothing explicit.

    Raw operands are preserved verbatim. A position is only reported when the
    value is an exact number, the interval is explicit, and a unit is recorded;
    every other case is 'undetermined' with its reasons. The laboratory-
    reported unit is the only unit context; nothing here establishes that the
    interval shares it beyond the lab having stated both on the same row.
    """
    value = parse_value(value_text)
    interval = parse_interval(interval_text)
    if value is None and interval is None:
        return None
    reasons = []
    if value is None:
        reasons.append('result is not an explicit number')
    elif value[0] != '=':
        reasons.append('comparator result cannot be positioned exactly')
    if interval is None:
        reasons.append('reference interval not an explicit numeric range')
    if not str(unit).strip():
        reasons.append('unit not recorded')
    pos = 'undetermined' if reasons else position(value, interval)
    return {'value_comparator': value[0] if value else '',
            'value_number': _display(value[1]) if value else None,
            # Exact operands for downstream rules; the float display fields
            # above are for rendering only and must not be re-parsed.
            'value_exact': str(value[1]) if value else '',
            'interval_low_exact': str(interval[0][0]) if interval and interval[0] else '',
            'interval_high_exact': str(interval[1][0]) if interval and interval[1] else '',
            'interval_low': _display(interval[0][0]) if interval and interval[0] else None,
            'interval_low_inclusive': interval[0][1] if interval and interval[0] else None,
            'interval_high': _display(interval[1][0]) if interval and interval[1] else None,
            'interval_high_inclusive': interval[1][1] if interval and interval[1] else None,
            'range_position': pos,
            'undetermined_reason': '; '.join(reasons),
            'raw_value': value_text if isinstance(value_text, str) else '',
            'raw_interval': interval_text if isinstance(interval_text, str) else '',
            'unit': unit.strip() if isinstance(unit, str) else '',
            'unit_assumption': ('interval assumed in the laboratory-reported unit as stated on '
                                'the same result; not independently verified') if str(unit).strip() else '',
            'basis': 'laboratory range position only; not a renal dosing, abnormality or clinical finding'}
