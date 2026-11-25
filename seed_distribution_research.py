"""Independent sampled virtual-seed research; never writes production forecasts or D1."""
import collections, hashlib, json, math, random, statistics, subprocess, tempfile
from pathlib import Path
from datetime import datetime, timezone
from incremental_seed import merge_feed, parameters
from worker import shuffle
ROOT=Path(__file__).resolve().parent
SPACE=2**32
WIDTH=2**24
STRIDE=2**18
MODELS=('set_density','transition','cycle','bits','combined','mean_median','uniform')

def labels(rows):
    data=json.loads((ROOT/'research/set_labels_loto6.json').read_text())
    return {int(k):v['set'] for k,v in data.items() if int(k) in rows and v['date']==rows[int(k)][0].isoformat() and v['main']==rows[int(k)][1] and v['set'] in 'ABCDEFGHIJ'}

def scan(rows,phase):
    hits={key:[] for key in rows}
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'targets.tsv'
        path.write_text(''.join(f"{g}\t{r}\t{','.join(map(str,v[1]))}\t{','.join(map(str,v[2]))}\n" for (g,r),v in sorted(rows.items())))
        for high in range(256):
            start=high*WIDTH+phase*STRIDE
            result=subprocess.run([str(ROOT/'global_scan'),str(start),str(STRIDE),str(path),'main'],capture_output=True,text=True,check=True,timeout=45)
            for line in result.stdout.splitlines():
                g,r,s,b=map(int,line.split('\t'))
                n,bc=parameters(g); seq=shuffle(n,s)
                assert start<=s<start+STRIDE and sorted(seq[:g])==rows[g,r][1] and b==int(sorted(seq[g:g+bc])==rows[g,r][2])
                hits[g,r].append((s,b))
    return hits

def hist(seeds):
    c=[0]*256
    for s,_ in seeds:c[s>>24]+=1
    return [(x+.5)/(len(seeds)+128) for x in c]
def mix(distributions):
    return [sum(x[i] for x in distributions)/len(distributions) for i in range(256)] if distributions else [1/256]*256
def bit_rates(seeds):
    return [(sum((s>>i)&1 for s,_ in seeds)+2)/(len(seeds)+4) for i in range(32)]
def expected_set(previous,transitions,counts):
    options='ABCDEFGHIJ'; c=transitions.get(previous,{})
    return max(options,key=lambda s:(c.get(s,0)+counts.get(s,0)/max(1,sum(counts.values())),s)) if counts else None
def choose(game,round_id,history,sets,phase):
    rng=random.Random(int.from_bytes(hashlib.sha256(f'{game}/{round_id}/{phase}/v1'.encode()).digest()[:8],'big'))
    base=[v for _,v in history[-32:]]
    prev=history[-1][0] if history else None
    # Actual target set is never used. Predict from previous observed set and prior transition counts.
    counts=collections.Counter(sets.get(r) for r,_ in history if sets.get(r))
    transitions={}
    for (a,_),(b,_) in zip(history,history[1:]):
        if b==a+1 and a in sets and b in sets:transitions.setdefault(sets[a],collections.Counter())[sets[b]]+=1
    guessed=expected_set(sets.get(prev),transitions,counts)
    set_dist=mix([hist(v) for r,v in history[-500:] if guessed and sets.get(r)==guessed])
    # Compare nearest prior distributions to the latest one; use their observed successors only.
    last=hist(base[-1]) if base else [1/256]*256
    pairs=[]
    for (r,a),(nr,b) in zip(history[-129:-1],history[-128:]):
        if nr==r+1 and a and b:
            dist=sum(abs(x-y) for x,y in zip(last,hist(a)))
            pairs.append((dist,r,hist(b)))
    trans=mix([p[2] for p in sorted(pairs,key=lambda x:(x[0],x[1]))[:12]])
    lookup=dict(history); cyc=mix([hist(lookup[round_id-lag]) for lag in (4,8,16,32) if round_id-lag in lookup])
    bits=bit_rates([x for v in base for x in v])
    combined=mix([set_dist,trans,cyc])
    means=[sum(s for s,_ in v)//len(v) for v in base if v]
    delta=int(statistics.median([b-a for a,b in zip(means,means[1:])])) if len(means)>1 else 0
    baseline=[means[-1],means[-1]+delta,int(statistics.median(means)),int(statistics.mean(means[-8:]))] if means else []
    result={}
    for method in MODELS:
        # Same deterministic random draw budget (five distinct tickets per model).
        chosen=[]; seen=set()
        while len(chosen)<5:
            if method=='bits':seed=sum((rng.random()<p)<<i for i,p in enumerate(bits))
            elif method=='mean_median' and len(chosen)<len(baseline):seed=(baseline[len(chosen)]+len(seen)*0)%SPACE
            elif method in ('set_density','transition','cycle','combined'):
                p={'set_density':set_dist,'transition':trans,'cycle':cyc,'combined':combined}[method]
                seed=rng.choices(range(256),p,k=1)[0]*WIDTH+rng.randrange(WIDTH)
            else:seed=rng.randrange(SPACE)
            n,_=parameters(game); ticket=tuple(sorted(shuffle(n,seed)[:game]))
            if ticket in seen:
                seed=rng.randrange(SPACE);ticket=tuple(sorted(shuffle(n,seed)[:game]))
                if ticket in seen:continue
            seen.add(ticket);chosen.append(ticket)
        result[method]=chosen
    return result,guessed

def evaluate(game,rows,hits,sets,phase):
    rounds=sorted(rows); cut=rounds[int(len(rounds)*.8)]; history=[]; stats={m:[] for m in MODELS}; set_correct=[]
    for r in rounds:
        actual=set(rows[r][1])
        if r>=cut and len(history)>=32:
            predictions,guessed=choose(game,r,history,sets,phase)
            if r in sets and guessed:set_correct.append(guessed==sets[r])
            for method,tickets in predictions.items():
                matches=[len(actual.intersection(t)) for t in tickets]
                stats[method].append((max(matches),len(actual.intersection(set().union(*map(set,tickets)))),int(max(matches)>=3 if game==6 else max(matches)>=4),int(max(matches)>=5)))
        history.append((r,hits.get((game,r),[])))
    out={}
    for m,values in stats.items():
        n=len(values)
        if not n:continue
        diffs=[a[2]-b[2] for a,b in zip(values,stats['uniform'])]
        diff=statistics.mean(diffs); se=statistics.stdev(diffs)/math.sqrt(n) if n>1 else 0
        out[m]={'n':n,'mean_max_hits':round(statistics.mean(v[0] for v in values),5),'mean_coverage':round(statistics.mean(v[1] for v in values),5),'threshold_rate':round(statistics.mean(v[2] for v in values),5),'at_least_5_rate':round(statistics.mean(v[3] for v in values),5),'paired_delta_vs_uniform':round(diff,5),'descriptive_95_interval':[round(diff-1.96*se,5),round(diff+1.96*se,5)]}
    return {'holdout_from':cut,'holdout_through':rounds[-1],'set_accuracy':sum(set_correct)/len(set_correct) if set_correct else None,'set_evaluated':len(set_correct),'models':out}

def describe(rows,hits,sets):
    groups={}
    for r,label in sets.items():
        if (6,r) not in rows:continue
        groups.setdefault(label,[]).extend(hits[6,r])
    return {label:{'rounds':sum(s==label for s in sets.values()),'matches':len(vals),'bonus_matches':sum(b for _,b in vals),'density_256':hist(vals),'bit_one_rate_32':bit_rates(vals),'hex_digit_counts':[[sum(((seed>>(4*i))&15)==v for seed,_ in vals) for v in range(16)] for i in range(8)],'median_gap_within_round':statistics.median([b-a for r,s in sets.items() if s==label for a,b in zip([x[0] for x in hits[6,r]][:-1],[x[0] for x in hits[6,r]][1:])]) if sum(len(hits[6,r])>1 for r,s in sets.items() if s==label) else None} for label,vals in groups.items()}

def main():
    all_rows={g:merge_feed(g)[1] for g in (6,7)}
    rows={(g,r):v for g,rs in all_rows.items() for r,v in rs.items()}
    sets=labels(all_rows[6]); folder=ROOT/'research'/'seed_distribution';folder.mkdir(parents=True,exist_ok=True)
    fingerprint=hashlib.sha256(repr(sorted(rows.items())).encode()).hexdigest()[:16]
    done={int(p.stem.split('-')[-1]) for p in folder.glob(f'{fingerprint}-*.json')}
    phase=next((i for i in range(64) if i not in done),None)
    if phase is None:print('All 64 disjoint sampling phases complete');return
    hits=scan(rows,phase)
    report={'version':'seed-distribution-v1','snapshot':fingerprint,'phase':phase,'sampled_seeds':256*STRIDE,'coverage_fraction':1/64,'generated_at':datetime.now(timezone.utc).isoformat(),'set_labels_through':max(sets,default=None),'set_labels_count':len(sets),'set_distributions':describe(rows,hits,sets),'loto6':evaluate(6,all_rows[6],hits,sets,phase),'loto7':evaluate(7,all_rows[7],hits,{},phase),'note':'Virtual PRNG sample; holdout reused across phases, descriptive only. No production promotion. LOTO7 set labels unavailable. Threshold 3 main hits for LOTO6; 4 for LOTO7, not official prize grades.'}
    report['matches_by_game']={str(g):sum(len(v) for (game,_),v in hits.items() if game==g) for g in (6,7)}
    path=folder/f'{fingerprint}-{phase}.json';path.write_text(json.dumps(report,ensure_ascii=False,separators=(',',':')))
    # Retain all sampled exact main matches in a separate job artifact, no personal information.
    import gzip
    with gzip.open(ROOT/'seed_research_matches.tsv.gz','wt') as f:
        for (g,r),vals in sorted(hits.items()):
            for seed,b in vals:f.write(f'{g}\t{r}\t{seed}\t{b}\n')
    print(json.dumps({k:report[k] for k in ('phase','sampled_seeds','matches_by_game','loto6','loto7')},ensure_ascii=False))
if __name__=='__main__':main()
