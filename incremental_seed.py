"""Read only the sanitized result snapshot exported by the owner-private Analyzer.
Keep independent cursors for post-baseline draws. Forecasts are immutable,
prospective virtual-PRNG research records, not actual-machine state."""
import csv,json,hashlib,os,subprocess,tempfile,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from statistics import median
from worker import query,shuffle,SPACE,USAGE,D1DailyQuotaExceeded
from global_search import targets
from sync_draw_registrations import register
ROOT=Path(__file__).resolve().parent
JST=timezone(timedelta(hours=9))
GAMES=(6,7)

def parameters(game):
    return (43,1) if game==6 else (37,2)

def read_feed(game):
    data=json.loads((ROOT/'data/analyzer_results.json').read_text(encoding='utf-8'))
    limit,b=parameters(game); rows={}
    for row in data['loto'+str(game)]:
        rid=int(row['round']); date=datetime.strptime(row['date'],'%Y-%m-%d').date()
        main=list(map(int,row['main'])); bonus=list(map(int,row['bonus'])); nums=main+bonus
        if rid<1 or date>datetime.now(JST).date() or len(main)!=game or len(bonus)!=b or len(set(nums))!=game+b or not all(1<=n<=limit for n in nums): raise ValueError('Invalid Analyzer result')
        value=(date,sorted(main),sorted(bonus))
        if rid in rows and rows[rid]!=value: raise ValueError('Conflicting Analyzer result')
        rows[rid]=value
    if not rows or set(rows)!=set(range(min(rows),max(rows)+1)): raise ValueError('Missing rounds in Analyzer history')
    return rows

def baseline(game):
    _,b=parameters(game)
    with (ROOT/'data'/f'loto{game}.csv').open(encoding='utf-8-sig') as f:
        return {int(r['round']):(datetime.strptime(r['date'].replace('-','/'),'%Y/%m/%d').date(),sorted(int(r[f'n{i}']) for i in range(1,game+1)),sorted(int(r[f'bonus{i}']) for i in range(1,b+1))) for r in csv.DictReader(f)}

def merge_feed(game):
    old=baseline(game); rows=read_feed(game)
    for rid,value in old.items():
        if rid in rows and rows[rid]!=value: raise ValueError(f'Baseline conflict: LOTO{game} {rid}')
    merged={**old,**rows}
    if set(merged)!=set(range(1,max(merged)+1)): raise ValueError('Incomplete history')
    return old,merged

def export_history():
    for game in GAMES:
        _,rows=merge_feed(game); _,b=parameters(game)
        with (ROOT/'data'/f'loto{game}.csv').open('w',encoding='utf-8',newline='') as f:
            w=csv.writer(f); w.writerow(['round','date',*[f'n{i}' for i in range(1,game+1)],*[f'bonus{i}' for i in range(1,b+1)]])
            for rid,(date,main,bonus) in sorted(rows.items()): w.writerow([rid,date.isoformat(),*main,*bonus])
        print(f'Analyzer LOTO{game} history through {max(rows)}')

def scan():
    all_rows={}; newer={}
    for game in GAMES:
        old,rows=merge_feed(game); all_rows[game]=rows
        added={r:v for r,v in rows.items() if r not in old}
        if added: register(game,{r:(v[1],v[2]) for r,v in added.items()})
        newer.update({(game,r):v for r,v in added.items()})
    query("""CREATE TABLE IF NOT EXISTS analyzer_round_scan(
        game INTEGER NOT NULL, round INTEGER NOT NULL, signature TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
        count INTEGER NOT NULL DEFAULT 0, sum_seed INTEGER NOT NULL DEFAULT 0,
        min_seed INTEGER, max_seed INTEGER, bonus_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(game,round))""")
    def signature(v): return json.dumps([v[1],v[2]],separators=(',',':'))
    for (game,rid),v in newer.items():
        query('INSERT OR IGNORE INTO analyzer_round_scan(game,round,signature) VALUES(?,?,?)',[game,rid,signature(v)])
    deadline=time.monotonic()+360
    def read_states():
        states=query('SELECT * FROM analyzer_round_scan ORDER BY cursor,game,round')
        for s in states:
            key=(s['game'],s['round'])
            if key not in newer or s['signature']!=signature(newer[key]): raise ValueError('Analyzer snapshot removed or changed a registered result')
        return states
    while newer and time.monotonic()<deadline-20 and USAGE['read']<50000 and USAGE['written']<1500:
        pending=[s for s in read_states() if s['cursor']<SPACE]
        if not pending: break
        start=pending[0]['cursor']; batch=min(12000000,SPACE-start)
        group=[s for s in pending if s['cursor']==start]
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'targets.tsv'
            target.write_text(''.join(f"{g}\t{r}\t{','.join(map(str,newer[g,r][1]))}\t{','.join(map(str,newer[g,r][2]))}\n" for g,r in [(s['game'],s['round']) for s in group]))
            out=subprocess.run([str(ROOT/'global_scan'),str(start),str(batch),str(target),'main'],capture_output=True,text=True,check=True,timeout=45,env={'PATH':os.environ.get('PATH','')})
        hits={(s['game'],s['round']):set() for s in group}
        for line in out.stdout.splitlines():
            game,rid,seed,b=map(int,line.split('\t'));key=(game,rid);limit,bc=parameters(game)
            seq=shuffle(limit,seed)
            if key not in hits or not start<=seed<start+batch or b not in (0,1) or sorted(seq[:game])!=newer[key][1] or b!=int(sorted(seq[game:game+bc])==newer[key][2]) or (seed,b) in hits[key]: raise ValueError('Scanner mismatch')
            hits[key].add((seed,b))
        for s in group:
            game,rid=s['game'],s['round']; values=hits[game,rid]; seeds=[x[0] for x in values]
            for seed,b in values:
                if b: query('INSERT OR IGNORE INTO global_exact_matches(game,round,seed) VALUES(?,?,?)',[game,str(rid),seed])
            mn=min([x for x in [s['min_seed'],*seeds] if x is not None],default=None)
            mx=max([x for x in [s['max_seed'],*seeds] if x is not None],default=None)
            result=query('UPDATE analyzer_round_scan SET cursor=?,count=count+?,sum_seed=sum_seed+?,min_seed=?,max_seed=?,bonus_count=bonus_count+? WHERE game=? AND round=? AND cursor=? RETURNING cursor',[start+batch,len(seeds),sum(seeds),mn,mx,sum(x[1] for x in values),game,rid,start])
            if not result: raise RuntimeError('Concurrent checkpoint')
            print(f'Analyzer LOTO{game} round {rid}: {start+batch:,}/{SPACE:,}')
    state=query('SELECT cursor,target_hash,stats FROM main_progress WHERE id=1')
    _,digest,_=targets()
    progress={(s['game'],s['round']):s for s in read_states()}
    for game,rows in all_rows.items():
        latest=max(rows)
        if not state or state[0]['cursor']!=SPACE or state[0]['target_hash']!=digest or any(key not in progress or progress[key]['cursor']!=SPACE for key in newer if key[0]==game):
            print(f'Latest registered LOTO{game} {latest}; baseline and incremental exploration not yet complete')
            continue
        hist={int(k.split(':')[1]):v for k,v in json.loads(state[0]['stats']).items() if k.startswith(f'{game}:')}
        hist.update({r:s for (g,r),s in progress.items() if g==game})
        forecast(game,rows,hist)

def forecast(game,rows,hist):
    latest=max(rows); target=latest+1;limit,b=parameters(game)
    path=ROOT/'predictions'/f'loto{game}_{target}.json'
    if list(path.parent.glob(f'loto{game}_{target}.json')) or list(path.parent.glob(f'loto{game}_{target}_*.json')): return
    day=rows[latest][0]+timedelta(days=1)
    while day.weekday() not in ((0,3) if game==6 else (4,)): day+=timedelta(days=1)
    now=datetime.now(JST)
    cutoff=datetime.combine(day,datetime.min.time(),JST)+timedelta(hours=18,minutes=30)
    if now>=cutoff: return
    recent=[int(v['sum_seed'])//int(v['count']) for r,v in sorted(hist.items()) if r<=latest and v['count']][-32:]
    if len(recent)<3: return
    delta=int(median([b-a for a,b in zip(recent,recent[1:])]))
    raw=[('last_mean',recent[-1]),('median_delta',recent[-1]+delta),('recent_median',int(median(recent))),('mean_8',sum(recent[-8:])//len(recent[-8:])),('hash_control',int.from_bytes(hashlib.sha256(json.dumps([game,latest,recent]).encode()).digest()[:4],'big'))]
    candidates=[]; seen=set()
    for method,seed in raw:
        seed%=SPACE
        while tuple(sorted(shuffle(limit,seed)[:game])) in seen: seed=(seed+1)%SPACE
        seq=shuffle(limit,seed); main=sorted(seq[:game]); seen.add(tuple(main))
        candidates.append(dict(method=method,seed=seed,numbers=main,bonus=seq[game] if game==6 else sorted(seq[game:game+b])))
    payload=dict(lottery=f'LOTO{game}',round=target,draw_date_jst=day.isoformat(),trained_through=latest,created_at=now.isoformat(),model='incremental-seed-v1',candidates=candidates)
    path.parent.mkdir(exist_ok=True)
    with path.open('x',encoding='utf-8') as f: json.dump(payload,f,ensure_ascii=False,indent=2)
    print(f'Frozen LOTO{game} research candidates for round {target}')

if __name__=='__main__':
    import sys
    if '--export' in sys.argv: export_history()
    else:
        try: scan()
        except D1DailyQuotaExceeded: print('::warning::D1 daily quota reached; incremental checkpoints preserved')
