"""Versioned canonical model preserves unknown/actual and provenance separately."""
import copy

import pytest

import clinical_snapshot


def sample():
    identity={'name':'Synthetic Person','gp':'Dr Example','dob':'1940-01-01'}
    interview={
        'conditions':'Synthetic condition','allergies':'',
        'meds':[['Medicine A 5 mg','one daily','two daily','Test indication','patient note']],
        'other_meds':[['Synthetic supplement','occasional','','']],
        'details':{'meds':[{'use_status':'taking','as_instructed':False,'prn_use':'',
                            'packed':'packed'}],
                   'other_meds':[{'use_status':'taking','kind':'OTC'}]},
        'consent':{'signed':False},
    }
    pathology={'records':[{'id':'a'*32,'test':'Creatinine','value':'98',
                           'unit':'umol/L','sample_date':'2026-11-01',
                           'source':'synthetic.pdf page 2','reference_interval':'',
                           'verified':True}],
               'verification':{}}
    report={'issues':[{'title':'Reconcile medicine',
                       'rec':'Pharmacist GP review','rationale':'Synthetic rationale'}]}
    return identity,interview,pathology,report


def test_legacy_pathology_verified_flag_without_reviewer_stays_unconfirmed():
    args=sample()
    out=clinical_snapshot.canonical(*args)
    assert out['schema_version']==1
    assert out['pathology'][0]['verification']=='unconfirmed'
    assert out['allergies']['state']=='unknown'
    assert out['medication_use'][0]['prescribed_or_reported_directions']=='one daily'
    assert out['medication_use'][0]['actual_directions']=='two daily'
    assert out['medication_use'][0]['packed']=='packed'
    assert out['medication_use'][1]['use_status']=='taking'
    assert out['findings'][0]['status']=='pharmacist_review_required'


def test_confirmed_none_differs_from_unknown_and_digests_are_deterministic():
    args=sample()
    before=copy.deepcopy(args)
    state={'clinical_review':{'confirmed':True,'source_page':1,
                               'reviewed_by':'Synthetic Pharmacist',
                               'allergies_status':'explicit_none'}}
    confirmed=clinical_snapshot.canonical(*args,referral_source=state)
    unknown=clinical_snapshot.canonical(*args)
    assert confirmed['allergies']['confirmed_negative'] is True
    assert unknown['allergies']['confirmed_negative'] is False
    assert clinical_snapshot.digest(confirmed)!=clinical_snapshot.digest(unknown)
    assert args==before


def test_missing_actual_medicine_details_retained_as_unconfirmed():
    identity, interview, path, report=sample()
    interview['details']['meds']=[]
    out=clinical_snapshot.canonical(identity,interview,path,report)
    assert out['medication_use'][0]['use_status']=='unknown'
    assert out['medication_use'][0]['verification']=='pharmacist_interview_record'
    interview['meds'][0][2]=''
    out=clinical_snapshot.canonical(identity,interview,path,report)
    assert out['medication_use'][0]['verification']=='unconfirmed_actual_use'


def test_nonstring_clinical_text_rejected_instead_of_coercing():
    args=list(sample())
    args[1]['allergies']=['no allergies inferred']
    with pytest.raises(ValueError,match='Invalid clinical snapshot text'):
        clinical_snapshot.canonical(*args)
