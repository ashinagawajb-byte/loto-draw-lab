"""Import LOTO draws CSV to D1, preserving existing search progress."""
import csv,io,json,re,sys
from pathlib import Path
from worker import query

def run(path,game):
    raw=Path(path).read_bytes()
    for enc in ('utf-8-sig','cp932'):
        try:txt=raw.decode(enc);break
        except UnicodeDecodeError:continue
    else:raise ValueError('CSV encoding must be UTF-8 or CP932')
    rows=csv.DictReader(io.StringIO(txt));norm=lambda s:re.sub(r'[\s_　]','',s or '').lower()
    cols={norm(c):c for c in rows.fieldnames or []}
    def find(*names):return next((cols[norm(n)] for n in names if norm(n) in cols),None)
    rnd=find('開催回','回号','抽選回','抽せん回','round','drawno')
    k,b,n=(6,1,43) if game==6 else (7,2,37)
    maincols=[find(f'本数字{i}',f'数字{i}',f'n{i}',f'num{i}') for i in range(1,k+1)]
    bonuscols=[find(f'ボーナス{i}',f'ボーナス数字{i}',f'bonus{i}') for i in range(1,b+1)]
    packed=find('本数字','当選数字','main','numbers');bp=find('ボーナス','ボーナス数字','bonus')
    if not rnd or (not all(maincols) and not packed):raise ValueError('Missing round or main-number columns')
    ok=bad=0
    for row in rows:
        try:
            nums=lambda v:[int(x) for x in re.findall(r'\d+',str(v or ''))]
            main=[int(row[c]) for c in maincols] if all(maincols) else nums(row[packed]);bonus=[int(row[c]) for c in bonuscols] if all(bonuscols) else nums(row[bp]) if bp else []
            round_=str(row[rnd]).strip()
            if not round_ or len(main)!=k or len(bonus) not in (0,b) or len(set(main+bonus))!=len(main+bonus) or not all(1<=v<=n for v in main+bonus):raise ValueError('Invalid row')
            query('INSERT OR IGNORE INTO draws(game,round,main,bonus) VALUES(?,?,?,?)',[game,round_,json.dumps(main),json.dumps(bonus)])
            query('INSERT OR IGNORE INTO jobs(game,round,seed_limit) VALUES(?,?,?)',[game,round_,10000]);ok+=1
        except (ValueError,KeyError,TypeError):bad+=1
    print('Imported:',ok,'invalid:',bad)
if __name__=='__main__':run(sys.argv[1],int(sys.argv[2]))
