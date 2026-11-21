"""Normalized records and deterministic numbers; independent of XLSX, UI and SQL."""
from dataclasses import asdict, dataclass
from decimal import Decimal as D
from math import isfinite

MONTHS = ('مهر','آبان','آذر','دی','بهمن','اسفند')
ACCOUNTS = {'ACC-DIGI':'دیجی‌کالا','ACC-OKALA':'اکالا','ACC-SNAPP':'اسنپ'}
PRODUCTS = {'PRD-CLEAR-450G':'شفاف ۴۵۰ گرمی','PRD-PEARL-450G':'صدفی ۴۵۰ گرمی','PRD-CREAM-2000G':'کرمی ۲۰۰۰ گرمی'}
BRAND, CATEGORY = 'اکتیو', 'مایع دستشویی'

def days(month):
    if month not in MONTHS:
        raise ValueError('ماه نامعتبر')
    return 29 if month == 'اسفند' else 30

def clock(month, day, hour=18):
    integer(day, 1, days(month))
    integer(hour, 0, 23)
    return (MONTHS.index(month)*30 + day-1)*24 + hour

def integer(value, lo=0, hi=10**14):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError('عدد صحیح خارج از محدوده است')
    return value

def bp(value):
    value = D(str(value))*100
    if not value.is_finite() or value != value.to_integral_value():
        raise ValueError('درصد حداکثر دو رقم اعشار دارد')
    return integer(int(value), 0, 10000)

def ratio(n, d):
    return None if n is None or not d else D(n)/D(d)

@dataclass(frozen=True)
class Sale:
    month: str
    day: int
    product: str
    registered: int
    cancelled: int
    returned: int
    price: int
    discount: int
    share: int

@dataclass(frozen=True)
class Plan:
    month: str
    target: int
    budget: int
    scope: str = 'training-category'

@dataclass(frozen=True)
class Offer:
    product: str
    offer: str
    store: str
    location: str
    status: str
    coverage: bool
    mapped: bool
    orderable: bool | None
    reference: int | None = None
    price: int | None = None
    witness: str | None = None

@dataclass(frozen=True)
class Policy:
    product: str
    offer: str
    location: str
    start: int
    end: int
    cap: str
    priority: int
    approved: bool

@dataclass(frozen=True)
class Witness:
    related_id: str
    text: str

@dataclass(frozen=True)
class Input:
    kind: str
    id: str
    revision: int
    account: str | None
    time: int
    available: int
    data: Sale | Plan | Offer | Policy | Witness
    trace: dict

    def validate(self):
        if (not isinstance(self.id, str) or not self.id.strip() or not isinstance(self.trace, dict)
            or not isinstance(self.data, {'sale':Sale,'plan':Plan,'offer':Offer,'policy':Policy,
                                          'witness':Witness}.get(self.kind, type(None)))):
            raise ValueError('شناسه، نوع رکورد یا منبع نامعتبر')
        if self.kind != 'witness' and self.account not in ACCOUNTS:
            raise ValueError(f'اکانت ناشناخته: {self.account!r}')
        integer(self.revision, 1)
        if not all(type(t) in (int,float) and isfinite(t) and 0 <= t <= 10**12 for t in (self.time,self.available)) or self.available < self.time:
            raise ValueError('زمان مشاهده یا دسترسی نامعتبر')
        x = self.data
        if isinstance(x, Sale):
            if x.product not in PRODUCTS or self.time//24 != clock(x.month,x.day)//24:
                raise ValueError('محصول یا زمان فروش نامعتبر')
            for n in (x.registered,x.cancelled,x.returned):
                integer(n, 0, 10**9)
            integer(x.price, 1, 10**9)
            integer(x.discount, 0, 10000); integer(x.share, 0, 10000)
            if x.cancelled + x.returned > x.registered:
                raise ValueError('لغو و مرجوع از ثبت‌شده بیشتر است')
        elif isinstance(x, Plan):
            days(x.month); integer(x.target); integer(x.budget)
            if x.scope != 'training-category' or self.revision != 1:
                raise ValueError('دامنه یا نسخهٔ برنامه نامعتبر')
        elif isinstance(x, Offer):
            if (x.product not in PRODUCTS or not all(isinstance(v,str) and v for v in (x.offer,x.store,x.location))
                or x.status not in ('ok','error','unknown') or type(x.coverage) is not bool
                or type(x.mapped) is not bool or (x.orderable is not None and type(x.orderable) is not bool)):
                raise ValueError('شاهد عرضه نامعتبر')
            for v in (x.reference, x.price):
                if v is not None:
                    integer(v)
        elif isinstance(x, Policy):
            if x.product not in (*PRODUCTS,'*'):
                raise ValueError('محصول سیاست نامعتبر')
            integer(x.start); integer(x.end,x.start); integer(x.priority)
            if not D(0) <= D(x.cap) <= D(100):
                raise ValueError('سقف سیاست نامعتبر')

    def payload(self):
        grain, units = {
            'sale': ('account/product/day', 'pack,toman,basis-point'),
            'plan': ('account/month/training-category', 'pack,toman'),
            'offer': ('account/product/offer/store/location', 'toman'),
            'policy': ('account/product/offer/location', 'percent'),
            'witness': ('linked-record', 'text'),
        }[self.kind]
        return dict(account=self.account,time=self.time,available=self.available,
                    grain=grain,units=units,**asdict(self.data))

