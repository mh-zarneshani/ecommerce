"""Start the app on loopback, optionally with a process-local, hidden model key."""
import argparse
import getpass
import os
from pathlib import Path
import socket
import subprocess
import sys
import warnings

import planner
from probe_avalai import normalize_key
from store import config

def streamlit_command(port, headless):
    return [sys.executable,'-m','streamlit','run','app.py','--server.address','127.0.0.1',
            '--server.port',str(port),'--server.headless',str(headless).lower(),
            '--server.showEmailPrompt','false','--browser.serverAddress','127.0.0.1',
            '--browser.serverPort',str(port),'--browser.gatherUsageStats','false']

def available_port(preferred):
    for port in (preferred,0):
        with socket.socket() as sock:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            try:
                sock.bind(('127.0.0.1',port))
                return sock.getsockname()[1]
            except OSError:
                if port==0:
                    raise

def read_model_key(provider):
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        key=getpass.getpass(f'{provider} API key (hidden; never written to disk): ').strip()
    if provider=='GapGPT' and key.lower().startswith('bearer '):
        key=key[7:].strip()
    return key


def check_gapgpt():
    if os.environ.get('ECOM_AI_ENV_ONLY')=='1':
        print('BLOCKED: use the controlled diagnostics in the main application.')
        return 1
    print('این بررسی فقط فهرست مدل‌ها را می‌خواند؛ درخواست تحلیل یا دادهٔ فروش نمی‌فرستد.')
    key=read_model_key('GapGPT')
    if not key:
        print('کلید وارد نشد؛ هیچ درخواستی ارسال نشد.')
        return 1
    try:
        found=planner.gapgpt_check_model(key)
    except planner.ToolError as exc:
        print(str(exc))
        if exc.status in (401,403):
            print('کلید API و مجوز آن را در پنل توسعه‌دهندگان GapGPT بررسی کنید.')
        return 1
    model=planner.GAPGPT_DASHBOARD_MODEL
    if found:
        print(f'HTTP 200 — مدل {model} در فهرست برگشتی دیده شد.')
    else:
        print(f'HTTP 200 — مدل {model} در فهرست برگشتی نبود.')
    print('این نتیجه فقط مربوط به فهرست است؛ امکان تولید پاسخ مدل آزموده نشد.')
    return 0 if found else 1


def probe_gapgpt():
    if os.environ.get('ECOM_AI_ENV_ONLY')=='1':
        print('BLOCKED: use the controlled diagnostics in the main application.')
        return 1
    import httpx
    import re

    def safe_field(value, limit):
        # Only strings (and numeric error codes) reach the terminal.
        if type(value) not in (str,int):
            return '—'
        text=str(value).replace(key,'[REDACTED]')
        text=re.sub(r'(?i)\b(Bearer|Basic)\s+[\w./+\-=:]+',r'\1 [REDACTED]',text)
        text=re.sub(
            r"""(?ix)\b(authorization|api[-_\s]?key|access[-_\s]?token|refresh[-_\s]?token|
                      token|secret|password|passwd|cookie|session[-_\s]?id|credential|email|
                      phone|username|user[-_\s]?id|account[-_\s]?id|request[-_\s]?id)\b
                 ["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|\[REDACTED\]|[^\s,;]+)""",
            r'\1=[REDACTED]',text)
        # Reflected data can also appear in quotes, links, or as opaque tokens.
        text=re.sub(r"""(?ix)\bsk-[\w.-]+ | https?://[^\s<>]+ | [\w.+-]+@[\w.-]+\.[\w-]+ |
                       \b(?:\d{1,3}\.){3}\d{1,3}\b | [a-z0-9_+/=-]{32,}""",'[REDACTED]',text)
        text=re.sub(r"""(["`])[^"`\r\n]*\1|(?<!\w)'[^'\r\n]+'(?!\w)""",'[REDACTED]',text)
        text=text.replace('[REDACTED]','[حذف شد]')
        text=' '.join(re.sub(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]', ' ',text).split())
        return (text[:limit]+'…' if len(text)>limit else text) or '—'

    body={
        'model':planner.GAPGPT_DASHBOARD_MODEL,
        'messages':[{'role':'system','content':'You are a helpful assistant.'},
                    {'role':'user','content':'سلام'}],
        'max_tokens':150,
    }
    url=planner.GAPGPT_BASE_URL+'/chat/completions'
    print(f'نمونهٔ پشتیبانی GapGPT | مدل: {body["model"]} | مهلت HTTPX: ۶۰ ثانیه')
    print('متن آزمون: سلام | دستور سیستم: You are a helpful assistant.')
    print('این آزمون به دیتابیس وصل نمی‌شود. فقط یک درخواست مدل می‌فرستد و ممکن است هزینه داشته باشد.')
    print('1. تنظیمات فعلی HTTPX')
    print('2. نادیده گرفتن تنظیمات محیطی با trust_env=False')
    try:
        mode=input('حالت را انتخاب کنید (1 یا 2؛ Enter برای لغو): ').strip()
        approved=mode in ('1','2') and input('برای تأیید هزینه و ارسال همین یک درخواست، SEND را تایپ کنید: ').strip()=='SEND'
    except (EOFError,KeyboardInterrupt):
        approved=False
    if not approved:
        print('لغو شد؛ هیچ درخواستی ارسال نشد.')
        return 0
    try:
        key=read_model_key('GapGPT')
    except (EOFError,KeyboardInterrupt,getpass.GetPassWarning):
        print('ورود مخفی کلید انجام نشد؛ هیچ درخواستی ارسال نشد.')
        return 1
    if not key:
        print('کلید وارد نشد؛ هیچ درخواستی ارسال نشد.')
        return 1
    status=None
    try:
        with httpx.Client(timeout=60,trust_env=mode=='1',verify=True,follow_redirects=False) as client:
            with client.stream('POST',url,headers={'Authorization':f'Bearer {key}'},json=body) as response:
                status=response.status_code
                if status in (200,400):
                    response.read()
    except (httpx.HTTPError,OSError,ValueError):
        if status is None:
            print('خطای تنظیمات، ارتباط یا مهلت پاسخ؛ وضعیت HTTP دریافت نشد.')
        else:
            print(f'HTTP {status} — پاسخ ناقص: خواندن بدنه قطع شد.')
        return 1
    if status==400:
        if not response.content.strip():
            print('HTTP 400 — بدنهٔ پاسخ خالی است.')
            return 1
        try:
            payload=response.json()
        except (ValueError,RecursionError):
            detail=('بدنهٔ JSON ناقص یا نامعتبر است.' if response.content.lstrip().startswith((b'{',b'['))
                    else 'بدنهٔ پاسخ JSON نیست.')
            print(f'HTTP 400 — {detail}')
            return 1
        error=payload.get('error') if isinstance(payload,dict) else None
        error=error if isinstance(error,dict) else {}
        fields=('code','param','message')
        complete=(all(f in error for f in fields) and type(error['code']) in (str,int,type(None))
                  and type(error['param']) in (str,type(None))
                  and isinstance(error['message'],str) and bool(error['message'].strip()))
        print('HTTP 400'+('' if complete else ' — ساختار JSON خطا ناقص است.'))
        for field,limit in zip(fields,(64,64,160)):
            if field in error:
                print(f'error.{field}: {safe_field(error[field],limit)}')
        return 1
    if status!=200:
        print(f'نمونهٔ پشتیبانی: HTTP {status}')
        return 1
    try:
        text=response.json()['choices'][0]['message']['content']
        if not isinstance(text,str) or not text.strip():
            raise ValueError
    except (ValueError,KeyError,IndexError,TypeError):
        print('نمونهٔ پشتیبانی: HTTP 200، اما پاسخ متنی قابل خواندن نبود.')
        return 1
    print('نمونهٔ پشتیبانی: HTTP 200 — پاسخ متنی معتبر دریافت شد.')
    return 0


def read_avalai_settings():
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    class SettingsDialog(simpledialog.Dialog):
        def body(self, frame):
            tk.Label(frame,text='Base URL').grid(row=0,column=0,sticky='w',padx=6,pady=4)
            self.base=tk.Entry(frame,width=49)
            self.base.insert(0,planner.AVALAI_BASE_URL)
            self.base.grid(row=0,column=1,padx=6,pady=4)
            tk.Label(frame,text='AvalAI API token').grid(row=1,column=0,sticky='w',padx=6,pady=4)
            self.token=tk.Entry(frame,width=49,show='*')
            self.token.grid(row=1,column=1,padx=6,pady=4)
            self.paste_button=tk.Button(frame,text='Paste token',command=self.paste_token)
            self.paste_button.grid(row=1,column=2,padx=6,pady=4)
            for event in ('<<Paste>>','<Control-v>','<Control-V>','<Shift-Insert>'):
                self.token.bind(event,self.paste_token)
            if sys.platform=='win32':
                self.token.bind('<Control-KeyPress>',self.paste_windows_shortcut)
            tk.Label(frame,text='Synthetic demo only. No request is sent from this window.').grid(row=2,columnspan=3,pady=6)
            return self.token

        def paste_windows_shortcut(self,event):
            # Windows still reports VK_V when the active layout produces a Persian character.
            if event.keycode==0x56:
                return self.paste_token()
            return None

        def paste_token(self,_event=None):
            try:
                value=self.clipboard_get()
            except tk.TclError:
                messagebox.showwarning('No text to paste','Copy the AvalAI token first, then click Paste token.',parent=self)
            else:
                self.token.delete(0,'end')
                self.token.insert(0,value)
                self.token.focus_set()
            return 'break'

        def validate(self):
            try:
                base=planner.avalai_base_url(self.base.get())
            except ValueError:
                messagebox.showerror('Invalid base URL','Enter an official AvalAI HTTPS base URL.',parent=self)
                return False
            key=normalize_key(self.token.get())
            if key is None or not key.startswith('aa-') or len(key)<=3:
                messagebox.showerror('Invalid token','Paste the full AvalAI API token.',parent=self)
                return False
            self.result=(base,key)
            self.token.delete(0,'end')
            return True

    root=tk.Tk()
    try:
        root.withdraw()
        return SettingsDialog(root,title='AvalAI settings for DeepSeek').result
    finally:
        root.destroy()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8501)
    parser.add_argument('--headless',action='store_true')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--deepseek',action='store_true',help='Enable reviewed dashboard summaries.')
    mode.add_argument('--deepseek-demo',action='store_true',help='Enable paid inference only for the synthetic demo.')
    mode.add_argument('--avalai-demo',action='store_true',help='Open a local dialog for AvalAI synthetic demo inference.')
    mode.add_argument('--check-gapgpt',action='store_true',help='Read only the GapGPT model catalog.')
    mode.add_argument('--probe-gapgpt',action='store_true',help='One consented synthetic model request.')
    a=parser.parse_args()
    try:
        if a.check_gapgpt:
            return check_gapgpt()
        if a.probe_gapgpt:
            return probe_gapgpt()
        config()
        if not 1 <= a.port <= 65535:
            raise ValueError('پورت برنامه نامعتبر است.')
        env=dict(os.environ)
        env.pop('DEEPSEEK_API_KEY',None)
        env.pop('GAPGPT_API_KEY',None)
        env.pop('ECOM_LOCAL_AVALAI_BASE_URL',None)
        env.pop('ECOM_LOCAL_AVALAI_TOKEN',None)
        env['AGENT_MODE']='offline'
        env['SLICE_AGENT']='off'
        if a.avalai_demo:
            settings=read_avalai_settings()
            if settings is None:
                print('Cancelled. No request sent.')
                return 0
            env['ECOM_LOCAL_AVALAI_BASE_URL'],env['ECOM_LOCAL_AVALAI_TOKEN']=settings
        elif a.deepseek or a.deepseek_demo:
            key=read_model_key('GapGPT' if a.deepseek else 'DeepSeek')
            env['GAPGPT_API_KEY' if a.deepseek else 'DEEPSEEK_API_KEY']=key
            env.update(SLICE_AGENT='deepseek' if a.deepseek else 'off',
                       AGENT_MODE='deepseek' if a.deepseek_demo else 'offline')
        port=available_port(a.port)
        if port!=a.port:
            print(f'Port {a.port} is in use. Starting a new app at http://127.0.0.1:{port}/',flush=True)
        return subprocess.call(streamlit_command(port,a.headless),env=env,cwd=Path(__file__).resolve().parent)
    except (OSError,ValueError,getpass.GetPassWarning) as exc:
        print(str(exc),file=sys.stderr)
        return 1

if __name__=='__main__':
    sys.exit(main())
