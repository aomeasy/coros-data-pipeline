

// ===== STATE =====
const SPORT_TYPE_MAP = {
  100: 'Outdoor Run',
  101: 'Indoor Run',
  102: 'Trail Run',
  103: 'Track Run',
  // เพิ่มตามโค้ดจริงที่เจอใน data — ต้องเช็ค COROS-MCP docs ให้ครบ
};
function sportLabel(code) {
  return SPORT_TYPE_MAP[code] || ('Sport ' + code);
}


let corosData = { activities: [], sleep: [], daily: [], journals: [] };
let analysisData = null;

// ===== HELPERS =====
function fmtPace(s) { if (!s) return '-'; const m = Math.floor(s / 60); const sec = Math.floor(s % 60); return m + ':' + (sec < 10 ? '0' : '') + sec; }
function fmtDuration(s) { if (!s) return '-'; const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60); return h > 0 ? h + 'h ' + m + 'm' : m + 'm'; }
function fmtDist(m) { if (!m) return '-'; return m >= 1000 ? (m / 1000).toFixed(2) + ' km' : m + ' m'; }
function fmtDate(s) { if (!s) return '-'; return s.replace('T', ' ').substring(0, 16); }
function fmtDateShort(s) { if (!s) return '-'; return s.substring(5, 10); }
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html) e.innerHTML = html; return e; }
function fmtNum(n) { return n != null && !isNaN(n) ? (Number.isInteger(n) ? n : n.toFixed(1)) : '-'; }

// ===== DATA LOADING =====
async function loadData() {
  try {
    const res = await fetch('./data.json?t=' + Date.now());
    if (res.ok) corosData = await res.json();
  } catch (e) { console.error('Load data.json failed:', e); }

  // Fetch analysis from API
  try {
    const analysisRes = await fetch('/api/analysis');
    if (analysisRes.ok) analysisData = await analysisRes.json();
  } catch (e) { console.error('Load /api/analysis failed (local server only):', e); }

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

// ===== NARRATIVE SECTION =====
function renderNarrativeSection(main) {
  if (!analysisData || !analysisData.narrative) return;

  const narrative = analysisData.narrative;
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">📝</span>สรุปภาพรวมวันนี้'));

  let html = '<div style="font-size:13.5px;line-height:1.7;color:var(--text)">';

  // Summary
  if (narrative.summary) {
    html += '<p style="font-weight:600;margin-bottom:12px;font-size:14px">' + narrative.summary + '</p>';
  }

  // Sections
  const sections = narrative.sections || {};
  const sectionLabels = {
    recovery: '❤️ Recovery',
    sleep: '😴 การนอน',
    training: '🏋️ การซ้อม',
    health: '⚠️ สุขภาพ',
  };

  for (const [key, label] of Object.entries(sectionLabels)) {
    if (sections[key]) {
      html += '<div style="margin-top:10px"><strong style="color:var(--accent)">' + label + '</strong><br>' + sections[key] + '</div>';
    }
  }

  // Action items
  if (narrative.action_items && narrative.action_items.length > 0) {
    html += '<div style="margin-top:14px"><strong style="color:var(--success)">💡 คำแนะนำ</strong><ul style="margin-top:6px;padding-left:20px">';
    for (const item of narrative.action_items) {
      html += '<li style="margin-bottom:3px">' + item + '</li>';
    }
    html += '</ul></div>';
  }

  html += '</div>';
  sect.innerHTML += html;
  main.appendChild(sect);
}

// ===== TRAINING ANALYTICS SECTION =====
function renderTrainingSection(main) {
  if (!analysisData || !analysisData.training_analytics) return;

  const ta = analysisData.training_analytics;
  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">📊</span>Training Analytics'));

  let html = '<div style="font-size:13px;line-height:1.7">';

  // CTL/ATL/TSB
  if (ta.fitness) {
    const f = ta.fitness;
    html += '<p><strong>Fitness / Fatigue / Form:</strong><br>';
    html += 'CTL (Fitness): ' + fmtNum(f.ctl) + ' | ATL (Fatigue): ' + fmtNum(f.atl) + ' | TSB (Form): ' + (f.tsb != null ? (f.tsb >= 0 ? '+' : '') + fmtNum(f.tsb) : '-') + '<br>';
    html += 'สถานะ: ' + (f.confidence === 'stable' ? 'ข้อมูลเพียงพอ' : f.confidence === 'moderate' ? 'กำลังสะสม' : 'ข้อมูลไม่พอ');
    html += '</p>';
  }

  // Economy
  if (ta.economy && ta.economy.trend) {
    const econ = ta.economy;
    html += '<p><strong>Running Economy:</strong><br>';
    if (econ.trend === 'improving') {
      html += '✅ ดีขึ้น ' + Math.abs(econ.economy_change_pct || 0).toFixed(1) + '% — วิ่งเร็วขึ้นที่ HR เดียวกัน';
    } else if (econ.trend === 'declining') {
      html += '⚠️ แย่ลง ' + Math.abs(econ.economy_change_pct || 0).toFixed(1) + '% — อาจยังไม่ฟื้น';
    } else {
      html += 'คงที่';
    }
    html += '</p>';
  }

  // Race Readiness
  if (ta.readiness && ta.readiness.readiness_score != null) {
    const r = ta.readiness;
    html += '<p><strong>Race Readiness Score:</strong><br>';
    html += 'คะแนน: ' + fmtNum(r.readiness_score) + '/100 — ';
    if (r.band === 'ready') {
      html += '<span style="color:var(--success);font-weight:600">พร้อมแข่ง</span>';
    } else if (r.band === 'moderate') {
      html += '<span style="color:var(--warning);font-weight:600">พอใช้</span>';
    } else {
      html += '<span style="color:var(--accent);font-weight:600">ยังไม่พร้อม</span>';
    }
    html += '</p>';
  }

  // Strain-Performance
  if (ta.strain_performance && ta.strain_performance.lag_days != null) {
    const sp = ta.strain_performance;
    html += '<p><strong>Strain → Performance:</strong><br>';
    html += 'Lag: ' + sp.lag_days + ' วัน (ซ้อมหนักแล้ว performance ลดลง ' + sp.lag_days + ' วันต่อมา)';
    if (sp.correlation) {
      html += ' | correlation: ' + sp.correlation;
    }
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

  let html = '<div style="font-size:13px;line-height:1.7">';

  if (illness && illness.risk_level && illness.risk_level !== 'none') {
    const levelColor = illness.risk_level === 'high' ? 'var(--accent)' : 'var(--warning)';
    html += '<p><strong>ความเสี่ยงป่วย: <span style="color:' + levelColor + '">' + illness.risk_score + '/4 (' + illness.risk_level + ')</span></strong>';
    if (illness.signals && illness.signals.length > 0) {
      const signalLabels = {
        rhr_high: 'RHR สูงผิดปกติ',
        hrv_low: 'HRV ต่ำผิดปกติ',
        skin_temp_high: 'Skin Temp สูงผิดปกติ',
        resp_rate_high: 'Respiratory Rate สูงผิดปกติ'
      };
      html += '<br>สัญญาณ: ' + illness.signals.map(s => signalLabels[s] || s).join(', ');
    }
    html += '</p>';
  }

  if (overtraining && overtraining.risk_level && overtraining.risk_level !== 'none') {
    const levelColor = overtraining.risk_level === 'high' ? 'var(--accent)' : overtraining.risk_level === 'medium' ? 'var(--warning)' : 'var(--info)';
    html += '<p><strong>ความเสี่ยง Overtraining: <span style="color:' + levelColor + '">' + overtraining.risk_level + '</span></strong>';
    if (overtraining.flags && overtraining.flags.length > 0) {
      const flagLabels = {
        acwr_high: 'ACWR สูงต่อเนื่อง',
        hrv_declining: 'HRV แนวโน้มลด',
        recovery_low: 'Recovery ต่ำติดต่อกัน'
      };
      html += '<br>สัญญาณ: ' + overtraining.flags.map(f => flagLabels[f] || f).join(', ');
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

  let html = '<ul style="padding-left:20px;font-size:13px;line-height:1.8">';
  for (const rec of recs) {
    const priorityColor = rec.priority === 'high' ? 'var(--accent)' : rec.priority === 'medium' ? 'var(--warning)' : 'var(--info)';
    html += '<li style="margin-bottom:6px"><span style="color:' + priorityColor + ';font-size:10px;text-transform:uppercase;font-weight:600">[' + rec.priority + ']</span> ' + rec.message + '</li>';
  }
  html += '</ul>';
  sect.innerHTML += html;
  main.appendChild(sect);
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

  // Narrative section (Phase 6) — บนสุด
  renderRecoveryRing(main);
  renderNarrativeSection(main);

  // Cards
  const cards = el('div', 'cards');
  cards.appendChild(card('Total Distance', (totalDist / 1000).toFixed(1), 'km'));
  cards.appendChild(card('Avg Pace', fmtPace(avgPace), '/km'));
  cards.appendChild(card('Total Steps', totalSteps.toLocaleString(), ''));
  cards.appendChild(card('Sleep Efficiency', avgEff + '%', 'average'));
  cards.appendChild(card('Avg Stress', avgStress, ''));
  cards.appendChild(card('Activities', acts.length, 'total'));

 

  // Add Strain card if available
  if (analysisData && analysisData.latest_strain) {
    const ls = analysisData.latest_strain;
    const strainCard = el('div', 'card');
    strainCard.innerHTML = '<div class="label">Strain</div><div class="val">' + (ls.day_strain != null ? ls.day_strain.toFixed(1) : '-') + '<span style="font-size:12px;color:var(--muted)"> /21</span></div>';
    cards.appendChild(strainCard);
  }

  main.appendChild(cards);

  // Training Analytics section
  renderTrainingSection(main);

  // Health Risk section
  renderHealthRiskSection(main);

  // Coach Recommendations
  renderCoachSection(main);

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
    acts.map(a => '<tr><td>' + fmtDate(a.start_time) + '</td><td><span class="badge">' + sportLabel(a.sport_type) + '</span></td>' + fmtDist(a.distance_m) + '</td><td>' + fmtDuration(a.duration_s) + '</td><td>' + fmtPace(a.avg_pace_s) + ' /km</td><td>' + (a.avg_hr || '-') + ' bpm</td></tr>').join('') +
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

function renderRecoveryRing(main) {
  if (!analysisData || !analysisData.recovery_score) return;
  const rs = analysisData.recovery_score;
  const pct = rs.recovery_score || 0;
  const bandClass = rs.band === 'green' ? 'status-green' : rs.band === 'yellow' ? 'status-yellow' : 'status-red';
  const r = 78, circumference = 2 * Math.PI * r;
  const offset = circumference - (pct / 100) * circumference;

  const sect = el('div', 'section recovery-ring-section');
  sect.innerHTML =
    '<div class="ring-wrap"><svg width="180" height="180" viewBox="0 0 180 180">' +
    '<circle class="ring-track" cx="90" cy="90" r="' + r + '"></circle>' +
    '<circle class="ring-progress ' + bandClass + '" cx="90" cy="90" r="' + r +
      '" stroke-dasharray="' + circumference + '" stroke-dashoffset="' + offset + '"></circle>' +
    '</svg><div class="ring-center"><div class="pct">' + fmtNum(pct) + '%</div><div class="lbl">Recovery</div></div></div>' +
    '<div class="ring-status-text ' + bandClass + '">' + rs.band.toUpperCase() + '</div>';
  main.appendChild(sect);
}

// ===== RECOVERY =====
function renderRecovery(main) {
  const sleeps = corosData.sleep || [];
  main.appendChild(el('div', 'header', '<div><h2>Recovery</h2><div class="breadcrumb">Recovery Analysis</div></div>'));

  // Use API data if available
  const score = analysisData && analysisData.recovery_score ? analysisData.recovery_score : null;

  const sect = el('div', 'section');
  sect.appendChild(el('h3', null, '<span class="sect-icon">❤️</span>Recovery Score'));

  if (score) {
    const bandColor = score.band === 'green' ? '#10b981' : score.band === 'yellow' ? '#f59e0b' : '#e94560';
    sect.innerHTML += '<div style="text-align:center;padding:20px"><div style="font-size:48px;font-weight:800;color:' + bandColor + '">' + fmtNum(score.recovery_score) + '</div><div style="font-size:13px;color:var(--muted);margin-top:4px">/100 — ' + score.band + '</div></div>';

    if (score.components) {
      const comp = score.components;
      const grid = el('div', 'grid-2');
      grid.appendChild(el('div', 'section', '<h3>❤️ HRV Score</h3><div style="font-size:24px;font-weight:700">' + fmtNum(comp.hrv_score) + '</div><div style="font-size:11px;color:var(--muted)">Weight 30%</div>'));
      grid.appendChild(el('div', 'section', '<h3>💓 RHR Score</h3><div style="font-size:24px;font-weight:700">' + fmtNum(comp.rhr_score) + '</div><div style="font-size:11px;color:var(--muted)">Weight 20%</div>'));
      grid.appendChild(el('div', 'section', '<h3>😴 Sleep Perf</h3><div style="font-size:24px;font-weight:700">' + fmtNum(comp.sleep_performance) + '</div><div style="font-size:11px;color:var(--muted)">Weight 25%</div>'));
      grid.appendChild(el('div', 'section', '<h3>🛏️ Sleep Eff</h3><div style="font-size:24px;font-weight:700">' + fmtNum(comp.sleep_efficiency) + '</div><div style="font-size:11px;color:var(--muted)">Weight 15%</div>'));
      sect.appendChild(grid);
    }

    if (score.penalty_applied > 0) {
      sect.innerHTML += '<div style="margin-top:12px;font-size:12px;color:var(--muted)">Penalty: ' + fmtNum(score.penalty_applied);
      if (score.training_load_penalty > 0) sect.innerHTML += ' | Training Load: ' + fmtNum(score.training_load_penalty);
      if (score.resp_rate_trend_penalty > 0) sect.innerHTML += ' | Resp Trend: ' + fmtNum(score.resp_rate_trend_penalty);
      sect.innerHTML += '</div>';
    }
  } else {
    // Fallback
    const avgHrv = sleeps.filter(s => s.hrv).reduce((s, x, _, a) => s + x.hrv / a.length, 0);
    const avgRhr = sleeps.filter(s => s.resting_hr).reduce((s, x, _, a) => s + x.resting_hr / a.length, 0);
    const avgEff = sleeps.length ? Math.round(sleeps.reduce((s, x) => s + getEff(x), 0) / sleeps.length) : 0;
    const fscore = Math.round(avgEff * 0.6 + (avgHrv > 0 ? 30 : 20));
    const fband = fscore >= 80 ? 'good' : fscore >= 60 ? 'moderate' : 'low';
    sect.innerHTML += '<div style="text-align:center;padding:20px"><div style="font-size:48px;font-weight:800;color:#10b981">' + fscore + '</div><div style="font-size:13px;color:var(--muted);margin-top:4px">/100 — ' + fband + '</div></div>';
  }

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

  if (!entry.date) {
    alert('กรุณาเลือกวันที่ก่อนบันทึก');
    return;
  }

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

  // Use weekly_narrative from API if available
  if (analysisData && analysisData.weekly_narrative) {
    const wn = analysisData.weekly_narrative;
    const sect = el('div', 'section');
    sect.appendChild(el('h3', null, '<span class="sect-icon">📊</span>สรุปสัปดาห์นี้'));

    let html = '<div style="font-size:13.5px;line-height:1.7">';
    if (wn.overview) html += '<p><strong>' + wn.overview + '</strong></p>';
    if (wn.training_trends && wn.training_trends.strain_avg) {
      html += '<p>📈 Training Load เฉลี่ย ' + wn.training_trends.strain_avg + '/21 — ' + wn.training_trends.strain_change + '%</p>';
    }
    if (wn.fitness) html += '<p>💪 ' + wn.fitness + '</p>';
    if (wn.economy) html += '<p>🏃 ' + wn.economy + '</p>';
    if (wn.insights && wn.insights.length > 0) {
      html += '<p><strong>🔍 Insights:</strong></p><ul style="padding-left:20px">';
      for (const i of wn.insights) html += '<li>' + i + '</li>';
      html += '</ul>';
    }
    if (wn.next_week && wn.next_week.length > 0) {
      html += '<p><strong>💡 สัปดาห์หน้า:</strong></p><ul style="padding-left:20px">';
      for (const i of wn.next_week) html += '<li>' + i + '</li>';
      html += '</ul>';
    }
    html += '</div>';
    sect.innerHTML += html;
    main.appendChild(sect);
  } else {
    // Fallback
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
}

// ===== INIT =====
loadData();
