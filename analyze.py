"""Exploratory lag-one analysis of ONLY verified full-match virtual seeds."""
import json,math,random
from worker import query

def correlation(x,y):
    if len(x)<3:return None
    mx=sum(x)/len(x);my=sum(y)/len(y)
    a=sum((u-mx)*(v-my) for u,v in zip(x,y))
    b=sum((u-mx)**2 for u in x)*sum((v-my)**2 for v in y)
    return a/math.sqrt(b) if b>0 else None

def main():
    for game in (6,7):
        rows=query("""SELECT round,MIN(seed) AS seed FROM exact_matches
            WHERE game=? GROUP BY round ORDER BY CAST(round AS INTEGER)""",[game])
        series=[(str(r['round']),int(r['seed'])) for r in rows]
        seeds=[v for _,v in series]
        if len(seeds)<5:
            print(f'LOTO{game}: only {len(seeds)} rounds have full-match seeds; no series inference')
            query("DELETE FROM seed_analysis WHERE game=?",[game])
            continue
        observed=correlation(seeds[:-1],seeds[1:])
        rng=random.Random(20261122+game)
        extreme=0
        for _ in range(499):
            shuffled=seeds[:];rng.shuffle(shuffled)
            value=correlation(shuffled[:-1],shuffled[1:])
            extreme+=int(value is not None and observed is not None and abs(value)>=abs(observed))
        deltas=[b-a for a,b in zip(seeds,seeds[1:])]
        summary={'completed_rounds':len(series),'matched_rounds':len(series),
                 'first_round':series[0][0],'last_round':series[-1][0],
                 'lag1_r':observed,'permutation_p_exploratory':(extreme+1)/500,
                 'mean_seed_delta':sum(deltas)/len(deltas),
                 'match_definition':'all main and bonus numbers, unordered within each group',
                 'warning':'These are retrospectively fitted virtual PRNG seeds, not physical machine parameters or evidence of prediction.'}
        query("""INSERT INTO seed_analysis(game,summary,updated_at)
                VALUES(?,?,datetime('now')) ON CONFLICT(game) DO
                UPDATE SET summary=excluded.summary,updated_at=excluded.updated_at""",
              [game,json.dumps(summary,ensure_ascii=False)])
        print('LOTO',game,json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
