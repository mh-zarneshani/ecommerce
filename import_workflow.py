"""Bounded XLSX preview using the existing reader and persistence rules. No disk upload."""
import base64
import binascii
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile,BadZipFile

from openpyxl import load_workbook
from readers import BOOK,WorkbookReader

MAX_UPLOAD_BYTES=5*1024*1024
MAX_JSON_BYTES=7*1024*1024
MAX_ITEMS=10000
SHEETS=('دیکشنری داده','کالاهای مرجع','راهنما','جامعه عرضه','فروش روزانه',
        'برنامه ماهانه','پایش عرضه','سیاست تخفیف','شواهد خواندنی')


@lru_cache(maxsize=1)
def expected_headers():
    with BOOK.open('rb') as file:
        book=load_workbook(file,read_only=True,data_only=True,keep_links=False)
        try:
            return {name:tuple(next(book[name].iter_rows(min_row=4,max_row=4,values_only=True))) for name in SHEETS}
        finally:
            book.close()


def decode_upload(name,encoded):
    if (not isinstance(name,str) or not 1<=len(name)<=120 or Path(name).name!=name
        or not name.lower().endswith('.xlsx')):
        raise ValueError('فقط فایل XLSX با قالب فعلی پروژه پشتیبانی می‌شود؛ فایل XLS پشتیبانی نمی‌شود.')
    if not isinstance(encoded,str) or len(encoded)>((MAX_UPLOAD_BYTES+2)//3)*4:
        raise ValueError('حجم فایل بیش از سقف پنج مگابایت است.')
    try:
        raw=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):
        raise ValueError('محتوای بارگذاری معتبر نیست.') from None
    if not raw or len(raw)>MAX_UPLOAD_BYTES:
        raise ValueError('فایل خالی یا بزرگ‌تر از سقف مجاز است.')
    return raw


def read_items(name,raw):
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries=archive.infolist()
            if len(entries)>300 or sum(e.file_size for e in entries)>64*1024*1024:
                raise ValueError('ساختار فشردهٔ فایل بیش از سقف مجاز است.')
            if any(e.flag_bits & 1 or 'vbaproject' in e.filename.lower() for e in entries):
                raise ValueError('فایل رمزدار یا دارای ماکرو پذیرفته نمی‌شود.')
            for entry in entries:
                if entry.filename.endswith(('.xml','.rels')):
                    content=archive.read(entry).replace(b'\x00',b'').upper()
                    if b'<!DOCTYPE' in content or b'<!ENTITY' in content:
                        raise ValueError('تعریف موجودیت XML در فایل مجاز نیست.')
        book=load_workbook(BytesIO(raw),read_only=True,data_only=True,keep_links=False)
        try:
            for sheet,header in expected_headers().items():
                if sheet not in book.sheetnames:
                    raise ValueError('کاربرگ لازم وجود ندارد: '+sheet)
                ws=book[sheet]
                if not ws.max_row or not ws.max_column or ws.max_row>12000 or ws.max_column>100:
                    raise ValueError('ابعاد کاربرگ خارج از محدوده است: '+sheet)
                actual=tuple(next(ws.iter_rows(min_row=4,max_row=4,max_col=len(header),values_only=True)))
                if actual!=header:
                    raise ValueError('ستون‌های کاربرگ با قالب پروژه هم‌خوان نیست: '+sheet)
            # The reader uses the data dictionary's bounds, so validate those separately.
            from openpyxl.utils.cell import range_boundaries
            for row in book['دیکشنری داده'].iter_rows(min_row=5,max_col=7,values_only=True):
                if isinstance(row[6],str) and row[6].startswith('A4:'):
                    left,top,right,bottom=range_boundaries(row[6])
                    if right>100 or bottom>12000:
                        raise ValueError('محدودهٔ جدول در دیکشنری داده بیش از حد مجاز است.')
        finally:
            book.close()
        items=[]
        for item in WorkbookReader(name,content=raw).read():
            if len(items)>=MAX_ITEMS:
                raise ValueError('تعداد رکوردهای فایل بیش از سقف مجاز است.')
            items.append(item)
        return items,sha256(raw).hexdigest()
    except ValueError:
        raise
    except (BadZipFile,KeyError,IndexError,TypeError,OSError,SyntaxError,RuntimeError):
        raise ValueError('ساختار فایل XLSX یا قالب کاربرگ‌ها معتبر نیست.') from None
