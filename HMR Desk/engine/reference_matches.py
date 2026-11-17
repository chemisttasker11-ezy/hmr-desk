"""Automatic local lexical retrieval, never clinical interpretation or advice.

Only literal single-word headings or heading phrases between adjacent significant words are used.
No medical rules, synonyms, abnormality thresholds or diagnosis inference.
"""
import copy
import hashlib
import re
import sqlite3
import fitz
import brainstorm
import reference_library as library
import suggestion_context
import reference_tables

VERSION=2
# Grammatical search words only, not a clinical ontology.
STOP=frozenset('a an and are as at be been by for from in into is it of on or that the their this to was were with without'.split())
KINDS=frozenset(('interview notes','interview concerns','observation','pathology','conditions','mobility','interview detail'))


def words(text):
    return [x.casefold() for x in re.findall(r"[^\W\d_][\w'-]*",text,flags=re.UNICODE)]


def anchors(title):
    tokens=words(title)
    significant=[n for n,t in enumerate(tokens) if len(t)>=3 and t not in STOP]
    if len(significant)==1:
        # Single-term retrieval is permitted only for a genuinely single-word heading.
        return [(tokens[0],)] if len(tokens)==1 and len(tokens[0])>=4 else []
    # Keep any intervening grammatical words, so a negation cannot disappear
    # from a claimed literal phrase. Never create adjacency by dropping words.
    return list(dict.fromkeys(tuple(tokens[a:b+1]) for a,b in zip(significant,significant[1:])))


def matching_terms(title,text):
    tokens=words(text)
    return [a for a in anchors(title) if any(tuple(tokens[n:n+len(a)])==a for n in range(len(tokens)-len(a)+1))]


def supported(e):
    if e.get('eligible') is not True or e.get('kind') not in KINDS or not str(e.get('text','')).strip():return False
    # Unverified/legacy pathology never drives automated retrieval. Current
    # observation eligibility already distinguishes original vs newer versions.
    if e['kind']=='pathology' and (e.get('verification')!='named pharmacist verified' or not e.get('verified_by') or not e.get('verified_at')):return False
    return True


def retrieve(context):
    if context.get('context_snapshot_sha256')!=suggestion_context.fingerprint(context):raise ValueError('Evidence context fingerprint mismatch')
    data=library.current()
    try:index=reference_tables.open_index(data,anchors)
    except (OSError,ValueError,sqlite3.DatabaseError):
        raise library.ReferenceUnavailable('Private reference tables unavailable; rebuild the local index') from None
    if hashlib.sha256(library.checked_path(data['path']).read_bytes()).hexdigest()!=data['pdf_sha256']:
        index.close()
        raise library.ReferenceUnavailable('Reference changed during retrieval; register it again')
    evidence=context['evidence'];eligible=[e for e in evidence if supported(e)]
    # Bound work explicitly, do not imply a complete review on a truncated pass.
    processed=eligible[:200];results=[];total=0
    norm=lambda t:re.sub(r'\s+',' ',t).strip()
    # SQL's indexed anchor lookup avoids scanning every section for every row.
    pairs=[]
    try:
        for position,e in enumerate(processed):
            for sid,terms in reference_tables.candidates(index,words(e['text'])).items():pairs.append((sid,position,terms))
        with fitz.open(data['path']) as original:
            for sid,position,terms in sorted(pairs):
                e=processed[position];section=reference_tables.section(index,sid,data['pdf_sha256'])
                if sorted(terms)!=sorted(matching_terms(section['title'],e['text'])):
                    raise library.ReferenceUnavailable('Reference index does not match original heading terms; rebuild it')
                if not 1<=section['page']<=section['page_end']<=len(original):
                    raise library.ReferenceUnavailable('Reference table pages are invalid; rebuild the local index')
                fragments=[fragment for fragment in section.get('fragments',[]) if any(matching_terms(' '.join(term),fragment['text']) for term in terms)]
                patterns=[r'(?<!\w)'+r'[^\w]+'.join(re.escape(word) for word in term)+r'(?!\w)' for term in terms]
                hit=brainstorm.passage({**section,'fragments':fragments},patterns)
                if hit:
                    quote_basis='matched_heading_phrase_in_body'
                else:
                    # A title match is enough to retrieve its opening passage.
                    # Do not pretend those heading words occur in the body quote.
                    hit=brainstorm.passage(section,[r'\S'])
                    quote_basis='heading_match_opening_passage'
                if not hit:continue
                if norm(hit['snippet']) not in norm(original[hit['page']-1].get_text()) or norm(hit['title']) not in norm(original[hit['section_page']-1].get_text()):
                    raise library.ReferenceUnavailable('Reference passage cannot be verified against original page')
                total+=1
                if len(results)<20:
                    results.append({'evidence':copy.deepcopy(e),'reference':{**hit,'edition':data['edition'],'source':'Brainstorm local reference'},
                        'matched_heading_words':[' '.join(t) for t in terms], 'quote_basis':quote_basis,
                        'match_kind':'literal_heading_text_overlap','review_status':'pharmacist_review_required',
                        'context_snapshot_sha256':context['context_snapshot_sha256'],
                        'limitations':['Text overlap is not a clinical finding or recommendation.',
                            'Original evidence may be negated, historical, uncertain or unrelated. Read it in full.',
                            'No clinical currency, relevance, diagnosis or abnormality was inferred.']})
    except library.ReferenceUnavailable:raise
    except (sqlite3.DatabaseError,IndexError,KeyError,TypeError,ValueError):
        raise library.ReferenceUnavailable('Private reference tables are invalid; rebuild the local index') from None
    finally:index.close()
    # Catch a source changed while PDF pages were being checked.
    if hashlib.sha256(library.checked_path(data['path']).read_bytes()).hexdigest()!=data['pdf_sha256']:
        raise library.ReferenceUnavailable('Reference changed during retrieval; reload and review')
    latest=library.current()
    if any(latest[key]!=data[key] for key in ('path','pdf_sha256','edition','registered_at')):
        raise library.ReferenceUnavailable('Registered reference changed during retrieval; reload and review')
    return {'matches':results,'reference':library.public(data),'context_snapshot_sha256':context['context_snapshot_sha256'],
        'retrieval_version':VERSION,'storage':'private_indexed_sqlite_tables','review_status':'pharmacist_review_required','checked_on':context['checked_on'],
        'context_gaps':context['context_gaps'],'source_revisions':context['source_revisions'],
        'evidence_rows':len(evidence),'eligible_evidence_rows':len(eligible),'processed_evidence_rows':len(processed),
        'excluded_evidence_ids':[e['id'] for e in evidence if not supported(e)],
        'total_matches':total,'truncated':len(eligible)>len(processed) or total>len(results),
        'method':'Literal heading text overlap only; no synonym, clinical-rule, threshold or past-case scoring.'}


def for_patient(conn,patient):
    context=suggestion_context.build(conn,patient)
    result=retrieve(context)
    if suggestion_context.build(conn,patient)['context_snapshot_sha256']!=context['context_snapshot_sha256']:
        raise library.ReferenceUnavailable('Saved evidence changed during retrieval; reload and review')
    return result
