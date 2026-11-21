"""Identity scopes and secret storage for the unified web application."""
from dataclasses import dataclass, field
import ctypes
from ctypes import wintypes
from base64 import b64decode, b64encode
import json
import os
import re
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit
from uuid import uuid4

import planner
from setup_local import BASE, protect_dir

ROLES = {
    'manager': ('مدیر', None, 'گزارش همهٔ اکانت‌ها، ورود اکسل و مدیریت دمو'),
    'digi': ('کارشناس دیجی‌کالا', 'ACC-DIGI', 'پیگیری و ثبت فقط دیجی‌کالا'),
    'okala': ('کارشناس اکالا', 'ACC-OKALA', 'پیگیری و ثبت فقط اکالا'),
    'snapp': ('کارشناس اسنپ', 'ACC-SNAPP', 'پیگیری و ثبت فقط اسنپ'),
    'observer': ('مشاهده‌گر', None, 'فقط‌خواندنی'),
    'admin': ('مدیر سیستم', None, 'کلید و تنظیمات اتصال، مدیریت مجوزها'),
}
PROVIDERS = {
    'GapGPT': (planner.GAPGPT_BASE_URL, '', (planner.GAPGPT_BASE_URL,)),
    'AvalAI': (planner.AVALAI_BASE_URL, planner.AVALAI_MODEL, tuple(sorted(planner.AVALAI_BASE_URLS))),
    'DeepSeek': ('https://api.deepseek.com/v1', 'deepseek-flash', ('https://api.deepseek.com/v1',)),
}


LIVE_KEY_ENV = {'AvalAI': 'AVALAI_API_KEY', 'GapGPT': 'GAPGPT_API_KEY'}


def environment_only():
    return os.environ.get('ECOM_AI_ENV_ONLY') == '1'


def environment_connection(provider, base, model, *, require_key=True):
    if provider not in LIVE_KEY_ENV or base not in PROVIDERS[provider][2]:
        raise ValueError('ارائه‌دهنده یا مقصد آزمون کنترل‌شده مجاز نیست.')
    if not isinstance(model, str) or not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,120}', model):
        raise ValueError('مدل آزمون باید صریحاً انتخاب شود.')
    key = os.environ.get(LIVE_KEY_ENV[provider], '')
    if not key and require_key:
        return None
    return Connection(provider, base, model, key)


def provider_options():
    options = dict(PROVIDERS)
    custom = os.environ.get('ECOM_COMPATIBLE_BASE_URL', '').strip().rstrip('/')
    if custom:
        p = urlsplit(custom)
        if (p.scheme == 'https' and p.hostname and re.fullmatch(r'[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+', p.hostname)
                and not re.fullmatch(r'[0-9.]+', p.hostname) and not p.hostname.endswith(('.local','.localhost'))
                and p.netloc == p.hostname and not p.fragment and not p.query and not p.username):
            options['OpenAI-Compatible'] = (custom, '', (custom,))
    return options


@dataclass(frozen=True)
class Connection:
    provider: str
    base: str
    model: str
    key: str = field(repr=False)


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('در این سیستم کلید را از مخزن امن یا محیط محافظت‌شدهٔ سرور تنظیم کنید.')
    buffer = ctypes.create_string_buffer(data)
    src, out = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    call = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not call(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(out)):
        raise ValueError('Windows نتوانست کلید را برای همین کاربر رمزگذاری یا بازیابی کند.')
    try:
        return ctypes.string_at(out.data, out.size)
    finally:
        kernel.LocalFree(out.data)


class Settings:
    def __init__(self, folder=None):
        location = folder or os.environ.get('ECOM_SETTINGS_DIR')
        self.folder = Path(location) if location else BASE / 'unified'
        self.path = self.folder / 'settings.json'
        self.lock = RLock()

    def _load(self):
        if not self.path.is_file():
            return {}
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise ValueError('خواندن تنظیمات محلی ممکن نشد؛ فایل را بررسی کنید.') from None

    def _write(self, data):
        if not self.folder.is_dir():
            protect_dir(self.folder)
        tmp = self.folder / (uuid4().hex+'.tmp')
        try:
            with os.fdopen(os.open(tmp, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def _values(self, data):
        p = data.get('provider', 'GapGPT')
        b, m, _ = provider_options().get(p, PROVIDERS['GapGPT'])
        return p, data.get('base', b), data.get('model', m)

    def connection(self):
        with self.lock:
            cfg = self._load()
            p, b, m = self._values(cfg)
            if environment_only():
                if 'provider' not in cfg or 'model' not in cfg:
                    return None
                return environment_connection(p,b,m)
            if b not in provider_options().get(p, ('','',()))[2]:
                return None
            secret = dpapi(b64decode(cfg['secret']), True).decode() if cfg.get('secret') else ''
            if not secret:
                secret = os.environ.get('ECOM_UNIFIED_API_KEY', '') if p == os.environ.get('ECOM_UNIFIED_KEY_PROVIDER') else ''
            return Connection(p,b,m,secret) if secret else None

    def candidate(self, data, *, allow_key=True, require_key=True):
        """Validate ephemeral form settings without persisting or replacing a typed key."""
        if not isinstance(data, dict):
            raise ValueError('تنظیمات آزمون نامعتبر است.')
        p, b, m, key = (data.get(k, '') for k in ('provider', 'base', 'model', 'key'))
        if not all(isinstance(v, str) for v in (p, b, m, key)):
            raise ValueError('تنظیمات آزمون نامعتبر است.')
        b = b.strip().rstrip('/')
        if (p not in provider_options() or b not in provider_options()[p][2]
                or not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,120}', m)):
            raise ValueError('ارائه‌دهنده، نشانی یا مدل مجاز نیست.')
        if environment_only():
            if key:
                raise ValueError('در آزمون کنترل‌شده کلید فقط از محیط سرور خوانده می‌شود.')
            connection = environment_connection(p,b,m,require_key=require_key)
            if connection is None:
                raise ValueError('متغیر محیطی کلید همین ارائه‌دهنده تنظیم نشده است.')
            return connection
        if key:
            if not allow_key:
                raise ValueError('کلید را در محیط محافظت‌شدهٔ سرور مدیریت کنید.')
            if not re.fullmatch(r'[!-~]{10,512}', key):
                raise ValueError('کلید API نامعتبر است.')
        else:
            saved = self.connection()
            if saved and (saved.provider, saved.base) == (p, b):
                key = saved.key
            elif require_key:
                raise ValueError('کلید API برای همین ارائه‌دهنده لازم است.')
        return Connection(p, b, m, key)

    def public(self):
        with self.lock:
            cfg = self._load()
            p,b,m = self._values(cfg)
            return dict(provider=p,base=b,model=m,has_key=bool(self.connection()),
                        status=cfg.get('status', 'هنوز آزمون نشده'),
                        editable_key=os.name=='nt' and os.environ.get('HOSTED')!='1' and not environment_only(),
                        options={k:{'base':v[0],'model':v[1]} for k,v in provider_options().items()
                                 if not environment_only() or k in LIVE_KEY_ENV})

    def save(self, p, b, m, key='', clear=False):
        options = provider_options()
        if not all(isinstance(v,str) for v in (p,b,m,key)):
            raise ValueError('تنظیمات نامعتبر است.')
        b=b.strip().rstrip('/')
        if p not in options or b not in options[p][2] or not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,120}',m):
            raise ValueError('Base URL یا شناسهٔ مدل برای ارائه‌دهنده معتبر نیست.')
        if environment_only():
            environment_connection(p,b,m,require_key=False)
        if (key or clear) and (environment_only() or os.name!='nt' or os.environ.get('HOSTED')=='1'):
            raise ValueError('کلید را از مخزن امن یا محیط محافظت‌شدهٔ سرور مدیریت کنید.')
        if key and not re.fullmatch(r'[!-~]{10,512}',key):
            raise ValueError('فقط کلید API را بدون پیشوند، فاصله و نقل‌قول وارد کنید.')
        with self.lock:
            cfg=self._load()
            old_p,old_b,_=self._values(cfg)
            if not environment_only() and (clear or (p,b)!=(old_p,old_b)):
                cfg.pop('secret',None)
            if key:
                cfg['secret']=b64encode(dpapi(key.encode())).decode()
            cfg.update(provider=p,base=b,model=m,status='هنوز آزمون نشده')
            self._write(cfg)
            return self.public()

    def status(self, connection, result):
        with self.lock:
            if connection != self.connection():
                return
            cfg = self._load()
            cfg['status'] = result
            self._write(cfg)

    def assignments(self):
        with self.lock:
            return self._load().get('roles',{})

    def role(self, identity):
        if identity == 'admin':
            return 'admin'
        preset = {'specialist':'digi', **{r:r for r in ROLES if r!='admin'}}
        return self.assignments().get(identity, preset.get(identity))

    def assign(self, identity, role):
        if (not isinstance(identity,str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,60}',identity)
                or identity=='admin' or not isinstance(role,str) or role not in (*ROLES,'blocked')):
            raise ValueError('شناسه یا نقش نامعتبر است.')
        with self.lock:
            cfg=self._load()
            cfg.setdefault('roles',{})[identity]=role
            self._write(cfg)
            return cfg['roles']
