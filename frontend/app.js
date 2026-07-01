'use strict';


// Custom confirm — replaces browser confirm()
let _confirmResolve = null;
function showConfirm(msg, yesLabel = 'Confirm', title = 'Are you sure?') {
  return new Promise(resolve => {
    _confirmResolve = resolve;
    document.getElementById('confirmMsg').textContent = msg;
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmYesBtn').textContent = yesLabel;
    document.getElementById('confirmModal').classList.add('open');
  });
}

function closeConfirm(result, e) {
  if (e && e.target !== document.getElementById('confirmModal')) return;
  if (_confirmResolve) { _confirmResolve(result); _confirmResolve = null; }
  document.getElementById('confirmModal').classList.remove('open');
}



const API = '/api/v1';
let toastedBudgetCats = new Set();
let authToken = localStorage.getItem('finos-token') || null;
let currentUser = JSON.parse(localStorage.getItem('finos-user') || 'null');

const CAT_COLORS = ['#6366F1','#10B981','#F59E0B','#3B82F6','#EC4899','#8B5CF6','#14B8A6','#F97316','#06B6D4'];
const CAT_ICONS = {
  food:'ti-tools-kitchen-2', groceries:'ti-shopping-cart', dining:'ti-tools-kitchen-2',
  transport:'ti-car', travel:'ti-plane', commute:'ti-bus',
  entertainment:'ti-device-tv', movies:'ti-movie', music:'ti-music',
  shopping:'ti-shopping-bag', clothing:'ti-shirt', fashion:'ti-hanger',
  housing:'ti-home', rent:'ti-home', utilities:'ti-bolt',
  health:'ti-heart-rate-monitor', medical:'ti-stethoscope', gym:'ti-barbell',
  salary:'ti-cash', freelance:'ti-briefcase', income:'ti-trending-up',
  education:'ti-school', books:'ti-book',
  savings:'ti-piggy-bank', investment:'ti-chart-line',
  insurance:'ti-shield', subscriptions:'ti-refresh',
  default:'ti-tag'
};
const CAT_BG_COLORS = [
  'rgba(99,102,241,0.15)','rgba(16,185,129,0.15)','rgba(245,158,11,0.15)',
  'rgba(59,130,246,0.15)','rgba(236,72,153,0.15)','rgba(139,92,246,0.15)',
  'rgba(20,184,166,0.15)','rgba(249,115,22,0.15)','rgba(6,182,212,0.15)'
];

function getCatIcon(name) {
  const lower = (name||'').toLowerCase();
  for (const [key, icon] of Object.entries(CAT_ICONS)) {
    if (lower.includes(key)) return icon;
  }
  return CAT_ICONS.default;
}

let currentPage = 'dashboard';
let currentPeriod = 'weekly';
let chartTypes = { line:'both', donut:'expense', bar:'both' };
let txnPage = 1, txnTotalPages = null;
const TXN_LIMIT = 20;
let chartLine = null, chartDonut = null, chartBar = null;
let chatHistory = [], addTxnType = 'expense';

// ── INIT ──
document.addEventListener('DOMContentLoaded', async () => {
  restoreTheme(); updateThemeUI();
  restoreSidebar();
  await checkAuth();
});

// ── AUTH ──
async function checkAuth() {
  if (authToken) {
    try {
      const r = await fetch(`${API}/auth/me`, { headers: authHdr() });
      if (r.ok) {
        currentUser = await r.json();
        localStorage.setItem('finos-user', JSON.stringify(currentUser));
        showApp();
        return;
      }
    } catch(e) {}
  }
  showAuthScreen();
}

function showAuthScreen() {
  document.getElementById('authScreen').style.display = 'flex';
  document.getElementById('appShell').style.display = 'none';
}

function showApp() {
  document.getElementById('authScreen').style.display = 'none';
  document.getElementById('appShell').style.display = 'flex';
  updateUserUI();
  setToday();
  loadCategories();
  loadDashboard();
}

function updateUserUI() {
  if (!currentUser) return;
  const name = currentUser.username || '?';
  const initial = name.charAt(0).toUpperCase();
  setEl('userName', name);
  setEl('userAv', initial);
  setEl('welcomeName', name.split(' ')[0]);
}

// Auth tab switcher
function switchAuthTab(tab) {
  const isLogin = tab === 'login';
  document.getElementById('formLogin').style.display = isLogin ? 'block' : 'none';
  document.getElementById('formSignup').style.display = isLogin ? 'none' : 'block';
  document.getElementById('tabLogin').classList.toggle('active', isLogin);
  document.getElementById('tabSignup').classList.toggle('active', !isLogin);
  document.getElementById('loginErr').textContent = '';
  document.getElementById('signupErr').textContent = '';
}

function togglePw(inputId, btn) {
  const input = document.getElementById(inputId);
  const showing = input.type === 'text';
  input.type = showing ? 'password' : 'text';
  btn.querySelector('i').className = showing ? 'ti ti-eye' : 'ti ti-eye-off';
}

function calcPwStrength(pw) {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (score <= 1) return { label: 'Weak', colorVar: '--red', pct: 25 };
  if (score === 2) return { label: 'Fair', colorVar: '--amber', pct: 50 };
  if (score === 3) return { label: 'Good', colorVar: '--cyan', pct: 75 };
  return { label: 'Strong', colorVar: '--green', pct: 100 };
}

function updatePwStrength(inputId, fillId, labelId, wrapId) {
  const pw = document.getElementById(inputId).value;
  const wrap = document.getElementById(wrapId);
  const fill = document.getElementById(fillId);
  const label = document.getElementById(labelId);
  if (!pw) { wrap.style.display = 'none'; return; }
  wrap.style.display = 'flex';
  const s = calcPwStrength(pw);
  fill.style.width = s.pct + '%';
  fill.style.background = `var(${s.colorVar})`;
  label.textContent = s.label;
  label.style.color = `var(${s.colorVar})`;
}

async function login() {
  const username = document.getElementById('loginUser').value.trim();
  const password = document.getElementById('loginPass').value;
  const errEl = document.getElementById('loginErr');
  const btn = document.getElementById('loginBtn');
  errEl.textContent = '';
  if (!username || !password) { errEl.textContent = 'Enter username and password'; return; }
  btn.disabled = true; btn.textContent = 'Logging in…';
  try {
    const r = await fetch(`${API}/auth/login`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username, password})
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.detail || 'Invalid credentials'; return; }
    authToken = d.token;
    localStorage.setItem('finos-token', authToken);
    // fetch user profile
    const me = await fetch(`${API}/auth/me`, { headers: authHdr() });
    currentUser = await me.json();
    localStorage.setItem('finos-user', JSON.stringify(currentUser));
    showApp();
  } catch(e) {
    errEl.textContent = 'Cannot connect to server';
  } finally {
    btn.disabled = false; btn.innerHTML = '<i class="ti ti-login"></i> Login';
  }
}

async function signup() {
  const username = document.getElementById('signupUser').value.trim();
  const password = document.getElementById('signupPass').value;
  const confirm  = document.getElementById('signupConfirm').value;
  const errEl    = document.getElementById('signupErr');
  const btn      = document.getElementById('signupBtn');
  errEl.textContent = '';
  if (!username || username.length < 5 || username.length > 30) { errEl.textContent = 'Username must be 5–30 characters'; return; }
  if (!password || password.length < 8) { errEl.textContent = 'Password must be at least 8 characters'; return; }
  if (password !== confirm) { errEl.textContent = 'Passwords do not match'; return; }
  btn.disabled = true; btn.textContent = 'Creating account…';
  try {
    const r = await fetch(`${API}/auth/signup`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username, password})
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.detail || 'Signup failed'; return; }
    // auto-login after signup
    authToken = d.token;
    localStorage.setItem('finos-token', authToken);
    const me = await fetch(`${API}/auth/me`, { headers: authHdr() });
    currentUser = await me.json();
    localStorage.setItem('finos-user', JSON.stringify(currentUser));
    showApp();
  } catch(e) {
    errEl.textContent = 'Cannot connect to server';
  } finally {
    btn.disabled = false; btn.innerHTML = '<i class="ti ti-user-plus"></i> Create Account';
  }
}

async function logout() {
  if (!await showConfirm('You will be returned to the login screen.', 'Sign Out', 'Sign out of FinOS?')) return;
  authToken = null; currentUser = null;
  localStorage.removeItem('finos-token');
  localStorage.removeItem('finos-user');
  chatHistory = [];
  if (chartLine) { chartLine.destroy(); chartLine = null; }
  if (chartDonut) { chartDonut.destroy(); chartDonut = null; }
  showAuthScreen();
  switchAuthTab('login');
  document.getElementById('loginUser').value = '';
  document.getElementById('loginPass').value = '';
}

async function changePassword() {
  const current = document.getElementById('cpCurrent').value;
  const next = document.getElementById('cpNew').value;
  const confirm = document.getElementById('cpConfirm').value;
  const errEl = document.getElementById('cpErr');
  const btn = document.getElementById('cpBtn');
  errEl.textContent = '';
  if (!current || !next) { errEl.textContent = 'Fill in all fields'; return; }
  if (next.length < 8) { errEl.textContent = 'New password must be at least 8 characters'; return; }
  if (next !== confirm) { errEl.textContent = 'New passwords do not match'; return; }
  btn.disabled = true; btn.textContent = 'Updating…';
  try {
    const r = await fetch(`${API}/auth/me/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHdr() },
      body: JSON.stringify({ current_password: current, new_password: next })
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.detail || 'Could not update password'; return; }
    document.getElementById('cpCurrent').value = '';
    document.getElementById('cpNew').value = '';
    document.getElementById('cpConfirm').value = '';
    document.getElementById('cpNewStrength').style.display = 'none';
    showToast('Password updated successfully');
  } catch (e) {
    errEl.textContent = 'Cannot connect to server';
  } finally {
    btn.disabled = false; btn.textContent = 'Update Password';
  }
}

// ── NAV ──
function go(page, el) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-'+page).classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  if (el) el.classList.add('active');
  document.getElementById('pageTitle').textContent =
    {dashboard:'Dashboard',add:'Add Transaction',transactions:'Transactions',budget:'Budget',export:'Export',settings:'Settings'}[page]||page;
  document.getElementById('periodTabs').style.display = page === 'dashboard' ? 'flex' : 'none';
  currentPage = page;
  if (page==='dashboard')    loadDashboard();
  if (page==='transactions') loadTxns();
  if (page==='budget')       loadBudget();
  if (page==='add')          setToday();
}

// ── PERIOD ──
function setPeriod(p, el) {
  currentPeriod = p;
  document.querySelectorAll('.ptab').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  loadDashboard();
}

// ── DASHBOARD ──
async function loadDashboard() {
  await Promise.all([loadMetrics(), loadLineChart(), loadBarChart(), loadCategoryBreakdown(), loadBudgetMini(), loadRecentTxns(), loadInsights(), loadForecast(), loadHealthScore()]);
}

async function loadMetrics() {
  try {
    const now = new Date();
    const month = ym(now), year = now.getFullYear(), today = now.toISOString().slice(0,10);
    let url = `${API}/analytics/summary?period=${currentPeriod}`;
    if (currentPeriod==='monthly') url += `&month=${month}`;
    if (currentPeriod==='yearly')  url += `&year=${year}`;
    const s = await apiFetch(url);
    if (s) {
      setEl('metricBalance', fmt(s.balance ?? ((s.income||0)-(s.expense||0))));
      setEl('metricIncome',  fmt(s.income||0));
      setEl('metricExpense', fmt(s.expense||0));
      const lbl = {weekly:'this week',monthly:'this month',yearly:'this year'}[currentPeriod];
      setEl('metricIncomeSub', lbl); setEl('metricExpenseSub', lbl);
    }
    const td = await apiFetch(`${API}/transactions/?limit=200&offset=0&date_from=${today}&date_to=${today}`);
    if (td) {
      const net = td.filter(t=>t.type==='income').reduce((a,t)=>a+t.amount,0)
                - td.filter(t=>t.type==='expense').reduce((a,t)=>a+t.amount,0);
      setEl('metricToday', fmt(net));
    }
  } catch(e) { console.error('metrics',e); }
}

// ── LINE CHART ──
async function loadLineChart() {
  try {
    const data = await apiFetch(`${API}/analytics/chart/line?period=${currentPeriod}&type=${chartTypes.line}`);
    if (!data) return renderLine([],{});
    renderLine(data.map(d=>d.label||d.date||d.month||''), { income:data.map(d=>d.income||0), expense:data.map(d=>d.expense||0) });
  } catch(e) { renderLine([],{}); }
}

function renderLine(labels, series) {
  const ctx = document.getElementById('chartLine').getContext('2d');
  if (chartLine) chartLine.destroy();
  const dark = document.documentElement.classList.contains('dark');

  function grad(col1, col2) {
    const g = ctx.createLinearGradient(0,0,0,220);
    g.addColorStop(0, col1); g.addColorStop(1, col2); return g;
  }

  const ds = [];
  const t = chartTypes.line;
  if (t!=='expense' && series.income) ds.push({
    label:'Income', data:series.income,
    borderColor:'#10B981', backgroundColor:grad('rgba(16,185,129,0.25)','rgba(16,185,129,0)'),
    borderWidth:2.5, pointRadius:3, pointHoverRadius:6, pointBackgroundColor:'#10B981',
    pointBorderColor: dark?'#161B26':'#fff', pointBorderWidth:2, fill:true, tension:0.45
  });
  if (t!=='income' && series.expense) ds.push({
    label:'Expense', data:series.expense,
    borderColor:'#6366F1', backgroundColor:grad('rgba(99,102,241,0.20)','rgba(99,102,241,0)'),
    borderWidth:2.5, pointRadius:3, pointHoverRadius:6, pointBackgroundColor:'#6366F1',
    pointBorderColor: dark?'#161B26':'#fff', pointBorderWidth:2, fill:true, tension:0.45
  });

  chartLine = new Chart(ctx, { type:'line', data:{labels,datasets:ds}, options: chartOpts('line', dark) });
}


// ── CATEGORY BREAKDOWN (donut + mini list share one fetch, one scope, one total) ──
async function loadCategoryBreakdown() {
  try {
    const now = new Date();
    let url = `${API}/analytics/breakdown?period=${currentPeriod}&type=${chartTypes.donut}`;
    if (currentPeriod==='monthly') url += `&month=${ym(now)}`;
    if (currentPeriod==='yearly')  url += `&year=${now.getFullYear()}`;
    const raw = await apiFetch(url) || [];
    const sorted = [...raw].sort((a,b)=>(b.total||0)-(a.total||0));
    const total = sorted.reduce((a,d)=>a+(d.total||0),0);
    renderDonut(sorted.map(d=>d.category), sorted.map(d=>d.total||0));
    renderCatMini(sorted.slice(0,5), total);
    updateScopeLabels();
  } catch(e) {
    renderDonut([],[]);
    document.getElementById('catMiniList').innerHTML = '<div style="font-size:12px;color:var(--t3)">No data</div>';
  }
}

function updateScopeLabels() {
  const lbl = {weekly:'this week',monthly:'this month',yearly:'this year'}[currentPeriod];
  setEl('catMiniScope', lbl);
  setEl('donutScope', lbl);
  setEl('barChartSub', currentPeriod==='yearly' ? 'Each bar = one month this year' : currentPeriod==='monthly' ? 'Each bar = one day this month' : 'Each bar = one day this week');
}

function renderDonut(labels, values) {
  const ctx = document.getElementById('chartDonut').getContext('2d');
  if (chartDonut) chartDonut.destroy();
  const total = values.reduce((a,b)=>a+b,0);
  setEl('donutTotal', fmt(total));
  const dark = document.documentElement.classList.contains('dark');

  chartDonut = new Chart(ctx, {
    type:'doughnut',
    data:{ labels, datasets:[{ data:values, backgroundColor:CAT_COLORS.slice(0,labels.length), borderWidth:3, borderColor:dark?'#161B26':'#fff', hoverOffset:8 }] },
    options:{ ...chartOpts('donut',dark), cutout:'72%', animation:{ animateRotate:true, duration:700, easing:'easeInOutQuart' } }
  });

  const leg = document.getElementById('donutLegend');
  const topTotal = values.reduce((a,b)=>a+b,0)||1;
  leg.innerHTML = labels.slice(0,5).map((l,i)=>`
    <div style="display:flex;align-items:center;gap:8px">
      <div style="width:8px;height:8px;border-radius:50%;background:${CAT_COLORS[i]};flex-shrink:0"></div>
      <span style="flex:1;font-size:12px;color:var(--t2)">${esc(l)}</span>
      <div style="width:80px;height:4px;background:var(--s3);border-radius:99px;overflow:hidden">
        <div style="height:100%;border-radius:99px;background:${CAT_COLORS[i]};width:${((values[i]/topTotal)*100).toFixed(0)}%"></div>
      </div>
      <span style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;color:var(--t2);min-width:30px;text-align:right">${((values[i]/topTotal)*100).toFixed(0)}%</span>
    </div>`).join('');
}


// ── BAR CHART (period breakdown) ──
async function loadBarChart() {
  try {
    const data = await apiFetch(`${API}/analytics/chart/bar?period=${currentPeriod}&type=${chartTypes.bar}`);
    if (!data) return renderBar([],{});
    renderBar(data.map(d=>d.label||d.date||d.month||''), { income:data.map(d=>d.income||0), expense:data.map(d=>d.expense||0) });
  } catch(e) { renderBar([],{}); }
}

function renderBar(labels, series) {
  const ctx = document.getElementById('chartBar').getContext('2d');
  if (chartBar) chartBar.destroy();
  const dark = document.documentElement.classList.contains('dark');
  const ds = [];
  const t = chartTypes.bar;
  if (t!=='expense' && series.income) ds.push({ label:'Income', data:series.income, backgroundColor:'#10B981', borderRadius:4, maxBarThickness:28 });
  if (t!=='income' && series.expense) ds.push({ label:'Expense', data:series.expense, backgroundColor:'#6366F1', borderRadius:4, maxBarThickness:28 });
  chartBar = new Chart(ctx, { type:'bar', data:{labels,datasets:ds}, options: chartOpts('bar', dark) });
}


// ── BUDGET MINI ──
async function loadBudgetMini() {
  try {
    const data = await apiFetch(`${API}/budget/status`);
    const el = document.getElementById('budgetMiniList');
    if (!data||!data.length) { el.innerHTML='<div style="font-size:12px;color:var(--t3)">No budgets set yet</div>'; return; }
    el.innerHTML = data.slice(0,3).map(b=>{
      const pct = Math.min((b.spent/b.monthly_limit)*100,100);
      const cls = pct>=100?'over':pct>=80?'warn':'';
      return `<div style="margin-bottom:12px">
        <div class="budget-mini-row">
          <span class="budget-mini-name">${esc(b.category)}</span>
          <span class="budget-mini-amt">${fmt(b.spent)} / ${fmt(b.monthly_limit)}</span>
        </div>
        <div class="bm-bar"><div class="bm-fill ${cls}" style="width:${pct}%"></div></div>
      </div>`;
    }).join('');
    checkBudgetAlerts(data);
  } catch(e) {}
}


function checkBudgetAlerts(data) {
  const triggered = data
    .filter(b => b.monthly_limit > 0)
    .map(b => ({ ...b, pct: (b.spent / b.monthly_limit) * 100 }))
    .filter(b => b.pct >= 80 && !toastedBudgetCats.has(b.category));
  if (!triggered.length) return;
  triggered.forEach(b => toastedBudgetCats.add(b.category));
  const worst = triggered.reduce((a, b) => b.pct > a.pct ? b : a);
  const over = worst.pct >= 100;
  const extra = triggered.length > 1 ? ` (+${triggered.length - 1} more)` : '';
  const msg = over
    ? `You've exceeded your ${worst.category} budget${extra}`
    : `You've used ${worst.pct.toFixed(0)}% of your ${worst.category} budget${extra}`;
  showToast(msg, over ? 'error' : 'info', () => go('budget', document.querySelector('[onclick*=budget]')));
}


function renderCatMini(top5, total) {
  const el = document.getElementById('catMiniList');
  if (!top5.length || !total) { el.innerHTML = '<div style="font-size:12px;color:var(--t3)">No data</div>'; return; }
  el.innerHTML = top5.map((d,i)=>`
    <div class="cat-mini-row">
      <div class="cat-mini-left">
        <div class="cat-dot" style="background:${CAT_COLORS[i]}"></div>
        <span class="cat-name">${esc(d.category)}</span>
      </div>
      <div class="cat-bar-wrap"><div class="cat-bar-fill" style="background:${CAT_COLORS[i]};width:${((d.total/total)*100).toFixed(0)}%"></div></div>
      <span class="cat-pct">${((d.total/total)*100).toFixed(0)}%</span>
    </div>`).join('');
}


// ── RECENT TXNS ──
async function loadRecentTxns() {
  try {
    const data = await apiFetch(`${API}/transactions/?limit=6&offset=0`);
    const tbody = document.getElementById('recentBody');
    if (!data||!data.length) { tbody.innerHTML='<tr><td colspan="4" class="tbl-empty">No transactions yet</td></tr>'; return; }
    tbody.innerHTML = data.map(t=>`
      <tr>
        <td style="font-size:12px;color:var(--t2)">${fmtDate(t.date)}</td>
        <td><span class="cat-pill"><i class="ti ${getCatIcon(t.category)}" style="font-size:12px"></i> ${esc(t.category)}</span></td>
        <td>${fmtDate(t.date)}</td>
        <td class="amt ${t.type==='income'?'pos':'neg'}">${t.type==='income'?'+':'-'}${fmt(t.amount)}</td>
      </tr>`).join('');
  } catch(e) {}
}

// ── CHART OPTIONS ──
function chartOpts(type, dark) {
  const tc = dark?'#3A4E66':'#A0B0CC';
  const lc = dark?'#7A8FA8':'#5A6A85';
  const gc = dark?'rgba(30,45,66,0.7)':'rgba(226,232,248,0.6)';
  const base = {
    responsive:true, maintainAspectRatio:false,
    plugins:{
      legend:{ display: type!=='donut', position:'top', align:'end',
        labels:{ color:lc, font:{family:'Outfit',size:11,weight:'600'}, boxWidth:10, boxHeight:10, borderRadius:3, useBorderRadius:true, padding:14 }
      },
      tooltip:{
        backgroundColor: dark?'#1C2333':'#fff',
        titleColor: dark?'#E8EDF5':'#0F172A',
        bodyColor: lc, borderColor: dark?'rgba(99,102,241,0.2)':'#E2E8F8',
        borderWidth:1, padding:12, cornerRadius:10, boxPadding:4,
        callbacks:{ label: c => ` ₹${Number(c.parsed.y??c.parsed).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}` }
      }
    },
    animation:{ duration:600, easing:'easeInOutQuart' }
  };
  if (type==='donut') return base;
  return { ...base, scales:{
    x:{ ticks:{color:tc,font:{family:'Outfit',size:10},maxRotation:0}, grid:{color:gc,drawBorder:false}, border:{display:false} },
    y:{ ticks:{color:tc,font:{family:'JetBrains Mono',size:10},callback:v=>'₹'+(v>=1000?(v/1000).toFixed(0)+'k':v),maxTicksLimit:6}, grid:{color:gc,drawBorder:false}, border:{display:false} }
  }};
}

function setChartType(chart, type, el) {
  chartTypes[chart] = type;
  el.closest('.type-pills,.tpill')?.parentElement?.querySelectorAll('.tpill').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  if (chart==='line') loadLineChart();
  if (chart==='bar') loadBarChart();
  if (chart==='donut') loadCategoryBreakdown();
}

// ── INSIGHTS ──
async function loadInsights() {
  try {
    const data = await apiFetch(`${API}/insights/`);
    const el = document.getElementById('insightsList');
    const cards = data?.insights || [];
    if (!cards.length) { el.innerHTML = '<div class="insights-empty">No notable patterns this month</div>'; return; }
    el.innerHTML = cards.map(c => `
      <div class="insight-card ${c.severity}">
        <div class="insight-icon"><i class="ti ${c.severity==='warning'?'ti-alert-triangle':'ti-bulb'}"></i></div>
        <div class="insight-msg">${esc(c.message)}</div>
      </div>`).join('');
  } catch(e) { console.error('insights', e); }
}


// ── FORECAST ──
async function loadForecast() {
  try {
    const data = await apiFetch(`${API}/analytics/forecast`);
    if (!data) return;
    setEl('forecastVal', fmt(data.forecast));
    const spent = data.current_month_spend_so_far || 0;
    const pct = data.forecast > 0 ? Math.min((spent / data.forecast) * 100, 100) : 0;
    const fill = document.getElementById('forecastFill');
    if (fill) {
      fill.style.width = pct + '%';
      fill.className = `forecast-progress-fill ${spent > data.forecast ? 'over' : ''}`;
    }
    setEl('forecastProgressLbl', `${fmt(spent)} so far`);
  } catch(e) { console.error('forecast', e); }
}


// ── HEALTH SCORE ──
async function loadHealthScore() {
  try {
    const d = await apiFetch(`${API}/analytics/health-score`);
    if (!d) return;
    _renderHealthCard('hsSavings', d.savings_rate, 'higher', d.months_available);
    _renderHealthCard('hsBudget', d.budget_adherence, 'lower', d.months_available);
    _renderHealthCard('hsIncome', d.income_stability, 'higher', d.months_available, true);
    _renderHealthCard('hsGrowth', d.expense_growth, 'lower', d.months_available, true);
  } catch(e) { console.error('health-score', e); }
}

function _renderHealthCard(id, value, direction, monthsAvailable, needsHistory=false) {
  const card = document.getElementById(id);
  const valEl = card.querySelector('.health-val');
  const fill = card.querySelector('.health-bar-fill');

  if (value === null || value === undefined) {
    card.classList.add('empty');
    valEl.textContent = needsHistory && monthsAvailable === 0
      ? 'Unlocks next month'
      : 'Not enough data';
    fill.style.width = '0%';
    return;
  }

  card.classList.remove('empty');
  valEl.textContent = value.toFixed(1) + '%';

  let cls;
  if (direction === 'higher') {
    cls = value >= 70 ? 'good' : value >= 40 ? 'warn' : 'bad';
  } else {
    cls = value <= 100 ? 'good' : value <= 120 ? 'warn' : 'bad';
  }
  fill.className = `health-bar-fill ${cls}`;
  fill.style.width = Math.min(value, 100) + '%';
}


// ── TRANSACTIONS PAGE ──
async function loadTxns() {
  try {
    const type = document.getElementById('filterType').value;
    const cat  = document.getElementById('filterCat').value.trim();
    const from = document.getElementById('filterFrom').value;
    const to   = document.getElementById('filterTo').value;
    const off  = (txnPage-1)*TXN_LIMIT;
    let url = `${API}/transactions/?limit=${TXN_LIMIT+1}&offset=${off}`;
    if (type) url+=`&type=${type}`;
    if (cat)  url+=`&category=${encodeURIComponent(cat)}`;
    if (from) url+=`&date_from=${from}`;
    if (to)   url+=`&date_to=${to}`;
    let data = await apiFetch(url);
    const tbody = document.getElementById('txnBody');
    if (!data||!data.length) { tbody.innerHTML='<tr><td colspan="6" class="tbl-empty">No transactions found</td></tr>'; document.getElementById('txnPagination').innerHTML=''; return; }
    const hasMore = data.length > TXN_LIMIT;
    if (hasMore) data = data.slice(0, TXN_LIMIT);
    tbody.innerHTML = data.map(t=>`
      <tr>
        <td style="font-size:12px;color:var(--t2);white-space:nowrap">${fmtDate(t.date)}</td>
        <td><span class="cat-pill"><i class="ti ${getCatIcon(t.category)}" style="font-size:12px"></i> ${esc(t.category)}</span></td>
        <td><span class="type-badge ${t.type}">${t.type}</span></td>
        <td style="font-size:12px;color:var(--t2)">${esc(t.note||'—')}</td>
        <td class="amt ${t.type==='income'?'pos':'neg'}">${t.type==='income'?'+':'-'}${fmt(t.amount)}</td>
        <td><button class="row-action" onclick="openEditModal(${JSON.stringify(t).replace(/"/g,'&quot;')})"><i class="ti ti-pencil"></i></button></td>
      </tr>`).join('');
    if (!hasMore) txnTotalPages=txnPage;
    const pg = document.getElementById('txnPagination');
    pg.innerHTML=`
      <button class="pag-btn" onclick="chgPage(-1)" ${txnPage===1?'disabled':''}><i class="ti ti-chevron-left"></i></button>
      <span style="font-size:12px;color:var(--t2);padding:0 12px">Page ${txnPage} of ${txnTotalPages??'?'}</span>
      <button class="pag-btn" onclick="chgPage(1)" ${!hasMore?'disabled':''}><i class="ti ti-chevron-right"></i></button>`;
  } catch(e) { console.error(e); }
}

function chgPage(d) { if (txnPage+d<1) return; txnPage+=d; loadTxns(); }

function clearFilters() {
  ['filterType','filterCat','filterFrom','filterTo'].forEach(id=>{const el=document.getElementById(id);if(el)el.value=''});
  txnPage=1; txnTotalPages=null; loadTxns();
}

// ── ADD TXN ──
function selType(type, el) {
  addTxnType = type;
  document.querySelectorAll('.tsel-pill').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  loadCategoriesByType(type);
}

function setToday() { const d=document.getElementById('addDate'); if(d) d.value=new Date().toISOString().slice(0,10); }

async function loadCategories() { await loadCategoriesByType('expense'); }

async function loadCategoriesByType(type) {
  try {
    const data = await apiFetch(`${API}/categories/?type=${type}`);
    const sel = document.getElementById('addCategory');
    if (!sel) return;
    sel.innerHTML='<option value="">Select category…</option>';
    (data||[]).forEach(c=>{ const o=document.createElement('option'); o.value=o.textContent=c.name; sel.appendChild(o); });
  } catch(e) {}
}

async function submitTxn() {
  const amount = parseFloat(document.getElementById('addAmount').value);
  const cat    = document.getElementById('addCategory').value;
  const date   = document.getElementById('addDate').value;
  const note   = document.getElementById('addNote').value.trim();
  const fb     = document.getElementById('addFb');
  if (!amount||amount<=0) return showFb(fb,'Enter a valid amount','err');
  if (!cat)               return showFb(fb,'Select a category','err');
  if (!date)              return showFb(fb,'Select a date','err');
  try {
    await apiPost(`${API}/transactions/`,{amount,category:cat,date,note,type:addTxnType});
    showFb(fb,'Transaction added!','ok');
    showToast('Transaction added','success');
    document.getElementById('addAmount').value='';
    document.getElementById('addNote').value='';
  } catch(e) { showFb(fb,e.message||'Failed','err'); }
}

// ── EDIT MODAL ──
async function openEditModal(t) {
  document.getElementById('editId').value = t.id;
  document.getElementById('editAmount').value = t.amount;
  document.getElementById('editType').value = t.type;
  document.getElementById('editDate').value = t.date;
  document.getElementById('editNote').value = t.note || '';
  await loadEditCategories(t.type, t.category);
  document.getElementById('editModal').classList.add('open');
}

async function loadEditCategories(type, selected) {
  try {
    const data = await apiFetch(`${API}/categories/?type=${type}`);
    const sel = document.getElementById('editCategory');
    sel.innerHTML = (data||[]).map(c => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join('');
    if (selected) sel.value = selected;
  } catch(e) {}
}

function closeModal(id, e) {
  if (e && e.target!==document.getElementById(id)) return;
  document.getElementById(id).classList.remove('open');
}

async function saveEdit() {
  const id=document.getElementById('editId').value;
  const amount=parseFloat(document.getElementById('editAmount').value);
  const type=document.getElementById('editType').value;
  const date=document.getElementById('editDate').value;
  const category=document.getElementById('editCategory').value;
  const note=document.getElementById('editNote').value;
  try { await apiPut(`${API}/transactions/${id}`,{amount,type,date,category,note}); closeModal('editModal'); showToast('Updated','success'); loadTxns(); }
  catch(e) { showToast(e.message||'Failed','error'); }
}

async function deleteTxn() {
  const id = document.getElementById('editId').value;
  if (!await showConfirm('This action cannot be undone.', 'Delete', 'Delete transaction?')) return;
  try { await apiDel(`${API}/transactions/${id}`); closeModal('editModal'); showToast('Deleted','info'); loadTxns(); }
  catch(e) { showToast(e.message||'Failed','error'); }
}

// ── BUDGET PAGE ──
async function loadBudget() {
  try {
    const [status, over, user] = await Promise.all([
      apiFetch(`${API}/budget/status`),
      apiFetch(`${API}/budget/overspend`),
      apiFetch(`${API}/auth/me`)
    ]);
    if (user) document.getElementById('incomeInput').value = user.monthly_income||'';
    renderBudgetHero(status);
    renderBudgetGrid(status);
    renderOverspend(over);
  } catch(e) { console.error(e); }
}

function renderBudgetHero(data) {
  if (!data||!data.length) return;
  const total = data.reduce((a,b)=>a+(b.monthly_limit||0),0);
  const spent = data.reduce((a,b)=>a+(b.spent||0),0);
  const pct   = total>0 ? Math.min((spent/total)*100,100) : 0;
  const days  = daysLeft();
  setEl('bhAmount', fmt(total));
  setEl('bhRemaining', `You have ${fmt(total-spent)} remaining for the next ${days} days`);
  setEl('bhPct', `${pct.toFixed(0)}% Used`);
  const fill = document.getElementById('bhBarFill');
  if (fill) fill.style.width = pct+'%';
}

function renderBudgetGrid(data) {
  const grid = document.getElementById('budgetGrid');
  if (!data||!data.length) {
    grid.innerHTML='<div style="grid-column:1/-1;text-align:center;padding:48px;color:var(--t3);font-size:13px">No budgets set yet. Click "+ Set Budget" to add one.</div>';
    return;
  }
  grid.innerHTML = data.map((b,i)=>{
    const pct = b.monthly_limit>0 ? Math.min((b.spent/b.monthly_limit)*100,100) : 0;
    const barCls = pct>=100?'over':pct>=80?'warn':'';
    const badgeCls = pct>=100?'pct-over':pct>=80?'pct-warn':'pct-ok';
    const icon = getCatIcon(b.category);
    const bg = CAT_BG_COLORS[i % CAT_BG_COLORS.length];
    const color = CAT_COLORS[i % CAT_COLORS.length];
    return `
      <div class="bcat-card">
        <div class="bcat-hd">
          <div class="bcat-hd-l">
            <div class="bcat-icon" style="background:${bg};color:${color}"><i class="ti ${icon}"></i></div>
            <div>
              <div class="bcat-name">${esc(b.category)}</div>
              <div class="bcat-type">Monthly limit</div>
            </div>
          </div>
          <button class="bcat-edit" onclick="openEditBudget('${esc(b.category)}',${b.monthly_limit})" title="Edit"><i class="ti ti-pencil"></i></button>
        </div>
        <div class="bcat-amounts">
          <span class="bcat-pct-badge ${badgeCls}" style="float:right;margin-top:2px">${pct.toFixed(0)}%</span>
          <span class="bcat-spent">${fmt(b.spent)}</span>
          <span class="bcat-limit"> / ${fmt(b.monthly_limit)}</span>
        </div>
        <div class="bcat-bar-track" style="margin-top:8px">
          <div class="bcat-bar-fill ${barCls}" style="width:${pct}%"></div>
        </div>
      </div>`;
  }).join('');
}

function renderOverspend(data) {
  const sec = document.getElementById('overspendSection');
  if (!data||!data.length) { sec.style.display='none'; return; }
  sec.style.display='block';
  document.getElementById('overspendList').innerHTML = data.map(b=>`
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--b)">
      <span style="font-size:13px;font-weight:600">${esc(b.category)}</span>
      <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--red)">${fmt(b.spent)} / ${fmt(b.monthly_limit)}</span>
    </div>`).join('');
}

function openBudgetModal() {
  document.getElementById('budgetModalTitle').textContent='Set Budget';
  document.getElementById('budgetCat').value='';
  document.getElementById('budgetLimit').value='';
  document.getElementById('budgetCat').removeAttribute('readonly');
  document.getElementById('budgetModal').classList.add('open');
}

function openEditBudget(cat, limit) {
  document.getElementById('budgetModalTitle').textContent='Edit Budget';
  document.getElementById('budgetCat').value=cat;
  document.getElementById('budgetCat').setAttribute('readonly','true');
  document.getElementById('budgetLimit').value=limit;
  document.getElementById('budgetModal').classList.add('open');
}

async function saveBudget() {
  const cat   = document.getElementById('budgetCat').value.trim();
  const limit = parseFloat(document.getElementById('budgetLimit').value);
  if (!cat)             return showToast('Enter a category','error');
  if (!limit||limit<=0) return showToast('Enter a valid limit','error');
  try {
    await apiPost(`${API}/budget/`,{category:cat,monthly_limit:limit});
    closeModal('budgetModal'); showToast('Budget saved','success'); loadBudget();
  } catch(e) { showToast(e.message||'Failed','error'); }
}

async function saveIncome() {
  const val = parseFloat(document.getElementById('incomeInput').value);
  const fb  = document.getElementById('incomeFb');
  if (!val||val<0) { fb.textContent='Enter a valid amount'; return; }
  try {
    await apiPut(`${API}/auth/me`,{monthly_income:val});
    fb.textContent='Saved!'; setTimeout(()=>fb.textContent='',2000);
  } catch(e) {
    try { await apiPost(`${API}/auth/me`,{monthly_income:val}); fb.textContent='Saved!'; setTimeout(()=>fb.textContent='',2000); }
    catch(e2) { fb.textContent='Not available yet'; }
  }
}

// ── EXPORT ──
async function doExport(fmt_) {
  const month = document.getElementById('exportMonth').value;
  const year  = document.getElementById('exportYear').value;
  const fb    = document.getElementById('exportFb');
  let url = `${API}/export/${fmt_}?`;
  if (month) url+=`month=${month}&`;
  if (year)  url+=`year=${year}&`;
  fb.textContent='Downloading…'; fb.className='ffeedback';
  try {
    const r = await fetch(url, { headers: authHdr() });
    if (!r.ok) throw new Error(`Server ${r.status}`);
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `finos-export.${fmt_==='excel'?'xlsx':fmt_}`;
    a.click(); URL.revokeObjectURL(a.href);
    fb.textContent='Downloaded!'; fb.className='ffeedback ok';
  } catch(e) { fb.textContent=e.message||'Failed'; fb.className='ffeedback err'; }
  setTimeout(()=>{fb.textContent='';fb.className='ffeedback'},3000);
}

// ── CHAT ──
function toggleChat() { document.getElementById('chatWindow').classList.toggle('hidden'); }

function sendChip(el) {
  document.getElementById('chatInput').value = el.textContent.trim();
  sendMsg();
}

async function sendMsg() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if (!msg) return;
  input.value=''; input.disabled=true;
  document.getElementById('chatSendBtn').disabled=true;
  const welcome = document.querySelector('.chat-welcome');
  if (welcome) welcome.remove();
  appendMsg('user', msg);
  chatHistory.push({role:'user',content:msg});
  const typing = appendTyping();
  try {
    let full='', bubble=null;
    const r = await fetch('/api/v1/agent/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json',...(authToken?{'Authorization':'Bearer '+authToken}:{})},
      body: JSON.stringify({message:msg})
    });
    if (!r.ok) throw new Error(`Server ${r.status}`);
    const reader = r.body.getReader(), dec = new TextDecoder();
    typing.remove();
    while(true) {
      const {done,value} = await reader.read();
      if (done) break;
      for (const line of dec.decode(value,{stream:true}).split('\n')) {
        if (!line.startsWith('data:')) continue;
        // const d = line.slice(5).trim();
        const d = line.startsWith('data: ') ? line.slice(6) : line.slice(5);
        if (d==='[DONE]') { chatHistory.push({role:'assistant',content:full}); input.disabled=false; document.getElementById('chatSendBtn').disabled=false; input.focus(); return; }
        if (!d) continue;
        if (!bubble) bubble = createBubble();
        full+=d;
        bubble.querySelector('.mbubble').textContent=full;
        scrollChat();
      }
    }
    if (!bubble) appendMsg('ai', full||'(no response)');
    chatHistory.push({role:'assistant',content:full});
  } catch(e) { typing.remove(); appendMsg('ai','Error: '+e.message); }
  input.disabled=false; document.getElementById('chatSendBtn').disabled=false; input.focus();
}

function appendMsg(role, text) {
  const el = document.createElement('div');
  el.className = `cmsg ${role}`;
  el.innerHTML = `<div class="mbubble">${esc(text)}</div><div class="mtime">${fmtTime()}</div>`;
  document.getElementById('chatMsgs').appendChild(el);
  scrollChat();
}

function createBubble() {
  const el = document.createElement('div');
  el.className = 'cmsg ai';
  el.innerHTML = `<div class="mbubble"></div><div class="mtime">${fmtTime()}</div>`;
  document.getElementById('chatMsgs').appendChild(el);
  scrollChat();
  return el;
}

function appendTyping() {
  const el = document.createElement('div');
  el.className = 'cmsg ai';
  el.innerHTML = `<div class="typing"><div class="td"></div><div class="td"></div><div class="td"></div></div>`;
  document.getElementById('chatMsgs').appendChild(el);
  scrollChat();
  return el;
}

function scrollChat() { const el=document.getElementById('chatMsgs'); el.scrollTop=el.scrollHeight; }

function clearChat() {
  chatHistory=[];
  const name = currentUser?.username?.split(' ')[0] || 'there';
  document.getElementById('chatMsgs').innerHTML=`
    <div class="chat-welcome">
      <div class="welcome-icon"><i class="ti ti-sparkles"></i></div>
      <div class="welcome-title">Hi ${esc(name)}! 👋</div>
      <div class="welcome-sub">Ask me anything about your finances.</div>
      <div class="welcome-chips">
        <button class="wchip" onclick="sendChip(this)">balance</button>
        <button class="wchip" onclick="sendChip(this)">show this month's expenses</button>
        <button class="wchip" onclick="sendChip(this)">top spending categories</button>
      </div>
    </div>`;
  showToast('Chat cleared','info');
}

// ── SIDEBAR ──
function toggleSidebar() {
  const s = document.getElementById('sidebar');
  const c = s.classList.toggle('col');
  document.getElementById('sbChevron').className = c ? 'ti ti-chevron-right' : 'ti ti-chevron-left';
  localStorage.setItem('finos-sb-col', c?'1':'0');
}

function restoreSidebar() {
  if (localStorage.getItem('finos-sb-col')==='1') {
    document.getElementById('sidebar').classList.add('col');
    document.getElementById('sbChevron').className = 'ti ti-chevron-right';
  }
}

// ── THEME ──
function toggleTheme() {
  const dark = document.documentElement.classList.contains('dark');
  document.documentElement.className = dark?'light':'dark';
  localStorage.setItem('finos-theme', dark?'light':'dark');
  updateThemeUI();
  if (currentPage==='dashboard') setTimeout(loadDashboard,50);
}

function restoreTheme() {
  document.documentElement.className = localStorage.getItem('finos-theme')||'dark';
}

function updateThemeUI() {
  const dark = document.documentElement.classList.contains('dark');
  const s=document.getElementById('iconSun'), m=document.getElementById('iconMoon'), l=document.getElementById('themeLabel');
  if(s) s.style.display = dark?'block':'none';
  if(m) m.style.display = !dark?'block':'none';
  if(l) l.textContent  = dark?'Dark':'Light';
}

// ── API ──
function authHdr(extra={}) {
  return {'Content-Type':'application/json',...(authToken?{'Authorization':'Bearer '+authToken}:{}),...extra};
}

async function apiFetch(url) {
  const r = await fetch(url,{headers:authHdr()});
  if (r.status===401) { showAuthScreen(); throw new Error('Unauthorized'); }
  if (!r.ok) { const e=await r.json().catch(()=>({})); throw new Error(e.detail||`HTTP ${r.status}`); }
  return r.json();
}

async function apiPost(url,body) {
  const r=await fetch(url,{method:'POST',headers:authHdr(),body:JSON.stringify(body)});
  if (r.status===401){showAuthScreen();throw new Error('Unauthorized');}
  if (!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||`HTTP ${r.status}`);}
  return r.json();
}

async function apiPut(url,body) {
  const r=await fetch(url,{method:'PUT',headers:authHdr(),body:JSON.stringify(body)});
  if (r.status===401){showAuthScreen();throw new Error('Unauthorized');}
  if (!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||`HTTP ${r.status}`);}
  return r.json();
}

async function apiDel(url) {
  const r=await fetch(url,{method:'DELETE',headers:authHdr()});
  if (r.status===401){showAuthScreen();throw new Error('Unauthorized');}
  if (!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||`HTTP ${r.status}`);}
  return r.status===204?null:r.json();
}

// ── UTILS ──
function fmt(n) { return '₹'+Number(n).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function fmtDate(d) { if(!d)return'—'; return new Date(d+'T00:00:00').toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'}); }
function fmtTime() { return new Date().toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:true}); }
function esc(s) { if(!s)return''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function setEl(id,v) { const el=document.getElementById(id); if(el)el.textContent=v; }
function showFb(el,msg,type) { el.textContent=msg;el.className=`ffeedback ${type}`;setTimeout(()=>{el.textContent='';el.className='ffeedback'},3000); }
function showToast(msg, type='info', onClick=null) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast ${type} show`;
  t.style.cursor = onClick ? 'pointer' : 'default';
  t.onclick = onClick ? () => { onClick(); t.className = `toast ${type}`; } : null;
  setTimeout(() => { t.className = `toast ${type}`; }, 2500);
}
function ym(d) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`; }
function daysLeft() { const n=new Date(),e=new Date(n.getFullYear(),n.getMonth()+1,0);return e.getDate()-n.getDate(); }