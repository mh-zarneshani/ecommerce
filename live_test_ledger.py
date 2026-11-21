"""Durable controlled-test reservations; never creates approval or makes network calls."""
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from uuid import uuid4

class LedgerError(ValueError):
    pass


LOCK=618114005
KINDS={'network','models','authentication','inference','assistant','invalid_token'}


def _amount(value):
    try:
        result=Decimal(str(value))
    except (InvalidOperation,ValueError):
        raise LedgerError('Invalid budget or rate.') from None
    if not result.is_finite() or result<0 or result>1000000:
        raise LedgerError('Invalid budget or rate.')
    return result


def create_run(connect, run_id, connection, *, approved_by, price_evidence,
               input_rate, output_rate, budget_usd='0.20', max_requests=6):
    """Internal operator service. No HTTP endpoint auto-arms this ledger."""
    from web_config import PROVIDERS
    if (not isinstance(run_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id)
        or connection.provider not in ('AvalAI','GapGPT')
        or connection.base not in PROVIDERS[connection.provider][2]
        or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}',connection.model)
        or not isinstance(approved_by,str) or not 1<=len(approved_by)<=120
        or not isinstance(price_evidence,str) or not 1<=len(price_evidence)<=500
        or type(max_requests) is not int or not 1<=max_requests<=6):
        raise LedgerError('Explicit provider/model/approval/price evidence is required.')
    inp,out,budget=map(_amount,(input_rate,output_rate,budget_usd))
    if not 0<budget<=Decimal('0.20'):
        raise LedgerError('Budget must be positive and at most USD 0.20.')
    with connect() as db, db.transaction():
        db.execute("""insert into ai_test_runs
            (run_id,provider,base_url,model,approved_by,price_evidence,input_rate,output_rate,max_requests,budget_usd)
            values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id,connection.provider,connection.base,connection.model,approved_by,price_evidence,
             inp,out,max_requests,budget))


@dataclass
class Outcome:
    status: str = 'success'
    http_status: int | None = None

    def expected_rejection(self, status):
        if status not in (401,403):
            raise LedgerError('Expected authentication rejection must be 401 or 403.')
        self.status,self.http_status='expected_rejection',status


@contextmanager
def attempt(connect, run_id, connection, kind):
    """Global sequential lock; durable reservation precedes caller's network operation.

    Unfinished reservations block subsequent attempts, even after a process crash.
    No path refunds cost/attempts or automatically retries an uncertain POST.
    """
    if kind not in KINDS:
        raise LedgerError('Unknown controlled-test request kind.')
    with connect() as db:
        if not db.autocommit:
            raise LedgerError('Durable reservations require an autocommit connection.')
        acquired=db.execute('select pg_try_advisory_lock(%s) as acquired',(LOCK,)).fetchone()['acquired']
        if not acquired:
            raise LedgerError('Another controlled request is active; no request sent.')
        try:
            with db.transaction():
                if db.execute("select 1 from ai_test_attempts where status='reserved' limit 1").fetchone():
                    raise LedgerError('An earlier attempt is unresolved; operator review is required.')
                run=db.execute('select * from ai_test_runs where run_id=%s and provider=%s for update',
                               (run_id,connection.provider)).fetchone()
                if (not run or run['stopped'] or run['base_url']!=connection.base or run['model']!=connection.model):
                    raise LedgerError('No active approval for this exact provider and model.')
                totals=db.execute("""select count(*) as count,coalesce(sum(reserved_usd),0) as cost
                    from ai_test_attempts where run_id=%s and provider=%s""",(run_id,connection.provider)).fetchone()
                # Conservative documented allowance; this estimate is not an invoice guarantee.
                cost=(8192*run['input_rate']+150*run['output_rate'])/1000000
                if totals['count']>=run['max_requests'] or totals['cost']+cost>run['budget_usd']:
                    raise LedgerError('Controlled request or estimated cost budget is exhausted.')
                ticket=uuid4().hex
                db.execute("""insert into ai_test_attempts(id,run_id,provider,ordinal,kind,reserved_usd,status)
                    values(%s,%s,%s,%s,%s,%s,'reserved')""",
                    (ticket,run_id,connection.provider,totals['count']+1,kind,cost))
            outcome=Outcome()
            try:
                yield outcome
            except BaseException as exc:
                http_status=getattr(exc,'provider_status',None)
                if type(http_status) is not int or not 100<=http_status<=599:
                    http_status=None
                status='failed' if http_status is not None else 'unknown'
                with db.transaction():
                    db.execute("update ai_test_attempts set status=%s,http_status=%s,finished_at=clock_timestamp() where id=%s",(status,http_status,ticket))
                    db.execute('update ai_test_runs set stopped=true where run_id=%s and provider=%s',(run_id,connection.provider))
                raise
            else:
                if outcome.status not in ('success','expected_rejection'):
                    raise LedgerError('Invalid outcome; reservation remains unresolved.')
                with db.transaction():
                    db.execute("update ai_test_attempts set status=%s,http_status=%s,finished_at=clock_timestamp() where id=%s",
                               (outcome.status,outcome.http_status,ticket))
        finally:
            db.execute('select pg_advisory_unlock(%s)',(LOCK,))


def list_runs(db):
    runs=db.execute('select run_id,provider,model,stopped,created_at from ai_test_runs order by created_at desc limit 20').fetchall()
    for run in runs:
        run['attempts']=db.execute("""select a.id,a.ordinal,a.kind,a.status,a.reserved_usd,a.http_status,
            a.created_at,r.resolution,r.actor as reviewer,r.note,r.reviewed_at
            from ai_test_attempts a left join ai_test_reviews r on r.attempt_id=a.id
            where a.run_id=%s and a.provider=%s order by a.ordinal""",(run['run_id'],run['provider'])).fetchall()
    return runs


def review_attempt(db,attempt_id,*,resolution,note,actor,identity_source):
    if (not isinstance(attempt_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',attempt_id)
        or resolution not in ('confirmed_failed','confirmed_completed','uncertain')
        or not isinstance(note,str) or not 3<=len(note.strip())<=300
        or re.search(r'(?i)bearer|api[_ -]?key|[A-Za-z0-9_+/=-]{24,}',note)
        or not isinstance(actor,str) or not actor
        or identity_source not in ('proxy_authenticated','local_simulation')):
        raise LedgerError('یادداشت و نتیجهٔ بررسی معتبر لازم است؛ کلید یا اطلاعات محرمانه وارد نکنید.')
    note=note.strip()
    with db.transaction():
        acquired=db.execute('select pg_try_advisory_xact_lock(%s) as acquired',(LOCK,)).fetchone()['acquired']
        if not acquired:
            raise LedgerError('درخواست فعال است؛ بررسی را پس از پایان آن انجام دهید.')
        attempt_row=db.execute('select * from ai_test_attempts where id=%s for update',(attempt_id,)).fetchone()
        if not attempt_row or attempt_row['status'] not in ('reserved','unknown','failed'):
            raise LedgerError('این تلاش برای بررسی توقف انتخاب نشده است.')
        existing=db.execute('select * from ai_test_reviews where attempt_id=%s',(attempt_id,)).fetchone()
        if existing:
            if (existing['resolution'],existing['note'],existing['actor'])==(resolution,note,actor):
                return {'result':'duplicate'}
            raise LedgerError('بررسی قبلاً ثبت شده و قابل جایگزینی نیست.')
        db.execute("""insert into ai_test_reviews(attempt_id,prior_status,resolution,actor,identity_source,note)
            values(%s,%s,%s,%s,%s,%s)""",(attempt_id,attempt_row['status'],resolution,actor,identity_source,note))
        # Human review is not provider success. Never refund usage or resume this run.
        if attempt_row['status']=='reserved':
            db.execute("update ai_test_attempts set status='unknown',finished_at=clock_timestamp() where id=%s",(attempt_id,))
        db.execute('update ai_test_runs set stopped=true where run_id=%s and provider=%s',
                   (attempt_row['run_id'],attempt_row['provider']))
        return {'result':'reviewed'}
