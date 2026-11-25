"""Build a read-only static dashboard from Cloudflare D1 without exposing credentials."""
import json
import shutil
from pathlib import Path
from worker import query
from evaluate_forecasts import score_predictions
from compare_models import compare

SPACE=2**32

def merge_main_counts(main_stats, baseline_cursor, incremental, registered):
    """Merge baseline and per-round checkpoints without summing overlapping scans."""
    by_game={}
    def add(game, rid, value, cursor, source):
        game=str(game); rid=int(rid); count=int(value.get('count') or 0)
        entry={'round':rid,'count':count,'bonus_count':int(value.get('bonus_count') or 0),
               'min_seed':int(value['min_seed']) if count and value.get('min_seed') is not None else None,
               'mean_seed':round(int(value['sum_seed'])/count) if count else None,
               'cursor':int(cursor),'source':source}
        rows=by_game.setdefault(game,{})
        if rid not in rows or entry['cursor']>rows[rid]['cursor']:
            rows[rid]=entry
    for key,value in main_stats.items():
        game,rid=key.split(':',1)
        add(game,rid,value,baseline_cursor,'baseline')
    for row in incremental:
        add(row['game'],row['round'],row,row['cursor'],'incremental')
    result={}
    for game,latest in registered.items():
        game=str(game); rows=by_game.setdefault(game,{})
        if latest is not None and int(latest) not in rows:
            add(game,latest,{},0,'pending')
    for game,rows in by_game.items():
        values=list(rows.values())
        result[game]={'matched_rounds':sum(r['count']>0 for r in values),
                      'matching_seeds':sum(r['count'] for r in values),
                      'bonus_matching_seeds':sum(r['bonus_count'] for r in values),
                      'recent':sorted(values,key=lambda r:r['round'],reverse=True)[:15]}
    return result

def get_data():
    summary = query("""
      SELECT game, COUNT(*) rounds, MAX(CAST(round AS INTEGER)) latest_round, COALESCE(SUM(scanned),0) scanned,
        COALESCE(SUM(seed_limit),0) planned,
        SUM(CASE WHEN exact_count>0 THEN 1 ELSE 0 END) completed,
        COALESCE(SUM(exact_count),0) exact
      FROM jobs GROUP BY game ORDER BY game
    """)
    # Only FULL matches are eligible for display, even when a seed window is incomplete.
    # Show a de-duplicated union while leaving old per-round checkpoints intact.
    try:
        completed = query("""
          SELECT j.game,j.round,j.scanned,j.seed_limit,
                 COUNT(*) AS exact_count,MIN(m.seed) AS seed
          FROM (
            SELECT game,round,seed FROM exact_matches
            UNION
            SELECT game,round,seed FROM global_exact_matches
          ) m JOIN jobs j ON j.game=m.game AND j.round=m.round
          GROUP BY j.game,j.round
          ORDER BY j.game,CAST(j.round AS INTEGER) DESC LIMIT 800
        """)
        global_rows = query("SELECT cursor,target_hash,updated_at FROM global_progress WHERE id=1")
        global_counts = query("""
          SELECT game,COUNT(DISTINCT round) AS matched_rounds,COUNT(*) AS exact_seeds
          FROM global_exact_matches GROUP BY game
        """)
        combined_counts = query("""
          SELECT game,COUNT(DISTINCT round) AS completed,COUNT(*) AS exact
          FROM (
            SELECT game,round,seed FROM exact_matches
            UNION
            SELECT game,round,seed FROM global_exact_matches
          ) GROUP BY game
        """)
    except RuntimeError as exc:
        if 'no such table' not in str(exc).lower():
            raise
        completed = query("""
          SELECT j.game,j.round,j.scanned,j.seed_limit,j.exact_count,MIN(m.seed) AS seed
          FROM exact_matches m JOIN jobs j ON j.game=m.game AND j.round=m.round
          GROUP BY j.game,j.round ORDER BY j.game,CAST(j.round AS INTEGER) DESC LIMIT 800
        """)
        global_rows = []
        global_counts = []
        combined_counts = []
    main_stats={}
    try:
        main_rows=query("SELECT cursor,target_hash,stats,updated_at FROM main_progress WHERE id=1")
        main_state=main_rows[0] if main_rows else None
        if main_state:
            main_stats=json.loads(main_state.pop("stats"))
    except RuntimeError as exc:
        if 'no such table' not in str(exc).lower():raise
        main_state=None
    try:
        incremental=query("SELECT game,round,cursor,count,bonus_count,min_seed,sum_seed FROM analyzer_round_scan ORDER BY game,round DESC")
    except RuntimeError as exc:
        if 'no such table' not in str(exc).lower():raise
        incremental=[]
    main_counts=merge_main_counts(main_stats,main_state['cursor'] if main_state else 0,
                                  incremental,{row['game']:row['latest_round'] for row in summary})
    active = query("""
      SELECT game, round, scanned, seed_limit, best
      FROM jobs WHERE scanned > 0 AND scanned < seed_limit
      ORDER BY updated_at DESC LIMIT 10
    """)
    studies = query("SELECT game, summary, updated_at FROM seed_analysis")
    # Metrics are updated only after a successful, checkpointed worker run.
    try:
        runs = query("""SELECT run_id,scanned,found,duration_seconds,completed_at
            FROM search_runs ORDER BY completed_at DESC LIMIT 12""")
    except RuntimeError as exc:
        # Allow the dashboard to publish before the first worker initializes telemetry.
        if 'no such table: search_runs' not in str(exc).lower():
            raise
        runs = []
    combined_by_game={int(row["game"]):row for row in combined_counts}
    for row in summary:
        matched=combined_by_game.get(int(row["game"]))
        if matched:
            row["completed"]=matched["completed"]
            row["exact"]=matched["exact"]
    for row in completed:
        row["best"] = [{"seed":int(row["seed"]),"hit":int(row["game"]),"bonusHit":1 if int(row["game"])==6 else 2}]
    for row in active:
        row["best"] = []
    for row in studies:
        row["summary"] = json.loads(row["summary"])
    return {"summary": summary, "completed": completed, "active": active,
            "studies": studies, "runs": runs,
            "global": global_rows[0] if global_rows else None,
            "global_counts": global_counts,
            "main_progress": main_state, "main_counts": main_counts,
            "incremental": incremental, "forecast_scores": score_predictions(),
            "site_comparison": compare(), "note": "シード値は仮想PRNGの値であり、実機の状態ではありません。過去結果に合わせた値から予測力は導けません。"}

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
.delta-plus{color:#9ee6b0}.delta-minus{color:#ffbcad}
.compare-empty{color:#a5b5c9}
.compare-detail{padding:14px;border:1px solid #38506b;border-radius:10px;margin:12px 0}
.compare-detail strong{color:#f2c278}
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
<section class="grid" aria-label="進捗"><div class="panel"><div class="muted">登録開催回</div><div class="metric" id="rounds">—</div><div class="muted lead" id="registered-through"></div></div>
<div class="panel"><div class="muted">最新回の主研究探索済みシード</div><div class="metric" id="scanned">—</div></div>
<div class="panel"><div class="muted">完全一致した開催回</div><div class="metric" id="finished">—</div></div>
<div class="panel"><div class="muted">最新回の主研究進捗</div><div class="metric" id="percent">—</div></div></section>
<section class="panel"><h2>Site Analyzer × DRAW LAB｜5口比較</h2>
<p class="muted lead">両者の抽せん前に固定した5口を同じ開催回で照合します。Site予測が未取込の場合は未取得と明示し、推測の数字で代用しません。</p>
<div id="site-comparison-status" class="muted lead">データ確認中</div>
<div class="scroll"><table><thead><tr><th>開催回</th><th>予測元</th><th>モデル</th><th>最大一致</th><th>5口の一致合計</th><th>5等以上</th></tr></thead><tbody id="site-comparison-table"></tbody></table></div>
</section>
<section class="panel"><h2>抽せん前に固定した予測の検証</h2>
<p class="muted lead">抽せん前にGitHubへ保存した候補だけを対象に、公式結果CSVが登録された後に採点します。数字6個の一致数が主指標。ボーナスは参考値です。</p>
<div id="forecast-scores" class="muted lead">照合待ち</div>
</section>
<section class="panel"><h2>Analyzer連携・追加回の探索</h2>
<p class="muted lead">既存探索を維持し、新規回は別カーソルで32ビット空間を探索。全探索完了後のみ次回候補を固定します。</p>
<div id="incremental-seed-progress" class="muted lead">確認中</div>
<p><a href="predictions/index.json">固定予測ファイル一覧</a></p></section>
<section class="panel"><h2>本数字のみの探索（主研究）</h2>
<p class="muted lead">本数字一致を主指標として、ボーナス一致は内訳として別集計。基礎探索とAnalyzerから追加された開催回の探索結果を統合します。探索中の回は途中集計として表示します。</p>
<div class="grid">
<div><div class="muted lead">最新登録回の探索済みシード</div><div class="metric" id="main-scanned">—</div></div>
<div><div class="muted lead">最新登録回の探索率</div><div class="metric" id="main-percent">—</div></div>
<div><div class="muted lead">本数字一致の延べ件数</div><div class="metric" id="main-hits">—</div></div>
</div>
<div class="progress"><div id="main-bar" style="width:0%"></div></div>
<p class="muted lead" id="main-note"></p>
<div class="scroll"><table><thead><tr><th>開催回</th><th>探索進捗</th><th>本数字一致</th><th>うちボーナス一致</th><th>最小シード</th><th>平均シード</th></tr></thead><tbody id="main-table"></tbody></table></div>
</section>
<section class="panel"><h2>新方式：全開催回一括照合</h2>
<p class="muted lead">各シードについてロト6・ロト7の結果を1回ずつ生成し、全開催回を同時照合します。旧方式の探索件数とは別の指標です。</p>
<div class="grid">
<div><div class="muted lead">重複のない探索済みシード</div><div class="metric" id="global-seeds">—</div></div>
<div><div class="muted lead">32ビット全空間の探索率</div><div class="metric" id="global-percent">—</div></div>
<div><div class="muted lead">新方式の完全一致シード</div><div class="metric" id="global-matches">—</div></div>
</div>
<div class="progress"><div id="global-bar" style="width:0%"></div></div>
<p class="muted lead" id="global-note"></p>
</section>
<section class="panel"><h2>旧方式のクラウド探索履歴（参考）</h2>
<div class="grid">
<div><div class="muted lead">直近の探索件数（両ゲーム合計）</div><div class="metric" id="last-scanned">—</div></div>
<div><div class="muted lead">直近の処理速度</div><div class="metric" id="last-rate">—</div></div>
<div><div class="muted lead">最近の平均探索数（最大12回）</div><div class="metric" id="avg-scanned">—</div></div>
</div><p id="last-run" class="muted lead"></p>
<p id="last-run-status" class="muted lead"></p>
</section>
<section class="panel"><h2>探索範囲の進捗</h2><p class="muted lead">現在稼働中の主研究（選択中のゲームの最新登録回）を表示します。</p><div class="progress"><div id="bar" style="width:0%"></div></div><p class="muted" id="plan"></p><p class="muted lead" id="legacy-plan"></p></section>
<section class="panel"><h2>シード番号から抽選数字を再現</h2>
<p class="muted lead">上のロト6／ロト7を選択し、0〜4,294,967,295の整数シードを入力。クラウド探索と同じ仮想乱数アルゴリズムで計算します。</p>
<form id="seed-form" class="seed-form"><label for="seed-input">シード</label><input id="seed-input" inputmode="numeric" type="text" placeholder="例：12345" autocomplete="off" required><button type="submit">数字へ変換</button></form>
<p id="convert-error" role="status"></p><div id="converted" aria-live="polite"></div></section>
<section class="panel"><h2>完全一致シードの推移</h2><p class="muted lead">本数字とボーナス数字の両方が完全一致したシードのみ表示。各回の最小シードを使用。実機のシードや予測力ではありません。</p>
<svg class="chart" id="chart" viewBox="0 0 900 250" role="img" aria-label="候補シード推移グラフ"></svg><p class="muted" id="chartnote"></p></section>
<section class="panel"><h2>完全一致シードの差分と数字の変化</h2>
<p class="muted lead">完全一致が発見された開催回を昇順に並べ、前後の<strong>発見済み回</strong>を比較。連続開催かどうかを区別します。各回で発見済みの最小シードを使用します。</p>
<div class="scroll"><table><thead><tr><th>比較する回</th><th>開催間隔</th><th>シード差分</th><th>本数字の共通数</th><th>新しく登場した本数字</th><th>表示</th></tr></thead><tbody id="delta-table"></tbody></table></div>
<div id="delta-summary" class="muted lead"></div><div id="delta-detail"></div>
</section>
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
function drawNumbers(seed){
  const k=game===6?6:7,b=game===6?1:2,n=game===6?43:37;
  const nums=shuffle(n,seed);
  return {main:nums.slice(0,k).sort((a,b)=>a-b),bonus:nums.slice(k,k+b).sort((a,b)=>a-b)};
}
function numberList(label,values,type){
  const holder=document.createElement('div');
  const title=document.createElement('p');title.className='muted lead';title.textContent=label;holder.append(title);
  const balls=document.createElement('div');balls.className='balls';
  for(const value of values){
    const ball=document.createElement('span');ball.className='ball '+(type||'');
    ball.textContent=String(value).padStart(2,'0');balls.append(ball);
  }
  holder.append(balls);return holder;
}
function renderPair(prev,next){
 const a=drawNumbers(Number(prev.seed)),b=drawNumbers(Number(next.seed));
 const root=$('delta-detail');root.replaceChildren();
 const card=document.createElement('div');card.className='compare-detail';
 const title=document.createElement('strong');
 title.textContent='第'+prev.round+'回 → 第'+next.round+'回（'+(Number(next.round)-Number(prev.round))+'開催分）';
 card.append(title);
 const p=document.createElement('p');p.className='muted lead';
 p.textContent='完全一致シード '+n(prev.seed)+' → '+n(next.seed)+' / 差分 '+(Number(next.seed)-Number(prev.seed)).toLocaleString('ja-JP',{signDisplay:'always'});
 card.append(p);
 card.append(numberList('前の回：本数字',a.main));
 card.append(numberList('次の回：本数字',b.main));
 card.append(numberList('前の回：ボーナス',a.bonus,'bonus'));
 card.append(numberList('次の回：ボーナス',b.bonus,'bonus'));
 const same=a.main.filter(x=>b.main.includes(x));
 const added=b.main.filter(x=>!a.main.includes(x));
 const removed=a.main.filter(x=>!b.main.includes(x));
 const info=document.createElement('p');
 info.textContent='共通した本数字：'+(same.join('・')||'なし')+' ／ 新登場：'+(added.join('・')||'なし')+' ／ 消えた数字：'+(removed.join('・')||'なし');
 card.append(info);
 const note=document.createElement('p');note.className='muted lead';
 note.textContent='開催回に欠番がある比較では、間にある開催回の数字の推移は分かりません。いずれのシードも過去結果に後付けで一致した値です。';
 card.append(note);root.append(card);
}
function renderDeltas(rows){
 const body=$('delta-table');body.replaceChildren();$('delta-detail').replaceChildren();
 const pairs=[];
 for(let i=1;i<rows.length;i++){
   const prev=rows[i-1],next=rows[i],gap=Number(next.round)-Number(prev.round);
   if(gap<=0)continue;
   const a=drawNumbers(Number(prev.seed)),b=drawNumbers(Number(next.seed));
   pairs.push({prev,next,gap,delta:Number(next.seed)-Number(prev.seed),
     same:a.main.filter(v=>b.main.includes(v)),
     added:b.main.filter(v=>!a.main.includes(v))});
 }
 const recent=pairs.slice(-50).reverse();
 for(const p of recent){
   const tr=document.createElement('tr');
   const vals=['第'+p.prev.round+'→'+p.next.round+'回',p.gap===1?'連続開催':'間隔 '+p.gap+' 回',
     p.delta.toLocaleString('ja-JP',{signDisplay:'always'}),p.same.length+'個',p.added.join('・')||'なし'];
   for(const v of vals){const td=document.createElement('td');td.textContent=v;tr.append(td)}
   const td=document.createElement('td'),btn=document.createElement('button');
   btn.className='small-btn';btn.type='button';btn.textContent='詳細';
   btn.addEventListener('click',()=>renderPair(p.prev,p.next));
   td.append(btn);tr.append(td);body.append(tr);
 }
 if(!recent.length){
   const tr=document.createElement('tr'),td=document.createElement('td');
   td.colSpan=6;td.className='compare-empty';
   td.textContent='比較できる完全一致の開催回が2回以上見つかると表示されます。';
   tr.append(td);body.append(tr);
 }
 const consecutive=pairs.filter(p=>p.gap===1);
 $('delta-summary').textContent='完全一致が確認された開催回：'+n(rows.length)+'回 ／ 比較可能な組：'+n(pairs.length)+'組 ／ 実際に連続する開催回：'+n(consecutive.length)+'組。共通数・差分は記述統計であり、次回予想の根拠にはなりません。';
}
function show(){
document.querySelectorAll('[data-game]').forEach(b=>b.setAttribute('aria-pressed',Number(b.dataset.game)===game?'true':'false'));
showMain();
const s=D.summary.find(v=>Number(v.game)===game)||{};
const latestMain=(mainByGame[String(game)]?.recent||[])[0];
const scanned=Number(latestMain?.cursor||0),planned=4294967296;
const pct=100*scanned/planned;
$('rounds').textContent=n(s.rounds);
$('registered-through').textContent=s.latest_round?'最新登録：第'+s.latest_round+'回':'';
$('scanned').textContent=n(scanned);
$('finished').textContent=n(s.completed);$('percent').textContent=pct.toFixed(2)+'%';
$('bar').style.width=Math.min(100,pct)+'%';
$('plan').textContent=(latestMain?'第'+latestMain.round+'回：':'')+n(scanned)+' / '+n(planned)+' シード｜'+(scanned===planned?'探索完了':scanned>0?'探索中（保存済み進捗）':'探索開始待ち');
$('legacy-plan').textContent='旧方式（停止・記録保持）：'+n(s.scanned||0)+' / '+n(s.planned||0)+' シード。現在は全回一括照合と追加回の主研究に移行済みです。';
const rows=D.completed.filter(v=>Number(v.game)===game).sort((a,b)=>Number(a.round)-Number(b.round));
const chosen=rows.slice(-150);
renderDeltas(rows);
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
const siteComparison=D.site_comparison||{};
const siteStatus=siteComparison.site_source||{};
const paired=Number(siteComparison.paired_rounds||0);
$('site-comparison-status').textContent=(siteStatus.state==='loaded'||siteStatus.state==='loaded_raw'
 ?'Site Analyzer：取込済み '+(siteStatus.loaded_rounds||0)+'開催回・'+(siteStatus.portfolio_count||0)+'組。'+
 (siteStatus.state==='loaded_raw'?'原本CSVに固定日時・世代なし（証跡未確認）。':'')
 :'Site Analyzer：予想記録が未取得。')+
 ' 同一回で採点できた回数 '+paired+'回（うち日時付き記録 '+Number(siteComparison.verified_paired_rounds||0)+'回）。比較は5口同士で行います。';
const siteBody=$('site-comparison-table');siteBody.replaceChildren();
for(const draw of (siteComparison.scored_rounds||[]).slice(-12).reverse()){
 for(const p of draw.portfolios){
  const tr=document.createElement('tr');
  for(const value of [draw.round,p.source,p.method+(p.generation?' / '+p.generation:''),p.max_main_hits+'個',p.main_hits_sum+'個',p.any_5th_or_better?'あり':'なし']){
   const td=document.createElement('td');td.textContent=value;tr.append(td)
  }
  siteBody.append(tr);
 }
}
if(!siteBody.children.length){
 const row=document.createElement('tr'),cell=document.createElement('td');
 cell.colSpan=6;cell.textContent='両モデルの事前予想と開催結果がそろうと比較を表示します。';row.append(cell);siteBody.append(row)
}
const forecastScores=D.forecast_scores||[];
const forecastBox=$('forecast-scores');
if(!forecastScores.length){
 forecastBox.textContent='まだ照合できる開催結果がありません。第2157回の予想は変更せず保持します。';
}else{
 forecastBox.replaceChildren();
 for(const result of forecastScores.slice(-5).reverse()){
  const heading=document.createElement('p');
  heading.textContent='第'+result.round+'回｜当選本数字：'+result.actual_main.join('・')+'｜ボーナス：'+result.actual_bonus;
  forecastBox.append(heading);
  const table=document.createElement('table');
  const header=document.createElement('tr');
  for(const label of ['予測方式','本数字一致','ボーナス一致']){
   const th=document.createElement('th');th.textContent=label;header.append(th)
  }
  table.append(header);
  for(const candidate of result.candidates){
   const tr=document.createElement('tr');
   for(const value of [candidate.method,candidate.main_hits+'個',candidate.bonus_hit?'一致':'不一致']){
    const td=document.createElement('td');td.textContent=value;tr.append(td)
   }
   table.append(tr)
  }
  forecastBox.append(table);
 }
 const disclaimer=document.createElement('p');
 disclaimer.textContent='公平乱数で予想した6数字と実際の本数字6個の平均一致数は36/43≈0.837個。少数回の差では予測力を判断できません。';
 forecastBox.append(disclaimer);
}
const incrementalBox=$('incremental-seed-progress');
const incremental=D.incremental||[];
incrementalBox.textContent=incremental.length?incremental.map(r=>'ロト'+r.game+' 第'+r.round+'回：'+(100*r.cursor/4294967296).toFixed(3)+'%（本数字一致 '+r.count+'件）').join(' ／ '):'追加回の探索準備中';
const mainState=D.main_progress||null;
const mainByGame=D.main_counts||{};
function showMain(){
 const summary=mainByGame[String(game)]||{matched_rounds:0,matching_seeds:0,bonus_matching_seeds:0,recent:[]};
 const latest=summary.recent[0],cursor=latest?Number(latest.cursor):0;
 const pct=100*cursor/4294967296;
 $('main-scanned').textContent=latest?n(cursor):'未開始';
 $('main-percent').textContent=latest?pct.toFixed(3)+'%':'—';
 $('main-bar').style.width=Math.min(100,pct)+'%';
 $('main-hits').textContent=n(summary.matching_seeds);
 $('main-note').textContent=(latest?'最新登録：第'+latest.round+'回｜'+(cursor===4294967296?'探索完了':cursor>0?'探索中（暫定値）':'探索開始待ち')+'。':'')+
 ' 本数字一致が見つかった開催回 '+n(summary.matched_rounds)+'回。ボーナスまで一致した延べ件数 '+n(summary.bonus_matching_seeds)+'件。'+
 (mainState?'基礎探索率 '+(Number(mainState.cursor)/4294967296*100).toFixed(3)+'%（最終更新 UTC：'+mainState.updated_at+'）。':'')+
 ' 本数字一致件数は基礎探索と追加回探索の合算です。';
 const body=$('main-table');body.replaceChildren();
 for(const r of summary.recent){
  const tr=document.createElement('tr'),progress=Number(r.cursor)/4294967296*100;
  for(const value of [n(r.round),progress.toFixed(3)+'%'+(r.cursor===4294967296?' 完了':r.cursor>0?' 探索中':' 待機'),n(r.count),n(r.bonus_count),r.min_seed==null?'—':n(r.min_seed),r.mean_seed==null?'—':n(r.mean_seed)]){
    const td=document.createElement('td');td.textContent=value;tr.append(td)
  }
  body.append(tr)
 }
 if(!summary.recent.length){
  const tr=document.createElement('tr'),td=document.createElement('td');
  td.colSpan=6;td.textContent='本数字一致データの蓄積待ち';tr.append(td);body.append(tr)
 }
}
const globalState=D.global||null;
const globalCursor=globalState?Number(globalState.cursor):0;
const globalPercent=100*globalCursor/4294967296;
$('global-seeds').textContent=globalState?n(globalCursor):'未開始';
$('global-percent').textContent=globalState?globalPercent.toFixed(3)+'%':'—';
$('global-matches').textContent=n((D.global_counts||[]).reduce((a,v)=>a+Number(v.exact_seeds||0),0));
$('global-bar').style.width=Math.min(100,globalPercent)+'%';
$('global-note').textContent=globalState?
  '全4,294,967,296シードのうち '+n(globalCursor)+'件を走査。最終チェックポイント（UTC）：'+globalState.updated_at+'。履歴CSV更新時は新しい対象も含めて再照合するため進捗を0から開始し、発見済み一致は保持します。':
  '新しい一括探索エンジンの初回チェックポイントを待っています。';
const runs=D.runs||[];
const latest=runs[0];
$('last-scanned').textContent=latest?n(latest.scanned):'データなし';
$('last-rate').textContent=latest&&Number(latest.duration_seconds)>0?n(Math.round(Number(latest.scanned)/Number(latest.duration_seconds)))+' /秒':'—';
$('avg-scanned').textContent=runs.length?n(Math.round(runs.reduce((a,r)=>a+Number(r.scanned),0)/runs.length)):'—';
$('last-run').textContent=latest?'最終実行記録（UTC）：'+latest.completed_at+'｜完全一致の新規発見：'+n(latest.found)+'件':'探索実行記録の収集開始前です。';
const age=latest?(Date.parse(D.generated_at)-Date.parse(latest.completed_at+'Z'))/3600000:null;
$('last-run-status').textContent=age!=null&&age>3?'注意：最終記録から3時間以上経過しています。GitHub Actionsを確認してください。':'この値は公開画面生成時点の記録です。リアルタイムの監視ではありません。';
$('stamp').textContent='データ取得時刻（UTC）: '+D.generated_at;
show();
</script></body></html>"""

def attach_analyzer_result(page):
    """Install the receiver even when publishing a previously generated snapshot."""
    page = Path(page)
    html = page.read_text(encoding="utf-8")
    if 'id="receivedAnalyzerResult"' not in html:
        card = """
<section id="receivedAnalyzerResult" class="panel" hidden>
<h2>Analyzerから受け取った抽せん結果</h2>
<p id="receivedAnalyzerStatus" role="status"></p>
<div id="receivedAnalyzerDetails" hidden>
<p>本数字 <strong id="receivedAnalyzerMain"></strong></p>
<p>ボーナス <strong id="receivedAnalyzerBonus"></strong></p>
<a id="receivedAnalyzerNext" href="./simulator/">この結果をDRAWシミュレーターで開く</a>
</div>
</section>
"""
        if "</header>" not in html or "</head>" not in html:
            raise ValueError("Dashboard header is missing")
        html = html.replace("</header>", "</header>" + card, 1)
        html = html.replace("</head>", '<script src="./analyzer-result.js" defer></script></head>', 1)
        page.write_text(html, encoding="utf-8")
    receiver = Path(__file__).resolve().parent / "simulator" / "analyzer-result.js"
    shutil.copyfile(receiver, page.with_name(receiver.name))

def main():
    from datetime import datetime,timezone
    data=get_data()
    data["generated_at"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
    encoded=json.dumps(data,ensure_ascii=False,separators=(",",":")).replace("<",r"\u003c")
    out=Path("site/index.html")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(HTML.replace("__DATA__",encoded),encoding="utf-8")
    attach_analyzer_result(out)
    print("Dashboard generated:",out,"size",out.stat().st_size,
          "bytes; completed rows",len(data["completed"]))

if __name__=="__main__":
    main()
