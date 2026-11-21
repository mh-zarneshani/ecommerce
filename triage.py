"""Scoped issue detection, persisted timeline and human decisions."""
from decimal import Decimal as D
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from domain import ACCOUNTS, Input, Offer, Policy, Witness
from planner import Offline
from store import _ingest, latest, locked, metrics

FIXTURE = Path(__file__).parent/'inputs/class-demo.json'
DEMO = 'class-demo'
MAX_AGE=5
ROLES={'manager':'manager','specialist':'specialist','observer':'viewer'}
EMPTY={'branch':None,'clock':0,'started':False,'performance':{}}

def state(db,dataset=DEMO):
    row=db.execute('select state from triage_state where dataset=%s',(dataset,)).fetchone()
    return row['state'] if row else dict(EMPTY)

def _save_state(db,dataset,s):
    db.execute('insert into triage_state values (%s,%s) on conflict(dataset) do update set state=excluded.state',
               (dataset,Jsonb(s)))

def _save(db,c):
    db.execute("""insert into cases values (%s,%s,%s,%s,%s)
                  on conflict(dataset,id) do update set status=excluded.status,body=excluded.body""",
               (c['dataset'],c['id'],c['scope'],c['status'],Jsonb(c)))

def cases(db,dataset=DEMO):
    return [r['body'] for r in db.execute('select body from cases where dataset=%s order by id',(dataset,)).fetchall()]

def queue(db,dataset=DEMO):
    return sorted(cases(db,dataset),key=lambda c:(c['status']=='closed',
            {'high':0,'medium':1,'review':2}.get(c['drafts'][-1]['priority'],2),c['id']))

def _case(db,dataset,case_id):
    row=db.execute('select body from cases where dataset=%s and id=%s',(dataset,case_id)).fetchone()
    if not row:
        raise ValueError('پرونده پیدا نشد.')
    return row['body']

def _scope(x,kind):
    return json.dumps([kind,*[x[k] for k in ('account','product','offer','store','location')]],ensure_ascii=False,separators=(',',':'))

def discount(x,policies):
    if x.get('reference') in (None,0) or x.get('price') is None:
        return {'breach':False,'reason':'unknown-price'}
    pct = D(x['reference']-x['price'])*100/D(x['reference'])
    applicable=[p for p in policies if p['approved'] and p['account']==x['account']
                and all(p[k] in ('*',x[k]) for k in ('product','offer','location'))
                and p['start']<=x['time']<=p['end']]
    if not applicable:
        return {'breach':False,'reason':'missing-policy','discount':str(pct)}
    best=max(p['priority'] for p in applicable)
    winners=sorted((p for p in applicable if p['priority']==best),key=lambda p:p['id'])
    caps={D(p['cap']) for p in winners}
    if len(caps)!=1:
        return {'breach':False,'reason':'conflicting-policy','discount':str(pct)}
    p=winners[0]
    cap=caps.pop()
    return {'id':p['id'],'time':p['time'],'available':p['available'],'breach':pct>cap,
            'discount':str(pct),'cap':str(cap),'reason':'resolved'}

def _typed_observation(x):
    data=Offer(x['product'],x['offer'],x['store'],x['location'],x['status'],x['coverage'],x['mapped'],
               x.get('orderable'),x.get('reference'),x.get('price'),x['id']+'-W')
    return [Input('offer',x['id'],1,x['account'],x['time'],x['available'],data,{'synthetic':True}),
            Input('witness',x['id']+'-W',1,None,x['time'],x['available'],
                  Witness(x['id'],'شاهد ساخته‌شده برای تمرین در همین فروشگاه'),{'synthetic':True})]

def _facts(rows):
    return [dict(r['payload'],id=r['external_id'],revision=r['revision']) for r in rows]

def _stamp(o):
    return o['id']+'@'+str(o['revision'])

def _policy_facts(db,dataset,source,as_of):
    return _facts(latest(db,dataset,'policy',as_of,source))

def _apply(db,dataset,source,observation,s,planner,performance=None):
    x=dict(observation)
    as_of=s['clock']
    if x['time']>as_of or x['available']>as_of:
        return
    x['fresh']=0<=as_of-x['time']<=MAX_AGE
    witness=next((w for w in _facts(latest(db,dataset,'witness',as_of,source))
                  if w['id']==x['witness'] and w['related_id']==x['id'] and w['time']>=x['time']),None)
    valid=(x['status']=='ok' and x['coverage'] and x['mapped'] and x['fresh'] and bool(witness))
    pol=discount(x,_policy_facts(db,dataset,source,as_of)) if valid else {'breach':False}
    signals={'stockout':x['orderable'] is False,'discount':pol['breach']}
    review_kind = ('stockout' if not valid and (x['orderable'] is False or x['status']!='ok')
                   else 'discount' if valid and (x['price'] is not None or x['reference'] is not None) and pol.get('reason') in ('unknown-price','missing-policy','conflicting-policy')
                   else None)
    for kind,signal in signals.items():
        scope=_scope(x,kind)
        rows=db.execute('select body from cases where dataset=%s and scope=%s order by id desc',
                        (dataset,scope)).fetchall()
        c=next((r['body'] for r in rows if r['body']['status']!='closed'),None)
        closed=rows[0]['body'] if rows and c is None else None
        xkey=_stamp(x)
        if not c:
            if not (valid and signal) and kind!=review_kind:
                continue
            if closed and x['time']<=closed['latest']['time']:
                continue
            index=db.execute('select count(*) n from cases where dataset=%s',(dataset,)).fetchone()['n']+1
            c=dict(id=f'CASE-{index:05}',dataset=dataset,scope=scope,kind=kind,account=x['account'],
                   product=x['product'],offer=x['offer'],store=x['store'],location=x['location'],
                   owner='specialist',status='needs_review',confirmed=False,latest=None,evidence=[],events=[],drafts=[],referrals=[])
            c['events'].append({'type':'opened','actor':'host','clock':as_of})
        if any(e['stamp']==xkey for e in c['evidence']):
            continue
        c['evidence'].append({'stamp':xkey,'observation':x,'witness':witness})
        c['events'].append({'type':'evidence','actor':'host','clock':as_of,'id':xkey})
        past=c['latest']
        if past and ((x['time'],x['revision'])<(past['time'],past['revision']) or
                     (x['time']==past['time'] and x['id']!=past['id'])):
            _save(db,c)
            continue
        x['stamp']=xkey
        c['latest']=x
        recovery = (valid and c['confirmed'] and past is not None and x['time']>past['time']
                    and ((kind=='stockout' and x['orderable'] is True) or
                         (kind=='discount' and pol.get('reason')=='resolved' and not signal)))
        if valid and signal:
            c['status']='open'
            c['confirmed']=True
        if recovery:
            c['status']='recovery_verified'
            c['events'].append({'type':'recovery_verified','actor':'host','clock':as_of,'id':xkey})
        perf=performance or s['performance'].get(x['account'],{})
        p=dict(perf,id=f"PERF-{x['account']}",time=as_of,net=perf.get('net'),target=perf.get('target'))
        p['behind']=p['net'] is not None and p['target'] is not None and p['net']<p['target']
        obs=dict(x,id=xkey,scope=scope)
        wit=dict(witness,id=_stamp(witness),scope=scope) if witness else None
        history=[{'id':e['stamp'],'time':e['observation']['time'],'available':e['observation']['available'],
                  'scope':scope} for e in c['evidence'][:-1]]
        ctx=dict(dataset=dataset,synthetic=dataset==DEMO and source=='fixture',case_id=c['id'],scope=scope,
                 kind=kind,as_of=as_of,recovery=recovery,observation=obs,evidence=wit,policy=pol,
                 performance=p,history=history)
        draft=(planner if dataset==DEMO else Offline()).run(ctx)
        # A new witness invalidates an unreviewed recommendation but never an existing referral.
        for old in c['drafts']:
            if old['approval'] in ('draft','edited'):
                old['approval']='superseded'
        draft.update(id=f"{c['id']}-D{len(c['drafts'])+1}",approval='draft',
                     original=draft['next_action_fa'],edited=None,clock=as_of)
        c['drafts'].append(draft)
        c['events'].append({'type':'drafted','actor':draft['mode'],'clock':as_of,'id':draft['id']})
        _save(db,c)

def _fixture():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))

def _process_demo(db,observations,s,planner):
    batch=[record for x in observations for record in _typed_observation(x)]
    _,_,accepted=_ingest(db,DEMO,'fixture',batch)
    wanted={x.id for x in accepted if x.kind=='offer'}
    for x in _facts(latest(db,DEMO,'offer',s['clock'],'fixture')):
        if x['id'] in wanted:
            _apply(db,DEMO,'fixture',x,s,planner)

def start(db,actor,planner=None):
    if actor!='manager':
        raise PermissionError('فقط مدیر می‌تواند دمو را آغاز کند.')
    with locked(db,DEMO):
        if state(db)['started']:
            return False
        f=_fixture()['initial']
        s=dict(branch=None,started=True,clock=f['clock'],
               performance={x['account']:x for x in f['plans']})
        policies=[Input('policy',p['id'],1,p['account'],p['start'],p['start'],
                        Policy(p['product'],p.get('offer','*'),p.get('location','*'),p['start'],p['end'],
                               str(p['cap']),p['priority'],p['approved']),{'synthetic':True})
                  for p in f['policies']]
        _ingest(db,DEMO,'fixture',policies)
        _process_demo(db,f['observations'],s,planner or Offline())
        _save_state(db,DEMO,s)
        return True

def advance(db,actor,branch,planner=None):
    if actor!='manager':
        raise PermissionError('فقط مدیر می‌تواند شاخه را انتخاب کند.')
    if branch not in ('orderable','error'):
        raise ValueError('شاخه نامعتبر')
    with locked(db,DEMO):
        s=state(db)
        if not s['started']:
            raise ValueError('ابتدا دمو را شروع کنید.')
        if s['branch']==branch:
            return False
        if s['branch']:
            raise ValueError('برای مسیر دیگر ابتدا دمو را بازنشانی کنید.')
        x=_fixture()[branch]
        s.update(branch=branch,clock=x['available'])
        _process_demo(db,[x],s,planner or Offline())
        _save_state(db,DEMO,s)
        return True

def reset(db,actor):
    if actor!='manager':
        raise PermissionError('فقط مدیر می‌تواند دمو را بازنشانی کند.')
    with locked(db,DEMO):
        for sql in ("delete from cases where dataset=%s","delete from triage_state where dataset=%s",
                    "delete from conflicts where dataset=%s","delete from records where dataset=%s"):
            db.execute(sql,(DEMO,))

def review_workbook(db,actor,month,day,hour):
    if actor not in ('manager','specialist'):
        raise PermissionError('بررسی شاهد نیازمند کارشناس است.')
    from domain import clock
    as_of=clock(month,day,hour)
    with locked(db,'workbook'):
        s=state(db,'workbook')
        if as_of<s['clock']:
            raise ValueError('زمان بررسی ذخیره‌شده جلوتر است؛ داشبورد همچنان برای گذشته قابل مشاهده است.')
        s.update(clock=as_of,started=True)
        sightings=sorted(_facts(latest(db,'workbook','offer',as_of,'xlsx')),
                         key=lambda x:(x['time'],x['revision'],x['id']),reverse=True)
        latest_by_scope={}
        for x in sightings:
            latest_by_scope.setdefault(_scope(x,'offer'),x)
        for x in latest_by_scope.values():
            if as_of-x['time']>MAX_AGE and not any(c['offer']==x['offer'] and c['status']!='closed'
                                                 for c in cases(db,'workbook')):
                continue
            perf=metrics(db,month,day,x['account'],hour=hour)
            _apply(db,'workbook','xlsx',x,s,Offline(),{'net':perf['net'],'target':perf['target']})
        _save_state(db,'workbook',s)

def decide(db,dataset,case_id,draft_id,actor,action,text=None):
    if actor not in ('manager','specialist'):
        raise PermissionError('این تصمیم فقط برای مدیر یا کارشناس مجاز است.')
    if action not in ('edit','approve','reject'):
        raise ValueError('تصمیم نامعتبر')
    with locked(db,dataset):
        c=_case(db,dataset,case_id)
        d=next((x for x in c['drafts'] if x['id']==draft_id),None)
        if not d or c['status']=='closed':
            raise ValueError('پیشنهاد فعال پیدا نشد.')
        if d['status'] != 'validated' and action in ('edit','approve'):
            raise ValueError('برای ارجاع، ابتدا شاهد و پیشنهاد معتبر لازم است.')
        if d['approval']=='approved' and action=='approve':
            return False
        if d['approval'] not in ('draft','edited'):
            raise ValueError('این پیشنهاد قبلاً بررسی شده است.')
        if (action in ('edit','approve') and text is not None) or action=='edit':
            if not isinstance(text,str) or not text.strip() or len(text)>500:
                raise ValueError('متن پیشنهاد باید ۱ تا ۵۰۰ نویسه باشد.')
            d['edited']=text.strip()
        clock=state(db,dataset)['clock']
        d['approval']={'edit':'edited','approve':'approved','reject':'rejected'}[action]
        d['reviewer']=actor
        c['events'].append({'type':action,'actor':actor,'clock':clock,'id':draft_id})
        if action=='approve':
            c['referrals'].append(dict(id=draft_id+'-R',draft_id=draft_id,original=d['original'],
                 text=d['edited'] or d['original'],actor=actor,owner=c['owner'],clock=clock,evidence=d['evidence']))
        _save(db,c)
        return True

def close(db,dataset,case_id,actor):
    with locked(db,dataset):
        c=_case(db,dataset,case_id)
        if actor!=c['owner']:
            raise PermissionError('فقط مسئول این پرونده می‌تواند آن را ببندد.')
        if c['status']=='closed':
            return False
        if (c['status']!='recovery_verified' or c['latest']['status']!='ok'
            or not c['latest']['fresh'] or not c['latest']['mapped'] or not c['latest']['coverage']
            or (c['kind']=='stockout' and c['latest']['orderable'] is not True)
            or c['events'][-1].get('type')=='closed'
            or not any(e['type']=='recovery_verified' and e.get('id')==c['latest']['stamp'] for e in c['events'])):
            raise ValueError('ابتدا بازگشت وضعیت را با شاهد معتبر تأیید کنید.')
        c['status']='closed'
        c['events'].append({'type':'closed','actor':actor,'clock':state(db,dataset)['clock']})
        _save(db,c)
        return True

