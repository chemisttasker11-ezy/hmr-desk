"""Pixel-and-text comparison utility synthetic regression without patient documents."""
import importlib.util
from pathlib import Path

import fitz


def visual():
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'compare-hmr-visual.py'
    spec = importlib.util.spec_from_file_location('visual_compare',script)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pdf(path, text='SYNTHETIC PAGE', count=1):
    with fitz.open() as doc:
        for i in range(count):
            page=doc.new_page(width=595,height=842)
            page.insert_text((70,70),text+' '+str(i))
        doc.save(path)


def test_identical_page_geometry_and_raster_match(tmp_path):
    before=tmp_path/'approved.pdf'
    generated=tmp_path/'generated.pdf'
    pdf(before)
    pdf(generated)
    result=visual().compare_pages(before,generated,tmp_path/'visual','short')
    assert result['same_page_count']
    assert result['pages'][0]['same_page_size']
    assert result['pages'][0]['same_text_order']
    assert result['pages'][0]['pixel_difference_ratio']==0
    assert (tmp_path/'visual'/'short-comparison.json').is_file()
    assert result['owner_signoff']=='NOT RECORDED'


def test_content_drift_is_detected_without_claiming_clinical_approval(tmp_path):
    before=tmp_path/'approved.pdf'
    generated=tmp_path/'generated.pdf'
    pdf(before,'SYNTHETIC PAGE',2)
    pdf(generated,'CHANGED SYNTHETIC TEXT',3)
    result=visual().compare_pages(before,generated,tmp_path/'visual','long')
    assert result['same_page_count'] is False
    assert result['pages'][0]['same_text_order'] is False
    assert result['pages'][0]['pixel_difference_ratio']>0
    assert result['pages'][-1]['missing_page']
    assert result['visual_review_required'] is True
