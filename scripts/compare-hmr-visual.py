"""Local-only clinical template DOCX/PDF visual comparison evidence.

Never upload private patient reports or rendered pages to CI. Accept synthetic
or safely de-identified owner-approved examples only. Produces PNGs and numeric
page/visual coverage results for human review; not automatic clinical approval.
"""
import argparse
import hashlib
import json
from pathlib import Path

import fitz

SCALE = 1.5
THRESHOLD = 28


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare_pages(approved, generated, output, label):
    approved = Path(approved).resolve()
    generated = Path(generated).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not approved.is_file() or not generated.is_file():
        raise FileNotFoundError('Both accepted example and generated PDF are required')
    results = {
        'fixture': label,
        'approved_pdf_sha256': file_hash(approved),
        'generated_pdf_sha256': file_hash(generated),
        'approved_page_count': None,
        'generated_page_count': None,
        'same_page_count': False,
        'pages': [],
    }
    with fitz.open(approved) as before, fitz.open(generated) as after:
        results['approved_page_count'] = before.page_count
        results['generated_page_count'] = after.page_count
        results['same_page_count'] = before.page_count == after.page_count
        for page_number in range(max(before.page_count, after.page_count)):
            item = {'page': page_number + 1, 'missing_page': False}
            if page_number >= before.page_count or page_number >= after.page_count:
                item['missing_page'] = True
                results['pages'].append(item)
                continue
            before_page = before[page_number]
            after_page = after[page_number]
            before_box = before_page.rect
            after_box = after_page.rect
            item['same_page_size'] = (abs(before_box.width-after_box.width) < 0.5 and
                                      abs(before_box.height-after_box.height) < 0.5)
            before_pix = before_page.get_pixmap(matrix=fitz.Matrix(SCALE,SCALE), alpha=False)
            after_pix = after_page.get_pixmap(matrix=fitz.Matrix(SCALE,SCALE), alpha=False)
            stem = f'{label}-{page_number + 1:02d}'
            before_pix.save(output / (stem + '-approved.png'))
            after_pix.save(output / (stem + '-generated.png'))
            before_text = '\n'.join(before_page.get_text('text').split())
            after_text = '\n'.join(after_page.get_text('text').split())
            item['same_text_order'] = before_text == after_text
            item['approved_text_sha256'] = hashlib.sha256(before_text.encode('utf-8')).hexdigest()
            item['generated_text_sha256'] = hashlib.sha256(after_text.encode('utf-8')).hexdigest()
            if before_pix.width != after_pix.width or before_pix.height != after_pix.height:
                item['pixel_difference_ratio'] = 1.0
                item['same_raster_dimensions'] = False
            else:
                item['same_raster_dimensions'] = True
                channels = before_pix.n
                first, second = before_pix.samples, after_pix.samples
                differences = 0
                pixels = before_pix.width * before_pix.height
                for i in range(0, pixels * channels, channels):
                    if any(abs(first[i+c]-second[i+c]) > THRESHOLD for c in range(channels)):
                        differences += 1
                item['pixel_difference_ratio'] = round(differences/max(1,pixels),6)
            item['approved_size_pts'] = [round(before_box.width,2),round(before_box.height,2)]
            item['generated_size_pts'] = [round(after_box.width,2),round(after_box.height,2)]
            results['pages'].append(item)
    results['visual_review_required'] = True
    results['owner_signoff'] = 'NOT RECORDED'
    (output / (label + '-comparison.json')).write_text(
        json.dumps(results,indent=2,sort_keys=True),encoding='utf-8')
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approved',required=True)
    parser.add_argument('--generated',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--label',required=True,choices=['short','long','multi-issue'])
    args=parser.parse_args()
    result=compare_pages(args.approved,args.generated,args.output,args.label)
    print(json.dumps({
        'pages_approved':result['approved_page_count'],
        'pages_generated':result['generated_page_count'],
        'same_page_count':result['same_page_count'],
        'maximum_pixel_difference_ratio':max(
            (row.get('pixel_difference_ratio',1.0) for row in result['pages']),default=1.0),
        'owner_visual_signoff_required':True,
        'local_evidence_directory':str(Path(args.output).resolve()),
    }))
    if not result['same_page_count'] or not all(
        row.get('same_page_size',False) for row in result['pages']
    ):
        raise SystemExit('Page geometry mismatch: owner visual acceptance NOT PASSED')


if __name__ == '__main__':
    main()
