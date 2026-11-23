"""Fetch a frozen five-ticket CSV from a trusted ChatGPT Site and commit it later.

No credentials are logged, no redirection is permitted, and a source CSV is
never overwritten with different bytes. Called from a scheduled GitHub Action.
"""
import csv
import io
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DESTINATION = ROOT / 'comparisons'
HEADER = ['回','口','数字1','数字2','数字3','数字4','数字5','数字6']
MAX_BYTES = 12_000
JST = timezone(timedelta(hours=9))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Site redirected export request; refusing transfer')

def validate_csv(blob):
    if len(blob)>MAX_BYTES:
        raise ValueError('CSV exceeded safe 12KB bound')
    try:
        text=blob.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ValueError('CSV must be UTF-8') from exc
    reader=csv.DictReader(io.StringIO(text))
    if reader.fieldnames != HEADER:
        raise ValueError('Unexpected CSV header')
    rows=list(reader)
    if len(rows)!=5:
        raise ValueError('Expected exactly five rows')
    rounds=set()
    tickets=set()
    lines=[]
    patterns=set()
    for row in rows:
        if any(v is None for v in row.values()):
            raise ValueError('CSV has a missing column')
        try:
            round_id=int(row['回'])
            ticket_id=int(row['口'])
            values=tuple(int(row[f'数字{i}']) for i in range(1,7))
        except (ValueError, TypeError) as exc:
            raise ValueError('Non-integer entry in CSV') from exc
        if round_id<1 or ticket_id not in range(1,6):
            raise ValueError('Round/ticket identifier out of range')
        if len(set(values))!=6 or not all(1<=n<=43 for n in values):
            raise ValueError('Invalid LOTO6 ticket')
        rounds.add(round_id)
        tickets.add(ticket_id)
        patterns.add(tuple(sorted(values)))
        lines.append((ticket_id,values))
    if len(rounds)!=1 or tickets!=set(range(1,6)) or len(patterns)!=5:
        raise ValueError('Incomplete or duplicate five-ticket portfolio')
    return rounds.pop(),lines

def secure_url(source):
    parsed=urllib.parse.urlsplit(source)
    if parsed.scheme!='https' or parsed.username or parsed.password:
        raise ValueError('Use an HTTPS read-only Site export URL')
    host=(parsed.hostname or '').lower()
    if not (host.endswith('.chatgpt.site') and host != 'chatgpt.site'):
        raise ValueError('Export URL must be a ChatGPT Site')
    if parsed.port not in (None,443):
        raise ValueError('Unexpected URL port')
    return source

def fetch(url,token):
    headers={'Accept':'text/csv'}
    if token:
        # Token applies only to the HTTPS Site URL; redirects are disabled.
        headers['OAI-Sites-Authorization']='Bearer '+token
    req=urllib.request.Request(secure_url(url),headers=headers,method='GET')
    opener=urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req,timeout=20) as resp:
            if resp.status!=200:
                raise RuntimeError('Site export unavailable')
            data=resp.read(MAX_BYTES+1)
    except urllib.error.HTTPError as exc:
        # Never print response bodies or authentication headers.
        raise RuntimeError(f'Site export failed with HTTP {exc.code}') from None
    return data

def save(data,destination=DESTINATION,now=None):
    rid,rows=validate_csv(data)
    # Reject post-draw uploads masquerading as a historical fixed forecast.
    # A previously committed snapshot remains intact and available.
    filename=f'loto6-{rid}-fixed-5tickets.csv'
    path=destination/filename
    if path.exists():
        existing=path.read_bytes()
        existing_round,existing_rows=validate_csv(existing)
        if (existing_round,sorted(existing_rows))!=(rid,sorted(rows)):
            raise RuntimeError('An immutable historical Analyzer export differs; manual review required')
        return 'unchanged',filename
    # Acquisition time is NOT proof of the original fixed timestamp. Store
    # the first valid observed snapshot, refuse changes and let compare_models
    # label its provenance as unverified. Never silently back-date a lock.
    destination.mkdir(parents=True,exist_ok=True)
    # Canonical UTF-8 export for deterministic diffs.
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f,lineterminator='\n')
        writer.writerow(HEADER)
        for ticket,values in sorted(rows):
            writer.writerow([rid,ticket,*values])
    return 'created',filename

def main():
    url=os.getenv('SITE_FIXED_CSV_URL','').strip()
    token=os.getenv('SITE_EXPORT_AUTH','').strip()
    if not url:
        print('SETUP_REQUIRED: GitHub secret SITE_FIXED_CSV_URL is not configured')
        return 0
    try:
        status,filename=save(fetch(url,token))
        print(f'Site Analyzer import: {status} {filename}; source fixed timestamp unverified')
        return 0
    except Exception as exc:
        # No URL, secrets, query strings or raw payloads in logs.
        print(f'Site Analyzer sync error: {type(exc).__name__}: {str(exc)[:180]}',file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
