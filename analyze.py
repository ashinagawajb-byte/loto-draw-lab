"""Exploratory descriptive seed-series report; not evidence of lottery predictability."""
import json
import math
import random
from worker import query

def correlation(x, y):
    if len(x) < 3: return None
    mx = sum(x) / len(x); my = sum(y) / len(y)
    a = sum((u - mx) * (v - my) for u, v in zip(x, y))
    b = sum((u - mx) ** 2 for u in x) * sum((v - my) ** 2 for v in y)
    return a / math.sqrt(b) if b > 0 else None

def main():
    for game in (6,7):
        rows = query("SELECT round,best FROM jobs WHERE game=? AND scanned>=seed_limit AND best!=? ORDER BY CAST(round AS INTEGER)",[game,'[]'])
        series=[]
        for row in rows:
            candidates=json.loads(row['best'])
            if candidates:series.append((str(row['round']),int(candidates[0]['seed'])))
        seeds=[x[1] for x in series]
        if len(seeds)<5:
            print(f'LOTO{game}: insufficient complete rounds ({len(seeds)})');continue
        observed=correlation(seeds[:-1],seeds[1:])
        rng=random.Random(20261122+game);extreme=0
        for _ in range(499):
            shuffled=seeds[:];rng.shuffle(shuffled)
            value=correlation(shuffled[:-1],shuffled[1:])
            extreme+=int(value is not None and observed is not None and abs(value)>=abs(observed))
        permutation_p=(extreme+1)/500
        deltas=[b-a for a,b in zip(seeds,seeds[1:])]
        summary={'completed_rounds':len(seeds),'first_round':series[0][0],'last_round':series[-1][0],
                 'lag1_r':observed,'permutation_p_exploratory':permutation_p,
                 'mean_seed_delta':sum(deltas)/len(deltas),
                 'warning':'Retrospectively selected virtual PRNG seeds are not real lottery machine seeds; this is descriptive, not predictive.'}
        query("INSERT INTO seed_analysis(game,summary,updated_at) VALUES(?,?,datetime('now')) ON CONFLICT(game) DO UPDATE SET summary=excluded.summary,updated_at=excluded.updated_at",
              [game,json.dumps(summary,ensure_ascii=False)])
        print('LOTO',game,json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
