"""Persian/RTL Streamlit views for the PostgreSQL classroom app."""
from hashlib import sha256
from functools import partial
from html import escape
from pathlib import Path
import os

import psycopg
import streamlit as st

import access
from domain import ACCOUNTS, BRAND, CATEGORY, MONTHS, PRODUCTS, bp, days
from planner import AVALAI_BASE_URL, AVALAI_MODEL, DeepSeek, Offline, ToolError, avalai_base_url, avalai_transport
from probe_avalai import normalize_key
import slice_assistant as analysis
import store
import triage

st.set_page_config(page_title='دفتر فروش اکتیو',layout='wide')
st.html(Path(__file__).with_name('ui.css'))

ROLES={'manager':'مدیر','specialist':'مسئول پرونده','observer':'مشاهده‌گر'}
DATA='گزارش‌ها و سوابق'
DASHBOARD='داشبورد'
ENTRY='ثبت و اصلاح فروش'
DESK='میز پیگیری'
SETTINGS='تنظیمات'
DEMO='دموی ساختگی کلاس'
WORKBOOK_CASES='پرونده‌های اکسل'
INTRO={DASHBOARD:'فروش، برنامه و حمایت تخفیف را در محدودهٔ انتخابی بررسی کنید.',
       DESK:'پرونده‌های اولویت‌دار، شاهد تصمیم و اقدام بعدی را در یک میز مرور کنید.',
       ENTRY:'فروش فرضی جدا از اکسل ثبت می‌شود. برای اصلاح، همان محصول و روز را انتخاب کنید.',
       DATA:'ورود فایل آموزشی و دسترسی به گزارش فروش در تاریخ‌های موجود.',
       SETTINGS:'اتصال مدل، نمایش بخش تحلیل و دسترسی نقش‌ها را بررسی کنید.'}
WRITERS=('manager','specialist')
ACTIONS={'needs_review':'شواهد نیازمند بررسی','open':'باز','recovery_verified':'رفع با شاهد تأیید شد؛ پرونده باز است','closed':'بسته شد'}
KINDS={'stockout':'سفارش‌ناپذیری','discount':'تخفیف صفحه'}
LABELS={'opened':'باز شدن','evidence':'ثبت شاهد','drafted':'پیشنهاد دستیار','edit':'اصلاح پیشنهاد',
        'approve':'تأیید و ارجاع داخلی','reject':'رد پیشنهاد','recovery_verified':'تأیید بازگشت','closed':'بستن'}
FA=str.maketrans('0123456789','۰۱۲۳۴۵۶۷۸۹')
def fmt(x,decimal=0):
    return 'نامشخص' if x is None else f'{x:,.{decimal}f}'.replace(',','٬').replace('.','٫').translate(FA)
def scenario_time(x):
    return fmt(x,1 if x % 1 else 0)
def pct(x):
    return fmt(x*100,1)+'٪' if x is not None else 'نامشخص'
def signed(x):
    return ('+' if x is not None and x>0 else '')+fmt(x)

@st.cache_resource(show_spinner=False)
def init():
    with store.connect() as db:
        store.initialize(db)
    return True

def act(fn,*args,**kwargs):
    try:
        changed=fn(*args,**kwargs)
        st.session_state['message']='ثبت شد.' if changed is not False else 'این رویداد قبلاً ثبت شده است.'
        st.rerun()
    except (ValueError,PermissionError) as exc:
        st.warning(str(exc))

def go(view):
    st.session_state['next_view']=view
    st.rerun()

def open_dashboard(scope):
    st.session_state['active_slice']=scope
    go(DASHBOARD)

def manual(db,account,month,day):
    with st.container(border=True,key='card_entry'):
        st.caption('ثبت دستی مستقل از فایل اصلی است. فقط بهمن از روز ۱۶ و همهٔ ۲۹ روز اسفند.')
        ac,pc,mc,dc=st.columns(4)
        a=ac.selectbox('اکانت ثبت',list(ACCOUNTS),index=list(ACCOUNTS).index(account) if account else 0,
                       format_func=ACCOUNTS.get,key='manual-account')
        m=mc.selectbox('ماه ثبت',MONTHS[-2:],index=1 if month=='اسفند' else 0,key='manual-month')
        start=16 if m=='بهمن' else 1
        d=dc.selectbox('روز ثبت',list(range(start,days(m)+1)),
                       index=max(0,min(days(m),day)-start) if m==month else 0,key=f'manual-day-{m}')
        p=pc.selectbox('محصول ثبت',list(PRODUCTS),format_func=PRODUCTS.get)
        row=store.manual_record(db,m,d,a,p)
        v=row['payload'] if row else {}
        dims=['registered','cancelled','returned','price','discount','share']
        names=['ثبت‌شده (بسته)','لغو (بسته)','مرجوع (بسته)','قیمت مرجع (تومان)','تخفیف مصرف‌کننده (درصد)','سهم برند از تخفیف (درصد)']
        key=f'{a}-{m}-{d}-{p}-{row["revision"] if row else 0}'
        st.write(f'نسخهٔ ثبت: {fmt(row["revision"])}' if row else 'برای این محصول و روز هنوز فروشی ثبت نشده است.')
        with st.form(key):
            vals=[]
            counts=st.columns(3)
            pricing=st.columns(3)
            for i,(field,label) in enumerate(zip(dims,names)):
                col=(counts+pricing)[i]
                if i>=4:
                    value=col.number_input(label,0.,100.,float(v.get(field,0))/100,step=.01,format='%.2f')
                    vals.append(value)
                else:
                    vals.append(col.number_input(label,0 if i<3 else 1,10**9,
                                                v.get(field,100000 if i==3 else 0),step=1))
            confirm=st.checkbox('اصلاح همین ردیف را تأیید می‌کنم') if row else False
            submit=st.form_submit_button('ذخیرهٔ اصلاح' if row else 'ثبت فروش فرضی',type='primary')
        if submit:
            try:
                vals[4:]=[bp(value) for value in vals[4:]]
                result=store.save_manual(db,m,d,a,p,vals,row['revision'] if row else 0,confirm)
                st.session_state['message']='این مقدار قبلاً ثبت شده است.' if result=='duplicate' else 'فروش فرضی ذخیره شد.'
                open_dashboard(analysis.Slice(a,m,d,18,True))
            except (ValueError,ArithmeticError) as exc:
                st.warning(str(exc))

def select_data(db,who):
    active=st.session_state.get('active_slice')
    if who=='manager' and st.button('ورود اکسل آموزشی'):
        with st.spinner('در حال خواندن فایل آموزشی…'):
            st.session_state['import_result']=store.import_book(db)
    if 'import_result' in st.session_state and who=='manager':
        counts,reasons=st.session_state['import_result']
        with st.expander('نتیجهٔ ورود فایل'):
            st.write(counts)
            if reasons:
                st.table([dict(ردیف=r,علت=e) for r,e in reasons])

    account=st.selectbox('اکانت اکسل',list(ACCOUNTS),format_func=ACCOUNTS.get,
                         index=list(ACCOUNTS).index(active.account) if active else 0)
    dates=store.workbook_dates(db,account)
    if not dates:
        st.info('برای این اکانت هنوز فروش اکسل وارد نشده است. '
                + ('«ورود اکسل آموزشی» را بزنید.' if who=='manager' else 'از مدیر بخواهید فایل آموزشی را وارد کند.'))
        return
    selected=(active.month,active.day) if active else ('بهمن',15)
    month,day=st.selectbox('تاریخ موجود در اکسل',dates,index=dates.index(selected) if selected in dates else 0,
                           format_func=lambda t:f'{fmt(t[1])} {t[0]}',key=f'xlsx-date-{account}')
    hour=st.selectbox('ساعت برش',range(24),index=active.hour if active else 18,
                      format_func=lambda h:f'{fmt(h)}:۰۰')
    if st.button('نمایش داشبورد',type='primary'):
        open_dashboard(analysis.Slice(account,month,day,hour,False))

def show_scope(scope):
    st.markdown(f'**{ACCOUNTS[scope.account]} | {fmt(scope.day)} {scope.month} | '
                f'ساعت {fmt(scope.hour)}:۰۰ | {scope.source}**')

def scope_picker(scope):
    with st.container(key='scope_picker'), st.expander(f'محدوده: {ACCOUNTS[scope.account]} · {fmt(scope.day)} {scope.month} · {fmt(scope.hour)}:۰۰ · {scope.source}  /  تغییر'):
        a,m,d,h,source=st.columns([1.2,1,1,1,1.4])
        accounts=list(ACCOUNTS)
        account=a.selectbox('فروشگاه',accounts,index=accounts.index(scope.account),format_func=ACCOUNTS.get)
        months=list(MONTHS)
        month=m.selectbox('ماه سناریو',months,index=months.index(scope.month))
        valid=list(range(1,days(month)+1))
        day=d.selectbox('روز گزارش',valid,index=min(scope.day,len(valid))-1,format_func=fmt)
        hour=h.selectbox('تا ساعت',range(24),index=scope.hour,format_func=lambda x:f'{fmt(x)}:۰۰')
        combined=source.selectbox('منبع فروش',(False,True),index=int(scope.overlay),
                                  format_func=lambda x:'اکسل + ثبت دستی' if x else 'فقط اکسل')
        st.caption('ساعت، زمان دسترسی به داده را مشخص می‌کند. ردیف‌های فروش روزانه در ساعت ۱۸:۰۰ در دسترس‌اند.')
        if st.button('اعمال محدوده',type='primary'):
            st.session_state['active_slice']=analysis.Slice(account,month,day,hour,combined)
            st.rerun()

def dashboard(db,scope):
    show_scope(scope)
    x=scope.metrics(db)
    with st.container(key='sales_kpis'):
        for col,(label,val) in zip(st.columns(3),[('فروش خالص',fmt(x['net'])),('هدف کامل ماه',fmt(x['target'])),
                ('فاصله تا هدف (فروش منهای هدف)',signed(x['gap']))]):
            col.metric(label,val)
    with st.container(border=True,key='card_pace'):
        st.markdown(f"**تحقق برنامه تا این برش: {pct(x['pace'])}** · هدف وزن‌دار: {fmt(x['due'],1)} بسته")
        st.caption(f'تحقق هدف ماه: {pct(x["attain"])} · برند {BRAND} · {CATEGORY} · واحد فروش: بسته')
        if x['missing']:
            st.caption(f"{fmt(x['missing'])} خانهٔ محصول/اکانت/روز بدون ثبت است؛ جمع فقط دادهٔ موجود را پوشش می‌دهد.")
        if x['rows']:
            with st.expander('فروش به تفکیک روز و منبع'):
                st.dataframe([{'روز':r['payload']['day'],'اکانت':ACCOUNTS[r['payload']['account']],
                               'محصول':PRODUCTS[r['payload']['product']],'منبع':'اکسل' if r['source']=='xlsx' else 'ثبت دستی فرضی',
                               'شناسه':r['external_id'],'نسخه':r['revision'],'فروش خالص':
                               r['payload']['registered']-r['payload']['cancelled']-r['payload']['returned']}
                              for r in x['rows']],hide_index=True)
    with st.container(border=True,key='card_budget'):
        st.subheader('حمایت تخفیف')
        for col,(label,val) in zip(st.columns(3),[('مصرف حمایت تخفیف',fmt(x['spend'])),('بودجهٔ مصوب حمایت',fmt(x['budget'])),
                ('درصد مصرف بودجه',pct(x['util']))]):
            col.metric(label,val)
        st.caption('واحد هزینه: تومان')
    if x['net'] is None or not x['target'] or not x['budget']:
        st.caption('«نامشخص»: فروش یا برنامه در این برش موجود نیست، یا مخرج صفر است.')
    if x['disputed']:
        st.warning(f"{fmt(len(x['disputed']))} تعارض نسخه یا برنامه؛ آخرین مقدار پذیرفته‌شده در جمع حفظ شد.")
    return x
def model_budget():
    return access.model_budget(store.connect,int(os.getenv('LLM_DAILY_REQUESTS','18')),
                               int(os.getenv('LLM_DAILY_TOKENS','306000')))

def assistant(who,scope,metrics):
    st.caption('پرسش درباره همین گزارش است. فقط پس از تأیید، خلاصهٔ زیر از مسیر مجاز ارسال می‌شود.')
    labels={'pace':'فاصله تا برنامه','budget':'مصرف بودجه','coverage':'پوشش داده'}
    question=st.radio('پرسش پیشنهادی',list(analysis.QUESTIONS),format_func=labels.get,horizontal=True,key='report_question')
    st.markdown('**بازبینی داده‌های این پرسش**')
    st.caption(analysis.QUESTIONS[question])
    reviewed=analysis.preview(scope,metrics,question)
    st.code(reviewed,language='json',wrap_lines=True)
    signature=sha256(reviewed.encode()).hexdigest()
    allowed=who in WRITERS and os.getenv('HOSTED')!='1'
    enabled=os.getenv('SLICE_AGENT')=='deepseek' and allowed
    key=os.getenv('GAPGPT_API_KEY') if enabled else None
    if not allowed:
        st.info('ارسال تنها برای مدیر یا کارشناس در اجرای محلی مجاز است.')
        return
    if not enabled or not key:
        st.info('این صفحه در اجرای فعلی فقط پیش‌نمایش آفلاین دارد. برای استفاده از آوال‌ای‌آی به «دموی ساختگی کلاس» بروید.')
        return
    results=st.session_state.setdefault('slice_results',{})
    consent_key='slice-consent-'+signature
    result=results.get(signature)
    if result:
        state,message=result
        if state=='ok':
            st.subheader('تحلیل DeepSeek از طریق GapGPT')
            st.caption('اعداد و محدودیت داده از برنامه؛ اولویت بررسی از DeepSeek.')
            st.text(message)
        elif state=='error':
            st.error(message)
            def retry():
                results.pop(signature,None)
                st.session_state.pop(consent_key,None)
            st.button('آماده‌سازی تلاش دوباره',key='slice-retry-'+signature,on_click=retry)
        else:
            st.info('درخواست این پیش‌نمایش قبلاً آغاز شده است.')
        return
    consent=st.checkbox('خلاصه و پرسش بالا را بررسی کردم و هزینهٔ همین درخواست را تأیید می‌کنم.',
                        key=consent_key)
    clicked=st.button('ارسال به DeepSeek',type='primary',key='slice-send-'+signature,disabled=not consent)
    if clicked and consent and signature not in results:
        results[signature]=('pending','')
        with st.spinner('در انتظار پاسخ DeepSeek…'):
            try:
                answer=analysis.analyze(scope=scope,metrics=metrics,question=question,actor=who,consent=consent,
                                        enabled=enabled,key=key,reserve=model_budget())
                results[signature]=('ok',answer)
            except (ToolError,PermissionError) as exc:
                results[signature]=('error',str(exc))
            except (psycopg.Error,ValueError):
                results[signature]=('error','ثبت بودجهٔ درخواست ممکن نشد؛ ارسال انجام نشد.')
        st.rerun()

def workbook_cases(db,who,scope):
    if who in WRITERS and st.button('بررسی آفلاین شاهدهای اکسل تا برش'):
        act(triage.review_workbook,db,who,scope.month,scope.day,scope.hour)
    cstate=triage.state(db,'workbook')
    if cstate['started'] and cstate['clock']<=scope.metrics(db)['cutoff']:
        detail(db,'workbook',who,account=scope.account)
    elif cstate['started']:
        st.caption('صف پرونده‌ها برای برش بعدی ذخیره شده است.')
    else:
        st.info('برای این محدوده هنوز بررسی ثبت نشده است.')

def detail(db,dataset,who,account=None):
    cs=[c for c in triage.queue(db,dataset) if not account or c['account']==account]
    if not cs:
        st.caption('پرونده‌ای در این نما نیست.')
        return
    by_id={c['id']:c for c in cs}
    def queue_label(i):
        c=by_id[i]
        return f"{ACCOUNTS[c['account']]} · {KINDS[c['kind']]} · {c['store']} — {ACTIONS[c['status']]}"
    with st.container(key='desk_grid'):
        right,left=st.columns([1,2.35])
        with right.container(border=True,key='desk_queue'):
            st.subheader('صف پیگیری')
            st.caption(f'{fmt(len(cs))} پرونده در این محدوده')
            picked=st.radio('پرونده',list(by_id),format_func=queue_label,key=f'case_pick_{dataset}',label_visibility='collapsed')
        with left.container(border=True,key='desk_case'):
            case_panel(db,dataset,who,by_id[picked])

def case_panel(db,dataset,who,c):
    d=c['drafts'][-1]
    tone='wait' if c['latest']['status']=='error' or c['status']=='needs_review' else 'action' if c['status']=='open' else ''
    title=f"{KINDS[c['kind']]} · {c['store']}"
    place=f"{c['offer']} | {c['location']} | {PRODUCTS[c['product']]} | مسئول: {ROLES[c['owner']]}"
    st.html(f'<section class="desk-case-head {tone}"><span class="desk-pill">{escape(ACTIONS[c["status"]])}</span>'
            f'<h2>{escape(title)}</h2><p>{escape(place)}</p><p>{escape(d["reason_fa"])}</p></section>')
    st.subheader('شاهد تصمیم')
    with st.expander('شاهد، استناد و ابزارهای بررسی',expanded=True):
        st.write('استناد: '+ '، '.join(f"{e['id']} ({scenario_time(e['time'])})" for e in d['evidence']))
        for i,e in enumerate(c['evidence']):
            o=e['observation']; w=e['witness']
            with st.container(key=f'proof_{i}'):
                st.caption(f"{e['stamp']} | ساعت مشاهده {scenario_time(o['time'])} | دسترسی {scenario_time(o['available'])}")
                st.write(('خطای دریافت' if o['status']=='error' else 'دریافت شده' if o['status']=='ok' else 'وضعیت نامعلوم')
                         + f" | {'تازه' if o['fresh'] else 'کهنه'} | {'در پوشش' if o['coverage'] else 'خارج از پوشش'}"
                         + f" | {'نگاشت منطبق' if o['mapped'] else 'نگاشت نیازمند بررسی'} | سفارش: "
                         + ('بله' if o['orderable'] is True else 'خیر' if o['orderable'] is False else 'نامشخص'))
                if w: st.text(w['text'])
        st.write('ابزارها: ' + ' ← '.join(t['tool'] for t in d['trace']))
    st.html(f'<div class="desk-next"><b>اقدام پیشنهادی</b><p>{escape(d["next_action_fa"])}</p></div>')
    if who in ('manager','specialist') and d['status']=='validated' and d['approval'] in ('draft','edited') and c['status']!='closed':
        with st.form('review-'+dataset+d['id']):
            value=st.text_area('متن ارجاع داخلی',value=d['edited'] or d['original'],max_chars=500)
            cols=st.columns(3)
            edit=cols[0].form_submit_button('ذخیرهٔ متن اصلاحی')
            approve=cols[1].form_submit_button('تأیید و ایجاد ارجاع داخلی')
            reject=cols[2].form_submit_button('رد پیشنهاد')
        if edit or approve or reject:
            act(triage.decide,db,dataset,c['id'],d['id'],who,'edit' if edit else 'approve' if approve else 'reject',
                value if edit or approve else None)
    if who==c['owner'] and c['status']=='recovery_verified':
        if st.button('بستن پرونده توسط مسئول'):
            act(triage.close,db,dataset,c['id'],who)
    with st.expander('خط زمانی، پیشنهادها و ارجاع‌های داخلی',expanded=True):
        for e in c['events']:
            st.write(f"{fmt(e['clock'])} | {LABELS.get(e['type'],e['type'])} | {ROLES.get(e['actor'],e['actor'])} | {e.get('id','')}")
        for d in c['drafts']:
            st.write(f"{d['id']} | {d['approval']} | متن اولیه: {d['original']} | اصلاح: {d['edited'] or '—'}")
        for r in c['referrals']:
            st.write(f"{r['id']} | {r['text']}")
    if st.session_state.get('show_case_ai',True):
        with st.container(key='case_ai'), st.expander('✦ تحلیل زمینه‌ای همین پرونده'):
            st.caption(f"حالت دستیار: {'آفلاین' if d['mode']=='offline' else 'DeepSeek'} | وضعیت: {d['status']} | بررسی انسانی: {d['approval']}")
            st.markdown('**مبنای پاسخ**')
            st.text(d['reason_fa'])
            st.markdown('**محدودیت و اقدام پیشنهادی**')
            st.text('دادهٔ لازم: '+ '، '.join(d['missing']) if d['missing'] else 'نتیجه به شواهد همین پرونده محدود است.')
            st.text(d['next_action_fa'])

def local_demo_connection(*,edit=False):
    if os.getenv('HOSTED')=='1' or st.get_option('server.address') not in ('127.0.0.1','::1','localhost'):
        return None
    key=os.getenv('ECOM_LOCAL_AVALAI_TOKEN')
    base=os.getenv('ECOM_LOCAL_AVALAI_BASE_URL')
    startup=(base,key) if base and key else None
    settings=st.session_state.get('local_avalai',startup)
    if not edit:
        return settings
    with st.expander('تنظیمات مدل آنلاین دمو',expanded=True):
        st.caption(f'آوال‌ای‌آی | مدل: {AVALAI_MODEL} | کلید روی دیسک ذخیره نمی‌شود.')
        with st.form('avalai_settings',clear_on_submit=True):
            base=st.text_input('آدرس پایه (Base URL)',value=(settings[0] if settings else AVALAI_BASE_URL),key='avalai_base_input')
            token=st.text_input('کلید API (توکن)',type='password',key='avalai_token_input')
            saved=st.form_submit_button('ثبت تنظیمات برای این نشست')
        if saved:
            try:
                base=avalai_base_url(base)
                key=normalize_key(token)
                if key is None or not key.startswith('aa-') or len(key)<=3:
                    raise ValueError('کلید کامل آوال‌ای‌آی را وارد کنید.')
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state['local_avalai']=(base,key)
                st.session_state.pop('avalai_paid_consent',None)
                st.rerun()
        if settings:
            st.success('تنظیمات آوال‌ای‌آی آماده است. هنوز برای شروع دمو باید هزینه را تأیید کنید.')
            if st.button('پاک کردن تنظیمات آوال‌ای‌آی',key='clear_avalai'):
                if startup:
                    st.session_state['local_avalai']=None
                else:
                    st.session_state.pop('local_avalai',None)
                st.session_state.pop('avalai_paid_consent',None)
                st.rerun()
    return settings


def demo(db,who):
    st.caption('مجموعه: class-demo | فقط اکالا و اسنپ | منبع: سناریوی محلی | فروش در دانه‌بندی دسته، به بسته')
    s=triage.state(db)
    st.caption(f"ساعت برش سناریو: {fmt(s['clock'])}" if s['started'] else 'ابتدا مدیر نقطهٔ شروع دمو را ثبت کند.')
    if s['performance']:
        for col,p in zip(st.columns(2),s['performance'].values()):
            col.metric(ACCOUNTS[p['account']],f"{fmt(p['net'])} / {fmt(p['target'])} بسته")
    if who=='manager':
        planner=Offline()
        can_advance=True
        settings=local_demo_connection()
        if settings:
            base,key=settings
            approved=st.checkbox('درخواست‌های پولی آوال‌ای‌آی برای دادهٔ ساختگی این دمو را تأیید می‌کنم',key='avalai_paid_consent')
            planner=DeepSeek(key,model_budget(),send=partial(avalai_transport,base),enabled=approved)
            can_advance=approved
        elif os.getenv('AGENT_MODE')=='deepseek':
            approved=st.checkbox('درخواست پولی DeepSeek برای دادهٔ ساختگی این دمو را صریحاً تأیید می‌کنم')
            key=os.getenv('DEEPSEEK_API_KEY')
            planner=DeepSeek(key,model_budget(),enabled=approved)
            if not key:
                st.warning('کلید محلی DeepSeek تنظیم نشده؛ هیچ درخواستی ارسال نمی‌شود.')
            elif not approved:
                st.info('برای اجرای دستیار آنلاین، ابتدا درخواست پولی را تأیید کنید.')
                can_advance=False
        else:
            st.caption('دستیار آفلاین است. برای اتصال اختیاری، بخش تنظیمات را باز کنید.')
        if not s['started'] and st.button('آغاز دمو',disabled=not can_advance):
            act(triage.start,db,who,planner)
        if s['started'] and not s['branch']:
            a,b=st.columns(2)
            if a.button('دوباره قابل سفارش شد',disabled=not can_advance):
                act(triage.advance,db,who,'orderable',planner)
            if b.button('دریافت اطلاعات خطا داد',disabled=not can_advance):
                act(triage.advance,db,who,'error',planner)
        if s['started'] and st.button('بازنشانی فقط دموی ساختگی'):
            act(triage.reset,db,who)
    detail(db,triage.DEMO,who)

def settings_page(who,hosted):
    with st.container(border=True,key='card_settings'):
        st.subheader('اتصال دستیار تحلیل')
        if who=='manager' and not hosted:
            local_demo_connection(edit=True)
            st.caption('آوال‌ای‌آی فقط به دموی ساختگی متصل است. ثبت تنظیمات، درخواستی ارسال نمی‌کند.')
        else:
            st.caption('تنظیم اتصال در اجرای محلی برای مدیر و در استقرار برای مدیر سرور در دسترس است.')
        def set_visibility(key):
            st.session_state[key]=st.session_state['widget_'+key]
        for key,label in (('show_report_ai','نمایش دستیار در داشبورد فروش'),('show_case_ai','نمایش دستیار در جزئیات پرونده')):
            st.checkbox(label,value=st.session_state.get(key,True),key='widget_'+key,on_change=set_visibility,args=(key,))
    with st.container(border=True,key='card_roles'):
        st.subheader('نقش‌ها و دسترسی‌ها')
        st.caption(f'نقش فعلی: {ROLES[who]} · '+('توسط ورود امن تعیین می‌شود.' if hosted else 'برای شبیه‌سازی نقش، از انتخاب‌گر هدر استفاده کنید.'))
        st.markdown('**مدیر:** ورود اکسل، مدیریت سناریوی دمو، ثبت فروش و بازبینی ارجاع.\n\n'
                    '**مسئول پرونده:** ثبت فروش، بازبینی ارجاع و بستن پروندهٔ واگذارشده پس از تأیید شواهد.\n\n'
                    '**مشاهده‌گر:** مشاهدهٔ شاخص‌ها، سوابق و پرونده‌ها.')

def main():
    hosted=os.getenv('HOSTED')=='1'
    if hosted:
        who=access.actor(st.context.headers,None)
    else:
        who=None
    if hosted and not who:
        st.error('برای دسترسی به برنامه وارد شوید.')
        st.stop()
    with st.container(key='desk_header',horizontal=True,vertical_alignment='center'):
        st.html('<div class="desk-brand"><span aria-hidden="true">✓</span>دفتر فروش اکتیو</div>')
        if hosted:
            st.caption(f'نقش کاربر: {ROLES[who]}')
        else:
            with st.container(key='desk_user',horizontal=True,vertical_alignment='center',width='content'):
                st.html('<span class="desk-role-hint" aria-hidden="true">شبیه‌سازی نقش</span>')
                local=st.selectbox('نقش شبیه‌سازی محلی',list(ROLES),format_func=ROLES.get,key='desk_role',
                                   width=116,label_visibility='collapsed')
            who=access.actor(st.context.headers,local)
    if not who:
        st.error('برای دسترسی به برنامه وارد شوید.')
        st.stop()
    views=(DASHBOARD,DESK,ENTRY,DATA,SETTINGS) if who in WRITERS else (DASHBOARD,DESK,DATA,SETTINGS)
    pending=st.session_state.pop('next_view',None)
    selected=pending or st.session_state.get('page',DASHBOARD)
    if selected not in views:
        selected=DASHBOARD
    if st.session_state.get('page')!=selected:
        st.session_state['page']=selected
    st.html(f'<p class="desk-crumb">دفتر فروش / {escape(selected)}</p><h1 class="desk-title">{escape(selected)}</h1>'
            f'<p class="desk-intro">{escape(INTRO[selected])}</p>')
    with st.container(key='desk_nav'):
        view=st.radio('نمای برنامه',views,key='page',horizontal=True,label_visibility='collapsed')
    if msg:=st.session_state.pop('message',None):
        st.success(msg)
    if view==SETTINGS:
        settings_page(who,hosted)
        return
    try:
        init()
        with store.connect() as db:
            scope=st.session_state.get('active_slice',analysis.Slice('ACC-DIGI','بهمن',15,18,False))
            if view==DATA:
                with st.container(border=True,key='card_history'):
                    select_data(db,who)
            elif view==ENTRY and who in WRITERS:
                manual(db,scope.account,scope.month,scope.day)
            elif view==DASHBOARD:
                scope_picker(scope)
                metrics=dashboard(db,scope)
                if st.session_state.get('show_report_ai',True):
                    with st.container(key='report_ai'), st.expander('✦ پرسش از هوش مصنوعی درباره همین گزارش'):
                        assistant(who,scope,metrics)
            elif view==DESK:
                mode=st.radio('مجموعهٔ پرونده‌ها',(WORKBOOK_CASES,DEMO),horizontal=True,key='desk_mode',label_visibility='collapsed')
                if mode==DEMO:
                    demo(db,who)
                else:
                    scope_picker(scope)
                    workbook_cases(db,who,scope)
    except psycopg.Error as exc:
        st.error('اتصال یا عملیات PostgreSQL ناموفق بود. راه‌انداز محلی و سرویس را بررسی کنید. '+(exc.sqlstate or ''))
    except ValueError as exc:
        st.error(str(exc))
    st.html('<footer class="desk-footer">دفتر فروش اکتیو · کارگاه آموزشی · داده‌های سناریو از داده‌های فروش جدا هستند.</footer>')

main()

