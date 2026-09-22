// ===== STATE =====
let corosData = { activities: [], sleep: [], daily: [], journals: [] };
let analysisData = null;

// ===== HELPERS =====
function fmtPace(s) { if (!s) return '-'; const m = Math.floor(s / 60); const sec = Math.floor(s % 60); return m + ':' + (sec < 10 ? '0' : '') + sec; }
function fmtDuration(s) { if (!s) return '-'; const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60); return h > 0 ? h + 'h ' + m + 'm' : m + 'm'; }
function fmtDist(m) { if (!m) return '-'; return m >= 1000 ? (m / 1000).toFixed(2) + ' km' : m + ' m'; }
function fmtDate(s) { if (!s) return '-'; return s.replace('T', ' ').substring(0, 16); }
function fmtDateShort(s) { if (!s) return '-'; return s.substring(5, 10); }
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html) e.innerHTML = html; return e; }

// ===== DATA LOADING =====
async function loadData() {
  try {
    const res = await fetch('./data.json?t=' + Date.now());
    if (res.ok) corosData = await res.json();
  } catch (e) { console.error('Load failed:', e); }
  render('dashboard');
}

// ===== NAV =====
document.querySelectorAll('.nav a').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    document.querySelectorAll('.nav a').forEach(x => x.classList.remove('active'));
    a.classList.add('active');
    render(a.dataset.page);
  });
});

// ===== RENDER =====
function render(page) {
  const main = document.getElementById('main');
  main.innerHTML = '';
  switch(page) {
    case 'dashboard': renderDashboard(main); break;
    case 'sleep': renderSleep(main); break;
    case 'recovery': renderRecovery(main); break;
    case 'breathing': renderBreathing(main); break;
    case 'journal': renderJournal(main); break;
    case 'activities': renderActivities(main); break;
    case 'weekly': renderWeekly(main); break;
  }
}

// ===== DASHBOARD =====
function renderDashboard(main) {
  const acts = corosData.activities || [];
  const sleeps = corosData.sleep || [];
  const daily = corosData.daily || [];
  
  const totalDist = acts.reduce((s, a) => s + (a.distance_m || 0), 0);
  const totalDur = acts.reduce((s, a) => s + (a.duration_s || 0), 0);
  const avgPace = acts.length ? Math.round(acts.reduce((s, a) => s + (a.avg_pace_s || 0), 0) / acts.length) : 0;
  const totalSteps = daily.reduce((s, x) => s + (x.steps || 0), 0);
  const avgStress = daily.length ? Math.round(daily.reduce((s, x) => s + (x.stress_score || 0), 0) / daily.length) : 0;
  const avgEff = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + getEff(x), 0) / sleeps.length) : 0;
  
  // Header
  main.appendChild(el('div', 'header', '<div><h2>Dashboard</h2><div class="breadcrumb">Overview / Summary</div></div>'));
  
  // Cards
  const cards = el('div', 'cards');
  cards.appendChild(card('Total Distance', (totalDist / 1000).toFixed(1), 'km'));
  cards.appendChild(card('Avg Pace', fmtPace(avgPace), '/km'));
  cards.appendChild(card('Total Steps', totalSteps.toLocaleString(), ''));
  cards.appendChild(card('Sleep Efficiency', avgEff + '%', 'average'));
  cards.appendChild(card('Avg Stress', avgStress, ''));
  cards.appendChild(card('Activities', acts.length, 'total'));
  main.appendChild(cards);
  
  // Recent activities
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">🏃</span>Recent Activities'));
  if (acts.length === 0) {
    sect.appendChild(el('div', 'empty', '<div style="font-size:32px;margin-bottom:8px">🏃</div><p>No activities yet</p>'));
  } else {
    sect.appendChild(renderActTable(acts.slice(0, 8)));
  }
  main.appendChild(sect);
}

function card(label, val, unit) {
  return el('div', 'card', '<div class="label">' + label + '</div><div class="val">' + val + '<span style="font-size:12px;color:var(--muted)"> ' + unit + '</span></div>');
}

function renderActTable(acts) {
  const table = el('table');
  table.innerHTML = '<tr><th>Date</th><th>Sport</th><th>Distance</th><th>Duration</th><th>Pace</th><th>HR</th></tr><tbody>' +
    acts.map(a => '<tr><td>' + fmtDate(a.start_time) + '</td><td><span class="badge">' + a.sport_type + '</span></td><td>' + fmtDist(a.distance_m) + '</td><td>' + fmtDuration(a.duration_s) + '</td><td>' + fmtPace(a.avg_pace_s) + ' /km</td><td>' + (a.avg_hr || '-') + ' bpm</td></tr>').join('') +
    '</tbody>';
  const wrap = el('div'); wrap.style.overflowX = 'auto'; wrap.appendChild(table); return wrap;
}

function getEff(s) {
  if (!s.duration_min || s.awake_min == null) return 0;
  return Math.round((s.duration_min / (s.duration_min + s.awake_min * 1.5)) * 100);
}

// ===== SLEEP =====
function renderSleep(main) {
  const sleeps = corosData.sleep || [];
  main.appendChild(el('div', 'header', '<div><h2>Sleep</h2><div class="breadcrumb">Recovery / Sleep Analysis</div></div>'));
  
  if (sleeps.length === 0) {
    main.appendChild(el('div', 'section empty', '<p>No sleep data yet</p>'));
    return;
  }
  
  const latest = sleeps[0] || {};
  const deep = latest.deep_sleep_pct || 0;
  const light = latest.light_sleep_pct || 0;
  const rem = latest.rem_sleep_pct || 0;
  const awake = Math.max(0, 100 - deep - light - rem);
  
  // Stage balance
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">🌙</span>Latest Night Stages'));
  sect.innerHTML += '<div class="stage-bar"><div class="stage-deep" style="width:' + deep + '%"></div><div class="stage-light" style="width:' + light + '%"></div><div class="stage-rem" style="width:' + rem + '%"></div><div class="stage-awake" style="width:' + awake + '%"></div></div>' +
    '<div class="legend"><span><span class="legend-dot" style="background:#7c3aed"></span>Deep ' + deep + '%</span><span><span class="legend-dot" style="background:#3b82f6"></span>Light ' + light + '%</span><span><span class="legend-dot" style="background:#f59e0b"></span>REM ' + rem + '%</span><span><span class="legend-dot" style="background:var(--accent)"></span>Awake ' + awake.toFixed(1) + '%</span></div>';
  main.appendChild(sect);
  
  // Sleep table
  const sect2 = el('div', 'section');
  sect2.appendChild(el('h3', null, '<span class="sect-icon">📊</span>Sleep History'));
  const table = el('table');
  table.innerHTML = '<tr><th>Date</th><th>Duration</th><th>Deep</th><th>Light</th><th>REM</th><th>Awake</th><th>Efficiency</th></tr><tbody>' +
    sleeps.map(s => { const eff = getEff(s); return '<tr><td>' + (s.date || '-') + '</td><td>' + fmtDuration((s.duration_min || 0) * 60) + '</td><td>' + (s.deep_sleep_pct || '-') + '%</td><td>' + (s.light_sleep_pct || '-') + '%</td><td>' + (s.rem_sleep_pct || '-') + '%</td><td>' + (s.awake_min || '-') + ' min</td><td>' + eff + '%</td></tr>'; }).join('') +
    '</tbody>';
  const wrap = el('div'); wrap.style.overflowX = 'auto'; wrap.appendChild(table);
  sect2.appendChild(wrap);
  main.appendChild(sect2);
}

// ===== RECOVERY =====
function renderRecovery(main) {
  const sleeps = corosData.sleep || [];
  main.appendChild(el('div', 'header', '<div><h2>Recovery</h2><div class="breadcrumb">Recovery Analysis</div></div>'));
  
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">❤️</span>Recovery Score'));
  
  const avgHrv = sleeps.filter(s => s.hrv).reduce((s, x, _, a) => s + x.hrv / a.length, 0);
  const avgRhr = sleeps.filter(s => s.resting_hr).reduce((s, x, _, a) => s + x.resting_hr / a.length, 0);
  const avgEff = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + getEff(x), 0) / sleeps.length) : 0;
  
  const score = Math.round(avgEff * 0.6 + (avgHrv > 0 ? 30 : 20));
  const band = score >= 80 ? 'good' : score >= 60 ? 'moderate' : 'low';
  const bandColor = score >= 80 ? 'var(--success)' : score >= 60 ? 'var(--warning)' : 'var(--accent)';
  
  sect.innerHTML += '<div style="text-align:center;padding:20px"><div style="font-size:48px;font-weight:800;color:' + bandColor + '">' + score + '</div><div style="font-size:13px;color:var(--muted);margin-top:4px">/100 — ' + band + '</div></div>';
  
  const grid = el('div', 'grid-2');
  grid.appendChild(el('div', 'section', '<h3>❤️ Avg HRV</h3><div style="font-size:24px;font-weight:700">' + (avgHrv > 0 ? Math.round(avgHrv) + ' ms' : '-') + '</div>'));
  grid.appendChild(el('div', 'section', '<h3>💓 Avg Resting HR</h3><div style="font-size:24px;font-weight:700">' + (avgRhr > 0 ? Math.round(avgRhr) + ' bpm' : '-') + '</div>'));
  sect.appendChild(grid);
  main.appendChild(sect);
}

// ===== BREATHING =====
function renderBreathing(main) {
  main.appendChild(el('div', 'header', '<div><h2>Breathing</h2><div class="breadcrumb">Respiratory Analysis</div></div>'));
  
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">🫁</span>Breathing Metrics'));
  sect.innerHTML += '<div class="empty"><div style="font-size:32px;margin-bottom:8px">🫁</div><p>Connect COROS wellness check to see SpO2 and respiratory rate</p></div>';
  main.appendChild(sect);
}

// ===== JOURNAL =====
function renderJournal(main) {
  main.appendChild(el('div', 'header', '<div><h2>Journal</h2><div class="breadcrumb">Sleep Factors / Correlation</div></div>'));
  
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">📝</span>Daily Journal'));
  
  const form = el('div');
  form.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:12px">' +
    '<div><label style="font-size:11px;color:var(--muted)">Date</label><input type="date" id="jDate" style="width:100%;padding:6px;border:1px solid var(--border);border-radius:4px"></div>' +
    '<div><label style="font-size:11px;color:var(--muted)">Alcohol (units)</label><input type="number" id="jAlcohol" min="0" max="10" value="0" style="width:100%;padding:6px;border:1px solid var(--border);border-radius:4px"></div>' +
    '<div><label style="font-size:11px;color:var(--muted)">Caffeine after 14:00</label><select id="jCaffeine" style="width:100%;padding:6px;border:1px solid var(--border);border-radius:4px"><option value="false">No</option><option value="true">Yes</option></select></div>' +
    '<div><label style="font-size:11px;color:var(--muted)">Late meal</label><select id="jLateMeal" style="width:100%;padding:6px;border:1px solid var(--border);border-radius:4px"><option value="false">No</option><option value="true">Yes</option></select></div>' +
    '<div><label style="font-size:11px;color:var(--muted)">Screen before bed (min)</label><input type="number" id="jScreen" min="0" max="180" value="0" style="width:100%;padding:6px;border:1px solid var(--border);border-radius:4px"></div>' +
    '<div><label style="font-size:11px;color:var(--muted)">Stress (1-5)</label><input type="number" id="jStress" min="1" max="5" value="3" style="width:100%;padding:6px;border:1px solid var(--border);border-radius:4px"></div>' +
    '</div>' +
    '<button onclick="saveJournal()" style="background:var(--accent);color:#fff;border:none;padding:8px 16px;border-radius:4px;cursor:pointer">Save Entry</button>';
  sect.appendChild(form);
  main.appendChild(sect);
}

function saveJournal() {
  const entry = {
    date: document.getElementById('jDate').value,
    alcohol_units: parseInt(document.getElementById('jAlcohol').value) || 0,
    caffeine_after_14: document.getElementById('jCaffeine').value === 'true',
    late_meal: document.getElementById('jLateMeal').value === 'true',
    screen_before_bed_min: parseInt(document.getElementById('jScreen').value) || 0,
    stress_level: parseInt(document.getElementById('jStress').value) || 3
  };
  alert('Journal entry saved for ' + entry.date);
}

// ===== ACTIVITIES =====
function renderActivities(main) {
  const acts = corosData.activities || [];
  main.appendChild(el('div', 'header', '<div><h2>Activities</h2><div class="breadcrumb">Training / Activities</div></div>'));
  
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">🏃</span>All Activities'));
  if (acts.length === 0) {
    sect.appendChild(el('div', 'empty', '<p>No activities yet</p>'));
  } else {
    sect.appendChild(renderActTable(acts));
  }
  main.appendChild(sect);
}

// ===== WEEKLY =====
function renderWeekly(main) {
  const sleeps = corosData.sleep || [];
  const daily = corosData.daily || [];
  
  main.appendChild(el('div', 'header', '<div><h2>Weekly Report</h2><div class="breadcrumb">Auto-generated Summary</div></div>'));
  
  const avgEff = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + getEff(x), 0) / sleeps.length) : 0;
  const avgDeep = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + (x.deep_sleep_pct || 0), 0) / sleeps.length) : 0;
  const avgRem = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + (x.rem_sleep_pct || 0), 0) / sleeps.length) : 0;
  const totalSteps = daily.reduce((s, x) => s + (x.steps || 0), 0);
  
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">📊</span>Sleep Summary'));
  sect.innerHTML += '<div style="white-space:pre-wrap;font-size:13px;line-height:1.6">' +
    '📊 สรุปการนอน (' + sleeps.length + ' คืน)\n' +
    '- Sleep Efficiency เฉลี่ย: ' + avgEff + '%\n' +
    '- Deep Sleep เฉลี่ย: ' + avgDeep + '%\n' +
    '- REM เฉลี่ย: ' + avgRem + '%\n' +
    '- Total Steps: ' + totalSteps.toLocaleString() + '\n' +
    '</div>';
  main.appendChild(sect);
} 

// ===== INIT =====
loadData();

