"""PostgreSQL persistence and shared import, manual and dashboard services."""
from collections import Counter
from contextlib import contextmanager
from decimal import Decimal as D
import hashlib
import json
import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from domain import ACCOUNTS, MONTHS, PRODUCTS, Input, Sale, clock, days, integer, ratio
from readers import Rejected
from setup_local import PROFILE

from pathlib import Path
import db_migrations

# Retained for compatibility and old-schema migration tests.
SCHEMA = (Path(__file__).parent/'migrations'/'001_existing_schema.sql').read_text('utf-8')

def config(test=False):
    key = 'ECOM_TEST_DSN' if test else 'ECOM_DSN'
    if os.environ.get(key):
        return (os.environ[key],), {}
    if PROFILE.is_file():
        return (), json.loads(PROFILE.read_text(encoding='utf-8'))['test' if test else 'app']
    raise ValueError('ابتدا راه‌انداز PostgreSQL پروژه را اجرا کنید.')

def connect(test=False):
    args, kwargs = config(test)
    return psycopg.connect(*args, **kwargs, row_factory=dict_row, autocommit=True)

def initialize(db):
    db_migrations.upgrade(db)

@contextmanager
def locked(db, dataset):
    if not isinstance(dataset,str) or not dataset.strip():
        raise ValueError('نام مجموعه لازم است')
    with db.transaction():
        db.execute('select pg_advisory_xact_lock(618114001,hashtext(%s))',(dataset,))
        yield

def latest(db,dataset,kind,cutoff,source):
    return db.execute("""select distinct on (external_id) *
                         from records where dataset=%s and kind=%s and source=%s
                         and event_time<=%s and available<=%s
                         order by external_id,revision desc""",(dataset,kind,source,cutoff,cutoff)).fetchall()

def _current(db,dataset,source):
    rows = db.execute("""select distinct on (kind,external_id) kind,external_id,revision,payload
                         from records where dataset=%s and source=%s
                         order by kind,external_id,revision desc""",(dataset,source)).fetchall()
    return {(x['kind'],x['external_id']):(x['revision'],x['payload']) for x in rows}

def _ingest(db,dataset,source,items, *, persist=True):
    current = _current(db,dataset,source)
    counts, reasons, changes, disputes, accepted = Counter(), [], [], [], []
    for x in items:
        if isinstance(x,Rejected):
            counts['rejected']+=1; reasons.append((x.row,x.reason)); continue
        row = x.trace.get('row',x.id) if isinstance(x.trace,dict) else x.id
        try:
            x.validate()
            data = x.payload()
            key = (x.kind,x.id if x.kind != 'plan' else f'{x.data.month}/{x.account}/{x.data.scope}')
        except (ValueError,TypeError,ArithmeticError) as exc:
            counts['rejected']+=1; reasons.append((row,str(exc))); continue
        trace = Jsonb(dict(x.trace, native_id=x.id), dumps=lambda val: json.dumps(val,default=str))
        prev = current.get(key)
        base = dataset, source, *key, x.revision
        if prev and x.revision < prev[0]:
            status = 'stale'
        elif prev and x.revision == prev[0]:
            status = 'duplicate' if prev[1]==data else 'conflict'
            if status=='conflict':
                digest = hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
                disputes.append((*base,digest,Jsonb(data),trace))
                reasons.append((row,'تعارض نسخه؛ سهم پذیرفته‌شده حفظ شد'))
        else:
            status = 'corrected' if prev else 'new'
            current[key] = (x.revision,data)
            changes.append((*base,x.time,x.available,Jsonb(data),trace))
            accepted.append(x)
        counts[f'{x.kind}:{status}'] += 1
    with db.cursor() as cur:
        if persist and changes:
            cur.executemany('insert into records values (%s,%s,%s,%s,%s,%s,%s,%s,%s)',changes)
        if persist and disputes:
            cur.executemany('insert into conflicts values (%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing',disputes)
    return dict(counts), reasons, accepted

def ingest(db,dataset,source,reader):
    if not isinstance(source,str) or not source.strip() or source=='manual':
        raise ValueError('منبع نامعتبر')
    # Reader iteration and all accepted/conflicting records share one transaction.
    with locked(db,dataset):
        counts,reasons,_ = _ingest(db,dataset,source,reader.read())
        return counts,reasons

def import_snapshot(db):
    current=_current(db,'workbook','xlsx')
    rows=[[kind,key,revision,payload] for (kind,key),(revision,payload) in sorted(current.items())]
    conflicts=db.execute("""select kind,external_id,revision,fingerprint from conflicts
        where dataset='workbook' and source='xlsx' order by kind,external_id,revision,fingerprint""").fetchall()
    return hashlib.sha256(json.dumps([rows,conflicts],sort_keys=True,default=str).encode()).hexdigest()


def preview_import(db,items,*,include_rows=False):
    with locked(db,'workbook'):
        counts,reasons,accepted=_ingest(db,'workbook','xlsx',items,persist=False)
        result=(import_snapshot(db),counts,reasons)
        if include_rows:
            rows=[dict(id=x.id,revision=x.revision,row=x.trace.get('row'),**x.payload())
                  for x in accepted if x.kind=='sale'][:50]
            return (*result,rows)
        return result


def commit_import(db,items,expected_snapshot,*,actor,identity_source):
    with locked(db,'workbook'):
        if import_snapshot(db)!=expected_snapshot:
            raise ValueError('اطلاعات اکسل پس از پیش‌نمایش تغییر کرده است؛ پیش‌نمایش تازه بگیرید.')
        recorded=db.execute('select clock_timestamp() as time').fetchone()['time'].isoformat()
        from dataclasses import replace
        prepared=[replace(x,trace=dict(x.trace,import_actor=actor,identity_source=identity_source,
                                      imported_at=recorded)) if hasattr(x,'trace') else x for x in items]
        counts,reasons,_=_ingest(db,'workbook','xlsx',prepared)
        return counts,reasons


def import_book(db,path=None):
    from readers import BOOK, WorkbookReader
    return ingest(db,'workbook','xlsx',WorkbookReader(path or BOOK))

def workbook_dates(db,account):
    if account not in ACCOUNTS:
        raise ValueError('اکانت نامعتبر')
    rows=latest(db,'workbook','sale',10**12,'xlsx')
    return sorted({(r['payload']['month'],r['payload']['day']) for r in rows
                   if r['payload']['account']==account},
                  key=lambda d:(MONTHS.index(d[0]),d[1]),reverse=True)

def manual_record(db,month,day,account,product):
    rid = f'{month}/{day}/{account}/{product}'
    return db.execute("""select revision,payload from records where dataset='workbook' and source='manual'
                         and kind='sale' and external_id=%s order by revision desc limit 1""",(rid,)).fetchone()

def save_manual(db,month,day,account,product,values,expected_rev,confirm=False, *,
                actor=None, role=None, identity_source='legacy_unspecified'):
    if month not in MONTHS[-2:] or account not in ACCOUNTS or product not in PRODUCTS:
        raise ValueError('خارج از دامنهٔ ورود دستی')
    integer(day,16 if month=='بهمن' else 1,days(month))
    time = clock(month,day)
    data = Sale(month,day,product,*values)
    x = Input('sale',f'{month}/{day}/{account}/{product}',expected_rev+1,account,time,time,
              data,{'mode':'hypothetical'})
    x.validate()
    with locked(db,'workbook'):
        if any(_sale_scope(r['payload'])==_sale_scope(x.payload()) for r in latest(db,'workbook','sale',10**12,'xlsx')):
            raise ValueError('این محصول و روز در اکسل موجود است')
        prev = manual_record(db,month,day,account,product)
        if prev and prev['payload']==x.payload():
            return 'duplicate'
        if expected_rev != (prev['revision'] if prev else 0):
            raise ValueError('ردیف تغییر کرده است؛ صفحه را تازه کنید')
        if prev and not confirm:
            raise ValueError('اصلاح ردیف را تأیید کنید')
        if identity_source not in ('legacy_unspecified','local_simulation','proxy_authenticated'):
            raise ValueError('منبع هویت نامعتبر است')
        if identity_source!='legacy_unspecified' and (not isinstance(actor,str) or not actor or not isinstance(role,str) or not role):
            raise ValueError('هویت ثبت‌کننده مشخص نیست')
        recorded=db.execute('select clock_timestamp() as recorded_at').fetchone()['recorded_at']
        x.trace.update(actor=actor,role=role,identity_source=identity_source,recorded_at=recorded.isoformat())
        _ingest(db,'workbook','manual',[x])
        return 'corrected' if prev else 'new'

def manual_history(db,month,day,account,product):
    rid=f'{month}/{day}/{account}/{product}'
    return db.execute("""select revision,payload,trace from records
        where dataset='workbook' and source='manual' and kind='sale' and external_id=%s
        order by revision desc limit 100""",(rid,)).fetchall()


def _sale_scope(s):
    return s['month'],s['day'],s['account'],s['product']

def metrics(db,month,day,account=None,overlay=False,*,dataset='workbook',source='xlsx',hour=18):
    if account is not None and account not in ACCOUNTS:
        raise ValueError('اکانت نامعتبر')
    cutoff = clock(month,day,hour)
    def selected(x):
        return x['month']==month and (account is None or x['account']==account)
    if overlay and (dataset,source)!=('workbook','xlsx'):
        raise ValueError('ثبت دستی تنها برای مجموعهٔ اکسل است')
    with db.transaction():
        book = [r for r in latest(db,dataset,'sale',cutoff,source) if selected(r['payload'])]
        allrows = {source:book}
        if overlay:
            covered = {_sale_scope(r['payload']) for r in book}
            allrows['manual'] = [r for r in latest(db,dataset,'sale',cutoff,'manual')
                                 if selected(r['payload']) and _sale_scope(r['payload']) not in covered]
        plans = [r['payload'] for r in latest(db,dataset,'plan',cutoff,source) if selected(r['payload'])]
        disputed = db.execute("""select source,kind,external_id,revision,payload from conflicts
            where dataset=%s and source=any(%s) and kind in ('sale','plan')
            and (payload->>'available')::double precision<=%s""",(dataset,list(allrows),cutoff)).fetchall()
    rows = [r for group in allrows.values() for r in group]
    n = spend = None
    if rows:
        n, spend = 0,D(0)
        for r in rows:
            s = r['payload']; packs=s['registered']-s['cancelled']-s['returned']
            n+=packs
            spend+=D(packs)*s['price']*s['discount']*s['share']/10**8
    required = 1 if account else len(ACCOUNTS)
    t,b = (sum(x['target'] for x in plans),sum(x['budget'] for x in plans)) if len(plans)==required else (None,None)
    fraction=(D(day)+D('.4')*max(0,min(day,14)-7))/(D(days(month))+D('2.8'))
    due=t*fraction if t is not None else None
    seen={_sale_scope(r['payload']) for r in rows}
    return dict(rows=rows,net=n,spend=spend,target=t,budget=b,cutoff=cutoff,
                gap=None if n is None or t is None else n-t,attain=ratio(n,t),
                util=ratio(spend,b),due=due,pace=ratio(n,due),fraction=fraction,
                missing=day*len(PRODUCTS)*required-len(seen),
                disputed=[r for r in disputed if selected(r['payload'])])

