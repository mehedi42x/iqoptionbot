/* IQ Bot Control Centre — browser application (same-origin API only). */
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);

const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));
const number = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};
const money = (value) => `${number(value) < 0 ? '-$' : '$'}${Math.abs(number(value)).toFixed(2)}`;
const hhmmss = (timestamp) => {
  const date = new Date(number(timestamp) * 1000);
  return Number.isNaN(date.getTime()) ? '—' : date.toISOString().slice(11, 19);
};
const priceText = (value) => {
  const parsed = number(value, NaN);
  if (!Number.isFinite(parsed)) return '—';
  return parsed.toFixed(Math.abs(parsed) < 10 ? 5 : 2);
};

async function api(path, body, method) {
  const options = {
    method: method || (body !== undefined ? 'POST' : 'GET'),
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
  };
  if (body !== undefined) options.body = JSON.stringify(body);

  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error('Network error. Check that the dashboard server is online.');
  }
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401) {
    window.location.assign('/login');
    throw new Error('Your dashboard session has expired.');
  }
  if (!response.ok) throw new Error(payload.error || payload.detail || response.statusText || 'Request failed.');
  return payload;
}

function showToast(message, kind = 'info') {
  const region = $('#toastRegion');
  if (!region) return;
  const toast = document.createElement('div');
  toast.className = `toast ${kind}`;
  toast.textContent = message;
  region.appendChild(toast);
  window.setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(6px)';
    window.setTimeout(() => toast.remove(), 180);
  }, 4200);
}

function setMessage(selector, text, kind = '') {
  const element = $(selector);
  element.textContent = text || '';
  element.className = `msg ${kind}`;
}

/* ------------------------------------------------------------------ */
/* Client state and navigation                                         */
/* ------------------------------------------------------------------ */
let STATE = {};
let CANDLES = [];
let MARKERS = [];
let ASSETS = [];
let EQUITY = [];
let socket;
let socketRetry;

function setTab(name) {
  const target = $(`#tab-${name}`);
  if (!target) return;
  $$('.nav-btn').forEach((button) => button.classList.toggle('active', button.dataset.tab === name));
  $$('.tab').forEach((tab) => tab.classList.toggle('active', tab === target));
  closeMenu();
  if (name === 'dashboard') requestAnimationFrame(drawChart);
  if (name === 'backtest' && EQUITY.length) requestAnimationFrame(drawEquity);
}

$$('.nav-btn').forEach((button) => {
  button.addEventListener('click', () => setTab(button.dataset.tab));
});
$$('[data-open-tab]').forEach((button) => {
  button.addEventListener('click', () => setTab(button.dataset.openTab));
});

function openMenu() {
  $('#sidebar').classList.add('open');
  $('#sidebarScrim').classList.add('visible');
  $('#menuToggle').setAttribute('aria-expanded', 'true');
}
function closeMenu() {
  $('#sidebar').classList.remove('open');
  $('#sidebarScrim').classList.remove('visible');
  $('#menuToggle')?.setAttribute('aria-expanded', 'false');
}
$('#menuToggle')?.addEventListener('click', () => {
  $('#sidebar').classList.contains('open') ? closeMenu() : openMenu();
});
$('#sidebarScrim')?.addEventListener('click', closeMenu);

/* ------------------------------------------------------------------ */
/* Candlestick chart                                                   */
/* ------------------------------------------------------------------ */
const chartCanvas = $('#chart');

function fitCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = Math.floor(rect.width);
  const height = Math.floor(rect.height);
  if (width < 2 || height < 2) return null;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  const context = canvas.getContext('2d');
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { width, height, context };
}

function drawChart() {
  const fitted = fitCanvas(chartCanvas);
  if (!fitted) return;
  const { width: w, height: h, context: c } = fitted;
  c.clearRect(0, 0, w, h);
  c.fillStyle = '#07101d';
  c.fillRect(0, 0, w, h);

  if (!CANDLES.length) {
    c.fillStyle = '#7087a5';
    c.font = '12px system-ui, sans-serif';
    c.textAlign = 'center';
    c.fillText('Waiting for live candles', w / 2, h / 2 - 5);
    c.fillStyle = '#4d6685';
    c.font = '10px system-ui, sans-serif';
    c.fillText('Connect your broker account and select a market.', w / 2, h / 2 + 15);
    c.textAlign = 'left';
    return;
  }

  const padLeft = 9;
  const padRight = w < 440 ? 57 : 67;
  const padTop = 12;
  const padBottom = 25;
  const maxBars = Math.max(20, Math.floor((w - padLeft - padRight) / (w < 440 ? 8 : 9)));
  const data = CANDLES.slice(-maxBars);
  let high = -Infinity;
  let low = Infinity;
  data.forEach((candle) => {
    high = Math.max(high, number(candle.high));
    low = Math.min(low, number(candle.low));
  });
  const rawRange = (high - low) || Math.abs(high * 0.0001) || 1;
  high += rawRange * 0.12;
  low -= rawRange * 0.12;

  const candleWidth = (w - padLeft - padRight) / data.length;
  const bodyWidth = Math.max(1.5, Math.min(10, candleWidth * 0.62));
  const x = (index) => padLeft + index * candleWidth + candleWidth / 2;
  const y = (price) => padTop + (high - price) / (high - low) * (h - padTop - padBottom);
  const decimals = high < 10 ? 5 : 2;

  c.strokeStyle = '#17304d';
  c.fillStyle = '#59728f';
  c.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
  c.lineWidth = 1;
  for (let i = 0; i <= 5; i += 1) {
    const price = low + (high - low) * i / 5;
    const lineY = Math.round(y(price)) + 0.5;
    c.beginPath(); c.moveTo(padLeft, lineY); c.lineTo(w - padRight, lineY); c.stroke();
    c.fillText(price.toFixed(decimals), w - padRight + 6, lineY + 3.5);
  }

  const timeStep = Math.max(1, Math.floor(data.length / (w < 440 ? 4 : 7)));
  for (let i = 0; i < data.length; i += timeStep) {
    c.fillText(hhmmss(data[i].timestamp).slice(0, 5), Math.max(padLeft, x(i) - 14), h - 8);
  }

  data.forEach((candle, index) => {
    const bullish = number(candle.close) >= number(candle.open);
    const live = index === data.length - 1;
    const colour = live ? '#f8bb4a' : (bullish ? '#41d88e' : '#ff6676');
    const centre = Math.round(x(index)) + 0.5;
    const openY = y(number(candle.open));
    const closeY = y(number(candle.close));
    c.strokeStyle = colour;
    c.fillStyle = colour;
    c.lineWidth = 1;
    c.beginPath(); c.moveTo(centre, y(number(candle.high))); c.lineTo(centre, y(number(candle.low))); c.stroke();
    c.fillRect(centre - bodyWidth / 2, Math.min(openY, closeY), bodyWidth, Math.max(1.2, Math.abs(closeY - openY)));
  });

  const last = number(data[data.length - 1].close);
  const lastY = Math.round(y(last)) + 0.5;
  c.setLineDash([4, 4]);
  c.strokeStyle = '#f8bb4a';
  c.beginPath(); c.moveTo(padLeft, lastY); c.lineTo(w - padRight, lastY); c.stroke();
  c.setLineDash([]);
  c.fillStyle = '#f8bb4a';
  c.fillRect(w - padRight + 2, lastY - 9, padRight - 4, 18);
  c.fillStyle = '#18200d';
  c.font = 'bold 9.5px ui-monospace, SFMono-Regular, Menlo, monospace';
  c.fillText(last.toFixed(decimals), w - padRight + 6, lastY + 3.5);

  const start = number(data[0].timestamp);
  const timeframe = number(STATE.chart_timeframe, 60);
  MARKERS.forEach((marker) => {
    if (marker.price === null || marker.price === undefined || number(marker.time) < start - timeframe) return;
    const index = (number(marker.time) - start) / timeframe;
    if (index < 0 || index > data.length) return;
    const markerX = padLeft + index * candleWidth + candleWidth / 2;
    const markerY = y(number(marker.price));
    const isCall = marker.direction === 'call';
    let colour = isCall ? '#41d88e' : '#ff6676';
    if (marker.status === 'win') colour = '#4ed8d0';
    if (marker.status === 'loss') colour = '#ad8bff';
    const orientation = isCall ? 1 : -1;
    c.fillStyle = colour; c.strokeStyle = colour; c.lineWidth = 1.4;
    c.beginPath();
    c.moveTo(markerX, markerY);
    c.lineTo(markerX - 5.5, markerY + 10 * orientation);
    c.lineTo(markerX + 5.5, markerY + 10 * orientation);
    c.closePath(); c.fill();
    c.beginPath(); c.arc(markerX, markerY, 3, 0, Math.PI * 2); c.fill();
    if (w > 420) {
      c.setLineDash([2, 3]); c.beginPath(); c.moveTo(markerX, markerY); c.lineTo(markerX, markerY + 22 * orientation); c.stroke(); c.setLineDash([]);
      c.font = 'bold 8.5px system-ui, sans-serif'; c.fillText(isCall ? 'CALL' : 'PUT', markerX - 11, markerY + (orientation * 30));
    }
  });
}

/* ------------------------------------------------------------------ */
/* Dashboard rendering                                                 */
/* ------------------------------------------------------------------ */
function renderState(state) {
  STATE = state || {};
  const connected = Boolean(STATE.connected);
  $('#connDot').className = `dot${connected ? ' on' : ''}`;
  $('#mobileConnDot').className = `dot${connected ? ' on' : ''}`;
  $('#connText').textContent = connected ? 'Connected' : 'Disconnected';
  $('#brandAsset').textContent = STATE.active_name || 'EURUSD';
  $('#mobileAsset').textContent = STATE.active_name || 'EURUSD';
  $('#chartAsset').textContent = STATE.active_name || 'EURUSD';

  $('#sBalance').textContent = `${money(STATE.balance)} ${STATE.currency || ''}`.trim();
  $('#sAcctType').textContent = `${String(STATE.account_type || 'practice').toLowerCase()} account`;
  const pnl = number(STATE.pnl);
  $('#sPnl').textContent = money(pnl);
  $('#sPnl').className = pnl > 0 ? 'g' : (pnl < 0 ? 'r' : '');
  $('#sTradesCount').textContent = `${(STATE.history || []).length} settled trade${(STATE.history || []).length === 1 ? '' : 's'}`;
  $('#sWr').textContent = `${number(STATE.winrate).toFixed(2).replace(/\.00$/, '')}%`;
  $('#sWl').textContent = `${number(STATE.wins)}W / ${number(STATE.losses)}L / ${number(STATE.draws)}D`;
  $('#sOpen').textContent = number(STATE.active_trades);
  $('#sMax').textContent = `max ${number(STATE.max_concurrent_trades, 1)} concurrent`;
  $('#sStrat').textContent = STATE.strategy || 'None';
  $('#sTf').textContent = (STATE.timeframes || []).length ? (STATE.timeframes || []).map((timeframe) => `${timeframe}s`).join(' · ') : 'Select a strategy to start';
  $('#sEmail').textContent = STATE.email ? String(STATE.email).split('@')[0] : '—';
  $('#sUid').textContent = STATE.user_id ? `UID ${STATE.user_id}` : 'Not connected';

  const autoPill = $('#pillAuto');
  autoPill.innerHTML = `<span class="pill-dot"></span>${STATE.auto_trading ? 'AUTO ON' : 'AUTO OFF'}`;
  autoPill.className = `pill${STATE.auto_trading ? ' on' : ''}`;
  const accountPill = $('#pillAcct');
  accountPill.textContent = STATE.account_type || 'PRACTICE';
  accountPill.className = `pill ${STATE.account_type === 'REAL' ? 'real' : 'pill-practice'}`;

  $('#autoToggle').checked = Boolean(STATE.auto_trading);
  $('#autoStateText').textContent = STATE.auto_trading ? 'Enabled — strategy may execute trades' : 'Disabled';
  $('#aConn').textContent = connected ? 'Connected' : 'Offline';
  $('#aBalId').textContent = STATE.balance ? `${STATE.currency || 'USD'} ${number(STATE.balance).toFixed(2)}` : '—';
  $('#aUserId').textContent = STATE.user_id || '—';
  $('#aTfs').textContent = (STATE.timeframes || []).length ? STATE.timeframes.map((timeframe) => `${timeframe}s`).join(', ') : '—';
  $('#openPositionBadge').textContent = `${number(STATE.active_trades)} active`;

  const notice = $('#connectionNotice');
  notice.classList.toggle('connected', connected);
  const noticeText = notice.querySelector('span:nth-child(2)');
  if (noticeText) {
    noticeText.innerHTML = connected
      ? '<strong>Live connection active.</strong> Candles and account events are now streaming to this workspace.'
      : '<strong>Ready when you are.</strong> Connect your IQ Option practice account to begin streaming live candles.';
  }

  const status = STATE.strategy_status || {};
  const statusBox = $('#stratStatus');
  if (Object.keys(status).length) {
    statusBox.innerHTML = Object.entries(status).map(([key, value]) => {
      const formatted = typeof value === 'number' ? Number(value).toFixed(6).replace(/0+$/, '').replace(/\.$/, '') : String(value ?? '—');
      return `<span>${escapeHtml(key)}: <b>${escapeHtml(formatted)}</b></span>`;
    }).join('');
  } else {
    statusBox.innerHTML = '<span class="muted">No strategy loaded.</span>';
  }

  $$('#tfGroup button').forEach((button) => button.classList.toggle('active', number(button.dataset.tf) === number(STATE.chart_timeframe, 60)));
  renderOpen(STATE.open_trades || []);
  renderHistory(STATE.history || []);
}

function renderOpen(trades) {
  const table = $('#openTable tbody');
  if (!trades.length) {
    table.innerHTML = '<tr class="empty"><td colspan="7"><span class="empty-icon">◌</span>No open positions</td></tr>';
    return;
  }
  table.innerHTML = trades.map((trade) => {
    const floating = trade.floating === 'winning' ? 'g' : (trade.floating === 'losing' ? 'r' : 'y');
    const label = trade.floating === 'winning' ? 'WINNING' : (trade.floating === 'losing' ? 'LOSING' : 'FLAT');
    const direction = String(trade.direction || '').toLowerCase();
    return `<tr><td>${escapeHtml(trade.asset)}</td><td><span class="tag ${direction}">${escapeHtml(direction.toUpperCase())}</span></td><td>${money(trade.amount)}</td><td>${priceText(trade.entry_price)}</td><td>${priceText(trade.current_price)}</td><td>${trade.seconds_left !== null && trade.seconds_left !== undefined ? `${number(trade.seconds_left)}s` : '—'}</td><td class="${floating}">${label}</td></tr>`;
  }).join('');
}

function renderHistory(trades) {
  const table = $('#histTable tbody');
  if (!trades.length) {
    table.innerHTML = '<tr class="empty"><td colspan="8"><span class="empty-icon">◌</span>Your completed trades will appear here</td></tr>';
    return;
  }
  table.innerHTML = trades.slice().reverse().map((trade, index) => {
    const direction = String(trade.direction || '').toLowerCase();
    const result = String(trade.result || 'UNKNOWN').toLowerCase();
    const source = `${trade.source || 'manual'}${trade.strategy ? ` · ${trade.strategy}` : ''}`;
    const profit = number(trade.profit);
    return `<tr><td>${trades.length - index}</td><td>${hhmmss(trade.open_time)}</td><td>${escapeHtml(trade.asset)}</td><td><span class="tag ${direction}">${escapeHtml(direction.toUpperCase())}</span></td><td>${money(trade.amount)}</td><td>${escapeHtml(source)}</td><td><span class="tag ${result}">${escapeHtml(result.toUpperCase())}</span></td><td class="${profit > 0 ? 'g' : (profit < 0 ? 'r' : '')}">${money(profit)}</td></tr>`;
  }).join('');
}

function addLog(entry) {
  const box = $('#logBox');
  const shouldStick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  const row = document.createElement('div');
  const time = document.createElement('span');
  time.className = 't';
  time.textContent = new Date().toTimeString().slice(0, 8);
  const message = document.createElement('span');
  message.className = entry.level || 'info';
  message.textContent = entry.message || '';
  row.append(time, message);
  box.appendChild(row);
  while (box.childNodes.length > 400) box.removeChild(box.firstChild);
  if (shouldStick) box.scrollTop = box.scrollHeight;
}

/* ------------------------------------------------------------------ */
/* WebSocket event stream                                              */
/* ------------------------------------------------------------------ */
function connectStream() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${protocol}://${location.host}/ws`);
  socket.onmessage = (event) => {
    let payload;
    try { payload = JSON.parse(event.data); } catch { return; }
    const { type, data } = payload;
    if (type === 'state') renderState(data);
    else if (type === 'log') addLog(data);
    else if (type === 'candles_snapshot') {
      CANDLES = data.candles || [];
      MARKERS = data.markers || [];
      const last = CANDLES[CANDLES.length - 1];
      $('#chartPrice').textContent = last ? priceText(last.close) : 'Waiting for price';
      drawChart();
    } else if (type === 'candle') {
      const candle = data.candle;
      if (!candle) return;
      if (CANDLES.length && CANDLES[CANDLES.length - 1].timestamp === candle.timestamp) CANDLES[CANDLES.length - 1] = candle;
      else {
        CANDLES.push(candle);
        if (CANDLES.length > 500) CANDLES.shift();
      }
      $('#chartPrice').textContent = priceText(candle.close);
      drawChart();
    } else if (type === 'chart_reset') {
      CANDLES = [];
      MARKERS = [];
      $('#chartPrice').textContent = 'Loading chart…';
      drawChart();
    } else if (type === 'trade_open') {
      if (data.entry_price !== null && data.entry_price !== undefined) {
        MARKERS = MARKERS.filter((marker) => marker.id !== data.id);
        MARKERS.push({ id: data.id, time: data.open_time, price: data.entry_price, direction: data.direction, status: 'open' });
        drawChart();
      }
    } else if (type === 'trade_close') {
      const marker = MARKERS.find((item) => item.id === data.id);
      if (marker) { marker.status = String(data.result || '').toLowerCase(); drawChart(); }
    } else if (type === 'trades_tick') {
      renderOpen(data.open || []);
    } else if (type === 'strategy_status') {
      STATE.strategy_status = data || {};
      renderState(STATE);
    }
  };
  socket.onclose = (event) => {
    socket = undefined;
    if (event.code === 1008) {
      window.location.assign('/login');
      return;
    }
    window.clearTimeout(socketRetry);
    socketRetry = window.setTimeout(connectStream, 2500);
  };
}

/* ------------------------------------------------------------------ */
/* Initial data                                                        */
/* ------------------------------------------------------------------ */
function optionMarkup(list) {
  const groups = {};
  list.forEach((asset) => { (groups[asset.group] ||= []).push(asset); });
  return Object.entries(groups).map(([group, assets]) => `<optgroup label="${escapeHtml(group)}">${assets.map((asset) => `<option value="${number(asset.id)}">${escapeHtml(asset.name)}</option>`).join('')}</optgroup>`).join('');
}

function setSelectValue(selector, value) {
  const element = $(selector);
  const desired = String(value ?? '');
  if ([...element.options].some((option) => option.value === desired)) element.value = desired;
}

async function loadStrategies() {
  const list = await api('/api/strategies');
  const markup = list.map((strategy) => `<option value="${escapeHtml(strategy.id)}">${escapeHtml(strategy.name)}${strategy.builtin ? '' : ' · Custom'}</option>`).join('');
  ['#tStrategy', '#sSelect', '#bStrategy'].forEach((selector) => {
    const select = $(selector);
    const current = select.value;
    select.innerHTML = markup || '<option value="">No strategies found</option>';
    if (current && list.some((strategy) => strategy.id === current)) select.value = current;
  });
  if (STATE.strategy) {
    const active = list.find((strategy) => strategy.id === STATE.strategy || strategy.id === `user:${STATE.strategy}.py`);
    if (active) $('#tStrategy').value = active.id;
  }
}

async function loadDatasets() {
  const list = await api('/api/datasets');
  $('#bDataset').innerHTML = list.length
    ? list.map((dataset) => `<option value="${escapeHtml(dataset.file)}">${escapeHtml(dataset.file)} · ${number(dataset.rows).toLocaleString()} candles · ${number(dataset.timeframe)}s</option>`).join('')
    : '<option value="">No local datasets found</option>';
}

async function boot() {
  try {
    ASSETS = await api('/api/assets');
    const options = optionMarkup(ASSETS);
    $('#tAsset').innerHTML = options;
    $('#aAsset').innerHTML = options;

    const state = await api('/api/state');
    renderState(state);
    $('#aEmail').value = state.email || '';
    setSelectValue('#aAcctType', state.account_type || 'PRACTICE');
    setSelectValue('#aTradeType', state.trade_type || 'turbo');
    setSelectValue('#tTradeType', state.trade_type || 'turbo');
    setSelectValue('#aAsset', state.active_id);
    setSelectValue('#tAsset', state.active_id);
    $('#aAmount').value = number(state.amount, 1);
    $('#tAmount').value = number(state.amount, 1);
    $('#aExp').value = number(state.expiration, 60);
    setSelectValue('#tExp', state.expiration);
    $('#aMaxConc').value = number(state.max_concurrent_trades, 1);
    $('#tMaxConc').value = number(state.max_concurrent_trades, 1);

    await Promise.all([loadStrategies(), loadDatasets()]);
    connectStream();
    drawChart();
  } catch (error) {
    console.error(error);
    showToast(error.message || 'The dashboard could not load.', 'error');
  }
}

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */
$('#btnConnect').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = 'Connecting…';
  try {
    await api('/api/connect', {});
    showToast('Connection request sent. Watch the live log for status.', 'info');
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    window.setTimeout(() => { button.disabled = false; button.textContent = 'Connect'; }, 1600);
  }
});

$('#btnDisconnect').addEventListener('click', async () => {
  try { await api('/api/disconnect', {}); showToast('Broker connection closed.', 'warning'); }
  catch (error) { showToast(error.message, 'error'); }
});

$('#btnResetStats').addEventListener('click', async () => {
  if (!window.confirm('Reset the current session statistics and trade history?')) return;
  try { await api('/api/reset-stats', {}); showToast('Session statistics reset.', 'success'); }
  catch (error) { showToast(error.message, 'error'); }
});

$('#tfGroup').addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-tf]');
  if (!button) return;
  $$('#tfGroup button').forEach((item) => item.classList.toggle('active', item === button));
  CANDLES = [];
  $('#chartPrice').textContent = 'Loading chart…';
  drawChart();
  try { await api('/api/chart-timeframe', { timeframe: number(button.dataset.tf) }); }
  catch (error) { showToast(error.message, 'error'); }
});

async function selectAsset(activeId) {
  try {
    await api('/api/asset', { active_id: number(activeId) });
    setSelectValue('#tAsset', activeId);
    setSelectValue('#aAsset', activeId);
    showToast('Market changed. Loading fresh chart data.', 'success');
  } catch (error) { showToast(error.message, 'error'); }
}
$('#tAsset').addEventListener('change', (event) => selectAsset(event.target.value));
$('#aAsset').addEventListener('change', (event) => selectAsset(event.target.value));

async function placeTrade(direction) {
  const amount = number($('#tAmount').value, 0);
  const expiration = number($('#tExp').value, 0);
  if (amount <= 0 || expiration <= 0) { showToast('Enter a valid stake and expiration.', 'warning'); return; }
  if (STATE.account_type === 'REAL' && !window.confirm(`Submit a REAL ${direction.toUpperCase()} order for ${money(amount)}?`)) return;
  try {
    await api('/api/trade', { direction, amount, expiration });
    showToast(`${direction.toUpperCase()} order submitted for ${money(amount)}.`, 'success');
  } catch (error) { showToast(error.message, 'error'); }
}
$('#btnCall').addEventListener('click', () => placeTrade('call'));
$('#btnPut').addEventListener('click', () => placeTrade('put'));

$('#autoToggle').addEventListener('change', async (event) => {
  const enabled = event.target.checked;
  if (enabled && STATE.account_type === 'REAL' && !window.confirm('Enable auto trading on a REAL account? Every valid signal can submit a live order.')) {
    event.target.checked = false;
    return;
  }
  try {
    await api('/api/auto', { enabled });
    showToast(enabled ? 'Auto trading enabled.' : 'Auto trading disabled.', enabled ? 'success' : 'warning');
  } catch (error) {
    event.target.checked = false;
    showToast(error.message, 'error');
  }
});

$('#btnLoadStratTrading').addEventListener('click', async () => {
  const strategy = $('#tStrategy').value;
  if (!strategy) { showToast('Select a strategy first.', 'warning'); return; }
  try {
    const result = await api('/api/strategy/load', { name: strategy });
    await loadStrategies();
    showToast(`Strategy loaded (${result.timeframes.join(', ')}s).`, 'success');
  } catch (error) { showToast(error.message, 'error'); }
});

$('#btnApplyTrading').addEventListener('click', async () => {
  try {
    await api('/api/account', {
      max_concurrent_trades: number($('#tMaxConc').value),
      trade_type: $('#tTradeType').value,
      amount: number($('#tAmount').value),
      expiration: number($('#tExp').value),
    });
    setSelectValue('#aTradeType', $('#tTradeType').value);
    $('#aAmount').value = $('#tAmount').value;
    $('#aExp').value = $('#tExp').value;
    $('#aMaxConc').value = $('#tMaxConc').value;
    showToast('Execution settings applied.', 'success');
  } catch (error) { showToast(error.message, 'error'); }
});

/* Strategy editor */
$('#btnOpenStrat').addEventListener('click', async () => {
  const strategy = $('#sSelect').value;
  if (!strategy) return;
  try {
    const result = await api(`/api/strategy-source?id=${encodeURIComponent(strategy)}`);
    $('#sCode').value = result.code;
    $('#sFilename').value = strategy.startsWith('user:') ? strategy.slice(5) : `${strategy}_copy.py`;
    setMessage('#sMsg', `Loaded ${strategy}. Save under a new filename to create a custom version.`, 'ok');
  } catch (error) { setMessage('#sMsg', error.message, 'err'); }
});

$('#btnNewStrat').addEventListener('click', () => {
  $('#sFilename').value = 'my_strategy.py';
  $('#sCode').value = TEMPLATE;
  setMessage('#sMsg', 'New strategy template ready. Edit it and save to validate.', 'ok');
});

async function saveEditorStrategy() {
  return api('/api/strategy/save', { filename: $('#sFilename').value.trim(), code: $('#sCode').value });
}

$('#btnSaveStrat').addEventListener('click', async () => {
  try {
    const result = await saveEditorStrategy();
    setMessage('#sMsg', `Saved and validated. Required timeframes: ${result.timeframes.join(', ')}s.`, 'ok');
    await loadStrategies();
    ['#sSelect', '#tStrategy', '#bStrategy'].forEach((selector) => setSelectValue(selector, result.id));
    showToast('Strategy saved and validated.', 'success');
  } catch (error) { setMessage('#sMsg', error.message, 'err'); }
});

$('#btnActivateStrat').addEventListener('click', async () => {
  try {
    const saved = await saveEditorStrategy();
    const result = await api('/api/strategy/load', { name: saved.id });
    await loadStrategies();
    ['#sSelect', '#tStrategy', '#bStrategy'].forEach((selector) => setSelectValue(selector, saved.id));
    setMessage('#sMsg', `Strategy is live (${result.timeframes.join(', ')}s). Enable auto trading only after reviewing the settings.`, 'ok');
    showToast('Strategy activated for live signals.', 'success');
  } catch (error) { setMessage('#sMsg', error.message, 'err'); }
});

/* Account and defaults */
$('#btnSaveAccount').addEventListener('click', async () => {
  const body = {
    email: $('#aEmail').value.trim(),
    account_type: $('#aAcctType').value,
    trade_type: $('#aTradeType').value,
    remember: $('#aRemember').checked,
  };
  if ($('#aPassword').value) body.password = $('#aPassword').value;
  try {
    await api('/api/account', body);
    $('#aPassword').value = '';
    setSelectValue('#tTradeType', body.trade_type);
    showToast(body.remember ? 'Account settings saved.' : 'Account settings applied for this session only.', 'success');
  } catch (error) { showToast(error.message, 'error'); }
});

$('#btnSaveDefaults').addEventListener('click', async () => {
  try {
    await api('/api/account', {
      active_id: number($('#aAsset').value),
      amount: number($('#aAmount').value),
      expiration: number($('#aExp').value),
      max_concurrent_trades: number($('#aMaxConc').value),
      remember: $('#aRemember').checked,
    });
    $('#tAmount').value = $('#aAmount').value;
    setSelectValue('#tExp', $('#aExp').value);
    $('#tMaxConc').value = $('#aMaxConc').value;
    showToast('Default trade parameters saved.', 'success');
  } catch (error) { showToast(error.message, 'error'); }
});

/* Backtest */
$('#btnRunBt').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  if (!$('#bStrategy').value || !$('#bDataset').value) { setMessage('#btMsg', 'Choose both a strategy and a dataset.', 'err'); return; }
  button.disabled = true;
  button.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 6v6l4 2"/><circle cx="12" cy="12" r="8"/></svg>Running simulation…';
  setMessage('#btMsg', '');
  try {
    const result = await api('/api/backtest', {
      strategy: $('#bStrategy').value,
      dataset: $('#bDataset').value,
      expiration: number($('#bExp').value),
      payout: number($('#bPayout').value) / 100,
      stake: number($('#bStake').value),
      start: $('#bStart').value || null,
      end: $('#bEnd').value || null,
    });
    renderBacktest(result);
    showToast(`Backtest complete: ${result.trades} trades analysed.`, 'success');
  } catch (error) { setMessage('#btMsg', error.message, 'err'); }
  finally {
    button.disabled = false;
    button.innerHTML = '<svg viewBox="0 0 24 24"><path d="m8 5 10 7-10 7V5Z"/></svg>Run backtest';
  }
});

function renderBacktest(result) {
  $('#btResult').classList.remove('hidden');
  $('#bTrades').textContent = number(result.trades).toLocaleString();
  $('#bRange').textContent = `${result.range || 'Selected range'} · ${number(result.candles).toLocaleString()} candles`;
  $('#bWr').textContent = `${number(result.winrate).toFixed(2).replace(/\.00$/, '')}%`;
  $('#bWr').className = number(result.winrate) >= number(result.breakeven_winrate) ? 'g' : 'r';
  $('#bBe').textContent = `Breakeven ${number(result.breakeven_winrate).toFixed(2)}%`;
  $('#bPnl').textContent = money(result.pnl);
  $('#bPnl').className = number(result.pnl) >= 0 ? 'g' : 'r';
  $('#bRoi').textContent = `ROI ${number(result.roi).toFixed(2)}%`;
  $('#bDd').textContent = money(result.max_drawdown);
  $('#bStreak').textContent = `Best ${number(result.best_win_streak)}W · Worst ${number(result.worst_loss_streak)}L`;

  $('#hourTable tbody').innerHTML = (result.hourly || []).map((hour) => `<tr><td>${String(number(hour.hour)).padStart(2, '0')}:00</td><td>${number(hour.trades)}</td><td class="g">${number(hour.wins)}</td><td class="r">${number(hour.losses)}</td><td class="${number(hour.winrate) >= number(result.breakeven_winrate) ? 'g' : 'r'}">${number(hour.winrate).toFixed(2)}%</td></tr>`).join('') || '<tr class="empty"><td colspan="5">No data in this range</td></tr>';
  $('#reasonTable tbody').innerHTML = (result.top_reasons || []).map(([reason, count]) => `<tr><td>${escapeHtml(reason)}</td><td>${number(count)}</td></tr>`).join('') || '<tr class="empty"><td colspan="2">No no-trade reasons recorded</td></tr>';
  $('#btTable tbody').innerHTML = (result.trade_list || []).slice().reverse().map((trade) => {
    const direction = String(trade.direction || '').toLowerCase();
    const outcome = String(trade.result || '').toLowerCase();
    const profit = number(trade.profit);
    return `<tr><td>${number(trade.n)}</td><td>${escapeHtml(trade.entry_dt)}</td><td><span class="tag ${direction}">${escapeHtml(direction.toUpperCase())}</span></td><td>${priceText(trade.entry_price)}</td><td>${priceText(trade.expiry_price)}</td><td><span class="tag ${outcome}">${escapeHtml(outcome.toUpperCase())}</span></td><td class="${profit > 0 ? 'g' : (profit < 0 ? 'r' : '')}">${money(profit)}</td><td>${money(trade.balance)}</td></tr>`;
  }).join('') || '<tr class="empty"><td colspan="8">No completed trades in this range</td></tr>';

  EQUITY = result.equity || [];
  requestAnimationFrame(drawEquity);
  setMessage('#btMsg', `Done — ${number(result.trades)} trades simulated on ${result.dataset}.`, 'ok');
}

function drawEquity() {
  const canvas = $('#eqChart');
  if (!canvas || !EQUITY.length) return;
  const fitted = fitCanvas(canvas);
  if (!fitted) return;
  const { width: w, height: h, context: c } = fitted;
  c.clearRect(0, 0, w, h);
  c.fillStyle = '#07101d'; c.fillRect(0, 0, w, h);
  const padLeft = 54; const padRight = 12; const padTop = 12; const padBottom = 22;
  let high = Math.max(...EQUITY.map((point) => number(point.balance)), 0);
  let low = Math.min(...EQUITY.map((point) => number(point.balance)), 0);
  const range = (high - low) || 1;
  high += range * .1; low -= range * .1;
  const x = (index) => padLeft + index / Math.max(1, EQUITY.length - 1) * (w - padLeft - padRight);
  const y = (value) => padTop + (high - value) / (high - low) * (h - padTop - padBottom);
  c.strokeStyle = '#17304d'; c.fillStyle = '#59728f'; c.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
  for (let i = 0; i <= 4; i += 1) {
    const value = low + (high - low) * i / 4;
    const lineY = Math.round(y(value)) + .5;
    c.beginPath(); c.moveTo(padLeft, lineY); c.lineTo(w - padRight, lineY); c.stroke();
    c.fillText(`$${value.toFixed(0)}`, 5, lineY + 3.5);
  }
  const zero = Math.round(y(0)) + .5;
  c.setLineDash([3, 3]); c.strokeStyle = '#53708f'; c.beginPath(); c.moveTo(padLeft, zero); c.lineTo(w - padRight, zero); c.stroke(); c.setLineDash([]);
  const finalBalance = number(EQUITY[EQUITY.length - 1].balance);
  const colour = finalBalance >= 0 ? '#41d88e' : '#ff6676';
  const gradient = c.createLinearGradient(0, padTop, 0, h - padBottom);
  gradient.addColorStop(0, finalBalance >= 0 ? 'rgba(65, 216, 142, .26)' : 'rgba(255, 102, 118, .26)');
  gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
  c.beginPath(); c.moveTo(x(0), zero);
  EQUITY.forEach((point, index) => c.lineTo(x(index), y(number(point.balance))));
  c.lineTo(x(EQUITY.length - 1), zero); c.closePath(); c.fillStyle = gradient; c.fill();
  c.beginPath(); c.strokeStyle = colour; c.lineWidth = 1.8;
  EQUITY.forEach((point, index) => index ? c.lineTo(x(index), y(number(point.balance))) : c.moveTo(x(index), y(number(point.balance))));
  c.stroke();
}

window.addEventListener('resize', () => { drawChart(); drawEquity(); });

const TEMPLATE = `"""Custom binary-options strategy.

Return "CALL" to buy or "PUT" to sell. Return None when there is no trade.
The engine calls update_candle for every required timeframe.
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
        for value in values[period:]:
            ema = value * k + ema * (1 - k)
        return ema

    def update_candle(self, timeframe, candle):
        if int(timeframe) != 60:
            return None

        timestamp = candle.get("timestamp") or candle.get("from")
        is_new_candle = timestamp != self.last_ts
        if is_new_candle:
            self.last_ts = timestamp
            self.candles.append(candle)
            self.candles = self.candles[-300:]
        elif self.candles:
            self.candles[-1] = candle

        # Act only when a fresh candle arrives; the previous one is closed.
        if not is_new_candle or len(self.candles) < self.EMA_SLOW + 2:
            self.no_trade_reason = "WARMUP"
            return None

        closes = [item["close"] for item in self.candles[:-1]]
        fast = self._ema(closes, self.EMA_FAST)
        slow = self._ema(closes, self.EMA_SLOW)
        previous_fast = self._ema(closes[:-1], self.EMA_FAST)
        previous_slow = self._ema(closes[:-1], self.EMA_SLOW)
        if None in (fast, slow, previous_fast, previous_slow):
            self.no_trade_reason = "EMA_NOT_READY"
            return None
        if previous_fast <= previous_slow and fast > slow:
            self.no_trade_reason = None
            self.last_signal = "CALL"
            return "CALL"
        if previous_fast >= previous_slow and fast < slow:
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
