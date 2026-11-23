"""Compare frozen LOTO DRAW LAB candidates and Site Analyzer five-ticket predictions.

Site predictions are read from an explicitly supplied *pre-draw* CSV file.
No guesses or post-draw reconstructions are accepted. Predictions are scored
on actual outcomes and compared at the same five-ticket/round budget.

CSV columns: round,draw_date,locked_at_jst,model,generation,ticket,n1,n2,n3,n4,n5,n6
One row per ticket, exactly five distinct tickets for each (round,model,generation).
"""
import csv
import json
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path

from evaluate_forecasts import ROOT, score_predictions

ANALYZER_CSV=ROOT/'comparisons'/'analyzer_frozen.csv'
HEADERS=['round','draw_date','locked_at_jst','model','generation','ticket',
         'n1','n2','n3','n4','n5','n6']

def parse_lock(value):
    if not value or 'T' not in value:
        raise ValueError('locked_at_jst requires ISO 8601 with explicit +09:00 offset')
    locked=datetime.fromisoformat(value)
    if locked.utcoffset() is None or locked.utcoffset().total_seconds()!=9*3600:
        raise ValueError('locked_at_jst must explicitly be JST (+09:00)')
    return locked

def load_site_predictions(path=ANALYZER_CSV):
    path=Path(path)
    if not path.is_file():
        return {}, {'state':'awaiting_export','loaded_rounds':0,
                    'note':'Site Analyzer の固定予想CSVは未取得。推定した5口は登録しません。'}
    groups=defaultdict(list)
    with path.open(encoding='utf-8-sig',newline='') as file:
        reader=csv.DictReader(file)
        if reader.fieldnames is None or any(x not in reader.fieldnames for x in HEADERS):
            raise ValueError('Analyzer CSV missing mandatory columns: '+','.join(HEADERS))
        for row in reader:
            round_id=int(row['round'])
            if round_id<1:raise ValueError('invalid round')
            locked=parse_lock(row['locked_at_jst'].strip())
            draw_date=datetime.strptime(row['draw_date'].strip(),'%Y-%m-%d').date()
            if locked.date()!=draw_date:
                raise ValueError('forecast must be frozen on the stated draw day')
            if locked.time()>time(18,30):
                raise ValueError('forecast locked after 18:30 JST protection cutoff')
            model=row['model'].strip()
            generation=row['generation'].strip()
            if not model or not generation:
                raise ValueError('model and generation are required')
            ticket=int(row['ticket'])
            if not 1<=ticket<=5:raise ValueError('ticket id must be 1..5')
            nums=tuple(sorted(int(row[f'n{i}']) for i in range(1,7)))
            if len(set(nums))!=6 or not all(1<=n<=43 for n in nums):
                raise ValueError('ticket numbers must be six unique integers in 1..43')
            groups[(round_id,model,generation)].append((ticket,nums,locked.isoformat(),draw_date.isoformat()))
    result={}
    for (round_id,model,generation),items in groups.items():
        if len(items)!=5 or {x[0] for x in items}!={1,2,3,4,5}:
            raise ValueError(f'round {round_id}: model {model} generation {generation} requires exactly tickets 1..5')
        if len({x[1] for x in items})!=5:
            raise ValueError('identical ticket repeated within a five-ticket portfolio')
        if len({(x[2],x[3]) for x in items})!=1:
            raise ValueError('inconsistent frozen timestamp/date within same portfolio')
        result.setdefault(round_id,[]).append({
            'source':'Site Analyzer','model':model,'generation':generation,
            'locked_at_jst':items[0][2],
            'tickets':[list(x[1]) for x in sorted(items,key=lambda x:x[0])]})
    return result,{'state':'loaded','loaded_rounds':len(result),
                   'portfolio_count':sum(map(len,result.values()))}

def classification(ticket,main,bonus):
    hits=len(set(ticket)&set(main))
    b=int(bonus in ticket)
    if hits==6:return 1
    if hits==5 and b:return 2
    if hits==5:return 3
    if hits==4:return 4
    if hits==3:return 5
    return 0

def compare():
    site,source_info=load_site_predictions()
    scored=score_predictions()
    by_round={x['round']:x for x in scored}
    # Current LOTO6 history may contain rounds without an existing DRAW LAB pre-draw forecast.
    outcomes={}
    with (ROOT/'data'/'loto6.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            rid=int(r['round'])
            outcomes[rid]=({int(r[f'n{i}']) for i in range(1,7)},int(r['bonus1']))

    result=[]
    for round_id in sorted(set(site)|set(by_round)):
        outcome=outcomes.get(round_id)
        if outcome is None:continue
        main,bonus=outcome
        rows=[]
        for portfolio in site.get(round_id,[]):
            tickets=portfolio['tickets']
            grades=[classification(t,main,bonus) for t in tickets]
            hits=[len(set(t)&main) for t in tickets]
            rows.append({'source':'Site Analyzer','method':portfolio['model'],
                'generation':portfolio['generation'],'ticket_count':5,
                'max_main_hits':max(hits),'main_hits_sum':sum(hits),
                'any_5th_or_better':int(any(g>0 for g in grades)),
                'any_4th_or_better':int(any(0<g<=4 for g in grades)),
                'any_3rd_or_better':int(any(0<g<=3 for g in grades)),
                'best_grade':min((g for g in grades if g),default=0),
                'locked_at_jst':portfolio['locked_at_jst']})
        if round_id in by_round:
            forecast=by_round[round_id]
            # Treat five fixed seed candidates as a five-ticket portfolio, and
            # maintain per-method scores separately. No selected best-of-five
            # hindsight ranking is used as a prediction.
            candidates=forecast['candidates']
            tickets=[c['predicted_main'] for c in candidates]
            if len(tickets)==5 and all(len(t)==6 for t in tickets):
                hits=[len(set(t)&main) for t in tickets]
                grades=[classification(t,main,bonus) for t in tickets]
                rows.append({'source':'LOTO DRAW LAB','method':'fixed_seeds_5',
                    'generation':'pre-draw','ticket_count':5,
                    'max_main_hits':max(hits),'main_hits_sum':sum(hits),
                    'any_5th_or_better':int(any(g>0 for g in grades)),
                    'any_4th_or_better':int(any(0<g<=4 for g in grades)),
                    'any_3rd_or_better':int(any(0<g<=3 for g in grades)),
                    'best_grade':min((g for g in grades if g),default=0)})
        if rows:result.append({'round':round_id,'actual_main':sorted(main),
                               'actual_bonus':bonus,'portfolios':rows})
    complete=[r for r in result if any(x['source']=='Site Analyzer' for x in r['portfolios'])
             and any(x['source']=='LOTO DRAW LAB' for x in r['portfolios'])]
    return {'site_source':source_info,'scored_rounds':result,
            'paired_rounds':len(complete),
            'note':'同じ開催回・同じ5口で比較。固定時刻・モデル世代を保持。実抽せんを予測できる証拠ではありません。'}

if __name__=='__main__':
    print(json.dumps(compare(),ensure_ascii=False,indent=2))
