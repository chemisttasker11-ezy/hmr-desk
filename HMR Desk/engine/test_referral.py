"""Synthetic referral layouts; no cached patient text is copied here."""
import referral

summary = """Medical History
2001
Asthma
Current Medications
Zinc 5mg tablet
One daily.
\f
Page 2 of 2
Aspirin 100mg tablet
Take once daily.
Zinc 5mg tablet
One daily.
Allergies
None known.
Measurements
Height
170 cm
Weight
70 kg
BMI
24
BP
120/80
01/02/2026
eGFR
65 mL/min
Social History
Smoking: Never
Alcohol: None
Reason for referral for DMMR
Review medicines.
Ceased Medications
Drug A 10mg tablet
One daily.
Plan:
End
"""
p = referral.parse(summary)
assert p['layout'] == 'clinical summary'
assert [r[0] for r in p['meds']] == ['Zinc 5mg tablet', 'Aspirin 100mg tablet', 'Zinc 5mg tablet']
assert p['meds'][1][1] == 'Take once daily.'
assert p['conditions'] == ['Asthma'] and p['allergies'] == ['nil known']
assert all(p['obs'].values()) and '65 mL/min' in p['renal'] and '01/02/2026' in p['renal']
assert p['smoking'] == 'Never' and p['alcohol'] == 'None' and p['reason'] == 'Review medicines.'
assert len(p['ceased']) == 1
assert referral.parse('Medical History\nAsthma\n')['meds'] == []
ocr = referral.parse('DOMICILIARY MEDICATION MANAGEMENT\nCURRENT MEDICATION:\n* Drug B lOmg tablet take daily\nDrug C 2mg tablet\nl tablet daily\nAllergies:\nNone known.\n')
assert len(ocr['meds']) == 2 and ocr['meds'][0][1] == 'take daily' and ocr['meds'][1][1] == 'l tablet daily'
assert referral.layout('DOMICILIARY MEDICATION MANAGEMENT\nCURRENT MEDICATION:\nDrug D 5mg tablet') == 'HMR referral form'
assert referral.layout('Current medication as per the patient') == 'past HMR report' and referral.parse('Thank you for referring\nAllergies\nNil')['unparsed'] == []
assert referral.layout('scanned unknown text') == 'scan / other'
assert 'meds' in referral.parse('scanned unknown text\nMedications:\nDrug E 5mg tablet')['unparsed']
assert referral.parse('Current medication as per the patient\nDrug E 5mg tablet')['unparsed'] == []
assert 'meds' in referral.parse('DOMICILIARY MEDICATION MANAGEMENT\nMedications:\nUnrecognised material\n')['unparsed']
print('referral self-check ok')
