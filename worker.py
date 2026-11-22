"""Bounded, resumable LOTO seed search using Cloudflare D1 HTTP API."""
import os,json,time,urllib.request
MASK=0xffffffff
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
    with urllib.request.urlopen(req,timeout=30) as r: result=json.load(r)
    if not result.get('success') or any(not x.get('success',True) for x in result.get('result',[])):
        raise RuntimeError('D1 query failed: '+str(result.get('errors') or result.get('result'))[:500])
    return result['result'][0].get('results',[])

def run():
    seconds=min(240,max(10,int(os.getenv('RUN_SECONDS','180'))))
    batch=min(2000,max(1,int(os.getenv('BATCH_SIZE','500'))))
    deadline=time.monotonic()+seconds
    count=0
    while time.monotonic()<deadline-3:
        rows=query('SELECT j.*,d.main,d.bonus FROM jobs j JOIN draws d ON d.game=j.game AND d.round=j.round WHERE j.scanned<j.seed_limit ORDER BY j.game,CAST(j.round AS INTEGER) LIMIT 1')
        if not rows: print('All configured jobs complete');break
        r=rows[0];game=int(r['game']);k,b,n=(6,1,43) if game==6 else (7,2,37)
        main=set(json.loads(r['main']));bonus=set(json.loads(r['bonus']));top=json.loads(r['best']);exact=int(r['exact_count'])
        size=min(batch,int(r['seed_limit'])-int(r['scanned']))
        for j in range(size):
            seed=int(r['seed_start'])+int(r['scanned'])+j
            a=shuffle(n,seed);hits=len(main.intersection(a[:k]));bhits=len(bonus.intersection(a[k:k+b]));match=hits==k and (not bonus or bhits==b)
            exact+=int(match)
            item={'seed':seed,'hit':hits,'bonusHit':bhits,'exact':match}
            if len(top)<5 or (int(match),hits,bhits,-seed)>(int(top[-1]['exact']),top[-1]['hit'],top[-1]['bonusHit'],-top[-1]['seed']):
                top.append(item);top.sort(key=lambda x:(-int(x['exact']),-x['hit'],-x['bonusHit'],x['seed']));top=top[:5]
        updated=query("UPDATE jobs SET scanned=?,best=?,exact_count=?,updated_at=datetime('now') WHERE game=? AND round=? AND scanned=? RETURNING scanned", [int(r['scanned'])+size,json.dumps(top),exact,game,r['round'],int(r['scanned'])])
        if not updated:raise RuntimeError('Concurrent update detected; retry on next scheduled run')
        count+=size
    print('Scanned',count,'seeds this run')
if __name__=='__main__':run()
