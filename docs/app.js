// ===== STATE =====
let corosData = { activities: [], sleep: [], daily: [], journals: [] };
let analysisData = null;

// ===== SPORT TYPE MAPPING =====
const SPORT_TYPE_MAP = {
  100: 'Outdoor Run',
  101: 'Indoor Run',
  102: 'Trail Run',
  103: 'Track Run',
};
function sportLabel(code) {
  return SPORT_TYPE_MAP[code] || ('Sport ' + code);
}

// ===== HELPERS =====
function fmtPace(s) { if (!s) return '–'; const m = Math.floor(s / 60); const sec = Math.floor(s % 60); return m + ':' + (sec < 10 ? '0' : '') + sec; }
function fmtDuration(s) { if (!s) return '–'; const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60); return h > 0 ? h + 'h ' + m + 'm' : m + 'm'; }
function fmtDist(m) { if (!m) return '–'; return m >= 1000 ? (m / 1000).toFixed(2) + ' km' : m + ' m'; }
function fmtDate(s) { if (!s) return '–'; return s.replace('T', ' ').substring(0, 16); }
function fmtDateShort(s) { if (!s) return '–'; return s.substring(5, 10); }
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html) e.innerHTML = html; return e; }
function fmtNum(n) { return n != null && !isNaN(n) ? (Number.isInteger(n) ? n : n.toFixed(1)) : '–'; }
function statusClass(value, thresholds) {
  if (value == null || isNaN(value)) return '';
  if (value >= thresholds.green) return 'status-green';
  if (value >= thresholds.yellow) return 'status-yellow';
  return 'status-red';
}

function colorizeNarrative(text) {
  if (!text) return '';
  const rules = [
    [/\(ดีมาก\)/g, 'tag-good'],
    [/\(ดี\)/g, 'tag-good'],
    [/\(ปกติ\)/g, 'tag-good'],
    [/\(พอใช้\)/g, 'tag-warn'],
    [/\(ต่ำ\)/g, 'tag-bad'],
    [/\(สูง\)/g, 'tag-bad'],
    [/\(ควรปรับปรุง\)/g, 'tag-bad'],
    [/\(ยาวเกินไป[^)]*\)/g, 'tag-bad'],
  ];
  let out = text;
  for (const [re, cls] of rules) {
    out = out.replace(re, m => '<span class="' + cls + '">' + m + '</span>');
  }
  return out;
}

// ===== DATA LOADING =====
async function loadData() {
  try {
    const res = await fetch('./data.json?t=' + Date.now());
    if (res.ok) corosData = await res.json();
  } catch (e) { console.error('Load data.json failed:', e); }

  analysisData = corosData;

  try {
    const analysisRes = await fetch('/api/analysis');
    if (analysisRes.ok) analysisData = await analysisRes.json();
  } catch (e) { console.log('Local /api/analysis not available — using data.json analysis fields'); }

  render('dashboard');
}

// ===== NAV =====
document.querySelectorAll('.tabbar a').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    document.querySelectorAll('.tabbar a').forEach(x => x.classList.remove('active'));
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

// ===== MINI RING (Sleep Perf — a % maps naturally to a ring) =====
function miniRing(value, max, decimals) {
  const r = 26, circumference = 2 * Math.PI * r;
  const hasData = value != null && !isNaN(value);
  const pct = hasData ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const offset = circumference - (pct / 100) * circumference;
  const cls = hasData ? statusClass(pct, {green:80, yellow:50}) : 'status-empty';
  const wrap = el('div', 'mini-ring-wrap');
  wrap.innerHTML =
    '<svg width="64" height="64" viewBox="0 0 64 64">' +
    '<circle class="mini-ring-track" cx="32" cy="32" r="' + r + '"></circle>' +
    '<circle class="mini-ring-progress ' + cls + '" cx="32" cy="32" r="' + r +
      '" stroke-dasharray="' + circumference + '" stroke-dashoffset="' + circumference + '"></circle>' +
    '</svg><div class="mini-ring-center">' + (hasData ? Number(value).toFixed(decimals || 0) : '–') + '</div>';
  // animate in on next frame
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const c = wrap.querySelector('.mini-ring-progress');
    if (c) c.style.strokeDashoffset = offset;
  }));
  return wrap;
}

// ===== STRAIN GAUGE (0-21 linear scale — a bar, not a second ring, since it isn't a %) =====
function strainGauge(value) {
  const max = 21;
  const hasData = value != null && !isNaN(value);
  const pct = hasData ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const cls = hasData ? statusClass(pct, {green:70, yellow:35}) : 'status-empty';
  const wrap = el('div');
  wrap.innerHTML =
    '<div class="gauge-track"><div class="gauge-fill ' + cls + '" style="width:0%"></div></div>' +
    '<div class="gauge-ticks"><span>0</span><span>7</span><span>14</span><span>21</span></div>';
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const f = wrap.querySelector('.gauge-fill');
    if (f) f.style.width = pct + '%';
  }));
  return wrap;
}

// ===== RECOVERY RING (hero) + secondary row (Sleep Perf ring / Strain gauge) =====
function renderRecoveryRing(main) {
  if (!analysisData || !analysisData.recovery_score) return;
  const rs = analysisData.recovery_score;
  const pct = rs.recovery_score;
  if (pct == null || isNaN(pct)) return;

  const bandClass = rs.band === 'green' ? 'status-green' : rs.band === 'yellow' ? 'status-yellow' : 'status-red';
  const bandLabel = rs.band === 'green' ? 'พร้อมซ้อม' : rs.band === 'yellow' ? 'ควรผ่อน' : 'ควรพัก';
  const r = 84, circumference = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, pct));
  const offset = circumference - (clamped / 100) * circumference;

  const sect = el('div', 'recovery-ring-section');
  sect.innerHTML =
    '<div class="ring-wrap"><svg width="188" height="188" viewBox="0 0 188 188">' +
    '<circle class="ring-track" cx="94" cy="94" r="' + r + '"></circle>' +
    '<circle class="ring-progress ' + bandClass + '" cx="94" cy="94" r="' + r +
      '" stroke-dasharray="' + circumference + '" stroke-dashoffset="' + circumference + '"></circle>' +
    '</svg><div class="ring-center"><div class="pct">' + fmtNum(pct) + '</div><div class="lbl">Recovery</div></div></div>' +
    '<div class="band-pill ' + bandClass + '"><span class="dot"></span>' + bandLabel + '</div>';

  requestAnimationFrame(() => requestAnimationFrame(() => {
    const c = sect.querySelector('.ring-progress');
    if (c) c.style.strokeDashoffset = offset;
  }));

  const sleepPerf = rs.components ? rs.components.sleep_performance : null;
  const strain = analysisData.latest_strain ? analysisData.latest_strain.day_strain : null;

  const row = el('div', 'secondary-row');

  const sleepBlock = el('div', 'metric-block');
  const sleepRing = miniRing(sleepPerf, 100, 0);
  const sleepWrap = el('div', 'secondary-row');
  sleepWrap.style.gap = '12px';
  sleepWrap.appendChild(sleepRing);
  const sleepText = el('div');
  sleepText.innerHTML = '<div class="m-lbl">Sleep Performance</div><div class="m-val">ของเป้าหมายที่ต้องการ</div>';
  sleepWrap.appendChild(sleepText);

  const strainBlock = el('div');
  strainBlock.style.marginTop = '18px';
  strainBlock.innerHTML = '<div class="m-lbl">Strain <span class="num" style="color:var(--text-dim)">' + (strain != null ? fmtNum(strain) : '–') + ' / 21</span></div>';
  strainBlock.appendChild(strainGauge(strain));

  sect.appendChild(sleepWrap);
  sect.appendChild(strainBlock);

  main.appendChild(sect);
}

// ===== NARRATIVE SECTION =====
function renderNarrativeSection(main) {
  if (!analysisData || !analysisData.narrative) return;

  const narrative = analysisData.narrative;
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">📝</span>สรุปภาพรวมวันนี้'));

  let html = '';
  if (narrative.summary) {
    html += '<p class="narrative-summary">' + colorizeNarrative(narrative.summary) + '</p>';
  }

  const sections = narrative.sections || {};
  const sectionLabels = { recovery: 'Recovery', sleep: 'การนอน', training: 'การซ้อม', health: 'สุขภาพ' };

  for (const [key, label] of Object.entries(sectionLabels)) {
    if (sections[key]) {
      html += '<div class="narrative-block"><strong>' + label + '</strong>' + colorizeNarrative(sections[key]) + '</div>';
    }
  }

  if (narrative.action_items && narrative.action_items.length > 0) {
    html += '<div class="action-list"><div class="al-title">คำแนะนำ</div><ul>';
    for (const item of narrative.action_items) html += '<li>' + colorizeNarrative(item) + '</li>';
    html += '</ul></div>';
  }

  sect.innerHTML += html;
  main.appendChild(sect);
}

// ===== TRAINING ANALYTICS SECTION =====
function renderTrainingSection(main) {
  if (!analysisData || !analysisData.training_analytics) return;

  const ta = analysisData.training_analytics;
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">📊</span>Training Analytics'));

  if (ta.fitness) {
    const f = ta.fitness;
    const grid = el('div', 'grid-2');
    grid.innerHTML =
      '<div class="g-cell"><h4>FITNESS (CTL)</h4><div class="g-val">' + fmtNum(f.ctl) + '</div></div>' +
      '<div class="g-cell"><h4>FATIGUE (ATL)</h4><div class="g-val">' + fmtNum(f.atl) + '</div></div>' +
      '<div class="g-cell"><h4>FORM (TSB)</h4><div class="g-val ' + (f.tsb < 0 ? 'status-yellow' : 'status-green') + '">' + (f.tsb != null ? (f.tsb >= 0 ? '+' : '') + fmtNum(f.tsb) : '–') + '</div></div>' +
      '<div class="g-cell"><h4>สถานะข้อมูล</h4><div class="g-sub" style="font-size:12px;margin-top:2px">' + (f.confidence === 'stable' ? 'เพียงพอ' : f.confidence === 'moderate' ? 'กำลังสะสม' : 'ยังไม่พอ') + '</div></div>';
    sect.appendChild(grid);
  }

  let html = '<div style="font-size:13px;line-height:1.7;color:var(--text-dim);margin-top:14px">';

  if (ta.economy && ta.economy.trend) {
    const econ = ta.economy;
    html += '<p><strong style="color:var(--text)">Running Economy — </strong>';
    if (econ.trend === 'improving') html += 'ดีขึ้น ' + Math.abs(econ.economy_change_pct || 0).toFixed(1) + '% (วิ่งเร็วขึ้นที่ HR เดียวกัน)';
    else if (econ.trend === 'declining') html += 'แย่ลง ' + Math.abs(econ.economy_change_pct || 0).toFixed(1) + '% (อาจยังไม่ฟื้น)';
    else html += 'คงที่';
    html += '</p>';
  }

  if (ta.readiness && ta.readiness.readiness_score != null) {
    const r = ta.readiness;
    const cls = r.band === 'ready' ? 'tag-good' : r.band === 'moderate' ? 'tag-warn' : '';
    html += '<p style="margin-top:8px"><strong style="color:var(--text)">Race Readiness — </strong>' +
      '<span class="num">' + fmtNum(r.readiness_score) + '/100</span> — <span class="' + cls + '">' +
      (r.band === 'ready' ? 'พร้อมแข่ง' : r.band === 'moderate' ? 'พอใช้' : 'ยังไม่พร้อม') + '</span></p>';
  }

  if (ta.strain_performance && ta.strain_performance.lag_days != null) {
    const sp = ta.strain_performance;
    html += '<p style="margin-top:8px"><strong style="color:var(--text)">Strain → Performance — </strong>lag ' + sp.lag_days + ' วัน';
    if (sp.correlation) html += ' · corr <span class="num">' + sp.correlation + '</span>';
    html += '</p>';
  }

  html += '</div>';
  sect.innerHTML += html;
  main.appendChild(sect);
}

// ===== ILLNESS / OVERTRAINING SECTION =====
function renderHealthRiskSection(main) {
  if (!analysisData) return;

  const illness = analysisData.illness_risk;
  const overtraining = analysisData.overtraining;
  if (!illness && !overtraining) return;

  const hasRisk = (illness && illness.risk_level && illness.risk_level !== 'none') ||
                  (overtraining && overtraining.risk_level && overtraining.risk_level !== 'none');
  if (!hasRisk) return;

  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">⚠️</span>ความเสี่ยง'));

  let html = '<div style="font-size:13px;line-height:1.75;color:var(--text-dim)">';

  if (illness && illness.risk_level && illness.risk_level !== 'none') {
    const cls = illness.risk_level === 'high' ? 'tag-bad' : 'tag-warn';
    html += '<p><strong style="color:var(--text)">ความเสี่ยงป่วย — </strong><span class="' + cls + '">' + illness.risk_score + '/4 (' + illness.risk_level + ')</span>';
    if (illness.signals && illness.signals.length > 0) {
      const signalLabels = { rhr_high: 'RHR สูงผิดปกติ', hrv_low: 'HRV ต่ำผิดปกติ', skin_temp_high: 'Skin Temp สูงผิดปกติ', resp_rate_high: 'Respiratory Rate สูงผิดปกติ' };
      html += '<br><span style="color:var(--text-faint);font-size:12px">' + illness.signals.map(s => signalLabels[s] || s).join(' · ') + '</span>';
    }
    html += '</p>';
  }

  if (overtraining && overtraining.risk_level && overtraining.risk_level !== 'none') {
    const cls = overtraining.risk_level === 'high' ? 'tag-bad' : overtraining.risk_level === 'medium' ? 'tag-warn' : 'tag-good';
    html += '<p style="margin-top:10px"><strong style="color:var(--text)">Overtraining — </strong><span class="' + cls + '">' + overtraining.risk_level + '</span>';
    if (overtraining.flags && overtraining.flags.length > 0) {
      const flagLabels = { acwr_high: 'ACWR สูงต่อเนื่อง', hrv_declining: 'HRV แนวโน้มลด', recovery_low: 'Recovery ต่ำติดต่อกัน' };
      html += '<br><span style="color:var(--text-faint);font-size:12px">' + overtraining.flags.map(f => flagLabels[f] || f).join(' · ') + '</span>';
    }
    html += '</p>';
  }

  html += '</div>';
  sect.innerHTML += html;
  main.appendChild(sect);
}

// ===== COACH RECOMMENDATIONS =====
function renderCoachSection(main) {
  if (!analysisData || !analysisData.coach_recommendations || analysisData.coach_recommendations.length === 0) return;

  const recs = analysisData.coach_recommendations;
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">💡</span>คำแนะนำ'));

  let html = '<ul style="list-style:none">';
  for (const rec of recs) {
    const cls = rec.priority === 'high' ? 'tag-bad' : rec.priority === 'medium' ? 'tag-warn' : 'tag-good';
    html += '<li style="margin-bottom:10px;font-size:13px;color:var(--text-dim);line-height:1.6"><span class="' + cls + '" style="font-size:9.5px;text-transform:uppercase;letter-spacing:0.03em;margin-right:8px">' + rec.priority + '</span>' + rec.message + '</li>';
  }
  html += '</ul>';
  sect.innerHTML += html;
  main.appendChild(sect);
}

// ===== TODAY'S ACTIVITY =====
function renderActivityCard(main, acts) {
  if (!acts || acts.length === 0) return;
  const sorted = [...acts].sort((a, b) => new Date(b.start_time) - new Date(a.start_time));
  const latest = sorted[0];

  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">🏃</span>Latest Activity'));

  const row = el('div', 'activity-row');
  row.innerHTML = '<span class="a-sport">' + sportLabel(latest.sport_type) + '</span><span class="a-date num">' + fmtDate(latest.start_time) + '</span>';
  sect.appendChild(row);

  const stats = el('div', 'activity-stats');
  stats.innerHTML =
    '<div class="a-stat"><div class="a-val">' + fmtDist(latest.distance_m) + '</div><div class="a-lbl">DIST</div></div>' +
    '<div class="a-stat"><div class="a-val">' + fmtDuration(latest.duration_s) + '</div><div class="a-lbl">TIME</div></div>' +
    '<div class="a-stat"><div class="a-val">' + fmtPace(latest.avg_pace_s) + '</div><div class="a-lbl">PACE</div></div>' +
    '<div class="a-stat"><div class="a-val">' + (latest.avg_hr || '–') + '</div><div class="a-lbl">HR</div></div>' +
    '<div class="a-stat"><div class="a-val">' + (latest.calories_burned || '–') + '</div><div class="a-lbl">CAL</div></div>';
  sect.appendChild(stats);
  main.appendChild(sect);
}

// ===== DASHBOARD =====
function renderDashboard(main) {
  const acts = corosData.activities || [];
  const sleeps = corosData.sleep || [];
  const daily = corosData.daily || [];

  const totalSteps = daily.reduce((s, x) => s + (x.steps || 0), 0);
  const avgStress = daily.length ? Math.round(daily.reduce((s, x) => s + (x.stress_score || 0), 0) / daily.length) : 0;
  const avgEff = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + getEff(x), 0) / sleeps.length) : 0;

  main.appendChild(el('div', 'header', '<h2>Dashboard</h2><div class="breadcrumb">Overview / Summary</div>'));

  renderRecoveryRing(main);
  renderNarrativeSection(main);
  renderActivityCard(main, acts);

  const sect = el('div', 'section');
  const strip = el('div', 'stat-strip');
  strip.innerHTML =
    '<div class="stat"><div class="s-val">' + totalSteps.toLocaleString() + '</div><div class="s-lbl">STEPS</div></div>' +
    '<div class="stat"><div class="s-val ' + statusClass(avgEff, {green:90, yellow:70}) + '">' + avgEff + '%</div><div class="s-lbl">SLEEP EFF</div></div>' +
    '<div class="stat"><div class="s-val ' + statusClass(100 - avgStress, {green:70, yellow:50}) + '">' + avgStress + '</div><div class="s-lbl">STRESS</div></div>' +
    '<div class="stat"><div class="s-val">' + acts.length + '</div><div class="s-lbl">ACTIVITIES</div></div>';
  sect.appendChild(strip);
  main.appendChild(sect);

  renderTrainingSection(main);
  renderHealthRiskSection(main);
  renderCoachSection(main);

  const sect2 = el('div', 'section');
  sect2.appendChild(el('h3', null, '<span class="sect-icon">🏃</span>Recent Activities'));
  if (acts.length === 0) {
    sect2.appendChild(el('div', 'empty', '<div class="e-icon">🏃</div><p>ยังไม่มีข้อมูลกิจกรรม — เมื่อ sync จาก COROS แล้วจะแสดงที่นี่</p>'));
  } else {
    sect2.appendChild(renderActTable(acts.slice(0, 8)));
  }
  main.appendChild(sect2);
}

function renderActTable(acts) {
  const table = el('table');
  table.innerHTML = '<tr><th>Date</th><th>Sport</th><th>Dist</th><th>Time</th><th>Pace</th><th>HR</th></tr><tbody>' +
    acts.map(a => '<tr><td>' + fmtDate(a.start_time) + '</td><td><span class="badge">' + sportLabel(a.sport_type) + '</span></td><td>' + fmtDist(a.distance_m) + '</td><td>' + fmtDuration(a.duration_s) + '</td><td>' + fmtPace(a.avg_pace_s) + '</td><td>' + (a.avg_hr || '–') + '</td></tr>').join('') +
    '</tbody>';
  const wrap = el('div', 'overflow-x'); wrap.appendChild(table); return wrap;
}

function getEff(s) {
  if (!s.duration_min || s.awake_min == null) return 0;
  return Math.round((s.duration_min / (s.duration_min + s.awake_min * 1.5)) * 100);
}

// ===== SLEEP =====
function renderSleep(main) {
  const sleeps = corosData.sleep || [];
  main.appendChild(el('div', 'header', '<h2>Sleep</h2><div class="breadcrumb">Recovery / Sleep Analysis</div>'));

  if (sleeps.length === 0) {
    main.appendChild(el('div', 'section empty', '<div class="e-icon">🌙</div><p>ยังไม่มีข้อมูลการนอน</p>'));
    return;
  }

  const latest = sleeps[0] || {};
  const deep = latest.deep_sleep_pct || 0;
  const light = latest.light_sleep_pct || 0;
  const rem = latest.rem_sleep_pct || 0;
  const awake = Math.max(0, 100 - deep - light - rem);

  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">🌙</span>Latest Night Stages'));
  sect.innerHTML += '<div class="stage-bar"><div class="stage-deep" style="width:' + deep + '%"></div><div class="stage-light" style="width:' + light + '%"></div><div class="stage-rem" style="width:' + rem + '%"></div><div class="stage-awake" style="width:' + awake + '%"></div></div>' +
    '<div class="legend"><span><span class="legend-dot" style="background:#8b7ae0"></span>Deep <span class="num">' + deep + '%</span></span><span><span class="legend-dot" style="background:#5b9bd5"></span>Light <span class="num">' + light + '%</span></span><span><span class="legend-dot" style="background:var(--signal)"></span>REM <span class="num">' + rem + '%</span></span><span><span class="legend-dot" style="background:var(--bad)"></span>Awake <span class="num">' + awake.toFixed(1) + '%</span></span></div>';
  main.appendChild(sect);

  const sect2 = el('div', 'section');
  sect2.appendChild(el('h3', null, '<span class="sect-icon">📊</span>Sleep History'));
  const table = el('table');
  table.innerHTML = '<tr><th>Date</th><th>Time</th><th>Deep</th><th>Light</th><th>REM</th><th>Awake</th><th>Eff</th></tr><tbody>' +
    sleeps.map(s => { const eff = getEff(s); return '<tr><td>' + (s.date || '–') + '</td><td>' + fmtDuration((s.duration_min || 0) * 60) + '</td><td>' + (s.deep_sleep_pct != null ? s.deep_sleep_pct + '%' : '–') + '</td><td>' + (s.light_sleep_pct != null ? s.light_sleep_pct + '%' : '–') + '</td><td>' + (s.rem_sleep_pct != null ? s.rem_sleep_pct + '%' : '–') + '</td><td>' + (s.awake_min != null ? s.awake_min + 'm' : '–') + '</td><td>' + eff + '%</td></tr>'; }).join('') +
    '</tbody>';
  const wrap = el('div', 'overflow-x'); wrap.appendChild(table);
  sect2.appendChild(wrap);
  main.appendChild(sect2);
}

// ===== RECOVERY =====
function renderRecovery(main) {
  const sleeps = corosData.sleep || [];
  main.appendChild(el('div', 'header', '<h2>Recovery</h2><div class="breadcrumb">Recovery Analysis</div>'));

  const score = analysisData && analysisData.recovery_score ? analysisData.recovery_score : null;

  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">❤️</span>Recovery Score'));

  if (score) {
    const bandColor = score.band === 'green' ? 'var(--good)' : score.band === 'yellow' ? 'var(--signal)' : 'var(--bad)';
    sect.innerHTML += '<div style="text-align:center;padding:14px 0 20px"><div class="num" style="font-size:44px;font-weight:600;color:' + bandColor + '">' + fmtNum(score.recovery_score) + '</div><div style="font-size:12px;color:var(--text-faint);margin-top:4px">/100 — ' + score.band + '</div></div>';

    if (score.components) {
      const comp = score.components;
      const grid = el('div', 'grid-2');
      grid.innerHTML =
        '<div class="g-cell"><h4>HRV · 30%</h4><div class="g-val">' + fmtNum(comp.hrv_score) + '</div></div>' +
        '<div class="g-cell"><h4>RHR · 20%</h4><div class="g-val">' + fmtNum(comp.rhr_score) + '</div></div>' +
        '<div class="g-cell"><h4>SLEEP PERF · 25%</h4><div class="g-val">' + fmtNum(comp.sleep_performance) + '</div></div>' +
        '<div class="g-cell"><h4>SLEEP EFF · 15%</h4><div class="g-val">' + fmtNum(comp.sleep_efficiency) + '</div></div>';
      sect.appendChild(grid);
    }

    if (score.penalty_applied > 0) {
      let p = '<div style="margin-top:14px;font-size:12px;color:var(--text-faint)">Penalty: <span class="num">' + fmtNum(score.penalty_applied) + '</span>';
      if (score.training_load_penalty > 0) p += ' · Load: <span class="num">' + fmtNum(score.training_load_penalty) + '</span>';
      if (score.resp_rate_trend_penalty > 0) p += ' · Resp: <span class="num">' + fmtNum(score.resp_rate_trend_penalty) + '</span>';
      p += '</div>';
      sect.innerHTML += p;
    }
  } else {
    const avgHrv = sleeps.filter(s => s.hrv).reduce((s, x, _, a) => s + x.hrv / a.length, 0);
    const avgEff = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + getEff(x), 0) / sleeps.length) : 0;
    const fscore = Math.round(avgEff * 0.6 + (avgHrv > 0 ? 30 : 20));
    const fband = fscore >= 80 ? 'good' : fscore >= 60 ? 'moderate' : 'low';
    sect.innerHTML += '<div style="text-align:center;padding:14px 0"><div class="num" style="font-size:44px;font-weight:600;color:var(--good)">' + fscore + '</div><div style="font-size:12px;color:var(--text-faint);margin-top:4px">/100 — ' + fband + '</div></div>';
  }

  main.appendChild(sect);
}

// ===== BREATHING =====
function renderBreathing(main) {
  main.appendChild(el('div', 'header', '<h2>Breathing</h2><div class="breadcrumb">Respiratory Analysis</div>'));
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">🫁</span>Breathing Metrics'));
  sect.innerHTML += '<div class="empty"><div class="e-icon">🫁</div><p>เชื่อมต่อ COROS wellness check เพื่อดู SpO2 และ respiratory rate</p></div>';
  main.appendChild(sect);
}

// ===== JOURNAL =====
function renderJournal(main) {
  main.appendChild(el('div', 'header', '<h2>Journal</h2><div class="breadcrumb">Sleep Factors / Correlation</div>'));

  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">📝</span>Daily Journal'));

  const form = el('div');
  form.innerHTML = '<div class="field-grid">' +
    '<div class="field"><label>Date</label><input type="date" id="jDate"></div>' +
    '<div class="field"><label>Alcohol (units)</label><input type="number" id="jAlcohol" min="0" max="10" value="0"></div>' +
    '<div class="field"><label>Caffeine after 14:00</label><select id="jCaffeine"><option value="false">No</option><option value="true">Yes</option></select></div>' +
    '<div class="field"><label>Late meal</label><select id="jLateMeal"><option value="false">No</option><option value="true">Yes</option></select></div>' +
    '<div class="field"><label>Screen before bed (min)</label><input type="number" id="jScreen" min="0" max="180" value="0"></div>' +
    '<div class="field"><label>Stress (1-5)</label><input type="number" id="jStress" min="1" max="5" value="3"></div>' +
    '</div>' +
    '<button class="btn-primary" onclick="saveJournal()">Save Entry</button>';
  sect.appendChild(form);
  main.appendChild(sect);
  document.getElementById('jDate').value = new Date().toISOString().split('T')[0];
}

async function saveJournal() {
  const entry = {
    date: document.getElementById('jDate').value,
    alcohol_units: parseInt(document.getElementById('jAlcohol').value) || 0,
    caffeine_after_14: document.getElementById('jCaffeine').value === 'true' ? 1 : 0,
    late_meal: document.getElementById('jLateMeal').value === 'true' ? 1 : 0,
    screen_before_bed_min: parseInt(document.getElementById('jScreen').value) || 0,
    stress_level: parseInt(document.getElementById('jStress').value) || 3
  };

  if (!entry.date) { alert('กรุณาเลือกวันที่ก่อนบันทึก'); return; }

  try {
    const res = await fetch('/api/journal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: entry })
    });
    const data = await res.json();
    if (data.ok) {
      alert('บันทึก Journal สำหรับวันที่ ' + entry.date + ' เรียบร้อย');
      document.getElementById('jAlcohol').value = 0;
      document.getElementById('jCaffeine').value = 'false';
      document.getElementById('jLateMeal').value = 'false';
      document.getElementById('jScreen').value = 0;
      document.getElementById('jStress').value = 3;
    } else {
      alert('บันทึกไม่สำเร็จ: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('เชื่อมต่อ server ไม่ได้: ' + err.message + ' (ใช้งานได้เฉพาะตอนรัน local server ที่มี /api/journal)');
  }
}

// ===== ACTIVITIES =====
function renderActivities(main) {
  const acts = corosData.activities || [];
  main.appendChild(el('div', 'header', '<h2>Activities</h2><div class="breadcrumb">Training / Activities</div>'));

  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">🏃</span>All Activities'));
  if (acts.length === 0) {
    sect.appendChild(el('div', 'empty', '<div class="e-icon">🏃</div><p>ยังไม่มีข้อมูลกิจกรรม</p>'));
  } else {
    sect.appendChild(renderActTable(acts));
  }
  main.appendChild(sect);
}

// ===== WEEKLY =====
function renderWeekly(main) {
  const sleeps = corosData.sleep || [];
  const daily = corosData.daily || [];

  main.appendChild(el('div', 'header', '<h2>Weekly Report</h2><div class="breadcrumb">Auto-generated Summary</div>'));

  if (analysisData && analysisData.weekly_narrative) {
    const wn = analysisData.weekly_narrative;
    const sect = el('div', 'section');
    sect.appendChild(el('h3', null, '<span class="sect-icon">📊</span>สรุปสัปดาห์นี้'));

    let html = '<div style="font-size:13.5px;line-height:1.75;color:var(--text-dim)">';
    if (wn.overview) html += '<p style="color:var(--text);font-weight:500">' + wn.overview + '</p>';
    if (wn.training_trends && wn.training_trends.strain_avg) {
      html += '<p style="margin-top:10px"><strong style="color:var(--text)">Training Load — </strong><span class="num">' + wn.training_trends.strain_avg + '/21</span> (' + wn.training_trends.strain_change + '%)</p>';
    }
    if (wn.fitness) html += '<p style="margin-top:6px">' + wn.fitness + '</p>';
    if (wn.economy) html += '<p style="margin-top:6px">' + wn.economy + '</p>';
    if (wn.insights && wn.insights.length > 0) {
      html += '<div class="action-list"><div class="al-title" style="color:var(--text)">Insights</div><ul>';
      for (const i of wn.insights) html += '<li>' + i + '</li>';
      html += '</ul></div>';
    }
    if (wn.next_week && wn.next_week.length > 0) {
      html += '<div class="action-list"><div class="al-title">สัปดาห์หน้า</div><ul>';
      for (const i of wn.next_week) html += '<li>' + i + '</li>';
      html += '</ul></div>';
    }
    html += '</div>';
    sect.innerHTML += html;
    main.appendChild(sect);
  } else {
    const avgEff = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + getEff(x), 0) / sleeps.length) : 0;
    const avgDeep = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + (x.deep_sleep_pct || 0), 0) / sleeps.length) : 0;
    const avgRem = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + (x.rem_sleep_pct || 0), 0) / sleeps.length) : 0;
    const totalSteps = daily.reduce((s, x) => s + (x.steps || 0), 0);

    const sect = el('div', 'section');
    sect.appendChild(el('h3', null, '<span class="sect-icon">📊</span>Sleep Summary'));
    const strip = el('div', 'stat-strip');
    strip.innerHTML =
      '<div class="stat"><div class="s-val">' + avgEff + '%</div><div class="s-lbl">EFF</div></div>' +
      '<div class="stat"><div class="s-val">' + avgDeep + '%</div><div class="s-lbl">DEEP</div></div>' +
      '<div class="stat"><div class="s-val">' + avgRem + '%</div><div class="s-lbl">REM</div></div>' +
      '<div class="stat"><div class="s-val">' + totalSteps.toLocaleString() + '</div><div class="s-lbl">STEPS</div></div>';
    sect.appendChild(strip);
    main.appendChild(sect);
  }
}

// ===== INIT =====
loadData();
