"""Windows synthetic template-bound DOCX/PDF fidelity smoke.

Uses an explicitly labelled fake template created in the temporary directory.
It does not imply that the owner's real layout is available or approved.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import fitz
from docx import Document

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'HMR Desk' / 'engine'))
import pdf_export
import template_report_builder


def make_template(folder):
    doc = Document()
    sec = doc.sections[0]
    sec.header.paragraphs[0].text = 'SYNTHETIC HMR LETTERHEAD / LAYOUT TEST ONLY'
    sec.footer.paragraphs[0].text = 'SYNTHETIC HMR FOOTER / NOT FOR CLINICAL USE'
    doc.add_heading('HOME MEDICINES REVIEW / SYNTHETIC ONLY', level=1)
    for name in template_report_builder.TEXT_FIELDS:
        doc.add_paragraph('{{HMR_' + name + '}}')
    for name in template_report_builder.TABLE_FIELDS:
        doc.add_paragraph('{{HMR_' + name + '}}')
    doc.add_paragraph(template_report_builder.ISSUES_ANCHOR)
    template = folder / 'approved-hmr.docx'
    doc.save(template)
    info = {
        'version':'synthetic-ci-layout-1',
        'approved_by':'Automated synthetic fixture only',
        'approved_on':'2026-11-16',
        'sha256':hashlib.sha256(template.read_bytes()).hexdigest(),
    }
    (folder / 'approved-hmr.json').write_text(json.dumps(info))
    return template


def data(many=False):
    count = 35 if many else 2
    return {
        'assess_date':'12/11/2026', 'report_date':'16/11/2026',
        'patient':'Synthetic Test Person / no actual patient',
        'doctor':'Dr Synthetic', 'dear':'Dear Dr Synthetic,',
        'thanks':'Thank you for the referral.', 'reason':'Reconciliation',
        'intro':'Local mock interview for source testing.',
        'conditions':'No real clinical conditions stated',
        'allergies':'Unknown; verification required',
        'obs':'No genuine measurements',
        'meds':[['Synthetic medicine ' + str(i), 'Recorded use ' + str(i),
                 'Patient narrative requires pharmacist review', 'Review'] for i in range(count)],
        'otc':[['Supplement X','PRN','Mock entry']],
        'ceased':[['Synthetic ceased','Historical','Review cessation']],
        'path':[['Synthetic test','98','umol/L','Synthetic only','sample fixture.pdf page 2']],
        'issues':[{'title':'Synthetic finding ' + str(i),
                   'rec':'Pharmacist to review against genuine sources.',
                   'rationale':'This is synthetic data, not a clinical recommendation.'}
                  for i in range(3 if many else 1)],
        'followup':'Synthetic follow-up example',
    }


def main():
    converter = (root / 'vendor' / 'libreoffice' / 'program' / 'soffice.exe').resolve()
    if not converter.is_file():
        raise RuntimeError('Pinned offline converter missing')
    os.environ['HMR_PDF_CONVERTER'] = str(converter)
    temp = tempfile.mkdtemp(prefix='hmr-template-pdf-')
    pending = []
    try:
        folder = Path(temp)
        template = make_template(folder)
        assert template_report_builder.approved_template(folder)[0] == template
        for long_case in (False, True):
            stem = 'long' if long_case else 'short'
            word = folder / (stem + '.docx')
            pdf = folder / (stem + '.pdf')
            template_report_builder.render(data(long_case), word, template)
            outcome = pdf_export.convert(word, pdf)
            if outcome.get('cleanup_pending'): pending.append(outcome['cleanup_pending'])
            with fitz.open(pdf) as document:
                assert document.page_count >= (2 if long_case else 1)
                all_text = '\n'.join(page.get_text() for page in document)
                for expected in ('SYNTHETIC HMR LETTERHEAD', 'SYNTHETIC HMR FOOTER',
                                 'Synthetic Test Person', 'Synthetic finding'):
                    assert expected in all_text, expected + ' missing in ' + stem
                assert '{{HMR_' not in all_text
                # Table cells wrap inside narrow columns; compare on whitespace-normalised text.
                flat = ' '.join(all_text.split())
                needle = 'Synthetic medicine 34' if long_case else 'Synthetic medicine 1'
                assert needle in flat, needle + ' missing in ' + stem + '; text sample: ' + flat[:1500]
                if long_case:
                    import re
                    pages = [' '.join(page.get_text().split()) for page in document]
                    with_rows = [t for t in pages if 'Synthetic medicine' in t]
                    assert len(with_rows) >= 2 and all('Actual use' in t for t in with_rows), 'medicine header row not repeated on each page'
                    for i in range(35):
                        label = [k for k, t in enumerate(pages) if re.search(r'Synthetic medicine %d(?!\d)' % i, t)]
                        use = [k for k, t in enumerate(pages) if re.search(r'Recorded use %d(?!\d)' % i, t)]
                        assert len(label) == 1 and label == use, 'medicine row %d split across pages' % i
            assert word.is_file() and pdf.is_file()
    finally:
        failure = pdf_export.remove_tree(temp)
    print('PASS: synthetic short/long template DOCX and matching bundled-LibreOffice PDF pagination/text (conversion and assertions)')
    if failure or pending:
        print('CLEANUP PENDING (separate from conversion result): ' + '; '.join(pending + [temp] * bool(failure)))
        if failure: print(failure)
        sys.exit(3)
    print('CLEANUP OK')


if __name__ == '__main__':
    main()
