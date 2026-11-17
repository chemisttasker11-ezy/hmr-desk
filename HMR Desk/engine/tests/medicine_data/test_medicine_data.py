"""Synthetic fixtures only. No licensed medicine descriptions or patient data."""
import csv
import datetime as dt
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from medicine_data import amt, artg, catalog, pbs, sigs


def csv_text(rows, delimiter=','):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), delimiter=delimiter)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def pbs_zip(path, bad=False, future=False, unknown_indicator=False):
    item = {'li_item_id': 'SYNTHETIC_ITEM', 'pbs_code': 'TEST001', 'program_code': 'TEST',
            'drug_name': 'Synthetic ingredient', 'brand_name': 'Synthetic brand', 'schedule_code': 'TEST',
            'brand_substitution_group_id': 'SYNTHETIC_GROUP', 'originator_brand_indicator': '?' if unknown_indicator else 'N',
            'schedule_form': 'Synthetic form, not a medicine'}
    if bad:
        del item['pbs_code']
    tables = {
        'items': [item],
        'schedules': [{'schedule_code': 'TEST', 'effective_date': '2999-01-01' if future else '2026-01-01'}],
        'amt-items': [{'li_item_id': 'SYNTHETIC_ITEM', 'concept_type_code': 'TPP', 'amt_code': 'SYNTHETIC_AMT', 'non_amt_code': 'null', 'schedule_code': 'TEST'}],
        'restrictions': [{'res_code': 'SYNTHETIC_RESTRICTION', 'schedule_code': 'TEST', 'schedule_html_text': '<p>Synthetic only</p>'}],
        'item-restriction-relationships': [{'pbs_code': 'TEST001', 'res_code': 'SYNTHETIC_RESTRICTION', 'benefit_type_code': 'R', 'schedule_code': 'TEST'}],
    }
    with zipfile.ZipFile(path, 'w') as z:
        for name, rows in tables.items():
            z.writestr('tables_as_csv/' + name + '.csv', csv_text(rows))


def rf2_zip(path, missing_preferred=False, inactive=False):
    """RF2 shape with clearly synthetic concept IDs; reference metadata is real."""
    base = dict(effectiveTime='20260131', active='1', moduleId='SYNTHETIC_MODULE')
    cids = ['SYNTHETIC_PRODUCT', 'SYNTHETIC_BRAND', 'SYNTHETIC_FORM', 'SYNTHETIC_INGREDIENT', 'SYNTHETIC_UNIT']
    concepts = [dict(id=c, **{**base, 'active': '0' if inactive and c == cids[0] else '1'}, definitionStatusId='TEST') for c in cids]
    descriptions = [dict(id='DESC_' + c, **base, conceptId=c, languageCode='en', typeId=amt.SYNONYM,
                         term=c.replace('_', ' ').title(), caseSignificanceId='TEST') for c in cids]
    lang = [dict(id='LANG_' + c, **base, refsetId=amt.AU_DIALECT,
                 referencedComponentId='DESC_' + c, acceptabilityId=amt.PREFERRED) for c in cids if not (missing_preferred and c == cids[0])]
    # Another dialect preference MUST NOT replace the Australian term.
    descriptions.append(dict(id='DESC_US', **base, conceptId=cids[0], languageCode='en', typeId=amt.SYNONYM, term='Synthetic US alias', caseSignificanceId='TEST'))
    lang.append(dict(id='LANG_US', **base, refsetId='900000000000509007', referencedComponentId='DESC_US', acceptabilityId=amt.PREFERRED))
    refs = [dict(id='MEMBER_TEST', **base, refsetId='929360031000036100', referencedComponentId=cids[0])]
    rels = [dict(id='REL_' + str(i), **base, sourceId=cids[0], destinationId=dest,
                 relationshipGroup='1' if i >= 2 else '0', typeId=kind,
                 characteristicTypeId=amt.INFERRED, modifierId='TEST') for i, (kind, dest) in enumerate([
                     (amt.PRODUCT_NAME,cids[1]), (amt.DOSE_FORM,cids[2]),
                     ('762949000',cids[3]), ('999000051000168108',cids[4])])]
    concrete = [dict(id='CONCRETE', **base, sourceId=cids[0], value='#5', relationshipGroup='1', typeId='999000041000168106', characteristicTypeId=amt.INFERRED, modifierId='TEST')]
    with zipfile.ZipFile(path, 'w') as z:
        for prefix, rows in [('sct2_Concept_',concepts), ('sct2_Description_', descriptions), ('der2_cRefset_Language',lang),
                             ('der2_Refset_',refs), ('sct2_Relationship_',rels), ('sct2_RelationshipConcreteValues_',concrete)]:
            z.writestr('RF2/Snapshot/' + prefix + 'Snapshot_AU_20260131.txt', csv_text(rows, '\t'))


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = catalog.connect(self.root / 'medicine-reference.sqlite')

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def pbs_load(self, path):
        pbs.load(self.db, path, 'TEST', 'https://example.invalid/synthetic', today=dt.date(2026,11,16))

    def test_pbs_real_shape(self):
        path = self.root / 'pbs.zip'; pbs_zip(path); self.pbs_load(path)
        result = catalog.search(self.db, 'synthetic brand')[0]
        data = json.loads(result['details_json'])
        self.assertIs(data['originator_for_price_disclosure'], False)
        self.assertEqual(data['generic_status'], 'unknown')
        self.assertEqual(data['amt_links'][0]['amt_code'], 'SYNTHETIC_AMT')
        self.assertEqual(result['release'], 'TEST')
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_row').fetchone()[0],5)

    def test_pbs_idempotent(self):
        path = self.root / 'pbs.zip'; pbs_zip(path)
        self.pbs_load(path); self.pbs_load(path)
        self.assertEqual(self.db.execute('SELECT count(*) FROM medicine').fetchone()[0],1)

    def test_pbs_failed_import_rolls_back(self):
        path = self.root / 'pbs.zip'; pbs_zip(path); self.pbs_load(path)
        old = self.db.execute('SELECT sha256 FROM source_release').fetchone()[0]
        pbs_zip(path, unknown_indicator=True)
        with self.assertRaises(ValueError):self.pbs_load(path)
        self.assertEqual(len(catalog.search(self.db,'synthetic')),1)
        self.assertEqual(self.db.execute('SELECT sha256 FROM source_release').fetchone()[0],old)

    def test_pbs_missing_columns_rejected(self):
        path = self.root / 'pbs.zip'; pbs_zip(path,bad=True)
        with self.assertRaises(ValueError):self.pbs_load(path)

    def test_future_schedule_rejected(self):
        path = self.root / 'pbs.zip'; pbs_zip(path,future=True)
        with self.assertRaises(ValueError):self.pbs_load(path)

    def test_literal_sql_search(self):
        path = self.root / 'pbs.zip'; pbs_zip(path); self.pbs_load(path)
        self.assertEqual(catalog.search(self.db,"%'; DROP TABLE medicine; --"),[])
        self.assertEqual(catalog.search(self.db,'%_'),[])
        self.assertEqual(catalog.search(self.db,'s'),[])

    def test_reference_db_rejects_patient_db(self):
        with self.assertRaises(ValueError):catalog.connect(self.root / 'hmr.db')
        patient = self.root / 'other.sqlite'
        db = sqlite3.connect(patient); db.execute('CREATE TABLE patients(id)'); db.close()
        with self.assertRaises(ValueError):catalog.connect(patient)

    def test_future_schema_refused(self):
        target = self.root / 'future.sqlite'
        db=sqlite3.connect(target); db.execute('PRAGMA user_version=999'); db.close()
        with self.assertRaises(ValueError):catalog.connect(target)

    def test_amt_v4_concrete_strength_and_dialect(self):
        path=self.root/'rf2.zip';rf2_zip(path)
        amt.load(self.db,path,'20260131','https://example.invalid/synthetic')
        row=catalog.search(self.db,'synthetic product')[0]
        self.assertEqual(row['kind'],'TPUU')
        self.assertEqual(row['brand_name'],'Synthetic Brand')
        self.assertEqual(row['dose_form'],'Synthetic Form')
        self.assertIsNone(row['generic_name'])  # no inferred generic from ingredient text
        self.assertEqual(json.loads(row['details_json'])['ingredient_names'],['Synthetic Ingredient'])
        strength=json.loads(row['strength_json'])
        self.assertEqual(strength[0]['group'],'1')
        self.assertIn('#5',str(strength))
        self.assertEqual(row['display'],'Synthetic Product')
        self.assertEqual(len(catalog.search(self.db,'synthetic us alias')),1)

    def test_amt_no_au_preferred_fails_closed(self):
        path=self.root/'rf2.zip';rf2_zip(path,missing_preferred=True)
        with self.assertRaises(ValueError):amt.load(self.db,path,'20260131','https://example.invalid/synthetic')

    def test_amt_inactive_concepts_not_searchable(self):
        path=self.root/'rf2.zip';rf2_zip(path,inactive=True)
        with self.assertRaises(ValueError):amt.load(self.db,path,'20260131','https://example.invalid/synthetic')

    def test_amt_release_label_mismatch(self):
        path=self.root/'rf2.zip';rf2_zip(path)
        with self.assertRaises(ValueError):amt.load(self.db,path,'20260228','https://example.invalid/synthetic')

    def test_artg_map_and_medicine_filter(self):
        path=self.root/'artg.csv'
        rows=[{'ARTG ID':'SYNTHETIC_1','Product Name':'Synthetic vitamin, not a medicine','Therapeutic Type':'Medicine','ARTG Status':'Active'},
              {'ARTG ID':'SYNTHETIC_2','Product Name':'Synthetic device','Therapeutic Type':'Medical Device','ARTG Status':'Active'},
              {'ARTG ID':'SYNTHETIC_3','Product Name':'Synthetic cancelled','Therapeutic Type':'Medicine','ARTG Status':'Cancelled'}]
        path.write_text(csv_text(rows),encoding='utf-8-sig')
        artg.load(self.db,path,'TEST','https://example.invalid/synthetic')
        result=catalog.search(self.db,'synthetic')
        self.assertEqual(len(result),1)
        self.assertEqual(json.loads(result[0]['details_json'])['pbs_status'],'unknown')

    def test_artg_unknown_header_fails(self):
        path=self.root/'artg.csv';path.write_text('unexpected\nvalue\n')
        with self.assertRaises(ValueError):artg.load(self.db,path,'TEST','https://example.invalid/synthetic')

    def test_artg_empty_snapshot_preserves_previous(self):
        path=self.root/'artg.csv';path.write_text(csv_text([{'ARTG ID':'TEST','Product Name':'Synthetic item','Therapeutic Type':'Medicine','ARTG Status':'Active'}]))
        artg.load(self.db,path,'TEST','https://example.invalid/synthetic')
        path.write_text('ARTG ID,Product Name,Therapeutic Type,ARTG Status\n')
        with self.assertRaises(ValueError):artg.load(self.db,path,'EMPTY','https://example.invalid/synthetic')
        self.assertEqual(len(catalog.search(self.db,'synthetic')),1)


class SigTests(unittest.TestCase):
    def test_library_integrity(self):
        entries=sigs.library()
        self.assertTrue(100 <= len(entries) <= 300)
        self.assertEqual(len({e['id'] for e in entries}),len(entries))
        sigs.index()  # no duplicate/ambiguous aliases
        self.assertEqual({e['category'] for e in entries},{'frequency','timing','instruction'})

    def test_bd_safe_render(self):
        result=sigs.parse('BD; with food')
        self.assertEqual(result['structured']['times_per_day'],2)
        self.assertEqual(result['patient_text'],'twice a day; with food')
        self.assertTrue(result['review_required'])

    def test_unsafe_and_ambiguous_never_actionable(self):
        for text in ('OD','O.D.','QD','Q4H','4/24','HS','D/C','QDS','TIW','2 hrly','tid'):
            with self.subTest(text=text):
                result=sigs.parse(text)
                self.assertEqual(result['status'],'unresolved')
                self.assertIsNone(result['structured'])
                self.assertIsNone(result['patient_text'])

    def test_unknown_text_not_dropped(self):
        result=sigs.parse('BD; take a mystery dose')
        self.assertIn('take a mystery dose',result['unknown'])
        self.assertIsNone(result['structured'])

    def test_free_text_is_not_silently_parsed(self):
        self.assertEqual(sigs.parse('take 2 tablets bd')['status'],'unresolved')

    def test_conflicting_frequencies(self):
        for text in ('BD; QID','once a day; every 12 hours','before food; after food'):
            self.assertEqual(sigs.parse(text)['status'],'unresolved')

    def test_prn_not_assigned_daily_frequency(self):
        result=sigs.parse('PRN')
        self.assertTrue(result['structured']['as_needed'])
        self.assertNotIn('times_per_day',result['structured'])
        self.assertTrue(result['warnings'])

    def test_weekly_needs_days(self):
        self.assertTrue(sigs.parse('once a week')['structured']['requires_days'])
        self.assertNotIn('times_per_day',sigs.parse('once a week')['structured'])

    def test_render_confirmation(self):
        with self.assertRaises(ValueError):sigs.render(['twice_daily'])
        self.assertEqual(sigs.render(['twice_daily','with_food'],pharmacist_confirmed=True),'twice a day; with food')
        with self.assertRaises(ValueError):sigs.render(['legacy_od'],pharmacist_confirmed=True)

    def test_render_exact_structure(self):
        self.assertEqual(sigs.render_structure({'times_per_day':2},pharmacist_confirmed=True),'twice a day')
        with self.assertRaises(ValueError):sigs.render_structure({'times_per_day':999},pharmacist_confirmed=True)
        with self.assertRaises(ValueError):sigs.render(['daily'],pharmacist_confirmed='false')

    def test_instruction_semicolon_exact_phrase(self):
        self.assertEqual(sigs.parse('Spit out after use; do not swallow')['status'],'review')

    def test_mane_nocte_full_english(self):
        self.assertEqual(sigs.parse('mane')['patient_text'],'in the morning')
        self.assertEqual(sigs.parse('nocte')['patient_text'],'at night')


if __name__ == '__main__':
    unittest.main()
