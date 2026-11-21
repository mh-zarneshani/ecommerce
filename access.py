"""Local simulated actors, or trusted identities established by the HTTPS proxy."""
import hmac
import os

def actor(headers,local_actor=None):
    if os.getenv('HOSTED')!='1':
        return local_actor if local_actor in ('manager','specialist','observer') else None
    expected=os.getenv('PROXY_TOKEN')
    received=headers.get('X-Ecom-Proxy-Token','')
    if not expected or not hmac.compare_digest(received.encode(),expected.encode()):
        return None
    user=headers.get('X-Ecom-Identity','')
    return user if user in ('manager','specialist','observer') else None

def model_budget(connect,requests,tokens):
    def reserve(cost):
        if type(cost) is not int or not 0 < cost <= tokens or requests < 1:
            return False
        with connect() as db:
            row=db.execute("""insert into model_budget(day,requests,tokens)
                values ((now() at time zone 'UTC')::date,1,%s)
                on conflict(day) do update set requests=model_budget.requests+1,
                tokens=model_budget.tokens+excluded.tokens
                where model_budget.requests<%s and model_budget.tokens+excluded.tokens<=%s
                returning requests""",(cost,requests,tokens)).fetchone()
            return bool(row)
    return reserve

