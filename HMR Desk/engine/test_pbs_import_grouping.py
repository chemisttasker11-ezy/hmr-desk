"""Grouping verified on rows produced by the real pbs.py importer from a fictional ZIP."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import db
import medicine_reference as ref
import synthetic_pbs_fixture as fx


def installed(tmp):
    db.DATA_DIR = str(tmp)
    path = fx.build_reference(tmp)
    return path


def test_importer_rows_group_exactly_the_equivalent_entries():
    with tempfile.TemporaryDirectory() as t:
        installed(t)
        out = ref.search_grouped('examplestatin')
        got = sorted((g['label'], g['count']) for g in out['groups'])
        assert got == sorted([('Brandex | Tablet 20 mg | oral', 4),
                              ('Brandex | Tablet 40 mg | oral', 1),
                              ('Brandex | Tablet 20 mg (modified release) | oral', 1),
                              ('Otherbrand | Tablet 20 mg | oral', 1)])
        assert len({g['label'] for g in out['groups']}) == len(out['groups'])  # no two lines read the same
        assert len(out['groups']) == 4
        assert len(out['results']) == 7
        pens = ref.search_grouped('examplepen')['groups']
        assert sorted(g['label'] for g in pens) == ['Penbrand | Injection 40 mg in 0.4 mL pre-filled pen | subcutaneous', 'Penbrand | Injection 40 mg in 0.4 mL pre-filled syringe | subcutaneous']


def test_no_code_in_any_label_and_incomplete_entries_stay_separate():
    with tempfile.TemporaryDirectory() as t:
        installed(t)
        out = ref.search_grouped('samplecor')
        assert len(out['groups']) == 2 and all(not g['grouped'] for g in out['groups'])
        for g in out['groups']:
            assert '1008H' not in g['label'] and '1009J' not in g['label']
            assert g['label'].endswith('(source details incomplete, entry kept separate)')
        every = ref.search_grouped('brandex')['groups']
        assert all(c not in g['label'] for g in every for c in ('1001A', '1002B', '1003C', '1004D', '1005E', '1007G'))


def test_chosen_reference_is_a_real_catalogue_row_and_pick_roundtrips():
    with tempfile.TemporaryDirectory() as t:
        installed(t)
        group = max(ref.search_grouped('examplestatin')['groups'], key=lambda g: g['count'])
        rep = group['listings'][0]
        assert ref.pick(rep['source'], rep['code'])['code'] == rep['code']
        assert rep['code'] == min(l['code'] for l in group['listings'])


def test_report_reference_text_hides_pbs_code_but_other_sources_keep_theirs():
    import interview
    pbs_meta = {'reference': {'source': 'pbs', 'code': 'GE:1001A:9001', 'display': 'Brandex | Tablet 20 mg | oral', 'release': 'SYN202611'}}
    text = interview.reference_text(pbs_meta)
    assert text == 'Reference: Brandex | Tablet 20 mg | oral (PBS, release SYN202611)'
    assert '1001A' not in text and '9001' not in text
    amt = {'reference': {'source': 'amt', 'code': '1001', 'display': 'Examplestatin 20 mg tablet', 'release': '20260101'}}
    assert 'AMT 1001' in interview.reference_text(amt)
    assert interview.reference_text({}) == ''
