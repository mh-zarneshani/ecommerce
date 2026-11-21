"""One local HTTP application for sales, the case desk, and the contextual assistant."""
import argparse
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
from threading import RLock, Timer
from time import monotonic
from urllib.parse import urlsplit
import webbrowser

import psycopg

from access import model_budget
from domain import ACCOUNTS, MONTHS, PRODUCTS, bp, clock, days
import store
import triage
from web_config import Connection, ROLES, Settings
from web_ai import Context, RESERVE, WebError, completion, encode, preview, request_model, take, verify_response

ROOT=Path(__file__).resolve().parent
PORT=8765
APP_ID='active-sales-unified'
LOG=logging.getLogger('ecom.http')
STATUS={'open':'نیازمند اقدام','needs_review':'نیازمند شاهد','recovery_verified':'رفع مشکل تأیید شد',
        'closed':'بسته شده'}
KIND={'discount':'تخفیف','stockout':'ناموجودی'}


@dataclass
class Session:
    identity: str
    role: str
    time: float = field(default_factory=monotonic)
    history: OrderedDict = field(default_factory=OrderedDict)
    pending: object = None
    diagnostic: object = None
    import_pending: object = None
    lock: RLock = field(default_factory=RLock)


def value(obj,key,options):
    x=obj.get(key)
    if not isinstance(x,str) or x not in options:
        raise WebError('انتخاب نامعتبر است.')
    return x


def integer(obj,key,low,high,default=None):
    x=obj.get(key,default)
    if type(x) is not int or not low<=x<=high:
        raise WebError('مقدار عددی یا بازه نامعتبر است.')
    return x


class Application:
    def __init__(self, connect=store.connect, settings=None, *, hosted=False, origin=None, transport=None):
        self.connect, self.settings = connect, settings or Settings()
        self.hosted, self.origin, self.transport = hosted, origin, transport
        if hosted:
            u=urlsplit(origin or '')
            if u.scheme!='https' or u.netloc=='' or u.username or u.path or u.query or u.fragment:
                raise ValueError('برای استقرار کنترل‌شده ECOM_PUBLIC_ORIGIN باید نشانی HTTPS باشد.')
            if not os.environ.get('PROXY_TOKEN'):
                raise ValueError('شناسهٔ امن پراکسی تنظیم نشده است.')
        self.sessions=OrderedDict()
        self.lock=RLock()
        requests=int(os.environ.get('ECOM_AI_DAILY_REQUESTS','8'))
        tokens=int(os.environ.get('ECOM_AI_DAILY_TOKENS','48000'))
        if not 0<=requests<=10000 or not 0<=tokens<=100_000_000:
            raise ValueError('بودجهٔ روزانهٔ مدل معتبر نیست.')
        self.reserve=model_budget(connect,requests,tokens)

    @contextmanager
    def read(self):
        with self.connect() as db, db.transaction():
            db.execute('set transaction isolation level repeatable read read only')
            yield db

    def identity(self, headers):
        if not self.hosted:
            return 'local'
        expected=os.environ.get('PROXY_TOKEN','')
        token=headers.get('X-Ecom-Proxy-Token','')
        identity=headers.get('X-Ecom-Identity','')
        if not expected or not compare_digest(expected.encode(),token.encode()) or not identity:
            raise WebError('ورود معتبر لازم است.',401)
        return identity

    def start(self, identity):
        role=self.settings.role(identity) if self.hosted else 'manager'
        if role not in ROLES:
            raise WebError('برای این هویت دسترسی تعریف نشده است.',403)
        with self.lock:
            token=secrets.token_urlsafe(32)
            session=self.sessions[token]=Session(identity,role)
            if len(self.sessions)>256:
                self.sessions.popitem(last=False)
        return dict(token=token, **self.bootstrap(session))

    def session(self, token, identity):
        with self.lock:
            s=self.sessions.get(token)
            if not s or s.identity!=identity or monotonic()-s.time>3600:
                raise WebError('نشست معتبر نیست؛ صفحه را دوباره باز کنید.',401)
            if self.hosted and self.settings.role(identity)!=s.role:
                raise WebError('دسترسی تغییر کرد؛ صفحه را دوباره باز کنید.',403)
            s.time=monotonic()
            self.sessions.move_to_end(token)
            return s

    def bootstrap(self,s):
        return dict(role=s.role,local=not self.hosted,
                    roles={key:{'label': r[0],'account':r[1],'permission':r[2]} for key,r in ROLES.items()},
                    accounts=self.accounts(s),products=PRODUCTS,
                    months=[{'name':m,'days':days(m)} for m in MONTHS])

    @staticmethod
    def accounts(s):
        account=ROLES[s.role][1]
        return {a:n for a,n in ACCOUNTS.items() if not account or account==a}

    def account(self,s,data,all_allowed=False):
        account=data.get('account')
        if account=='all' and all_allowed and s.role in ('manager','observer'):
            return None
        if not isinstance(account,str) or account not in self.accounts(s):
            raise WebError('دسترسی به این اکانت مجاز نیست.',403)
        return account

    def require(self,s,*roles):
        if s.role not in roles:
            raise WebError('این عملیات برای نقش فعلی مجاز نیست.',403)

    def report_scope(self,s,data):
        account=self.account(s,data,all_allowed=True)
        dataset=value(data,'dataset',('workbook',triage.DEMO))
        return dict(dataset=dataset,account=account,month=(m:=value(data,'month',MONTHS)),
                    day=integer(data,'day',1,days(m)),hour=integer(data,'hour',0,23),
                    overlay=data.get('overlay') is True and dataset=='workbook')

    def report(self,db,x):
        a,m,d,h,o=x['account'],x['month'],x['day'],x['hour'],x['overlay']
        if x['dataset']==triage.DEMO:
            state=triage.state(db)
            p=[dict(v,account=k) for k,v in state['performance'].items() if not a or a==k]
            net=sum(v['net'] for v in p) if p else None
            target=sum(v['target'] for v in p) if p else None
            return dict(scope=x, net=net,target=target,gap=net-target if p else None,due=None,pace=None,pace_gap=None,missing=None,
                        util=None,spend=None,budget=None,rows=[],disputed=0,performance=p,cutoff=state['clock'],counts=None)
        base=store.metrics(db,m,d,a,o,hour=h)
        parts=[]
        for a_id in (a,) if a else ACCOUNTS:
            stats=base if a else store.metrics(db,m,d,a_id,o,hour=h)
            parts.append({k:stats[k] for k in ('net','target','due','pace','missing')} | {'account':a_id})
        rows=[]
        for row in base['rows']:
            p=row['payload']
            rows.append(dict(id=row['external_id'],rev=row['revision'],day=p['day'],account=p['account'],product=p['product'],
                             source=row['source'],registered=p['registered'],cancelled=p['cancelled'],returned=p['returned'],
                             net=p['registered']-p['cancelled']-p['returned']))
        rows.sort(key=lambda r:(r['day'],r['account'],r['product'],r['source']))
        pace_gap=base['net']-base['due'] if not base['missing'] and base['net'] is not None and base['due'] is not None else None
        return {**{k:base[k] for k in ('net','target','gap','cutoff','due','pace','missing','util','spend','budget','attain')},
                'pace_gap':pace_gap,
                'scope':x,'rows':rows,'disputed':len(base['disputed']),'performance':parts,
                'counts':{k:sum(r[k] for r in rows) for k in ('registered','cancelled','returned')} if rows else None}

    def case_selector(self,s,data):
        a=self.account(s,data,all_allowed=True)
        dataset=value(data,'dataset',('workbook',triage.DEMO))
        cutoff=clock((m:=value(data,'month',MONTHS)),integer(data,'day',1,days(m)),integer(data,'hour',0,23))
        return dict(dataset=dataset,account=a,cutoff=cutoff)

    def case_list(self,db,x):
        state=triage.state(db,x['dataset'])
        available=state['started'] and (x['dataset']==triage.DEMO or state['clock']<=x['cutoff'])
        cs=[c for c in triage.queue(db,x['dataset']) if x['account'] in (None,c['account'])] if available else []
        return dict(started=state['started'],available=available,branch=state['branch'],
                    cases=[dict(id=c['id'],title=f"{KIND[c['kind']]} · {c['store']}",
                                account=c['account'],status=c['status'],status_label=STATUS[c['status']]) for c in cs])

    def case(self,db,s,x,case_id):
        if not isinstance(case_id,str) or len(case_id)>40:
            raise WebError('شناسهٔ پرونده نامعتبر است.')
        record=next((c for c in self.case_list(db,x)['cases'] if c['id']==case_id),None)
        if not record:
            raise WebError('پرونده در محدودهٔ گزارش یا دسترسی فعلی پیدا نشد.',404)
        c=triage._case(db,x['dataset'],case_id)
        cutoff=triage.state(db,x['dataset'])['clock']
        d=c['drafts'][-1]
        evidence=[]
        policies=triage._policy_facts(db,x['dataset'],'fixture' if x['dataset']==triage.DEMO else 'xlsx',cutoff)
        for e in c['evidence']:
            o,w=e['observation'],e['witness']
            if max(o['time'],o['available'])>cutoff or triage._scope(o,c['kind'])!=c['scope']:
                continue
            witnessed=bool(w and w['related_id']==o['id'] and o['time']<=w['time']<=cutoff and w['available']<=cutoff)
            valid=witnessed and o['fresh'] and o['coverage'] and o['mapped'] and o['status']=='ok'
            calc=triage.discount(o,policies) if valid and c['kind']=='discount' else {}
            evidence.append(dict(id=e['stamp'],time=o['time'],available=o['available'],valid=valid,
                                 retrieval=o['status'],orderable=o['orderable'] if valid else None,
                                 fresh=o['fresh'],coverage=o['coverage'],mapped=o['mapped'],
                                 price=o['price'] if valid else None,reference=o['reference'] if valid else None,
                                 percent=calc.get('discount'),cap=calc.get('cap'),policy_id=calc.get('id'),
                                 text=w['text'] if witnessed else None))
        writer=s.role in ('manager','digi','okala','snapp')
        owner=ROLES[s.role][1]==c['account'] and c['owner']=='specialist'
        return {**record,'dataset':x['dataset'],'cutoff':cutoff,'kind':c['kind'],'store':c['store'],
                'product':c['product'],'location':c['location'],'reason':d['reason_fa'],'next':d['next_action_fa'],
                'events':[e for e in c['events'] if e['clock']<=cutoff],'evidence':evidence,
                'drafts':c['drafts'],'referrals':c['referrals'],
                'can_decide':writer and c['status']!='closed' and d['approval'] in ('draft','edited'),
                'can_close':owner and c['status']=='recovery_verified'}

    def move_case(self,s,data,action):
        self.require(s,'manager','digi','okala','snapp')
        x=self.case_selector(s,data)
        with self.connect() as db, store.locked(db,x['dataset']):
            c=self.case(db,s,x,data.get('id'))
            if action=='close':
                if not c['can_close']:
                    raise WebError('بستن پرونده فقط با شاهد معتبر و توسط مسئول همان اکانت ممکن است.',403)
                triage.close(db,x['dataset'],c['id'],'specialist')
            else:
                if not c['can_decide'] or data.get('draft')!=c['drafts'][-1]['id']:
                    raise WebError('پیشنهاد فعال تغییر کرده یا بررسی شده است.',409)
                triage.decide(db,x['dataset'],c['id'],data['draft'],'manager' if s.role=='manager' else 'specialist',
                              value(data,'decision',('edit','approve','reject')),data.get('text'))
            return self.case(db,s,x,c['id'])

    def context(self,db,s,selector):
        kind=value(selector,'kind',('report','case'))
        eligible=s.role!='observer'
        if kind=='report':
            x=self.report_scope(s,selector)
            r=self.report(db,x)
            facts={'نوع':'گزارش فروش','مجموعه':x['dataset'],'فروشگاه':ACCOUNTS.get(x['account'],'همهٔ اکانت‌های مجاز'),
                   'برش':r['cutoff'],'فروش خالص':r['net'],'هدف ماه':r['target'],'هدف تا برش':r['due'],
                   'پوشش ناقص':r['missing'],'تفکیک ثبت، لغو و مرجوعی':r['counts'],
                   'منبع':'دموی ساختگی' if x['dataset']==triage.DEMO else
                   'اکسل و ثبت فرضی' if x['overlay'] else 'اکسل'}
            if x['dataset']=='workbook':
                facts['تاریخ و ساعت انتخاب‌شده']=[x['month'],x['day'],x['hour']]
            refs={f"PERF-{p['account']}":f"{ACCOUNTS[p['account']]} · فروش {p['net']} · هدف {p['target']}"
                  for p in r['performance'] if p['net'] is not None or p['target'] is not None}
            if x['dataset']=='workbook':
                refs.update({f"{row['source']}:{row['id']}@{row['rev']}":f"روز {row['day']} · فروش خالص {row['net']} بسته"
                             for row in r['rows'][-8:]})
            prompts=('وضعیت فروش نسبت به هدف چیست؟',
                     'کدام پلتفرم عملکرد بهتری داشته؟' if not x['account']
                     else 'کدام روزها فروش پایین‌تری داشتند؟' if r['rows'] else 'تفاوت فروش و هدف این حساب چیست؟',
                     'آیا دادهٔ کافی برای نتیجه‌گیری داریم؟' if r['missing'] or r['net'] is None
                     else 'یک قدم بعدی برای بررسی عملکرد پیشنهاد کن')
        else:
            x=self.case_selector(s,selector)
            c=self.case(db,s,x,selector.get('id'))
            facts={'نوع':KIND[c['kind']],'مجموعه':x['dataset'],'پرونده':c['id'],'وضعیت':c['status_label'],
                   'پلتفرم':ACCOUNTS[c['account']],'فروشگاه':c['store'],'محصول':PRODUCTS[c['product']],
                   'برش':c['cutoff'],
                   'وضعیت پیشنهاد انسانی': {'draft':'در انتظار بررسی','edited':'اصلاح شده','approved':'تأیید شده',
                                            'rejected':'رد شده','superseded':'جایگزین شده'}.get(c['drafts'][-1]['approval'])}
            refs={}
            for e in c['evidence'][-8:]:
                facts_e=f"زمان {e['time']} · دریافت {'ناموفق' if e['retrieval']=='error' else 'انجام شد'}"
                if e['percent'] is not None:
                    facts_e+=f" · تخفیف {e['percent']}٪"
                if e['price'] is not None:
                    facts_e+=f" · قیمت {e['price']} و قیمت مرجع {e['reference']} تومان"
                if e['cap'] is not None:
                    facts_e+=f" · سقف {e['cap']}٪ ({e['policy_id']})"
                if e['orderable'] is not None:
                    facts_e+=' · قابل سفارش' if e['orderable'] else ' · ناموجود'
                refs[e['id']]=facts_e
            if c['status']=='closed':
                prompts=('چرا پرونده بسته شده؟','متن اعلام نتیجه برای کارشناس بنویس','کدام شاهد بسته‌شدن را پشتیبانی می‌کند؟')
            elif c['kind']=='discount':
                prompts=('چرا این تخفیف نیاز به بررسی دارد؟','پیام پیگیری برای کارشناس بنویس','کدام شاهد قیمت یا سیاست لازم است؟')
            else:
                prompts=('آخرین شاهد معتبر چیست؟','آیا مشکل رفع شده؟','چه اقدامی برای پیگیری لازم است؟')
        # Operational/workbook data stays on the machine under the existing privacy contract.
        return Context(dict(selector),facts,refs,prompts,bool(eligible and x['dataset']==triage.DEMO and refs))

    def connection(self):
        if self.transport:
            return Connection('AvalAI','https://api.avalai.ir/v1','mock-test','offline-test-secret')
        return self.settings.connection()

    def ai(self,s,data,action):
        self.require(s,'manager','digi','okala','snapp','observer')
        if action=='cancel':
            with s.lock:
                s.pending=None
            return {}
        if action=='confirm':
            with s.lock:
                _,_,scope,selector,connection,body,mode,question=take(s,'pending',data.get('nonce'))
            with self.read() as db:
                ctx=self.context(db,s,selector)
            if ctx.scope!=scope or connection!=self.connection():
                raise WebError('زمینه یا مقصد تغییر کرد؛ دوباره پیش‌نمایش بگیرید.',409)
            if not ctx.may_send or not body or mode=='offline':
                raise WebError('در این زمینه ارسال آنلاین فعال نیست.',409)
            if not self.reserve(RESERVE):
                raise WebError('بودجهٔ روزانهٔ مشترک تکمیل شده است.',429)
            raw=completion(connection,body,self.transport)
            try:
                result=verify_response(raw,ctx.references)
            except ValueError:
                raise WebError('ساختار پاسخ، مقدار یا شناسهٔ شاهد مدل معتبر نبود.',502) from None
            with s.lock:
                history=s.history.setdefault(scope,[])
                history.append(dict(question=question,result=result,mode=mode))
                del history[:-6]
                s.history.move_to_end(scope)
                if len(s.history)>16:
                    s.history.popitem(last=False)
            return {'result':result,'mode':mode}
        selector=data.get('context')
        if not isinstance(selector,dict):
            raise WebError('زمینهٔ درخواست مشخص نیست.')
        with self.read() as db:
            ctx=self.context(db,s,selector)
        connection=self.connection()
        with s.lock:
            if action=='context':
                s.pending=None
                return dict(questions=ctx.questions,history=s.history.get(ctx.scope,[]),
                            mode=('mock' if self.transport else 'live') if connection and ctx.may_send else 'offline')
            return preview(s,ctx,data.get('question'),connection,bool(self.transport))

    def diagnostic_command(self,s,data,action):
        self.require(s,'admin')
        if action=='cancel':
            with s.lock:
                s.diagnostic=None
            return {}
        supplied = 'settings' in data
        pending_kind = s.diagnostic[3] if s.diagnostic else None
        kind = data.get('kind') if action=='prepare' else pending_kind
        conn = self.settings.candidate(data['settings'],allow_key=not self.hosted,
                                       require_key=kind!='network') if supplied else self.connection()
        if not conn:
            raise WebError('کلید API یا تنظیم معتبر وجود ندارد.')
        if action=='prepare':
            kind=value(data,'kind',('network','models','authentication','completion'))
            nonce=secrets.token_urlsafe(32)
            challenge='ECOM-'+secrets.token_hex(8)
            question='Reply with exactly this test identifier: '+challenge if kind in ('authentication','completion') else None
            with s.lock:
                s.diagnostic=(nonce,monotonic(),conn,kind,challenge,supplied)
            return dict(nonce=nonce,destination=conn.base+('/chat/completions' if question else '/models'),
                        model=conn.model,question=question,mock=bool(self.transport),kind=kind)
        with s.lock:
            _,_,approved,kind,challenge,had_settings=take(s,'diagnostic',data.get('nonce'))
        if approved!=conn or supplied!=had_settings:
            raise WebError('تنظیمات آزمون تغییر کرد؛ دوباره پیش‌نمایش بگیرید.',409)
        if not self.reserve(RESERVE if kind in ('authentication','completion') else 1):
            raise WebError('بودجهٔ روزانهٔ مشترک تکمیل شده است.',429)
        try:
            if kind in ('authentication','completion'):
                text=completion(conn,{'model':conn.model,'messages':[{'role':'user','content':
                    'Reply with exactly this test identifier: '+challenge}],'max_tokens':64},self.transport,diagnostic=True)
                if not isinstance(text,str) or text.strip()!=challenge:
                    raise WebError('پاسخ مدل شناسهٔ همین آزمون را تأیید نکرد.',502)
                status='احراز هویت و پاسخ درخواست محافظت‌شده تأیید شد' if kind=='authentication' else 'آزمون پاسخ مدل موفق'
            elif kind=='network':
                from web_ai import network_probe
                network_probe(conn,self.transport)
                status='دسترسی شبکه برقرار است؛ اعتبار کلید و مدل بررسی نشده است'
            else:
                result=request_model(conn,'GET','/models',transport=self.transport)
                options=result.get('data') if isinstance(result,dict) else None
                if not isinstance(options,list):
                    raise WebError('فهرست مدل‌ها در پاسخ معتبر نیست.',502)
                status='فهرست مدل‌ها دریافت شد؛ این آزمون اعتبار کلید یا پاسخ مدل را اثبات نمی‌کند'
        except WebError as exc:
            if not self.transport:
                self.settings.status(conn,str(exc))
            raise
        if not self.transport:
            self.settings.status(conn,status)
        return {'status':('Mock: ' if self.transport else '')+status,
                'kind':kind,'mode':'mock' if self.transport else 'live'}

    def import_command(self,s,data,action):
        self.require(s,'manager')
        if action=='cancel':
            s.import_pending=None
            return {}
        if action=='confirm':
            if data.get('confirm') is not True:
                raise WebError('ثبت فایل نیاز به تأیید صریح پیش‌نمایش دارد.')
            _,_,snapshot,items,counts,file_hash,name=take(s,'import_pending',data.get('nonce'))
            with self.connect() as db:
                try:
                    actual,reasons=store.commit_import(db,items,snapshot,actor=s.identity,
                        identity_source='proxy_authenticated' if self.hosted else 'local_simulation')
                except ValueError as exc:
                    raise WebError(str(exc),409) from None
            return dict(counts=actual,reasons=reasons[:100],reasons_total=len(reasons),file_hash=file_hash)
        from import_workflow import decode_upload,read_items
        from readers import BOOK
        with self.lock:
            for existing in self.sessions.values():
                if existing.import_pending and monotonic()-existing.import_pending[1]>600:
                    existing.import_pending=None
            if sum(x.import_pending is not None for x in self.sessions.values() if x is not s)>=4:
                raise WebError('ظرفیت پیش‌نمایش‌های فعال پر است؛ بعداً دوباره تلاش کنید.',429)
            s.import_pending=None
            if data.get('bundled') is True:
                name,raw=BOOK.name,BOOK.read_bytes()
            else:
                name=data.get('name')
                raw=decode_upload(name,data.get('content'))
            items,file_hash=read_items(name,raw)
            with self.connect() as db:
                snapshot,counts,reasons,rows=store.preview_import(db,items,include_rows=True)
            nonce=secrets.token_urlsafe(32)
            s.import_pending=(nonce,monotonic(),snapshot,items,counts,file_hash,name)
            return dict(nonce=nonce,name=name,file_hash=file_hash,counts=counts,
                        reasons=reasons[:100],reasons_total=len(reasons),rows=len(items),sample=rows,expires_seconds=600)

    def api(self,s,action,data):
        if action=='role':
            if self.hosted:
                raise WebError('شبیه‌سازی نقش در حالت احراز هویت غیرفعال است.',403)
            with s.lock:
                s.role=value(data,'role',ROLES)
                s.history.clear()
                s.pending=s.diagnostic=s.import_pending=None
            return self.bootstrap(s)
        if action=='settings':
            self.require(s,'admin')
            return self.settings.public()
        if action in ('settings-save','settings-clear'):
            self.require(s,'admin')
            if action=='settings-clear':
                cfg=self.settings.public()
                return self.settings.save(cfg['provider'],cfg['base'],cfg['model'],clear=True)
            return self.settings.save(data.get('provider'),data.get('base'),data.get('model'),data.get('key',''))
        if action in ('test-runs','test-attempt-review'):
            self.require(s,'admin')
            import live_test_ledger
            with self.connect() as db:
                if action=='test-runs':
                    return {'runs':live_test_ledger.list_runs(db)}
                if data.get('confirm') is not True:
                    raise WebError('ثبت بررسی به تأیید صریح نیاز دارد.')
                try:
                    return live_test_ledger.review_attempt(db,data.get('id'),resolution=data.get('resolution'),
                        note=data.get('note'),actor=s.identity,
                        identity_source='proxy_authenticated' if self.hosted else 'local_simulation')
                except live_test_ledger.LedgerError as exc:
                    raise WebError(str(exc),409) from None
        if action=='roles':
            self.require(s,'admin')
            return dict(assignments=self.settings.assignments(),local=not self.hosted)
        if action=='assign':
            self.require(s,'admin')
            if not self.hosted:
                raise WebError('مدیریت حساب واقعی تنها در حالت احراز هویت فعال است.',403)
            return self.settings.assign(data.get('identity'),data.get('role'))
        if action in ('diag-prepare','diag-confirm','diag-cancel'):
            return self.diagnostic_command(s,data,action[5:])
        self.require(s,'manager','digi','okala','snapp','observer')
        if action in ('ai-context','ai-prepare','ai-confirm','ai-cancel'):
            return self.ai(s,data,action[3:])
        if action=='report':
            with self.read() as db:
                return self.report(db,self.report_scope(s,data))
        if action=='cases':
            with self.read() as db:
                return self.case_list(db,self.case_selector(s,data))
        if action=='case':
            with self.read() as db:
                return self.case(db,s,self.case_selector(s,data),data.get('id'))
        if action in ('decide','close'):
            return self.move_case(s,data,action)
        if action in ('manual','manual-save'):
            self.require(s,'manager','digi','okala','snapp')
            acct=self.account(s,data)
            product=value(data,'product',PRODUCTS)
            month=value(data,'month',MONTHS[-2:])
            day=integer(data,'day',16 if month=='بهمن' else 1,days(month))
            with self.connect() as db:
                if action=='manual':
                    return {'record':store.manual_record(db,month,day,acct,product),
                            'history':store.manual_history(db,month,day,acct,product)}
                counts=[integer(data,k,0 if k!='price' else 1,10**9) for k in ('registered','cancelled','returned','price')]
                amounts=[data.get(k) for k in ('discount','share')]
                if not all(isinstance(a,str) and len(a)<=6 for a in amounts):
                    raise WebError('درصد نامعتبر است.')
                result=store.save_manual(db,month,day,acct,product,counts+[bp(a) for a in amounts],
                                         integer(data,'revision',0,10**9),data.get('confirm') is True,
                                         actor=s.identity,role=s.role,
                                         identity_source='proxy_authenticated' if self.hosted else 'local_simulation')
                return {'result':result}
        if action in ('import-prepare','import-confirm','import-cancel'):
            return self.import_command(s,data,action[7:])
        if action=='history':
            with self.read() as db:
                return {'dates':{a:store.workbook_dates(db,a) for a in self.accounts(s)},
                        'accounts':self.accounts(s),'products':PRODUCTS}
        if action in ('import','review','demo-start','demo-orderable','demo-error','demo-reset'):
            self.require(s,'manager')
            with self.connect() as db:
                if action=='import':
                    counts,reasons=store.import_book(db)
                    return dict(counts=counts,reasons=reasons)
                if action=='review':
                    z=self.report_scope(s,data|{'dataset':'workbook'})
                    triage.review_workbook(db,'manager',z['month'],z['day'],z['hour'])
                elif action=='demo-start':
                    triage.start(db,'manager')
                elif action=='demo-reset':
                    if data.get('confirm') is not True:
                        raise WebError('بازنشانی فقط پس از تأیید ممکن است.')
                    triage.reset(db,'manager')
                else:
                    triage.advance(db,'manager',action[5:])
            return {}
        raise WebError('مسیر پیدا نشد.',404)


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*_):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(45)

    def reply(self,status,body,mime):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        if self.close_connection:
            self.send_header('Connection','close')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Request-ID',self.request_id)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'self'; script-src 'self'; "
                         "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def json(self,data,status=200):
        if status>=400:
            data=dict(data,request_id=self.request_id)
            LOG.warning('request_id=%s method=%s status=%s',self.request_id,self.command,status)
        self.reply(status, encode(data).encode(), 'application/json; charset=utf-8')

    def local_origin(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def authorized(self):
        app=self.server.app
        if not app.hosted and self.headers.get('Host')!=self.local_origin().split('://')[1]:
            raise WebError('میزبان محلی مجاز نیست.',403)
        return app.identity(self.headers)

    def do_GET(self):
        self.request_id=secrets.token_hex(12)
        try:
            self.authorized()
            if self.path=='/health':
                return self.json({'app':APP_ID})
            assets={'/':('frontend/index.html','text/html'),'/app.js':('frontend/app.js','text/javascript'),
                    '/assistant.js':('frontend/assistant.js','text/javascript'),
                    '/style.css':('frontend/style.css','text/css'),'/app.css':('frontend/app.css','text/css'),
                    '/font.woff2':('static/Vazirmatn.woff2','font/woff2')}
            if self.path not in assets:
                raise WebError('صفحه پیدا نشد.',404)
            file,mime=assets[self.path]
            self.reply(200,(ROOT/file).read_bytes(),mime if mime.startswith('font/') else mime+'; charset=utf-8')
        except WebError as exc:
            self.json({'error':str(exc)},exc.status)

    def discard_rejected_body(self):
        # Drain only the already bounded upload envelope, without parsing or retaining it.
        # On Windows, closing with unread request bytes can discard the 403 response via RST.
        remaining=getattr(self,'unread_body',0)
        deadline=monotonic()+2
        try:
            self.connection.settimeout(.5)
            while remaining>0 and monotonic()<deadline:
                part=self.rfile.read1(min(65536,remaining))
                if not part:
                    break
                remaining-=len(part)
        except OSError:
            pass
        finally:
            self.unread_body=0

    def do_POST(self):
        self.request_id=secrets.token_hex(12)
        self.unread_body=0
        try:
            from import_workflow import MAX_JSON_BYTES
            size=int(self.headers.get('Content-Length','0'))
            if 1<=size<=MAX_JSON_BYTES:
                self.unread_body=size
            identity=self.authorized()
            app=self.server.app
            if self.headers.get('Origin')!=(app.origin if app.hosted else self.local_origin()):
                self.close_connection=True
                raise WebError('مبدأ درخواست معتبر نیست.',403)
            if self.headers.get_content_type()!='application/json':
                self.close_connection=True
                raise WebError('نوع درخواست معتبر نیست.',415)
            if not self.path.startswith('/api/'):
                self.close_connection=True
                raise WebError('درخواست معتبر نیست.')
            action=self.path[5:]
            session=None if action=='start' else app.session(self.headers.get('X-Active-Session'),identity)
            limit=8192
            if action=='import-prepare':
                app.require(session,'manager')
                from import_workflow import MAX_JSON_BYTES
                limit=MAX_JSON_BYTES
            size=int(self.headers.get('Content-Length','0'))
            if not 1<=size<=limit:
                self.close_connection=True
                raise WebError('اندازهٔ درخواست نامعتبر است.')
            raw=self.rfile.read(size)
            self.unread_body=0
            data=json.loads(raw)
            if not isinstance(data,dict):
                raise WebError('درخواست معتبر نیست.')
            if action=='start':
                return self.json(app.start(identity))
            with session.lock:
                self.json(app.api(session,action,data))
        except WebError as exc:
            self.close_connection=True
            self.discard_rejected_body()
            self.json({'error':str(exc)},exc.status)
        except psycopg.Error:
            self.json({'error':'اتصال یا خواندن و ثبت PostgreSQL کامل نشد.'},503)
        except (json.JSONDecodeError,UnicodeError,TimeoutError):
            self.json({'error':'درخواست ناقص یا نامعتبر است.'},400)
        except (ValueError,ArithmeticError,PermissionError) as exc:
            self.json({'error':str(exc) if str(exc) else 'ورودی نامعتبر است.'},403 if isinstance(exc,PermissionError) else 400)
        except OSError:
            self.json({'error':'خواندن یا ذخیرهٔ تنظیمات محلی کامل نشد.'},503)
        except Exception as exc:
            # Deliberately omit exception messages, request bodies and local variables.
            LOG.error('request_id=%s exception_type=%s',self.request_id,type(exc).__name__)
            self.json({'error':'پردازش درخواست کامل نشد؛ شناسهٔ خطا را برای پشتیبانی ارسال کنید.'},500)


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address=os.name!='nt'

    def server_bind(self):
        if os.name=='nt' and hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


def server(port,app):
    http=LocalServer(('127.0.0.1',port),Handler)
    http.app=app
    return http


def running(url):
    import httpx
    try:
        with httpx.Client(timeout=1,trust_env=False) as client:
            r=client.get(url+'health')
            return r.status_code==200 and r.json().get('app')==APP_ID
    except (httpx.RequestError,ValueError,AttributeError):
        return False


def main():
    parser=argparse.ArgumentParser(description='Active Sales unified web server')
    parser.add_argument('--port',type=int,default=PORT)
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--credential-status',action='store_true',help='Print presence only; no network or database access')
    args=parser.parse_args()
    if args.credential_status:
        for name in ('AVALAI_API_KEY','GAPGPT_API_KEY'):
            print(name+': '+('SET' if os.environ.get(name) else 'MISSING'))
        return 0
    if not 1<=args.port<=65535:
        parser.error('Port must be between 1 and 65535.')
    hosted=os.getenv('HOSTED')=='1'
    url=f'http://127.0.0.1:{args.port}/'
    try:
        app=Application(hosted=hosted,origin=os.getenv('ECOM_PUBLIC_ORIGIN'))
        try:
            http=server(args.port,app)
        except OSError:
            if not hosted and running(url):
                print(f'Active Sales is already running: {url}',flush=True)
                if not args.headless:
                    webbrowser.open(url)
                return 0
            print(f'Port {args.port} is unavailable. Close the other process; no second server was started.',file=sys.stderr)
            return 1
        with http:
            with store.connect() as db:
                store.initialize(db)
            print(f'Active Sales: {url}',flush=True)
            if not hosted and not args.headless:
                Timer(.25,webbrowser.open,(url,)).start()
            http.serve_forever()
    except KeyboardInterrupt:
        pass
    except (ValueError,OSError,psycopg.Error):
        print('Cannot start Active Sales. Verify local PostgreSQL is running and run Start-Windows.cmd --setup if needed.',
              file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
