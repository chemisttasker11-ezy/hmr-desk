"""Fictional PBS API CSV bulk ZIP for tests and local synthetic setups.

Every drug and brand name here is invented. The column set is the importer's required
columns plus the form/pack columns the grouping reads; it is a contract fixture, not a
copy of any real schedule. Run as a script to write a synthetic medicine-reference file:
    python synthetic_pbs_fixture.py OUT_DIR   (writes OUT_DIR/medicine-reference.sqlite)
"""
import csv, io, sys, zipfile
from pathlib import Path

SCHEDULE = '2026-11-01'
ITEM_COLS = ['li_item_id', 'pbs_code', 'program_code', 'drug_name', 'li_drug_name', 'brand_name', 'li_form', 'schedule_form',
             'pack_size', 'manner_of_administration', 'schedule_code', 'brand_substitution_group_id',
             'originator_brand_indicator', 'benefit_type_code']
# (li_item_id, pbs_code, program, drug, brand, li_form, schedule_form, pack, route)
ITEMS = [
    # Shapes follow the real items.csv aggregate: li_form = form + strength (+ presentation),
    # schedule_form = "<strength> <form>, <pack count>". Same product under three PBS codes: collapse.
    ('9001', '1001A', 'GE', 'Examplestatin', 'Brandex', 'Tablet 20 mg', '20 mg tablet, 30', '30', 'ORAL'),
    ('9002', '1002B', 'GE', 'Examplestatin', 'Brandex', 'Tablet 20 mg', '20 mg tablet, 30', '30', 'ORAL'),
    ('9003', '1003C', 'S100', 'Examplestatin', 'Brandex', 'Tablet 20 mg', '20 mg tablet, 30', '30', 'ORAL'),
    # Same product, different pack count (schedule_form differs only by the trailing count): collapse.
    ('9005', '1005E', 'GE', 'Examplestatin', 'Brandex', 'Tablet 20 mg', '20 mg tablet, 90', '90', 'ORAL'),
    # Different strength, brand or release type: stay separate.
    ('9004', '1004D', 'GE', 'Examplestatin', 'Brandex', 'Tablet 40 mg', '40 mg tablet, 30', '30', 'ORAL'),
    ('9006', '1006F', 'GE', 'Examplestatin', 'Otherbrand', 'Tablet 20 mg', '20 mg tablet, 30', '30', 'ORAL'),
    ('9007', '1007G', 'GE', 'Examplestatin', 'Brandex', 'Tablet 20 mg (modified release)', '20 mg modified release tablet, 30', '30', 'ORAL'),
    # Device wording in li_form is a material presentation difference: stays separate.
    ('9010', '1010K', 'GE', 'Examplepen', 'Penbrand', 'Injection 40 mg in 0.4 mL pre-filled pen', '40 mg/0.4 mL injection, 2 x 0.4 mL pen devices', '2', 'SUBCUTANEOUS'),
    ('9011', '1011L', 'GE', 'Examplepen', 'Penbrand', 'Injection 40 mg in 0.4 mL pre-filled syringe', '40 mg/0.4 mL injection, 2 x 0.4 mL syringes', '2', 'SUBCUTANEOUS'),
    # Uncertain metadata (no form text): never grouped.
    ('9008', '1008H', 'GE', 'Samplecor', 'Corbrand', '', '', '', ''),
    ('9009', '1009J', 'GE', 'Samplecor', 'Corbrand', '', '', '', ''),
]


def _csv(cols, rows):
    out = io.StringIO(newline='')
    w = csv.writer(out); w.writerow(cols); w.writerows(rows)
    return out.getvalue()


def build_zip(path, release='SYN202611'):
    items = [[i[0], i[1], i[2], i[3], i[3], i[4], i[5], i[6], i[7], i[8], release, 'G' + i[0], 'N', 'U'] for i in ITEMS]
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('items.csv', _csv(ITEM_COLS, items))
        z.writestr('schedules.csv', _csv(['schedule_code', 'effective_date'], [[release, SCHEDULE]]))
        z.writestr('amt-items.csv', _csv(['li_item_id', 'concept_type_code', 'amt_code', 'non_amt_code', 'schedule_code'], []))
        z.writestr('restrictions.csv', _csv(['res_code', 'schedule_code'], []))
        z.writestr('item-restriction-relationships.csv', _csv(['pbs_code', 'res_code', 'benefit_type_code', 'schedule_code'], []))
    return release


def build_reference(out_dir, release='SYN202611'):
    """Import the fictional ZIP through the real importer into out_dir/medicine-reference.sqlite."""
    import datetime as dt
    from medicine_data import catalog, pbs
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / 'synthetic-pbs.zip'
    build_zip(zip_path, release)
    db_path = out_dir / 'medicine-reference.sqlite'
    conn = catalog.connect(db_path)
    pbs.load(conn, zip_path, release, 'https://example.invalid/synthetic-pbs', today=dt.date(2026, 11, 19))
    catalog.build_search_index(conn)
    conn.close()
    return db_path


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    print(build_reference(sys.argv[1]))
