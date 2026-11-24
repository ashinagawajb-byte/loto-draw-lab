(() => {
 const prefix='#analyzer-result=';
 function decodeAnalyzerResult(hash){
  if(!hash.startsWith(prefix))return null;
  if(hash.length>768)throw Error('long payload');
  const result=JSON.parse(decodeURIComponent(hash.slice(prefix.length)));
  if(!result||result.v!==1||!['loto6','loto7'].includes(result.game))throw Error('invalid game');
  const {game,round,date,main,bonus,set}=result;
  const seven=game==='loto7';
  const dateTime=typeof date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(date)?Date.parse(date):NaN;
  if(!Number.isSafeInteger(round)||round<1||round>99999||
     !Number.isFinite(dateTime)||new Date(dateTime).toISOString().slice(0,10)!==date)
   throw Error('invalid round or date');
  if(!Array.isArray(main)||main.length!==(seven?7:6)||!Array.isArray(bonus)||bonus.length!==(seven?2:1))
   throw Error('invalid number count');
  const numbers=[...main,...bonus];
  if(new Set(numbers).size!==numbers.length||numbers.some(n=>!Number.isInteger(n)||n<1||n>(seven?37:43)))
   throw Error('invalid numbers');
  if(set!==undefined&&(typeof set!=='string'||!/^[A-J]$/.test(set)))throw Error('invalid set');
  return {game,round,date,main,bonus,set};
 }
 function renderAnalyzerResult(){
  const card=document.getElementById('receivedAnalyzerResult');
  const status=document.getElementById('receivedAnalyzerStatus');
  const details=document.getElementById('receivedAnalyzerDetails');
  card.hidden=!location.hash.startsWith(prefix);
  if(card.hidden)return;
  details.hidden=true;
  try{
   const result=decodeAnalyzerResult(location.hash);
   const format=numbers=>numbers.map(n=>String(n).padStart(2,'0')).join('・');
   const game=result.game==='loto7'?'ロト7':'ロト6';
   status.textContent=`${game} 第${result.round}回（${result.date}）${result.set?' ／ セット球 '+result.set:''}`;
   document.getElementById('receivedAnalyzerMain').textContent=format(result.main);
   document.getElementById('receivedAnalyzerBonus').textContent=format(result.bonus);
   const next=document.getElementById('receivedAnalyzerNext');
   next.hash=location.hash;
   details.hidden=false;
   const tab=document.querySelector(`button[data-game="${result.game.slice(-1)}"]`);
   if(tab&&tab.getAttribute('aria-pressed')!=='true')tab.click();
  }catch{
   status.textContent='結果を読み込めませんでした。Analyzerから開き直してください。';
  }
 }
 renderAnalyzerResult();
 window.addEventListener('hashchange',renderAnalyzerResult);
})();
