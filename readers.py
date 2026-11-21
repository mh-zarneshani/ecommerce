"""Workbook columns are translated only here. No external URLs are opened."""
from dataclasses import dataclass
from decimal import Decimal as D
from pathlib import Path
from io import BytesIO
from typing import Iterable, Protocol

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries

from domain import ACCOUNTS, BRAND, CATEGORY, PRODUCTS, Input, Offer, Plan, Policy, Sale, Witness, bp, clock

ROOT = Path(__file__).resolve().parent
BOOK = ROOT / 'inputs/Active_Ecommerce_Bootcamp_Sample_Data(1).xlsx'

@dataclass(frozen=True)
class Rejected:
    row: str
    reason: str

class Reader(Protocol):
    def read(self) -> Iterable[Input | Rejected]: ...

class WorkbookReader:
    def __init__(self, path=BOOK, *, content=None):
        self.path = Path(path)
        self.content = content

    def read(self):
        book = load_workbook(BytesIO(self.content) if self.content is not None else self.path, read_only=True, data_only=True, keep_links=False)
        try:
            bounds = {r[0]:range_boundaries(r[6]) for r in book['دیکشنری داده'].iter_rows(min_row=5, values_only=True)
                      if isinstance(r[6],str) and r[6].startswith('A4:')}
            def rows(sheet):
                _, _, width, end = bounds[sheet]
                return enumerate(book[sheet].iter_rows(min_row=5,max_row=end,max_col=width,values_only=True),5)
            ref = {r[11]:r[9] for _,r in rows('کالاهای مرجع') if r[1:3] == (BRAND,CATEGORY) and r[11] in PRODUCTS}
            if set(ref) != set(PRODUCTS) or not any(r[0]=='روز تحلیل از ابتدای مهر' and r[1]==135 for _,r in rows('راهنما')):
                raise ValueError('دامنهٔ محصولات یا روز سناریو با فایل هم‌خوانی ندارد')
            offers = {r[0]:r for _,r in rows('جامعه عرضه') if r[0]}
            for sheet in ('فروش روزانه','برنامه ماهانه','پایش عرضه','سیاست تخفیف','شواهد خواندنی'):
                versions = {}
                for i,r in rows(sheet):
                    if not r[0]:
                        continue
                    label = f'{sheet}:{i}'
                    try:
                        if sheet == 'فروش روزانه':
                            key,absolute,m,d = r[:4]
                            if absolute != clock(m,d)//24+1 or r[16] not in ref:
                                raise ValueError('روز یا محصول ناسازگار است')
                            data = Sale(m,d,r[16],*r[6:10],bp(D(str(r[10]))*100),bp(D(str(r[11]))*100))
                            item = Input('sale',key,r[18],r[15],r[17],r[17],data,{})
                        elif sheet == 'برنامه ماهانه':
                            data = Plan(r[0],r[3],r[5])
                            start = clock(r[0],1,0)
                            item = Input('plan',f'{r[0]}/{r[13]}/{data.scope}',1,r[13],start,start,data,{})
                        elif sheet == 'پایش عرضه':
                            o = offers.get(r[6])
                            status = {'قابل سفارش':'ok','ناموجود':'ok','خطای دریافت':'error'}.get(r[11],'unknown')
                            matches = bool(o and (o[15],o[16],o[2],o[3],o[4]) == (r[17],r[18],r[7],r[8],r[9]))
                            data = Offer(r[18],r[6],r[9],f'{r[7]} / {r[8]}',status,
                                         bool(o and o[13]=='خدمت‌دهی فرض‌شده'),matches,
                                         r[11]=='قابل سفارش' if status=='ok' else None,r[12],r[13],r[14])
                            item = Input('offer',r[0],r[21],r[17],r[19],r[20],data,{})
                        elif sheet == 'سیاست تخفیف':
                            key = r[0]
                            data = Policy(r[12], '*' if r[3].startswith('همه') else r[3],
                                          '*' if r[4].startswith('همه') else r[4],
                                          (r[5]-1)*24,r[6]*24-1,str(D(str(r[7]))*100),r[8],r[10]=='مصوب فرضی')
                            item = Input('policy',key,1,r[11],data.start,data.start,data,{})
                        else:
                            if r[1] not in ('متن مشاهده صفحه عرضه','متن صفحه محصول'):
                                continue
                            key = r[0]
                            versions[key] = versions.get(key,0)+1
                            item = Input('witness',key,versions[key],None,r[2],r[3],Witness(r[4],r[5]),{})
                        yield Input(item.kind,item.id,item.revision,item.account,item.time,item.available,item.data,
                                    {'row':label,'file':self.path.name,'raw':list(r)})
                    except (ValueError,TypeError,ArithmeticError,AttributeError) as exc:
                        yield Rejected(label,str(exc))
        finally:
            book.close()

