"""Build a read-only static dashboard from Cloudflare D1 without exposing credentials."""
import json
from pathlib import Path
from worker import query

def get_data():
    summary = query("""
      SELECT game, COUNT(*) rounds, COALESCE(SUM(scanned),0) scanned,
        COALESCE(SUM(seed_limit),0) planned,
        SUM(CASE WHEN exact_count>0 THEN 1 ELSE 0 END) completed,
        COALESCE(SUM(exact_count),0) exact
      FROM jobs GROUP BY game ORDER BY game
    """)
    # Only FULL matches are eligible for display, even when a seed window is incomplete.
    completed = query("""
      SELECT j.game,j.round,j.scanned,j.seed_limit,j.exact_count,MIN(m.seed) AS seed
      FROM exact_matches m JOIN jobs j ON j.game=m.game AND j.round=m.round
      GROUP BY j.game,j.round ORDER BY j.game,CAST(j.round AS INTEGER) DESC LIMIT 800
    """)
    active = query("""
      SELECT game, round, scanned, seed_limit, best
      FROM jobs WHERE scanned > 0 AND scanned < seed_limit
      ORDER BY updated_at DESC LIMIT 10
    """)
    studies = query("SELECT game, summary, updated_at FROM seed_analysis")
    for row in completed:
        row["best"] = [{"seed":int(row["seed"]),"hit":int(row["game"]),"bonusHit":1 if int(row["game"])==6 else 2}]
    for row in active:
        row["best"] = []
    for row in studies:
        row["summary"] = json.loads(row["summary"])
    return {"summary": summary, "completed": completed, "active": active,
            "studies": studies, "note": "シード値は仮想PRNGの値であり、実機の状態ではありません。過去結果に合わせた値から予測力は導けません。"}

HTML = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>LOTO DRAW LAB | シード探索ダッシュボード</title>
<style>
:root{font-family:system-ui,-apple-system,"Noto Sans JP",sans-serif;color:#f5f7fa;background:#0c1422}
*{box-sizing:border-box}body{margin:0;padding:0 16px 40px}main{max-width:1100px;margin:auto}
header{padding:28px 0 16px;border-bottom:1px solid #294059}h1{margin:0;font-size:clamp(22px,4vw,32px)}
h2{font-size:18px;margin:0 0 18px}.muted{color:#a5b5c9}.lead{font-size:14px}
.controls{display:flex;gap:10px;margin:22px 0;flex-wrap:wrap}
button{padding:10px 20px;border:1px solid #52677f;background:#1b2b42;color:#fff;border-radius:9px;cursor:pointer}
button[aria-pressed=true]{background:#e69a24;color:#101825;border-color:#e69a24;font-weight:700}
input{background:#091727;border:1px solid #52677f;color:#fff;border-radius:9px;padding:11px;font-size:16px;max-width:260px}
.seed-form{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.balls{display:flex;flex-wrap:wrap;gap:9px;margin:15px 0}
.ball{display:inline-flex;justify-content:center;align-items:center;width:43px;height:43px;border-radius:50%;background:#f2aa39;color:#161d29;font-weight:800}
.ball.bonus{background:#90b8db}
.small-btn{font-size:12px;padding:6px 9px;margin-left:8px}
#convert-error{color:#ffb5b5}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.panel{border:1px solid #2e4059;background:#132239;border-radius:14px;padding:19px;margin:16px 0}
.metric{font-size:clamp(25px,4vw,36px);font-weight:750;margin:5px 0;font-variant-numeric:tabular-nums}
.progress{height:12px;background:#2a4059;overflow:hidden;border-radius:8px;margin:12px 0}
.progress>div{background:linear-gradient(90deg,#e69a24,#ffcd71);height:100%}
.value{display:flex;justify-content:space-between;gap:10px;align-items:center}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:10px;text-align:left;border-bottom:1px solid #2b4058}
.scroll{overflow:auto}td{font-variant-numeric:tabular-nums;white-space:nowrap}
.chart{width:100%;height:250px;display:block}
footer{font-size:12px;color:#a5b5c9;margin-top:20px;line-height:1.7}
.status{font-weight:700;color:#ffd180}
a{color:#a7d4ff}svg text{font-family:inherit}
</style></head><body><main>
<header><h1>LOTO DRAW LAB <span class="muted">/ 研究ダッシュボード</span></h1>
<p class="muted lead">GitHub Actions × Cloudflare D1｜読み取り専用スナップショット</p>
<p id="stamp" class="muted lead"></p></header>
<div class="controls"><button type="button" data-game="6" aria-pressed="true">ロト6</button><button type="button" data-game="7" aria-pressed="false">ロト7</button></div>
<section class="grid" aria-label="進捗"><div class="panel"><div class="muted">登録開催回</div><div class="metric" id="rounds">—</div></div>
<div class="panel"><div class="muted">探索済みシード</div><div class="metric" id="scanned">—</div></div>
<div class="panel"><div class="muted">完全一致した開催回</div><div class="metric" id="finished">—</div></div>
<div class="panel"><div class="muted">現在の探索範囲に対する進捗</div><div class="metric" id="percent">—</div></div></section>
<section class="panel"><h2>探索範囲の進捗</h2><div class="progress"><div id="bar" style="width:0%"></div></div><p class="muted" id="plan"></p></section>
<section class="panel"><h2>シード番号から抽選数字を再現</h2>
<p class="muted lead">上のロト6／ロト7を選択し、0〜4,294,967,295の整数シードを入力。クラウド探索と同じ仮想乱数アルゴリズムで計算します。</p>
<form id="seed-form" class="seed-form"><label for="seed-input">シード</label><input id="seed-input" inputmode="numeric" type="text" placeholder="例：12345" autocomplete="off" required><button type="submit">数字へ変換</button></form>
<p id="convert-error" role="status"></p><div id="converted" aria-live="polite"></div></section>
<section class="panel"><h2>完全一致シードの推移</h2><p class="muted lead">本数字とボーナス数字の両方が完全一致したシードのみ表示。各回の最小シードを使用。実機のシードや予測力ではありません。</p>
<svg class="chart" id="chart" viewBox="0 0 900 250" role="img" aria-label="候補シード推移グラフ"></svg><p class="muted" id="chartnote"></p></section>
<section class="panel"><h2>分析結果</h2><div id="analysis" class="muted"></div></section>
<section class="panel"><h2>完全一致した開催回とシード</h2><div class="scroll"><table><thead><tr><th>開催回</th><th>完全一致シード</th><th>本数字一致</th><th>ボーナス一致</th><th>発見数</th></tr></thead><tbody id="candidates"></tbody></table></div></section>
<section class="panel"><h2>処理中の開催回</h2><div id="active" class="muted"></div></section>
<footer>このページは自動実行時点の静的な集計結果です。リアルタイム通信は行いません。APIトークン・認証情報は含まれていません。
各回のシード探索は過去結果に合わせた後付けの探索であり、実際の抽選機のシードを復元したものではありません。</footer>
</main><script id="payload" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.querySelector('#payload').textContent);
let game=6;
const $=id=>document.getElementById(id), n=x=>Number(x||0).toLocaleString('ja-JP');
function shuffle(n,seed){
  let state=seed>>>0;
  function rnd(){
    state=(state+0x6D2B79F5)>>>0;
    let t=state;
    t=Math.imul(t^(t>>>15),t|1)>>>0;
    t=(t^((t+Math.imul(t^(t>>>7),t|61))>>>0))>>>0;
    return ((t^(t>>>14))>>>0)/4294967296;
  }
  const a=Array.from({length:n},(_,i)=>i+1);
  for(let i=n-1;i>0;i--){const j=Math.floor(rnd()*(i+1));[a[i],a[j]]=[a[j],a[i]]}
  return a;
}
function renderSeed(value){
  const input=String(value).trim();
  if(!/^(0|[1-9][0-9]*)$/.test(input)||Number(input)>4294967295){
    $('convert-error').textContent='シードには0〜4,294,967,295の整数を入力してください。';
    $('converted').replaceChildren();return;
  }
  $('convert-error').textContent='';
  $('seed-input').value=input;
  const size=game===6?43:37, k=game===6?6:7, bonuses=game===6?1:2;
  const nums=shuffle(size,Number(input)), main=nums.slice(0,k).sort((a,b)=>a-b), bonus=nums.slice(k,k+bonuses).sort((a,b)=>a-b);
  const root=$('converted');root.replaceChildren();
  const heading=document.createElement('p');heading.textContent='ロト'+game+'｜シード '+input;root.append(heading);
  for(const [label,values,type] of [['本数字',main,''],['ボーナス数字',bonus,'bonus']]){
    const title=document.createElement('div');title.textContent=label;title.className='muted';root.append(title);
    const balls=document.createElement('div');balls.className='balls';
    for(const value of values){const ball=document.createElement('span');ball.className='ball '+type;ball.textContent=String(value).padStart(2,'0');balls.append(ball)}
    root.append(balls);
  }
  const info=document.createElement('p');info.className='muted lead';
  info.textContent='これは指定シードから生成した数字です。過去回との一致、将来の当選、実抽選機の状態を保証するものではありません。';root.append(info);
}
$('seed-form').addEventListener('submit',e=>{e.preventDefault();renderSeed($('seed-input').value)});
function show(){
document.querySelectorAll('[data-game]').forEach(b=>b.setAttribute('aria-pressed',Number(b.dataset.game)===game?'true':'false'));
const s=D.summary.find(v=>Number(v.game)===game)||{};
const scanned=Number(s.scanned||0),planned=Number(s.planned||0);
const pct=planned?100*scanned/planned:0;
$('rounds').textContent=n(s.rounds);$('scanned').textContent=n(scanned);
$('finished').textContent=n(s.completed);$('percent').textContent=pct.toFixed(2)+'%';
$('bar').style.width=Math.min(100,pct)+'%';
$('plan').textContent=n(scanned)+' / '+n(planned)+' シード（現在設定されている探索範囲。未発見の場合は拡張）';
const rows=D.completed.filter(v=>Number(v.game)===game).sort((a,b)=>Number(a.round)-Number(b.round));
const chosen=rows.slice(-150);
const svg=$('chart');svg.replaceChildren();
const el=(tag,attrs,text)=>{let x=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>x.setAttribute(k,v));if(text!=null)x.textContent=text;svg.append(x);return x};
if(chosen.length<2){$('chartnote').textContent='完全一致した開催回が2回以上になるとグラフが表示されます。';}
else{
const points=chosen.map(r=>Number(r.best[0].seed));
const lo=Math.min(...points),hi=Math.max(...points),range=Math.max(1,hi-lo);
for(let i=0;i<5;i++){const y=30+i*43;el('line',{x1:65,y1:y,x2:880,y2:y,stroke:'#38506b'});el('text',{x:5,y:y+4,fill:'#b5c4d6','font-size':13},n(Math.round(hi-i*range/4)))}
const xy=points.map((v,i)=>[65+815*i/Math.max(points.length-1,1),202-(v-lo)/range*172]);
el('polyline',{points:xy.map(p=>p.join(',')).join(' '),fill:'none',stroke:'#ffbb59','stroke-width':2.5,'stroke-linejoin':'round'});
$('chartnote').textContent='表示対象: '+chosen.length+'開催回（第'+chosen[0].round+'回〜第'+chosen[chosen.length-1].round+'回）';
}
const study=D.studies.find(v=>Number(v.game)===game),a=study&&study.summary;
$('analysis').textContent=a&&a.matched_rounds>=5
? '完全一致した開催回 '+n(a.matched_rounds)+'件｜1期ラグ相関 '+(a.lag1_r==null?'算出不可':Number(a.lag1_r).toFixed(4))+'｜探索的置換検定 p≈'+Number(a.permutation_p_exploratory).toFixed(3)+'。候補は過去結果で選択されており、将来予測の根拠にはなりません。'
: '完全一致した開催回が5回以上になると、自己相関などを表示します。';
const table=$('candidates');table.replaceChildren();
for(const r of rows.slice(-60).reverse()){
 const tr=document.createElement('tr');const best=r.best[0]||{};
 for(const v of [r.round,best.seed??'—',best.hit??'—',best.bonusHit??'—',r.exact_count]){
 const td=document.createElement('td');td.textContent=String(v);tr.append(td)
 }
 if(best.seed!=null){
   const btn=document.createElement('button');btn.type='button';btn.className='small-btn';btn.textContent='数字に変換';
   btn.addEventListener('click',()=>{renderSeed(best.seed);$('seed-form').scrollIntoView({behavior:'smooth',block:'center'})});
   tr.cells[1].append(btn);
 }
 table.append(tr);
}
if(!rows.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=5;td.textContent='完全一致したシードが見つかると表示されます';tr.append(td);table.append(tr)}
const active=D.active.filter(v=>Number(v.game)===game);
$('active').textContent=active.length?active.map(v=>'第'+v.round+'回：'+n(v.scanned)+' / '+n(v.seed_limit)).join(' ／ '):'現在部分的に処理済みの開催回はありません';
}
document.querySelectorAll('[data-game]').forEach(b=>b.addEventListener('click',()=>{game=Number(b.dataset.game);show();if($('seed-input').value)renderSeed($('seed-input').value)}));
$('stamp').textContent='データ取得時刻（UTC）: '+D.generated_at;
show();
</script></body></html>"""

def main():
    from datetime import datetime,timezone
    data=get_data()
    data["generated_at"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
    encoded=json.dumps(data,ensure_ascii=False,separators=(",",":")).replace("<",r"\u003c")
    out=Path("site/index.html")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(HTML.replace("__DATA__",encoded),encoding="utf-8")
    print("Dashboard generated:",out,"size",out.stat().st_size,
          "bytes; completed rows",len(data["completed"]))

if __name__=="__main__":
    main()
