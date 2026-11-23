"""Shared 32-bit seed-space traversal for LOTO6 and LOTO7 (no legacy reset).

Each seed is generated once per GAME and matched against all historical draws
in memory by native code. The state cursor describes unique seeds, never the
sum of per-round search attempts. All matches are exact main+bonus matches.
"""
import csv
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import time

from worker import SPACE, USAGE, query, shuffle

ROOT = Path(__file__).resolve().parent

def targets():
    lines = []
    valid = {}
    for game, n, bonus in ((6, 43, 1), (7, 37, 2)):
        path = ROOT / 'data' / f'loto{game}.csv'
        if not path.is_file():
            raise RuntimeError(f'Missing historical file {path}')
        with path.open(encoding='utf-8-sig', newline='') as file:
            for row in csv.DictReader(file):
                round_id = str(int(row['round']))
                main = tuple(int(row[f'n{i}']) for i in range(1, game+1))
                extras = tuple(int(row[f'bonus{i}']) for i in range(1, bonus+1))
                all_values = main + extras
                if len(set(all_values)) != game+bonus or not all(1<=v<=n for v in all_values):
                    raise ValueError(f'Invalid LOTO{game} round {round_id}')
                identity = (game, round_id)
                if identity in valid:
                    raise ValueError(f'Duplicate LOTO{game} round {round_id}')
                valid[identity]=(frozenset(main),frozenset(extras))
                lines.append((game, int(round_id), ','.join(map(str,sorted(main))), ','.join(map(str,sorted(extras)))))
    lines.sort(key=lambda a:(a[0],a[1]))
    text = ''.join(f'{game}\t{round_id}\t{main}\t{bonus}\n' for game,round_id,main,bonus in lines)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return text, digest, valid

def initialize(target_hash):
    query("""CREATE TABLE IF NOT EXISTS global_progress (
        id INTEGER PRIMARY KEY CHECK(id=1),
        cursor INTEGER NOT NULL DEFAULT 0,
        target_hash TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    query("""CREATE TABLE IF NOT EXISTS global_exact_matches (
        game INTEGER NOT NULL, round TEXT NOT NULL, seed INTEGER NOT NULL,
        detected_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY(game,round,seed)
    )""")
    query("""INSERT OR IGNORE INTO global_progress(id,cursor,target_hash)
        VALUES(1,0,?)""",[target_hash])
    state = query("SELECT cursor,target_hash FROM global_progress WHERE id=1")
    if not state:
        raise RuntimeError('Missing global progress checkpoint')
    cursor = int(state[0]['cursor'])
    previous_hash = state[0]['target_hash']
    if previous_hash != target_hash:
        # New historical rounds require replay of earlier seeds; retain every
        # previously found match in global_exact_matches and legacy tables.
        updated = query("""UPDATE global_progress SET cursor=0,target_hash=?,updated_at=datetime('now')
            WHERE id=1 AND cursor=? AND target_hash=? RETURNING cursor""",
            [target_hash,cursor,previous_hash])
        if not updated:
            raise RuntimeError('Another global search changed the target snapshot')
        print('Target history updated: restarting global cursor at zero; preserving all matches')
        cursor=0
    return cursor

def verify_match(game, round_id, seed, valid):
    main, bonuses = valid[(game,round_id)]
    numbers = shuffle(43 if game==6 else 37,seed)
    bonus_count = 1 if game==6 else 2
    if frozenset(numbers[:game]) != main or frozenset(numbers[game:game+bonus_count]) != bonuses:
        raise RuntimeError(f'Native scanner mismatch game {game}, round {round_id}, seed {seed}')

def run():
    target_text, target_hash, valid=targets()
    start = initialize(target_hash)
    native=ROOT/'global_scan'
    if not native.is_file() or not os.access(native,os.X_OK):
        raise RuntimeError('Build global_scan first: g++ -O3 -std=c++17 global_scan.cpp -o global_scan')
    deadline=time.monotonic()+min(240,max(5,int(os.getenv('RUN_SECONDS','90'))))
    max_reads=int(os.getenv('D1_RUN_READ_BUDGET','60000'))
    max_writes=int(os.getenv('D1_RUN_WRITE_BUDGET','2000'))
    # Larger checkpoints amortize D1 API requests, but replay at most one
    # chunk when Cloudflare rejects a checkpoint.
    batch=min(5_000_000,max(1,int(os.getenv('GLOBAL_BATCH_SIZE','1000000'))))
    processed=0
    found=0
    started=time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        target_path=Path(tmp)/'targets.tsv'
        target_path.write_text(target_text,encoding='utf-8')
        while start<SPACE and time.monotonic()<deadline-5:
            if USAGE['read']>=max_reads or USAGE['written']>=max_writes:
                print('Reached conservative process-wide D1 row budget')
                break
            size=min(batch,SPACE-start)
            result=subprocess.run(
                [str(native),str(start),str(size),str(target_path)],
                capture_output=True,text=True,timeout=45,check=True,env={'PATH':os.environ.get('PATH','')})
            hits=[]
            seen=set()
            for line in result.stdout.splitlines():
                parts=line.split('\t')
                if len(parts)!=3:raise RuntimeError('Malformed native global match line')
                game,round_id,seed=int(parts[0]),parts[1],int(parts[2])
                if (game,round_id) not in valid or not start<=seed<start+size:
                    raise RuntimeError('Out-of-range or unknown global match')
                if (game,round_id,seed) in seen:
                    raise RuntimeError('Repeated native match')
                seen.add((game,round_id,seed))
                verify_match(game,round_id,seed,valid)
                hits.append((game,round_id,seed))
            # Matches are inserted idempotently before the checkpoint. If a
            # quota failure occurs, retrying the same batch cannot lose a hit.
            for game,round_id,seed in hits:
                query("""INSERT OR IGNORE INTO global_exact_matches(game,round,seed)
                    VALUES(?,?,?)""",[game,round_id,seed])
            committed=query("""UPDATE global_progress SET cursor=?,updated_at=datetime('now')
                WHERE id=1 AND cursor=? AND target_hash=? RETURNING cursor""",
                [start+size,start,target_hash])
            if not committed:raise RuntimeError('Global progress modified concurrently')
            start+=size
            processed+=size
            found+=len(hits)
            print(f'Global checkpoint: {start:,}/{SPACE:,} unique seeds; matches in chunk {len(hits)}')
    elapsed=max(.001,time.monotonic()-started)
    print(f'Global scanned {processed:,} unique seeds in {elapsed:.2f}s, '
          f'rate {processed/elapsed:,.0f}/s; full-match hits observed {found}')
    print(f'D1 rows read={USAGE["read"]:,}, written={USAGE["written"]:,}; targets={len(valid)}')

if __name__ == '__main__':
    run()
