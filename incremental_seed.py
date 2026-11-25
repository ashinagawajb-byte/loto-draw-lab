"""Incremental LOTO6 research using the public result feed used by Analyzer.
Baseline searches retain their existing cursors; newly published rounds have
independent 32-bit cursors. No personal Analyzer records are fetched."""
import csv, json, hashlib, io, os, subprocess, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from worker import query, shuffle, SPACE, USAGE
from global_search import targets
from sync_draw_registrations import register
ROOT=Path(__file__).resolve().parent
JST=timezone(timedelta(hours=9))

def read_feed():
    # This file is written by the authorized Analyzer synchronization task.
    # No access token or personal account information enters the repository.
    data=json.loads((ROOT/'data/analyzer_results.json').read_text(encoding='utf-8'))
    rows={}
    for row in data['loto6']:
        rid=int(row['round']); date=datetime.strptime(row['date'],'%Y-%m-%d').date()
        nums=list(map(int,row['main']+row['bonus']))
        if rid<1 or date>datetime.now(JST).date() or len(nums)!=7 or len(set(nums))!=7 or not all(1<=n<=43 for n in nums): raise ValueError('Invalid Analyzer result')
        value=(date,sorted(nums[:6]),[nums[6]])
        if rid in rows and rows[rid]!=value: raise ValueError('Conflicting Analyzer result')
        rows[rid]=value
    if not rows or set(rows)!=set(range(min(rows),max(rows)+1)): raise ValueError('Missing rounds in Analyzer history')
    return rows

def baseline():
    with (ROOT/'data/loto6.csv').open(encoding='utf-8-sig') as f:
        return {int(r['round']):(datetime.strptime(r['date'].replace('-','/'),'%Y/%m/%d').date(),sorted(int(r[f'n{i}']) for i in range(1,7)),[int(r['bonus1'])]) for r in csv.DictReader(f)}

def merge_feed():
    old=baseline(); rows=read_feed()
    for rid,value in old.items():
        if rid in rows and rows[rid]!=value: raise ValueError(f'Baseline conflict: {rid}')
    merged={**old,**rows}
    if set(merged)!=set(range(1,max(merged)+1)): raise ValueError('Incomplete history')
    return old,merged

def export_history():
    old,rows=merge_feed()
    with (ROOT/'data/loto6.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f); w.writerow(['round','date',*[f'n{i}' for i in range(1,7)],'bonus1'])
        for rid,(date,main,bonus) in sorted(rows.items()): w.writerow([rid,date.isoformat(),*main,*bonus])
    return rows

def scan():
    old,rows=merge_feed()
    newer={r:v for r,v in rows.items() if r not in old}
    register(6,{r:(v[1],v[2]) for r,v in newer.items()}) if newer else None
    query("""CREATE TABLE IF NOT EXISTS incremental_seed_progress(
        round INTEGER PRIMARY KEY, signature TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
        count INTEGER NOT NULL DEFAULT 0, sum_seed INTEGER NOT NULL DEFAULT 0,
        min_seed INTEGER, max_seed INTEGER, bonus_count INTEGER NOT NULL DEFAULT 0)""")
    for rid,(_,main,bonus) in newer.items():
        signature=json.dumps([main,bonus],separators=(',',':'))
        query('INSERT OR IGNORE INTO incremental_seed_progress(round,signature) VALUES(?,?)',[rid,signature])
    deadline=time.monotonic()+75
    while newer and time.monotonic()<deadline-8 and USAGE['read']<50000 and USAGE['written']<1500:
        states=query('SELECT * FROM incremental_seed_progress ORDER BY cursor,round')
        pending=[s for s in states if s['round'] in newer and s['cursor']<SPACE]
        if not pending: break
        # Fair scheduling: each new round starts from zero; completed rounds never restart.
        start=pending[0]['cursor']; batch=min(1000000,SPACE-start)
        group=[s for s in pending if s['cursor']==start]
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'targets.tsv'
            target.write_text(''.join(f"6\t{s['round']}\t{','.join(map(str,newer[s['round']][1]))}\t{newer[s['round']][2][0]}\n" for s in group))
            out=subprocess.run([str(ROOT/'global_scan'),str(start),str(batch),str(target),'main'],capture_output=True,text=True,check=True,timeout=45,env={'PATH':os.environ.get('PATH','')})
        hits={s['round']:[] for s in group}
        for line in out.stdout.splitlines():
            game,rid,seed,b=map(int,line.split('\t'))
            seq=shuffle(43,seed)
            if game!=6 or rid not in hits or not start<=seed<start+batch or sorted(seq[:6])!=newer[rid][1] or b!=int(seq[6]==newer[rid][2][0]): raise ValueError('Scanner mismatch')
            hits[rid].append((seed,b))
        for s in group:
            rid=s['round']; values=hits[rid]; sig=json.dumps([newer[rid][1],newer[rid][2]],separators=(',',':'))
            if s['signature']!=sig: raise ValueError('Stored round conflict')
            seeds=[x[0] for x in values]
            for seed,b in values:
                if b: query('INSERT OR IGNORE INTO global_exact_matches(game,round,seed) VALUES(6,?,?)',[str(rid),seed])
            mn=min([x for x in [s['min_seed'],*seeds] if x is not None],default=None)
            mx=max([x for x in [s['max_seed'],*seeds] if x is not None],default=None)
            result=query('UPDATE incremental_seed_progress SET cursor=?,count=count+?,sum_seed=sum_seed+?,min_seed=?,max_seed=?,bonus_count=bonus_count+? WHERE round=? AND cursor=? RETURNING cursor',[start+batch,len(seeds),sum(seeds),mn,mx,sum(x[1] for x in values),rid,start])
            if not result: raise RuntimeError('Concurrent checkpoint')
    # Use main-only completed baseline (which also tracks bonus matches).
    state=query('SELECT cursor,target_hash,stats FROM main_progress WHERE id=1')
    _,digest,_=targets()
    progress={s['round']:s for s in query('SELECT * FROM incremental_seed_progress') if s['round'] in newer}
    latest=max(rows)
    if not state or state[0]['cursor']!=SPACE or state[0]['target_hash']!=digest or any(r not in progress or progress[r]['cursor']!=SPACE for r in newer):
        print(f'Latest registered LOTO6 {latest}; baseline and incremental exploration not yet complete')
        return
    hist={int(k.split(':')[1]):v for k,v in json.loads(state[0]['stats']).items() if k.startswith('6:')}
    hist.update(progress)
    forecast(rows,hist)

def forecast(rows,hist):
    latest=max(rows); target=latest+1
    path=ROOT/'predictions'/f'loto6_{target}.json'
    # Protect every prior forecast, including names with different suffixes.
    if list(path.parent.glob(f'loto6_{target}*.json')): return
    day=rows[latest][0]+timedelta(days=1)
    while day.weekday() not in (0,3): day+=timedelta(days=1)
    now=datetime.now(JST)
    cutoff=datetime.combine(day,datetime.min.time(),JST)+timedelta(hours=18,minutes=30)
    if now>=cutoff: return
    recent=[int(v['sum_seed'])//int(v['count']) for r,v in sorted(hist.items()) if r<=latest and v['count']][-32:]
    if len(recent)<3: return
    delta=int(median([b-a for a,b in zip(recent,recent[1:])]))
    raw=[('last_mean',recent[-1]),('median_delta',recent[-1]+delta),('recent_median',int(median(recent))),('mean_8',sum(recent[-8:])//len(recent[-8:])),('hash_control',int.from_bytes(hashlib.sha256(json.dumps([latest,recent]).encode()).digest()[:4],'big'))]
    candidates=[]; seen=set()
    for method,seed in raw:
        seed%=SPACE
        while tuple(sorted(shuffle(43,seed)[:6])) in seen: seed=(seed+1)%SPACE
        seq=shuffle(43,seed); main=sorted(seq[:6]); seen.add(tuple(main))
        candidates.append(dict(method=method,seed=seed,numbers=main,bonus=seq[6]))
    payload=dict(lottery='LOTO6',round=target,draw_date_jst=day.isoformat(),trained_through=latest,created_at=now.isoformat(),model='incremental-seed-v1',candidates=candidates)
    path.parent.mkdir(exist_ok=True)
    with path.open('x',encoding='utf-8') as f: json.dump(payload,f,ensure_ascii=False,indent=2)
    print(f'Frozen research candidates for round {target}')

if __name__=='__main__':
    import sys
    if '--export' in sys.argv: export_history()
    else: scan()
