"""ARTG user-exported medicine CSV adapter. No scraping or redistribution.

Power BI exports vary. Explicit --column-map supports changed field names; fail
closed if core fields are absent. Summary exports do not promise ingredients or
strength. Never infer that every complementary/OTC product is PBS-unlisted.
"""
import csv
from .catalog import add_medicine, add_raw, snapshot

DEFAULT_COLUMNS = {
    'id': 'ARTG ID', 'name': 'Product Name', 'good_name': 'Good Name',
    'type': 'Therapeutic Type', 'status': 'ARTG Status',
    'ingredients': 'Active Ingredient', 'form': 'Dosage Form',
    'category': 'Product Category',
}


def load(db, path, release, url, column_map=None):
    columns = {**DEFAULT_COLUMNS, **(column_map or {})}
    with open(path, encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {columns[k] for k in ('id', 'name', 'type', 'status')}
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f'ARTG missing columns {required - set(reader.fieldnames or [])}; supply --column-map')
        with snapshot(db, 'artg', release, path, url):
            seen = {}
            for number, row in enumerate(reader, 1):
                if None in row:
                    raise ValueError('Malformed ARTG CSV')
                add_raw(db, 'artg', 'medicines-export', number, row)
                if row[columns['type']].strip().casefold() not in ('medicine', 'medicines'):
                    continue
                if row[columns['status']].strip().casefold() != 'active':
                    continue
                code = row[columns['id']].strip()
                name = row[columns['name']].strip() or row.get(columns['good_name'], '').strip()
                # Repeated identical rows may occur in exports. Different rows for
                # one ARTG ID must not silently overwrite multi-ingredient detail.
                if code in seen:
                    if seen[code] != row:
                        raise ValueError(f'Conflicting ARTG rows for {code}; consolidate export first')
                    continue
                seen[code] = row
                details = {'raw': row, 'pbs_status': 'unknown', 'market_availability': 'unknown',
                           'ingredients_text': row.get(columns['ingredients']),
                           'category': row.get(columns['category'])}
                add_medicine(db, 'artg', code, name, 'artg_registered_or_listed',
                             form=row.get(columns['form']), details=details)
