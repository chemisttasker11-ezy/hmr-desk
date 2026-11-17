"""Private local reference registration, never a distributable knowledge base.

The original file remains where the user selected it. Only local path/hash/edition
metadata is saved. Every read rechecks the original. No implicit clinical approval.
"""
import hashlib
import json
from pathlib import Path
import re
import fitz
import brainstorm
import db
import jobs


class ReferenceUnavailable(ValueError):
    pass


def registry_path(): return Path(db.DATA_DIR)/'local-reference.json'


def checked_path(value):
    if not isinstance(value,(str,Path)): raise ReferenceUnavailable('Choose a local PDF')
    path=Path(value)
    if not path.is_absolute() or path.suffix.lower()!='.pdf': raise ReferenceUnavailable('Choose a local PDF')
    for item in [path,*path.parents]:
        if item.is_symlink() or getattr(item.lstat(),'st_file_attributes',0)&0x400: raise ReferenceUnavailable('Linked reference path refused')
    if not path.is_file() or not 5<=path.stat().st_size<=25*1024*1024: raise ReferenceUnavailable('Invalid reference PDF size')
    return path


def inspect(path):
    path=checked_path(path)
    content=path.read_bytes()
    if not content.startswith(b'%PDF-'): raise ReferenceUnavailable('Invalid reference PDF header')
    with fitz.open(stream=content,filetype='pdf') as doc:
        if doc.needs_pass or not 1<=len(doc)<=500: raise ReferenceUnavailable('Unsupported reference PDF')
        text=' '.join(doc[i].get_text() for i in range(min(4,len(doc))));count=len(doc)
    if not re.search(r'Brainstorm',text,re.I): raise ReferenceUnavailable('Choose the Brainstorm reference PDF')
    if len(text.strip())<100: raise ReferenceUnavailable('Text-extractable reference PDF required')
    # Edition is always user-reviewed, not guessed from PDF metadata.
    return {'pdf_sha256':hashlib.sha256(content).hexdigest(),'page_count':count,'size_bytes':len(content)}


def register(body):
    if not isinstance(body,dict) or set(body)!={'path','edition','local_use_confirmed'} or body['local_use_confirmed'] is not True:
        raise ReferenceUnavailable('Confirm permission for this private local reference copy')
    edition=body['edition']
    if not isinstance(edition,str) or not edition.strip() or len(edition)>100: raise ReferenceUnavailable('Enter the edition shown on the original PDF')
    try:
        path=checked_path(body['path']);meta=inspect(path)
    except (OSError,fitz.FileDataError): raise ReferenceUnavailable('Local PDF cannot be read') from None
    data={**meta,'path':str(path),'edition':edition.strip(),'local_use_confirmed':True,'registered_at':db.now(),'schema':1}
    registry_path().parent.mkdir(parents=True,exist_ok=True)
    jobs.atomic_json(registry_path(),data)
    return public(data)


def public(data):
    return {k:data[k] for k in ('pdf_sha256','page_count','size_bytes','edition','registered_at')}


def current():
    try:
        data=json.loads(registry_path().read_text(encoding='utf-8'))
        if not isinstance(data,dict): raise ReferenceUnavailable('Register the local reference again')
        if data.get('schema')!=1 or data.get('local_use_confirmed') is not True: raise ReferenceUnavailable('Register the local reference again')
        meta=inspect(data['path'])
        if any(meta[k]!=data[k] for k in meta): raise ReferenceUnavailable('Reference changed; choose and review the new edition')
        return data
    except (OSError,KeyError,TypeError,ValueError,fitz.FileDataError) as e:
        if isinstance(e,ReferenceUnavailable): raise
        raise ReferenceUnavailable('Local reference unavailable; choose the original PDF') from None


def search(query):
    data=current();words=str(query).casefold().split()
    if not words: return {'reference':public(data),'results':[]}
    if len(words)>12 or len(query)>200: raise ReferenceUnavailable('Search is too long')
    results=[]
    sections=brainstorm.sections(data['path'])
    if hashlib.sha256(checked_path(data['path']).read_bytes()).hexdigest()!=data['pdf_sha256']:
        raise ReferenceUnavailable('Reference changed during lookup; register it again')
    for section in sections:
        if not all(w in (section['title']+' '+section['text']).casefold() for w in words):continue
        matching=[f for f in section.get('fragments',[]) if all(w in (section['title']+' '+f['text']).casefold() for w in words)]
        hit=brainstorm.passage({**section,'fragments':matching},[re.escape(w) for w in words])
        if hit:
            # Cached extraction is not proof: recheck the returned excerpt against
            # this exact original physical page before exposing a citation.
            with fitz.open(data['path']) as original:
                page_text=original[hit['page']-1].get_text()
                heading_page_text=original[hit['section_page']-1].get_text()
            normalized=lambda text:re.sub(r'\s+',' ',text).strip()
            if normalized(hit['snippet']) not in normalized(page_text) or normalized(hit['title']) not in normalized(heading_page_text):
                raise ReferenceUnavailable('Reference excerpt cannot be verified against the original page')
            results.append({**hit,'edition':data['edition'],'source':'Brainstorm local reference','disclaimer':'Writing guide only. Cross-check current clinical sources; pharmacist review required.'})
        if len(results)==20:break
    return {'reference':public(data),'results':results}


def open_source(pdf_hash,page):
    data=current()
    if pdf_hash!=data['pdf_sha256'] or type(page) is not int or not 1<=page<=data['page_count']: raise ReferenceUnavailable('Invalid or stale reference citation')
    return {'path':data['path'],'page':page,'pdf_sha256':data['pdf_sha256']}
