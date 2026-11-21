"""Read tools shared by offline and online planners; host validates actions and citations."""
from http.client import HTTPException, IncompleteRead
from pathlib import Path
import json
import re
from queue import Empty, SimpleQueue
from threading import Thread
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import httpx

PROMPT = Path(__file__).parent / 'prompts/triage-system.md'
ACTIONS = {
    'check_store_supply':'وضعیت عرضه را با مسئول همین فروشگاه بررسی کنید.',
    'review_discount':'قیمت مشاهده‌شده و سقف مصوب را با کارشناس قیمت بررسی کنید.',
    'verify_source':'دریافت شاهد را دوباره امتحان کنید و وضعیت همان عرضه را مستقیم تأیید کنید.',
    'request_human_review':'شاهد کافی نیست؛ کارشناس منشأ و دامنهٔ داده را بررسی کند.',
    'review_recovery':'بازگشت قابلیت سفارش در همین فروشگاه را برای تصمیم مسئول پرونده مرور کنید.',
}
PRIORITY = {'check_store_supply':'high','review_discount':'medium','review_recovery':'review',
            'verify_source':'review','request_human_review':'review'}
TOOLS = {
    'observation':'Read the triggering observation and its validity.',
    'evidence':'Read the accessible witness for that observation.',
    'history':'Read earlier same-scope witness identifiers.',
    'policy':'Read the approved policy and calculated discount.',
    'performance':'Read same account category performance; never SKU sales.',
}

class ToolError(Exception):
    def __init__(self,message,*,status=None,reason=None):
        super().__init__(message)
        self.status=status
        self.reason=reason

def recommendation(ctx):
    o = ctx['observation']
    if not o['fresh'] or not o['coverage'] or not o['mapped'] or o['status']!='ok':
        return 'verify_source'
    if ctx['recovery']:
        return 'review_recovery'
    if ctx['kind']=='stockout' and o['orderable'] is False:
        return 'check_store_supply' if ctx['evidence'] else 'request_human_review'
    if ctx['kind']=='discount' and ctx['policy'].get('breach'):
        return 'review_discount' if ctx['evidence'] else 'request_human_review'
    return 'request_human_review'

class Tools:
    def __init__(self, ctx, cap=8):
        self.ctx, self.cap, self.trace, self.citations, self.by_tool = ctx,cap,[],set(),{}
    def read(self,name):
        if len(self.trace)>=self.cap:
            raise ToolError('سقف فراخوانی ابزار')
        if name not in TOOLS:
            raise ToolError('ابزار مجاز نیست')
        if any(t['tool']==name for t in self.trace):
            raise ToolError('ابزار تکراری بدون پیشرفت')
        ctx = self.ctx
        payload = ctx[name]
        if payload is None:
            self.trace.append({'tool':name,'ids':[],'error':'ناموجود'})
            raise ToolError('ابزار یا شاهد در دسترس نیست')
        facts = payload if isinstance(payload,list) else [payload]
        citations = {(x['id'],x['time']) for x in facts if 'id' in x and 'time' in x
                     and x['time']<=ctx['as_of'] and x.get('available',x['time'])<=ctx['as_of']
                     and x.get('scope',ctx['scope'])==ctx['scope']}
        self.citations.update(citations)
        self.by_tool[name] = citations
        self.trace.append({'tool':name,'ids':sorted(x[0] for x in citations)})
        return payload

def deferral(ctx,tools,reason,mode):
    return {'case_id':ctx['case_id'],'priority':'review','action_code':'request_human_review',
            'next_action_fa':ACTIONS['request_human_review'],'owner_role':'specialist',
            'reason_fa':reason,'evidence':[],'missing':['شاهد معتبر یا خروجی قابل اعتبارسنجی'],
            'mode':mode,'trace':tools.trace,'status':'deferred'}

def _refs(pairs):
    return [{'id':i,'time':t} for i,t in sorted(pairs)]

def validate(draft,tools,mode):
    ctx=tools.ctx
    required={'case_id','priority','action_code','next_action_fa','owner_role','reason_fa','evidence','missing'}
    try:
        if not isinstance(draft,dict) or set(draft)!=required or draft['case_id']!=ctx['case_id']:
            raise ValueError
        action=draft['action_code']
        if (action not in (recommendation(ctx),'request_human_review') or draft['priority'] not in ('high','medium','review')
            or draft['owner_role']!='specialist'):
            raise ValueError
        for key in ('reason_fa','next_action_fa'):
            s=draft[key]
            if not isinstance(s,str) or not 1<=len(s)<=500 or not re.search('[آ-ی]',s) or '<' in s or '://' in s:
                raise ValueError
        if not isinstance(draft['missing'],list) or len(draft['missing'])>8 or not all(
            isinstance(s,str) and len(s)<=250 for s in draft['missing']):
            raise ValueError
        if not isinstance(draft['evidence'],list) or len(draft['evidence'])>20:
            raise ValueError
        cited=set()
        for e in draft['evidence']:
            if set(e)!= {'id','time'} or type(e['time']) not in (int,float) or not isinstance(e['id'],str):
                raise ValueError
            cited.add((e['id'],e['time']))
        if not cited<=tools.citations or (not cited and (action!='request_human_review' or not draft['missing'])):
            raise ValueError
        for name in {'check_store_supply':('observation','evidence'),
                     'review_discount':('observation','evidence','policy'),
                     'verify_source':('observation',),
                     'review_recovery':('observation','evidence')}.get(action,()):
            if not cited & tools.by_tool.get(name,set()):
                raise ValueError
    except (ValueError, KeyError, TypeError):
        return deferral(ctx,tools,'خروجی یا استناد نامعتبر بود.',mode)
    priority = PRIORITY[action]
    if action=='check_store_supply' and not ctx['performance']['behind']:
        priority='medium'
    return dict(draft,priority=priority,mode=mode,trace=tools.trace,status='validated')

class Offline:
    mode='offline'
    def run(self,ctx):
        tools=Tools(ctx)
        try:
            o=tools.read('observation')
            action=recommendation(ctx)
            if not o['fresh'] or not o['coverage'] or not o['mapped'] or o['status']!='ok':
                tools.read('history')
                reason='دریافت یا اعتبار شاهد کافی نیست؛ نتیجهٔ پرونده تغییر قطعی نکرد.'
            else:
                tools.read('evidence')
                if ctx['recovery']:
                    reason='شاهد تازه از همین دامنه دوباره قابل سفارش بودن را نشان می‌دهد.'
                elif ctx['kind']=='discount':
                    p=tools.read('policy')
                    reason=(f"تخفیف صفحه {p['discount']}٪ و سقف مصوب {p['cap']}٪ است."
                            if p.get('breach') else 'سیاست یا قیمت به بررسی نیاز دارد.')
                else:
                    p=tools.read('performance')
                    reason=(f"عدم سفارش در همین عرضه تأیید شد؛ فروش دسته {p['net']} از هدف {p['target']} بسته است."
                            if p['target'] is not None else 'عدم سفارش در همین عرضه تأیید شد؛ عملکرد دسته نامشخص است.')
            draft=dict(case_id=ctx['case_id'],priority=PRIORITY[action],action_code=action,
                       next_action_fa=ACTIONS[action],owner_role='specialist',reason_fa=reason,
                       evidence=_refs(tools.citations),missing=['شاهد معتبر'] if PRIORITY[action]=='review' and
                       action!='review_recovery' else [])
            return validate(draft,tools,self.mode)
        except ToolError as exc:
            return deferral(ctx,tools,str(exc),self.mode)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*_args,**_kwargs):
        return None

GAPGPT_BASE_URL = 'https://api.gapgpt.app/v1'
GAPGPT_DASHBOARD_MODEL = 'gapgpt-deepseek-v4.1-flash'
AVALAI_BASE_URL = 'https://api.avalai.ir/v1'
AVALAI_BASE_URLS = frozenset((AVALAI_BASE_URL,'https://api.avalapis.ir/v1','https://api.avalai.org/v1'))
AVALAI_MODEL = 'deepseek-v4.1-flash'


def avalai_base_url(value):
    base=value.strip().rstrip('/')
    if base+'/v1' in AVALAI_BASE_URLS:
        base+='/v1'
    if base not in AVALAI_BASE_URLS:
        raise ValueError('آدرس پایه باید یکی از آدرس‌های رسمی HTTPS آوال‌ای‌آی باشد.')
    return base


def avalai_transport(base,key,body,timeout):
    url=avalai_base_url(base)+'/chat/completions'
    payload={**body,'model':AVALAI_MODEL}
    payload['max_completion_tokens']=payload.pop('max_tokens')
    try:
        with httpx.Client(timeout=timeout,verify=True,trust_env=False,follow_redirects=False) as client:
            response=client.post(url,headers={'Authorization':f'Bearer {key}'},json=payload)
            if response.status_code!=200:
                raise ToolError(f'آوال‌ای‌آی پاسخ HTTP {response.status_code} داد.',status=response.status_code)
            if key in response.text:
                raise ToolError('پاسخ مدل قابل نمایش نیست.')
            return response.json()
    except (httpx.HTTPError,ValueError):
        raise ToolError('ارتباط با آوال‌ای‌آی یا خواندن پاسخ ناموفق بود.') from None

def transport(key,body,timeout):
    return _post_completion('https://api.deepseek.com/chat/completions',key,body,timeout)

def gapgpt_transport(key,body,timeout):
    return _gapgpt_request('POST','/chat/completions',key,timeout,body=body)


def gapgpt_check_model(key):
    """Read the catalog without invoking a model or sending a prompt."""
    try:
        data=_gapgpt_request('GET','/models',key,10)['data']
        if not isinstance(data,list) or not all(isinstance(row,dict) for row in data):
            raise ValueError
        return any(row.get('id')==GAPGPT_DASHBOARD_MODEL for row in data)
    except ToolError as exc:
        detail=f'HTTP {exc.status}' if exc.status else 'خطای شبکه یا پاسخ ناقص'
        raise ToolError(f'دریافت فهرست مدل‌های GapGPT ناموفق بود ({detail}).',status=exc.status) from None
    except (ValueError,KeyError,TypeError):
        raise ToolError('قالب فهرست مدل‌های GapGPT معتبر نبود.') from None


def _gapgpt_client(timeout):
    # HTTPX defaults to zero transport retries; redirects could forward auth or resend a POST.
    return httpx.Client(timeout=timeout,follow_redirects=False)


def _bounded_gapgpt_body(response,limit):
    data=bytearray()
    for chunk in response.iter_bytes(chunk_size=4096):
        data.extend(chunk)
        if len(data)>limit:
            raise ValueError
    return data


def _gapgpt_request(method,path,key,timeout,*,body=None):
    headers={'Authorization':f'Bearer {key}','Accept':'application/json'}
    try:
        with _gapgpt_client(timeout) as client, client.stream(
            method,GAPGPT_BASE_URL+path,headers=headers,json=body
        ) as response:
            status=response.status_code
            if not 200<=status<300:
                reason=None
                if status in (400,422):
                    try:
                        reason=_gateway_error_reason(_bounded_gapgpt_body(response,4096))
                    except (httpx.RemoteProtocolError,httpx.ReadError):
                        reason='incomplete'
                    except (httpx.HTTPError,ValueError):
                        pass
                raise ToolError(f'خطای سرویس مدل (HTTP {status})',status=status,reason=reason)
            limit=2_000_000 if method=='GET' else 200_000
            return json.loads(_bounded_gapgpt_body(response,limit))
    except (httpx.RemoteProtocolError,httpx.ReadError):
        raise ToolError('پاسخ سرویس مدل ناقص رسید؛ تحلیلی نمایش داده نشد.',reason='incomplete') from None
    except (httpx.HTTPError,ValueError):
        raise ToolError('مهلت یا ارتباط سرویس مدل ناموفق بود') from None


def _gateway_error_reason(body):
    # Never propagate or log the body: providers can echo prompt or credential material.
    try:
        payload=json.loads(body)
        fields=payload['error']
        code=fields.get('code')
        param=fields.get('param')
        if code in ('model_not_found','invalid_model','unsupported_model','model_not_supported'):
            return 'model'
        if code in ('insufficient_quota','insufficient_balance','billing_hard_limit_reached'):
            return 'balance'
        if code in ('invalid_api_key','authentication_error'):
            return 'key'
        if code in ('context_length_exceeded','max_tokens_exceeded'):
            return 'length'
        if param in ('model','messages','max_tokens'):
            return param
    except (ValueError,KeyError,TypeError,AttributeError):
        pass
    return None

def _post_completion(endpoint,key,body,timeout):
    request=Request(endpoint,data=json.dumps(body).encode(),
                    headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect()).open(request,timeout=timeout) as response:
            return json.loads(response.read(200001))
    except HTTPError as exc:
        raise ToolError(f'خطای سرویس مدل ({exc.code})',status=exc.code) from None
    except IncompleteRead:
        raise ToolError('پاسخ سرویس مدل ناقص رسید؛ تحلیلی نمایش داده نشد.',reason='incomplete') from None
    except (URLError,TimeoutError,ValueError,OSError,HTTPException):
        raise ToolError('مهلت یا ارتباط سرویس مدل ناموفق بود') from None

def within_deadline(send, key, body, allowance):
    finished=SimpleQueue()
    def request():
        try:
            finished.put((True,send(key,body,allowance)))
        except Exception as exc:
            finished.put((False,exc))
    Thread(target=request,daemon=True).start()
    try:
        ok,result=finished.get(timeout=allowance)
    except Empty:
        raise ToolError('مهلت دریافت پاسخ مدل تمام شد') from None
    if not ok:
        raise result
    return result

DEFINITIONS=[{'type':'function','function':{'name':n,'description':d,
             'parameters':{'type':'object','properties':{},'additionalProperties':False}}}
             for n,d in TOOLS.items()]

class DeepSeek:
    mode='deepseek'
    def __init__(self,key,reserve,send=transport,enabled=False):
        self.key,self.reserve,self.send,self.enabled=key,reserve,send,enabled
    def run(self,ctx):
        tools=Tools(ctx)
        try:
            if ctx['dataset']!='class-demo' or not ctx.get('synthetic') or not self.enabled or not self.key:
                raise ToolError('کلید یا تأیید درخواست مدل برای این داده وجود ندارد.')
            deadline=time.monotonic()+20
            msgs=[{'role':'system','content':PROMPT.read_text(encoding='utf-8')},
                  {'role':'user','content':json.dumps({'case_id':ctx['case_id'],'kind':ctx['kind'],
                   'as_of':ctx['as_of']})+' Return one final JSON object only when done.'}]
            for _ in range(9):
                remain=deadline-time.monotonic()
                if remain<=0 or len(json.dumps(msgs))>16000:
                    raise ToolError('مهلت یا اندازهٔ نشست مدل تمام شد')
                if not self.reserve(17000):
                    raise ToolError('سقف روزانهٔ درخواست یا توکن مدل تمام شد')
                reply=within_deadline(self.send,self.key,dict(model='deepseek-flash',messages=msgs,thinking={'type':'disabled'},
                                             max_tokens=600,tools=DEFINITIONS,temperature=0),remain)
                m=reply['choices'][0]['message']
                calls=m.get('tool_calls') or []
                if not calls:
                    return validate(json.loads(m['content']),tools,self.mode)
                safe=[]
                for call in calls:
                    f=call['function']; name=f['name']; cid=call['id']
                    if not isinstance(cid,str) or len(cid)>120 or json.loads(f['arguments'])!={} or name not in TOOLS:
                        raise ToolError('فراخوانی نامعتبر مدل')
                    safe.append({'id':cid,'type':'function','function':{'name':name,'arguments':'{}'}})
                msgs.append({'role':'assistant','content':None,'tool_calls':safe})
                for call in safe:
                    name=call['function']['name']
                    facts=tools.read(name)
                    allowed={'id','time','available','status','fresh','coverage','mapped','orderable','account',
                             'net','target','behind','discount','cap','breach','reference','price'}
                    def strip(x):
                        return {k:v for k,v in x.items() if k in allowed}
                    safe_facts=[strip(x) for x in facts] if isinstance(facts,list) else strip(facts)
                    msgs.append({'role':'tool','tool_call_id':call['id'],
                                 'content':json.dumps(safe_facts,ensure_ascii=False)})
            raise ToolError('سقف دورهای مدل تمام شد')
        except ToolError as exc:
            return deferral(ctx,tools,str(exc),self.mode)
        except (ValueError,KeyError,TypeError,IndexError,OSError):
            return deferral(ctx,tools,'پاسخ مدل معتبر یا قابل دریافت نبود.',self.mode)

