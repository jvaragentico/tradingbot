const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };
const usd = (v, d=2) => v == null ? 'Unavailable' : '$'+Number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const signed = v => v == null ? 'Unavailable' : (v<0?'−':'+')+usd(Math.abs(v));
const date = t => new Date(t*1000);
let last=null, busy=false;

function draw(points) {
  const c=$('price-chart'), r=c.getBoundingClientRect(), d=devicePixelRatio||1;
  c.width=r.width*d;c.height=r.height*d;
  const x=c.getContext('2d');x.scale(d,d);
  if(!points?.length)return;
  const values=points.map(p=>p.close), low=Math.min(...values), high=Math.max(...values);
  const range=Math.max(high-low,1), lo=low-range*.1, hi=high+range*.1;
  const px=i=>60+i/(values.length-1)*(r.width-72), py=v=>15+(hi-v)/(hi-lo)*(r.height-46);
  x.font='11px system-ui';x.textAlign='right';
  for(let i=0;i<4;i++){let v=lo+(hi-lo)*i/3,y=py(v);x.strokeStyle='#243044';x.beginPath();x.moveTo(60,y);x.lineTo(r.width-12,y);x.stroke();x.fillStyle='#8d9bb0';x.fillText('$'+Math.round(v).toLocaleString(),54,y+4)}
  const gradient=x.createLinearGradient(0,15,0,r.height);gradient.addColorStop(0,'#4ce6b640');gradient.addColorStop(1,'#4ce6b600');
  x.beginPath();values.forEach((v,i)=>i?x.lineTo(px(i),py(v)):x.moveTo(px(i),py(v)));x.lineTo(px(values.length-1),r.height-31);x.lineTo(px(0),r.height-31);x.closePath();x.fillStyle=gradient;x.fill();
  x.beginPath();values.forEach((v,i)=>i?x.lineTo(px(i),py(v)):x.moveTo(px(i),py(v)));x.strokeStyle='#4ce6b6';x.lineWidth=2;x.stroke();
  x.fillStyle='#8d9bb0';x.textAlign='left';x.fillText(date(points[0].time).toLocaleDateString(),60,r.height-7);x.textAlign='right';x.fillText(date(points.at(-1).time).toLocaleDateString(),r.width-12,r.height-7);
}

async function refresh(){
  if(busy)return;busy=true;
  try {
    const response=await fetch('/api/state',{cache:'no-store'});if(!response.ok)throw Error('Dashboard unavailable');
    const s=await response.json();last=s;
    text('clock',new Date().toLocaleTimeString());text('mode',s.mode+' MODE');
    text('connection',s.ready&&s.healthy?'MARKET CONNECTED':'WAITING FOR MARKET');$('connection').className='status-dot '+(s.ready&&s.healthy?'healthy':'bad');
    $('error').hidden=!s.error;text('error',s.error||'');
    text('notice',s.mode==='LIVE'?'LIVE: this bot sends real transactions from your dedicated wallet. Losses, gas costs and failed trades are possible.':'PAPER: live market data with simulated trades. Live execution is implemented but no wallet is connected to this session.');
    if(!s.ready)return;
    text('equity',usd(s.equity));text('profit',signed(s.pnl)+' total P/L');$('profit').className='sub '+(s.pnl>=0?'positive':'negative');text('initial','Starting capital '+usd(s.initial));
    text('price',usd(s.market.BTCB.price));text('updated',s.age.toFixed(0)+'s ago · '+(s.market.gas_price/1e9).toFixed(3)+' gwei');text('block','BNB Chain block '+s.market.block.toLocaleString());
    text('signal',s.signal);text('averages','20h '+usd(s.fast)+' · 50h '+usd(s.slow));text('decision',s.paused?s.pause_reason:s.decision);
    text('base',s.balances.BTCB.toFixed(8)+' BTCB');text('quote',s.balances.USDT.toFixed(4)+' USDT');text('gas-reserve',s.balances.BNB.toFixed(7)+' BNB for gas');
    text('wallet',s.wallet?'Wallet '+s.wallet.slice(0,8)+'…'+s.wallet.slice(-6):'Simulated wallet · native BNB retained for gas');text('gas-cost',usd(s.market.gas_price*180000/1e18*s.market.BNB.price,4));
    $('toggle').disabled=false;text('toggle',(s.paused?'Resume':'Pause')+' '+s.mode.toLowerCase()+' bot');text('trades-title',s.mode==='LIVE'?'Onchain trade activity':'Paper trade activity');
    text('trade-count',s.events.filter(e=>['BUY','SELL'].includes(e.kind)).length+' trend trades / '+s.events.filter(e=>e.kind==='ARB').length+' arb cycles');$('trades').replaceChildren();
    if(!s.events.length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=6;cell.className='empty';cell.textContent='Waiting for the first qualifying action.';row.append(cell);$('trades').append(row)}
    for(const e of s.events){const row=document.createElement('tr');for(const v of [date(e.time).toISOString().slice(0,16).replace('T',' '),e.kind,(e.deltas.BTCB/1e18).toFixed(8),(e.deltas.USDT/1e18).toFixed(4),usd(e.gas_usd,4)]){const c=document.createElement('td');c.textContent=v;row.append(c)}const c=document.createElement('td');if(e.execution==='LIVE'){const a=document.createElement('a');a.href='https://bscscan.com/tx/'+e.txid;a.textContent=e.txid.slice(0,10)+'…';a.target='_blank';a.rel='noopener noreferrer';c.append(a)}else{c.textContent='Simulation'}row.append(c);$('trades').append(row)}
    text('pending',s.pending?'Awaiting confirmation: '+s.pending.kind+' · '+s.pending.txid:'No transaction awaiting confirmation');
    const b=s.backtest;if(b.end_usd!=null){text('test-range',date(b.start).toLocaleDateString()+' – '+date(b.end).toLocaleDateString());text('test-end',usd(b.end_usd));text('test-profit',signed(b.end_usd-22)+' from $22 cash');$('test-profit').className='sub '+(b.end_usd>=22?'positive':'negative');text('test-hold',usd(b.hold_end_usd));text('test-stats',b.trade_count+' / '+b.max_drawdown_pct.toFixed(2)+'%');text('test-halted',b.halted?'Triggered':'Not triggered');text('test-notes',b.assumptions)}
    const arb=s.arbitrage||{}, best=arb.best;
    text('arb-state',arb.candidate?'QUALIFIED':best?'NO EDGE':'WAITING');
    text('arb-route',best?best.route.join(' > '):'No funded route yet');
    text('arb-gain',best?best.gross_gain_usd.toFixed(4)+' USD':'—');
    text('arb-required',best?'+'+best.required_gain_usd.toFixed(2)+' USD':'—');
    text('arb-reason',arb.status||'Restart this bot process to enable the new 24-hour arbitrage scanner.');
    draw(s.candles);text('footer-time','Refreshed '+new Date().toLocaleTimeString());
  }catch(e){$('error').hidden=false;text('error',String(e));text('connection','DISCONNECTED');$('connection').className='status-dot bad'}finally{busy=false}
}
$('toggle').addEventListener('click',async()=>{if(!last?.ready)return;$('toggle').disabled=true;try{const res=await fetch(last.paused?'/api/resume':'/api/pause',{method:'POST',headers:{'X-Orbit-Token':document.querySelector('meta[name="control-token"]').content}});const data=await res.json();if(!res.ok)throw Error(data.error);await refresh()}catch(e){$('error').hidden=false;text('error',String(e));$('toggle').disabled=false}});
window.addEventListener('resize',()=>draw(last?.candles));refresh();setInterval(refresh,3000);
