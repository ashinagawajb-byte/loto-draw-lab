"""Resumable exact-match-only LOTO seed search for the virtual PRNG."""
import os, json, time, urllib.request, urllib.error
MASK=0xffffffff
SPACE=2**32
WINDOW=100000
API='https://api.cloudflare.com/client/v4/accounts/{}/d1/database/{}/query'

def shuffle(n,seed):
    state=seed&MASK
    def rnd():
        nonlocal state
        state=(state+0x6D2B79F5)&MASK
        t=state
        t=((t^(t>>15))*((t|1)&MASK))&MASK
        t=(t^(t+(((t^(t>>7))*((t|61)&MASK))&MASK)))&MASK
        return ((t^(t>>14))&MASK)/4294967296
    a=list(range(1,n+1))
    for i in range(n-1,0,-1):
        j=int(rnd()*(i+1));a[i],a[j]=a[j],a[i]
    return a

def query(sql,params=None):
    url=API.format(os.environ['CF_ACCOUNT_ID'],os.environ['CF_D1_DATABASE_ID'])
    payload=json.dumps({'sql':sql,'params':params or []}).encode()
    req=urllib.request.Request(url,data=payload,headers={'Authorization':'Bearer '+os.environ['CF_API_TOKEN'],'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: result=json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'D1 HTTP {e.code}: '+e.read(400).decode('utf-8','replace')) from None
    if not result.get('success') or any(not x.get('success',True) for x in result.get('result',[])):
        raise RuntimeError('D1 query failed: '+str(result.get('errors') or result.get('result'))[:500])
    return result['result'][0].get('results',[])

def init():
    query("""CREATE TABLE IF NOT EXISTS exact_matches (
        game INTEGER NOT NULL, round TEXT NOT NULL,
        seed INTEGER NOT NULL, detected_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY(game,round,seed))""")
    # Recover exact matches stored among the previous top-5; these are verified
    # independently by the same deterministic shuffle.
    rows=query("SELECT j.game,j.round,j.best,d.main,d.bonus FROM jobs j JOIN draws d USING (game,round) WHERE j.exact_count>0")
    for r in rows:
        game=int(r['game']); k,b,n=(6,1,43) if game==6 else (7,2,37)
        main=set(json.loads(r['main']));bonus=set(json.loads(r['bonus']))
        for item in json.loads(r['best']):
            seed=int(item['seed'])
            sequence=shuffle(n,seed)
            if set(sequence[:k])==main and set(sequence[k:k+b])==bonus:
                query("INSERT OR IGNORE INTO exact_matches(game,round,seed) VALUES(?,?,?)",[game,r['round'],seed])
    # Extend all legacy 10k windows; no progress or previously found matches reset.
    query("UPDATE jobs SET seed_limit=? WHERE seed_limit<? AND scanned< ?", [WINDOW,WINDOW,SPACE])

def run():
    init()
    seconds=min(240,max(10,int(os.getenv('RUN_SECONDS','90'))))
    batch=min(2000,max(1,int(os.getenv('BATCH_SIZE','500'))))
    deadline=time.monotonic()+seconds
    count=0
    while time.monotonic()<deadline-3:
        # Lowest scanned first ensures all 2860 rounds, both games, receive service.
        rows=query("""SELECT j.*,d.main,d.bonus FROM jobs j
            JOIN draws d ON d.game=j.game AND d.round=j.round
            WHERE j.scanned<j.seed_limit AND j.scanned<? 
            ORDER BY j.scanned,j.game,CAST(j.round AS INTEGER) LIMIT 1""",[SPACE])
        if not rows:
            expanded=query("""UPDATE jobs SET seed_limit=MIN(?,seed_limit+?)
                WHERE scanned>=seed_limit AND seed_limit<? RETURNING round""",
                [SPACE,WINDOW,SPACE])
            if not expanded:
                print('Entire 32-bit seed space has been evaluated for all configured rounds')
                break
            print('Extended seed windows for',len(expanded),'rounds')
            continue
        r=rows[0];game=int(r['game']);k,b,n=(6,1,43) if game==6 else (7,2,37)
        main=set(json.loads(r['main'])); bonus=set(json.loads(r['bonus']))
        exact=int(r['exact_count']); start=int(r['scanned'])
        size=min(batch,int(r['seed_limit'])-start,SPACE-start)
        found=[]
        for j in range(size):
            seed=int(r['seed_start'])+start+j
            a=shuffle(n,seed)
            if set(a[:k])==main and set(a[k:k+b])==bonus:
                found.append(seed)
        # Insert matches first (idempotently). Progress checkpoint follows.
        for seed in found:
            query("INSERT OR IGNORE INTO exact_matches(game,round,seed) VALUES(?,?,?)",
                  [game,r['round'],seed])
        updated=query("""UPDATE jobs SET scanned=?,exact_count=exact_count+?,
            updated_at=datetime('now') WHERE game=? AND round=? AND scanned=? RETURNING scanned""",
            [start+size,len(found),game,r['round'],start])
        if not updated: raise RuntimeError('Concurrent update detected; retry next run')
        count+=size
        if found:print(f'LOTO{game} round {r["round"]}: found {len(found)} exact matches')
    print('Scanned',count,'seeds this run (exact-match-only)')
if __name__=='__main__':run()
