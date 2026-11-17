"""Bounded, explicit arithmetic observations over the saved evidence context.

Each check is deterministic and states exactly what it compared. The only
check present compares one pharmacist-verified result against the interval
stated on the same row and reports a neutral arithmetic observation - or why
no observation is possible. Applicability of the laboratory interval to this
patient (assay, units, age/sex partitions, clinical context) is NOT
established here and the output says so. Observations are review material
only: the pharmacist selects what, if anything, is included in a report;
inclusion is their clinical judgment, not validation by this software.
"""
import suggestion_context

VERSION = 2

LIMITATIONS = [
    'Check output is an arithmetic observation, not a clinical finding, diagnosis or recommendation.',
    'A range observation compares the result with the interval printed on the same laboratory row; interval provenance, assay and unit compatibility are not independently confirmed.',
    'Pharmacist review selects what enters a report; software inclusion confers no clinical validity.',
]


def _verified_pathology(evidence):
    for e in evidence:
        if (e.get('kind') == 'pathology' and
                e.get('verification') == 'named pharmacist verified' and
                e.get('verified_by') and e.get('verified_at')):
            yield e


def _cautions(e):
    cautions = list(e.get('flags') or [])
    if e.get('date'):
        cautions.append('sample date %s (%s days before context date)' % (e['date'], e.get('age_days')))
    else:
        cautions.append('sample date not established')
    cautions.append('source: %s' % (e.get('source') or 'not recorded'))
    return cautions


def check_lab_range_position(e):
    """Same-row arithmetic observation, applicability unestablished.

    Only explicit positions map to an observation; anything unknown,
    malformed or missing fails closed to cannot_assess with reasons.
    """
    structured = e.get('structured') or {}
    base = {'check_id': 'lab_range_position', 'kind': 'arithmetic_observation',
            'evidence_id': e['id'], 'test': e.get('test', ''),
            'source': e.get('source', ''), 'date': e.get('date', ''),
            'flags': list(e.get('flags') or []),
            'verified_by': e.get('verified_by', ''), 'verified_at': e.get('verified_at', ''),
            'applicability': 'unestablished',
            'applicability_note': ('same-row arithmetic only; interval provenance, assay and unit '
                                   'compatibility not independently confirmed'),
            'cautions': _cautions(e),
            'review_status': 'pharmacist_review_required'}
    if not structured:
        return {**base, 'status': 'cannot_assess',
                'reasons': ['result or reference interval not recorded in an explicit numeric form']}
    operands = {'raw_value': structured.get('raw_value', ''),
                'raw_interval': structured.get('raw_interval', ''),
                'unit': structured.get('unit', ''),
                'value_exact': structured.get('value_exact', ''),
                'interval_low_exact': structured.get('interval_low_exact', ''),
                'interval_high_exact': structured.get('interval_high_exact', ''),
                'interval_low_inclusive': structured.get('interval_low_inclusive'),
                'interval_high_inclusive': structured.get('interval_high_inclusive'),
                'basis': structured.get('basis', '')}
    # Defensive fail-closed: a missing unit or any recorded undetermined
    # reason blocks an observation regardless of the supplied position, even
    # if a future caller hands this check an inconsistent structured row.
    defensive = []
    if not str(structured.get('unit', '')).strip():
        defensive.append('unit not recorded')
    if structured.get('undetermined_reason'):
        defensive.extend(r for r in structured['undetermined_reason'].split('; ') if r)
    if defensive:
        return {**base, **operands, 'status': 'cannot_assess', 'reasons': defensive}
    position = structured.get('range_position')
    if position == 'undetermined':
        reasons = [r for r in structured.get('undetermined_reason', '').split('; ') if r]
        return {**base, **operands, 'status': 'cannot_assess',
                'reasons': reasons or ['range position could not be determined']}
    if position not in ('below', 'within', 'above'):
        # Fail closed: unknown or malformed positions never become observations.
        return {**base, **operands, 'status': 'cannot_assess',
                'reasons': ['unrecognised range position %r' % (position,)]}
    status = {'below': 'below_stated_interval',
              'within': 'within_stated_interval',
              'above': 'above_stated_interval'}[position]
    return {**base, **operands, 'status': status, 'reasons': [],
            'detail': ('%s %s is arithmetically %s the interval %s stated on the same '
                       'laboratory row' % (e.get('test', 'Result'), structured.get('raw_value', ''),
                                           'within' if position == 'within' else position,
                                           structured.get('raw_interval', ''))).strip()}


CHECKS = (('lab_range_position', check_lab_range_position),)


def run(context):
    if context.get('context_snapshot_sha256') != suggestion_context.fingerprint(context):
        raise ValueError('Evidence context fingerprint mismatch')
    observations = []
    assessed = set()
    for e in _verified_pathology(context['evidence']):
        for name, check in CHECKS:
            if name == 'lab_range_position':
                observations.append(check(e))
                assessed.add(e['id'])
    unassessed = [e['id'] for e in context['evidence']
                  if e.get('kind') == 'pathology' and e['id'] not in assessed]
    return {'observations': observations, 'checks_version': VERSION,
            'review_status': 'pharmacist_review_required',
            'context_snapshot_sha256': context['context_snapshot_sha256'],
            'unassessed_pathology_ids': unassessed,
            'limitations': LIMITATIONS,
            'checked_on': context['checked_on'],
            'method': 'Deterministic same-row arithmetic only; applicability unestablished; no external normal ranges, clinical rules or thresholds.'}


def for_patient(conn, patient):
    context = suggestion_context.build(conn, patient)
    result = run(context)
    if suggestion_context.build(conn, patient)['context_snapshot_sha256'] != context['context_snapshot_sha256']:
        raise ValueError('Saved evidence changed during checks; reload and review')
    return result
