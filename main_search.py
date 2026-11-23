"""Compact main-number-only scan, independent of full-match cursor.

Store one checkpoint row with per-round aggregate statistics. Do NOT save
all matching seeds or overwrite legacy or full-exact tables.
"""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from global_search import ROOT, targets
from worker import SPACE, USAGE, query, shuffle

def update_statistics(stats, hits, valid):
    """Return new dictionary, preserving previous snapshot on any error."""
    next_stats = {k: v.copy() for k, v in stats.items()}
    for game, round_id, seed, bonus_match in hits:
        key=f'{game}:{round_id}'
        main, bonuses=valid[(game,round_id)]
        nums=shuffle(43 if game==6 else 37,seed)
        b=1 if game==6 else 2
        if frozenset(nums[:game])!=main or (int(frozenset(nums[game:game+b])==bonuses)!=bonus_match):
            raise RuntimeError(f'Invalid main-only match {key} seed={seed}')
        item=next_stats.setdefault(key,{'count':0,'bonus_count':0,'min_seed':seed,'max_seed':seed,'sum_seed':0})
        item['count']+=1
        item['bonus_count']+=bonus_match
        item['min_seed']=min(item['min_seed'],seed)
        item['max_seed']=max(item['max_seed'],seed)
        item['sum_seed']+=seed
    return next_stats

def initialize(hash_value):
    query("""CREATE TABLE IF NOT EXISTS main_progress (
        id INTEGER PRIMARY KEY CHECK(id=1),
        cursor INTEGER NOT NULL DEFAULT 0,
        target_hash TEXT NOT NULL,
        stats TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    query("INSERT OR IGNORE INTO main_progress(id,cursor,target_hash) VALUES(1,0,?)",[hash_value])
    rows=query("SELECT cursor,target_hash,stats FROM main_progress WHERE id=1")
    if len(rows)!=1:raise RuntimeError('Main checkpoint missing')
    old=rows[0]
    cursor=int(old['cursor'])
    if old['target_hash'] != hash_value:
        # This is a new version of the historical target set. Archive the
        # aggregate snapshot before re-scanning; legacy/full results remain.
        query("""CREATE TABLE IF NOT EXISTS main_progress_archive(
            target_hash TEXT PRIMARY KEY,
            cursor INTEGER NOT NULL,
            stats TEXT NOT NULL,
            archived_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        query("""INSERT OR IGNORE INTO main_progress_archive(target_hash,cursor,stats)
            SELECT target_hash,cursor,stats FROM main_progress WHERE id=1""")
        updated=query("""UPDATE main_progress SET cursor=0,target_hash=?,stats='{}',
            updated_at=datetime('now') WHERE id=1 AND cursor=? AND target_hash=? RETURNING cursor""",
            [hash_value,cursor,old['target_hash']])
        if not updated:raise RuntimeError('Concurrent main snapshot update')
        print('Main-only target CSV changed: archived prior aggregate and reset only main cursor')
        return 0,{}
    return cursor,json.loads(old['stats'])

def run():
    text,hash_value,valid=targets()
    cursor,stats=initialize(hash_value)
    native=ROOT/'global_scan'
    if not native.is_file() or not os.access(native,os.X_OK):
        raise RuntimeError('Missing compiled global_scan')
    batch=min(2_000_000,max(1,int(os.getenv('MAIN_BATCH_SIZE','1000000'))))
    deadline=time.monotonic()+min(200,max(5,int(os.getenv('MAIN_RUN_SECONDS','75'))))
    limit_reads=int(os.getenv('D1_RUN_READ_BUDGET','60000'))
    limit_writes=int(os.getenv('D1_RUN_WRITE_BUDGET','2000'))
    processed=0
    matched=0
    began=time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        target_path=Path(tmp)/'targets.tsv'
        target_path.write_text(text,encoding='utf-8')
        while cursor<SPACE and time.monotonic()<deadline-5:
            if USAGE['read']>=limit_reads or USAGE['written']>=limit_writes:
                print('Main-only scan stopped at conservative D1 process quota guard')
                break
            count=min(batch,SPACE-cursor)
            result=subprocess.run(
                [str(native),str(cursor),str(count),str(target_path),'main'],
                capture_output=True,text=True,timeout=45,check=True,
                env={'PATH':os.environ.get('PATH','')})
            hits=[]
            seen=set()
            for line in result.stdout.splitlines():
                parts=line.split('\t')
                if len(parts)!=4:raise RuntimeError('Invalid main-only result format')
                game,round_id,seed,bonus=int(parts[0]),parts[1],int(parts[2]),int(parts[3])
                identity=(game,round_id,seed)
                if identity in seen or (game,round_id) not in valid or not cursor<=seed<cursor+count or bonus not in (0,1):
                    raise RuntimeError('Invalid main-only result value')
                seen.add(identity)
                hits.append((game,round_id,seed,bonus))
            updated=update_statistics(stats,hits,valid)
            # Atomic data AND cursor checkpoint: no partial summary on quota errors.
            result=query("""UPDATE main_progress SET cursor=?,stats=?,
                updated_at=datetime('now')
                WHERE id=1 AND cursor=? AND target_hash=? RETURNING cursor""",
                [cursor+count,json.dumps(updated,separators=(',',':')),cursor,hash_value])
            if not result:raise RuntimeError('Concurrent main progress update')
            stats=updated;cursor+=count;processed+=count;matched+=len(hits)
            print(f'Main-only checkpoint: {cursor:,}/{SPACE:,}; hits this chunk={len(hits)}; rounds with hits={len(stats)}')
    elapsed=max(.001,time.monotonic()-began)
    print(f'Main-only scan: unique seeds processed={processed:,}; recorded matches={matched:,}; speed={processed/elapsed:,.0f}/s')
    print(f'D1 rows read={USAGE["read"]:,}; rows written={USAGE["written"]:,}')

if __name__=='__main__':run()
