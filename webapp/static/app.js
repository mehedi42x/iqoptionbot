/* ------------------------------------------------------------------ */
/* helpers                                                             */
/* ------------------------------------------------------------------ */
const $  = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const api = async (path, body, method) => {
  const opt = { method: method || (body ? 'POST' : 'GET'), headers: { 'Content-Type': 'application/json' } };
  if (body) opt.body = JSON.stringify(body);
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const money = (n) => (n < 0 ? '-$' : '$') + Math.abs(Number(n) || 0).toFixed(2);
const hhmmss = (ts) => new Date(ts * 1000).toISOString().substr(11, 8);

/* ------------------------------------------------------------------ */
/* state                                                               */
/* ------------------------------------------------------------------ */
let STATE = {};
let CANDLES = [];
let MARKERS = [];
let ASSETS = [];
let LAST_PRICE = null;

/* ------------------------------------------------------------------ */
/* tabs                                                                */
/* ------------------------------------------------------------------ */
$$('.nav-btn').forEach(b => b.onclick = () => {
  $$('.nav-btn').forEach(x => x.classList.remove('active'));
  $$('.tab').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  $('#tab-' + b.dataset.tab).classList.add('active');
  if (b.dataset.tab === 'dashboard') drawChart();
});

/* ------------------------------------------------------------------ */
/* candlestick chart (canvas)                                          */
/* ------------------------------------------------------------------ */
const cv = $('#chart');
const ctx = cv.getContext('2d');

function fit(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  canvas.width = r.width * dpr;
  canvas.height = r.height * dpr;
  const c = canvas.getContext('2d');
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { w: r.width, h: r.height, c };
}

function drawChart() {
  const { w, h, c } = fit(cv);
  c.clearRect(0, 0, w, h);
  c.fillStyle = '#080c14';
  c.fillRect(0, 0, w, h);

  if (!CANDLES.length) {
    c.fillStyle = '#4c5b73';
    c.font = '13px Inter, sans-serif';
    c.textAlign = 'center';
    c.fillText('Waiting for live candles… connect and select a pair.', w / 2, h / 2);
    c.textAlign = 'left';
    return;
  }

  const padR = 66, padB = 24, padT = 12, padL = 8;
  const maxBars = Math.max(20, Math.floor((w - padL - padR) / 9));
  const data = CANDLES.slice(-maxBars);

  let hi = -Infinity, lo = Infinity;
  for (const d of data) { hi = Math.max(hi, d.high); lo = Math.min(lo, d.low); }
  const range = (hi - lo) || (hi * 0.0001) || 1;
  hi += range * 0.12; lo -= range * 0.12;

  const cw = (w - padL - padR) / data.length;
  const bw = Math.max(1.5, Math.min(11, cw * 0.62));
  const x = (i) => padL + i * cw + cw / 2;
  const y = (p) => padT + (hi - p) / (hi - lo) * (h - padT - padB);

  // grid + price axis
  c.strokeStyle = '#141d2b'; c.lineWidth = 1;
  c.fillStyle = '#4c5b73'; c.font = '10.5px "JetBrains Mono", monospace';
  const digits = hi < 10 ? 5 : 2;
  for (let i = 0; i <= 5; i++) {
    const p = lo + (hi - lo) * i / 5, yy = Math.round(y(p)) + .5;
    c.beginPath(); c.moveTo(padL, yy); c.lineTo(w - padR, yy); c.stroke();
    c.fillText(p.toFixed(digits), w - padR + 7, yy + 3.5);
  }
  // time axis
  const step = Math.max(1, Math.floor(data.length / 7));
  for (let i = 0; i < data.length; i += step) {
    c.fillText(hhmmss(data[i].timestamp).substr(0, 5), x(i) - 15, h - 7);
  }

  // candles
  data.forEach((d, i) => {
    const up = d.close >= d.open;
    const live = i === data.length - 1;
    const col = live ? '#f59e0b' : (up ? '#22c55e' : '#ef4444');
    c.strokeStyle = col; c.fillStyle = col; c.lineWidth = 1;
    const xx = Math.round(x(i)) + .5;
    c.beginPath(); c.moveTo(xx, y(d.high)); c.lineTo(xx, y(d.low)); c.stroke();
    const yo = y(d.open), yc = y(d.close);
    const top = Math.min(yo, yc), hgt = Math.max(1.2, Math.abs(yc - yo));
    c.fillRect(xx - bw / 2, top, bw, hgt);
  });

  // last price line
  const last = data[data.length - 1].close;
  const ly = Math.round(y(last)) + .5;
  c.strokeStyle = '#f59e0b'; c.setLineDash([4, 4]); c.lineWidth = 1;
  c.beginPath(); c.moveTo(padL, ly); c.lineTo(w - padR, ly); c.stroke();
  c.setLineDash([]);
  c.fillStyle = '#f59e0b';
  c.fillRect(w - padR + 2, ly - 9, padR - 4, 18);
  c.fillStyle = '#100a00'; c.font = 'bold 10.5px "JetBrains Mono", monospace';
  c.fillText(last.toFixed(digits), w - padR + 6, ly + 4);

  // trade markers
  const t0 = data[0].timestamp;
  const tfSec = STATE.chart_timeframe || 60;
  MARKERS.forEach(m => {
    if (!m.price || m.time < t0 - tfSec) return;
    const idx = (m.time - t0) / tfSec;
    if (idx < 0 || idx > data.length) return;
    const mx = padL + idx * cw + cw / 2, my = y(m.price);
    const call = m.direction === 'call';
    let col = call ? '#22c55e' : '#ef4444';
    if (m.status === 'win') col = '#14b8a6';
    if (m.status === 'loss') col = '#a855f7';
    c.fillStyle = col; c.strokeStyle = col; c.lineWidth = 1.6;
    c.beginPath();
    const d1 = call ? 1 : -1;
    c.moveTo(mx, my);
    c.lineTo(mx - 6, my + 11 * d1);
    c.lineTo(mx + 6, my + 11 * d1);
    c.closePath(); c.fill();
    c.beginPath(); c.arc(mx, my, 3.2, 0, 7); c.fill();
    c.beginPath(); c.setLineDash([2, 3]);
    c.moveTo(mx, my); c.lineTo(mx, call ? my + 26 : my - 26); c.stroke();
    c.setLineDash([]);
    c.font = 'bold 9.5px Inter, sans-serif';
    c.fillText(call ? 'CALL' : 'PUT', mx - 12, call ? my + 34 : my - 28);
  });
}
window.addEventListener('resize', () => { drawChart(); drawEquity(); });

/* ------------------------------------------------------------------ */
/* rendering                                                           */
/* ------------------------------------------------------------------ */
function renderState(s) {
  STATE = s;
  $('#connDot').className = 'dot' + (s.connected ? ' on' : '');
  $('#connText').textContent = s.connected ? 'Connected' : 'Disconnected';
  $('#brandAsset').textContent = s.active_name || '—';
  $('#chartAsset').textContent = s.active_name || '—';

  $('#sBalance').textContent = money(s.balance) + ' ' + (s.currency || '');
  $('#sAcctType').textContent = (s.account_type || '').toLowerCase();
  $('#sPnl').textContent = money(s.pnl);
  $('#sPnl').className = s.pnl > 0 ? 'g' : (s.pnl < 0 ? 'r' : '');
  $('#sTradesCount').textContent = (s.history || []).length + ' trades';
  $('#sWr').textContent = (s.winrate || 0) + '%';
  $('#sWl').textContent = `${s.wins}W / ${s.losses}L / ${s.draws}D`;
  $('#sOpen').textContent = s.active_trades || 0;
  $('#sMax').textContent = 'max ' + s.max_concurrent_trades;
  $('#sStrat').textContent = s.strategy || 'none';
  $('#sTf').textContent = (s.timeframes || []).map(t => t + 's').join(', ');
  $('#sEmail').textContent = s.email ? s.email.split('@')[0] : '—';
  $('#sEmail').style.fontSize = '15px';
  $('#sUid').textContent = s.user_id ? 'UID ' + s.user_id : 'not logged in';

  const pa = $('#pillAuto');
  pa.textContent = s.auto_trading ? 'AUTO ON' : 'AUTO OFF';
  pa.className = 'pill' + (s.auto_trading ? ' on' : '');
  const pc = $('#pillAcct');
  pc.textContent = s.account_type;
  pc.className = 'pill' + (s.account_type === 'REAL' ? ' real' : '');

  $('#autoToggle').checked = !!s.auto_trading;
  $('#autoStateText').textContent = s.auto_trading ? 'Enabled' : 'Disabled';

  $('#aConn').textContent = s.connected ? 'Connected' : 'Offline';
  $('#aBalId').textContent = s.balance ? (s.currency + ' ' + s.balance) : '—';
  $('#aUserId').textContent = s.user_id || '—';
  $('#aTfs').textContent = (s.timeframes || []).map(t => t + 's').join(', ') || '—';

  const st = s.strategy_status || {};
  $('#stratStatus').innerHTML = Object.keys(st).length
    ? Object.entries(st).map(([k, v]) =>
        `<span>${k}: <b>${v === null || v === undefined ? '—' : (typeof v === 'number' ? Number(v).toFixed(6).replace(/0+$/, '') : v)}</b></span>`).join('')
    : '<span class="muted">No strategy loaded.</span>';

  renderOpen(s.open_trades || []);
  renderHistory(s.history || []);
}

function renderOpen(list) {
  const tb = $('#openTable tbody');
  if (!list.length) { tb.innerHTML = '<tr class="empty"><td colspan="7">No open positions</td></tr>'; return; }
  tb.innerHTML = list.map(t => {
    const fl = t.floating === 'winning' ? 'g' : (t.floating === 'losing' ? 'r' : 'y');
    const txt = t.floating === 'winning' ? 'WINNING' : (t.floating === 'losing' ? 'LOSING' : 'FLAT');
    return `<tr>
      <td>${t.asset}</td>
      <td><span class="tag ${t.direction}">${t.direction.toUpperCase()}</span></td>
      <td>${money(t.amount)}</td>
      <td>${t.entry_price ? t.entry_price.toFixed(5) : '—'}</td>
      <td>${t.current_price ? t.current_price.toFixed(5) : '—'}</td>
      <td>${t.seconds_left != null ? t.seconds_left + 's' : '—'}</td>
      <td class="${fl}">${txt}</td></tr>`;
  }).join('');
}

function renderHistory(list) {
  const tb = $('#histTable tbody');
  if (!list.length) { tb.innerHTML = '<tr class="empty"><td colspan="8">No trades yet</td></tr>'; return; }
  tb.innerHTML = list.slice().reverse().map((t, i) => `<tr>
    <td>${list.length - i}</td>
    <td>${hhmmss(t.open_time)}</td>
    <td>${t.asset}</td>
    <td><span class="tag ${t.direction}">${t.direction.toUpperCase()}</span></td>
    <td>${money(t.amount)}</td>
    <td>${t.source}${t.strategy ? ' · ' + t.strategy : ''}</td>
    <td><span class="tag ${(t.result || '').toLowerCase()}">${t.result}</span></td>
    <td class="${t.profit > 0 ? 'g' : (t.profit < 0 ? 'r' : '')}">${money(t.profit)}</td></tr>`).join('');
}

function addLog(d) {
  const box = $('#logBox');
  const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  const el = document.createElement('div');
  el.innerHTML = `<span class="t">${new Date().toTimeString().substr(0, 8)}</span><span class="${d.level}">${d.message}</span>`;
  box.appendChild(el);
  while (box.childNodes.length > 400) box.removeChild(box.firstChild);
  if (stick) box.scrollTop = box.scrollHeight;
}

/* ------------------------------------------------------------------ */
/* websocket                                                           */
/* ------------------------------------------------------------------ */
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (e) => {
    const { type, data } = JSON.parse(e.data);
    if (type === 'state') renderState(data);
    else if (type === 'log') addLog(data);
    else if (type === 'candles_snapshot') {
      CANDLES = data.candles || []; MARKERS = data.markers || []; drawChart();
    } else if (type === 'candle') {
      const c = data.candle;
      if (CANDLES.length && CANDLES[CANDLES.length - 1].timestamp === c.timestamp) CANDLES[CANDLES.length - 1] = c;
      else { CANDLES.push(c); if (CANDLES.length > 500) CANDLES.shift(); }
      LAST_PRICE = c.close;
      $('#chartPrice').textContent = c.close.toFixed(5);
      drawChart();
    } else if (type === 'chart_reset') {
      CANDLES = []; MARKERS = []; drawChart();
    } else if (type === 'trade_open') {
      if (data.entry_price) {
        MARKERS = MARKERS.filter(m => m.id !== data.id);
        MARKERS.push({ id: data.id, time: data.open_time, price: data.entry_price, direction: data.direction, status: 'open' });
        drawChart();
      }
    } else if (type === 'trade_close') {
      const m = MARKERS.find(m => m.id === data.id);
      if (m) { m.status = (data.result || '').toLowerCase(); drawChart(); }
    } else if (type === 'trades_tick') {
      renderOpen(data.open || []);
    } else if (type === 'strategy_status') {
      STATE.strategy_status = data; renderState(STATE);
    } else if (type === 'signal') {
      // handled via log
    }
  };
  ws.onclose = () => setTimeout(connectWS, 2000);
}

/* ------------------------------------------------------------------ */
/* boot data                                                           */
/* ------------------------------------------------------------------ */
async function boot() {
  ASSETS = await api('/api/assets');
  const opts = (() => {
    const groups = {};
    ASSETS.forEach(a => (groups[a.group] = groups[a.group] || []).push(a));
    return Object.entries(groups).map(([g, list]) =>
      `<optgroup label="${g}">${list.map(a => `<option value="${a.id}">${a.name}</option>`).join('')}</optgroup>`).join('');
  })();
  $('#tAsset').innerHTML = opts;
  $('#aAsset').innerHTML = opts;

  const s = await api('/api/state');
  renderState(s);
  $('#aEmail').value = s.email || '';
  $('#aAcctType').value = s.account_type || 'PRACTICE';
  $('#aTradeType').value = s.trade_type || 'turbo';
  $('#tTradeType').value = s.trade_type || 'turbo';
  $('#aAsset').value = s.active_id;
  $('#tAsset').value = s.active_id;
  $('#aAmount').value = s.amount;
  $('#tAmount').value = s.amount;
  $('#aExp').value = s.expiration;
  $('#aMaxConc').value = s.max_concurrent_trades;
  $('#tMaxConc').value = s.max_concurrent_trades;

  await loadStrategies();
  await loadDatasets();
  connectWS();
  drawChart();
}

async function loadStrategies() {
  const list = await api('/api/strategies');
  const html = list.map(s => `<option value="${s.id}">${s.name}${s.builtin ? '' : ' (custom)'}</option>`).join('');
  ['#tStrategy', '#sSelect', '#bStrategy'].forEach(sel => {
    const cur = $(sel).value;
    $(sel).innerHTML = html;
    if (cur && list.find(x => x.id === cur)) $(sel).value = cur;
  });
  if (STATE.strategy) {
    const match = list.find(x => x.name === STATE.strategy);
    if (match) $('#tStrategy').value = match.id;
  }
}

async function loadDatasets() {
  const list = await api('/api/datasets');
  $('#bDataset').innerHTML = list.map(d =>
    `<option value="${d.file}">${d.file} (${d.rows} candles, ${d.timeframe}s)</option>`).join('');
}

/* ------------------------------------------------------------------ */
/* actions                                                             */
/* ------------------------------------------------------------------ */
$('#btnConnect').onclick = async (e) => {
  e.target.disabled = true; e.target.textContent = 'Connecting…';
  try { await api('/api/connect', {}); } catch (err) { alert(err.message); }
  setTimeout(() => { e.target.disabled = false; e.target.textContent = 'Connect'; }, 2500);
};
$('#btnDisconnect').onclick = () => api('/api/disconnect', {});
$('#btnResetStats').onclick = () => api('/api/reset-stats', {});

$('#tfGroup').onclick = (e) => {
  if (e.target.tagName !== 'BUTTON') return;
  $$('#tfGroup button').forEach(b => b.classList.remove('active'));
  e.target.classList.add('active');
  CANDLES = []; drawChart();
  api('/api/chart-timeframe', { timeframe: +e.target.dataset.tf });
};

$('#tAsset').onchange = (e) => api('/api/asset', { active_id: +e.target.value });
$('#aAsset').onchange = (e) => { $('#tAsset').value = e.target.value; api('/api/asset', { active_id: +e.target.value }); };

$('#btnCall').onclick = () => placeTrade('call');
$('#btnPut').onclick = () => placeTrade('put');
async function placeTrade(dir) {
  try {
    await api('/api/trade', { direction: dir, amount: +$('#tAmount').value, expiration: +$('#tExp').value });
  } catch (e) { alert(e.message); }
}

$('#autoToggle').onchange = async (e) => {
  try { await api('/api/auto', { enabled: e.target.checked }); }
  catch (err) { alert(err.message); e.target.checked = false; }
};

$('#btnLoadStratTrading').onclick = async () => {
  try { await api('/api/strategy/load', { name: $('#tStrategy').value }); await loadStrategies(); }
  catch (e) { alert(e.message); }
};

$('#btnApplyTrading').onclick = async () => {
  await api('/api/account', {
    max_concurrent_trades: +$('#tMaxConc').value,
    trade_type: $('#tTradeType').value,
    amount: +$('#tAmount').value,
    expiration: +$('#tExp').value,
  });
  $('#aTradeType').value = $('#tTradeType').value;
};

/* ---- strategy editor ---- */
$('#btnOpenStrat').onclick = async () => {
  const id = $('#sSelect').value;
  const r = await api('/api/strategy-source?id=' + encodeURIComponent(id));
  $('#sCode').value = r.code;
  $('#sFilename').value = (id.startsWith('user:') ? id.slice(5) : id + '_copy.py');
  msg('#sMsg', 'Loaded ' + id, 'ok');
};
$('#btnNewStrat').onclick = () => {
  $('#sFilename').value = 'my_strategy.py';
  $('#sCode').value = TEMPLATE;
  msg('#sMsg', 'New strategy template. Edit and save.', 'ok');
};
$('#btnSaveStrat').onclick = async () => {
  try {
    const r = await api('/api/strategy/save', { filename: $('#sFilename').value, code: $('#sCode').value });
    msg('#sMsg', `Saved & validated. Timeframes: ${r.timeframes.join(', ')}s`, 'ok');
    await loadStrategies();
    $('#sSelect').value = r.id; $('#tStrategy').value = r.id; $('#bStrategy').value = r.id;
  } catch (e) { msg('#sMsg', e.message, 'err'); }
};
$('#btnActivateStrat').onclick = async () => {
  try {
    const r = await api('/api/strategy/save', { filename: $('#sFilename').value, code: $('#sCode').value });
    await api('/api/strategy/load', { name: r.id });
    await loadStrategies();
    msg('#sMsg', 'Strategy is now live. Enable Auto Trading in the Trading tab.', 'ok');
  } catch (e) { msg('#sMsg', e.message, 'err'); }
};
function msg(sel, text, cls) { const el = $(sel); el.textContent = text; el.className = 'msg ' + (cls || ''); }

/* ---- account ---- */
$('#btnSaveAccount').onclick = async () => {
  const body = {
    email: $('#aEmail').value.trim(),
    account_type: $('#aAcctType').value,
    trade_type: $('#aTradeType').value,
    remember: $('#aRemember').checked,
  };
  if ($('#aPassword').value) body.password = $('#aPassword').value;
  await api('/api/account', body);
  $('#tTradeType').value = body.trade_type;
  alert('Account settings saved. Click Connect in the sidebar.');
};
$('#btnSaveDefaults').onclick = async () => {
  await api('/api/account', {
    active_id: +$('#aAsset').value,
    amount: +$('#aAmount').value,
    expiration: +$('#aExp').value,
    max_concurrent_trades: +$('#aMaxConc').value,
    remember: $('#aRemember').checked,
  });
  $('#tAmount').value = $('#aAmount').value;
  $('#tMaxConc').value = $('#aMaxConc').value;
  alert('Defaults saved.');
};

/* ---- backtest ---- */
let EQ = [];
$('#btnRunBt').onclick = async (e) => {
  e.target.disabled = true; e.target.textContent = 'Running…';
  msg('#btMsg', '', '');
  try {
    const r = await api('/api/backtest', {
      strategy: $('#bStrategy').value,
      dataset: $('#bDataset').value,
      expiration: +$('#bExp').value,
      payout: +$('#bPayout').value / 100,
      stake: +$('#bStake').value,
      start: $('#bStart').value || null,
      end: $('#bEnd').value || null,
    });
    renderBacktest(r);
  } catch (err) { msg('#btMsg', err.message, 'err'); }
  e.target.disabled = false; e.target.textContent = 'Run Backtest';
};

function renderBacktest(r) {
  $('#btResult').classList.remove('hidden');
  $('#bTrades').textContent = r.trades;
  $('#bRange').textContent = r.range + ' · ' + r.candles + ' candles';
  $('#bWr').textContent = r.winrate + '%';
  $('#bWr').className = r.winrate >= r.breakeven_winrate ? 'g' : 'r';
  $('#bBe').textContent = 'breakeven ' + r.breakeven_winrate + '%';
  $('#bPnl').textContent = money(r.pnl);
  $('#bPnl').className = r.pnl >= 0 ? 'g' : 'r';
  $('#bRoi').textContent = 'ROI ' + r.roi + '%';
  $('#bDd').textContent = money(r.max_drawdown);
  $('#bStreak').textContent = `best ${r.best_win_streak}W · worst ${r.worst_loss_streak}L`;

  $('#hourTable tbody').innerHTML = r.hourly.map(h =>
    `<tr><td>${String(h.hour).padStart(2, '0')}:00</td><td>${h.trades}</td><td class="g">${h.wins}</td><td class="r">${h.losses}</td>
     <td class="${h.winrate >= r.breakeven_winrate ? 'g' : 'r'}">${h.winrate}%</td></tr>`).join('')
    || '<tr class="empty"><td colspan="5">No data</td></tr>';

  $('#reasonTable tbody').innerHTML = r.top_reasons.map(([k, v]) =>
    `<tr><td>${k}</td><td>${v}</td></tr>`).join('') || '<tr class="empty"><td colspan="2">None</td></tr>';

  $('#btTable tbody').innerHTML = r.trade_list.slice().reverse().map(t =>
    `<tr><td>${t.n}</td><td>${t.entry_dt}</td><td><span class="tag ${t.direction.toLowerCase()}">${t.direction}</span></td>
     <td>${t.entry_price}</td><td>${t.expiry_price}</td>
     <td><span class="tag ${t.result.toLowerCase()}">${t.result}</span></td>
     <td class="${t.profit > 0 ? 'g' : (t.profit < 0 ? 'r' : '')}">${money(t.profit)}</td>
     <td>${money(t.balance)}</td></tr>`).join('') || '<tr class="empty"><td colspan="8">No trades</td></tr>';

  EQ = r.equity; drawEquity();
  msg('#btMsg', `Done — ${r.trades} trades on ${r.dataset}`, 'ok');
}

function drawEquity() {
  const canvas = $('#eqChart');
  if (!canvas || !EQ.length) return;
  const { w, h, c } = fit(canvas);
  c.clearRect(0, 0, w, h);
  c.fillStyle = '#080c14'; c.fillRect(0, 0, w, h);
  const padL = 54, padR = 12, padT = 12, padB = 22;
  let hi = Math.max(...EQ.map(e => e.balance), 0);
  let lo = Math.min(...EQ.map(e => e.balance), 0);
  const rng = (hi - lo) || 1; hi += rng * .1; lo -= rng * .1;
  const x = (i) => padL + i / Math.max(1, EQ.length - 1) * (w - padL - padR);
  const y = (v) => padT + (hi - v) / (hi - lo) * (h - padT - padB);

  c.strokeStyle = '#141d2b'; c.fillStyle = '#4c5b73'; c.font = '10.5px monospace';
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4, yy = Math.round(y(v)) + .5;
    c.beginPath(); c.moveTo(padL, yy); c.lineTo(w - padR, yy); c.stroke();
    c.fillText('$' + v.toFixed(0), 6, yy + 3.5);
  }
  const zy = Math.round(y(0)) + .5;
  c.strokeStyle = '#4c5b73'; c.setLineDash([3, 3]);
  c.beginPath(); c.moveTo(padL, zy); c.lineTo(w - padR, zy); c.stroke(); c.setLineDash([]);

  const fin = EQ[EQ.length - 1].balance;
  const col = fin >= 0 ? '#22c55e' : '#ef4444';
  const grad = c.createLinearGradient(0, padT, 0, h - padB);
  grad.addColorStop(0, fin >= 0 ? 'rgba(34,197,94,.3)' : 'rgba(239,68,68,.3)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  c.beginPath(); c.moveTo(x(0), zy);
  EQ.forEach((e, i) => c.lineTo(x(i), y(e.balance)));
  c.lineTo(x(EQ.length - 1), zy); c.closePath(); c.fillStyle = grad; c.fill();
  c.beginPath(); c.strokeStyle = col; c.lineWidth = 1.8;
  EQ.forEach((e, i) => i ? c.lineTo(x(i), y(e.balance)) : c.moveTo(x(i), y(e.balance)));
  c.stroke();
}

const TEMPLATE = `"""Custom binary-options strategy.

Return "CALL" to BUY (price up) or "PUT" to SELL (price down).
Return None for no trade. The bot subscribes to required_timeframes.
"""


class Strategy:
    required_timeframes = [60]

    EMA_FAST = 5
    EMA_SLOW = 20

    def __init__(self):
        self.reset()

    def reset(self):
        self.candles = []
        self.last_ts = None
        self.no_trade_reason = "WARMUP"
        self.last_signal = None

    @staticmethod
    def _ema(values, period):
        if len(values) < period:
            return None
        ema = sum(values[:period]) / period
        k = 2.0 / (period + 1.0)
        for v in values[period:]:
            ema = v * k + ema * (1 - k)
        return ema

    def update_candle(self, timeframe, candle):
        if int(timeframe) != 60:
            return None

        ts = candle.get("timestamp") or candle.get("from")
        new_candle = ts != self.last_ts

        if new_candle:
            self.last_ts = ts
            self.candles.append(candle)
            self.candles = self.candles[-300:]
        else:
            self.candles[-1] = candle

        # only act on a freshly closed candle
        if not new_candle or len(self.candles) < self.EMA_SLOW + 2:
            self.no_trade_reason = "WARMUP"
            return None

        closes = [c["close"] for c in self.candles[:-1]]
        fast = self._ema(closes, self.EMA_FAST)
        slow = self._ema(closes, self.EMA_SLOW)
        prev = self._ema(closes[:-1], self.EMA_FAST)
        prev_slow = self._ema(closes[:-1], self.EMA_SLOW)

        if None in (fast, slow, prev, prev_slow):
            self.no_trade_reason = "EMA_NOT_READY"
            return None

        if prev <= prev_slow and fast > slow:
            self.no_trade_reason = None
            self.last_signal = "CALL"
            return "CALL"
        if prev >= prev_slow and fast < slow:
            self.no_trade_reason = None
            self.last_signal = "PUT"
            return "PUT"

        self.no_trade_reason = "NO_CROSS"
        return None

    def get_status(self):
        return {
            "candles": len(self.candles),
            "no_trade_reason": self.no_trade_reason,
            "last_signal": self.last_signal,
        }
`;

boot();
