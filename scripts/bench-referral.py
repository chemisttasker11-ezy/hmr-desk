"""Synthetic searchable referral throughput benchmark (no patient information).

Measures PyMuPDF plus conservative referral review on Windows. Deliberately
does not claim handwritten/scanned OCR speed or full UI latency.
"""
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

import fitz

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'HMR Desk'/'engine'))

import db
import referral_entry


class SyntheticParser:
    def classify(self,text):
        return 'referral','',['Synthetic source; all fields require review']
    def extract_fields(self,text):
        return {'name':'Synthetic Benchmark','dob':'1950-01-01'},[]
    def ocr_pdfs(self,files):
        return {}


def generate(folder,pages):
    target=folder/f'synthetic-{pages}-pages.pdf'
    with fitz.open() as doc:
        for index in range(pages):
            page=doc.new_page()
            page.insert_text((50,65),f'SYNTHETIC HMR referral page {index+1} - testing extracted text only, no actual clinical data')
        doc.save(target)
    return target


def percentile(items,fraction):
    sorted_items=sorted(items)
    index=max(0,min(len(items)-1,round((len(items)-1)*fraction)))
    return round(sorted_items[index],4)


def main():
    with tempfile.TemporaryDirectory(prefix='hmr-referral-perf-') as directory:
        tmp=Path(directory)
        db.BASE=str(tmp/'workspace')
        db.DATA_DIR=str(tmp/'data')
        (tmp/'workspace').mkdir()
        referral_entry.parser=lambda:SyntheticParser()
        results=[]
        for pages in (5,15,50):
            path=generate(tmp,pages)
            times=[]
            for repetition in range(5):
                conn=db.connect(str(tmp/'data'/f'measure-{pages}-{repetition}.db'))
                started=time.perf_counter()
                row=referral_entry.review(conn,[str(path)])['rows'][0]
                times.append(time.perf_counter()-started)
                conn.close()
                if row['status']!='review' or row['sha256']=='':
                    raise RuntimeError('Synthetic referral failed to produce reviewable source')
            results.append({
                'pages':pages,'bytes':path.stat().st_size,'repetitions':5,
                'p50_seconds':percentile(times,0.5),'p95_seconds':percentile(times,0.95),
                'max_seconds':round(max(times),4),
                'ocr_included':False,'ui_included':False,
            })
    output=Path(os.environ.get('HMR_M2_BENCH_OUTPUT',str(root/'m2-referral-performance.json')))
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'synthetic_only':True,'os':platform.platform(),
            'python':platform.python_version(),'method':'searchable PDF text only',
            'status':'measured engineering baseline; Windows 11 end-to-end performance still required',
            'measurements':results}
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'synthetic':True,'results':results}))


if __name__=='__main__':
    main()
