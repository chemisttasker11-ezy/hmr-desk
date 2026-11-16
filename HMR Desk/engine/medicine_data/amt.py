"""AMT v4 RF2 Snapshot import. Uses refset membership, not retired v3 roots.

Read only locally downloaded licensed ZIPs. Preserve all strength role groups and
concrete values; never guess units/brand/form by splitting display strings.
"""
import io
import json
import re
from pathlib import PurePosixPath
import zipfile
from .catalog import add_medicine, snapshot

REFSETS = {
    '929360061000036106': 'MP', '929360071000036103': 'MPUU',
    '929360081000036101': 'MPP', '929360021000036102': 'TP',
    '929360031000036100': 'TPUU', '929360041000036105': 'TPP',
    '929360051000036108': 'CTPP',
}
AU_DIALECT = '32570271000036106'
PREFERRED = '900000000000548007'
SYNONYM = '900000000000013009'
IS_A = '116680003'
INFERRED = '900000000000011006'
PRODUCT_NAME = '774158006'
DOSE_FORM = '411116001'
INGREDIENTS = {'127489000', '762949000'}
STRENGTH_TYPES = {
    '732943007': 'basis_of_strength_substance',
    '999000041000168106': 'total_quantity_value',
    '999000051000168108': 'total_quantity_unit',
    '999000021000168100': 'concentration_value',
    '999000031000168102': 'concentration_unit',
    '1142142004': 'pack_size_value', '774163005': 'pack_size_unit',
}


MAX_RF2_LINE_CHARS = 1_000_000


def rf2_rows(stream):
    """One physical RF2 TSV line per record. Quotes/backslashes are literal data.

    RF2 is tab-delimited, not CSV-quoted. Never let a leading quote join lines
    or strip quotes used by concrete-value strings. Preserve empty fields.
    """
    def line():
        value = stream.readline(MAX_RF2_LINE_CHARS + 1)
        if len(value) > MAX_RF2_LINE_CHARS:
            raise ValueError('RF2 physical line exceeds supported bound')
        return value

    header = line()
    if not header:
        raise ValueError('Missing RF2 header')
    names = header.rstrip('\r\n').split('\t')
    if not all(names) or len(set(names)) != len(names) or 'active' not in names:
        raise ValueError('Invalid RF2 header')
    while True:
        raw = line()
        if not raw:
            break
        values = raw.rstrip('\r\n').split('\t')
        if len(values) != len(names) or any('\r' in v or '\n' in v or '\x00' in v for v in values):
            raise ValueError('Malformed RF2 TSV field count or control character')
        yield dict(zip(names, values))


def load(db, path, release, url, *, row_counts=None):
    with zipfile.ZipFile(path) as z:
        members = [i for i in z.infolist() if '/Snapshot/' in '/' + i.filename
                   and i.filename.endswith('.txt') and not i.is_dir()]
        if not members or sum(i.file_size for i in members) > 8_000_000_000:
            raise ValueError('Expected RF2 Snapshot archive (not Full or Delta) of supported size')

        def rows(prefix):
            found = False
            for info in members:
                if not PurePosixPath(info.filename).name.startswith(prefix):
                    continue
                found = True
                with z.open(info) as stream:
                    count = 0
                    for row in rf2_rows(io.TextIOWrapper(stream, encoding='utf-8-sig', newline='')):
                        count += 1
                        if row.get('active') == '1':
                            yield row
                    if row_counts is not None:
                        previous = row_counts.setdefault(info.filename, count)
                        if previous != count:
                            raise ValueError('RF2 row count changed between scans')
            if not found:
                raise ValueError(f'Missing RF2 Snapshot component {prefix}')

        membership = {}
        for row in rows('der2_Refset_'):
            if row['refsetId'] in REFSETS:
                membership.setdefault(row['referencedComponentId'], set()).add(REFSETS[row['refsetId']])
        if not membership:
            raise ValueError('No AMT seven-box refset members found')
        active = set()
        for row in rows('sct2_Concept_'):
            if row['id'] in membership:
                active.add(row['id'])
        if not active:
            raise ValueError('No active AMT concepts')
        rels = {}
        needed = set(active)
        for prefix in ('sct2_Relationship_', 'sct2_RelationshipConcreteValues_'):
            for row in rows(prefix):
                if row['sourceId'] not in active or row.get('characteristicTypeId') != INFERRED:
                    continue
                rels.setdefault(row['sourceId'], []).append(row)
                needed.add(row['typeId'])
                if 'destinationId' in row:
                    needed.add(row['destinationId'])
        preferred = set()
        for row in rows('der2_cRefset_Language'):
            if row['refsetId'] == AU_DIALECT and row.get('acceptabilityId') == PREFERRED:
                preferred.add(row['referencedComponentId'])
        terms, aliases = {}, {}
        for row in rows('sct2_Description_'):
            cid = row['conceptId']
            if cid not in needed or row.get('languageCode') != 'en':
                continue
            if row['typeId'] == SYNONYM:
                aliases.setdefault(cid, []).append(row['term'])
                if row['id'] in preferred:
                    if cid in terms and terms[cid] != row['term']:
                        raise ValueError(f'Multiple active Australian preferred terms for {cid}')
                    terms[cid] = row['term']
        missing = active - terms.keys()
        if missing:
            raise ValueError(f'{len(missing)} active AMT concepts lack Australian preferred terms; check combined release')
        if not re.fullmatch(r'\d{8}', release):
            raise ValueError('AMT release must be YYYYMMDD from the downloaded release')
        # Bind provenance to the requested release instead of accepting an
        # arbitrary label on an older ZIP.
        if not any(release in PurePosixPath(i.filename).name for i in members):
            raise ValueError('AMT release date not present in Snapshot filenames')
        priority = ['CTPP', 'TPP', 'TPUU', 'TP', 'MPP', 'MPUU', 'MP']

        def generic_parents(code):
            # Only exact modelled ancestors, at the nearest available AMT box.
            # Non-box intermediate ancestors are not inferred or guessed.
            visited, frontier = {code}, [code]
            while frontier:
                following, matches = [], []
                for node in frontier:
                    for rel in rels.get(node, []):
                        target = rel.get('destinationId')
                        if rel['typeId'] != IS_A or target in visited:
                            continue
                        visited.add(target)
                        if target in active and membership[target] & {'MP', 'MPUU', 'MPP'}:
                            matches.append(target)
                        elif target in active:
                            following.append(target)
                if matches:
                    return sorted(set(matches))
                frontier = following
            return []
        with snapshot(db, 'amt', release, path, url):
            for code in sorted(active):
                relations = rels.get(code, [])
                brands, forms, ingredients, groups = [], [], [], {}
                for rel in relations:
                    kind = rel['typeId']
                    dest = rel.get('destinationId')
                    term = terms.get(dest)
                    if kind == PRODUCT_NAME and term:
                        brands.append(term)
                    if kind == DOSE_FORM and term:
                        forms.append(term)
                    if kind in INGREDIENTS and term:
                        ingredients.append(term)
                    if kind in STRENGTH_TYPES:
                        groups.setdefault(rel['relationshipGroup'], []).append({
                            'attribute': STRENGTH_TYPES[kind], 'type_id': kind,
                            'destination_id': dest, 'term': term, 'value': rel.get('value')})
                box = next(b for b in priority if b in membership[code])
                details = {'refsets': sorted(membership[code]), 'relationships': relations,
                           'ingredient_names': sorted(set(ingredients)),
                           'generic_ancestor_codes': generic_parents(code),
                           'pbs_status': 'unknown', 'originator_status': 'unknown',
                           'market_availability': 'unknown'}
                # Names are extracted only when explicitly modelled. A missing
                # property stays missing; complete preferred term remains searchable.
                add_medicine(db, 'amt', code, terms[code], box,
                             generic=(terms[code] if box in ('MP', 'MPUU', 'MPP') else
                                      terms[details['generic_ancestor_codes'][0]] if len(details['generic_ancestor_codes']) == 1 else None),
                             brand=' + '.join(sorted(set(brands))) or None,
                             form='; '.join(sorted(set(forms))) or None,
                             strengths=[{'group': k, 'attributes': v} for k, v in sorted(groups.items())],
                             details=details, aliases=aliases.get(code, []))
