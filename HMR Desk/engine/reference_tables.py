"""Private indexed reference tables. Extracted licensed text is never bundled.

The original PDF remains authoritative. These tables are a rebuildable local
search index, not clinical rules and not part of the clinical record database.
"""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import brainstorm
import db

SCHEMA=1
PARSER='physical-fragments-v4'


def open_index(source,anchor_builder):
    directory=Path(db.DATA_DIR);directory.mkdir(parents=True,exist_ok=True)
    target=directory/('reference-index-v1-'+source['pdf_sha256']+'.sqlite3')
    if target.is_symlink():raise ValueError('Linked reference index refused')
    try:
        conn=sqlite3.connect(str(target));conn.row_factory=sqlite3.Row
        row=conn.execute('SELECT * FROM source').fetchone()
        if row and row['schema_version']==SCHEMA and row['edition']==source['edition'] and row['parser_version']==PARSER and row['pdf_sha256']==source['pdf_sha256']:
            if conn.execute('SELECT count(*) FROM sections').fetchone()[0]==row['section_count'] and conn.execute('SELECT count(*) FROM fragments').fetchone()[0]==row['fragment_count'] and conn.execute('SELECT count(*) FROM anchors').fetchone()[0]==row['anchor_count']:
                return conn
        conn.close()
    except (sqlite3.DatabaseError,IndexError):
        try:conn.close()
        except UnboundLocalError:pass
    sections=brainstorm.sections(source['path'])
    handle,temporary=tempfile.mkstemp(prefix='reference-index-',suffix='.sqlite3',dir=str(directory));os.close(handle)
    try:
        conn=sqlite3.connect(temporary)
        conn.executescript('''
        CREATE TABLE source(pdf_sha256 TEXT PRIMARY KEY,edition TEXT NOT NULL,schema_version INTEGER NOT NULL,parser_version TEXT NOT NULL,section_count INTEGER NOT NULL,fragment_count INTEGER NOT NULL,anchor_count INTEGER NOT NULL);
        CREATE TABLE sections(id INTEGER PRIMARY KEY,title TEXT NOT NULL,page_start INTEGER NOT NULL,page_end INTEGER NOT NULL);
        CREATE TABLE fragments(section_id INTEGER NOT NULL,page INTEGER NOT NULL,text TEXT NOT NULL,PRIMARY KEY(section_id,page));
        CREATE TABLE anchors(section_id INTEGER NOT NULL,phrase TEXT NOT NULL,first_word TEXT NOT NULL,token_count INTEGER NOT NULL,PRIMARY KEY(section_id,phrase));
        CREATE INDEX anchors_first_word ON anchors(first_word);
        CREATE INDEX fragments_section ON fragments(section_id,page);
        ''')
        fragments=0;anchor_count=0
        for sid,section in enumerate(sections,1):
            conn.execute('INSERT INTO sections VALUES(?,?,?,?)',(sid,section['title'],section['page'],section['page_end']))
            for fragment in section['fragments']:
                conn.execute('INSERT INTO fragments VALUES(?,?,?)',(sid,fragment['page'],fragment['text']));fragments+=1
            for term in anchor_builder(section['title']):
                conn.execute('INSERT INTO anchors VALUES(?,?,?,?)',(sid,json.dumps(term),term[0],len(term)));anchor_count+=1
        conn.execute('INSERT INTO source VALUES(?,?,?,?,?,?,?)',(source['pdf_sha256'],source['edition'],SCHEMA,PARSER,len(sections),fragments,anchor_count));conn.commit();conn.close();os.replace(temporary,target)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    conn=sqlite3.connect(str(target));conn.row_factory=sqlite3.Row;return conn


def candidates(conn,tokens):
    """Index by original first word, then require the full literal token phrase."""
    result={};unique=sorted(set(tokens))
    for start in range(0,len(unique),400):
        batch=unique[start:start+400]
        rows=conn.execute('SELECT section_id,phrase,token_count FROM anchors WHERE first_word IN ('+','.join('?' for _ in batch)+')',batch)
        windows={}
        for row in rows:
            size=row['token_count']
            if size not in windows:windows[size]={tuple(tokens[n:n+size]) for n in range(len(tokens)-size+1)}
            term=tuple(json.loads(row['phrase']))
            if term in windows[size]:result.setdefault(row['section_id'],[]).append(term)
    return result


def section(conn,sid,pdf_hash):
    row=conn.execute('SELECT * FROM sections WHERE id=?',(sid,)).fetchone()
    fragments=[dict(r) for r in conn.execute('SELECT page,text FROM fragments WHERE section_id=? ORDER BY page',(sid,))]
    return {'title':row['title'],'page':row['page_start'],'page_end':row['page_end'],'fragments':fragments,'pdf_sha256':pdf_hash,'citation_version':1}
