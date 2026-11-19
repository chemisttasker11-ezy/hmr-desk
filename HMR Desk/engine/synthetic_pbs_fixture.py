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
    # Same product under three PBS codes (different programs / prescriber codes): should collapse.
    ('9001', '1001A', 'GE', 'Examplestatin', 'Brandex', 'Tablet', 'Tablet 20 mg', '30', 'ORAL'),
    ('9002', '1002B', 'GE', 'Examplestatin', 'Brandex', 'Tablet', 'Tablet 20 mg', '30', 'ORAL'),
    ('9003', '1003C', 'S100', 'Examplestatin', 'Brandex', 'Tablet', 'Tablet 20 mg', '30', 'ORAL'),
    # Different strength, pack and brand: must stay separate.
    ('9004', '1004D', 'GE', 'Examplestatin', 'Brandex', 'Tablet', 'Tablet 40 mg', '30', 'ORAL'),
    ('9005', '1005E', 'GE', 'Examplestatin', 'Brandex', 'Tablet', 'Tablet 20 mg', '90', 'ORAL'),
    ('9006', '1006F', 'GE', 'Examplestatin', 'Otherbrand', 'Tablet', 'Tablet 20 mg', '30', 'ORAL'),
    # Release type differs in the source's own form text: must stay separate.
    ('9007', '1007G', 'GE', 'Examplestatin', 'Brandex', 'Tablet', 'Tablet 20 mg (modified release)', '30', 'ORAL'),
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
