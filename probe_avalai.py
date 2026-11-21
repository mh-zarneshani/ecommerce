"""Standalone AvalAI smoke test. No dashboard, database, or credential files."""
import os
import getpass
import re
import sys
import warnings

import httpx

URL = 'https://api.avalai.ir/v1/chat/completions'
MODEL = 'deepseek-v4.1-flash'
MAX_TOKENS = 150
UUID = re.compile(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}',re.I)
HTTP_DETAILS = {
    400:'Request rejected.',
    401:'Authentication was rejected.',
    402:'Check available API credit.',
    403:'Access to this request was denied.',
    404:'Endpoint or model was not found.',
    429:'Request limit reached.',
}
BEARER_PREFIX = re.compile(r'(?:Authorization:[ \t]*)?Bearer[ \t]+',re.I|re.ASCII)
KEY_PATTERN = re.compile(r'[A-Za-z0-9._~+/\-]+=*')
EDGE_MARKS = '\u061c\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff'
QUOTES = {'"':'"', "'":"'", '“':'”', '‘':'’', '«':'»'}


def trim_copy_edges(text):
    start, end = 0, len(text)
    while start < end and (text[start].isspace() or text[start] in EDGE_MARKS):
        start += 1
    while end > start and (text[end-1].isspace() or text[end-1] in EDGE_MARKS):
        end -= 1
    return text[start:end]


def unwrap_key(text):
    text=trim_copy_edges(text)
    if len(text)>=2 and QUOTES.get(text[0])==text[-1]:
        text=trim_copy_edges(text[1:-1])
    return text


def normalize_key(text):
    text=unwrap_key(text)
    prefix=BEARER_PREFIX.match(text)
    if prefix:
        text=unwrap_key(text[prefix.end():])
    if not KEY_PATTERN.fullmatch(text) or text.lower()=='bearer':
        return None
    return text


def prompt_key(windows_dialog):
    if windows_dialog:
        import tkinter as tk
        from tkinter.simpledialog import askstring

        root=tk.Tk()
        try:
            root.withdraw()
            return askstring('AvalAI API key', 'Paste the original API key (Ctrl+V).\nThe key is hidden.',
                             parent=root, show='*')
        finally:
            root.destroy()
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        return getpass.getpass('AvalAI API key (hidden): ')


def main(*, windows_dialog=False):
    if os.environ.get('ECOM_AI_ENV_ONLY')=='1':
        print('BLOCKED: use the controlled diagnostics in the main application.')
        return 1
    # ASCII console text also works in CMD fonts that cannot display Persian.
    print(f'AvalAI model test: POST {URL}')
    print(f'Model: {MODEL} | One greeting in Persian | Output limit: {MAX_TOKENS} tokens')
    try:
        if input('This one request may use paid credit. Type SEND to continue: ').strip() != 'SEND':
            print('Cancelled. No request sent.')
            return 0
        pasted=prompt_key(windows_dialog)
    except (EOFError,KeyboardInterrupt,getpass.GetPassWarning):
        print('Cancelled. No request sent.')
        return 0
    if pasted is None:
        print('Cancelled. No request sent.')
        return 0
    if not trim_copy_edges(pasted):
        print('No key was received. Paste your AvalAI API key and press Enter. No request sent.')
        return 1
    key=normalize_key(pasted)
    del pasted
    if key is None:
        print('Input is not a single API key. Copy the original key, not a masked value or a label. No request sent.')
        return 1

    status=None
    request_id=None
    try:
        with httpx.Client(timeout=60,verify=True,trust_env=False,follow_redirects=False) as client:
            with client.stream('POST',URL,headers={'Authorization':f'Bearer {key}'},json={
                'model':MODEL,
                'messages':[{'role':'user','content':'سلام'}],
                'max_completion_tokens':MAX_TOKENS,
            }) as response:
                status=response.status_code
                request_id=response.headers.get('avalai-request-id','')
                if status==200:
                    response.read()
    except (httpx.HTTPError,OSError,ValueError):
        if status is None:
            print('Connection, TLS, or timeout error. No HTTP status received.')
        else:
            print(f'HTTP {status} - Response body could not be read.')
            show_request_id(request_id,key)
        return 1

    print(f'HTTP {status}')
    show_request_id(request_id,key)
    if status!=200:
        print(HTTP_DETAILS.get(status,'No successful completion.'))
        return 1
    try:
        choice=response.json()['choices'][0]
        content=choice['message']['content']
        if isinstance(content,str) and content.strip():
            print('PASS - Model returned a text completion.')
            return 0
        if choice.get('finish_reason')=='length':
            print('No text returned before the output token limit.')
            return 1
    except (ValueError,KeyError,TypeError,IndexError,RecursionError):
        pass
    print('No readable text completion.')
    return 1


def show_request_id(request_id,key):
    if request_id and UUID.fullmatch(request_id) and key not in request_id:
        print(f'AvalAI request ID: {request_id}')


if __name__=='__main__':
    raise SystemExit(main(windows_dialog='--windows-dialog' in sys.argv[1:]))
