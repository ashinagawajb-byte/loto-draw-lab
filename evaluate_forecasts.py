"""Read-only scoring of pre-draw virtual seed forecasts against recorded draws.

A forecast for round R is scored only if the stored CSV already contains R.
No generated or post hoc virtual seeds are accepted as predictions.
"""
import csv
import json
from pathlib import Path
from worker import shuffle

ROOT=Path(__file__).resolve().parent

def score_predictions():
    results=[]
    for path in sorted((ROOT/'predictions').glob('loto6_*.json')):
        with path.open(encoding='utf-8') as file:
            forecast=json.load(file)
        game=int(str(forecast['lottery']).replace('LOTO',''))
        if game!=6:continue
        round_id=str(int(forecast['round']))
        source=ROOT/'data'/'loto6.csv'
        with source.open(encoding='utf-8-sig',newline='') as file:
            actual=next((r for r in csv.DictReader(file) if str(int(r['round']))==round_id),None)
        if not actual:continue
        target={int(actual[f'n{i}']) for i in range(1,7)}
        bonus=int(actual['bonus1'])
        candidates=[]
        for item in forecast['candidates']:
            seed=int(item['seed'])
            seq=shuffle(43,seed)
            predicted=set(seq[:6])
            candidates.append({'method':item['method'],'seed':seed,
                               'predicted_main':sorted(predicted),
                               'main_hits':len(predicted&target),
                               'bonus_hit':int(seq[6]==bonus)})
        results.append({'round':int(round_id),'date':forecast['draw_date_jst'],
                        'actual_main':sorted(target),'actual_bonus':bonus,
                        'candidates':candidates,'expected_random_main_hits':36/43,
                        'note':'This records pre-draw predictions; more rounds are required to assess predictive skill.'})
    return results

def main():
    import sys
    json.dump(score_predictions(),sys.stdout,ensure_ascii=False,indent=2)
    print()

if __name__=='__main__':main()
